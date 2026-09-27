"""Internal read endpoints for Client -> Engine API-only contract."""
from __future__ import annotations

from typing import Any

import numpy as np

from data.embeddings import fetch_embeddings_by_ids, fetch_seed_embedding
from data.metadata import fetch_metadata_by_ids, fetch_metadata_by_uuids, uuid_key
from http_utils import read_json_body, respond_json
from recommendations.dislike_profile import compute_centroids
from server_config import DISLIKE_MAX_ENTRIES


def _like_key(entry: dict[str, Any]) -> str:
    """Handle like key."""
    return f"{entry.get('video_id') or ''}::{entry.get('instance_domain') or ''}"


def _stripped(value: Any) -> str | None:
    """Return a non-empty stripped string, or None."""
    return (value.strip() or None) if isinstance(value, str) else None


def _parse_entries(body: Any) -> list[dict[str, str]] | None:
    """Return the distinct well-formed (video_id, instance_domain) entries of a body.

    :returns: None when `entries` is not a list; malformed items are skipped.
    """
    raw_entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(raw_entries, list):
        return None
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        video_id = _stripped(raw.get("video_id"))
        instance = _stripped(raw.get("instance_domain"))
        if video_id is None or instance is None:
            continue
        entry = {"video_id": video_id, "instance_domain": instance}
        key = _like_key(entry)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def _parse_metadata_entries(body: Any) -> list[tuple[str, dict[str, str]]] | None:
    """Return the distinct well-formed metadata entries of a body, tagged "id" or "uuid", in order.

    An item with a valid video_id is id-keyed even if it also carries video_uuid; duplicates are dropped per form, keeping the first.
    :returns: None when `entries` is not a list; malformed items are skipped.
    """
    raw_entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(raw_entries, list):
        return None
    entries: list[tuple[str, dict[str, str]]] = []
    # Tagged with the form because id and uuid keys are both `x::y` strings and could collide.
    seen: set[tuple[str, str]] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        instance = _stripped(raw.get("instance_domain"))
        if instance is None:
            continue
        video_id = _stripped(raw.get("video_id"))
        video_uuid = _stripped(raw.get("video_uuid"))
        if video_id is not None:
            form, entry = "id", {"video_id": video_id, "instance_domain": instance}
            key = _like_key(entry)
        elif video_uuid is not None:
            form, entry = "uuid", {"video_uuid": video_uuid, "instance_domain": instance}
            key = uuid_key(entry)
        else:
            continue
        if (form, key) in seen:
            continue
        seen.add((form, key))
        entries.append((form, entry))
    return entries


def handle_internal_video_resolve(handler: Any, server: Any) -> bool:
    """Resolve canonical video identity by video_id/uuid (+ optional host)."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    video_id_raw = body.get("video_id")
    host_raw = body.get("host")
    uuid_raw = body.get("uuid")

    video_id = video_id_raw.strip() if isinstance(video_id_raw, str) else None
    host = host_raw.strip() if isinstance(host_raw, str) else None
    uuid = uuid_raw.strip() if isinstance(uuid_raw, str) else None

    if not video_id and not uuid:
        respond_json(handler, 400, {"error": "Missing video_id or uuid"})
        return True

    with server.db_lock:
        seed = fetch_seed_embedding(server.db, video_id, host, uuid)

    if not seed:
        respond_json(handler, 404, {"error": "Video not found"})
        return True

    respond_json(
        handler,
        200,
        {
            "ok": True,
            "video": {
                "video_id": seed.get("video_id"),
                "video_uuid": seed.get("video_uuid"),
                "instance_domain": seed.get("instance_domain"),
                "channel_id": seed.get("channel_id"),
                "title": seed.get("title"),
            },
        },
    )
    return True


def handle_internal_videos_metadata(handler: Any, server: Any) -> bool:
    """Return metadata rows for (video_id, instance_domain) and (video_uuid, instance_domain) entries.

    Both forms are answered under one db_lock hold; each video appears once, at its first matching entry.
    """
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    entries = _parse_metadata_entries(body)
    if entries is None:
        respond_json(handler, 400, {"error": "Missing entries"})
        return True

    if not entries:
        respond_json(handler, 200, {"ok": True, "count": 0, "rows": []})
        return True

    id_entries = [entry for form, entry in entries if form == "id"]
    uuid_entries = [entry for form, entry in entries if form == "uuid"]
    error_threshold = getattr(server, "video_error_threshold", None)
    by_id: dict[str, dict[str, Any]] = {}
    by_uuid: dict[str, dict[str, Any]] = {}
    with server.db_lock:
        if id_entries:
            by_id = fetch_metadata_by_ids(server.db, id_entries, error_threshold=error_threshold)
        if uuid_entries:
            by_uuid = fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=error_threshold)

    rows: list[dict[str, Any]] = []
    # Keyed on the returned row, not the entry, so a video reached by both forms is emitted once.
    emitted: set[str] = set()
    for form, entry in entries:
        row = by_id.get(_like_key(entry)) if form == "id" else by_uuid.get(uuid_key(entry))
        if not isinstance(row, dict) or _like_key(row) in emitted:
            continue
        emitted.add(_like_key(row))
        rows.append(row)

    respond_json(handler, 200, {"ok": True, "count": len(rows), "rows": rows})
    return True


def handle_internal_dislike_centroids(handler: Any, server: Any) -> bool:
    """Cluster a visitor's disliked videos into taste centroids; nothing is stored."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    entries = _parse_entries(body)
    if entries is None:
        respond_json(handler, 400, {"error": "Missing entries"})
        return True
    if len(entries) > DISLIKE_MAX_ENTRIES:
        respond_json(handler, 400, {"error": f"At most {DISLIKE_MAX_ENTRIES} entries"})
        return True

    with server.db_lock:
        embeddings = fetch_embeddings_by_ids(server.db, entries)
    vectors = [embeddings[_like_key(entry)] for entry in entries if _like_key(entry) in embeddings]
    centroids = compute_centroids(np.array(vectors)) if vectors else np.empty((0, 0))
    respond_json(
        handler,
        200,
        {
            "ok": True,
            "space": getattr(server, "embeddings_model", None),
            "centroids": [[round(float(x), 6) for x in row] for row in centroids],
        },
    )
    return True
