"""The Engine's random, popular and global-feed reads: their orders, their pages and the rows they return.

`fetch_ordered_page(conn, "trending", ...)` walks catalogue rows in `trending_ranks` order and ends on an empty page, and the popular layer's pool is the head of that order:

- With and without an error threshold of 3 and the NSFW filter, and with `idx_trending_ranks_order` present and dropped, Trending pages of 1, 2 and 3 rows, paged to one past the end, concatenate with no repeat into the hand-derived `TRENDING_EXPECTED` order (rank, then listed likes, listed views, `video_id` and domain, all descending but rank), and the page at the end offset is `[]`. A ranked row absent from `videos`, a ranked row with no embedding and an embedded row with no rank are never served.
- With `trending_ranks` emptied, the Trending page and `fetch_popular_videos` are both `[]`, while the Popular order still serves the catalogue.
- `fetch_popular_videos(conn, n, ...)` is the hand-derived head of the Trending order and equals `fetch_ordered_page(conn, "trending", n, 0, ...)` row for row, for every n up to one past the order and every filter combination.
- On a 4,000-row DB, the query `fetch_ordered_page` runs for a Trending page has an `EXPLAIN QUERY PLAN` naming `idx_trending_ranks_order` and no `TEMP B-TREE`; the same capture for Popular shows the temp B-tree (control).
- Every order in `ORDERED_FEED_ORDER_BY` serves rows through `fetch_ordered_page`, and `ORDERED_FEED_SOURCE` holds a source for each of them and no other.

Those run on a temp whitelist-shaped DB holding the labelled rows in `RANKS`: four hosts, ranks with gaps, a ranked row absent from `videos`, a ranked row with no embedding, an embedded row with no rank, an NSFW row and a row at the error threshold. Crawled likes and popularity run opposite to the ranks.

Popular and Recent page through `fetch_ordered_page` as one total order over the rows each may serve:

- With no error threshold and with a threshold of 3, pages of 1, 2 and 3 rows fetched at increasing offsets, one page past the end included, concatenate with no `(video_id, instance_domain)` repeated into the hand-derived order: for popular, crawled likes descending, then views, then `video_id`; for recent, `published_at` descending. In both orders two rows of one domain equal on every key above `video_id` come out higher `video_id` first, and two rows equal in all but `instance_domain` come out higher domain first.
- A single page of either order holds exactly the embedded rows whose error count is under the threshold, when one is given. A video with no embedding is left out, and so, under the threshold, is a video with an error count equal to it, while one at the threshold minus one stays. Recent also leaves out a NULL and a future `published_at`.

Those run on a temporary copy of eight real videos out of `whitelist.db`, set to the values in `VIDEOS`, plus a copy of one of them under a higher `instance_domain`. B also carries an `interaction_signals` row, which no order reads.

The orders rank on stored counts, whatever `interaction_signals` holds:

- Popular pages rank by crawled `likes`, then views: a video with a `likes_count` of 100 stays at its crawled likes' place.

Those run on a temporary copy of seven real videos, set to the values in `SIGNAL_VIDEOS`, with the signal rows in `SIGNALS` keyed to them.

Rows report the crawled like count, and the ordered rows carry no interaction signal score:

- `fetch_random_rows` and `fetch_ordered_page` for popular and recent each report `likes` as the video's stored `videos.likes`: 3 for a video whose `interaction_signals` row holds 50 likes, and 11 for a video with no signal row. This holds with no error threshold and with one.
- `fetch_ordered_page` for popular and recent returns rows with no `interaction_signal_score` key, while each row still carries `video_id`, `likes` and `popularity`, with no error threshold and with one.

Those run on a temporary copy of two real videos, set to the values in `LIKES_VIDEOS`, the first with a signal row.

With `include_nsfw=False` the listing reads leave out every `nsfw = 1` video inside their SQL, so LIMIT and OFFSET count only the rows that are allowed:

- `fetch_random_rows`, `fetch_recent_videos` and `fetch_ordered_page` for popular and recent, each with no error threshold and with a threshold of 3: the default call and `include_nsfw=True` return all nine videos (E dropped under the threshold), and `include_nsfw=False` returns exactly A, B, C, D and E (E dropped under the threshold), whose `nsfw` values are 0 and NULL and none 1.
- NSFW videos head Popular and Recent, and one more sits mid-order. With the filter on, `fetch_ordered_page` pages of 1, 2 and 3 rows, fetched at increasing offsets to one past the end, concatenate with no repeat into the single filtered page, which is the allowed videos in order.
- With the filter on, `fetch_recent_videos` at LIMIT n returns the first n allowed videos for every n up to the allowed count, and `fetch_random_rows` at LIMIT (allowed count) returns every allowed video on each of five draws.

Those run on an in-memory database of nine videos in `NSFW_ORDER` with the `nsfw` values in `NSFW_FLAGS`.

With the filter on, the random-cache draw refills past NSFW rows instead of coming back short; with it off, it makes one draw:

- `fetch_random_rows_from_cache(include_nsfw=False)`, limit 4, over the cache X1 A X2 B C X3 D E with windows starting at 0, 2 and 4: three draws, and the page is A, B, C, D. The rows are in draw order, B and C are not repeated from the overlapping window, and E is cut at the limit.
- With one allowed row per window and a limit of `RANDOM_CACHE_NSFW_MAX_DRAWS` + 2, it makes exactly `RANDOM_CACHE_NSFW_MAX_DRAWS` draws, although the next window would add an unseen allowed row. The page is those draws' allowed rows.
- Over a 3-row cache (X1 A X2) at limit 5 it makes two draws of that same whole window and returns A.
- Over an all-NSFW 8-row cache it returns [] after three draws (windows 0, 4, then 0 again, which adds no unseen ANN id). The same cache with the filter off returns X1..X4.
- `include_nsfw=True` and the default call each make one draw of A X1 A R and return A, X1, A. The duplicate is kept, NSFW is included, and the errored R leaves the page short without a redraw.

The cache holds ANN ids, not rowids:

- `fetch_random_rows_from_cache` turns a cache of [C, 1, A, unknown id, D] into the videos C, A, D: an id no row carries is dropped, and so is 1, which is only a rowid, the one D's embedding happens to hold (control).

Those run on an in-memory Engine db and random cache, owned by a SimpleNamespace holding `random_cache_db`, `random_cache_lock`, `db` and `db_lock`; the cache holds each label's computed ann_id. The window start is scripted through `data.random_cache.random`, and draws are counted by wrapping `fetch_random_ann_ids`.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"

from data import random_cache, random_videos  # noqa: E402
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
THRESHOLD = 3
DAY_MS = 86_400_000
PAST_MS = 1_700_000_000_000


def _labels(rows: list[dict], label_of: dict[tuple[str, str], str]) -> list[str]:
    return [label_of.get((row["video_id"], row["instance_domain"]), row["video_id"]) for row in rows]


# The Trending order. label: (video_id, instance_domain, rank or None, listed likes, listed views, nsfw, error_count, in videos, embedded).
RANKS = {
    "C1": ("c1", "c.example", 1, 70, 10, 0, 0, True, True),
    "X": ("x1", "d.example", 1, 60, 10, 1, 0, True, True),
    "B1": ("b1", "b.example", 1, 50, 900, None, 0, True, True),
    "A1": ("a1", "a.example", 1, 50, 100, 0, 0, True, True),
    "B2": ("v-z", "b.example", 2, 10, 10, 0, 0, True, True),
    "C2": ("v-m", "c.example", 2, 10, 10, 0, 0, True, True),
    "A2": ("v-m", "a.example", 2, 10, 10, 0, 0, True, True),
    "E": ("v-a", "d.example", 2, 10, 10, 0, THRESHOLD, True, True),
    "A3": ("a3", "a.example", 3, 500, 5000, 0, 0, True, True),
    "B5": ("b5", "b.example", 5, 400, 4000, 0, 0, True, True),
    "GHOST": ("g1", "f.example", 1, 999, 999, 0, 0, False, False),
    "U": ("u1", "e.example", 1, 999, 999, 0, 0, True, False),
    "N": ("n1", "b.example", None, 0, 0, 0, 0, True, True),
}
# Derived by hand from RANKS. Rank 1: C1 (70 listed likes), X (60), then B1 and A1 on 50 with B1's 900 listed views first. Rank 2: all on 10 likes and 10 views, so video_id descending puts v-z (B2), then the two v-m with c.example (C2) before a.example (A2), then v-a (E). Rank 3: A3, whatever its 500 likes. Rank 5: B5. GHOST is not in videos, U has no embedding and N no rank, so none is served.
TRENDING_EXPECTED = ["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"]
# Keyed by (error_threshold, include_nsfw): the threshold drops E, the filter drops X.
TRENDING_FILTERED = {
    (None, True): TRENDING_EXPECTED,
    (None, False): ["C1", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"],
    (THRESHOLD, True): ["C1", "X", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
    (THRESHOLD, False): ["C1", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
}
TRENDING_FILTERS = list(TRENDING_FILTERED)
TRENDING_LABEL_OF = {(spec[0], spec[1]): label for label, spec in RANKS.items()}


def _schema(path: Path) -> sqlite3.Connection:
    """A whitelist-shaped DB: the crawler schema with the Engine's popularity column, the shared embeddings table, moderation and trending ranks."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    ensure_trending_schema(conn)
    return conn


