"""Client-owned users/likes persistence helpers."""
from __future__ import annotations

import sqlite3
from typing import Any

from .time_utils import now_ms


def ensure_user_schema(conn: sqlite3.Connection) -> None:
    """Create the users, likes, like generation, profile, block, follow, dislike and analytics event tables if missing."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          username TEXT,
          created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS likes (
          user_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          video_uuid TEXT,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (user_id, video_id, instance_domain)
        );
        CREATE INDEX IF NOT EXISTS likes_user_updated_idx
          ON likes (user_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS profiles (
          profile_id TEXT PRIMARY KEY,
          key_hash TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL,
          last_seen_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS blocks (
          profile_id TEXT NOT NULL,
          kind TEXT NOT NULL CHECK (kind IN ('channel', 'account')),
          instance_domain TEXT NOT NULL DEFAULT '',
          channel_id TEXT NOT NULL DEFAULT '',
          account_url TEXT NOT NULL DEFAULT '',
          label TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          PRIMARY KEY (profile_id, kind, instance_domain, channel_id, account_url)
        );
        CREATE TABLE IF NOT EXISTS follows (
          profile_id TEXT NOT NULL,
          kind TEXT NOT NULL CHECK (kind IN ('channel', 'account')),
          instance_domain TEXT NOT NULL DEFAULT '',
          channel_id TEXT NOT NULL DEFAULT '',
          account_url TEXT NOT NULL DEFAULT '',
          label TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          PRIMARY KEY (profile_id, kind, instance_domain, channel_id, account_url)
        );
        CREATE TABLE IF NOT EXISTS dislikes (
          profile_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          video_uuid TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          PRIMARY KEY (profile_id, video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS dislike_profiles (
          profile_id TEXT PRIMARY KEY,
          space TEXT NOT NULL,
          centroids TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS like_generations (
          user_id TEXT NOT NULL,
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          generation INTEGER NOT NULL,
          published INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (user_id, video_id, instance_domain)
        );
        CREATE TABLE IF NOT EXISTS analytics_events (
          id INTEGER PRIMARY KEY,
          type TEXT NOT NULL CHECK (type IN ('page_view', 'outbound_click')),
          track_id TEXT,
          href TEXT,
          page_path TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          user_agent TEXT,
          referer TEXT
        );
        CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx
          ON analytics_events (type, track_id, created_at);
        -- Every visitor's actions used to land on this one shared row; it is nobody's.
        DELETE FROM likes WHERE user_id = 'local-user';
        DELETE FROM users WHERE user_id = 'local-user';
        """
    )


def insert_analytics_event(
    conn: sqlite3.Connection,
    event_type: str,
    track_id: str | None,
    href: str | None,
    page_path: str,
    created_at: int,
    user_agent: str | None,
    referer: str | None,
) -> None:
    """Insert one analytics event, inside the caller's transaction."""
    conn.execute(
        "INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, track_id, href, page_path, created_at, user_agent, referer),
    )


