"""`open_random_cache_if_usable` opens a usable random cache read-only; the Engine serves a usable cache from startup, runs its builds in the background after it listens, and swaps a new cache in on each tick of a positive interval.

- `open_random_cache_if_usable` gives None for a missing file (and does not create it), a file without `random_rowids`, and an empty table. For a 3-row cache it gives a handle that reads the three rows as seeded and fails a write "readonly", both with the file free and with another connection holding `BEGIN IMMEDIATE` on it.
- `run_random_cache_worker` with interval 0 and no startup build returns within 5 s having built nothing, leaving the owner's handle, the active file's bytes and the directory as they were. With a startup build it returns within 5 s having built exactly once, and the owner serves a new handle on the rebuilt file, the only file left.
- A refresh-on Engine over a seeded 20-row cache, interval 0, its startup build held at a gate: once the build has entered the gate, `/api/health` answers 200, and the random feed answers 200 with rows that all map into the seeded rowids while the seeded file is still at its inode. No `ok` line is logged while held. Released, it logs exactly one `ok` line with size 200 for the tmp path, which then holds 200 rows at a new inode. The gate was entered exactly once and one `random cache build start` line was logged.
- An Engine with interval 0.25 min, refresh off and no cache file logs at least three `ok` lines, the file at a different inode after each than after the one before. The random feed, requested throughout, answers 200 with rows every time, and after each `ok` its rows all map into the rowids of the file then at the path.
- A refresh-off Engine, interval 0, with a gate set, over a missing cache file enters the gate within 5 s of answering health and logs one `random cache build start` line. The same Engine over the same seeded 20-row cache, which logged `random_cache_refresh=false`: 5 s after it answers health, no build has entered the gate, no `random cache build start` line is logged, the seeded file is at its inode with its rows, and the random feed answers 200 with rows that all map into the seeded rowids.

The in-process tests use temporary sqlite files and a `SimpleNamespace` owner with a `threading.Lock`. The Engine tests run the real `server.py` on the repo's dataset through CACHE_VARIANT_RUNNER, with the config module's cache path, size, interval and rate limit overridden; rows are mapped to rowids through a read-only `whitelist.db`.
"""
from __future__ import annotations

