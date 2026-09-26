"""Checkpoint for plan 05, Phase 1 — per-thread statement deadline.

must_prove:
  C1 — Entering and leaving `statement_deadline` in one thread while another thread's
       statement is running on the same `connect_db` connection returns without waiting
       for that statement.
  C2 — A passed `statement_deadline` interrupts only statements run by the thread that
       set it.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.db import connect_db, is_interrupted_error, statement_deadline  # noqa: E402

# A three-way cartesian COUNT over a recursive series. n=600 runs ~1.5s and returns
# 216,000,000 (observed); n=2000 would take minutes, so it only ends by interruption.
_SERIES = (
    "WITH RECURSIVE s(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM s WHERE x<{n})"
    " SELECT COUNT(*) FROM s a, s b, s c"
)
BOUNDED = _SERIES.format(n=600)
BOUNDED_COUNT = 216_000_000
UNBOUNDED = _SERIES.format(n=2000)

# Runs in a child: under a per-connection handler install this scenario deadlocks the
# whole interpreter, which the asserting process could not survive.
_C1_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from data.db import connect_db, is_interrupted_error, statement_deadline

    conn = connect_db(Path(sys.argv[2]))
    started = threading.Event()
    out = {}

    def other_thread():
        started.set()
        out["other_count"] = conn.execute(sys.argv[3]).fetchone()[0]

    worker = threading.Thread(target=other_thread)
    worker.start()
    started.wait(5)
    time.sleep(0.2)  # let the other thread's statement get under way

    t0 = time.monotonic()
    with statement_deadline(5.0):
        pass
    out["enter_leave_seconds"] = time.monotonic() - t0
    out["other_running_after"] = worker.is_alive()
    worker.join(30)

    try:
        with statement_deadline(0.3):
            conn.execute(sys.argv[4]).fetchone()
        out["own_interrupted"] = False
    except sqlite3.OperationalError as exc:
        out["own_interrupted"] = is_interrupted_error(exc)
    print(json.dumps(out), flush=True)
    """
)


def test_a_deadline_entered_and_left_mid_statement_returns_at_once(tmp_path):
    try:
        run = subprocess.run(
            [sys.executable, "-c", _C1_CHILD, str(SERVER_DIR), str(tmp_path / "c1.db"),
             BOUNDED, UNBOUNDED],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the child never exited: entering the deadline waited on the other "
                    "thread's statement and the process deadlocked")
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout)

    assert out["other_running_after"] is True  # C1
    assert out["enter_leave_seconds"] < 0.5  # C1
    # Controls: the other statement was real and finished, and a deadline on this
    # connection still interrupts its own thread, so a no-op deadline cannot pass.
    assert out["other_count"] == BOUNDED_COUNT
    assert out["own_interrupted"] is True


def test_a_passed_deadline_interrupts_its_own_thread_and_not_another(tmp_path):
    conn = connect_db(tmp_path / "c2.db")
    deadline_open, other_done = threading.Event(), threading.Event()
    out: dict[str, object] = {}

    def deadline_thread() -> None:
        try:
            with statement_deadline(0.3):
                out["deadline_at"] = time.monotonic() + 0.3
                deadline_open.set()
                other_done.wait(30)
                conn.execute(UNBOUNDED).fetchone()
                out["own"] = "completed"
        except sqlite3.OperationalError as exc:
            out["own"] = "interrupted" if is_interrupted_error(exc) else str(exc)
        except Exception as exc:  # reported through `own`, asserted below
            out["own"] = f"raised {type(exc).__name__}"

    def other_thread() -> None:
        deadline_open.wait(5)
        try:
            out["other"] = conn.execute(BOUNDED).fetchone()[0]
        except sqlite3.OperationalError as exc:
            out["other"] = str(exc)
        out["other_finished_at"] = time.monotonic()
        other_done.set()

    threads = [threading.Thread(target=deadline_thread), threading.Thread(target=other_thread)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not any(thread.is_alive() for thread in threads)

    assert out.get("own") == "interrupted"  # C2
    # Supporting: the other thread's statement ran past the setting thread's deadline,
    # so its completion is evidence the deadline did not reach it.
    assert out["other_finished_at"] > out["deadline_at"]
    assert out["other"] == BOUNDED_COUNT  # C2
