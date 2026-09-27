"""A random-cache connection waits out another writer's lock for longer than sqlite's default, and a refresh rebuild through it completes.

- A connection from `connect_random_cache_db` reports a `busy_timeout` above sqlite's 5000 ms default.
- With another connection holding `BEGIN IMMEDIATE` on the cache for 6 s, past sqlite's 5 s default, a refresh-on filtered `populate_random_cache` through such a connection, its wait as `connect_random_cache_db` set it, returns 20, takes at least 6 s, and leaves the cache holding positions 1..20 over source rowids 1..20, the stale rows gone.

The source and cache are temporary sqlite files; the lock holder is a real second connection released by a timer.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402

SQLITE_DEFAULT_BUSY_MS = 5000
SOURCE_ROWS = 20
# Outlasts sqlite's 5 s default, so only a longer wait on the connection carries the rebuild through; a 5 s wait raises "database is locked" at 5.0 s.
HOLD_SECONDS = 6.0
STALE_ROWID = 999


def _source_db(tmp_path: Path) -> sqlite3.Connection:
    """A source of 20 embedded videos, rowids 1..20, one instance, three channels."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT)")
    for index in range(1, SOURCE_ROWS + 1):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example')", (f"v{index}",))
    conn.commit()
    return conn


def test_random_cache_connection_waits_longer_than_sqlite_default(tmp_path: Path) -> None:
    """A random-cache connection's busy wait exceeds sqlite's 5 s default."""
    cache = connect_random_cache_db(tmp_path / "cache.db")
    try:
        assert cache.execute("PRAGMA busy_timeout").fetchone()[0] > SQLITE_DEFAULT_BUSY_MS  # C1
    finally:
        cache.close()


def test_rebuild_waits_for_a_write_lock_held_past_sqlite_default(tmp_path: Path) -> None:
    """A refresh rebuild through a random-cache connection, its wait untouched, waits out a 6 s write lock and completes."""
    source = _source_db(tmp_path)
    cache_path = tmp_path / "cache.db"
    cache = connect_random_cache_db(cache_path)
    ensure_random_cache_schema(cache)
    cache.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(position, STALE_ROWID) for position in range(1, 6)])
    cache.commit()

    holder = sqlite3.connect(cache_path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    # Control: the lock is armed, so a writer that does not wait fails on it.
    probe = sqlite3.connect(cache_path, timeout=0)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        probe.execute("DELETE FROM random_rowids")
    probe.close()

    # No test-side cap on the wait: lowering it would stand in for the value under test; the timer always releases the lock at HOLD_SECONDS.
    release = threading.Timer(HOLD_SECONDS, lambda: holder.execute("ROLLBACK"))
    started = time.monotonic()
    release.start()
    try:
        built = populate_random_cache(source, cache, 100, True, True, 0, 100)
        elapsed = time.monotonic() - started
    finally:
        release.join()
        holder.close()

    assert built == SOURCE_ROWS  # C2
    assert elapsed >= HOLD_SECONDS  # C2
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    assert [row["position"] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C2
    assert {row["video_rowid"] for row in rows} == set(range(1, SOURCE_ROWS + 1))  # C2