def _ranks_db(path: Path, ranks_index: bool = True) -> sqlite3.Connection:
    """The RANKS rows, stored last expected first, with crawled likes, views and popularity rising along TRENDING_EXPECTED and highest on the unranked N, so a likes or popularity order comes out reversed."""
    conn = _schema(path)
    if not ranks_index:
        # A walk on the index already runs in the full tie-break order, so an ORDER BY on rank alone passes there (observed); without it, only the ORDER BY orders ties.
        conn.execute("DROP INDEX idx_trending_ranks_order")
    for label in reversed(list(RANKS)):
        video_id, host, rank, likes, views, nsfw, errors, in_videos, embedded = RANKS[label]
        crawled = 100 if label == "N" else TRENDING_EXPECTED.index(label) + 1 if label in TRENDING_EXPECTED else 200
        if in_videos:
            conn.execute(
                "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, likes, views, nsfw, popularity, error_count, published_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (video_id, f"uuid-{label}", host, f"ch-{label}", crawled, 10 * crawled, nsfw, float(crawled), errors, 1_700_000_000_000),
            )
        if embedded:
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
        if rank is not None:
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, likes, views))
    conn.commit()
    return conn


def _trending_labels(rows: list[dict]) -> list[str]:
    return _labels(rows, TRENDING_LABEL_OF)


