"""A connection prepared by `attach_trending_override` reads `trending_ranks` from the attached file, and a plain connection on the same main reads main's:

- On `_ranks_db` (main ranks giving `TRENDING_EXPECTED`) with a private file holding the same keys ranked in `OVERRIDE_EXPECTED`, the reverse order: a plain connection serves `TRENDING_EXPECTED` from `fetch_ordered_page(conn, "trending", ...)` and `fetch_popular_videos`, a second connection on the same main prepared with `attach_trending_override` serves `OVERRIDE_EXPECTED` from both, the plain connection still serves `TRENDING_EXPECTED` afterwards, and `main.trending_ranks` holds exactly the rows written to it.
- On a 4,000-row main DB whose own `trending_ranks` is empty, with the ranks written to a private file after `prepare_trending_override`, the prepared connection reads a full Trending page from the file, its `EXPLAIN QUERY PLAN` names `idx_trending_ranks_order` and has no `TEMP B-TREE`; the same capture for Popular shows the temp B-tree (control).

The fixtures, `TRENDING_EXPECTED` and `_plan` are the harness in `tests/active/test_random_videos.py`, loaded by path so its tests are not collected here. The override helpers are looked up on `data.trending` when called, so the controls that need none of them run first.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_HARNESS_SPEC = importlib.util.spec_from_file_location("random_videos_harness", ROOT / "tests" / "active" / "test_random_videos.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server and its api dir on sys.path, which the data imports below need.
_HARNESS_SPEC.loader.exec_module(harness)

from data import random_videos, trending  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402

# The override file's order: TRENDING_EXPECTED reversed, written as ranks 1..10 on equal listed likes and views so the rank alone orders them. GHOST and U keep a rank there too and stay unserved.
OVERRIDE_EXPECTED = ["B5", "A3", "E", "A2", "C2", "B2", "A1", "B1", "X", "C1"]
OVERRIDE_UNSERVED = ("GHOST", "U")


def _private_file(path: Path) -> Path:
    """An empty file touched at `path`, then given the trending schema by `prepare_trending_override`."""
    path.touch()
    trending.prepare_trending_override(str(path))
    return path


def _prepared(main: Path, private: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(main)
    conn.row_factory = sqlite3.Row
    trending.attach_trending_override(conn, str(private))
    return conn


def _catalogue(conn: sqlite3.Connection) -> None:
    """30 hosts of 100 embedded catalogue rows, and 1,000 embedded rows `_catalogue_ranks` leaves unranked, on `conn`."""
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()


def _catalogue_ranks(ranks_conn: sqlite3.Connection) -> None:
    """The 30 hosts' catalogue rows ranked 1..100, on `ranks_conn`."""
    for h in range(30):
        for rank in range(1, 101):
            ranks_conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (f"h{h:02d}.example", f"v{rank:03d}", rank, 100 - rank, 1000 - rank))
    ranks_conn.commit()


def test_trending_and_the_popular_pool_read_main_ranks_without_the_override_and_the_file_s_ranks_with_it(tmp_path):
    main = tmp_path / "main.db"
    plain = harness._ranks_db(main)
    assert OVERRIDE_EXPECTED != harness.TRENDING_EXPECTED and sorted(OVERRIDE_EXPECTED) == sorted(harness.TRENDING_EXPECTED)  # control: the same rows in another order, so only the ranks source decides which order is served
    written = sorted((host, video_id, rank, likes, views, 0) for video_id, host, rank, likes, views, *_ in harness.RANKS.values() if rank is not None)

    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: unprepared, the Trending page reads main's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(plain, 100)) == harness.TRENDING_EXPECTED  # C1: unprepared, the popular pool reads main's ranks
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    for rank, label in enumerate(OVERRIDE_EXPECTED, start=1):
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, 10, 10, 0)", (host, video_id, rank))
    for label in OVERRIDE_UNSERVED:
        video_id, host = harness.RANKS[label][:2]
        writer.execute("INSERT INTO trending_ranks VALUES (?, ?, 1, 999, 999, 0)", (host, video_id))
    writer.commit()
    writer.close()
    prepared = _prepared(main, private)
    # Observed: a bare ATTACH of this file, which leaves main.trending_ranks in front, still serves TRENDING_EXPECTED from both reads.
    assert harness._trending_labels(random_videos.fetch_ordered_page(prepared, "trending", 100, 0)) == OVERRIDE_EXPECTED  # C1: prepared, the Trending page reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_popular_videos(prepared, 100)) == OVERRIDE_EXPECTED  # C1: prepared, the popular pool reads the file's ranks
    assert harness._trending_labels(random_videos.fetch_ordered_page(plain, "trending", 100, 0)) == harness.TRENDING_EXPECTED  # C1: the override stays on the prepared connection; the plain one still reads main's ranks
    assert sorted(tuple(row) for row in plain.execute("SELECT * FROM main.trending_ranks")) == written  # C1: main's ranks are left as written


def test_a_trending_page_on_the_override_file_walks_its_ranks_index_without_sorting(tmp_path):
    main = tmp_path / "main.db"
    conn = harness._schema(main)
    _catalogue(conn)
    # Control: main's own ranks are empty, so a full page on the prepared connection can only come from the file (observed: a bare ATTACH of it, with main.trending_ranks still in front, serves 0 rows).
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0) == []
    private = _private_file(tmp_path / "private.db")
    writer = sqlite3.connect(private)
    _catalogue_ranks(writer)
    writer.close()
    prepared = _prepared(main, private)
    # Control: the plan shows a sort where an order has no index (observed: USE TEMP B-TREE FOR ORDER BY).
    assert any("TEMP B-TREE" in detail for detail in harness._plan(prepared, "popular"))
    # _plan also asserts the prepared connection read a full 50-row page 100 rows in.
    details = harness._plan(prepared, "trending")
    assert any("idx_trending_ranks_order" in detail for detail in details), details  # C2: the Trending page walks the file's ranks index
    assert not any("TEMP B-TREE" in detail for detail in details), details  # C2: and does not sort (observed: an unindexed temp copy of the ranks plans SCAN t and USE TEMP B-TREE FOR ORDER BY)
