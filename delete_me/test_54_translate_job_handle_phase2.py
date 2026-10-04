"""Phase 2 checkpoint of plan 54: `open_subtitles_db` opens a missing nested path or a B1-era file as the full schema in WAL, and crash recovery runs only through `open_translate_worker_store`, under the worker's flock.

Store openers in `engine/server/data/subtitles.py`, called directly on files under tmp_path; the file's state is read back through a fresh plain connection, since the file and not the opener's connection is what the next opener meets.

- C1, missing nested path: on `a/b/subtitles.db` with neither `a` nor `b` present, `open_subtitles_db` creates both. The file then has the fourteen columns, a `(state, queued_at)` index, `translate_worker_heartbeat` with `id`, `beat_at` and `pid`, and journal mode `wal`. The returned connection reads the empty heartbeat.
- C1, B1-era file: on a rollback-journal file with B1's table and two ready/instance rows, the same four facts hold afterwards, and both the returned connection and the plain one read the two old cue lists unchanged.
- C2: while a separate `os.open` description of the worker lock holds LOCK_EX, `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError, and neither the file nor its `sub` directory exists. Each call is bounded by an alarm, so an opener that blocks on the flock fails instead of hanging. Control: once the holder is closed, the same call on the same descriptor returns (0, 0) and the file exists, and a third description is then refused the lock, because the opener took it on `mine` and kept it.
- Recovery under a held flock: `open_subtitles_db` on the file leaves a running job running with attempts 1, and `open_translate_worker_store` then returns (1, 0) at 9000, requeuing a running job with attempts 1. Claimed again, that job is failed with "worker stopped while running twice" at 9500 beside two first-time running jobs that are requeued, and the call returns (2, 1). The claims are read through the handle's attributes, and a queued row and a ready row are untouched.
"""
from __future__ import annotations

import fcntl
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import ALL_COLUMNS, B1_CUES, B1_READY_INSTANCE, HOST, RECOVERY_TEXT, _b1_file, _insert, _old_cues, _plain, _snapshot, _subtitles  # noqa: E402

# The module, not its names: the openers are this phase's, so each test fails at its own call, after its controls, instead of the whole file failing to collect.
from data import subtitles as store  # noqa: E402

# Long enough for a migration on a tmp file; a blocking flock on a held lock never returns at all (probed: SIGALRM interrupts it).
OPENER_SECONDS = 10


@contextmanager
def _bounded() -> Iterator[None]:
    """Fail, rather than hang, when the opener blocks on the flock instead of refusing with LOCK_NB."""

    def ring(signum, frame):  # noqa: ANN001, ANN202
        pytest.fail(f"open_translate_worker_store blocked for {OPENER_SECONDS} s instead of refusing the held flock")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(OPENER_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _schema(path: Path) -> tuple[list[str], list[list[str]], list[str], str]:
    """The file's subtitles columns, index column lists, heartbeat columns and journal mode, through a plain connection."""
    conn = _plain(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        indexed = [[info[2] for info in conn.execute(f"PRAGMA index_info('{index[1]}')")] for index in conn.execute("PRAGMA index_list(subtitles)")]
        heartbeat = [row[1] for row in conn.execute("PRAGMA table_info(translate_worker_heartbeat)")]
        return columns, indexed, heartbeat, conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal(tmp_path):
    path = tmp_path / "a" / "b" / "subtitles.db"
    assert not (tmp_path / "a").exists()  # control: neither directory exists, and a bare sqlite3 connect there fails (probed)

    conn = store.open_subtitles_db(path)
    try:
        assert store.fetch_translate_heartbeat(conn) is None  # C1: the returned connection reads the migrated, empty heartbeat table
    finally:
        conn.close()

    assert path.parent.is_dir()  # C1
    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1


def test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues(tmp_path):
    path = tmp_path / "subtitles.db"
    _b1_file(path)
    before = _plain(path)
    try:
        # Controls: a rollback-journal B1 file whose rows B1's reader already returns.
        assert before.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert _old_cues(before) == B1_CUES
    finally:
        before.close()

    conn = store.open_subtitles_db(path)
    try:
        assert _old_cues(conn) == B1_CUES  # C1: the returned connection reads the old cues unchanged
    finally:
        conn.close()

    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1
    after = _plain(path)
    try:
        assert _old_cues(after) == B1_CUES  # C1: the file itself still holds them
    finally:
        after.close()


def test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing(tmp_path):
    lock = tmp_path / "worker.lock"
    path = tmp_path / "sub" / "subtitles.db"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    # A second open of the file, not os.dup: a dup shares held's description and so its lock (probed), and would never be refused.
    mine = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        with _bounded(), pytest.raises(BlockingIOError):  # C2
            store.open_translate_worker_store(path, mine, 1)
        assert not path.exists()  # C2: the file was never opened
        assert not path.parent.exists()  # C2: nor its directory created, so the flock came before the mkdir

        os.close(held)
        held = -1
        with _bounded():
            opened, counts = store.open_translate_worker_store(path, mine, 1)
        opened.close()
        assert tuple(counts) == (0, 0)  # control: with the lock free the same call on the same descriptor succeeds
        assert path.exists()  # control: so the absence above is the refusal's doing
        other = os.open(lock, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # control: the opener took the lock on mine and kept it
        finally:
            os.close(other)
    finally:
        if held != -1:
            os.close(held)
        os.close(mine)


def test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    path = tmp_path / "subtitles.db"
    lock_fd = os.open(tmp_path / "worker.lock", os.O_RDONLY | os.O_CREAT)
    # Set up through the plain connect and migrate, so the claims below run as controls before the phase's opener is reached.
    conn = _subtitles(path)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
        _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})
        _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
        # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
        _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})
        _insert(conn, "b1", HOST, B1_READY_INSTANCE)
        _, before = _snapshot(path)
        bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]
        assert len(bystanders_before) == 2  # control: the quote()d filter finds both rows, so the comparison at the end is not two empty lists

        def job(video_id: str) -> tuple:
            return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

        first = store.claim_translate_job(conn, "en", 5000)
        assert (first.video_id, first.attempts) == ("t", 1)  # control: t is running after one claim

        store.open_subtitles_db(path).close()
        assert job("t") == ("running", 1, None, None)  # the plain opener recovers nothing; the (1, 0) below shows this row was recoverable

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9000)
        opened.close()
        assert tuple(counts) == (1, 0)
        assert job("t") == ("queued", 1, None, None)  # requeued, its one claim still counted

        second = [store.claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
        assert [(row.video_id, row.attempts) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9500)
        opened.close()
        assert tuple(counts) == (2, 1)
        assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)
        assert job("o1") == ("queued", 1, None, None)
        assert job("o2") == ("queued", 1, None, None)
    finally:
        conn.close()
        os.close(lock_fd)
    _, after = _snapshot(path)
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # recovery touches only running rows
