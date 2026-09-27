"""The Engine's random cache waits out another writer's lock, reuses a short non-empty cache at a refresh-off start without writing it, and lets Engines started at once all come up.

- A connection from `connect_random_cache_db` reports a `busy_timeout` above sqlite's 5000 ms default.
- With another connection holding `BEGIN IMMEDIATE` on the cache for 6 s, past sqlite's 5 s default, a refresh-on filtered `populate_random_cache` through such a connection, its wait as `connect_random_cache_db` set it, returns 20, takes at least 6 s, and leaves the cache holding positions 1..20 over source rowids 1..20, the stale rows gone.
- With a 3-row cache under `size=100` and another connection holding `BEGIN IMMEDIATE` on it, the default call on a `timeout=0` connection fails "locked" (control), while the refresh-off call with `reuse_non_empty=True` on its own `timeout=0` connection returns 3, leaves that connection outside any transaction, and leaves the three rows exactly as seeded.
- With the `random_rowids` table missing, or present and empty, the refresh-off call with `reuse_non_empty=True` returns 20 and leaves positions 1..20 over source rowids 1..20.
- Eight Engines started at once against the checkout, with refresh off and no start lock, all answer `/api/health` 200 within 120 s while another connection holds the write lock on the checkout's random-cache.db.

The in-process tests use temporary sqlite files and a real second connection as the lock holder. The Engine test starts real processes on the repo's dataset.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ClientBackend, _free_port

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402
import server_config  # noqa: E402

SQLITE_DEFAULT_BUSY_MS = 5000
SOURCE_ROWS = 20
# Outlasts sqlite's 5 s default, so only a longer wait on the connection carries the rebuild through; a 5 s wait raises "database is locked" at 5.0 s.
HOLD_SECONDS = 6.0
STALE_ROWID = 999
# Fewer rows than the requested size, so a start that does not reuse rebuilds this cache.
SEEDED_ROWS = [(1, 7), (2, 3), (3, 11)]
RANDOM_CACHE_DB = ROOT / "engine" / "server" / "db" / "random-cache.db"
ENGINE_COUNT = 8
HEALTHY_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
LOG_TAIL_LINES = 20


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


def _log_tail(log_path: Path) -> str:
    """The last lines one Engine wrote to its log."""
    return "\n".join(log_path.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:])


def test_random_cache_connection_waits_longer_than_sqlite_default(tmp_path: Path) -> None:
    """A random-cache connection's busy wait exceeds sqlite's 5 s default."""
    cache = connect_random_cache_db(tmp_path / "cache.db")
    try:
        assert cache.execute("PRAGMA busy_timeout").fetchone()[0] > SQLITE_DEFAULT_BUSY_MS
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

    assert built == SOURCE_ROWS
    assert elapsed >= HOLD_SECONDS
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    assert [row["position"] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert {row["video_rowid"] for row in rows} == set(range(1, SOURCE_ROWS + 1))


def test_refresh_off_reuses_a_short_cache_without_writing(tmp_path: Path) -> None:
    """Refresh off with `reuse_non_empty=True` returns a 3-row cache's count under a held write lock, opens no transaction, and leaves the rows as seeded."""
    source = _source_db(tmp_path)
    cache_path = tmp_path / "cache.db"
    seed = connect_random_cache_db(cache_path)
    ensure_random_cache_schema(seed)
    seed.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", SEEDED_ROWS)
    seed.commit()
    seed.close()

    holder = sqlite3.connect(cache_path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        # Control: the lock is armed and a short cache is otherwise rebuilt, so the default call's write fails on it.
        control = sqlite3.connect(cache_path, timeout=0)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            populate_random_cache(source, control, 100, False, True, 0, 100)
        control.close()

        # timeout=0: any write this call sent would fail "locked" at once instead of waiting.
        cache = sqlite3.connect(cache_path, timeout=0)
        reused = populate_random_cache(source, cache, 100, False, True, 0, 100, reuse_non_empty=True)
        in_transaction = cache.in_transaction
        rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
        cache.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert reused == len(SEEDED_ROWS)
    # A write attempt, even a failed one, leaves Python's implicit BEGIN open on the connection.
    assert in_transaction is False
    assert rows == SEEDED_ROWS


@pytest.mark.parametrize("table", ["missing", "empty"])
def test_refresh_off_builds_a_missing_or_empty_cache(tmp_path: Path, table: str) -> None:
    """Refresh off with `reuse_non_empty=True` builds a cache whose table is missing or empty: 20 rows, positions 1..20 over source rowids 1..20."""
    source = _source_db(tmp_path)
    cache = connect_random_cache_db(tmp_path / "cache.db")
    if table == "empty":
        ensure_random_cache_schema(cache)
        cache.commit()

    built = populate_random_cache(source, cache, 100, False, True, 0, 100, reuse_non_empty=True)

    assert built == SOURCE_ROWS
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    assert [row["position"] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert {row["video_rowid"] for row in rows} == set(range(1, SOURCE_ROWS + 1))
    cache.close()


def test_engines_starting_at_once_all_become_healthy(engine, tmp_path: Path) -> None:
    """Eight Engines launched at once with refresh off, no start lock and the checkout's non-empty cache write-locked by another connection: none exits and all answer `/api/health` 200 within 120 s.

    An Engine start that writes the cache waits on the held lock and never becomes healthy, and a start that only skips the rebuild for a full cache writes this short one; one that reuses the non-empty cache only reads it. Each Engine is started as `server.py --host 127.0.0.1 --port <own port> --no-random-cache-refresh` with `ENGINE_INGEST_MODE=bridge`, the bridge token and `RECOMMENDATIONS_DEBUG=1`. The session `engine` fixture is what leaves the checkout's cache non-empty.
    """
    cache = sqlite3.connect(f"file:{RANDOM_CACHE_DB}?mode=ro", uri=True)
    cached_rows = cache.execute("SELECT COUNT(*) FROM random_rowids").fetchone()[0]
    cache.close()
    # Control: a non-empty cache is the one a refresh-off start may reuse; an empty one is built, and that write would wait on the lock below.
    assert cached_rows > 0, "the session Engine left the checkout's random-cache.db empty"
    # Control: a full cache is already read-only for a start that skips its rebuild at `existing >= size`, so only a short one tells reuse from that skip.
    assert cached_rows < server_config.DEFAULT_RANDOM_CACHE_SIZE, f"the checkout's random-cache.db holds {cached_rows} rows, not short of {server_config.DEFAULT_RANDOM_CACHE_SIZE}, so a start without reuse would not write it either"

    holder = sqlite3.connect(RANDOM_CACHE_DB, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    procs: list[subprocess.Popen] = []
    try:
        # Control: the lock is armed, so a start that writes the cache waits on it rather than finishing.
        control = sqlite3.connect(RANDOM_CACHE_DB, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                control.execute("DELETE FROM random_rowids WHERE 0")
        finally:
            control.close()

        env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
        # Distinct ports, so no Engine exits on a port another one took.
        ports: set[int] = set()
        while len(ports) < ENGINE_COUNT:
            ports.add(_free_port())
        engines: list[ClientBackend] = []
        log_paths: list[Path] = []
        deadline = time.time() + HEALTHY_WITHIN_SECONDS
        for port in sorted(ports):
            log_path = tmp_path / f"engine-{port}.log"
            with open(log_path, "w") as log:
                procs.append(subprocess.Popen(
                    [str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port),
                     "--no-random-cache-refresh"],
                    env=env, stdout=log, stderr=log,
                ))
            engines.append(ClientBackend(f"http://127.0.0.1:{port}", log_path))
            log_paths.append(log_path)

        pending = set(range(ENGINE_COUNT))
        while pending and time.time() < deadline and all(proc.poll() is None for proc in procs):
            for index in sorted(pending):
                try:
                    if engines[index].request("GET", "/api/health")[0] == 200:
                        pending.discard(index)
                except OSError:
                    pass
            time.sleep(0.25)

        exited = {index: proc.returncode for index, proc in enumerate(procs) if proc.poll() is not None}
        assert exited == {}, "\n\n".join(f"Engine on {engines[index].base} exited {code}; log tail:\n{_log_tail(log_paths[index])}" for index, code in sorted(exited.items()))
        assert pending == set(), f"{len(pending)} of {ENGINE_COUNT} Engines not healthy within {HEALTHY_WITHIN_SECONDS}s: {[engines[index].base for index in sorted(pending)]}"
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        # A start still waiting on the held lock is inside sqlite's busy wait and does not act on SIGTERM until it returns, so a straggler is killed.
        stop_deadline = time.time() + STOP_WITHIN_SECONDS
        for proc in procs:
            try:
                proc.wait(timeout=max(0.0, stop_deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        holder.execute("ROLLBACK")
        holder.close()
