"""Verify that a FAISS index and a database of embeddings describe the same space.

Every consumer of the ANN index - the API server and the similarity precompute job -
searches vectors produced by one specific sentence-transformer model. Nothing about a
vector says which model produced it, so an index built before a model change looks
entirely valid to FAISS and returns confident, wrongly ranked neighbours instead of an
error. Comparing dimensions does not catch this, because different models share
dimensions: this deployment's current and candidate models are both 384.

`build-ann-index.py` records the model name in a sidecar JSON next to the index. These
helpers are the readers of that record.

The sidecar also records `id_source`. Readers resolve hits by `video_embeddings.ann_id`
(ADR-0006), so an index whose ids are rowids would return the wrong videos and is refused.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from data.ann_ids import ANN_ID_SOURCE


def resolve_embedding_space(db: sqlite3.Connection) -> tuple[int, str]:
    """Return the single (embedding_dim, model_name) present in video_embeddings.

    More than one pair means vectors from two models share the table. They are not
    comparable, so there is no single space to build, precompute or serve against, and
    the caller must fail rather than pick whichever row comes first. Because
    `build-video-embeddings.py` only fills in missing rows unless `--force` is passed,
    changing the model without a full rebuild is an easy mistake to make; this turns it
    into a clean failure instead of a silent quality regression.

    Rows are read positionally, so the caller's row factory does not matter.

    :param db: Connection to the database holding video_embeddings.
    :returns: The embedding dimension and model name shared by every row.
    :raises RuntimeError: If the table is empty or holds more than one embedding space.
    """
    rows = db.execute(
        "SELECT model_name, embedding_dim, COUNT(*) AS n FROM video_embeddings"
        " GROUP BY model_name, embedding_dim"
    ).fetchall()
    if not rows:
        raise RuntimeError("No embeddings found in database.")
    if len(rows) > 1:
        detail = ", ".join(f"{row[0]} (dim={row[1]}, rows={row[2]})" for row in rows)
        raise RuntimeError(
            "video_embeddings holds more than one embedding space: "
            f"{detail}. Vectors from different models are not comparable. "
            "Re-run build-video-embeddings.py with --force so every row uses one "
            "model, then rebuild the ANN index."
        )
    return int(rows[0][1]), str(rows[0][0])


def assert_index_matches_embeddings(
    index_path: Path, index: Any, dim: int, model_name: str
) -> None:
    """Raise unless the index at index_path was built from this embedding space.

    A missing or unreadable sidecar is a failure rather than a fallback to a
    dimension-only check: silently accepting an unverifiable index would restore the bug
    this function exists to close, and the file is written by every index build.

    `index` is a faiss.Index. It is typed loosely so this module does not import faiss
    for one attribute read.
    """
    meta_path = Path(f"{index_path}.json")
    if not meta_path.exists():
        raise RuntimeError(
            f"Index metadata {meta_path} is missing; rebuild the index with "
            "build-ann-index.py so its embedding space can be verified."
        )
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Index metadata {meta_path} is unreadable: {exc}") from exc

    index_model = str(meta.get("model_name") or "")
    index_dim = meta.get("embedding_dim")
    if index_model != model_name:
        raise RuntimeError(
            f"Index was built from model {index_model or '<unset>'} but video_embeddings "
            f"now holds {model_name}. Rebuild the index with build-ann-index.py."
        )
    index_id_source = str(meta.get("id_source") or "")
    if index_id_source != ANN_ID_SOURCE:
        raise RuntimeError(
            f"Index ids come from {index_id_source or '<unset>'} but readers resolve "
            f"{ANN_ID_SOURCE}. Rebuild the index with build-ann-index.py."
        )
    if index_dim is not None and int(index_dim) != dim:
        raise RuntimeError(
            f"Index metadata dimension {index_dim} does not match database dimension {dim}"
        )
    if index.d != dim:
        raise RuntimeError(
            f"Index dimension {index.d} does not match database dimension {dim}"
        )
    logging.info(
        "index verified model=%s dim=%d built_at=%s",
        index_model,
        dim,
        meta.get("built_at"),
    )
