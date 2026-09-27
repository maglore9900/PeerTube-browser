"""`repair-video-channel-names.py` run as a command, through `sys.executable`, against a crawl.db-shaped temp database seeded with foreign, NULL, correct and unrepairable channel names.

- Run with no arguments it exits 2 with argparse's usage error naming `--db` as required, and logs no repair.
- Run with `--db` it exits 0 and logs `channel names repaired rows=3` exactly once, and the database then reads v1, v2 and v7 as their own channel's display name while v3 to v6 keep their stored names.
- Run again it exits 0 and logs `channel names repaired rows=0`.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPAIR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "repair-video-channel-names.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
# (video_id, instance_domain, channel_id, stored channel_name); channel 7 exists on both instances, so each instance's rows start with the other instance's name.
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]
STORED = {"v1": "Betachan", "v2": "Alphachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": None}
REPAIRED = {"v1": "Alphachan", "v2": "Betachan", "v3": "Betachan", "v4": "Stalename", "v5": "Stalename", "v6": "Orphanname", "v7": "Alphachan"}
REPAIRED_LOG = r"channel names repaired rows=(\d+)"


def _names(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall())
    finally:
        conn.close()


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPAIR_JOB), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_cli_requires_db_and_logs_changed_count(tmp_path):
    bare = _run(tmp_path)
    assert bare.returncode == 2, f"stdout: {bare.stdout} stderr: {bare.stderr}"  # C1
    assert "the following arguments are required: --db" in bare.stderr  # C1
    assert re.findall(REPAIRED_LOG, bare.stderr) == []  # C1

    db_path = tmp_path / "crawl.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
        conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
        conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)
        conn.commit()
    finally:
        conn.close()
    assert _names(db_path) == STORED, "the seed did not land as written"

    first = _run(tmp_path, "--db", str(db_path))
    assert first.returncode == 0, f"stdout: {first.stdout} stderr: {first.stderr}"  # C2
    assert re.findall(REPAIRED_LOG, first.stderr) == ["3"], f"stderr: {first.stderr}"  # C2
    # The logged count is only the changed count if exactly those three rows changed.
    assert _names(db_path) == REPAIRED  # C2

    second = _run(tmp_path, "--db", str(db_path))
    assert second.returncode == 0, f"stdout: {second.stdout} stderr: {second.stderr}"  # C2
    assert re.findall(REPAIRED_LOG, second.stderr) == ["0"], f"stderr: {second.stderr}"  # C2
    assert _names(db_path) == REPAIRED  # C2
