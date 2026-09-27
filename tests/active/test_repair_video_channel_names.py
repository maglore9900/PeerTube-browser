"""`repair-video-channel-names.py` sets each video's `channel_name` to its own instance's channel display name, rebuilds `videos_fts` to match, and runs as a command that requires `--db` and logs the changed count.

- In-process on a crawl.db-shaped and a whitelist.db-shaped temp database seeded with foreign, NULL, correct and unrepairable names, `repair_channel_names` returns 3, and a fresh connection then reads v1, v2 and v7 (foreign or NULL names) as their own channel's display name, while v3 (already correct), v4 (empty display name), v5 (NULL display name) and v6 (no channel row) keep their stored names. `channels` reads back identical to its pre-repair snapshot. A second call returns 0 and leaves every name as the first call set it. `has_videos_fts` is True on the whitelist shape and False on the crawl shape.
- On a whitelist.db-shaped database whose `videos_fts` has drifted (v1 corrected and v8 inserted while the triggers were dropped), after the repair and through a fresh connection a `channel_name` MATCH on "Alphachan" returns exactly v1 and v7, and one on "Betachan" exactly v2 and v3; `videos_fts_docsize` holds as many rows as `videos` (8), and the FTS5 integrity-check passes.
- Run as a command through `sys.executable` with no arguments it exits 2 with argparse's usage error naming `--db` as required, and logs no repair. Run with `--db` on a crawl.db-shaped database it exits 0, logs `channel names repaired rows=3` exactly once, and leaves the repaired names; run again it exits 0 and logs `channel names repaired rows=0`.

The whitelist shape and its FTS triggers come from `sync-whitelist.py`, the crawl shape from `engine/crawler/schema.sql`.
"""
from __future__ import annotations

import importlib.util
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
REPAIR_JOB = JOBS_DIR / "repair-video-channel-names.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
STORED = {"v1": "Betachan", "v2": "Alphachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": None}
REPAIRED = {"v1": "Alphachan", "v2": "Betachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": "Alphachan"}
# Channel 8 has an empty display name, so the repair's UPDATE never touches v8 and only a rebuild can index it.
UNINDEXED_VIDEO = ("v8", "a.example", "8", "Stalename")
INSERT_VIDEO_SQL = "INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)"
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"
# COUNT(*) on the external-content videos_fts reads the videos table, so the index's own row count is taken from its docsize shadow table.
INDEXED_COUNT_SQL = "SELECT COUNT(*) FROM videos_fts_docsize"
VIDEOS_COUNT_SQL = "SELECT COUNT(*) FROM videos"
REPAIRED_LOG = r"channel names repaired rows=(\d+)"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_channel_names", "sync-whitelist.py")


@pytest.fixture(scope="module")
def repair_job():
    return _load_job("repair_video_channel_names", "repair-video-channel-names.py")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany(INSERT_VIDEO_SQL, VIDEOS)


@pytest.fixture(params=["crawl", "whitelist"])
def seeded_db(request, sync_job, tmp_path):
    db_path = tmp_path / f"{request.param}.db"
    conn = sqlite3.connect(db_path)
    try:
        if request.param == "crawl":
            conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        else:
            sync_job.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path, request.param


def _names(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall())


def _names_at(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return _names(conn)
    finally:
        conn.close()


def _channels(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM channels ORDER BY channel_id, instance_domain").fetchall()


def _matches(conn: sqlite3.Connection, name: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'channel_name : "{name}"',))}


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPAIR_JOB), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_repair_sets_each_video_to_its_own_channel_name(seeded_db, repair_job):
    db_path, shape = seeded_db
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == STORED, "the seed did not land as written"
        channels_before = _channels(conn)
        changed = repair_job.repair_channel_names(conn)
    finally:
        conn.close()
    assert changed == 3

    # Reopened, so a repair that never commits reads back as the stored names.
    conn = sqlite3.connect(db_path)
    try:
        assert _names(conn) == REPAIRED
        assert _channels(conn) == channels_before
        assert repair_job.has_videos_fts(conn) is (shape == "whitelist"), f"the {shape} shape was not told apart by videos_fts"
        assert repair_job.repair_channel_names(conn) == 0
    finally:
        conn.close()

    assert _names_at(db_path) == REPAIRED


def test_repaired_fts_finds_own_name_not_foreign_name(sync_job, repair_job, tmp_path):
    db_path = tmp_path / "whitelist.db"
    conn = sqlite3.connect(db_path)
    try:
        sync_job.ensure_content_schema(conn)
        _seed(conn)
        conn.commit()
        # v1 corrected and v8 added behind the index's back, as a repair that stopped before its rebuild leaves it; per-row triggers alone cannot mend this.
        sync_job.drop_videos_fts_triggers(conn)
        conn.execute("UPDATE videos SET channel_name = 'Alphachan' WHERE video_id = 'v1'")
        conn.execute(INSERT_VIDEO_SQL, UNINDEXED_VIDEO)
        conn.commit()
        sync_job.create_videos_fts_triggers(conn)
        assert _matches(conn, "Alphachan") == {"v2"} and _matches(conn, "Betachan") == {"v1", "v3"}, "the index did not start out holding the stale names"
        assert (_count(conn, INDEXED_COUNT_SQL), _count(conn, VIDEOS_COUNT_SQL)) == (7, 8), "the index did not start out missing v8"
        repair_job.repair_channel_names(conn)
    finally:
        conn.close()

    # Reopened, so a rebuild that never commits reads back as the stale index.
    conn = sqlite3.connect(db_path)
    try:
        assert _matches(conn, "Alphachan") == {"v1", "v7"}
        assert _matches(conn, "Betachan") == {"v2", "v3"}
        assert (_count(conn, INDEXED_COUNT_SQL), _count(conn, VIDEOS_COUNT_SQL)) == (8, 8)
        # Raises DatabaseError ("database disk image is malformed") when the index disagrees with videos.
        conn.execute("INSERT INTO videos_fts (videos_fts, rank) VALUES ('integrity-check', 1)")
    finally:
        conn.close()


def test_cli_requires_db_and_logs_changed_count(tmp_path):
    bare = _run(tmp_path)
    assert bare.returncode == 2, f"stdout: {bare.stdout} stderr: {bare.stderr}"
    assert "the following arguments are required: --db" in bare.stderr
    assert re.findall(REPAIRED_LOG, bare.stderr) == []

    db_path = tmp_path / "crawl.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    assert _names_at(db_path) == STORED, "the seed did not land as written"

    first = _run(tmp_path, "--db", str(db_path))
    assert first.returncode == 0, f"stdout: {first.stdout} stderr: {first.stderr}"
    assert re.findall(REPAIRED_LOG, first.stderr) == ["3"], f"stderr: {first.stderr}"
    # The logged count is only the changed count if exactly those three rows changed.
    assert _names_at(db_path) == REPAIRED

    second = _run(tmp_path, "--db", str(db_path))
    assert second.returncode == 0, f"stdout: {second.stdout} stderr: {second.stderr}"
    assert re.findall(REPAIRED_LOG, second.stderr) == ["0"], f"stderr: {second.stderr}"
    assert _names_at(db_path) == REPAIRED
