"""`run` in `engine/server/db/jobs/translate-worker.py`, plan 49 phase 4: one worker at a time under an flock, beating its heartbeat row every 5 s while idle, and not beating once its main loop has stalled.

Seam: the script run under `ENGINE_PY` as `translate-worker.py --whitelist-db <tmp> --subtitles-db <tmp> run --lock <tmp> --log <tmp>` with an empty queue, so no job is claimed and the model is never loaded; the same `run` started through a `-c` driver that loads the script, lowers its `STALL_SECONDS` to 4 s and calls its `main()`, so the worker's own main loop can be stalled within the test; and `heartbeat_loop(db_path, stop, progress)` called in-process on a thread for the guard's threshold.

Held lock (C1): while the test process holds an flock on the lock file, `run` exits 6 and its log file names the lock's path. With no subtitles.db beforehand, none is created; with a B1-shaped one, it is byte-identical afterwards, still has exactly B1's eight columns and no heartbeat table, and no `-wal`, `-shm` or `-journal` file appears beside it.

Heartbeat (C2): on an idle queue, `run` writes a `translate_worker_heartbeat` row whose pid is the subprocess's own; within 14 s of the first beat the row shows three distinct `beat_at` values, each a wall-clock ms stamp taken during the run, consecutive ones 4.5 to 6.5 s apart. The worker holds the lock while it runs; after SIGTERM it exits 0 within the unit's 60 s, and the lock is then free to a fresh non-blocking flock.

Stall (C2): a driven `run` beats while idle. Once its main loop claims a queued job and blocks in that job's whitelist lookup, which the test holds on an EXCLUSIVE lock, the heartbeat row keeps the same `beat_at` over 11 s, two due 5 s ticks, while the worker is alive and the job is still `running`. After the lock is released the job ends `failed` with `not in whitelist`, and within 8 s the row gets a new `beat_at`, no earlier than the release, carrying the subprocess's pid. In-process, `heartbeat_loop` with `progress['at']` 30 s inside `STALL_SECONDS` beats at its first check; set 1 s past `STALL_SECONDS` it writes no further row over 11 s, two due ticks, and is still running; once `progress['at']` is refreshed it writes a row with this process's pid and a `beat_at` no earlier than the refresh.

Every database, lock and log path the tests hand the worker is under `tmp_path`.
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.subtitles import connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema  # noqa: E402

# B1's CREATE TABLE as delivered (subtitles.py before plan 49), so a refused run is shown to leave the shape the Engine wrote in production untouched.
B1_CREATE = """
CREATE TABLE IF NOT EXISTS subtitles (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  target_language TEXT NOT NULL,
  state TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  track_text TEXT,
  cues_json TEXT,
  PRIMARY KEY (video_id, instance_domain, target_language)
)
"""
B1_COLUMNS = ["video_id", "instance_domain", "target_language", "state", "source", "fetched_at", "track_text", "cues_json"]
B1_ROW = ("v-1", "peer.example", "en", "ready", "instance", 1700000000000, "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello\n", '[{"start":1.0,"end":2.5,"text":"Hello"}]')
# The unit's TimeoutStopSec.
STOP_WINDOW_SECONDS = 60
# A beater on a 5 s wait was probed writing exactly 5000 ms apart; the margin is for a loaded machine, and still refuses a 4 s or a 7 s cadence.
BEAT_GAP_MS = (4500, 6500)
# Three beats at a 5 s cadence span 10 s; 14 s is that plus slack.
BEAT_WINDOW_SECONDS = 14.0
# Interpreter start, imports and the schema upgrade before the first beat; probed at about 1 s.
FIRST_BEAT_SECONDS = 30.0
# Loads the worker as a module, lowers its STALL_SECONDS to argv[2] and runs its main() on the rest of argv, so a stall shows within the test instead of after 600 s; every function it runs is the script's own.
STALL_DRIVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("translate_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
worker.STALL_SECONDS = float(sys.argv[2])
sys.argv = [sys.argv[1], *sys.argv[3:]]
worker.main()
"""
# Twice the idle loop's 2 s poll, so an idle worker never trips it, and under one 5 s tick, so at most one beat follows the claim.
TEST_STALL_SECONDS = 4.0
# Two 5 s ticks, so an unguarded beater writes at least once in it; with the claim wait and TEST_STALL_SECONDS the whitelist lock is held about 18 s, inside the lookup's 30 s busy timeout.
STALLED_WINDOW_SECONDS = 11.0
# One 5 s tick after the main loop moves on, plus slack.
RESUME_SECONDS = 8.0
# Not in the test's whitelist.db, so the job fails at its lookup and no instance is contacted.
STALL_KEY = ("v-stall", "peer.example")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _worker() -> ModuleType:
    """The worker script as a module; its hyphenated name rules out a plain import."""
    spec = importlib.util.spec_from_file_location("translate_worker_phase4", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {"subtitles": tmp_path / "subtitles.db", "whitelist": tmp_path / "whitelist.db", "lock": tmp_path / "translate-worker.lock", "log": tmp_path / "translate-worker.log"}


def _run_argv(paths: dict[str, Path]) -> list[str]:
    return [str(ENGINE_PY), str(WORKER), "--whitelist-db", str(paths["whitelist"]), "--subtitles-db", str(paths["subtitles"]), "run", "--lock", str(paths["lock"]), "--log", str(paths["log"])]


def _require_tools() -> None:
    assert ENGINE_PY.exists(), f"the Engine interpreter is missing at {ENGINE_PY}"
    # run checks ffmpeg before it takes the lock, so without it every run here would exit 1 for that reason instead.
    if shutil.which("ffmpeg") is None:
        pytest.fail("ffmpeg is not on PATH; the translate worker decodes media with it")


def _locked_by_someone(lock: Path) -> bool:
    fd = os.open(lock.as_posix(), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def _beat(db: Path) -> tuple[int, int] | None:
    """The heartbeat row as (beat_at, pid), or None while the file, the table or the row is missing; mode=ro, so polling never creates the file."""
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    except sqlite3.OperationalError:
        return None
    try:
        row = conn.execute("SELECT beat_at, pid FROM translate_worker_heartbeat WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return (row[0], row[1]) if row is not None else None


def _heartbeat_rows(db: Path) -> list[tuple[int, int]]:
    """Every heartbeat row as (beat_at, pid); unlike _beat it raises on a missing file or table, so an empty list is a read that found no row."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return conn.execute("SELECT beat_at, pid FROM translate_worker_heartbeat").fetchall()
    finally:
        conn.close()


def _next_beat(db: Path, proc: subprocess.Popen, after: tuple[int, int] | None, seconds: float) -> tuple[int, int] | None:
    """The first heartbeat row with a beat_at past `after`'s, polled every 0.2 s for up to `seconds` while proc runs; None if none came."""
    deadline = time.monotonic() + seconds
    while proc.poll() is None and time.monotonic() < deadline:
        row = _beat(db)
        if row is not None and (after is None or row[0] > after[0]):
            return row
        time.sleep(0.2)
    return None


def _jobs(db: Path) -> list[tuple[str, str | None]]:
    """Every subtitles row's (state, error), read mode=ro."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return conn.execute("SELECT state, error FROM subtitles").fetchall()
    finally:
        conn.close()


def _whitelist(path: Path) -> None:
    """A whitelist.db with the tables resolve_video reads and no videos, as phase 2's `_whitelist` builds them, left in its default rollback journal so an EXCLUSIVE lock blocks readers."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    conn.commit()
    conn.close()


def _b1_file(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(B1_CREATE)
    conn.execute("INSERT INTO subtitles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", B1_ROW)
    conn.commit()
    conn.close()


def _sidecars(paths: dict[str, Path]) -> list[str]:
    return sorted(path.name for path in paths["subtitles"].parent.iterdir() if path.name.startswith(paths["subtitles"].name) and path != paths["subtitles"])


@pytest.fixture
def holder(tmp_path: Path):
    """A second open file description holding the worker's flock, as a running worker would."""
    lock = _paths(tmp_path)["lock"]
    fd = os.open(lock.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield lock
    finally:
        os.close(fd)


@pytest.mark.parametrize("b1_file", [False, True], ids=["no-subtitles-db", "b1-subtitles-db"])
def test_run_against_a_held_lock_exits_6_names_the_lock_and_writes_nothing(tmp_path: Path, holder: Path, b1_file: bool) -> None:
    """With the flock held elsewhere, `run` exits 6 and logs the lock's path; an absent subtitles.db is not created, and a B1-shaped one stays byte-identical, with no job column, no heartbeat table and no sidecar file."""
    _require_tools()
    paths = _paths(tmp_path)
    if b1_file:
        _b1_file(paths["subtitles"])
    before = paths["subtitles"].read_bytes() if b1_file else None
    assert _locked_by_someone(holder)  # control: the holder really holds it

    # A run that waited on the lock instead of refusing it raises TimeoutExpired here.
    result = subprocess.run(_run_argv(paths), capture_output=True, text=True, timeout=30, cwd=tmp_path)

    assert result.returncode == 6, (result.returncode, result.stdout, result.stderr)  # C1: the locked exit, not argparse's 2, ffmpeg's 1 or a crash
    log = paths["log"].read_text(encoding="utf-8") if paths["log"].exists() else ""
    assert str(paths["lock"]) in log, (log, result.stdout, result.stderr)  # C1: the log names the held lock
    assert _sidecars(paths) == []  # C1: no -wal, -shm or -journal, so the file was never opened for writing
    if not b1_file:
        assert not paths["subtitles"].exists()  # C1: a refused run creates no subtitles.db
        return
    assert paths["subtitles"].read_bytes() == before  # C1: not one byte written, the WAL switch included
    conn = sqlite3.connect(f"file:{paths['subtitles'].as_posix()}?mode=ro", uri=True)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert columns == B1_COLUMNS, columns  # C1: no job column added
    assert "translate_worker_heartbeat" not in tables, tables  # C1: no heartbeat table, so no heartbeat row


def test_idle_run_beats_with_its_pid_every_5_s_and_releases_the_lock_on_sigterm(tmp_path: Path) -> None:
    """On an idle queue `run` writes heartbeat rows carrying its own pid and a wall-clock ms `beat_at`, three distinct beats 4.5 to 6.5 s apart, holds the lock while it runs, and after SIGTERM exits 0 within 60 s with the lock free."""
    _require_tools()
    paths = _paths(tmp_path)
    start_ms = _now_ms()
    # The worker logs to stdout as well; a file, not a pipe, so a chatty idle loop can never block on a full pipe.
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(_run_argv(paths), stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            beats: list[tuple[int, int, int]] = []
            first_at: float | None = None
            deadline = time.monotonic() + FIRST_BEAT_SECONDS
            while proc.poll() is None and len(beats) < 3 and time.monotonic() < deadline:
                row = _beat(paths["subtitles"])
                if row is not None and (not beats or beats[-1][0] != row[0]):
                    beats.append((row[0], row[1], _now_ms()))
                    if first_at is None:
                        first_at = time.monotonic()
                        deadline = first_at + BEAT_WINDOW_SECONDS
                time.sleep(0.2)
            output = out_path.read_text(encoding="utf-8", errors="replace")
            assert len(beats) == 3, (beats, proc.poll(), output)  # C2: beat_at advanced at least twice within the window
            assert [pid for _, pid, _ in beats] == [proc.pid] * 3, (beats, proc.pid)  # C2: the row carries the running worker's pid
            assert all(start_ms <= beat_at <= seen_ms for beat_at, _, seen_ms in beats), (start_ms, beats)  # C2: beat_at is a wall-clock ms stamp taken during this run
            gaps = [later[0] - earlier[0] for earlier, later in zip(beats, beats[1:])]
            assert all(BEAT_GAP_MS[0] <= gap <= BEAT_GAP_MS[1] for gap in gaps), gaps  # C2: about 5 s apart
            assert proc.poll() is None, (proc.returncode, output)  # control: still serving, so the exit code below answers SIGTERM
            assert _locked_by_someone(paths["lock"])  # control: the running worker holds the lock, so its absence below is a release

            proc.send_signal(signal.SIGTERM)
            try:
                code = proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # C2: a clean stop
            assert not _locked_by_someone(paths["lock"])  # C2: the lock is released, so the next worker can start
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on(tmp_path: Path) -> None:
    """A `run` with STALL_SECONDS lowered to 4 s beats while idle; while its main loop is held in a claimed job's whitelist lookup the row's `beat_at` stays put over two due ticks; once the lookup returns, the job fails `not in whitelist` and beating resumes with the subprocess's pid."""
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"])
    argv = [str(ENGINE_PY), "-c", STALL_DRIVER, str(WORKER), str(TEST_STALL_SECONDS), *_run_argv(paths)[2:]]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            idle = _next_beat(paths["subtitles"], proc, first, BEAT_WINDOW_SECONDS) if first is not None else None
            assert idle is not None and idle[1] == proc.pid, (first, idle, proc.poll(), out_path.read_text(encoding="utf-8", errors="replace"))  # C2: the worker beats while idle under the lowered threshold, so the silence below is a stop

            holder = sqlite3.connect(paths["whitelist"], isolation_level=None)
            try:
                holder.execute("BEGIN EXCLUSIVE")
                conn = connect_subtitles_db(paths["subtitles"])
                try:
                    assert enqueue_translate_job(conn, *STALL_KEY, "en", 50, _now_ms()) == ("queued", "queued")  # control: one job on the queue
                finally:
                    conn.close()
                deadline = time.monotonic() + 10.0
                while _jobs(paths["subtitles"]) != [("running", None)] and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop claimed the job and is now in its whitelist lookup
                time.sleep(TEST_STALL_SECONDS + 1.0)
                stalled = _beat(paths["subtitles"])
                time.sleep(STALLED_WINDOW_SECONDS)
                assert proc.poll() is None, (proc.returncode, out_path.read_text(encoding="utf-8", errors="replace"))  # control: the worker is alive, so the silence below is not an exit
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop is still held, so it stalled for the whole window
                assert _beat(paths["subtitles"]) == stalled, stalled  # C2: no beat over two due ticks while the worker's own main loop is stalled
                released_ms = _now_ms()
            finally:
                holder.close()

            resumed = _next_beat(paths["subtitles"], proc, stalled, RESUME_SECONDS)
            assert resumed is not None, (stalled, proc.poll(), _jobs(paths["subtitles"]), out_path.read_text(encoding="utf-8", errors="replace"))  # C2: beating resumes once the main loop moves on
            assert resumed[1] == proc.pid, (resumed, proc.pid)  # C2: the running worker's own beat
            assert resumed[0] >= released_ms, (resumed, released_ms)  # C2: written after the main loop was let go
            assert _jobs(paths["subtitles"]) == [("failed", "not in whitelist")]  # control: the main loop finished the job it was held in

            proc.send_signal(signal.SIGTERM)
            try:
                code = proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # control: a clean stop, so nothing above ran in a dying worker
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_heartbeat_loop_skips_beats_while_the_main_loop_is_stalled_and_beats_once_it_progresses(tmp_path: Path) -> None:
    """`heartbeat_loop` with `progress['at']` 30 s inside STALL_SECONDS beats at its first check; set 1 s past STALL_SECONDS it writes no further row over two due 5 s ticks, still running; once `progress['at']` is refreshed it writes a row with this process's pid and a `beat_at` no earlier than the refresh."""
    worker = _worker()
    db = tmp_path / "subtitles.db"
    conn = connect_subtitles_db(db)
    ensure_subtitles_schema(conn)
    conn.close()
    assert _heartbeat_rows(db) == []  # control: the table exists and starts empty
    stop = threading.Event()
    progress = {"at": time.monotonic() - worker.STALL_SECONDS + 30}
    thread = threading.Thread(target=worker.heartbeat_loop, args=(db, stop, progress), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 3.0
        while _beat(db) is None and time.monotonic() < deadline:
            time.sleep(0.1)
        first = _beat(db)
        assert first is not None and first[1] == os.getpid(), first  # C2: 30 s inside the threshold its first check beats, so the ticks below were due

        progress["at"] = time.monotonic() - worker.STALL_SECONDS - 1
        time.sleep(STALLED_WINDOW_SECONDS)
        assert thread.is_alive()  # control: the loop is running, so the missing rows below are the guard and not a crash
        assert _heartbeat_rows(db) == [first]  # C2: 1 s past the threshold, two due ticks write nothing

        refreshed_ms = _now_ms()
        progress["at"] = time.monotonic()
        deadline = time.monotonic() + RESUME_SECONDS
        while _beat(db) == first and time.monotonic() < deadline:
            time.sleep(0.1)
        row = _beat(db)
        assert row != first, row  # C2: beating resumes once the main loop progresses
        assert row[1] == os.getpid(), row  # C2: the beating process's pid
        assert row[0] >= refreshed_ms, (row, refreshed_ms)  # C2: a beat written after the refresh
    finally:
        stop.set()
        thread.join(10)
