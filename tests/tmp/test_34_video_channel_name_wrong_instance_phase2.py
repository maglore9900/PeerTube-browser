"""`repair_channel_names` from `repair-video-channel-names.py`, run in-process on a crawl.db-shaped and a whitelist.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names.

- It returns 3, and a fresh connection then reads v1, v2 and v7 (foreign or NULL names) as their own channel's display name, while v3 (already correct), v4 (empty display name), v5 (NULL display name) and v6 (no channel row) keep their stored names.
- `channels` reads back identical to its pre-repair snapshot.
- A second call returns 0 and leaves every name as the first call set it.
- `has_videos_fts` is True on the whitelist shape and False on the crawl shape.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
STORED = {"v1": "Betachan", "v2": "Alphachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": None}
REPAIRED = {"v1": "Alphachan", "v2": "Betachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": "Alphachan"}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)


@pytest.fixture(params=["crawl", "whitelist"])
def seeded_db(request, sync_job, tmp_path):
    sync = sync_job
    db_path = tmp_path / f"{request.param}.db"
    conn = sqlite3.connect(db_path)
    try:
        if request.param == "crawl":
            conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        else:
            sync.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path, request.param


def _names(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall())


def _channels(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM channels ORDER BY channel_id, instance_domain").fetchall()


def test_repair_sets_each_video_to_its_own_channel_name(seeded_db):
    db_path, shape = seeded_db
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == STORED, "the seed did not land as written"
        channels_before = _channels(conn)
        # Loaded after the seed control, so a missing job is reported only once the fixture is known good.
        repair = _load_job("repair_video_channel_names", "repair-video-channel-names.py")
        changed = repair.repair_channel_names(conn)
    finally:
        conn.close()
    assert changed == 3  # C2

    # Reopened, so a repair that never commits reads back as the stored names.
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == REPAIRED  # C1
        assert _channels(conn) == channels_before  # C1
        assert repair.has_videos_fts(conn) is (shape == "whitelist"), f"the {shape} shape was not told apart by videos_fts"
        assert repair.repair_channel_names(conn) == 0  # C2
    finally:
        conn.close()

    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == REPAIRED  # C2
    finally:
        conn.close()