@pytest.mark.parametrize("ranks_index", (True, False), ids=("ranks-index", "no-ranks-index"))
@pytest.mark.parametrize("threshold,include_nsfw", TRENDING_FILTERS)
def test_trending_pages_walk_ranked_catalogue_rows_by_rank_then_listed_likes_views_video_id_and_domain(tmp_path, threshold, include_nsfw, ranks_index):
    conn = _ranks_db(tmp_path / "ranks.db", ranks_index)
    expected = TRENDING_FILTERED[(threshold, include_nsfw)]
    for limit in (1, 2, 3):
        rows = []
        # One offset past the last row, so a page beyond the end must come back empty.
        for offset in range(0, len(expected) + limit, limit):
            page = random_videos.fetch_ordered_page(conn, "trending", limit, offset, error_threshold=threshold, include_nsfw=include_nsfw)
            assert len(page) <= limit, (limit, offset)
            rows += page
        labels = _trending_labels(rows)
        assert len(labels) == len(set(labels)), (limit, labels)  # no row repeated
        assert labels == expected, (limit, labels)  # no row skipped, in rank, listed likes, listed views, video_id, domain order, and never a ranked row outside the catalogue or an unranked one
        assert random_videos.fetch_ordered_page(conn, "trending", limit, len(expected), error_threshold=threshold, include_nsfw=include_nsfw) == []  # the order ends, with no fallback


def test_an_empty_ranks_table_gives_an_empty_trending_page_and_an_empty_popular_pool(tmp_path):
    conn = _ranks_db(tmp_path / "ranks.db")
    # Control: with ranks present both read rows on this connection, so the two empty results below are the emptied ranks and not a stub.
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0)
    assert random_videos.fetch_popular_videos(conn, 100)
    conn.execute("DELETE FROM trending_ranks")
    conn.commit()
    # Control: the catalogue still serves, so an empty page is the empty order and not an empty DB.
    assert len(random_videos.fetch_ordered_page(conn, "popular", 100, 0)) == 11
    assert random_videos.fetch_ordered_page(conn, "trending", 100, 0) == []  # no fallback to another order
    assert random_videos.fetch_popular_videos(conn, 100) == []  # the popular pool is empty with the ranks


@pytest.mark.parametrize("threshold,include_nsfw", TRENDING_FILTERS)
def test_the_popular_pool_of_size_n_is_the_first_n_rows_of_the_trending_order_under_the_same_filters(tmp_path, threshold, include_nsfw):
    conn = _ranks_db(tmp_path / "ranks.db")
    expected = TRENDING_FILTERED[(threshold, include_nsfw)]
    for n in range(1, len(expected) + 2):
        pool = random_videos.fetch_popular_videos(conn, n, error_threshold=threshold, include_nsfw=include_nsfw)
        assert _trending_labels(pool) == expected[:n], (n, _trending_labels(pool))  # the hand-derived head, not the popularity order N leads
        assert pool == random_videos.fetch_ordered_page(conn, "trending", n, 0, error_threshold=threshold, include_nsfw=include_nsfw), n  # same rows, same shape


class _Recorder:
    """A connection that records each statement and its parameters before running it."""

    def __init__(self, inner: sqlite3.Connection):
        self.inner = inner
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params)))
        return self.inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _plan(conn: sqlite3.Connection, order: str) -> list[str]:
    """The EXPLAIN QUERY PLAN details of the statement fetch_ordered_page runs for one filtered 50-row page past the head."""
    recorder = _Recorder(conn)
    rows = random_videos.fetch_ordered_page(recorder, order, 50, 100, error_threshold=THRESHOLD, include_nsfw=False)
    assert len(rows) == 50 and len(recorder.calls) == 1, (len(rows), len(recorder.calls))  # control: one real query read a full page
    sql, params = recorder.calls[0]
    return [row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]


def test_a_trending_page_walks_the_ranks_index_without_sorting(tmp_path):
    conn = _schema(tmp_path / "plan.db")
    # 30 hosts of 100 ranked catalogue rows, and 1,000 embedded rows with no rank.
    for h in range(30):
        host = f"h{h:02d}.example"
        for rank in range(1, 101):
            video_id = f"v{rank:03d}"
            conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, popularity, last_checked_at) VALUES (?, ?, ?, ?, ?, 0)", (video_id, host, rank, 10 * rank, rank))
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, 100 - rank, 1000 - rank))
    for n in range(1000):
        conn.execute("INSERT INTO videos (video_id, instance_domain, likes, views, last_checked_at) VALUES (?, 'u.example', 1, 1, 0)", (f"u{n}",))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'u.example', x'00', 1, 'm', 't', ?)", (f"u{n}", compute_ann_id(f"u{n}", "u.example")))
    conn.commit()
    # Control: the plan shows a sort where an order has no index (observed: USE TEMP B-TREE FOR ORDER BY).
    assert any("TEMP B-TREE" in detail for detail in _plan(conn, "popular"))
    details = _plan(conn, "trending")
    assert any("idx_trending_ranks_order" in detail for detail in details), details  # the Trending page walks the ranks index
    assert not any("TEMP B-TREE" in detail for detail in details), details  # and does not sort


def test_every_ordered_feed_has_a_source_and_serves_catalogue_rows(tmp_path):
    conn = _ranks_db(tmp_path / "ranks.db")
    for order in random_videos.ORDERED_FEED_ORDER_BY:
        assert random_videos.fetch_ordered_page(conn, order, 100, 0), order  # control: each ordered feed serves rows through fetch_ordered_page
    assert set(getattr(random_videos, "ORDERED_FEED_SOURCE", {})) == set(random_videos.ORDERED_FEED_ORDER_BY)


