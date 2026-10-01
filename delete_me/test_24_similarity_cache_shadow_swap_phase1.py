"""The Engine's `_write_cache` stores nothing while `<cache>.building` holds a live PID and ignores a dead or unparseable one; the updater's `cleanup_similarity_leftovers` removes a dead or unparseable marker and a crashed build's shadow, and keeps a live one.

- `_write_cache` with a live-PID marker, for two uncached sources: neither `similarity_sources` nor `similarity_items` gains a row, exactly one `write skipped reason=build-marker` line is logged, and the marker is untouched. With the marker unlinked, the same call stores the source and both items.
- `_write_cache` with a marker holding a reaped child's PID, `garbage`, the empty string, `0`, `-1` or `99999999999`: the source and both items are stored, and the marker still holds what was written.
- `cleanup_similarity_leftovers` over the same six markers: the marker, `.next.db` and `.next.db-journal` are gone, the active file is byte-identical, and a log line carries `path=<marker>` and `pid=` (the PID itself for the reaped child).
- `cleanup_similarity_leftovers` with a live-PID marker keeps it byte-identical and still removes `.next.db` and `.next.db-journal`; with no marker it removes whichever of the two exists and leaves the active file alone.

The Engine side runs on a `tmp_path` cache through a `SimpleNamespace` stub server, as in `test_similarity_candidates.py`; rows are read back through a separate read-only connection, so only committed rows count. The updater is loaded in-process from its file, as `test_updater_worker.py` does. A live PID is a sleeping child; a dead PID is a child already waited on.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sqlite3
import subprocess
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

UPDATER = SERVER_DIR / "db" / "jobs" / "updater-worker.py"
HOST = "h.example"
ENTRIES = [{"video_id": "A", "instance_domain": HOST, "score": 0.9, "rank": 1}, {"video_id": "B", "instance_domain": HOST, "score": 0.8, "rank": 2}]
# similarity_items rows for source S after ENTRIES are stored.
STORED_ITEMS = [("S", HOST, "A", HOST, 0.9, 1), ("S", HOST, "B", HOST, 0.8, 2)]
# None is a reaped child's PID. os.kill(0, 0) and os.kill(-1, 0) succeed and 99999999999 raises OverflowError, so each needs the parser's own guard.
NON_BLOCKING = [None, "garbage", "", "0", "-1", "99999999999"]
NON_BLOCKING_IDS = ["dead-pid", "garbage", "empty", "zero", "negative", "oversized"]


@pytest.fixture
def live_pid():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        os.kill(child.pid, 0)  # control: raises unless the child is running
        yield child.pid
    finally:
        child.terminate()
        child.wait()


def _marker_text(content: str | None) -> str:
    if content is not None:
        return content
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    with pytest.raises(ProcessLookupError):  # control: the reaped child's PID is dead
        os.kill(child.pid, 0)
    return str(child.pid)


def _files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    # The names are the documented contract (UPDATER_WORKER.md), not derived through the module under test.
    return tmp_path / "similarity-cache.db", tmp_path / "similarity-cache.db.building", tmp_path / "similarity-cache.next.db", tmp_path / "similarity-cache.next.db-journal"


@pytest.fixture
def server(tmp_path: Path):
    path = tmp_path / "similarity-cache.db"
    conn = connect_similarity_db(path)
    ensure_similarity_schema(conn)
    conn.commit()
    stat = os.stat(path)
    stub = SimpleNamespace(similarity_db=conn, similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=(stat.st_dev, stat.st_ino))
    yield stub
    stub.similarity_db.close()


def _write(server: SimpleNamespace, video_id: str) -> None:
    similarity_candidates._write_cache(server, {"video_id": video_id, "instance_domain": HOST}, ENTRIES, SimilarityCachePolicy())


def _committed(path: Path) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        sources = [tuple(row) for row in conn.execute("SELECT video_id, instance_domain FROM similarity_sources ORDER BY video_id")]
        items = [tuple(row) for row in conn.execute("SELECT source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank FROM similarity_items ORDER BY source_video_id, rank")]
    finally:
        conn.close()
    return sources, items


def test_live_marker_blocks_writes_with_one_log_line(server, live_pid, caplog):
    caplog.set_level(logging.INFO)
    _, marker, _, _ = _files(server.similarity_db_path.parent)
    marker.write_text(str(live_pid), encoding="ascii")

    _write(server, "S")
    _write(server, "T")

    assert _committed(server.similarity_db_path) == ([], [])  # C1: two uncached sources, no row in either table
    skip_lines = [record.getMessage() for record in caplog.records if "write skipped reason=build-marker" in record.getMessage()]
    assert len(skip_lines) == 1, [record.getMessage() for record in caplog.records]  # C1: two skips, one line
    assert marker.read_text(encoding="ascii") == str(live_pid)  # C1: the Engine never deletes a marker

    marker.unlink()
    _write(server, "S")
    assert _committed(server.similarity_db_path) == ([("S", HOST)], STORED_ITEMS)  # C1 control: the same call stores once the marker is gone, so the empty tables above came from the marker


@pytest.mark.parametrize("content", NON_BLOCKING, ids=NON_BLOCKING_IDS)
def test_dead_or_unparseable_marker_does_not_block_and_is_kept(server, content):
    _, marker, _, _ = _files(server.similarity_db_path.parent)
    text = _marker_text(content)
    marker.write_text(text, encoding="ascii")

    _write(server, "S")

    assert _committed(server.similarity_db_path) == ([("S", HOST)], STORED_ITEMS)  # C1
    assert marker.read_text(encoding="ascii") == text  # C1: left in place for the updater to judge


@pytest.fixture(scope="module")
def updater():
    spec = importlib.util.spec_from_file_location("updater_worker_phase1", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("content", NON_BLOCKING, ids=NON_BLOCKING_IDS)
def test_cleanup_removes_dead_or_unparseable_marker_and_shadow(updater, tmp_path, caplog, content):
    caplog.set_level(logging.INFO)
    active, marker, shadow, journal = _files(tmp_path)
    active.write_bytes(b"active")
    shadow.write_bytes(b"shadow")
    journal.write_bytes(b"journal")
    text = _marker_text(content)
    marker.write_text(text, encoding="ascii")

    updater.cleanup_similarity_leftovers(similarity_db=active)

    assert not marker.exists()  # C2
    assert not shadow.exists()  # C2
    assert not journal.exists()  # C2
    assert active.read_bytes() == b"active"  # C2: the served cache is not a leftover
    messages = [record.getMessage() for record in caplog.records]
    removal = [message for message in messages if f"path={marker}" in message and "pid=" in message]
    assert removal, messages  # C2: the removal is logged with path and pid
    if content is None:
        assert any(f"pid={text}" in message for message in removal), removal  # C2: a parseable dead PID is logged as itself


def test_cleanup_keeps_live_marker_and_removes_shadow(updater, tmp_path, live_pid):
    active, marker, shadow, journal = _files(tmp_path)
    active.write_bytes(b"active")
    shadow.write_bytes(b"shadow")
    journal.write_bytes(b"journal")
    marker.write_text(str(live_pid), encoding="ascii")

    updater.cleanup_similarity_leftovers(similarity_db=active)

    assert marker.read_text(encoding="ascii") == str(live_pid)  # C2
    assert not shadow.exists()  # C2: a crashed build's shadow goes even beside a live marker
    assert not journal.exists()  # C2
    assert active.read_bytes() == b"active"


@pytest.mark.parametrize("leftovers", [("shadow", "journal"), ("shadow",), ("journal",), ()], ids=["both", "shadow-only", "journal-only", "none"])
def test_cleanup_removes_each_leftover_on_its_own(updater, tmp_path, leftovers):
    active, _, shadow, journal = _files(tmp_path)
    active.write_bytes(b"active")
    for name in leftovers:
        {"shadow": shadow, "journal": journal}[name].write_bytes(name.encode())

    updater.cleanup_similarity_leftovers(similarity_db=active)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["similarity-cache.db"]  # C2: any leftover goes, with or without the other and with no marker
    assert active.read_bytes() == b"active"
