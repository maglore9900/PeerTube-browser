"""`repair_channel_names` from `repair-video-channel-names.py`, run in-process on a whitelist.db-shaped temp database whose `videos_fts` has drifted: seeded with foreign and NULL channel names, then, while the triggers were dropped, v1 corrected and v8 inserted, so the index still holds v1's foreign name and has no row for v8.

- After the repair, and read through a fresh connection, a `channel_name` MATCH on "Alphachan" returns exactly v1 and v7, and one on "Betachan" returns exactly v2 and v3, so neither name finds the other instance's same-id channel's videos.
- `videos_fts_docsize` holds as many rows as `videos` (8), and the FTS5 integrity-check passes.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
# Channel 8 has an empty display name, so the repair's UPDATE never touches v8 and only a rebuild can index it.
UNINDEXED_VIDEO = ("v8", "a.example", "8", "Stalename")
INSERT_VIDEO_SQL = "INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)"
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"
# COUNT(*) on the external-content videos_fts reads the videos table, so the index's own row count is taken from its docsize shadow table.
INDEXED_COUNT_SQL = "SELECT COUNT(*) FROM videos_fts_docsize"
VIDEOS_COUNT_SQL = "SELECT COUNT(*) FROM videos"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py"), _load_job("repair_video_channel_names", "repair-video-channel-names.py")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany(INSERT_VIDEO_SQL, VIDEOS)


def _matches(conn: sqlite3.Connection, name: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'channel_name : "{name}"',))}


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def test_repaired_fts_finds_own_name_not_foreign_name(jobs, tmp_path):
    sync, repair = jobs
    db_path = tmp_path / "whitelist.db"
    conn = sqlite3.connect(db_path)
    try:
        sync.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
        # v1 corrected and v8 added behind the index's back, as a repair that stopped before its rebuild leaves it; per-row triggers alone cannot mend this.
        sync.drop_videos_fts_triggers(conn)
        conn.execute("UPDATE videos SET channel_name = 'Alphachan' WHERE video_id = 'v1'")
        conn.execute(INSERT_VIDEO_SQL, UNINDEXED_VIDEO)
        conn.commit()
        sync.create_videos_fts_triggers(conn)
        assert _matches(conn, "Alphachan") == {"v2"} and _matches(conn, "Betachan") == {"v1", "v3"}, "the index did not start out holding the stale names"
        assert (_count(conn, INDEXED_COUNT_SQL), _count(conn, VIDEOS_COUNT_SQL)) == (7, 8), "the index did not start out missing v8"
        repair.repair_channel_names(conn)
    finally:
        conn.close()

    # Reopened, so a rebuild that never commits reads back as the stale index.
    conn = sqlite3.connect(db_path)
    try:
        assert _matches(conn, "Alphachan") == {"v1", "v7"}  # C1
        assert _matches(conn, "Betachan") == {"v2", "v3"}  # C1
        assert (_count(conn, INDEXED_COUNT_SQL), _count(conn, VIDEOS_COUNT_SQL)) == (8, 8)  # C2
        # Raises DatabaseError ("database disk image is malformed") when the index disagrees with videos.
        conn.execute("INSERT INTO videos_fts (videos_fts, rank) VALUES ('integrity-check', 1)")  # C2
    finally:
        conn.close()
