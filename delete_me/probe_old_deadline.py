"""Probe: time the CTE sizes, and run both checkpoint scenarios against TODAY's db.py.

Run from the project root: python3 tests/tmp/probe_old_deadline.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
sys.path.insert(0, str(SERVER_DIR))

from data.db import connect_db, is_interrupted_error, statement_deadline  # noqa: E402

LONG = (
    "WITH RECURSIVE s(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM s WHERE x<{n})"
    " SELECT COUNT(*) FROM s a, s b, s c"
)

tmp = Path(tempfile.mkdtemp())
conn = connect_db(tmp / "probe.db")
for n in (600,):
    start = time.monotonic()
    count = conn.execute(LONG.format(n=n)).fetchone()[0]
    print(f"n={n} count={count} seconds={time.monotonic() - start:.3f}")

# C2 against today's code: A holds a deadline open, B (no deadline) runs a long statement.
a_entered, b_done = threading.Event(), threading.Event()
result: dict[str, object] = {}


def thread_a() -> None:
    with statement_deadline(conn, 0.3):
        a_entered.set()
        b_done.wait(10)


def thread_b() -> None:
    a_entered.wait(10)
    try:
        result["b"] = conn.execute(LONG.format(n=600)).fetchone()[0]
    except Exception as exc:  # probe: record whatever happened
        result["b"] = f"{type(exc).__name__}: {exc} interrupted={is_interrupted_error(exc)}"
    b_done.set()


ta, tb = threading.Thread(target=thread_a), threading.Thread(target=thread_b)
ta.start(); tb.start(); ta.join(15); tb.join(15)
print("C2 today, thread B:", result.get("b"))

# C1 against today's code, in a child so a deadlock cannot freeze this probe.
child = textwrap.dedent(
    f"""
    import sys, threading, time
    sys.path.insert(0, {str(SERVER_DIR)!r})
    from data.db import connect_db, statement_deadline
    from pathlib import Path
    conn = connect_db(Path({str(tmp / "c1.db")!r}))
    started = threading.Event()
    def b():
        with statement_deadline(conn, 3.0):
            started.set()
            try:
                conn.execute({LONG.format(n=2000)!r}).fetchone()
            except Exception:
                pass
    t = threading.Thread(target=b); t.start()
    started.wait(5); time.sleep(0.2)
    t0 = time.monotonic()
    with statement_deadline(conn, 5.0):
        pass
    print("A returned after", round(time.monotonic() - t0, 3), "b_alive", t.is_alive(), flush=True)
    t.join()
    """
)
try:
    out = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=15)
    print("C1 today:", out.returncode, out.stdout.strip(), out.stderr.strip()[-300:])
except subprocess.TimeoutExpired:
    print("C1 today: child did not exit within 15s (hung)")