# Popular and Recent paging. NULL and FUTURE stand for an undated and a future published_at.
NULL = "null"
FUTURE = "future"
# popularity, crawled likes, views, published_at (days before PAST_MS, NULL or FUTURE), error_count. N gets no embedding; T is copied as T2 under a higher domain.
VIDEOS = {
    "A": (30.0, 8, 50, 1, 0),
    "B": (1.0, 2, 10, 5, 0),
    "C": (20.0, 20, 900, NULL, 0),
    "D": (10.0, 20, 500, FUTURE, 0),
    "E": (30.0, 8, 50, 1, THRESHOLD),
    "F": (15.0, 1, 5, 3, THRESHOLD - 1),
    "T": (12.0, 10, 200, 4, 0),
    "N": (0.0, 0, 0, 0, 0),
}
# B's signal: 50 likes would lead popular were the signal read; no order reads it, so B keeps its stored place.
SIGNAL_SCORE = 1000.0
SIGNAL_LIKES = 50
# Insertion order: E and A (same domain, E's id lower, equal on every key above video_id in both orders) are stored first, and T2 after T, so a missing video_id or instance_domain tie-break leaves storage order, the wrong way round. C's id is below D's while C has the more views, so popular without its views key puts D first.
LABELS = ("E", "A", "B", "C", "D", "F", "T", "N")
# Derived by hand from VIDEOS, B's signal ignored. popular: C 20 likes/900 views, D 20/500, T2/T 10, A and E 8/50, B 2, F 1. recent: A and E, F, T2/T, B, dropping C (NULL) and D (future).
EXPECTED = {
    "popular": ["C", "D", "T2", "T", "A", "E", "B", "F"],
    "recent": ["A", "E", "F", "T2", "T", "B"],
}


def _feed_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[tuple[str, str], str]]:
    """A database holding the labelled videos, returned with the label of each (video_id, instance_domain)."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT ?", (len(LABELS),)
    ).fetchall()
    picks = sorted((pick["video_id"], pick["instance_domain"]) for pick in picks)
    assert len({video_id for video_id, _ in picks}) == len(LABELS)  # control: distinct ids
    # E and A share a domain, so only video_id can order them; E takes the lower id. The rest go out in id order, so C's id is below D's.
    domains = [domain for _, domain in picks]
    shared = next(domain for domain in domains if domains.count(domain) >= 2)
    pair = [pick for pick in picks if pick[1] == shared][:2]
    keys = dict(zip(LABELS, pair + [pick for pick in picks if pick not in pair]))
    assert keys["E"][1] == keys["A"][1] and keys["E"][0] < keys["A"][0] and keys["C"][0] < keys["D"][0]  # control
    conn.execute("CREATE TABLE videos AS SELECT * FROM src.videos WHERE 0")
    conn.execute("CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE 0")
    for label in LABELS:
        conn.execute("INSERT INTO videos SELECT * FROM src.videos WHERE video_id = ? AND instance_domain = ?", keys[label])
        if label != "N":
            conn.execute("INSERT INTO video_embeddings SELECT * FROM src.video_embeddings WHERE video_id = ? AND instance_domain = ?", keys[label])
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    future_ms = int(time.time() * 1000) + 365 * DAY_MS
    for label, (popularity, likes, views, published, errors) in VIDEOS.items():
        published_at = None if published == NULL else future_ms if published == FUTURE else PAST_MS - published * DAY_MS
        conn.execute("UPDATE videos SET popularity = ?, likes = ?, views = ?, published_at = ?, error_count = ? WHERE video_id = ? AND instance_domain = ?",
                     (popularity, likes, views, published_at, errors, *keys[label]))
    tie_id, tie_domain = keys["T"]
    keys["T2"] = (tie_id, "zz." + tie_domain)
    assert keys["T2"][1] > tie_domain  # control: the copy, stored after the original, has the higher domain
    conn.execute("INSERT INTO videos SELECT * FROM videos WHERE video_id = ? AND instance_domain = ?", keys["T"])
    conn.execute("UPDATE videos SET instance_domain = ? WHERE rowid = last_insert_rowid()", (keys["T2"][1],))
    conn.execute("INSERT INTO video_embeddings SELECT * FROM video_embeddings WHERE video_id = ? AND instance_domain = ?", keys["T"])
    conn.execute("UPDATE video_embeddings SET instance_domain = ? WHERE rowid = last_insert_rowid()", (keys["T2"][1],))
    uuid = conn.execute("SELECT video_uuid FROM videos WHERE video_id = ? AND instance_domain = ?", keys["B"]).fetchone()[0]
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, ?, ?, 0)",
                 (uuid, keys["B"][1], SIGNAL_LIKES, SIGNAL_SCORE))
    conn.commit()
    return conn, {key: label for label, key in keys.items()}


def _served(order: str, threshold: int | None) -> list[str]:
    return [label for label in EXPECTED[order] if threshold is None or label != "E"]


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ("popular", "recent"))
def test_popular_and_recent_pages_concatenate_into_the_order_s_total_sort(tmp_path, order, threshold):
    conn, label_of = _feed_db(tmp_path)
    expected = _served(order, threshold)
    for limit in (1, 2, 3):
        rows = []
        # One offset past the last row, so a page beyond the end must come back empty.
        for offset in range(0, len(expected) + limit, limit):
            page = random_videos.fetch_ordered_page(conn, order, limit, offset, error_threshold=threshold)
            assert len(page) <= limit, (limit, offset)
            rows += page
        labels = _labels(rows, label_of)
        assert len(labels) == len(set(labels)), (limit, labels)  # no row repeated
        assert labels == expected, (limit, labels)
        assert labels.index("T2") + 1 == labels.index("T"), labels  # the tie comes out instance_domain DESC


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ("popular", "recent"))
def test_a_popular_or_recent_page_holds_exactly_the_embedded_rows_under_the_threshold(tmp_path, order, threshold):
    conn, label_of = _feed_db(tmp_path)
    served = set(_labels(random_videos.fetch_ordered_page(conn, order, 100, 0, error_threshold=threshold), label_of))
    left_out = {"N"} | ({"E"} if threshold is not None else set()) | ({"C", "D"} if order == "recent" else set())
    assert served == set(VIDEOS) - left_out | {"T2"}, served
    assert not served & left_out, served  # no unembedded, at-threshold, NULL or future row


# popularity, crawled likes, views. Labels are assigned to the picked videos in video_id order, so C's id is below G's and B's below C's.
SIGNAL_VIDEOS = {
    "A": (30.0, 5, 100),
    "B": (20.0, 9, 100),
    "C": (20.0, 4, 900),
    "D": (10.0, 1, 50),
    "E": (5.0, 2, 10),
    "F": (1.0, 7, 300),
    "G": (20.0, 4, 100),
}
# signal_score, likes_count. D's 1000 counts as 25 under a capped signal (35, ahead of A); G's 1000, inside the popularity-20 group, would lead that group were the signal a tie-break below popularity; C's 10 likes put it ahead of B on likes (14 against 9); E's 100 likes lead Popular.
SIGNALS = {
    "D": (1000.0, 0),
    "G": (1000.0, 0),
    "C": (0.0, 10),
    "E": (0.0, 100),
}
# Derived by hand from SIGNAL_VIDEOS alone.
# popular: B 9, F 7, A 5, C and G on 4 with C's 900 views first, E 2, D 1.
SIGNAL_EXPECTED = {
    "popular": ["B", "F", "A", "C", "G", "E", "D"],
}


def _signal_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[tuple[str, str], str]]:
    """A database holding the SIGNAL_VIDEOS and their signal rows, returned with the label of each (video_id, instance_domain)."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT ?", (len(SIGNAL_VIDEOS),)
    ).fetchall()
    picks = sorted((pick["video_id"], pick["instance_domain"]) for pick in picks)
    assert len({video_id for video_id, _ in picks}) == len(SIGNAL_VIDEOS)  # control: distinct ids, so the id order is strict
    keys = dict(zip(sorted(SIGNAL_VIDEOS), picks))
    conn.execute("CREATE TABLE videos AS SELECT * FROM src.videos WHERE 0")
    conn.execute("CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE 0")
    for label in SIGNAL_VIDEOS:
        conn.execute("INSERT INTO videos SELECT * FROM src.videos WHERE video_id = ? AND instance_domain = ?", keys[label])
        conn.execute("INSERT INTO video_embeddings SELECT * FROM src.video_embeddings WHERE video_id = ? AND instance_domain = ?", keys[label])
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    # One published_at for all, so where views should decide, a missing views key falls through to video_id rather than to a date.
    for label, (popularity, likes, views) in SIGNAL_VIDEOS.items():
        conn.execute("UPDATE videos SET popularity = ?, likes = ?, views = ?, published_at = ?, error_count = 0 WHERE video_id = ? AND instance_domain = ?",
                     (popularity, likes, views, PAST_MS, *keys[label]))
    for label, (score, likes_count) in SIGNALS.items():
        conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) "
                     "SELECT video_uuid, instance_domain, ?, ?, 0 FROM videos WHERE video_id = ? AND instance_domain = ?",
                     (likes_count, score, *keys[label]))
    conn.commit()
    matched = conn.execute(
        "SELECT v.video_id, v.instance_domain, s.signal_score, s.likes_count FROM interaction_signals s JOIN videos v "
        "ON v.video_uuid = s.video_uuid AND v.instance_domain = s.instance_domain"
    ).fetchall()
    label_of = {key: label for label, key in keys.items()}
    # control: every signal row is keyed to its own copied video, so a join on (video_uuid, instance_domain) reaches it
    assert {label_of[(row["video_id"], row["instance_domain"])]: (row["signal_score"], row["likes_count"]) for row in matched} == SIGNALS
    return conn, label_of


