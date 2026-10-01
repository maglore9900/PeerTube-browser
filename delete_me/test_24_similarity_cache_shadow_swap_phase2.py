"""The Engine's `_read_cache` moves `server.similarity_db` onto the file its `similarity_db_path` names once that path is a different inode holding a valid cache, and closes the old handle; while the path names a text file, a schema-less SQLite file or nothing, reads keep coming from the old handle and `_write_cache` skips without writing anywhere.

- After `os.replace` with a valid cache holding B: `_read_cache` returns B, `server.similarity_db` is a new object, the old handle raises `sqlite3.ProgrammingError`, `similarity_db_identity` equals the new `(st_dev, st_ino)`, and exactly one `reopen ok` line carries both inode numbers; a second read reuses the new handle and logs no second reopen.
- With the path replaced by a text file, then by a schema-less SQLite file, then unlinked: two reads each return the old entry A, the handle and identity are unchanged, one reopen warning is logged per target, `_write_cache` returns without raising and logs one `write skipped reason=stale-handle` line per target, the old inode (reachable through `os.link`) still holds only source S, the text and schema-less files are byte-identical and the unlinked path stays absent. A valid cache holding C replaced in afterwards is read as C through a new handle, the old handle is closed, no further warning is logged, and the same `_write_cache` then stores its source in the active file and logs no further skip. Skip lines are throttled, so the module's `monotonic` is stepped past the interval before each target (observed to release the existing `build-marker` throttle).
- 8 threads call `_read_cache` while 20 valid caches are replaced in one after another: no read raises, none returns an empty result, and every one of the 20 caches is read by some thread.
- A stub with a handle and a lock but no `similarity_db_path` reads and stores as before, keeps its handle, and gains no attributes.

The stub server and the `sys.path` setup follow `test_24_similarity_cache_shadow_swap_phase1.py`; caches are written under `tmp_path` by their own closed connections, and rows are read back through separate read-only connections, so only committed rows count. SQLite itself refuses a write through a handle whose file was replaced (`attempt to write a readonly database`, observed), so the `stale-handle` line and the call not raising are what tell a deliberate skip from that refusal.
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

from data import similarity_candidates  # noqa: E402
from data.db import connect_similarity_db  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402
from data.similarity_cache_manager import SimilarityCachePolicy  # noqa: E402

HOST = "h.example"
SOURCE = {"video_id": "S", "instance_domain": HOST}
# Every test cache holds one item for S; require_full=False makes that a hit whatever the limit.
READ_POLICY = SimilarityCachePolicy(require_full=False)
ENTRIES = [{"video_id": "X", "instance_domain": HOST, "score": 0.9, "rank": 1}]
REPLACES = 20
READERS = 8


def _cache(path: Path, similar: str) -> None:
    conn = sqlite3.connect(path)
    try:
        ensure_similarity_schema(conn)
        conn.execute("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES ('S', ?, 1)", (HOST,))
        conn.execute("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES ('S', ?, ?, ?, 0.5, 1)", (HOST, similar, HOST))
        conn.commit()
    finally:
        conn.close()


def _identity(path: Path) -> tuple[int, int]:
    stat = os.stat(path)
    return (stat.st_dev, stat.st_ino)


@pytest.fixture
def server(tmp_path: Path):
    path = tmp_path / "similarity-cache.db"
    _cache(path, "A")
    stub = SimpleNamespace(similarity_db=connect_similarity_db(path), similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=_identity(path))
    yield stub
    if stub.similarity_db is not None:
        stub.similarity_db.close()


def _read(server: SimpleNamespace) -> list[str]:
    return [entry["video_id"] for entry in similarity_candidates._read_cache(server, SOURCE, 10, READ_POLICY)]


def _write(server: SimpleNamespace, video_id: str) -> None:
    similarity_candidates._write_cache(server, {"video_id": video_id, "instance_domain": HOST}, ENTRIES, SimilarityCachePolicy())


def _sources(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT video_id FROM similarity_sources ORDER BY video_id")]
    finally:
        conn.close()


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _reopen_warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING and "reopen" in record.getMessage()]


def _stale_skips(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if "write skipped reason=stale-handle" in record.getMessage()]


def test_valid_replace_moves_reads_to_new_file_and_closes_old_handle(server, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    old = server.similarity_db
    old_identity = server.similarity_db_identity
    assert _read(server) == ["A"]  # control: the stub serves the first file
    replacement = tmp_path / "next.db"
    _cache(replacement, "B")
    os.replace(replacement, server.similarity_db_path)
    new_identity = _identity(server.similarity_db_path)
    assert new_identity != old_identity  # control: the path now names a different inode

    assert _read(server) == ["B"]  # C1: read from the new file (today's code reads A through the old handle)
    reopened = server.similarity_db
    assert reopened is not old  # C1
    with pytest.raises(sqlite3.ProgrammingError):  # C1: the old handle is closed
        old.execute("SELECT 1")
    assert server.similarity_db_identity == new_identity  # C1
    reopen_ok = [message for message in _messages(caplog) if "reopen ok" in message]
    assert len(reopen_ok) == 1, _messages(caplog)  # C1
    assert str(old_identity[1]) in reopen_ok[0] and str(new_identity[1]) in reopen_ok[0], reopen_ok  # C1: the line carries both inodes

    assert _read(server) == ["B"]  # C1
    assert server.similarity_db is reopened  # C1: a matching inode is not reopened again
    assert len([message for message in _messages(caplog) if "reopen ok" in message]) == 1  # C1


def _assert_on_old_handle(server: SimpleNamespace, old: sqlite3.Connection, old_identity: tuple[int, int], old_inode: Path) -> None:
    assert _read(server) == ["A"]  # C2: reads come from the old handle
    assert _read(server) == ["A"]  # C2
    _write(server, "W")  # C2: skips; today's code raises `attempt to write a readonly database` here
    assert server.similarity_db is old  # C2: the old handle is kept
    assert server.similarity_db_identity == old_identity  # C2: and so is its inode record
    assert _sources(old_inode) == ["S"]  # C2: the old inode gains no row


def test_invalid_or_missing_path_keeps_old_handle_and_writes_nowhere(server, tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    clock = [0.0]
    # Skip lines are logged at most once per interval; stepping past it before each target lets each target's skip log its own line.
    monkeypatch.setattr(similarity_candidates, "monotonic", lambda: clock[0])
    path = server.similarity_db_path
    old = server.similarity_db
    old_identity = server.similarity_db_identity
    old_inode = tmp_path / "old-inode.db"
    os.link(path, old_inode)  # keeps the replaced inode readable by name after the swaps
    text = tmp_path / "text.db"
    text.write_bytes(b"not a database\n")
    bare = tmp_path / "bare.db"
    bare_conn = sqlite3.connect(bare)
    bare_conn.execute("CREATE TABLE unrelated (x INTEGER)")
    bare_conn.commit()
    bare_conn.close()
    bare_bytes = bare.read_bytes()

    clock[0] += 3600.0
    os.replace(text, path)
    _assert_on_old_handle(server, old, old_identity, old_inode)
    assert len(_reopen_warnings(caplog)) == 1, _messages(caplog)  # C2: one warning for the text file, however often it is retried
    assert len(_stale_skips(caplog)) == 1, _messages(caplog)  # C2: the write was skipped as stale, not refused by SQLite and swallowed
    assert path.read_bytes() == b"not a database\n"  # C2: the new file gains nothing

    clock[0] += 3600.0
    os.replace(bare, path)
    _assert_on_old_handle(server, old, old_identity, old_inode)
    assert len(_reopen_warnings(caplog)) == 2, _messages(caplog)  # C2: one more for the schema-less file
    assert len(_stale_skips(caplog)) == 2, _messages(caplog)  # C2: this write too was skipped as stale
    assert path.read_bytes() == bare_bytes  # C2: no cache tables or rows created in it

    clock[0] += 3600.0
    path.unlink()
    _assert_on_old_handle(server, old, old_identity, old_inode)
    assert len(_reopen_warnings(caplog)) == 3, _messages(caplog)  # C2: one more for the missing path
    assert len(_stale_skips(caplog)) == 3, _messages(caplog)  # C2: and this write too
    assert not path.exists()  # C2: nothing is created at the missing active path

    clock[0] += 3600.0
    replacement = tmp_path / "next.db"
    _cache(replacement, "C")
    os.replace(replacement, path)
    assert _read(server) == ["C"]  # C1: a valid cache replaced in later is picked up
    assert server.similarity_db is not old  # C1
    with pytest.raises(sqlite3.ProgrammingError):  # C1
        old.execute("SELECT 1")
    assert server.similarity_db_identity == _identity(path)  # C1
    assert len(_reopen_warnings(caplog)) == 3, _messages(caplog)  # C1: the valid target logs no warning
    _write(server, "W")
    assert _sources(path) == ["S", "W"]  # C2 control: the same write stores once the handle is on the active file, so the skips above came from the stale handle
    assert len(_stale_skips(caplog)) == 3, _messages(caplog)  # C2 control: a write on the active file logs no skip, though the clock would let one through
    assert _sources(old_inode) == ["S"]  # C2


def test_concurrent_reads_during_replaces_see_no_error_and_no_miss(server, tmp_path):
    caches = []
    for index in range(REPLACES):
        cache = tmp_path / f"next-{index}.db"
        _cache(cache, f"V{index}")
        caches.append(cache)
    seen = {f"V{index}": threading.Event() for index in range(REPLACES)}
    stop = threading.Event()
    errors: list[BaseException] = []
    results: list[list[str]] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                ids = _read(server)
            except BaseException as exc:
                errors.append(exc)
                return
            results.append(ids)
            if ids and ids[0] in seen:
                seen[ids[0]].set()

    threads = [threading.Thread(target=reader) for _ in range(READERS)]
    for thread in threads:
        thread.start()
    picked = []
    try:
        for index, cache in enumerate(caches):
            os.replace(cache, server.similarity_db_path)
            # The next replace waits until a reader has read this one, so every swap races live readers.
            if not seen[f"V{index}"].wait(5):
                break
            picked.append(f"V{index}")
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    assert errors == []  # C1: no read raises during the swaps
    assert [ids for ids in results if not ids] == []  # C1: no read comes back empty (a read on a just-closed handle is swallowed as a miss)
    assert picked == [f"V{index}" for index in range(REPLACES)]  # C1: every replaced cache was read (today's code reads A throughout)


def test_server_without_path_reads_and_writes_as_before(tmp_path):
    path = tmp_path / "similarity-cache.db"
    _cache(path, "A")
    conn = connect_similarity_db(path)
    stub = SimpleNamespace(similarity_db=conn, similarity_db_lock=threading.Lock())
    try:
        assert _read(stub) == ["A"]  # C1 guard: no path, no reopen
        _write(stub, "W")
        assert _sources(path) == ["S", "W"]  # C1 guard
        assert stub.similarity_db is conn  # C1 guard
        assert sorted(vars(stub)) == ["similarity_db", "similarity_db_lock"]  # C1 guard: no identity or reopen state added
    finally:
        conn.close()
