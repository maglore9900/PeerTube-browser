"""With the NSFW filter on, the up-next pool in `data/similarity_candidates.py` refills past NSFW hits instead of coming back short; with it off, it is unchanged. The similarity cache's `_write_cache` stores nothing while `<cache>.building` holds a live PID, and `_read_cache` / `_write_cache` move the handle onto a valid cache swapped in at `similarity_db_path` while never writing through a replaced inode.

- `get_upnext_candidates` with no cache entry, a per-author cap of 1 and target pool 5, over an ANN script whose step 2 adds only NSFW hits and whose step 3 adds Y on NSFW X1's channel. Filtered, it steps (1,10), (2,20), (4,40), (8,80) with pool counts 1, 1, 2, 4, stops at the caps, and returns A, Y, B, C. Unfiltered, it steps (1,10), (2,20), (4,40) with counts 2, 3, 3 and returns X1, A, X2.
- The same ladder when step 2 adds no hit: filtered, it stops after (2,20) with counts 1, 1 and returns A. Unfiltered, it stops at the same step with counts 2, 2 and returns X1, A.
- One ANN step with top_k 3, target 3 and a per-author cap of 1, where NSFW X1 outscores A on A's channel and NSFW X2 also outscores A. Filtered, it returns A, B, C with a pool count of 3. Unfiltered, it returns X1, X2, B.

- `_write_cache` with a live-PID marker, for two uncached sources: neither `similarity_sources` nor `similarity_items` gains a row, exactly one `write skipped reason=build-marker` line is logged, and the marker is untouched; with the marker unlinked, the same call stores. With a marker holding a reaped child's PID, `garbage`, the empty string, `0`, `-1` or `99999999999`, the source and both items are stored and the marker still holds what was written.
- After `os.replace` with a valid cache, `_read_cache` returns its rows through a new handle, the old handle is closed, the identity is the new `(st_dev, st_ino)` and one `reopen ok` line carries both inodes. While the path names a text file, a schema-less SQLite file or nothing, reads come from the old handle, one reopen warning is logged per target, and `_write_cache` skips as `stale-handle` without writing to either inode; a valid cache replaced in later is picked up.
- 8 threads reading while 20 valid caches are replaced in see no error and no empty result. A stub without `similarity_db_path` reads and stores as before and gains no attributes.

The Engine db is an in-memory SQLite table. `data.ann` is replaced in `sys.modules` by a stub `search_similar_above`, because the real module needs numpy and faiss, which this interpreter lacks. The stub returns scripted hits unfiltered, as the real search does. The server's moderation switches are off, so only the NSFW filter, the author cap and the pool count shape the rows. The similarity cache tests run on a `tmp_path` cache through a `SimpleNamespace` stub server; rows are read back through separate read-only connections, so only committed rows count. A live PID is a sleeping child; a dead PID is a child already waited on.
"""
from __future__ import annotations

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

HOST = "h.example"
THRESHOLD = 3