def _paged(conn: sqlite3.Connection, order: str, limit: int, label_of: dict[tuple[str, str], str]) -> list[str]:
    rows = []
    # One offset past the last row, so a page beyond the end must come back empty.
    for offset in range(0, len(SIGNAL_VIDEOS) + limit, limit):
        page = random_videos.fetch_ordered_page(conn, order, limit, offset)
        assert len(page) <= limit, (order, limit, offset)
        rows += page
    return _labels(rows, label_of)


def test_popular_pages_rank_by_crawled_likes_then_views_whatever_the_signal_likes(tmp_path):
    conn, label_of = _signal_db(tmp_path)
    for limit in (1, 2, 3):
        assert _paged(conn, "popular", limit, label_of) == SIGNAL_EXPECTED["popular"], limit


# crawled likes per label. X carries a signal of 50 likes (and a score of 50), so a row adding it reads 53.
LIKES_VIDEOS = {"X": 3, "Y": 11}
LIKES_SIGNAL_LIKES = 50
LIKES_SIGNAL_SCORE = 50.0
# Both videos are stored with error_count 0, so a threshold keeps them while every read takes its filtered WHERE and parameter list.
THRESHOLDS = (None, THRESHOLD)


def _two_video_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[tuple[str, str], str]]:
    """A database holding X and Y and X's signal row, returned with the label of each (video_id, instance_domain)."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT ?", (len(LIKES_VIDEOS),)
    ).fetchall()
    keys = dict(zip(LIKES_VIDEOS, ((pick["video_id"], pick["instance_domain"]) for pick in picks)))
    assert len(set(keys.values())) == len(LIKES_VIDEOS)  # control: two distinct videos
    conn.execute("CREATE TABLE videos AS SELECT * FROM src.videos WHERE 0")
    conn.execute("CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE 0")
    for label in LIKES_VIDEOS:
        conn.execute("INSERT INTO videos SELECT * FROM src.videos WHERE video_id = ? AND instance_domain = ?", keys[label])
        conn.execute("INSERT INTO video_embeddings SELECT * FROM src.video_embeddings WHERE video_id = ? AND instance_domain = ?", keys[label])
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    # A past published_at keeps both in recent, which leaves out undated and future rows.
    for label, likes in LIKES_VIDEOS.items():
        conn.execute("UPDATE videos SET likes = ?, published_at = ?, error_count = 0 WHERE video_id = ? AND instance_domain = ?",
                     (likes, PAST_MS, *keys[label]))
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) "
                 "SELECT video_uuid, instance_domain, ?, ?, 0 FROM videos WHERE video_id = ? AND instance_domain = ?",
                 (LIKES_SIGNAL_LIKES, LIKES_SIGNAL_SCORE, *keys["X"]))
    conn.commit()
    matched = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM interaction_signals s JOIN videos v "
        "ON v.video_uuid = s.video_uuid AND v.instance_domain = s.instance_domain"
    ).fetchall()
    assert [(row["video_id"], row["instance_domain"]) for row in matched] == [keys["X"]]  # control: the signal row reaches X, and only X
    return conn, {key: label for label, key in keys.items()}


def _reads(conn: sqlite3.Connection) -> dict[tuple[str, int | None], list[dict]]:
    """Every read under test, by name and error threshold: the random fallback and one page of the popular and recent orders."""
    reads = {}
    for threshold in THRESHOLDS:
        reads[("random", threshold)] = random_videos.fetch_random_rows(conn, 10, error_threshold=threshold)
        for order in ("popular", "recent"):
            reads[(order, threshold)] = random_videos.fetch_ordered_page(conn, order, 10, 0, error_threshold=threshold)
    return reads


def _by_label(rows: list[dict], label_of: dict[tuple[str, str], str]) -> dict[str, dict]:
    return {label_of[(row["video_id"], row["instance_domain"])]: row for row in rows}


def test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        likes = {label: row["likes"] for label, row in _by_label(rows, label_of).items()}
        assert likes == LIKES_VIDEOS, name


def test_popular_and_recent_order_rows_carry_no_interaction_signal_score(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        if name[0] == "random":
            continue
        by_label = _by_label(rows, label_of)
        assert set(by_label) == set(LIKES_VIDEOS), name  # control: both videos came back, X with its signal row included
        for label, row in by_label.items():
            assert {"video_id", "likes", "popularity"} <= set(row), (name, label)  # control: the row is the full read, not an empty shell
            assert "interaction_signal_score" not in row, (name, label)


# The NSFW filter on the listing reads: one rank order for all of them, the video at rank r having popularity and likes 100 - 10r, views 1000 - 100r, and being r days old, so Popular and Recent both run in this sequence. NSFW rows lead it, sit in its middle and end it.
NSFW_HOST = "h.example"
NSFW_ORDER = ("X1", "X2", "A", "B", "X3", "C", "D", "E", "X4")
NSFW_FLAGS = {"X1": 1, "X2": 1, "A": 0, "B": None, "X3": 1, "C": 0, "D": None, "E": 0, "X4": 1}
# E sits at the threshold, so a threshold drops it whatever the flag.
NSFW_ERRORED = "E"
# Derived by hand from NSFW_ORDER, NSFW_FLAGS and NSFW_ERRORED, keyed by (error_threshold, include_nsfw).
NSFW_EXPECTED = {
    (None, True): ["X1", "X2", "A", "B", "X3", "C", "D", "E", "X4"],
    (None, False): ["A", "B", "C", "D", "E"],
    (THRESHOLD, True): ["X1", "X2", "A", "B", "X3", "C", "D", "X4"],
    (THRESHOLD, False): ["A", "B", "C", "D"],
}
NSFW_VIDEOS_TABLE = "CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))"
NSFW_EMBEDDINGS_TABLE = "CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, ann_id INTEGER NOT NULL, PRIMARY KEY (video_id, instance_domain))"
NSFW_CHANNELS_TABLE = "CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)"


@pytest.fixture
def nsfw_conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for table in (NSFW_VIDEOS_TABLE, NSFW_EMBEDDINGS_TABLE, NSFW_CHANNELS_TABLE):
        db.execute(table)
    # Stored last rank first, so storage order is never the order under test.
    for label in reversed(NSFW_ORDER):
        rank = NSFW_ORDER.index(label) + 1
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, views, likes, nsfw, popularity, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            [label, f"u-{label}", NSFW_HOST, f"ch-{label}", label, PAST_MS - rank * DAY_MS, 1000 - 100 * rank, 100 - 10 * rank, NSFW_FLAGS[label], 100.0 - 10 * rank, THRESHOLD if label == NSFW_ERRORED else 0],
        )
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm', ?)", [label, NSFW_HOST, compute_ann_id(label, NSFW_HOST)])
    db.commit()
    yield db
    db.close()


# Each read at a limit past the nine videos, so it returns every row it may serve.
NSFW_READS = {
    "fetch_random_rows": lambda conn, threshold, **flag: random_videos.fetch_random_rows(conn, 100, error_threshold=threshold, **flag),
    "fetch_recent_videos": lambda conn, threshold, **flag: random_videos.fetch_recent_videos(conn, 100, error_threshold=threshold, **flag),
    "fetch_ordered_page:popular": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "popular", 100, 0, error_threshold=threshold, **flag),
    "fetch_ordered_page:recent": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "recent", 100, 0, error_threshold=threshold, **flag),
}
# Reads whose row order is their contract; the rest are compared in NSFW_ORDER's sequence, duplicates kept.
NSFW_ORDERED_READS = {"fetch_recent_videos", "fetch_ordered_page:popular", "fetch_ordered_page:recent"}


def _nsfw_labels(rows: list[dict]) -> list[str]:
    return [row["video_id"] for row in rows]


def _nsfw_ranked(rows: list[dict]) -> list[str]:
    return sorted(_nsfw_labels(rows), key=NSFW_ORDER.index)


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("name", NSFW_READS)
def test_the_filter_drops_every_nsfw_row_and_keeps_the_null_and_0_rows(nsfw_conn, name, threshold):
    read = NSFW_READS[name]
    shape = _nsfw_labels if name in NSFW_ORDERED_READS else _nsfw_ranked
    assert shape(read(nsfw_conn, threshold)) == NSFW_EXPECTED[(threshold, True)]  # control: unfiltered, the NSFW rows come back
    assert shape(read(nsfw_conn, threshold, include_nsfw=True)) == NSFW_EXPECTED[(threshold, True)]  # filter off runs and is the unfiltered read
    filtered = read(nsfw_conn, threshold, include_nsfw=False)
    assert shape(filtered) == NSFW_EXPECTED[(threshold, False)]  # exactly the allowed rows, in order where order is the contract
    assert [row["video_id"] for row in filtered if row["nsfw"] == 1] == []  # no nsfw = 1 row
    assert {row["nsfw"] for row in filtered} == {0, None}  # the 0 and the NULL rows both stay


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ("popular", "recent"))
def test_filtered_pages_concatenate_into_the_one_filtered_page(nsfw_conn, order, threshold):
    allowed = NSFW_EXPECTED[(threshold, False)]
    assert _nsfw_labels(random_videos.fetch_ordered_page(nsfw_conn, order, 1, 0, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads the order
    whole = _nsfw_labels(random_videos.fetch_ordered_page(nsfw_conn, order, 100, 0, error_threshold=threshold, include_nsfw=False))
    assert whole == allowed  # the single filtered page is the allowed order
    for size in (1, 2, 3):
        rows = []
        # One offset past the last allowed row, so a page beyond the end must come back empty.
        for offset in range(0, len(allowed) + size, size):
            page = random_videos.fetch_ordered_page(nsfw_conn, order, size, offset, error_threshold=threshold, include_nsfw=False)
            assert len(page) <= size, (size, offset)
            rows += page
        labels = _nsfw_labels(rows)
        assert len(labels) == len(set(labels)), (size, labels)  # no repeat
        assert labels == whole, (size, labels)  # no gap: the OFFSET walks the filtered order


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
def test_recent_and_random_limits_count_only_allowed_rows(nsfw_conn, threshold):
    allowed = NSFW_EXPECTED[(threshold, False)]
    assert _nsfw_labels(random_videos.fetch_recent_videos(nsfw_conn, 1, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads Recent
    for n in range(1, len(allowed) + 1):
        assert _nsfw_labels(random_videos.fetch_recent_videos(nsfw_conn, n, error_threshold=threshold, include_nsfw=False)) == allowed[:n], n
    # A LIMIT counting NSFW rows fills every allowed slot on one draw in 70 at best; five draws in a row make that chance negligible.
    for _ in range(5):
        assert _nsfw_ranked(random_videos.fetch_random_rows(nsfw_conn, len(allowed), error_threshold=threshold, include_nsfw=False)) == allowed


def _video_db(videos: list[tuple[str, str]]) -> tuple[sqlite3.Connection, dict[str, int]]:
    """An in-memory Engine db holding `videos` as (label, channel), embedded in that order, and each label's embedding ann_id.

    A label starting X is flagged nsfw = 1 and one starting R sits at THRESHOLD errors; the rest alternate nsfw 0 and NULL.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for table in (NSFW_VIDEOS_TABLE, NSFW_EMBEDDINGS_TABLE, NSFW_CHANNELS_TABLE):
        db.execute(table)
    ann_ids: dict[str, int] = {}
    for index, (label, channel) in enumerate(videos):
        nsfw = 1 if label.startswith("X") else (0 if index % 2 else None)
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (label, f"u-{label}", NSFW_HOST, channel, nsfw, THRESHOLD if label.startswith("R") else 0),
        )
        ann_ids[label] = compute_ann_id(label, NSFW_HOST)
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm', ?)", (label, NSFW_HOST, ann_ids[label]))
    db.commit()
    return db, ann_ids


