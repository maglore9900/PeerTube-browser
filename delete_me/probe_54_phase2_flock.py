import fcntl
import os
import signal
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import _b1_file, _plain  # noqa: E402

from data.subtitles import connect_subtitles_db, ensure_subtitles_schema  # noqa: E402


def test_probe(tmp_path):
    lock = tmp_path / "worker.lock"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    mine = os.open(lock, os.O_RDONLY | os.O_CREAT)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        fcntl.flock(mine, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("second description: no raise")
    except Exception as exc:
        print("second description:", type(exc).__name__, exc, type(exc) is BlockingIOError)
    dup = os.dup(held)
    fcntl.flock(dup, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("dup of held: re-assert ok")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("held re-assert: ok")

    class Alarm(Exception):
        pass

    def ring(signum, frame):
        raise Alarm()

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(1)
    start = time.monotonic()
    try:
        fcntl.flock(mine, fcntl.LOCK_EX)
        print("blocking flock returned")
    except Alarm:
        print("blocking flock interrupted after", round(time.monotonic() - start, 2))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    os.close(held)
    os.close(dup)
    fcntl.flock(mine, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("after held+dup closed, mine takes lock: ok")
    other = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print("third: no raise")
    except BlockingIOError:
        print("third: BlockingIOError while mine holds")
    os.close(other)
    os.close(mine)

    try:
        sqlite3.connect(tmp_path / "x" / "y" / "s.db")
        print("connect nested: ok")
    except Exception as exc:
        print("connect nested:", type(exc).__name__, exc)
    nested = tmp_path / "a" / "b" / "subtitles.db"
    nested.parent.mkdir(parents=True)
    conn = connect_subtitles_db(nested)
    print("connect only, columns:", [r[1] for r in conn.execute("PRAGMA table_info(subtitles)")])
    conn.close()
    plain = _plain(nested)
    print("connect only mode:", plain.execute("PRAGMA journal_mode").fetchone()[0])
    plain.close()

    b1 = tmp_path / "b1.db"
    _b1_file(b1)
    conn = sqlite3.connect(b1)
    ensure_subtitles_schema(conn)
    conn.close()
    plain = _plain(b1)
    print("b1 ensure without wal mode:", plain.execute("PRAGMA journal_mode").fetchone()[0])
    print("b1 heartbeat:", [r[1] for r in plain.execute("PRAGMA table_info(translate_worker_heartbeat)")])
    print("b1 index:", [[i[2] for i in plain.execute(f"PRAGMA index_info('{ix[1]}')")] for ix in plain.execute("PRAGMA index_list(subtitles)")])
    plain.close()
    try:
        import pytest_timeout  # noqa: F401
        print("pytest_timeout: present")
    except ImportError:
        print("pytest_timeout: absent")
    print("subtitles names:", sorted(n for n in dir(__import__("data.subtitles", fromlist=["x"])) if "open" in n or "recover" in n))
    assert False, "probe"