def _video_db(videos: list[tuple[str, str]]) -> sqlite3.Connection:
    """An in-memory Engine db holding `videos` as (label, channel), embedded in that order.

    A label starting X is flagged nsfw = 1 and one starting R sits at THRESHOLD errors; the rest alternate nsfw 0 and NULL.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    for index, (label, channel) in enumerate(videos):
        nsfw = 1 if label.startswith("X") else (0 if index % 2 else None)
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (label, f"u-{label}", HOST, channel, nsfw, THRESHOLD if label.startswith("R") else 0),
        )
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (label, HOST))
    db.commit()
    return db


def _labels(rows: list[dict]) -> list[str]:
    return [row["video_id"] for row in rows]


# Every up-next run starts at (1, 10) and doubles to the (8, 80) caps; the floors keep all scripted hits in the core pool.
UPNEXT_POLICY = {"top_k": 48, "target_min_pool": 5, "nprobe": 1, "search_limit": 10, "max_nprobe": 8, "max_search_limit": 80, "min_score": 0.5, "tail_min_score": 0.3, "cache_limit": 20}
STEP_1 = [("X1", 0.95, "ch-X"), ("A", 0.9, "ch-A")]
# Its only new hit is NSFW.
STEP_2 = STEP_1 + [("X2", 0.85, "ch-X2")]
# Y shares NSFW X1's channel, so under a cap of 1 it shows only once X1 is filtered out.
STEP_3 = STEP_2 + [("Y", 0.8, "ch-X")]
STEP_4 = STEP_3 + [("B", 0.78, "ch-B"), ("C", 0.76, "ch-C")]
LADDER = {(1, 10): STEP_1, (2, 20): STEP_2, (4, 40): STEP_3, (8, 80): STEP_4}
# Step 2 finds no hit step 1 did not.
STALLED = {(1, 10): STEP_1, (2, 20): STEP_1, (4, 40): STEP_4, (8, 80): STEP_4}
# NSFW X1 outscores A on A's channel, and NSFW X2 outscores A too.
CAPPED = {(1, 10): [("X1", 0.95, "ch-A"), ("X2", 0.92, "ch-X2"), ("A", 0.9, "ch-A"), ("B", 0.85, "ch-B"), ("C", 0.8, "ch-C"), ("D", 0.75, "ch-D")]}


def _upnext(monkeypatch: pytest.MonkeyPatch, script: dict[tuple[int, int], list[tuple[str, float, str]]], include_nsfw: bool, author_limit: int, **policy) -> tuple[list[tuple[int, int]], list[str], list[tuple[int, int, int]]]:
    """Run get_upnext_candidates for a seed with no cache entry, the ANN search answering each (nprobe, search_limit) from `script` as (label, score, channel) hits.

    :returns: the steps the search was called at, the pool's labels, and the (nprobe, search_limit, pool count) steps the stats report.
    """
    db = _video_db(list({label: channel for hits in script.values() for label, _, channel in hits}.items()))
    called: list[tuple[int, int]] = []

    def search_similar_above(server, seed, nprobe, search_limit, min_score):
        called.append((nprobe, search_limit))
        return [{"video_id": label, "instance_domain": HOST, "score": score} for label, score, _ in script[(nprobe, search_limit)]], None

    monkeypatch.setitem(sys.modules, "data.ann", SimpleNamespace(search_similar_above=search_similar_above))
    server = SimpleNamespace(db=db, db_lock=threading.Lock(), similarity_max_per_author=author_limit, enable_instance_ignore=False, enable_channel_blocklist=False)
    seed = {"video_id": "S", "instance_domain": HOST, "channel_id": "ch-S", "embedding": [0.0]}
    rows, stats = similarity_candidates.get_upnext_candidates(server, seed, similarity_candidates.UpnextPoolPolicy(**{**UPNEXT_POLICY, **policy}, include_nsfw=include_nsfw))
    return called, _labels(rows), stats["steps"]


@pytest.mark.parametrize(
    "include_nsfw, steps, pool",
    [
        (False, [(1, 10, 1), (2, 20, 1), (4, 40, 2), (8, 80, 4)], ["A", "Y", "B", "C"]),
        (True, [(1, 10, 2), (2, 20, 3), (4, 40, 3)], ["X1", "A", "X2"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_ladder_widens_past_an_all_nsfw_step_to_the_caps_when_filtered(monkeypatch, include_nsfw, steps, pool):
    called, rows, reported = _upnext(monkeypatch, LADDER, include_nsfw, 1)
    # Filtered: step 2 adds no row but a hit, so the ladder goes on; NSFW rows are out of every count and of the channel cap, so Y shows; the caps end it short of 5. Unfiltered: step 3 adds a hit but no row, so it stops there.
    assert called == [step[:2] for step in steps]
    assert reported == steps
    assert rows == pool


@pytest.mark.parametrize(
    "include_nsfw, steps, pool",
    [
        (False, [(1, 10, 1), (2, 20, 1)], ["A"]),
        (True, [(1, 10, 2), (2, 20, 2)], ["X1", "A"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_ladder_stops_when_a_step_adds_no_hit(monkeypatch, include_nsfw, steps, pool):
    called, rows, reported = _upnext(monkeypatch, STALLED, include_nsfw, 0)
    assert called == [step[:2] for step in steps]  # the raw hit count stopped growing, so the ladder stops below the caps
    assert reported == steps
    assert rows == pool


@pytest.mark.parametrize(
    "include_nsfw, pool",
    [
        (False, ["A", "B", "C"]),
        (True, ["X1", "X2", "B"]),
    ],
    ids=["filtered", "unfiltered"],
)
def test_upnext_nsfw_hits_take_no_author_slot_and_no_pool_place(monkeypatch, include_nsfw, pool):
    called, rows, reported = _upnext(monkeypatch, CAPPED, include_nsfw, 1, top_k=3, target_min_pool=3)
    assert called == [(1, 10)]  # control: one step fills the target, so the pool below comes from these hits alone
    assert reported == [(1, 10, 3)]
    assert rows == pool  # filtered, X1 does not take A's channel slot and X1, X2 do not use up top_k; unfiltered, the NSFW hits take both


MARKER_ENTRIES = [{"video_id": "A", "instance_domain": HOST, "score": 0.9, "rank": 1}, {"video_id": "B", "instance_domain": HOST, "score": 0.8, "rank": 2}]
# similarity_items rows for source S after MARKER_ENTRIES are stored.
MARKER_STORED_ITEMS = [("S", HOST, "A", HOST, 0.9, 1), ("S", HOST, "B", HOST, 0.8, 2)]
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


def _marker_path(server: SimpleNamespace) -> Path:
    # The name is the documented contract (UPDATER_WORKER.md, ADR-0008), not derived through the module under test.
    return server.similarity_db_path.parent / "similarity-cache.db.building"


@pytest.fixture
def empty_cache_server(tmp_path: Path):
    path = tmp_path / "similarity-cache.db"
    conn = connect_similarity_db(path)
    ensure_similarity_schema(conn)
    conn.commit()
    stat = os.stat(path)
    stub = SimpleNamespace(similarity_db=conn, similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=(stat.st_dev, stat.st_ino))
    yield stub
    stub.similarity_db.close()


def _write_two_entries(server: SimpleNamespace, video_id: str) -> None:
    similarity_candidates._write_cache(server, {"video_id": video_id, "instance_domain": HOST}, MARKER_ENTRIES, SimilarityCachePolicy())


def _committed(path: Path) -> tuple[list[tuple], list[tuple]]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        sources = [tuple(row) for row in conn.execute("SELECT video_id, instance_domain FROM similarity_sources ORDER BY video_id")]
        items = [tuple(row) for row in conn.execute("SELECT source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank FROM similarity_items ORDER BY source_video_id, rank")]
    finally:
        conn.close()
    return sources, items


def test_live_marker_blocks_writes_with_one_log_line(empty_cache_server, live_pid, caplog):
    """While the build marker holds a live PID, `_write_cache` stores no row in either table, two skips log one throttled `build-marker` line, and the Engine leaves the marker in place."""
    caplog.set_level(logging.INFO)
    server = empty_cache_server
    marker = _marker_path(server)
    marker.write_text(str(live_pid), encoding="ascii")

    _write_two_entries(server, "S")
    _write_two_entries(server, "T")

    assert _committed(server.similarity_db_path) == ([], [])  # two uncached sources, no row in either table
    skip_lines = [record.getMessage() for record in caplog.records if "write skipped reason=build-marker" in record.getMessage()]
    assert len(skip_lines) == 1, [record.getMessage() for record in caplog.records]  # two skips, one line
    assert marker.read_text(encoding="ascii") == str(live_pid)  # the Engine never deletes a marker

    marker.unlink()
    _write_two_entries(server, "S")
    assert _committed(server.similarity_db_path) == ([("S", HOST)], MARKER_STORED_ITEMS)  # control: the same call stores once the marker is gone, so the empty tables above came from the marker


@pytest.mark.parametrize("content", NON_BLOCKING, ids=NON_BLOCKING_IDS)
def test_dead_or_unparseable_marker_does_not_block_and_is_kept(empty_cache_server, content):
    """A build marker whose PID is dead, unparseable, non-positive or out of range does not block `_write_cache`, and the Engine leaves it for the updater to judge."""
    server = empty_cache_server
    marker = _marker_path(server)
    text = _marker_text(content)
    marker.write_text(text, encoding="ascii")

    _write_two_entries(server, "S")

    assert _committed(server.similarity_db_path) == ([("S", HOST)], MARKER_STORED_ITEMS)
    assert marker.read_text(encoding="ascii") == text  # left in place for the updater to judge


SOURCE = {"video_id": "S", "instance_domain": HOST}
# Every swap test cache holds one item for S; require_full=False makes that a hit whatever the limit.
READ_POLICY = SimilarityCachePolicy(require_full=False)
SWAP_ENTRIES = [{"video_id": "X", "instance_domain": HOST, "score": 0.9, "rank": 1}]
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
def cached_server(tmp_path: Path):
    path = tmp_path / "similarity-cache.db"
    _cache(path, "A")
    stub = SimpleNamespace(similarity_db=connect_similarity_db(path), similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=_identity(path))
    yield stub
    if stub.similarity_db is not None:
        stub.similarity_db.close()


def _read(server: SimpleNamespace) -> list[str]:
    return [entry["video_id"] for entry in similarity_candidates._read_cache(server, SOURCE, 10, READ_POLICY)]


def _write_one_entry(server: SimpleNamespace, video_id: str) -> None:
    similarity_candidates._write_cache(server, {"video_id": video_id, "instance_domain": HOST}, SWAP_ENTRIES, SimilarityCachePolicy())


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


def test_valid_replace_moves_reads_to_new_file_and_closes_old_handle(cached_server, tmp_path, caplog):
    """Once `similarity_db_path` names a different inode holding a valid cache, `_read_cache` reads it through a new handle, closes the old one, records the new identity and logs one `reopen ok` line with both inodes; a matching inode is not reopened again."""
    caplog.set_level(logging.INFO)
    server = cached_server
    old = server.similarity_db
    old_identity = server.similarity_db_identity
    assert _read(server) == ["A"]  # control: the stub serves the first file
    replacement = tmp_path / "next.db"
    _cache(replacement, "B")
    os.replace(replacement, server.similarity_db_path)
    new_identity = _identity(server.similarity_db_path)
    assert new_identity != old_identity  # control: the path now names a different inode

    assert _read(server) == ["B"]  # read from the new file, not through the old handle
    reopened = server.similarity_db
    assert reopened is not old
    with pytest.raises(sqlite3.ProgrammingError):  # the old handle is closed
        old.execute("SELECT 1")
    assert server.similarity_db_identity == new_identity
    reopen_ok = [message for message in _messages(caplog) if "reopen ok" in message]
    assert len(reopen_ok) == 1, _messages(caplog)
    assert str(old_identity[1]) in reopen_ok[0] and str(new_identity[1]) in reopen_ok[0], reopen_ok  # the line carries both inodes

    assert _read(server) == ["B"]
    assert server.similarity_db is reopened  # a matching inode is not reopened again
    assert len([message for message in _messages(caplog) if "reopen ok" in message]) == 1


def _assert_on_old_handle(server: SimpleNamespace, old: sqlite3.Connection, old_identity: tuple[int, int], old_inode: Path) -> None:
    assert _read(server) == ["A"]  # reads come from the old handle
    assert _read(server) == ["A"]
    _write_one_entry(server, "W")  # skips; a write through the replaced handle would raise `attempt to write a readonly database`
    assert server.similarity_db is old  # the old handle is kept
    assert server.similarity_db_identity == old_identity  # and so is its inode record
    assert _sources(old_inode) == ["S"]  # the old inode gains no row


def test_invalid_or_missing_path_keeps_old_handle_and_writes_nowhere(cached_server, tmp_path, caplog, monkeypatch):
    """While `similarity_db_path` names a text file, a schema-less SQLite file or nothing, reads keep coming from the old handle, one reopen warning is logged per target, and `_write_cache` skips as `stale-handle` without writing to either inode; a valid cache replaced in later is picked up and written to."""
    caplog.set_level(logging.INFO)
    server = cached_server
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
    assert len(_reopen_warnings(caplog)) == 1, _messages(caplog)  # one warning for the text file, however often it is retried
    assert len(_stale_skips(caplog)) == 1, _messages(caplog)  # the write was skipped as stale, not refused by SQLite and swallowed
    assert path.read_bytes() == b"not a database\n"  # the new file gains nothing

    clock[0] += 3600.0
    os.replace(bare, path)
    _assert_on_old_handle(server, old, old_identity, old_inode)
    assert len(_reopen_warnings(caplog)) == 2, _messages(caplog)  # one more for the schema-less file
    assert len(_stale_skips(caplog)) == 2, _messages(caplog)  # this write too was skipped as stale
    assert path.read_bytes() == bare_bytes  # no cache tables or rows created in it

    clock[0] += 3600.0
    path.unlink()
    _assert_on_old_handle(server, old, old_identity, old_inode)
    assert len(_reopen_warnings(caplog)) == 3, _messages(caplog)  # one more for the missing path
    assert len(_stale_skips(caplog)) == 3, _messages(caplog)  # and this write too
    assert not path.exists()  # nothing is created at the missing active path

    clock[0] += 3600.0
    replacement = tmp_path / "next.db"
    _cache(replacement, "C")
    os.replace(replacement, path)
    assert _read(server) == ["C"]  # a valid cache replaced in later is picked up
    assert server.similarity_db is not old
    with pytest.raises(sqlite3.ProgrammingError):
        old.execute("SELECT 1")
    assert server.similarity_db_identity == _identity(path)
    assert len(_reopen_warnings(caplog)) == 3, _messages(caplog)  # the valid target logs no warning
    _write_one_entry(server, "W")
    assert _sources(path) == ["S", "W"]  # control: the same write stores once the handle is on the active file, so the skips above came from the stale handle
    assert len(_stale_skips(caplog)) == 3, _messages(caplog)  # control: a write on the active file logs no skip, though the clock would let one through
    assert _sources(old_inode) == ["S"]


def test_concurrent_reads_during_replaces_see_no_error_and_no_miss(cached_server, tmp_path):
    """With 8 threads reading while 20 valid caches are replaced in one after another, no read raises, none comes back empty, and every replaced cache is read."""
    server = cached_server
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

    assert errors == []  # no read raises during the swaps
    assert [ids for ids in results if not ids] == []  # no read comes back empty (a read on a just-closed handle is swallowed as a miss)
    assert picked == [f"V{index}" for index in range(REPLACES)]  # every replaced cache was read


def test_server_without_path_reads_and_writes_as_before(tmp_path):
    """A server with a handle and a lock but no `similarity_db_path` reads and stores through its handle as before, is never reopened and gains no attributes."""
    path = tmp_path / "similarity-cache.db"
    _cache(path, "A")
    conn = connect_similarity_db(path)
    stub = SimpleNamespace(similarity_db=conn, similarity_db_lock=threading.Lock())
    try:
        assert _read(stub) == ["A"]  # no path, no reopen
        _write_one_entry(stub, "W")
        assert _sources(path) == ["S", "W"]
        assert stub.similarity_db is conn
        assert sorted(vars(stub)) == ["similarity_db", "similarity_db_lock"]  # no identity or reopen state added
    finally:
        conn.close()