def _cache_owner(monkeypatch: pytest.MonkeyPatch, cache: list[str], offsets: list[int]) -> tuple[SimpleNamespace, list[list[str]]]:
    """An owner serving a random cache whose positions hold `cache` in order, and the list each draw appends its window to, as labels.

    Draws start at `offsets` in turn; a draw past them fails the test.
    """
    db, ann_ids = _video_db([(label, f"ch-{label}") for label in dict.fromkeys(cache)])
    labels = {ann_id: label for label, ann_id in ann_ids.items()}
    cache_db = sqlite3.connect(":memory:")
    cache_db.row_factory = sqlite3.Row
    cache_db.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    cache_db.executemany("INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)", [(position, ann_ids[label]) for position, label in enumerate(cache, start=1)])
    cache_db.commit()
    scripted = list(offsets)

    def randint(low: int, high: int) -> int:
        assert scripted, "a draw past the scripted windows"
        offset = scripted.pop(0)
        assert low <= offset <= high, (low, high, offset)
        return offset

    # The window start is the draw's random source; scripting it fixes which cache positions each draw reads.
    monkeypatch.setattr(random_cache, "random", SimpleNamespace(randint=randint))
    draws: list[list[str]] = []
    real_fetch = random_cache.fetch_random_ann_ids

    def counting_fetch(cache_conn: sqlite3.Connection, limit: int) -> list[int]:
        window = real_fetch(cache_conn, limit)
        draws.append([labels[ann_id] for ann_id in window])
        return window

    monkeypatch.setattr(random_videos, "fetch_random_ann_ids", counting_fetch)
    return SimpleNamespace(random_cache_db=cache_db, random_cache_lock=threading.Lock(), db=db, db_lock=threading.Lock()), draws


