"""The random cache stores and serves ANN ids in a `random_ann_ids` table drawn from the source's `video_embeddings.ann_id`, and a cache holding only the old `random_rowids` table counts as having none and is rebuilt into the new shape.

- Over a 20-row source whose `ann_id`s share nothing with rowids 1..20 (control), `populate_random_cache` (unfiltered, and filtered with an uncapped author limit) returns 20, writes a file whose only table is `random_ann_ids`, and `fetch_random_ann_ids` on it returns exactly the source's 20 `ann_id`s.
- An unfiltered populate of 5 whose random start is the largest `ann_id` holds that id and the four smallest, the window wrapping in `ann_id` order.
- A filtered populate capped at 2 per author over three channels returns 6 and holds 6 distinct source `ann_id`s, 2 per channel.
- `fetch_random_ann_ids` returns a seeded cache's ids in position order, and nothing at limit 0.
- `fetch_random_rows_from_cache` turns a cache of [C, 1, A, unknown id, D] into the videos C, A, D: an id no row carries is dropped, and so is 1, which is only a rowid, the one D's embedding happens to hold (control).
- `precompute-random-rowids.py --size 20` on a fresh `--out` writes positions 1..20 over exactly the source's `ann_id`s into a file whose only table is `random_ann_ids`.
- `open_random_cache_if_usable` gives a handle serving a 3-id `random_ann_ids` cache, and None with `reason=empty` for an empty one (controls). For a 20-row `random_rowids` file it gives None and logs `reason=no_table`.
- Starting from that old file, `refresh_random_cache` returns True. The active path is at a new inode holding only `random_ann_ids`, and the owner serves exactly the source's `ann_id`s.
- The job without flags at `--size 20` keeps a 20-id `random_ann_ids` `--out` at the same inode with the same bytes (control). It replaces a 20-row `random_rowids` `--out` with one at a new inode that holds positions 1..20 over exactly the source's `ann_id`s and only `random_ann_ids`. The directory then holds only `--out`.

The in-process cases use temporary sqlite files and a `SimpleNamespace` owner with `threading.Lock`s. The scripted window start replaces `random_cache.random`, the random source. The job runs as a child process through `sys.executable`.
"""
from __future__ import annotations

import importlib.util
import logging
import random
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
PRECOMPUTE_JOB = JOBS_DIR / "precompute-random-rowids.py"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.db as db  # noqa: E402
import data.random_cache as random_cache  # noqa: E402
import data.random_videos as random_videos  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402

HOST = "a.example"
SOURCE_ROWS = 20
CHANNEL_OF = {f"v{index}": f"c{index % 3}" for index in range(1, SOURCE_ROWS + 1)}
# The ann_id each source row is stored under; the cache must hold these, never rowids 1..20.
SOURCE_IDS = sorted(compute_ann_id(label, HOST) for label in CHANNEL_OF)
CHANNEL_BY_ID = {compute_ann_id(label, HOST): channel for label, channel in CHANNEL_OF.items()}
STALE_ROWID = 999
# Above every cache here, so a fetch reads from position 1 without a random start.
READ_ALL = 100
WINDOW = 5
PER_AUTHOR = 2
LABELS = ["A", "B", "C", "D"]


def _source_db(tmp_path: Path) -> Path:
    """A source of 20 embedded videos on one instance over three channels, each stored with its computed ann_id."""
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, ann_id INTEGER NOT NULL)")
    for label, channel in CHANNEL_OF.items():
        conn.execute("INSERT INTO videos VALUES (?, ?, ?)", (label, HOST, channel))
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?)", (label, HOST, compute_ann_id(label, HOST)))
    conn.commit()
    conn.close()
    return path


