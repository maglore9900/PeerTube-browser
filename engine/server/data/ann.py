"""Provide ann runtime helpers."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

try:
    import faiss  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "faiss is required. Install faiss-cpu in your Python environment."
    ) from exc

from data.embeddings import normalize_vector
from data.metadata import fetch_metadata


def compute_similar_items(server: Any, seed: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """Compute similar items using ANN, mirroring the precompute script behavior."""
    vector = seed["embedding"]
    if server.normalize_queries:
        vector = normalize_vector(vector)
    search_limit = max(limit + 1, limit)
    configured_limit = int(getattr(server, "similarity_search_limit", 0) or 0)
    if configured_limit > 0:
        search_limit = max(search_limit, configured_limit)
    logging.info(
        "[similar-server] ann_search nprobe=%s search_limit=%d configured_limit=%d",
        getattr(getattr(server, "index", None), "nprobe", None),
        search_limit,
        configured_limit,
    )
    with server.index_lock:
        scores, ids = server.index.search(vector.reshape(1, -1), search_limit)
    ann_ids = [int(item) for item in ids[0] if int(item) > 0]
    logging.info(
        "[similar-server] ann_ids=%d search_limit=%d",
        len(ann_ids),
        search_limit,
    )
    with server.db_lock:
        metadata = fetch_metadata(
            server.db,
            ann_ids,
            error_threshold=getattr(server, "video_error_threshold", None),
        )
    logging.info("[similar-server] ann_metadata=%d", len(metadata))
    source_author_key = None
    if server.similarity_exclude_source_author:
        source_author_key = _author_key(
            seed.get("channel_id") or seed.get("meta", {}).get("channel_id"),
            seed.get("instance_domain") or seed.get("meta", {}).get("instance_domain"),
        )
    author_limit = server.similarity_max_per_author
    author_counts: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for score, ann_id in zip(scores[0], ids[0]):
        ann_id_int = int(ann_id)
        if ann_id_int == seed["ann_id"]:
            continue
        meta = metadata.get(ann_id_int)
        if not meta:
            continue
        author_key = _author_key(meta.get("channel_id"), meta.get("instance_domain"))
        if source_author_key and author_key == source_author_key:
            continue
        if author_limit > 0 and author_key:
            if author_counts.get(author_key, 0) >= author_limit:
                continue
        items.append(
            {
                "video_id": meta["video_id"],
                "instance_domain": meta["instance_domain"],
                "score": float(score),
            }
        )
        if author_limit > 0 and author_key:
            author_counts[author_key] = author_counts.get(author_key, 0) + 1
        if len(items) >= limit:
            break
    logging.info("[similar-server] ann_candidates=%d limit=%d", len(items), limit)
    return [{**item, "rank": index} for index, item in enumerate(items, start=1)]


def search_similar_above(
    server: Any,
    seed: dict[str, Any],
    nprobe: int,
    search_limit: int,
    min_score: float,
) -> tuple[list[dict[str, Any]], int | None]:
    """ANN-search the seed at a temporary nprobe; return hits scoring >= min_score and the restored nprobe.

    The nprobe is set, searched and restored inside one index_lock hold, so every other search on the shared index sees the startup value. Hits come back in score order with no per-author cap: the caller caps authors over its merged pool.
    """
    vector = seed["embedding"]
    if server.normalize_queries:
        vector = normalize_vector(vector)
    with server.index_lock:
        previous = get_nprobe(server.index)
        try:
            if previous is not None:
                apply_nprobe(server.index, nprobe)
            scores, ids = server.index.search(vector.reshape(1, -1), search_limit)
        finally:
            if previous is not None:
                apply_nprobe(server.index, previous)
        restored = get_nprobe(server.index)
    seed_ann_id = seed.get("ann_id")
    kept = [
        (float(score), int(ann_id))
        for score, ann_id in zip(scores[0], ids[0])
        if int(ann_id) > 0 and int(ann_id) != seed_ann_id and float(score) >= min_score
    ]
    logging.info(
        "[similar-server] ann_fallback nprobe=%d search_limit=%d floor=%.2f hits=%d restored_nprobe=%s",
        nprobe,
        search_limit,
        min_score,
        len(kept),
        restored,
    )
    if not kept:
        return [], restored
    with server.db_lock:
        metadata = fetch_metadata(
            server.db,
            [ann_id for _, ann_id in kept],
            error_threshold=getattr(server, "video_error_threshold", None),
        )
    items: list[dict[str, Any]] = []
    for score, ann_id in kept:
        meta = metadata.get(ann_id)
        if not meta:
            continue
        items.append({"video_id": meta["video_id"], "instance_domain": meta["instance_domain"], "score": score})
    return items, restored


def search_index(
    index: faiss.Index,
    vector: np.ndarray,
    limit: int,
    exclude_ann_id: int | None,
) -> tuple[list[int], list[float]]:
    """Search the ANN index and optionally exclude an ANN id."""
    if vector.ndim != 1:
        raise ValueError("Query vector must be 1D")
    k = max(limit + 5, limit)
    scores, ids = index.search(vector.reshape(1, -1), k)
    scores_list = scores[0].tolist()
    ids_list = ids[0].tolist()
    filtered_ids: list[int] = []
    filtered_scores: list[float] = []
    for score, ann_id in zip(scores_list, ids_list):
        if ann_id < 0:
            continue
        if exclude_ann_id is not None and ann_id == exclude_ann_id:
            continue
        if ann_id in filtered_ids:
            continue
        filtered_ids.append(ann_id)
        filtered_scores.append(float(score))
        if len(filtered_ids) >= limit:
            break
    return filtered_ids, filtered_scores


def _extract_ivf(index: faiss.Index) -> Any:
    """Return the IVF index holding nprobe, or None when the index has none."""
    if not hasattr(faiss, "extract_index_ivf"):
        return None
    try:
        return faiss.extract_index_ivf(index)
    except Exception:  # pragma: no cover
        return None


def get_nprobe(index: faiss.Index) -> int | None:
    """Read nprobe from the IVF index the setter writes, or None without one."""
    ivf_index = _extract_ivf(index)
    return int(ivf_index.nprobe) if ivf_index is not None else None


def apply_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on a supported index, without logging."""
    ivf_index = _extract_ivf(index)
    if ivf_index is not None:
        ivf_index.nprobe = nprobe
    if hasattr(index, "nprobe"):
        index.nprobe = nprobe
    elif hasattr(index, "index") and hasattr(index.index, "nprobe"):
        index.index.nprobe = nprobe


def set_nprobe(index: faiss.Index, nprobe: int) -> None:
    """Set FAISS nprobe on a supported index and log it (startup)."""
    apply_nprobe(index, nprobe)
    ivf_index = _extract_ivf(index)
    logging.info(
        "[similar-server] ann_nprobe_configured=%d index_type=%s ivf_type=%s",
        nprobe,
        type(index).__name__,
        type(ivf_index).__name__ if ivf_index is not None else None,
    )


def _author_key(channel_id: str | None, instance_domain: str | None) -> str | None:
    """Handle author key."""
    if not channel_id:
        return None
    return f"{channel_id}::{instance_domain or ''}"