def get_or_create_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Insert a user row if it does not exist."""
    now = now_ms()
    row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return
    conn.execute(
        "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)",
        (user_id, user_id, now),
    )
    conn.commit()


def record_like(
    conn: sqlite3.Connection,
    user_id: str,
    action: str,
    video: dict[str, Any],
    max_likes: int,
    publish: bool = False,
) -> tuple[bool, int]:
    """Record a like with recency tracking.

    :param publish: The caller publishes a `Like` when this opens one. The likes import passes nothing, so an imported like never opens one.
    :returns: Whether this like opened the video's published like, and the video's like generation (0 when none was ever opened).
    """
    if action != "like":
        raise ValueError("Unsupported action")
    get_or_create_user(conn, user_id)
    video_id = str(video.get("video_id") or "")
    instance_domain = str(video.get("instance_domain") or "")
    video_uuid = video.get("video_uuid")
    now = now_ms()
    inserted = conn.execute(
        """
        INSERT INTO likes (user_id, video_id, instance_domain, video_uuid, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, video_id, instance_domain) DO NOTHING
        """,
        (user_id, video_id, instance_domain, video_uuid, now),
    ).rowcount > 0
    if not inserted:
        conn.execute(
            "UPDATE likes SET video_uuid = ?, updated_at = ? WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
            (video_uuid, now, user_id, video_id, instance_domain),
        )
    opened = False
    if inserted and publish:
        # A like still published (the Engine holds it through a reset or trim) is not opened again.
        opened = conn.execute(
            """
            INSERT INTO like_generations (user_id, video_id, instance_domain, generation, published)
            VALUES (?, ?, ?, 1, 1)
            ON CONFLICT(user_id, video_id, instance_domain)
            DO UPDATE SET generation = like_generations.generation + 1, published = 1
            WHERE like_generations.published = 0
            """,
            (user_id, video_id, instance_domain),
        ).rowcount > 0
    generation = like_generation(conn, user_id, video_id, instance_domain)
    if max_likes > 0:
        conn.execute(
            """
            DELETE FROM likes
            WHERE user_id = ?
            AND rowid NOT IN (
              SELECT rowid FROM likes
              WHERE user_id = ?
              ORDER BY updated_at DESC
              LIMIT ?
            )
            """,
            (user_id, user_id, max_likes),
        )
    conn.commit()
    return opened, generation


def fetch_recent_likes(conn: sqlite3.Connection, user_id: str, limit: int) -> list[dict[str, Any]]:
    """Return recent likes for a user, newest first."""
    if limit <= 0:
        limit = -1
    rows = conn.execute(
        """
        SELECT video_id, video_uuid, instance_domain, updated_at
        FROM likes
        WHERE user_id = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [
        {
            "video_id": row["video_id"],
            "video_uuid": row["video_uuid"],
            "instance_domain": row["instance_domain"] or None,
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def load_liked_keys(conn: sqlite3.Connection, profile_id: str) -> set[tuple[str, str]]:
    """Return the profile's liked videos as `(video_id, instance_domain)` pairs."""
    rows = conn.execute(
        "SELECT video_id, instance_domain FROM likes WHERE user_id = ?", (profile_id,)
    ).fetchall()
    return {(row["video_id"], row["instance_domain"]) for row in rows}


def clear_likes(conn: sqlite3.Connection, user_id: str) -> None:
    """Remove all likes for a user."""
    conn.execute("DELETE FROM likes WHERE user_id = ?", (user_id,))
    conn.commit()


def remove_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> bool:
    """Remove one like by canonical video identity, inside the caller's transaction.

    :returns: Whether a like was removed.
    """
    cursor = conn.execute(
        "DELETE FROM likes WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
        (user_id, video_id, instance_domain),
    )
    return cursor.rowcount > 0


def like_generation(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> int:
    """Return the profile's like generation for one video.

    :returns: The generation, or 0 when no like of it was ever published.
    """
    row = conn.execute(
        "SELECT generation FROM like_generations WHERE user_id = ? AND video_id = ? AND instance_domain = ?",
        (user_id, video_id, instance_domain),
    ).fetchone()
    return int(row[0]) if row else 0


def close_like(conn: sqlite3.Connection, user_id: str, video_id: str, instance_domain: str) -> tuple[bool, int]:
    """Close the profile's published like of one video, inside the caller's transaction.

    :returns: Whether a published like was closed, so an `UndoLike` is due, and the generation that like was published under.
    """
    closed = conn.execute(
        "UPDATE like_generations SET published = 0 WHERE user_id = ? AND video_id = ? AND instance_domain = ? AND published = 1",
        (user_id, video_id, instance_domain),
    ).rowcount > 0
    return closed, like_generation(conn, user_id, video_id, instance_domain)


def video_reaction(conn: sqlite3.Connection, profile_id: str, video_uuid: str,
                   instance_domain: str) -> dict[str, bool]:
    """Return whether the profile likes and whether it dislikes one video."""
    liked = conn.execute(
        "SELECT 1 FROM likes WHERE user_id = ? AND video_uuid = ? AND instance_domain = ?",
        (profile_id, video_uuid, instance_domain),
    ).fetchone()
    disliked = conn.execute(
        "SELECT 1 FROM dislikes WHERE profile_id = ? AND video_uuid = ? AND instance_domain = ?",
        (profile_id, video_uuid, instance_domain),
    ).fetchone()
    return {"liked": liked is not None, "disliked": disliked is not None}
