"""The Engine's random, popular and global-feed reads: their orders, their pages and the rows they return.

The three global feed orders page through `fetch_ordered_page` as one total order over the rows each may serve:

- `ORDERED_FEED_ORDER_BY` holds exactly hot, popular and recent. For each, with no error threshold and with a threshold of 3, pages of 1, 2 and 3 rows fetched at increasing offsets, one page past the end included, concatenate with no `(video_id, instance_domain)` repeated into the hand-derived order: for hot, popularity descending; for popular, crawled likes descending, then views, then `video_id`; for recent, `published_at` descending. In every order two rows of one domain equal on every key above `video_id` come out higher `video_id` first, and two rows equal in all but `instance_domain` come out higher domain first.
- Hot is the order `fetch_popular_videos` ranks by, tie-break included: for every k, its LIMIT k keeps exactly hot's first k rows.
- A single page of every order holds exactly the embedded rows whose error count is under the threshold, when one is given: a video with no embedding and, under the threshold, a video with an error count equal to it are left out, while one at the threshold minus one stays; recent also leaves out a NULL and a future `published_at`.

Those run on a temporary copy of eight real videos out of `whitelist.db`, set to the values in `VIDEOS`, plus a copy of one of them under a higher `instance_domain`; B also carries an `interaction_signals` row, which no order reads.

The orders rank on stored counts, whatever `interaction_signals` holds:

- Hot pages and `fetch_popular_videos` rank by `popularity`, then crawled `likes`, then views: a video with a `signal_score` of 1000 stays at its popularity's place, among lower and among equal popularities, and a video whose `likes_count` would outscore a popularity rival's crawled likes stays behind it.
- Popular pages rank by crawled `likes`, then views: a video with a `likes_count` of 100 stays at its crawled likes' place.

Those run on a temporary copy of seven real videos, set to the values in `SIGNAL_VIDEOS`, with the signal rows in `SIGNALS` keyed to them.

Rows report the crawled like count, and the popular and ordered rows carry no interaction signal score:

- `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` for hot, popular and recent each report `likes` as the video's stored `videos.likes`: 3 for a video whose `interaction_signals` row holds 50 likes, and 11 for a video with no signal row. This holds with no error threshold and with one.
- `fetch_popular_videos` and `fetch_ordered_page` for hot, popular and recent return rows with no `interaction_signal_score` key, while each row still carries `video_id`, `likes` and `popularity`, with no error threshold and with one.

Those run on a temporary copy of two real videos, set to the values in `LIKES_VIDEOS`, the first with a signal row.

With `include_nsfw=False` the listing reads leave out every `nsfw = 1` video inside their SQL, so LIMIT and OFFSET count only the rows that are allowed:

- `fetch_random_rows`, `fetch_recent_videos`, `fetch_popular_videos` and `fetch_ordered_page` for hot, popular and recent, each with no error threshold and with a threshold of 3: the default call and `include_nsfw=True` return all nine videos (E dropped under the threshold), and `include_nsfw=False` returns exactly A, B, C, D and E (E dropped under the threshold), whose `nsfw` values are 0 and NULL and none 1.
- NSFW videos head Hot, Popular and Recent, and one more sits mid-order. With the filter on, `fetch_popular_videos` and `fetch_recent_videos` at LIMIT n return the first n allowed videos for every n up to the allowed count, and `fetch_random_rows` at LIMIT (allowed count) returns every allowed video on each of five draws. `fetch_ordered_page` pages of 1, 2 and 3 rows, fetched at increasing offsets to one past the end, concatenate with no repeat into the single filtered page, which is the allowed videos in order.

Those run on an in-memory database of nine videos in `NSFW_ORDER` with the `nsfw` values in `NSFW_FLAGS`.

With the filter on, the random-cache draw refills past NSFW rows instead of coming back short; with it off, it makes one draw:

- `fetch_random_rows_from_cache(include_nsfw=False)`, limit 4, over the cache X1 A X2 B C X3 D E with windows starting at 0, 2 and 4: three draws, and the page is A, B, C, D. The rows are in draw order, B and C are not repeated from the overlapping window, and E is cut at the limit.
- With one allowed row per window and a limit of `RANDOM_CACHE_NSFW_MAX_DRAWS` + 2, it makes exactly `RANDOM_CACHE_NSFW_MAX_DRAWS` draws, although the next window would add an unseen allowed row. The page is those draws' allowed rows.
- Over a 3-row cache (X1 A X2) at limit 5 it makes two draws of that same whole window and returns A.
- Over an all-NSFW 8-row cache it returns [] after three draws (windows 0, 4, then 0 again, which adds no unseen rowid). The same cache with the filter off returns X1..X4.
- `include_nsfw=True` and the default call each make one draw of A X1 A R and return A, X1, A. The duplicate is kept, NSFW is included, and the errored R leaves the page short without a redraw.

Those run on an in-memory Engine db and random cache, owned by a SimpleNamespace holding `random_cache_db`, `random_cache_lock`, `db` and `db_lock`. The window start is scripted through `data.random_cache.random`, and draws are counted by wrapping `fetch_random_rowids`.
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
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402

THRESHOLD = 3
DAY_MS = 86_400_000
PAST_MS = 1_700_000_000_000
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
# B's signal: 1000 would lift it past C in hot were the signal read, and 50 likes would lead popular; no order reads it, so B keeps its stored place.
SIGNAL_SCORE = 1000.0
SIGNAL_LIKES = 50
# Insertion order: E and A (same domain, E's id lower, equal on every key above video_id in all three orders) are stored first, and T2 after T, so a missing video_id or instance_domain tie-break leaves storage order, the wrong way round. C's id is below D's while C has the more views, so popular without its views key puts D first.
LABELS = ("E", "A", "B", "C", "D", "F", "T", "N")
# Derived by hand from VIDEOS, B's signal ignored. hot: A and E 30 (A's id higher), C 20, F 15, T2/T 12, D 10, B 1. popular: C 20 likes/900 views, D 20/500, T2/T 10, A and E 8/50, B 2, F 1. recent: A and E, F, T2/T, B, dropping C (NULL) and D (future).
EXPECTED = {
    "hot": ["A", "E", "C", "F", "T2", "T", "D", "B"],
    "popular": ["C", "D", "T2", "T", "A", "E", "B", "F"],
    "recent": ["A", "E", "F", "T2", "T", "B"],
}
# Read without raising, so a module lacking the table fails each test rather than the file's collection.
ORDERS = tuple(vars(random_videos).get("ORDERED_FEED_ORDER_BY", ("ORDERED_FEED_ORDER_BY missing",)))


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


def _labels(rows: list[dict], label_of: dict[tuple[str, str], str]) -> list[str]:
    return [label_of.get((row["video_id"], row["instance_domain"]), row["video_id"]) for row in rows]


def _served(order: str, threshold: int | None) -> list[str]:
    return [label for label in EXPECTED[order] if threshold is None or label != "E"]


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ORDERS)
def test_consecutive_pages_concatenate_into_the_order_s_total_sort(tmp_path, order, threshold):
    assert set(ORDERS) == set(EXPECTED), ORDERS  # the three orders, each carried below
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
    if order == "hot":
        # fetch_popular_videos' ranking shows in which rows its LIMIT keeps; N, unembedded, ranks last and takes no slot ahead of them.
        for limit in range(1, len(expected) + 1):
            kept = set(_labels(random_videos.fetch_popular_videos(conn, limit, error_threshold=threshold), label_of))
            assert kept == set(expected[:limit]), (limit, kept)  # hot is the order fetch_popular_videos ranks by


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ORDERS)
def test_a_page_holds_exactly_the_embedded_rows_under_the_threshold(tmp_path, order, threshold):
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
# hot: A 30; B, C, G 20 with B's 9 likes first, then C and G on 4 likes with C's 900 views first; D 10; E 5; F 1.
# popular: B 9, F 7, A 5, C and G on 4 with C's 900 views first, E 2, D 1.
SIGNAL_EXPECTED = {
    "hot": ["A", "B", "C", "G", "D", "E", "F"],
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


def test_hot_pages_and_the_popular_pool_rank_by_popularity_then_crawled_likes_then_views_whatever_the_signal(tmp_path):
    conn, label_of = _signal_db(tmp_path)
    for limit in (1, 2, 3):
        assert _paged(conn, "hot", limit, label_of) == SIGNAL_EXPECTED["hot"], limit
    for limit in range(1, len(SIGNAL_VIDEOS) + 1):
        kept = set(_labels(random_videos.fetch_popular_videos(conn, limit), label_of))
        assert kept == set(SIGNAL_EXPECTED["hot"][:limit]), (limit, kept)


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
    """Every read under test, by name and error threshold: the random fallback, the popular pool, and one page of each ordered feed."""
    reads = {}
    for threshold in THRESHOLDS:
        reads[("random", threshold)] = random_videos.fetch_random_rows(conn, 10, error_threshold=threshold)
        reads[("popular pool", threshold)] = random_videos.fetch_popular_videos(conn, 10, error_threshold=threshold)
        for order in ("hot", "popular", "recent"):
            reads[(order, threshold)] = random_videos.fetch_ordered_page(conn, order, 10, 0, error_threshold=threshold)
    return reads


def _by_label(rows: list[dict], label_of: dict[tuple[str, str], str]) -> dict[str, dict]:
    return {label_of[(row["video_id"], row["instance_domain"])]: row for row in rows}


def test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        likes = {label: row["likes"] for label, row in _by_label(rows, label_of).items()}
        assert likes == LIKES_VIDEOS, name


def test_popular_and_ordered_rows_carry_no_interaction_signal_score(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        if name[0] == "random":
            continue
        by_label = _by_label(rows, label_of)
        assert set(by_label) == set(LIKES_VIDEOS), name  # control: both videos came back, X with its signal row included
        for label, row in by_label.items():
            assert {"video_id", "likes", "popularity"} <= set(row), (name, label)  # control: the row is the full read, not an empty shell
            assert "interaction_signal_score" not in row, (name, label)


# The NSFW filter on the listing reads: one rank order for all of them, the video at rank r having popularity and likes 100 - 10r, views 1000 - 100r, and being r days old, so Hot, Popular and Recent all run in this sequence. NSFW rows lead it, sit in its middle and end it.
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
NSFW_EMBEDDINGS_TABLE = "CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))"
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
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", [label, NSFW_HOST])
    db.commit()
    yield db
    db.close()


# Each read at a limit past the nine videos, so it returns every row it may serve.
NSFW_READS = {
    "fetch_random_rows": lambda conn, threshold, **flag: random_videos.fetch_random_rows(conn, 100, error_threshold=threshold, **flag),
    "fetch_recent_videos": lambda conn, threshold, **flag: random_videos.fetch_recent_videos(conn, 100, error_threshold=threshold, **flag),
    "fetch_popular_videos": lambda conn, threshold, **flag: random_videos.fetch_popular_videos(conn, 100, error_threshold=threshold, **flag),
    "fetch_ordered_page:hot": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "hot", 100, 0, error_threshold=threshold, **flag),
    "fetch_ordered_page:popular": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "popular", 100, 0, error_threshold=threshold, **flag),
    "fetch_ordered_page:recent": lambda conn, threshold, **flag: random_videos.fetch_ordered_page(conn, "recent", 100, 0, error_threshold=threshold, **flag),
}
# Reads whose row order is their contract; the rest are compared in NSFW_ORDER's sequence, duplicates kept.
NSFW_ORDERED_READS = {"fetch_recent_videos", "fetch_ordered_page:hot", "fetch_ordered_page:popular", "fetch_ordered_page:recent"}


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
def test_limits_count_only_allowed_rows(nsfw_conn, threshold):
    allowed = NSFW_EXPECTED[(threshold, False)]
    assert _nsfw_labels(random_videos.fetch_popular_videos(nsfw_conn, 1, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads Hot
    assert _nsfw_labels(random_videos.fetch_recent_videos(nsfw_conn, 1, error_threshold=threshold)) == ["X1"]  # control: an NSFW video heads Recent
    for n in range(1, len(allowed) + 1):
        assert _nsfw_ranked(random_videos.fetch_popular_videos(nsfw_conn, n, error_threshold=threshold, include_nsfw=False)) == allowed[:n], n
        assert _nsfw_labels(random_videos.fetch_recent_videos(nsfw_conn, n, error_threshold=threshold, include_nsfw=False)) == allowed[:n], n
    # A LIMIT counting NSFW rows fills every allowed slot on one draw in 70 at best; five draws in a row make that chance negligible.
    for _ in range(5):
        assert _nsfw_ranked(random_videos.fetch_random_rows(nsfw_conn, len(allowed), error_threshold=threshold, include_nsfw=False)) == allowed


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ("hot", "popular", "recent"))
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


def _video_db(videos: list[tuple[str, str]]) -> tuple[sqlite3.Connection, dict[str, int]]:
    """An in-memory Engine db holding `videos` as (label, channel), embedded in that order, and each label's embedding rowid.

    A label starting X is flagged nsfw = 1 and one starting R sits at THRESHOLD errors; the rest alternate nsfw 0 and NULL.
    """
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for table in (NSFW_VIDEOS_TABLE, NSFW_EMBEDDINGS_TABLE, NSFW_CHANNELS_TABLE):
        db.execute(table)
    rowids: dict[str, int] = {}
    for index, (label, channel) in enumerate(videos):
        nsfw = 1 if label.startswith("X") else (0 if index % 2 else None)
        db.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (label, f"u-{label}", NSFW_HOST, channel, nsfw, THRESHOLD if label.startswith("R") else 0),
        )
        rowids[label] = db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (label, NSFW_HOST)).lastrowid
    db.commit()
    return db, rowids


def _cache_owner(monkeypatch: pytest.MonkeyPatch, cache: list[str], offsets: list[int]) -> tuple[SimpleNamespace, list[list[str]]]:
    """An owner serving a random cache whose positions hold `cache` in order, and the list each draw appends its window to, as labels.

    Draws start at `offsets` in turn; a draw past them fails the test.
    """
    db, rowids = _video_db([(label, f"ch-{label}") for label in dict.fromkeys(cache)])
    labels = {rowid: label for label, rowid in rowids.items()}
    cache_db = sqlite3.connect(":memory:")
    cache_db.row_factory = sqlite3.Row
    cache_db.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    cache_db.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(position, rowids[label]) for position, label in enumerate(cache, start=1)])
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
    real_fetch = random_cache.fetch_random_rowids

    def counting_fetch(cache_conn: sqlite3.Connection, limit: int) -> list[int]:
        window = real_fetch(cache_conn, limit)
        draws.append([labels[rowid] for rowid in window])
        return window

    monkeypatch.setattr(random_videos, "fetch_random_rowids", counting_fetch)
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
    assert draws == [cache[:4], cache[4:], cache[:4]]  # redrew while a draw added unseen rowids, stopped at the first that added none


@pytest.mark.parametrize("flag", [{"include_nsfw": True}, {}], ids=["include_nsfw", "default"])
def test_filter_off_makes_one_draw_and_returns_its_rows_duplicates_included(monkeypatch, flag):
    owner, draws = _cache_owner(monkeypatch, ["A", "X1", "A", "R", "B", "C", "D", "E"], [0, 4])
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, error_threshold=THRESHOLD, **flag)
    assert draws == [["A", "X1", "A", "R"]]  # one draw, although R's error count leaves the page short
    assert _nsfw_labels(rows) == ["A", "X1", "A"]  # that window's rows, the duplicate and the NSFW row kept
