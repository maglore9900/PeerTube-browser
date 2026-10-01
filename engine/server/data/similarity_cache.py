"""Provide similarity cache runtime helpers."""

from __future__ import annotations

import os
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable

# One neighbour in similarity_sources.neighbours: its video_keys.key (int32) and score (float32), little-endian.
# Neighbours are packed in rank order, so a neighbour's rank is its position + 1.
NEIGHBOUR = struct.Struct("<if")
# Pairs per row-value IN lookup, as data/metadata.py chunks its pair lookups.
KEY_CHUNK = 450


def ensure_similarity_schema(conn: sqlite3.Connection) -> None:
    """Create the compact similarity cache tables if missing; raise RuntimeError, writing nothing, on a legacy-layout file."""
    if is_legacy_similarity_cache(conn):
        path = conn.execute("SELECT file FROM pragma_database_list WHERE name = 'main'").fetchone()[0]
        raise RuntimeError(
            f"{path} holds the legacy similarity cache layout. Convert it with "
            f"migrate-similarity-cache.py --in {path} --out <new file>, then move the new file into place."
        )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS video_keys (
          key INTEGER PRIMARY KEY,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          UNIQUE (video_id, instance_domain)
        );
        CREATE INDEX IF NOT EXISTS video_keys_instance_domain_idx
          ON video_keys (instance_domain);
        CREATE TABLE IF NOT EXISTS similarity_sources (
          source_key INTEGER PRIMARY KEY,
          computed_at INTEGER NOT NULL,
          neighbours BLOB NOT NULL
        );
        """
    )


def is_legacy_similarity_cache(conn: sqlite3.Connection) -> bool:
    """Return True when the file holds the pre-compact layout, recognised by its similarity_items table."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'similarity_items'"
    ).fetchone()
    return row is not None


def pack_neighbours(pairs: Iterable[tuple[int, float]]) -> bytes:
    """Pack (key, score) pairs, already in rank order, into a neighbours blob."""
    return b"".join(NEIGHBOUR.pack(key, score) for key, score in pairs)


def unpack_neighbours(blob: bytes, limit: int | None = None) -> list[tuple[int, float]]:
    """Unpack a neighbours blob into (key, score) pairs in rank order, the first `limit` only when given."""
    if limit is not None:
        blob = blob[: max(limit, 0) * NEIGHBOUR.size]
    return list(NEIGHBOUR.iter_unpack(blob))


def intern_video_keys(
    conn: sqlite3.Connection, pairs: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], int]:
    """Return the video_keys key of every (video_id, instance_domain) pair, inserting the pairs not yet keyed."""
    unique = list(dict.fromkeys(pairs))
    conn.executemany(
        "INSERT OR IGNORE INTO video_keys (video_id, instance_domain) VALUES (?, ?)", unique
    )
    keys: dict[tuple[str, str], int] = {}
    for start in range(0, len(unique), KEY_CHUNK):
        chunk = unique[start : start + KEY_CHUNK]
        values = ", ".join(["(?, ?)"] * len(chunk))
        params = [value for pair in chunk for value in pair]
        for key, video_id, instance_domain in conn.execute(
            f"""
            SELECT key, video_id, instance_domain FROM video_keys
            WHERE (video_id, instance_domain) IN (VALUES {values})
            """,
            params,
        ):
            keys[(video_id, instance_domain)] = key
    return keys


def _pair(entry: dict[str, Any]) -> tuple[str, str]:
    """Return the (video_id, instance_domain) key text of a source or item dict."""
    return (entry.get("video_id"), entry.get("instance_domain") or "")


def write_similarities(
    conn: sqlite3.Connection,
    entries: list[tuple[dict[str, Any], list[dict[str, Any]], int]],
) -> None:
    """Upsert (source, items, computed_at) entries without committing; items are packed in `rank` order."""
    if not entries:
        return
    keys = intern_video_keys(
        conn,
        (pair for source, items, _ in entries for pair in [_pair(source), *map(_pair, items)]),
    )
    rows = []
    for source, items, computed_at in entries:
        ranked = sorted(items, key=lambda item: item["rank"])
        neighbours = pack_neighbours((keys[_pair(item)], item["score"]) for item in ranked)
        rows.append((keys[_pair(source)], computed_at, neighbours))
    conn.executemany(
        """
        INSERT INTO similarity_sources (source_key, computed_at, neighbours)
        VALUES (?, ?, ?)
        ON CONFLICT(source_key)
        DO UPDATE SET computed_at = excluded.computed_at, neighbours = excluded.neighbours
        """,
        rows,
    )


def build_marker_path(cache_path: str | Path) -> Path:
    """Return the build marker path for a similarity cache file: `<cache>.building` (ADR-0008)."""
    path = Path(cache_path)
    return path.with_name(path.name + ".building")


def build_marker_live_pid(content: bytes) -> int | None:
    """Return the PID in a build marker's content when that process is alive; None when the content is unparseable or the PID is dead."""
    text = content.strip()
    # bytes.isdigit is ASCII-only, so the signs, spaces and underscores int() would accept are refused.
    if not text.isdigit():
        return None
    pid = int(text)
    # os.kill(0, 0) signals our own process group and succeeds, so 0 would read as a live updater.
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return None
    except PermissionError:
        return pid
    return pid


def build_marker_blocks_writes(cache_path: str | Path) -> bool:
    """Return True while the cache's build marker exists and holds a live PID."""
    try:
        content = build_marker_path(cache_path).read_bytes()
    except FileNotFoundError:
        return False
    return build_marker_live_pid(content) is not None


def fetch_cached_similarities(
    conn: sqlite3.Connection | None, source: dict[str, Any], limit: int
) -> list[dict[str, Any]]:
    """Fetch cached similar items for a source video."""
    if conn is None:
        return []
    try:
        row = conn.execute(
            """
            SELECT s.neighbours
            FROM similarity_sources s
            JOIN video_keys k ON k.key = s.source_key
            WHERE k.video_id = ? AND k.instance_domain = ?
            """,
            _pair(source),
        ).fetchone()
        if row is None:
            return []
        pairs = unpack_neighbours(row[0], limit)
        if not pairs:
            return []
        placeholders = ", ".join("?" for _ in pairs)
        names = {
            key: (video_id, instance_domain)
            for key, video_id, instance_domain in conn.execute(
                f"SELECT key, video_id, instance_domain FROM video_keys WHERE key IN ({placeholders})",
                [key for key, _ in pairs],
            )
        }
        return [
            {
                "video_id": names[key][0],
                "instance_domain": names[key][1],
                "score": score,
                "rank": position,
            }
            for position, (key, score) in enumerate(pairs, start=1)
        ]
    except sqlite3.Error:
        return []


def has_cached_similarities(conn: sqlite3.Connection, source: dict[str, Any]) -> bool:
    """Return True if the source video already has cached similars."""
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM similarity_sources s
            JOIN video_keys k ON k.key = s.source_key
            WHERE k.video_id = ? AND k.instance_domain = ? AND length(s.neighbours) > 0
            """,
            _pair(source),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def store_similarity_cache(
    conn: sqlite3.Connection,
    source: dict[str, Any],
    items: list[dict[str, Any]],
    computed_at: int,
) -> None:
    """Persist similar items for a source video, replacing any earlier entry."""
    write_similarities(conn, [(source, items, computed_at)])
    conn.commit()
