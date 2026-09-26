"""A profile's dislikes, and the taste centroids the Engine derives from them.

A dislike is private: it shapes only this profile's feeds and publishes nothing. The
centroids are stored beside the dislikes and replaced whenever the set changes, so a feed
request carries them without the Client or the Engine recomputing anything.

The write functions do not commit: each runs inside the caller's transaction, which also
holds the like it replaces.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .time_utils import now_ms

MAX_DISLIKES = 1000


class DislikeLimitReached(Exception):
    """The profile already holds `MAX_DISLIKES` dislikes."""


def dislike_entries(conn: sqlite3.Connection, profile_id: str) -> list[dict[str, str]]:
    """Return the profile's disliked videos as `(video_id, instance_domain)` entries."""
    rows = conn.execute(
        "SELECT video_id, instance_domain FROM dislikes WHERE profile_id = ?", (profile_id,)
    ).fetchall()
    return [{"video_id": row["video_id"], "instance_domain": row["instance_domain"]} for row in rows]


def is_disliked(conn: sqlite3.Connection, profile_id: str, video_id: str, instance_domain: str) -> bool:
    """Return whether the profile dislikes one video."""
    return conn.execute(
        "SELECT 1 FROM dislikes WHERE profile_id = ? AND video_id = ? AND instance_domain = ?",
        (profile_id, video_id, instance_domain),
    ).fetchone() is not None


def write_dislike(conn: sqlite3.Connection, profile_id: str, video: dict[str, Any],
                  centroids: dict[str, Any] | None) -> None:
    """Store a dislike and the centroids of the set that now includes it."""
    conn.execute(
        "INSERT OR IGNORE INTO dislikes (profile_id, video_id, instance_domain, video_uuid, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (profile_id, video["video_id"], video["instance_domain"], video["video_uuid"], now_ms()),
    )
    _store_centroids(conn, profile_id, centroids)


def delete_dislike(conn: sqlite3.Connection, profile_id: str, video_id: str, instance_domain: str,
                   centroids: dict[str, Any] | None) -> None:
    """Remove a dislike and store the centroids of the set without it."""
    conn.execute(
        "DELETE FROM dislikes WHERE profile_id = ? AND video_id = ? AND instance_domain = ?",
        (profile_id, video_id, instance_domain),
    )
    _store_centroids(conn, profile_id, centroids)


def load_disliked_keys(conn: sqlite3.Connection, profile_id: str) -> set[tuple[str, str]]:
    """Return the profile's disliked videos as `(video_id, instance_domain)` pairs."""
    return {(e["video_id"], e["instance_domain"]) for e in dislike_entries(conn, profile_id)}


def filter_disliked(rows: list[dict[str, Any]], keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    """Drop every row that is a disliked video."""
    return [row for row in rows
            if (str(row.get("video_id") or ""), str(row.get("instance_domain") or "")) not in keys]


def load_centroids(conn: sqlite3.Connection, profile_id: str) -> dict[str, Any] | None:
    """Return the profile's centroids as `{"space", "vectors"}`, or None when it has none."""
    row = conn.execute(
        "SELECT space, centroids FROM dislike_profiles WHERE profile_id = ?", (profile_id,)
    ).fetchone()
    if row is None:
        return None
    return {"space": row["space"], "vectors": json.loads(row["centroids"])}


def _store_centroids(conn: sqlite3.Connection, profile_id: str, centroids: dict[str, Any] | None) -> None:
    if centroids is None:
        conn.execute("DELETE FROM dislike_profiles WHERE profile_id = ?", (profile_id,))
        return
    conn.execute(
        "INSERT OR REPLACE INTO dislike_profiles (profile_id, space, centroids, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (profile_id, centroids["space"], json.dumps(centroids["vectors"]), now_ms()),
    )
