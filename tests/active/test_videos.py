"""`ensure_video_indexes` keeps the uuid seed-lookup index and leaves no index duplicating the (video_id, instance_domain) primary keys of `videos` and `video_embeddings`.

- A database carrying `idx_videos_id_instance`, `idx_video_embeddings_id_instance` and `idx_videos_uuid_instance` keeps only the uuid index; a fresh one gains only the uuid index.

Runs in-process on temporary sqlite files.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.videos import ensure_video_indexes  # noqa: E402


def _video_db(path: Path, with_duplicates: bool) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, instance_domain TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB, PRIMARY KEY (video_id, instance_domain))")
    if with_duplicates:
        conn.execute("CREATE INDEX idx_videos_id_instance ON videos (video_id, instance_domain)")
        conn.execute("CREATE INDEX idx_video_embeddings_id_instance ON video_embeddings (video_id, instance_domain)")
        conn.execute("CREATE INDEX idx_videos_uuid_instance ON videos (video_uuid, instance_domain)")
    conn.commit()
    conn.close()


def _indexes(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'")}
    finally:
        conn.close()


def test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_index(tmp_path: Path) -> None:
    """A database carrying both duplicates and the uuid index keeps only the uuid index; a fresh one gains only the uuid index."""
    for name, with_duplicates in (("old.db", True), ("fresh.db", False)):
        path = tmp_path / name
        _video_db(path, with_duplicates)
        conn = sqlite3.connect(path)
        ensure_video_indexes(conn)
        conn.close()
        assert _indexes(path) == {"idx_videos_uuid_instance"}, name
