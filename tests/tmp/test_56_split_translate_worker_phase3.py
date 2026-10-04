"""Phase 3 checkpoint for `engine/server/db/jobs/translate-worker.py`: `run --stall-seconds` reaches the heartbeat, so the stall threshold is the one the operator gave on the command line.

- `run --stall-seconds 4`, the script run under `ENGINE_PY` with every path under `tmp_path`, beats while idle with its own pid; once its main loop claims a queued job and blocks in that job's whitelist lookup, which the test holds on an EXCLUSIVE lock, the heartbeat row keeps the same `beat_at` over 11 s, two due 5 s ticks, while the worker is alive and the job still `running`. After the lock is released the job ends `failed` with `not in whitelist`, and within 8 s the row gets a new `beat_at`, no earlier than the release, carrying the subprocess's pid; SIGTERM then ends it with exit 0.
- `run --stall-seconds 60`, held the same way for the same time, writes a newer `beat_at` with its own pid by the end of the 11 s window, so the stop above follows the given 4 s and not a threshold fixed in the worker.
"""
from __future__ import annotations

import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import BEAT_WINDOW_SECONDS, FIRST_BEAT_SECONDS, RESUME_SECONDS, STALL_KEY, STALLED_WINDOW_SECONDS, STOP_WINDOW_SECONDS, _beat, _jobs, _next_beat, _now_ms, _paths, _require_tools, _run_argv, _whitelist, connect_subtitles_db, enqueue_translate_job  # noqa: E402

# Twice the idle loop's 2 s poll, so an idle worker never trips it, and under one 5 s tick, so at most one beat follows the claim.
TEST_STALL_SECONDS = 4
# Well past the ~18 s the main loop is held below, so a worker honouring it keeps beating through the stall.
LONG_STALL_SECONDS = 60


def _hold_main_loop(paths: dict[str, Path], proc: subprocess.Popen, out_path: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None, int]:
    """Hold whitelist.db EXCLUSIVE, queue one job, wait for the main loop to claim it, then read the heartbeat row one stall threshold plus 1 s after the claim and again STALLED_WINDOW_SECONDS later; (first reading, second reading, release time in wall-clock ms)."""
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
        assert proc.poll() is None, (proc.returncode, out_path.read_text(encoding="utf-8", errors="replace"))  # control: the worker is alive, so a silence is not an exit
        assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop is still held, so it stalled for the whole window
        after = _beat(paths["subtitles"])
        released_ms = _now_ms()
    finally:
        holder.close()
    return stalled, after, released_ms


def _stop(proc: subprocess.Popen) -> int:
    proc.send_signal(signal.SIGTERM)
    try:
        return proc.wait(timeout=STOP_WINDOW_SECONDS)
    except subprocess.TimeoutExpired:
        pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")


def test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on(tmp_path: Path) -> None:
    """`run --stall-seconds 4` beats while idle; while its main loop is held in a claimed job's whitelist lookup the row's `beat_at` stays put over two due ticks; once the lookup returns, the job fails `not in whitelist`, beating resumes with the subprocess's pid after the release, and SIGTERM ends it with exit 0."""
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"], [], deny=False)
    argv = _run_argv(paths) + ["--stall-seconds", str(TEST_STALL_SECONDS)]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            idle = _next_beat(paths["subtitles"], proc, first, BEAT_WINDOW_SECONDS) if first is not None else None
            assert idle is not None and idle[1] == proc.pid, (first, idle, proc.poll(), out_path.read_text(encoding="utf-8", errors="replace"))  # C1: the worker beats while idle under the given threshold, so the silence below is a stop

            stalled, after, released_ms = _hold_main_loop(paths, proc, out_path)
            assert stalled is not None and after == stalled, (stalled, after)  # C1: no beat over two due ticks while the main loop is stalled past the given 4 s; the 600 s default would beat here

            resumed = _next_beat(paths["subtitles"], proc, stalled, RESUME_SECONDS)
            assert resumed is not None, (stalled, proc.poll(), _jobs(paths["subtitles"]), out_path.read_text(encoding="utf-8", errors="replace"))  # C1: beating resumes once the main loop moves on
            assert resumed[1] == proc.pid, (resumed, proc.pid)  # C1: the running worker's own beat
            assert resumed[0] >= released_ms, (resumed, released_ms)  # C1: written after the main loop was let go
            assert _jobs(paths["subtitles"]) == [("failed", "not in whitelist")]  # control: the main loop finished the job it was held in

            code = _stop(proc)
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # control: a clean stop, so nothing above ran in a dying worker
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall(tmp_path: Path) -> None:
    """`run --stall-seconds 60`, its main loop held in a claimed job's whitelist lookup for the same window, writes a newer `beat_at` with the subprocess's pid by the window's end, so the stop in the 4 s test follows the operator's value and not a threshold fixed in the worker."""
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"], [], deny=False)
    argv = _run_argv(paths) + ["--stall-seconds", str(LONG_STALL_SECONDS)]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            assert first is not None and first[1] == proc.pid, (first, proc.poll(), out_path.read_text(encoding="utf-8", errors="replace"))  # control: the worker is up and has made the heartbeat table

            stalled, after, _ = _hold_main_loop(paths, proc, out_path)
            assert stalled is not None and after is not None and after[0] > stalled[0], (stalled, after)  # C1: under a 60 s threshold the same stall does not stop the beat, so the 4 s stop is the flag's
            assert after[1] == proc.pid, (after, proc.pid)  # C1: the beat over the stall is this worker's own

            code = _stop(proc)
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # control: a clean stop
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
