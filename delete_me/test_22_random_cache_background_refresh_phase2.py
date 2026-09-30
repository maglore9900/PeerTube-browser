"""A finished random cache build becomes the owner's read-only serving handle only after it is validated and renamed into place, the old handle is closed without failing a read, and a failure at the build, the check or the rename, or a stop before the swap, leaves the active file and the handle as they were and removes the temp file.

- `refresh_random_cache` over a seeded active file returns True. The active path is then at a new inode and the directory holds only that file. `owner.random_cache_db` is a different object, `fetch_random_rowids` on it returns the renamed file's rowids in position order (source rowids 1..20), and a write through it fails "readonly". The old handle raises `ProgrammingError`.
- After one swap, a second same-pid build is paused after an uncommitted write that spills sqlite's page cache. While it is paused, no `random-cache.tmp.<pid>.db-journal` exists and `fetch_random_rowids` on the served handle returns the first build's rowids. The build then swaps. Control: with `connect_random_cache_db` replaced by an opener without the in-memory journal, the journal exists and the same read raises `OperationalError`.
- Three reader threads loop `fetch_random_rowids` under the owner's lock while 10 refreshes run, all of which swap. No read raises and none comes back empty.
- `swap_readonly_connection` with a failing check SQL raises `OperationalError`, and with a refused rename raises `OSError`. Either way the active file's bytes and `owner.random_cache_db` are unchanged, the old handle still reads the seeded rowids, and the temp file is still there.
- `refresh_random_cache` with the build raising after writing, a table-less build failing the check, or the rename refused returns False and logs `failed` with the reason. The active file's bytes are unchanged, the owner holds the same handle and it still reads, and the directory holds only the active file.
- With the stop event set during the build, `refresh_random_cache` returns False with the same file, handle and directory outcome.

The tests use temporary sqlite files and a `SimpleNamespace` owner with a `threading.Lock`, the contract `fetch_random_rows_from_cache(server)` reads. The rename refusal replaces `os.replace`, the filesystem boundary.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.db as db  # noqa: E402
import data.random_cache as random_cache  # noqa: E402

SOURCE_ROWS = 20
SEEDED_ROWS = [(1, 7), (2, 3), (3, 11)]
SEEDED_ROWIDS = [7, 3, 11]
STALE_ROWID = 999
# Above the source's 20 rows, so every build holds the whole source.
BUILD_SIZE = 100
# Above every cache in these tests, so fetch_random_rowids reads from offset 0 and returns the whole table in position order.
READ_ALL = 100
CHECK_SQL = "SELECT COUNT(*) FROM random_rowids"
FAILING_CHECK_SQL = "SELECT COUNT(*) FROM no_such_table"
FAILURE_MESSAGE = "populate failed after writing"
RENAME_REFUSED = "rename refused"
# Past sqlite's page cache at this size, so the paused build's rollback journal is synced to disk with its magic header, as a production-size build's is; a smaller uncommitted write leaves a zeroed header that no reader treats as hot.
SPILL_CACHE_PAGES = 10
SPILL_ROWS = 5000
WAIT_SECONDS = 30
READER_THREADS = 3
REFRESH_CYCLES = 10
READ_LIMIT = 5


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


def test_refresh_serves_a_new_readonly_handle_on_the_renamed_file_and_closes_the_old(tmp_path: Path) -> None:
    """A refresh leaves a new inode at the active path and nothing else, serves it through a new read-only handle that reads its rows, and closes the old handle."""
    active_path, owner = _seeded(tmp_path)
    seeded_inode = active_path.stat().st_ino
    old = owner.random_cache_db

    swapped = _refresh(tmp_path, active_path, owner)

    assert swapped is True  # C1
    # The seeded file still exists when the temp file is created beside it, so the two cannot share an inode; an in-place write keeps it.
    assert active_path.stat().st_ino != seeded_inode  # C1
    assert _names(active_path.parent) == {active_path.name}  # C1
    assert owner.random_cache_db is not old  # C1
    served = _served_rowids(owner)
    assert sorted(served) == list(range(1, SOURCE_ROWS + 1))  # C1
    # Same order as the file now at the active path, which the build shuffled, so the handle reads that file and not a copy of the rows.
    assert served == [row[1] for row in _cache_rows(active_path)]  # C1
    with pytest.raises(sqlite3.ProgrammingError):
        old.execute("SELECT 1")  # C1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        owner.random_cache_db.execute("DELETE FROM random_rowids")  # C1
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
        assert journal_on_disk is False  # C1
        assert read == first_rowids  # C1
    assert results == [True]  # C1
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
    assert swaps == [True] * REFRESH_CYCLES  # C1
    assert errors == []  # C1
    assert empties == []  # C1
    owner.random_cache_db.close()


@pytest.mark.parametrize("stage", ["check", "rename"])
def test_swap_failure_leaves_the_target_and_the_handle_and_keeps_the_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """`swap_readonly_connection` failing its check or its rename raises, and leaves the target's bytes, the owner's handle and the temp file as they were."""
    active_path, owner = _seeded(tmp_path)
    active_bytes = active_path.read_bytes()
    old = owner.random_cache_db
    temp_path, _, _ = random_cache.build_random_cache(tmp_path / "source.db", active_path, BUILD_SIZE, True, 0, 100)

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
            db.swap_readonly_connection(temp_path, active_path, owner.random_cache_lock, owner, "random_cache_db", check_sql)

    assert active_path.read_bytes() == active_bytes  # C2
    assert owner.random_cache_db is old  # C2
    assert _served_rowids(owner) == SEEDED_ROWIDS  # C2
    # The helper leaves the temp file to its caller.
    assert _names(active_path.parent) == {active_path.name, temp_path.name}  # C2
    old.close()


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
    assert swapped is False  # C2
    failure_lines = [record.getMessage() for record in caplog.records if "failed" in record.getMessage()]
    assert any(reason in line for line in failure_lines), failure_lines  # C2
    assert active_path.read_bytes() == active_bytes  # C2
    assert owner.random_cache_db is old  # C2
    assert _served_rowids(owner) == SEEDED_ROWIDS  # C2
    assert _names(active_path.parent) == {active_path.name}  # C2
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
    assert swapped is False  # C2
    assert active_path.read_bytes() == active_bytes  # C2
    assert owner.random_cache_db is old  # C2
    assert _served_rowids(owner) == SEEDED_ROWIDS  # C2
    assert _names(active_path.parent) == {active_path.name}  # C2
    old.close()