import fcntl
import json
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

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ACTIVE_DIR = ROOT / "tests" / "active"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it; tests/tmp has no conftest, so the active one is imported by name.
for path in (SERVER_DIR, SERVER_DIR / "api", ACTIVE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.db as db  # noqa: E402
import data.random_cache as random_cache  # noqa: E402
# `engine` is imported so pytest registers the session fixture in this module.
from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, WHITELIST_DB, ClientBackend, _free_port  # noqa: E402

SOURCE_ROWS = 20
SEEDED_ROWS = [(1, 7), (2, 3), (3, 11)]
SEEDED_ROWIDS = [7, 3, 11]
# Above the source's 20 rows, so every in-process build holds the whole source.
BUILD_SIZE = 100
READ_ALL = 100
RETURN_WITHIN_SECONDS = 5
VARIANT_CACHE_SIZE = 200
# 15 s ticks: the startup build and two ticks put three builds in about 30 s, well inside TICKS_WITHIN_SECONDS.
SHORT_INTERVAL_MINUTES = 0.25
TICKS = 3
TICKS_WITHIN_SECONDS = 90
HEALTHY_WITHIN_SECONDS = 120
ENTERED_WITHIN_SECONDS = 30
OK_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
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


def _source_db(tmp_path: Path) -> None:
    """A source of 20 embedded videos, rowids 1..20, one instance, three channels."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT)")
    for index in range(1, SOURCE_ROWS + 1):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example')", (f"v{index}",))
    conn.commit()
    conn.close()


def _seed_cache(path: Path, rows: list[tuple[int, int]]) -> None:
    """Write a random cache file holding exactly `rows`, through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _cache_rowids(path: Path) -> list[int]:
    """A cache file's rowids in position order, read through a read-only handle so a missing file is never created."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT video_rowid FROM random_rowids ORDER BY position").fetchall()]
    finally:
        conn.close()


def _seed_servable_cache(dataset: sqlite3.Connection, cache_path: Path) -> list[int]:
    """Seed `cache_path` with the first 20 rowids the random feed can serve, and return them in position order."""
    # Rows the random feed's metadata join keeps: a matching videos row and an error count under the Engine's threshold of 3.
    seeded = [row[0] for row in dataset.execute("SELECT e.rowid FROM video_embeddings e JOIN videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain WHERE v.error_count IS NULL OR v.error_count < 3 ORDER BY e.rowid LIMIT ?", (SEEDED_CACHE_ROWS,)).fetchall()]
    assert len(seeded) == SEEDED_CACHE_ROWS
    _seed_cache(cache_path, list(enumerate(seeded, start=1)))
    return seeded


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


def _served_rowids(owner: SimpleNamespace) -> list[int]:
    """Read the whole cache through the owner's current handle, holding its lock as the request path does."""
    with owner.random_cache_lock:
        return random_cache.fetch_random_rowids(owner.random_cache_db, READ_ALL)


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
    assert opened is None  # C1
    assert path.exists() is (state != "missing")  # C1


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

        assert opened is not None  # C1
        try:
            assert [tuple(row) for row in opened.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()] == SEEDED_ROWS  # C1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                opened.execute("DELETE FROM random_rowids")  # C1
        finally:
            opened.close()
    finally:
        if lock == "held":
            holder.execute("ROLLBACK")
        holder.close()


@pytest.mark.parametrize("startup_build", [False, True], ids=["no_startup_build", "startup_build"])
def test_worker_with_interval_0_returns_after_at_most_the_startup_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, startup_build: bool) -> None:
    """`run_random_cache_worker` with interval 0 returns within 5 s: without a startup build having built nothing and changed nothing, with one having built exactly once and swapped the result in."""
    _source_db(tmp_path)
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

    assert returned is True  # C2
    assert _names(active_path.parent) == {active_path.name}  # C2
    if startup_build:
        assert len(builds) == 1  # C2
        assert owner.random_cache_db is not old  # C2
        assert sorted(_served_rowids(owner)) == list(range(1, SOURCE_ROWS + 1))  # C2
    else:
        assert builds == []  # C2
        assert owner.random_cache_db is old  # C2
        assert _served_rowids(owner) == SEEDED_ROWIDS  # C2
        assert active_path.read_bytes() == active_bytes  # C2
    owner.random_cache_db.close()


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
            assert entered.exists(), f"no build reached the gate within {ENTERED_WITHIN_SECONDS}s of the Engine answering health; see {log_path}"  # C1
            assert engine_http.request("GET", "/api/health")[0] == 200  # C1
            status, rowids = _feed_rowids(engine_http, dataset)
            assert status == 200  # C1
            assert rowids and set(rowids) <= set(seeded), rowids  # C1
            assert cache_path.stat().st_ino == seeded_inode  # C1
            assert _cache_rowids(cache_path) == seeded  # C1
            assert _messages(log_path, OK_PREFIX) == []  # C1

            (gate / "release").touch()
            deadline = time.time() + OK_WITHIN_SECONDS
            while not _messages(log_path, OK_PREFIX) and time.time() < deadline:
                time.sleep(0.1)
            time.sleep(SETTLE_SECONDS)
            ok_lines = _messages(log_path, OK_PREFIX)
            assert len(ok_lines) == 1, ok_lines  # C1
            ok = _tokens(ok_lines[0])
            assert (ok.get("size"), ok.get("path")) == (str(VARIANT_CACHE_SIZE), str(cache_path)), ok_lines  # C1
            assert len(_cache_rowids(cache_path)) == VARIANT_CACHE_SIZE  # C1
            assert cache_path.stat().st_ino != seeded_inode  # C1
            # Interval 0: the startup build is the only one.
            assert entered.read_text().splitlines() == ["entered"]  # C2
            assert len(_messages(log_path, START_PREFIX)) == 1  # C2
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

    assert len(inodes) >= TICKS, f"{len(inodes)} ok lines within {TICKS_WITHIN_SECONDS}s; see {log_path}"  # C2
    # Each new file is written while the previous one is still open at the path, so consecutive files cannot share an inode.
    assert all(before != after for before, after in zip(inodes, inodes[1:])), inodes  # C2
    # Control: the feed was requested between the swaps, not only once after each.
    assert requests > len(inodes)
    assert bad_answers == []  # C2
    assert foreign == []  # C2


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

            assert not entered.exists()  # C1
            assert _messages(log_path, START_PREFIX) == []  # C1
            assert cache_path.stat().st_ino == seeded_inode  # C1
            assert _cache_rowids(cache_path) == seeded  # C1
            assert status == 200  # C1
            assert rowids and set(rowids) <= set(seeded), rowids  # C1
    finally:
        dataset.close()