def test_filter_on_redraws_past_nsfw_and_seen_rowids_until_the_page_is_full(monkeypatch):
    owner, draws = _cache_owner(monkeypatch, ["X1", "A", "X2", "B", "C", "X3", "D", "E"], [0, 2, 4])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=False)
    assert draws == [["X1", "A", "X2", "B"], ["X2", "B", "C", "X3"], ["C", "X3", "D", "E"]]  # short after two draws, so a third, and none once the page is full
    assert _nsfw_labels(rows) == ["A", "B", "C", "D"]  # draw order, B and C not repeated from the overlap, E cut at the limit


def test_filter_on_stops_at_the_draw_cap_with_the_page_still_short(monkeypatch):
    cap = random_videos.RANDOM_CACHE_NSFW_MAX_DRAWS
    # One allowed row per window and a limit two above the cap, so neither the cap's draws nor one more fill the page: only the cap stops the loop.
    limit = cap + 2
    windows = [[f"X{k}_{j}" for j in range(limit - 1)] for k in range(cap + 1)]
    for k, window in enumerate(windows):
        window.insert(1, f"A{k}")
    owner, draws = _cache_owner(monkeypatch, [label for window in windows for label in window], [k * limit for k in range(cap + 1)])
    rows = random_videos.fetch_random_rows_from_cache(owner, limit, include_nsfw=False)
    assert draws == windows[:cap]  # exactly the cap, although the next window holds an unseen allowed row
    assert _nsfw_labels(rows) == [f"A{k}" for k in range(cap)]


