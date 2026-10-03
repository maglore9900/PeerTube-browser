"""Provide trending ranks runtime helpers."""

from __future__ import annotations

import sqlite3


def ensure_trending_schema(conn: sqlite3.Connection) -> None:
    """Create the table of each catalogue host's own trending list and the index the Trending order walks."""
    # executescript commits any open transaction first, so callers run this before their BEGIN IMMEDIATE, never inside it.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trending_ranks (
          instance_domain TEXT NOT NULL,
          video_id TEXT NOT NULL,
          rank INTEGER NOT NULL,
          likes INTEGER NOT NULL,
          views INTEGER NOT NULL,
          fetched_at INTEGER NOT NULL,
          PRIMARY KEY (instance_domain, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trending_ranks_order
          ON trending_ranks (rank ASC, likes DESC, views DESC, video_id DESC, instance_domain DESC);
        """
    )
