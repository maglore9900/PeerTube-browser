"""The per-thread statement deadline on connections opened by `data.db`, and the validate-first swap of a read-only serving handle.

- Entering and leaving `statement_deadline` in one thread while another thread's statement
  is running on the same `connect_db` connection returns without waiting for that
  statement. A deadline that waited here is the process-wide deadlock the Engine hit when
  the handler was installed per request.
- A passed `statement_deadline` interrupts only statements run by the thread that set it.
- `swap_readonly_connection` with a failing check SQL raises `OperationalError`, and with a refused rename raises `OSError`. Either way the target file's bytes and the owner's attribute are unchanged, the old handle still reads the seeded ann_ids, and the temp file is still there for the caller to remove.

The swap test builds its temp file with `data.random_cache.build_random_cache` on temporary sqlite files, serves through a `SimpleNamespace` owner with a `threading.Lock`, and refuses the rename by replacing `os.replace`, the filesystem boundary.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
# `data.random_cache` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.db import connect_db, connect_readonly_db, is_interrupted_error, statement_deadline, swap_readonly_connection  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402
from data.random_cache import build_random_cache, fetch_random_ann_ids  # noqa: E402

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


SOURCE_ROWS = 20
SEEDED_ROWIDS = [compute_ann_id(f"v{index}", "a.example") for index in (7, 3, 11)]
SEEDED_ROWS = list(enumerate(SEEDED_ROWIDS, start=1))
# Above the source's 20 rows, so the build holds the whole source.
BUILD_SIZE = 100
# Above every cache here, so fetch_random_ann_ids reads from offset 0 and returns the whole table in position order.
READ_ALL = 100
CHECK_SQL = "SELECT COUNT(*) FROM random_ann_ids"
FAILING_CHECK_SQL = "SELECT COUNT(*) FROM no_such_table"
RENAME_REFUSED = "rename refused"


def _source_db(tmp_path: Path) -> sqlite3.Connection:
    """A source of 20 embedded videos, one instance, three channels, each stored with its computed ann_id."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, ann_id INTEGER NOT NULL)")
    for index in range(1, SOURCE_ROWS + 1):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example', ?)", (f"v{index}", compute_ann_id(f"v{index}", "a.example")))
    conn.commit()
    return conn


def _seed_cache(path: Path, rows: list[tuple[int, int]]) -> None:
    """Write a random cache file holding exactly `rows`, through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _seeded(tmp_path: Path) -> tuple[Path, SimpleNamespace]:
    """A 20-row source, an active cache holding SEEDED_ROWS, and an owner serving it through a read-only handle."""
    _source_db(tmp_path).close()
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_cache(active_path, SEEDED_ROWS)
    return active_path, SimpleNamespace(random_cache_db=connect_readonly_db(active_path), random_cache_lock=threading.Lock())


def _served_ann_ids(owner: SimpleNamespace) -> list[int]:
    """Read the whole cache through the owner's current handle, holding its lock as the request path does."""
    with owner.random_cache_lock:
        return fetch_random_ann_ids(owner.random_cache_db, READ_ALL)


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


@pytest.mark.parametrize("stage", ["check", "rename"])
def test_swap_failure_leaves_the_target_and_the_handle_and_keeps_the_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """`swap_readonly_connection` failing its check or its rename raises, and leaves the target's bytes, the owner's handle and the temp file as they were."""
    active_path, owner = _seeded(tmp_path)
    active_bytes = active_path.read_bytes()
    old = owner.random_cache_db
    temp_path, _, _ = build_random_cache(tmp_path / "source.db", active_path, BUILD_SIZE, True, 0, 100)

    def refuse_replace(src: str | os.PathLike, dst: str | os.PathLike) -> None:
        raise OSError(RENAME_REFUSED)

    with monkeypatch.context() as patch:
        if stage == "check":
            check_sql, expected = FAILING_CHECK_SQL, sqlite3.OperationalError
        else:
            # The check passes, so only the rename stands between this temp file and the target.
            check_sql, expected = CHECK_SQL, OSError
            patch.setattr(os, "replace", refuse_replace)
        with pytest.raises(expected):
            swap_readonly_connection(temp_path, active_path, owner.random_cache_lock, owner, "random_cache_db", check_sql)

    assert active_path.read_bytes() == active_bytes
    assert owner.random_cache_db is old
    assert _served_ann_ids(owner) == SEEDED_ROWIDS
    # The helper leaves the temp file to its caller.
    assert _names(active_path.parent) == {active_path.name, temp_path.name}
    old.close()
