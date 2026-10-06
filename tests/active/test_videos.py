"""`ensure_video_indexes` keeps the uuid seed-lookup index, adds the per-channel and per-account Following recency indexes, and leaves no index duplicating the (video_id, instance_domain) primary keys of `videos` and `video_embeddings`.

- A database carrying `idx_videos_id_instance`, `idx_video_embeddings_id_instance` and `idx_videos_uuid_instance` keeps only the uuid index plus the two recency indexes; a fresh one gains exactly those three.
- On a crawl-shaped DB holding neither recency index (control), run twice as two Engine starts would, it leaves idx_videos_channel_published on `videos` keyed (instance_domain, channel_id, published_at DESC, video_id DESC) and idx_videos_account_published keyed (account_url, published_at DESC, video_id DESC), read back through `PRAGMA index_xinfo`.

Runs in-process on temporary sqlite files.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.ann_ids import create_video_embeddings_table  # noqa: E402
from data.videos import ensure_video_indexes  # noqa: E402

CRAWL_SCHEMA = SERVER_DIR.parents[1] / "engine" / "crawler" / "schema.sql"


def _video_db(path: Path, with_duplicates: bool) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, instance_domain TEXT NOT NULL, channel_id TEXT, account_url TEXT, published_at INTEGER, PRIMARY KEY (video_id, instance_domain))")
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


def test_ensure_video_indexes_drops_the_two_duplicate_indexes_and_keeps_the_uuid_and_recency_indexes(tmp_path: Path) -> None:
    """A database carrying both duplicates and the uuid index keeps only the uuid and recency indexes; a fresh one gains exactly those three."""
    for name, with_duplicates in (("old.db", True), ("fresh.db", False)):
        path = tmp_path / name
        _video_db(path, with_duplicates)
        conn = sqlite3.connect(path)
        ensure_video_indexes(conn)
        conn.close()
        assert _indexes(path) == {"idx_videos_uuid_instance", "idx_videos_channel_published", "idx_videos_account_published"}, name


# (column, desc) of each index key column, read from PRAGMA index_xinfo rows (seqno, cid, name, desc, coll, key); key = 0 rows are the rowid tail.
RECENCY_INDEXES = {
    "idx_videos_channel_published": [("instance_domain", 0), ("channel_id", 0), ("published_at", 1), ("video_id", 1)],
    "idx_videos_account_published": [("account_url", 0), ("published_at", 1), ("video_id", 1)],
}


def _key_columns(conn: sqlite3.Connection) -> dict[str, tuple[str | None, list[tuple[str, int]]]]:
    """Per recency index: the table it is on, and its key columns with their DESC flag; an absent index reads (None, [])."""
    out = {}
    for name in RECENCY_INDEXES:
        table = conn.execute("SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
        out[name] = (table[0] if table else None, [(row[2], row[3]) for row in conn.execute(f"PRAGMA index_xinfo({name})") if row[5] == 1])
    return out


EXPECTED_INDEXES = {name: ("videos", columns) for name, columns in RECENCY_INDEXES.items()}


def test_ensure_video_indexes_creates_the_channel_and_account_recency_indexes_and_runs_again_on_a_database_that_has_them(tmp_path):
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    create_video_embeddings_table(conn)
    assert _key_columns(conn) == {name: (None, []) for name in RECENCY_INDEXES}  # control: only ensure_video_indexes can add them
    # Twice, as a first and a later Engine start on the same database; a bare CREATE INDEX raises on the second.
    ensure_video_indexes(conn)
    ensure_video_indexes(conn)
    # An ASC published_at or video_id, a missing or reordered column, or no index reads differently.
    assert _key_columns(conn) == EXPECTED_INDEXES  # C2
    conn.close()