def test_filter_on_stops_after_a_draw_adds_no_unseen_rowid(monkeypatch):
    # No bigger than the limit, so every draw reads the whole cache from position 1 without a random start.
    owner, draws = _cache_owner(monkeypatch, ["X1", "A", "X2"], [])
    rows = random_videos.fetch_random_rows_from_cache(owner, 5, include_nsfw=False)
    assert draws == [["X1", "A", "X2"], ["X1", "A", "X2"]]  # the second draw added nothing unseen, so no third
    assert _nsfw_labels(rows) == ["A"]


def test_filter_on_returns_nothing_from_an_all_nsfw_cache(monkeypatch):
    cache = [f"X{index}" for index in range(1, 9)]
    owner, _ = _cache_owner(monkeypatch, cache, [0])
    assert _nsfw_labels(random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=True)) == cache[:4]  # control: the same cache serves rows with the filter off
    owner, draws = _cache_owner(monkeypatch, cache, [0, 4, 0])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, include_nsfw=False)
    assert rows == []
    assert draws == [cache[:4], cache[4:], cache[:4]]  # redrew while a draw added unseen ann_ids, stopped at the first that added none


@pytest.mark.parametrize("flag", [{"include_nsfw": True}, {}], ids=["include_nsfw", "default"])
def test_filter_off_makes_one_draw_and_returns_its_rows_duplicates_included(monkeypatch, flag):
    owner, draws = _cache_owner(monkeypatch, ["A", "X1", "A", "R", "B", "C", "D", "E"], [0, 4])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, error_threshold=THRESHOLD, **flag)
    assert draws == [["A", "X1", "A", "R"]]  # one draw, although R's error count leaves the page short
    assert _nsfw_labels(rows) == ["A", "X1", "A"]  # that window's rows, the duplicate and the NSFW row kept


def test_cached_rows_resolve_each_cached_ann_id_to_its_video_and_drop_ids_no_row_carries():
    # Embedded last label first, so D's embedding holds rowid 1.
    db, ann_ids = _video_db([(label, f"ch-{label}") for label in ("D", "C", "B", "A")])
    unknown = compute_ann_id("gone", NSFW_HOST)
    # control: 1 is a rowid that names D's embedding, and `unknown` is carried by no row, so only an ann_id lookup drops both.
    assert [tuple(row) for row in db.execute("SELECT video_id FROM video_embeddings WHERE rowid = 1")] == [("D",)]
    assert db.execute("SELECT COUNT(*) FROM video_embeddings WHERE ann_id IN (?, 1)", (unknown,)).fetchone()[0] == 0
    cache_db = sqlite3.connect(":memory:")
    cache_db.row_factory = sqlite3.Row
    cache_db.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    cache_db.executemany("INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)", list(enumerate([ann_ids["C"], 1, ann_ids["A"], unknown, ann_ids["D"]], start=1)))
    cache_db.commit()
    owner = SimpleNamespace(random_cache_db=cache_db, random_cache_lock=threading.Lock(), db=db, db_lock=threading.Lock())

    # Above the 5 cached ids, so the draw reads the whole cache from position 1 without a random start.
    rows = random_videos.fetch_random_rows_from_cache(owner, 100)

    assert [(row["video_id"], row["instance_domain"]) for row in rows] == [("C", NSFW_HOST), ("A", NSFW_HOST), ("D", NSFW_HOST)]  # cache order, the unknown id and the bare rowid dropped
