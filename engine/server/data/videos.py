"""Provide videos runtime helpers."""

from __future__ import annotations

import sqlite3


def ensure_video_indexes(conn: sqlite3.Connection) -> None:
    """Create the uuid seed-lookup index and the per-channel and per-account recency indexes the Following read seeks, and drop the two indexes that duplicate the (video_id, instance_domain) primary keys."""
    videos_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'videos' LIMIT 1"
    ).fetchone()
    embeddings_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'video_embeddings' LIMIT 1"
    ).fetchone()
    if not videos_exists and not embeddings_exists:
        return
    if videos_exists:
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_videos_uuid_instance
              ON videos (video_uuid, instance_domain);
            CREATE INDEX IF NOT EXISTS idx_videos_channel_published
              ON videos (instance_domain, channel_id, published_at DESC, video_id DESC);
            CREATE INDEX IF NOT EXISTS idx_videos_account_published
              ON videos (account_url, published_at DESC, video_id DESC);
            DROP INDEX IF EXISTS idx_videos_id_instance;
            """
        )
    if embeddings_exists:
        # Both duplicates repeat their table's (video_id, instance_domain) primary key, which already serves those lookups.
        conn.executescript("DROP INDEX IF EXISTS idx_video_embeddings_id_instance;")
