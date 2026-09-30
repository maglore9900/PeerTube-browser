"""The Engine's random cache is built complete in a per-pid temp file, swapped in as a read-only serving handle only after it is validated and renamed into place, opened read-only at startup when usable, and rebuilt by one background worker after the Engine listens.

- A connection from `connect_random_cache_db` reports a `busy_timeout` above sqlite's 5000 ms default.
- With another connection holding `BEGIN IMMEDIATE` on the cache for 6 s, past sqlite's 5 s default, a refresh-on filtered `populate_random_cache` through such a connection, its wait as `connect_random_cache_db` set it, returns 20, takes at least 6 s, and leaves the cache holding positions 1..20 over source rowids 1..20, the stale rows gone.
- `build_random_cache(source, <dir>/random-cache.db, 100, True, 0, 100)` returns `<dir>/random-cache.tmp.<pid>.db` and 20, and that file holds positions 1..20 over source rowids 1..20. The directory then holds only that file and the active file's prior state: no `-journal` or other sidecar, a seeded active file byte-identical and a missing one still missing. A non-sqlite leftover at the temp name does not stop the build.
- With `populate_random_cache` patched to write into the temp file and then raise, `build_random_cache` re-raises, and the directory holds only the seeded active file, byte-identical, with no temp file or `-journal`.
- `refresh_random_cache` over a seeded active file returns True. The active path is then at a new inode and the directory holds only that file. `owner.random_cache_db` is a different object, `fetch_random_rowids` on it returns the renamed file's rowids in position order (source rowids 1..20), and a write through it fails "readonly". The old handle raises `ProgrammingError`.
- After one swap, a second same-pid build is paused after an uncommitted write that spills sqlite's page cache. While it is paused, no `random-cache.tmp.<pid>.db-journal` exists and `fetch_random_rowids` on the served handle returns the first build's rowids. The build then swaps. Control: with `connect_random_cache_db` replaced by an opener without the in-memory journal, the journal exists and the same read raises `OperationalError`.
- Three reader threads loop `fetch_random_rowids` under the owner's lock while 10 refreshes run, all of which swap. No read raises and none comes back empty.
- `refresh_random_cache` with the build raising after writing, a table-less build failing the check, or the rename refused returns False and logs `failed` with the reason. The active file's bytes are unchanged, the owner holds the same handle and it still reads, and the directory holds only the active file.
- With the stop event set during the build, `refresh_random_cache` returns False with the same file, handle and directory outcome.
- `open_random_cache_if_usable` gives None for a missing file (and does not create it), a file without `random_rowids`, and an empty table. For a 3-row cache it gives a handle that reads the three rows as seeded and fails a write "readonly", both with the file free and with another connection holding `BEGIN IMMEDIATE` on it.
- `run_random_cache_worker` with interval 0 and no startup build returns within 5 s having built nothing, leaving the owner's handle, the active file's bytes and the directory as they were. With a startup build it returns within 5 s having built exactly once, and the owner serves a new handle on the rebuilt file, the only file left.
- Eight Engines started at once against the checkout, with refresh off and no start lock, all answer `/api/health` 200 within 120 s while another connection holds the write lock on the checkout's random-cache.db.
- A refresh-on Engine over a seeded 20-row cache, interval 0, its startup build held at a gate: once the build has entered the gate, `/api/health` answers 200, and the random feed answers 200 with rows that all map into the seeded rowids while the seeded file is still at its inode. No `ok` line is logged while held. Released, it logs exactly one `ok` line with size 200 for the tmp path, which then holds 200 rows at a new inode. The gate was entered exactly once and one `random cache build start` line was logged.
- An Engine with interval 0.25 min, refresh off and no cache file logs at least three `ok` lines, the file at a different inode after each than after the one before. The random feed, requested throughout, answers 200 with rows every time, and after each `ok` its rows all map into the rowids of the file then at the path.
- A refresh-off Engine, interval 0, with a gate set, over a missing cache file enters the gate within 5 s of answering health and logs one `random cache build start` line. The same Engine over the same seeded 20-row cache, which logged `random_cache_refresh=false`: 5 s after it answers health, no build has entered the gate, no `random cache build start` line is logged, the seeded file is at its inode with its rows, and the random feed answers 200 with rows that all map into the seeded rowids.

The in-process tests use temporary sqlite files, a real second connection as the lock holder, and a `SimpleNamespace` owner with a `threading.Lock`, the contract `fetch_random_rows_from_cache(server)` reads; the rename refusal replaces `os.replace`, the filesystem boundary. The Engine tests start real processes on the repo's dataset, the gated ones through CACHE_VARIANT_RUNNER with the config module's cache path, size, interval and rate limit overridden; rows are mapped to rowids through a read-only `whitelist.db`.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, WHITELIST_DB, ClientBackend, _free_port

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.db as db  # noqa: E402
import data.random_cache as random_cache  # noqa: E402
from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402
import server_config  # noqa: E402

SQLITE_DEFAULT_BUSY_MS = 5000
SOURCE_ROWS = 20
# Outlasts sqlite's 5 s default, so only a longer wait on the connection carries the rebuild through; a 5 s wait raises "database is locked" at 5.0 s.
HOLD_SECONDS = 6.0
STALE_ROWID = 999
# A 3-row cache whose order no build over the 20-row source reproduces.
SEEDED_ROWS = [(1, 7), (2, 3), (3, 11)]
SEEDED_ROWIDS = [7, 3, 11]
RANDOM_CACHE_DB = ROOT / "engine" / "server" / "db" / "random-cache.db"
ENGINE_COUNT = 8
HEALTHY_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
LOG_TAIL_LINES = 20
# Above the source's 20 rows, so every in-process build holds the whole source.
BUILD_SIZE = 100
# Above every cache in these tests, so fetch_random_rowids reads from offset 0 and returns the whole table in position order.
READ_ALL = 100
FAILURE_MESSAGE = "populate failed after writing"
RENAME_REFUSED = "rename refused"
# Past sqlite's page cache at this size, so the paused build's rollback journal is synced to disk with its magic header, as a production-size build's is; a smaller uncommitted write leaves a zeroed header that no reader treats as hot.
SPILL_CACHE_PAGES = 10
SPILL_ROWS = 5000
WAIT_SECONDS = 30
READER_THREADS = 3
REFRESH_CYCLES = 10
READ_LIMIT = 5
RETURN_WITHIN_SECONDS = 5
VARIANT_CACHE_SIZE = 200
# 15 s ticks: the startup build and two ticks put three builds in about 30 s, well inside TICKS_WITHIN_SECONDS.
SHORT_INTERVAL_MINUTES = 0.25
TICKS = 3
TICKS_WITHIN_SECONDS = 90
ENTERED_WITHIN_SECONDS = 30
OK_WITHIN_SECONDS = 120
# Past HEALTHY_WITHIN_SECONDS plus the held checks, so an Engine that builds before listening is still held when the health wait gives up.
GATE_BOUND_SECONDS = 300
SEEDED_CACHE_ROWS = 20
# Above the default 60 per minute per path, which the looped random feed passes in seconds.
RATE_LIMIT = 1000000
SETTLE_SECONDS = 2
# The worker starts just before the Engine serves, so a startup build enters the gate about when health first answers; the missing-cache control must do so inside this window.
NO_BUILD_WINDOW_SECONDS = 5
FEED_PAUSE_SECONDS = 0.05
START_PREFIX = "random cache build start"
OK_PREFIX = "random cache build ok"
MODE_PREFIX = "[similar-server] mode="
RANDOM_FEED = "/recommendations?random=1"
# Runs server.py as __main__ with `server_config` bound to the real file's module, the overrides set on it. A non-empty gate directory holds every `build_random_cache` call until `<gate>/release` exists, recording each call in `<gate>/entered`.
CACHE_VARIANT_RUNNER = """
import importlib.util, json, os, runpy, sys, time
server, overrides, gate, bound = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], float(sys.argv[4])
api = os.path.dirname(server)
sys.path.insert(0, api)
sys.path.insert(0, os.path.dirname(api))
spec = importlib.util.spec_from_file_location("server_config", os.path.join(api, "server_config.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name, value in overrides.items():
    setattr(module, name, value)
sys.modules["server_config"] = module
if gate:
    import data.random_cache as random_cache
    real_build = random_cache.build_random_cache
    def gated_build(*args, **kwargs):
        with open(os.path.join(gate, "entered"), "a") as entered:
            entered.write("entered\\n")
        deadline = time.time() + bound
        while not os.path.exists(os.path.join(gate, "release")) and time.time() < deadline:
            time.sleep(0.05)
        return real_build(*args, **kwargs)
    random_cache.build_random_cache = gated_build
sys.argv = [server, *sys.argv[5:]]
runpy.run_path(server, run_name="__main__")
"""


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


def _seed_cache(path: Path, rows: list[tuple[int, int]]) -> None:
    """Write a random cache file holding exactly `rows`, through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _cache_rows(path: Path) -> list[tuple[int, int]]:
    """A cache file's rows in position order, read through a read-only handle so a missing file is never created."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    finally:
        conn.close()


def _cache_rowids(path: Path) -> list[int]:
    """A cache file's rowids in position order, read through a read-only handle so a missing file is never created."""
    return [row[1] for row in _cache_rows(path)]


def _seeded(tmp_path: Path) -> tuple[Path, SimpleNamespace]:
    """A 20-row source, an active cache holding SEEDED_ROWS, and an owner serving it through a read-only handle."""
    _source_db(tmp_path).close()
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_cache(active_path, SEEDED_ROWS)
    return active_path, SimpleNamespace(random_cache_db=db.connect_readonly_db(active_path), random_cache_lock=threading.Lock())


def _refresh(tmp_path: Path, active_path: Path, owner: SimpleNamespace, stop_event: threading.Event | None = None) -> bool:
    return random_cache.refresh_random_cache(tmp_path / "source.db", active_path, BUILD_SIZE, True, 0, 100, owner, stop_event or threading.Event())


def _served_rowids(owner: SimpleNamespace) -> list[int]:
    """Read the whole cache through the owner's current handle, holding its lock as the request path does."""
    with owner.random_cache_lock:
        return random_cache.fetch_random_rowids(owner.random_cache_db, READ_ALL)


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


def _seed_servable_cache(dataset: sqlite3.Connection, cache_path: Path) -> list[int]:
    """Seed `cache_path` with the first 20 rowids the random feed can serve, and return them in position order."""
    # Rows the random feed's metadata join keeps: a matching videos row and an error count under the Engine's threshold of 3.
    seeded = [row[0] for row in dataset.execute("SELECT e.rowid FROM video_embeddings e JOIN videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain WHERE v.error_count IS NULL OR v.error_count < 3 ORDER BY e.rowid LIMIT ?", (SEEDED_CACHE_ROWS,)).fetchall()]
    assert len(seeded) == SEEDED_CACHE_ROWS
    _seed_cache(cache_path, list(enumerate(seeded, start=1)))
    return seeded


def _payloads(log_path: Path) -> list[dict]:
    payloads = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _messages(log_path: Path, prefix: str) -> list[str]:
    return [payload["message"] for payload in _payloads(log_path) if isinstance(payload.get("message"), str) and payload["message"].startswith(prefix)]


def _tokens(message: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in message.split() if "=" in token)


def _has_started(log_path: Path) -> bool:
    # The lifecycle start is the Engine's last startup line, logged just before it serves.
    return any(payload.get("event") == "service.lifecycle" and (payload.get("context") or {}).get("state") == "start" for payload in _payloads(log_path))


def _feed_rowids(http: ClientBackend, dataset: sqlite3.Connection) -> tuple[int, list[int]]:
    """One random-feed page: its status and its rows' `video_embeddings` rowids, looked up by (video_id, instance_domain) in whitelist.db."""
    status, body = http.request("POST", RANDOM_FEED, body={})
    if status != 200:
        return status, []
    rowids = []
    for row in body["rows"]:
        found = dataset.execute("SELECT rowid FROM video_embeddings WHERE video_id = ? AND instance_domain = ?", (row["video_id"], row["instance_domain"])).fetchall()
        assert len(found) == 1, f"{row['video_id']}@{row['instance_domain']} has {len(found)} embeddings in whitelist.db"
        rowids.append(found[0][0])
    return status, rowids


@contextmanager
def _cache_variant(tmp_path: Path, cache_path: Path, interval_minutes: float, refresh_flag: str, gate: Path | None = None) -> Iterator[ClientBackend]:
    """A real Engine on the repo's dataset with its random cache at `cache_path`, size 200 and the given interval, healthy on its own port; stopped on exit."""
    overrides = {"DEFAULT_RANDOM_CACHE_DB_PATH": str(cache_path), "DEFAULT_RANDOM_CACHE_SIZE": VARIANT_CACHE_SIZE, "RANDOM_CACHE_REFRESH_INTERVAL_MINUTES": interval_minutes, "DEFAULT_RATE_LIMIT_MAX_REQUESTS": RATE_LIMIT}
    # The interval comes from the override; a value in this environment would only be parsed at import.
    env = {key: val for key, val in os.environ.items() if key != "RANDOM_CACHE_REFRESH_INTERVAL_MINUTES"}
    env.update({"ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"})
    log_path = tmp_path / "engine.log"
    port = _free_port()
    http = ClientBackend(f"http://127.0.0.1:{port}", log_path)
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen(
                [str(ENGINE_PY), "-c", CACHE_VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps(overrides), str(gate or ""), str(GATE_BOUND_SECONDS), "--host", "127.0.0.1", "--port", str(port), refresh_flag],
                env=env, stdout=log, stderr=log,
            )
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS
            while proc.poll() is None and time.time() < deadline and not healthy:
                try:
                    healthy = http.request("GET", "/api/health")[0] == 200
                except OSError:
                    pass
                if not healthy:
                    time.sleep(0.1)
        try:
            assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"
            yield http
        finally:
            if gate is not None:
                (gate / "release").touch()
            proc.terminate()
            try:
                proc.wait(timeout=STOP_WITHIN_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


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


@pytest.mark.parametrize("active", ["seeded", "missing", "leftover"])
def test_build_writes_a_complete_cache_into_the_pid_temp_file_only(tmp_path: Path, active: str) -> None:
    """`build_random_cache` returns `<stem>.tmp.<pid><suffix>` beside the active file holding positions 1..20 over source rowids 1..20, leaves no sidecar, and leaves the active file as it was."""
    source = _source_db(tmp_path)
    active_path = tmp_path / "db" / "random-cache.db"
    expected_temp = tmp_path / "db" / f"random-cache.tmp.{os.getpid()}.db"
    active_path.parent.mkdir()
    if active != "missing":
        _seed_cache(active_path, [(position, STALE_ROWID) for position in range(1, 6)])
    if active == "leftover":
        # Left by an earlier process with this pid; sqlite refuses it as "file is not a database", so only a build that clears it first gets through.
        expected_temp.write_bytes(b"not a sqlite database" * 10)
    active_bytes = active_path.read_bytes() if active_path.exists() else None

    temp_path, count, _ = random_cache.build_random_cache(tmp_path / "source.db", active_path, 100, True, 0, 100)
    source.close()

    assert temp_path == expected_temp
    assert count == SOURCE_ROWS
    # Listed before any read, so no sidecar a reader could create is counted; a left-open write or a persisted journal shows here as `-journal`.
    expected_names = {expected_temp.name} if active == "missing" else {expected_temp.name, active_path.name}
    assert _names(active_path.parent) == expected_names
    assert (active_path.read_bytes() if active_path.exists() else None) == active_bytes
    rows = _cache_rows(expected_temp)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))


def test_build_failure_removes_the_temp_file_and_leaves_the_active_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `populate_random_cache` that writes into the temp file and then raises: `build_random_cache` re-raises and the directory holds only the unchanged active file."""
    source = _source_db(tmp_path)
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_cache(active_path, [(position, STALE_ROWID) for position in range(1, 6)])
    active_bytes = active_path.read_bytes()
    real_populate = random_cache.populate_random_cache
    temp_existed: list[bool] = []

    def populate_then_raise(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        real_populate(src_db, cache_db, *args, **kwargs)
        # Uncommitted, so the connection is mid-write when the exception leaves it.
        cache_db.execute("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", (SOURCE_ROWS + 1, STALE_ROWID))
        temp_existed.append((tmp_path / "db" / f"random-cache.tmp.{os.getpid()}.db").exists())
        raise RuntimeError(FAILURE_MESSAGE)

    monkeypatch.setattr(random_cache, "populate_random_cache", populate_then_raise)
    with pytest.raises(RuntimeError, match=FAILURE_MESSAGE):
        random_cache.build_random_cache(tmp_path / "source.db", active_path, 100, True, 0, 100)
    source.close()

    # Control: the build reached the patched step with its temp file on disk, so its absence below is the cleanup's doing.
    assert temp_existed == [True]
    assert _names(active_path.parent) == {active_path.name}
    assert active_path.read_bytes() == active_bytes


def test_refresh_serves_a_new_readonly_handle_on_the_renamed_file_and_closes_the_old(tmp_path: Path) -> None:
    """A refresh leaves a new inode at the active path and nothing else, serves it through a new read-only handle that reads its rows, and closes the old handle."""
    active_path, owner = _seeded(tmp_path)
    seeded_inode = active_path.stat().st_ino
    old = owner.random_cache_db

    swapped = _refresh(tmp_path, active_path, owner)

    assert swapped is True
    # The seeded file still exists when the temp file is created beside it, so the two cannot share an inode; an in-place write keeps it.
    assert active_path.stat().st_ino != seeded_inode
    assert _names(active_path.parent) == {active_path.name}
    assert owner.random_cache_db is not old
    served = _served_rowids(owner)
    assert sorted(served) == list(range(1, SOURCE_ROWS + 1))
    # Same order as the file now at the active path, which the build shuffled, so the handle reads that file and not a copy of the rows.
    assert served == _cache_rowids(active_path)
    with pytest.raises(sqlite3.ProgrammingError):
        old.execute("SELECT 1")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        owner.random_cache_db.execute("DELETE FROM random_rowids")
    owner.random_cache_db.close()


@pytest.mark.parametrize("journal", ["memory", "disk"])
def test_second_same_pid_build_leaves_the_served_handle_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, journal: str) -> None:
    """After one swap, a second same-pid build paused mid-write puts no journal at the served handle's name, and the served handle reads the first build's rows; with an on-disk journal the same read fails."""
    active_path, owner = _seeded(tmp_path)
    assert _refresh(tmp_path, active_path, owner) is True
    # The served handle was opened on the first build's temp name, and sqlite fixed its journal name then.
    served_journal = active_path.parent / f"random-cache.tmp.{os.getpid()}.db-journal"
    first_rowids = _served_rowids(owner)

    if journal == "disk":
        def connect_with_disk_journal(path: Path) -> sqlite3.Connection:
            conn = sqlite3.connect(path.as_posix(), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

        monkeypatch.setattr(random_cache, "connect_random_cache_db", connect_with_disk_journal)

    real_populate = random_cache.populate_random_cache
    paused = threading.Event()
    release = threading.Event()

    def populate_paused(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        cache_db.execute(f"PRAGMA cache_size={SPILL_CACHE_PAGES}")
        cache_db.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(index, index) for index in range(1, SPILL_ROWS + 1)])
        paused.set()
        release.wait(WAIT_SECONDS)
        return real_populate(src_db, cache_db, *args, **kwargs)

    monkeypatch.setattr(random_cache, "populate_random_cache", populate_paused)
    results: list[bool] = []
    builder = threading.Thread(target=lambda: results.append(_refresh(tmp_path, active_path, owner)))
    builder.start()
    try:
        assert paused.wait(WAIT_SECONDS), "the second build never reached its paused write"
        journal_on_disk = served_journal.exists()
        try:
            read: list[int] | sqlite3.Error = _served_rowids(owner)
        except sqlite3.Error as exc:
            read = exc
    finally:
        release.set()
        builder.join(WAIT_SECONDS)

    if journal == "disk":
        # Control: an on-disk journal at the served handle's name looks hot to it and fails its read, so this test can see the defect.
        assert journal_on_disk is True
        assert isinstance(read, sqlite3.OperationalError)
    else:
        assert journal_on_disk is False
        assert read == first_rowids
    assert results == [True]
    owner.random_cache_db.close()


def test_readers_under_the_lock_never_fail_or_come_back_empty_across_refresh_cycles(tmp_path: Path) -> None:
    """Three threads reading under the owner's lock through 10 refreshes, all of which swap, never raise and never get an empty result."""
    active_path, owner = _seeded(tmp_path)
    stop_reading = threading.Event()
    first_read = [threading.Event() for _ in range(READER_THREADS)]
    reads = [0] * READER_THREADS
    errors: list[str] = []
    empties: list[int] = []

    def read_loop(index: int) -> None:
        while not stop_reading.is_set():
            try:
                with owner.random_cache_lock:
                    rowids = random_cache.fetch_random_rowids(owner.random_cache_db, READ_LIMIT)
            except Exception as exc:
                errors.append(repr(exc))
                return
            if not rowids:
                empties.append(index)
            reads[index] += 1
            first_read[index].set()

    readers = [threading.Thread(target=read_loop, args=(index,)) for index in range(READER_THREADS)]
    for reader in readers:
        reader.start()
    try:
        started = [event.wait(WAIT_SECONDS) for event in first_read]
        reads_before = sum(reads)
        swaps = [_refresh(tmp_path, active_path, owner) for _ in range(REFRESH_CYCLES)]
        reads_during = sum(reads) - reads_before
    finally:
        stop_reading.set()
        for reader in readers:
            reader.join(WAIT_SECONDS)

    # Control: every reader was reading before the cycles began and reads continued through them, so the swaps ran under live reads.
    assert started == [True] * READER_THREADS
    assert reads_during > 0
    assert swaps == [True] * REFRESH_CYCLES
    assert errors == []
    assert empties == []
    owner.random_cache_db.close()


@pytest.mark.parametrize("stage", ["build", "check", "rename"])
def test_refresh_failure_keeps_the_active_file_and_the_handle_and_removes_the_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, stage: str) -> None:
    """A refresh whose build raises after writing, whose build fails the check, or whose rename is refused returns False, logs `failed` with the reason, and leaves only the unchanged active file, served through the same handle."""
    active_path, owner = _seeded(tmp_path)
    active_bytes = active_path.read_bytes()
    old = owner.random_cache_db
    temp_path = active_path.parent / f"random-cache.tmp.{os.getpid()}.db"
    real_populate = random_cache.populate_random_cache
    temp_existed: list[bool] = []

    def populate_then_raise(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        real_populate(src_db, cache_db, *args, **kwargs)
        # Uncommitted, so the connection is mid-write when the exception leaves it.
        cache_db.execute("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", (SOURCE_ROWS + 1, STALE_ROWID))
        temp_existed.append(temp_path.exists())
        raise RuntimeError(FAILURE_MESSAGE)

    def populate_without_table(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        count = real_populate(src_db, cache_db, *args, **kwargs)
        # The build completes, but the file it leaves cannot answer a count on random_rowids.
        cache_db.execute("DROP TABLE random_rowids")
        cache_db.commit()
        temp_existed.append(temp_path.exists())
        return count

    def refuse_replace(src: str | os.PathLike, dst: str | os.PathLike) -> None:
        temp_existed.append(Path(src).exists())
        raise OSError(RENAME_REFUSED)

    if stage == "build":
        monkeypatch.setattr(random_cache, "populate_random_cache", populate_then_raise)
        reason = FAILURE_MESSAGE
    elif stage == "check":
        monkeypatch.setattr(random_cache, "populate_random_cache", populate_without_table)
        reason = "no such table"
    else:
        monkeypatch.setattr(os, "replace", refuse_replace)
        reason = RENAME_REFUSED
    caplog.set_level(logging.INFO)

    swapped = _refresh(tmp_path, active_path, owner)
    monkeypatch.undo()

    # Control: the refresh reached the failing stage with its temp file on disk, so its absence below is the cleanup's doing.
    assert temp_existed == [True]
    assert swapped is False
    failure_lines = [record.getMessage() for record in caplog.records if "failed" in record.getMessage()]
    assert any(reason in line for line in failure_lines), failure_lines
    assert active_path.read_bytes() == active_bytes
    assert owner.random_cache_db is old
    assert _served_rowids(owner) == SEEDED_ROWIDS
    assert _names(active_path.parent) == {active_path.name}
    old.close()


def test_stop_set_before_the_swap_keeps_the_active_file_and_the_handle_and_removes_the_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stop event set during the build: the refresh returns False and leaves only the unchanged active file, served through the same handle."""
    active_path, owner = _seeded(tmp_path)
    active_bytes = active_path.read_bytes()
    old = owner.random_cache_db
    temp_path = active_path.parent / f"random-cache.tmp.{os.getpid()}.db"
    stop_event = threading.Event()
    real_populate = random_cache.populate_random_cache
    temp_existed: list[bool] = []

    def populate_then_stop(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        count = real_populate(src_db, cache_db, *args, **kwargs)
        temp_existed.append(temp_path.exists())
        stop_event.set()
        return count

    monkeypatch.setattr(random_cache, "populate_random_cache", populate_then_stop)

    swapped = _refresh(tmp_path, active_path, owner, stop_event)

    # Control: the build ran to a full temp file before the stop, so the stop is what kept it out.
    assert temp_existed == [True]
    assert swapped is False
    assert active_path.read_bytes() == active_bytes
    assert owner.random_cache_db is old
    assert _served_rowids(owner) == SEEDED_ROWIDS
    assert _names(active_path.parent) == {active_path.name}
    old.close()


@pytest.mark.parametrize("state", ["missing", "no_table", "empty"])
def test_a_missing_tableless_or_empty_cache_is_not_usable(tmp_path: Path, state: str) -> None:
    """`open_random_cache_if_usable` gives None for a missing file, a file without `random_rowids`, and an empty table; a missing file is not created."""
    path = tmp_path / "random-cache.db"
    if state == "no_table":
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE other (x INTEGER)")
        conn.commit()
        conn.close()
    elif state == "empty":
        _seed_cache(path, [])
    usable_path = tmp_path / "usable" / "random-cache.db"
    _seed_cache(usable_path, SEEDED_ROWS)

    usable = random_cache.open_random_cache_if_usable(usable_path)
    opened = random_cache.open_random_cache_if_usable(path)

    # Control: the same opener gives a handle on a 3-row cache in this run, so the None below is its verdict on this state.
    assert usable is not None
    usable.close()
    assert opened is None
    assert path.exists() is (state != "missing")


@pytest.mark.parametrize("lock", ["free", "held"])
def test_a_non_empty_cache_opens_read_only_even_under_a_held_write_lock(tmp_path: Path, lock: str) -> None:
    """`open_random_cache_if_usable` on a 3-row cache gives a handle that reads the rows as seeded and refuses a write as readonly, whether or not another connection holds `BEGIN IMMEDIATE` on the file."""
    path = tmp_path / "random-cache.db"
    _seed_cache(path, SEEDED_ROWS)
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        if lock == "held":
            holder.execute("BEGIN IMMEDIATE")
            # Control: the lock is armed, so an opener that writes on open fails on it.
            probe = sqlite3.connect(path, timeout=0)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                probe.execute("DELETE FROM random_rowids WHERE 0")
            probe.close()

        opened = random_cache.open_random_cache_if_usable(path)

        assert opened is not None
        try:
            assert [tuple(row) for row in opened.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()] == SEEDED_ROWS
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                opened.execute("DELETE FROM random_rowids")
        finally:
            opened.close()
    finally:
        if lock == "held":
            holder.execute("ROLLBACK")
        holder.close()


@pytest.mark.parametrize("startup_build", [False, True], ids=["no_startup_build", "startup_build"])
def test_worker_with_interval_0_returns_after_at_most_the_startup_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, startup_build: bool) -> None:
    """`run_random_cache_worker` with interval 0 returns within 5 s: without a startup build having built nothing and changed nothing, with one having built exactly once and swapped the result in."""
    _source_db(tmp_path).close()
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_cache(active_path, SEEDED_ROWS)
    active_bytes = active_path.read_bytes()
    owner = SimpleNamespace(random_cache_db=db.connect_readonly_db(active_path), random_cache_lock=threading.Lock())
    old = owner.random_cache_db
    real_build = random_cache.build_random_cache
    builds: list[int] = []

    def counting_build(*args, **kwargs):
        builds.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(random_cache, "build_random_cache", counting_build)
    stop_event = threading.Event()
    worker = threading.Thread(
        target=random_cache.run_random_cache_worker,
        args=(tmp_path / "source.db", active_path, BUILD_SIZE, True, 0, 100, owner, stop_event),
        kwargs={"startup_build": startup_build, "interval_seconds": 0},
        daemon=True,
    )
    worker.start()
    worker.join(RETURN_WITHIN_SECONDS)
    returned = not worker.is_alive()
    # Stops a worker that did not return, so a failing run does not keep building.
    stop_event.set()
    worker.join(RETURN_WITHIN_SECONDS)

    assert returned is True
    assert _names(active_path.parent) == {active_path.name}
    if startup_build:
        assert len(builds) == 1
        assert owner.random_cache_db is not old
        assert sorted(_served_rowids(owner)) == list(range(1, SOURCE_ROWS + 1))
    else:
        assert builds == []
        assert owner.random_cache_db is old
        assert _served_rowids(owner) == SEEDED_ROWIDS
        assert active_path.read_bytes() == active_bytes
    owner.random_cache_db.close()


def test_engines_starting_at_once_all_become_healthy(engine, tmp_path: Path) -> None:
    """Eight Engines launched at once with refresh off, no start lock and the checkout's non-empty cache write-locked by another connection: none exits and all answer `/api/health` 200 within 120 s.

    Each Engine opens the non-empty cache read-only, which the held write lock does not block, and with refresh off runs no startup build, so it listens without writing the cache; a start that wrote the cache would wait on the lock and never become healthy. Each Engine is started as `server.py --host 127.0.0.1 --port <own port> --no-random-cache-refresh` with `ENGINE_INGEST_MODE=bridge`, the bridge token and `RECOMMENDATIONS_DEBUG=1`. The session `engine` fixture is what leaves the checkout's cache non-empty.
    """
    cache = sqlite3.connect(f"file:{RANDOM_CACHE_DB}?mode=ro", uri=True)
    cached_rows = cache.execute("SELECT COUNT(*) FROM random_rowids").fetchone()[0]
    cache.close()
    # Control: a non-empty cache is usable, so a refresh-off start serves it and runs no startup build.
    assert cached_rows > 0, "the session Engine left the checkout's random-cache.db empty"
    # Control: a start that filled the cache towards its size would write a short cache and leave a full one alone, so only a short one shows a start that never writes it.
    assert cached_rows < server_config.DEFAULT_RANDOM_CACHE_SIZE, f"the checkout's random-cache.db holds {cached_rows} rows, not short of {server_config.DEFAULT_RANDOM_CACHE_SIZE}, so a start that fills it towards size would not write it either"

    holder = sqlite3.connect(RANDOM_CACHE_DB, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    procs: list[subprocess.Popen] = []
    try:
        # Control: the lock is armed, so a start that writes the active cache file waits on it instead of becoming healthy.
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
        # An Engine blocked in sqlite on the held lock does not act on SIGTERM until the call returns, so a straggler is killed at the deadline.
        stop_deadline = time.time() + STOP_WITHIN_SECONDS
        for proc in procs:
            try:
                proc.wait(timeout=max(0.0, stop_deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        holder.execute("ROLLBACK")
        holder.close()


def test_refresh_on_engine_serves_its_usable_cache_while_the_startup_build_is_held_then_swaps_in_200_rows(tmp_path: Path) -> None:
    """A refresh-on Engine over a seeded 20-row cache, its startup build held at a gate, answers health and serves the random feed from the seeded file; released, it logs one `ok` for 200 rows and the path holds them at a new inode."""
    dataset = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    cache_path = tmp_path / "db" / "random-cache.db"
    seeded = _seed_servable_cache(dataset, cache_path)
    seeded_inode = cache_path.stat().st_ino
    gate = tmp_path / "gate"
    gate.mkdir()
    entered = gate / "entered"
    log_path = tmp_path / "engine.log"
    try:
        with _cache_variant(tmp_path, cache_path, 0, "--random-cache-refresh", gate) as engine_http:
            deadline = time.time() + ENTERED_WITHIN_SECONDS
            while not entered.exists() and time.time() < deadline:
                time.sleep(0.1)
            # The build is running and held, so every answer below comes before any build finishes.
            assert entered.exists(), f"no build reached the gate within {ENTERED_WITHIN_SECONDS}s of the Engine answering health; see {log_path}"
            assert engine_http.request("GET", "/api/health")[0] == 200
            status, rowids = _feed_rowids(engine_http, dataset)
            assert status == 200
            assert rowids and set(rowids) <= set(seeded), rowids
            assert cache_path.stat().st_ino == seeded_inode
            assert _cache_rowids(cache_path) == seeded
            assert _messages(log_path, OK_PREFIX) == []

            (gate / "release").touch()
            deadline = time.time() + OK_WITHIN_SECONDS
            while not _messages(log_path, OK_PREFIX) and time.time() < deadline:
                time.sleep(0.1)
            time.sleep(SETTLE_SECONDS)
            ok_lines = _messages(log_path, OK_PREFIX)
            assert len(ok_lines) == 1, ok_lines
            ok = _tokens(ok_lines[0])
            assert (ok.get("size"), ok.get("path")) == (str(VARIANT_CACHE_SIZE), str(cache_path)), ok_lines
            assert len(_cache_rowids(cache_path)) == VARIANT_CACHE_SIZE
            assert cache_path.stat().st_ino != seeded_inode
            # Interval 0: the startup build is the only one.
            assert entered.read_text().splitlines() == ["entered"]
            assert len(_messages(log_path, START_PREFIX)) == 1
    finally:
        dataset.close()


def test_positive_interval_swaps_a_new_file_in_each_tick_while_the_random_feed_serves_the_current_one(tmp_path: Path) -> None:
    """An Engine with interval 0.25 min, refresh off and no cache file logs three `ok` lines, the path at a new inode after each; the random feed answers 200 with rows throughout and, after each `ok`, only with rowids of the file then at the path."""
    dataset = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    cache_path = tmp_path / "db" / "random-cache.db"
    cache_path.parent.mkdir()
    log_path = tmp_path / "engine.log"
    inodes: list[int] = []
    bad_answers: list[tuple[int, int]] = []
    foreign: list[list[int]] = []
    requests = 0
    try:
        with _cache_variant(tmp_path, cache_path, SHORT_INTERVAL_MINUTES, "--no-random-cache-refresh") as engine_http:
            deadline = time.time() + TICKS_WITHIN_SECONDS
            while len(inodes) < TICKS and time.time() < deadline:
                status, rowids = _feed_rowids(engine_http, dataset)
                requests += 1
                if status != 200 or not rowids:
                    bad_answers.append((status, len(rowids)))
                if len(_messages(log_path, OK_PREFIX)) > len(inodes):
                    # A tick is 15 s, so nothing swaps between these reads and the request after them.
                    inodes.append(cache_path.stat().st_ino)
                    current = set(_cache_rowids(cache_path))
                    status, rowids = _feed_rowids(engine_http, dataset)
                    requests += 1
                    if status != 200 or not rowids:
                        bad_answers.append((status, len(rowids)))
                    if not set(rowids) <= current:
                        foreign.append(sorted(set(rowids) - current))
                time.sleep(FEED_PAUSE_SECONDS)
    finally:
        dataset.close()

    assert len(inodes) >= TICKS, f"{len(inodes)} ok lines within {TICKS_WITHIN_SECONDS}s; see {log_path}"
    # Each new file is written while the previous one is still open at the path, so consecutive files cannot share an inode.
    assert all(before != after for before, after in zip(inodes, inodes[1:])), inodes
    # Control: the feed was requested between the swaps, not only once after each.
    assert requests > len(inodes)
    assert bad_answers == []
    assert foreign == []


def test_refresh_off_engine_over_a_usable_cache_with_interval_0_starts_no_build(tmp_path: Path) -> None:
    """A refresh-off Engine with interval 0 and the gate set enters it within the watch window when its cache file is missing; over a seeded 20-row cache the same Engine reaches no build in that window: nothing enters the gate, no start line is logged, and the seeded file stays at its inode and serves the random feed."""
    # Control: the same flags and interval over a missing cache do build, and the gate and log see it inside the window the usable case is watched for.
    control_dir = tmp_path / "control"
    control_cache = control_dir / "db" / "random-cache.db"
    control_cache.parent.mkdir(parents=True)
    control_gate = control_dir / "gate"
    control_gate.mkdir()
    with _cache_variant(control_dir, control_cache, 0, "--no-random-cache-refresh", control_gate):
        deadline = time.time() + NO_BUILD_WINDOW_SECONDS
        while not (control_gate / "entered").exists() and time.time() < deadline:
            time.sleep(0.1)
        assert (control_gate / "entered").exists(), f"the missing-cache control reached no build within {NO_BUILD_WINDOW_SECONDS}s of health; see {control_dir / 'engine.log'}"
        assert len(_messages(control_dir / "engine.log", START_PREFIX)) == 1
    dataset = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    cache_path = tmp_path / "db" / "random-cache.db"
    seeded = _seed_servable_cache(dataset, cache_path)
    seeded_inode = cache_path.stat().st_ino
    gate = tmp_path / "gate"
    gate.mkdir()
    entered = gate / "entered"
    log_path = tmp_path / "engine.log"
    try:
        # The interval is 0 by the override, the same one that runs the refresh-on sibling's single build.
        with _cache_variant(tmp_path, cache_path, 0, "--no-random-cache-refresh", gate) as engine_http:
            # Control: the Engine started and took the refresh-off flag.
            assert _has_started(log_path)
            modes = [_tokens(message) for message in _messages(log_path, MODE_PREFIX)]
            assert modes and all(mode.get("random_cache_refresh") == "false" for mode in modes), modes
            time.sleep(NO_BUILD_WINDOW_SECONDS)
            status, rowids = _feed_rowids(engine_http, dataset)

            assert not entered.exists()
            assert _messages(log_path, START_PREFIX) == []
            assert cache_path.stat().st_ino == seeded_inode
            assert _cache_rowids(cache_path) == seeded
            assert status == 200
            assert rowids and set(rowids) <= set(seeded), rowids
    finally:
        dataset.close()