def _seed_cache(path: Path, ann_ids: list[int]) -> None:
    """Write a `random_ann_ids` cache holding `ann_ids` at positions 1.., through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)", list(enumerate(ann_ids, start=1)))
    conn.commit()
    conn.close()


def _seed_old_cache(path: Path) -> None:
    """Write a cache in the pre-cutover shape: 20 `random_rowids` rows and no `random_ann_ids`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(position, STALE_ROWID) for position in range(1, SOURCE_ROWS + 1)])
    conn.commit()
    conn.close()


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(path: Path) -> set[str]:
    conn = _read_only(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def _cache_rows(path: Path) -> list[tuple[int, int]]:
    """A cache file's (position, ann_id) rows in position order."""
    conn = _read_only(path)
    try:
        return conn.execute("SELECT position, ann_id FROM random_ann_ids ORDER BY position").fetchall()
    finally:
        conn.close()


def _populate(tmp_path: Path, size: int, filtered: bool, max_per_author: int) -> tuple[int, list[int], Path]:
    """Populate a fresh cache file from the 20-row source; return the count, the ids `fetch_random_ann_ids` reads back, and the file."""
    source = db.connect_readonly_db(_source_db(tmp_path))
    cache_path = tmp_path / "cache.db"
    cache = random_cache.connect_random_cache_db(cache_path)
    try:
        built = random_cache.populate_random_cache(source, cache, size, True, filtered, 0, max_per_author)
        served = random_cache.fetch_random_ann_ids(cache, READ_ALL)
    finally:
        cache.close()
        source.close()
    return built, served, cache_path


def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PRECOMPUTE_JOB), "--db", str(tmp_path / "source.db"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


# ---- C1: the cache stores and serves the source's ann_ids from random_ann_ids ----


@pytest.mark.parametrize(("filtered", "max_per_author"), [(False, 0), (True, 100)], ids=["unfiltered", "filtered"])
def test_populate_over_the_whole_source_stores_and_serves_exactly_its_ann_ids(tmp_path: Path, filtered: bool, max_per_author: int) -> None:
    # control: the source's ids are 20 distinct values outside rowids 1..20, so a cache of rowids cannot equal them.
    assert len(set(SOURCE_IDS)) == SOURCE_ROWS
    assert set(SOURCE_IDS).isdisjoint(range(1, SOURCE_ROWS + 1))

    built, served, cache_path = _populate(tmp_path, READ_ALL, filtered, max_per_author)

    assert built == SOURCE_ROWS  # C1
    assert sorted(served) == SOURCE_IDS  # C1
    assert _tables(cache_path) == {"random_ann_ids"}  # C1


def test_an_unfiltered_window_starting_at_the_largest_ann_id_wraps_to_the_smallest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The window start is the build's random source; scripting it at the top of the range forces the wrap-around.
    monkeypatch.setattr(random_cache, "random", SimpleNamespace(randint=lambda low, high: high, shuffle=random.shuffle))

    built, served, _ = _populate(tmp_path, WINDOW, False, 0)

    assert built == WINDOW  # C1
    assert sorted(served) == sorted([SOURCE_IDS[-1], *SOURCE_IDS[:WINDOW - 1]])  # C1


def test_a_capped_filtered_populate_draws_distinct_source_ann_ids_up_to_the_cap_per_channel(tmp_path: Path) -> None:
    built, served, _ = _populate(tmp_path, READ_ALL, True, PER_AUTHOR)

    assert built == 6  # C1
    assert set(served) <= set(SOURCE_IDS)  # C1
    assert len(set(served)) == 6  # C1
    assert Counter(CHANNEL_BY_ID[ann_id] for ann_id in served) == {"c0": 2, "c1": 2, "c2": 2}  # C1


def test_fetch_random_ann_ids_returns_a_caches_ids_in_position_order(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    seeded = [SOURCE_IDS[7], SOURCE_IDS[2], SOURCE_IDS[11]]
    _seed_cache(path, seeded)
    conn = db.connect_readonly_db(path)
    try:
        assert random_cache.fetch_random_ann_ids(conn, READ_ALL) == seeded  # C1
        assert random_cache.fetch_random_ann_ids(conn, 0) == []  # C1
    finally:
        conn.close()


def test_cached_rows_resolve_each_cached_ann_id_to_its_video_and_drop_ids_no_row_carries(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_test_42_phase2", JOBS_DIR / "sync-whitelist.py")
    sync_job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_job)
    conn = sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    # Embedded last label first, so D's embedding holds rowid 1.
    for label in reversed(LABELS):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, nsfw, last_checked_at) VALUES (?, ?, ?, ?, ?, 0, 1)", (label, f"u-{label}", HOST, f"ch-{label}", f"title {label}"))
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, x'00', 1, 'm', 'now', ?)", (label, HOST, compute_ann_id(label, HOST)))
    conn.commit()
    unknown = compute_ann_id("gone", HOST)
    # control: 1 is a rowid that names D's embedding, and `unknown` is carried by no row, so only an ann_id lookup drops both.
    assert [tuple(row) for row in conn.execute("SELECT video_id FROM video_embeddings WHERE rowid = 1")] == [("D",)]
    assert conn.execute("SELECT COUNT(*) FROM video_embeddings WHERE ann_id IN (?, 1)", (unknown,)).fetchone()[0] == 0
    cache_path = tmp_path / "cache.db"
    _seed_cache(cache_path, [compute_ann_id("C", HOST), 1, compute_ann_id("A", HOST), unknown, compute_ann_id("D", HOST)])
    owner = SimpleNamespace(random_cache_db=db.connect_readonly_db(cache_path), random_cache_lock=threading.Lock(), db=conn, db_lock=threading.Lock())
    try:
        rows = random_videos.fetch_random_rows_from_cache(owner, READ_ALL)
    finally:
        owner.random_cache_db.close()
        conn.close()

    assert [(row["video_id"], row["instance_domain"], row["title"]) for row in rows] == [("C", HOST, "title C"), ("A", HOST, "title A"), ("D", HOST, "title D")]  # C1


def test_job_writes_positions_over_exactly_the_source_ann_ids_into_random_ann_ids(tmp_path: Path) -> None:
    _source_db(tmp_path)
    out_path = tmp_path / "out" / "random-cache.db"

    result = _run_job(tmp_path, out_path, "--size", str(SOURCE_ROWS))

    assert result.returncode == 0, result.stderr  # C1
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C1
    assert sorted(row[1] for row in rows) == SOURCE_IDS  # C1
    assert _tables(out_path) == {"random_ann_ids"}  # C1


# ---- C2: a cache holding only random_rowids counts as having no table and is rebuilt ----


def test_open_treats_a_cache_holding_only_random_rowids_as_having_no_table(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    current = tmp_path / "current" / "random-cache.db"
    _seed_cache(current, SOURCE_IDS[:3])
    empty = tmp_path / "empty" / "random-cache.db"
    _seed_cache(empty, [])
    old = tmp_path / "old" / "random-cache.db"
    _seed_old_cache(old)
    caplog.set_level(logging.INFO)

    assert random_cache.open_random_cache_if_usable(old) is None  # C2
    assert f"random cache unusable path={old} reason=no_table" in caplog.messages  # C2

    usable = random_cache.open_random_cache_if_usable(current)
    # control: the same opener serves a non-empty random_ann_ids cache, and reports an empty one as empty, not as tableless.
    assert usable is not None
    try:
        assert random_cache.fetch_random_ann_ids(usable, READ_ALL) == SOURCE_IDS[:3]
    finally:
        usable.close()
    assert random_cache.open_random_cache_if_usable(empty) is None
    assert f"random cache unusable path={empty} reason=empty" in caplog.messages


def test_refresh_rebuilds_a_random_rowids_cache_into_random_ann_ids_and_serves_it(tmp_path: Path) -> None:
    source_path = _source_db(tmp_path)
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_old_cache(active_path)
    old_inode = active_path.stat().st_ino
    owner = SimpleNamespace(random_cache_db=random_cache.open_random_cache_if_usable(active_path), random_cache_lock=threading.Lock())
    assert owner.random_cache_db is None  # C2: the old cache is not served

    swapped = random_cache.refresh_random_cache(source_path, active_path, READ_ALL, False, 0, 0, owner, threading.Event())

    assert swapped is True  # C2
    assert active_path.stat().st_ino != old_inode  # C2
    assert _tables(active_path) == {"random_ann_ids"}  # C2
    with owner.random_cache_lock:
        served = random_cache.fetch_random_ann_ids(owner.random_cache_db, READ_ALL)
    owner.random_cache_db.close()
    assert sorted(served) == SOURCE_IDS  # C2


def test_job_rebuilds_an_out_holding_only_random_rowids_and_keeps_one_holding_random_ann_ids(tmp_path: Path) -> None:
    _source_db(tmp_path)
    current = tmp_path / "current" / "random-cache.db"
    _seed_cache(current, SOURCE_IDS)
    old = tmp_path / "old" / "random-cache.db"
    _seed_old_cache(old)
    current_inode, current_bytes = current.stat().st_ino, current.read_bytes()
    old_inode = old.stat().st_ino

    kept = _run_job(tmp_path, current, "--size", str(SOURCE_ROWS))
    rebuilt = _run_job(tmp_path, old, "--size", str(SOURCE_ROWS))

    assert rebuilt.returncode == 0, rebuilt.stderr  # C2
    # The seeded file still exists when the replacing file is created beside it, so the two cannot share an inode; an in-place write keeps it.
    assert old.stat().st_ino != old_inode  # C2
    rows = _cache_rows(old)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C2
    assert sorted(row[1] for row in rows) == SOURCE_IDS  # C2
    assert _tables(old) == {"random_ann_ids"}  # C2
    assert [path.name for path in old.parent.iterdir()] == [old.name]  # C2
    # control: at the same size and without flags, a random_ann_ids `--out` is kept unwritten, so the rebuild above is the old table's doing.
    assert kept.returncode == 0, kept.stderr
    assert current.stat().st_ino == current_inode
    assert current.read_bytes() == current_bytes
