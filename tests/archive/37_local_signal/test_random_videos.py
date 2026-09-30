"""Retired from `tests/active/test_random_videos.py` in build 37-hot-popular-drop-local-signal (plan 21), step 8.

Retired: `test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count`, `test_an_undone_like_keeps_the_popular_order_of_two_tied_videos`, `test_the_popular_order_caps_the_interaction_signal` and `test_consecutive_pages_concatenate_into_the_order_s_total_sort`. `test_a_page_holds_exactly_the_embedded_rows_under_the_threshold` stays active.

All four conflict with that build's confirmed requirements: Hot, the Recommendations popular pool and Popular no longer read `interaction_signals` (R1-R3), rows report crawled `videos.likes` only (R4), and `POPULAR_SIGNAL_CAP` and the `interaction_signal_score` row key are gone (R5).

- The two undone-like tests arm their controls on a Like adding 1 to a row's `likes` and on `interaction_signal_score` in popular rows.
- The cap test asserts the removed 25 cap.
- The paging test's hot and popular `EXPECTED` place B by its signal; its recent order, tie-breaks and threshold paging were still valid and are carried back at that build's harvest.

The original module docstring and code follow unchanged, less the test that stays active.
"""
"""A like that is undone is neutral in the Engine's random and popular reads.

- After a `Like` and its `UndoLike` are ingested for a video, `fetch_random_rows` reports that
  video's `likes` as its crawled `likes`, as it does before either event; a later `Like`
  still counts.
- `fetch_popular_videos` places the higher-viewed of two videos tied on popularity and crawled
  likes first, whichever of the two holds the views, and still after a `Like` of it, which the
  read saw land, has been undone.
- The popular order adds a video's interaction signal only up to a cap of 25: popularity 0 with a
  signal of 1000 ranks below popularity 30 and no signal, with and without an error threshold, and
  the row still reports the raw 1000; that video ranks above popularity 24.5 and below 25.5; a
  signal of 10, under the cap, counts in full, above popularity 5 and below 15.

The database is a temporary copy of two real videos out of `whitelist.db`, set to equal
popularity and crawled likes; events go through the real ingest, and the capped-signal test writes
the signal straight into `interaction_signals`.

The three global feed orders page through `fetch_ordered_page` as one total order over the rows each may serve:

- `ORDERED_FEED_ORDER_BY` holds exactly hot, popular and recent. For each, with no error threshold and with a threshold of 3, pages of 1, 2 and 3 rows fetched at increasing offsets, one page past the end included, concatenate with no `(video_id, instance_domain)` repeated into the hand-derived order: for hot, popularity plus the interaction signal capped at 25 descending; for popular, crawled plus signal likes descending, then views, then `video_id`; for recent, `published_at` descending. In every order two rows of one domain equal on every key above `video_id` come out higher `video_id` first, and two rows equal in all but `instance_domain` come out higher domain first.
- Hot is the order `fetch_popular_videos` ranks by, tie-break included: for every k, its LIMIT k keeps exactly hot's first k rows.
- A single page of every order holds exactly the embedded rows whose error count is under the threshold, when one is given: a video with no embedding and, under the threshold, a video with an error count equal to it are left out, while one at the threshold minus one stays; recent also leaves out a NULL and a future `published_at`.

Those run on a temporary copy of eight real videos out of `whitelist.db`, set to the values in `VIDEOS`, plus a copy of one of them under a higher `instance_domain`; the signal is written straight into `interaction_signals`.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"

from data import random_videos  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402
from data.random_videos import fetch_popular_videos, fetch_random_rows  # noqa: E402

CRAWLED_LIKES = 7
POPULARITY = 3.0
SIGNAL = 1000.0
# The requirement's cap: a signal counts for at most this much in the popular order.
CAP = 25.0
SUB_CAP_SIGNAL = 10.0


def _two_video_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict, dict]:
    """A database holding two real videos, the higher-viewed one returned first."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT 2"
    ).fetchall()
    assert len(picks) == 2
    where = " OR ".join(["(video_id = ? AND instance_domain = ?)"] * 2)
    args = [value for pick in picks for value in (pick["video_id"], pick["instance_domain"])]
    conn.execute(f"CREATE TABLE videos AS SELECT * FROM src.videos WHERE {where}", args)
    conn.execute(f"CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE {where}", args)
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    rows = conn.execute("SELECT rowid, video_id, video_uuid, instance_domain FROM videos ORDER BY rowid").fetchall()
    first, second = dict(rows[0]), dict(rows[1])
    _set_views(conn, (first, 1000), (second, 10))
    return conn, first, second


def _set_views(conn: sqlite3.Connection, *views: tuple[dict, int]) -> None:
    for video, count in views:
        conn.execute("UPDATE videos SET popularity = ?, likes = ?, views = ?, error_count = 0 WHERE rowid = ?",
                     (POPULARITY, CRAWLED_LIKES, count, video["rowid"]))
    conn.commit()


def _set_popularity(conn: sqlite3.Connection, *popularities: tuple[dict, float]) -> None:
    # error_count 0 keeps both rows under an error threshold of 1.
    for video, popularity in popularities:
        conn.execute("UPDATE videos SET popularity = ?, error_count = 0 WHERE rowid = ?", (popularity, video["rowid"]))
    conn.commit()


def _set_signal(conn: sqlite3.Connection, video: dict, signal: float) -> None:
    conn.execute("UPDATE interaction_signals SET signal_score = ? WHERE video_uuid = ? AND instance_domain = ?",
                 (signal, video["video_uuid"], video["instance_domain"]))
    conn.commit()


def _event(conn: sqlite3.Connection, video: dict, event_type: str, event_id: str) -> None:
    ingest_interaction_event(conn, {
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": "anonymous",
        "object": {"video_uuid": video["video_uuid"], "instance_domain": video["instance_domain"]},
        "published_at": 1_700_000_000_000,
        "source_instance": video["instance_domain"],
        "raw_payload": {},
    })
    conn.commit()


def _likes_by_video(conn: sqlite3.Connection) -> dict[str, int]:
    return {row["video_id"]: row["likes"] for row in fetch_random_rows(conn, 10)}


def _popular(conn: sqlite3.Connection) -> list[dict]:
    return fetch_popular_videos(conn, 10)


def _popular_order(conn: sqlite3.Connection) -> list[str]:
    return [row["video_id"] for row in _popular(conn)]


def test_an_undone_like_leaves_the_random_row_s_likes_at_the_crawled_count(tmp_path):
    conn, video, other = _two_video_db(tmp_path)
    assert _likes_by_video(conn)[video["video_id"]] == CRAWLED_LIKES  # control: no events yet

    _event(conn, video, "Like", "t-like-1")
    after_like = _likes_by_video(conn)
    assert after_like[video["video_id"]] == CRAWLED_LIKES + 1  # control: the Like counts
    assert after_like[other["video_id"]] == CRAWLED_LIKES  # and only for its own video
    _event(conn, video, "UndoLike", "t-undo-1")

    assert _likes_by_video(conn)[video["video_id"]] == CRAWLED_LIKES

    _event(conn, video, "Like", "t-like-2")
    assert _likes_by_video(conn)[video["video_id"]] == CRAWLED_LIKES + 1  # a later Like still counts


def test_an_undone_like_keeps_the_popular_order_of_two_tied_videos(tmp_path):
    conn, first, second = _two_video_db(tmp_path)
    tied = {row["video_id"]: (row["popularity"], row["likes"]) for row in _popular(conn)}
    assert set(tied.values()) == {(POPULARITY, CRAWLED_LIKES)}, tied  # the two are tied on both
    assert _popular_order(conn) == [first["video_id"], second["video_id"]]  # the higher-viewed first
    _set_views(conn, (first, 10), (second, 1000))
    assert _popular_order(conn) == [second["video_id"], first["video_id"]]  # views decide, not row order
    high, low = second, first

    _event(conn, high, "Like", "t-like-1")
    landed = {row["video_id"]: row["interaction_signal_score"] for row in _popular(conn)}
    assert landed == {high["video_id"]: 1.0, low["video_id"]: 0}, landed  # control: the read sees the Like
    _event(conn, high, "UndoLike", "t-undo-1")

    assert _popular_order(conn) == [high["video_id"], low["video_id"]]


def test_the_popular_order_caps_the_interaction_signal(tmp_path):
    conn, first, second = _two_video_db(tmp_path)
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, ?, 0)",
                 (first["video_uuid"], first["instance_domain"], SIGNAL))
    conn.commit()

    for threshold in (None, 1):
        _set_signal(conn, first, SIGNAL)
        _set_popularity(conn, (first, 0.0), (second, 30.0))
        rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
        assert [row["video_id"] for row in rows] == [second["video_id"], first["video_id"]], threshold
        scores = {row["video_id"]: row["interaction_signal_score"] for row in rows}
        assert scores == {first["video_id"]: SIGNAL, second["video_id"]: 0}, threshold  # control: the returned score stays raw

        # Half a point either side of the cap pins it at 25: a cap of 24 or less (a dropped signal, or the threshold 1 or the limit 10 bound in the cap's slot) fails the first case, a cap of 26 or more the second.
        # A signal under the cap counts in full: 10 beats popularity 5 but not 15, where a flat bonus of the cap for any signal would still win.
        for signal, popularity, leader, trailer in ((SIGNAL, CAP - 0.5, first, second), (SIGNAL, CAP + 0.5, second, first), (SUB_CAP_SIGNAL, 5.0, first, second), (SUB_CAP_SIGNAL, 15.0, second, first)):
            _set_signal(conn, first, signal)
            _set_popularity(conn, (first, 0.0), (second, popularity))
            rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
            assert [row["video_id"] for row in rows] == [leader["video_id"], trailer["video_id"]], (threshold, signal, popularity)


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
# B's signal: 1000 counts as the cap of 25 in hot (26, between A's 30 and C's 20; uncapped it would lead, dropped it would trail), and 50 likes lead popular.
SIGNAL_SCORE = 1000.0
SIGNAL_LIKES = 50
# Insertion order: E and A (same domain, E's id lower, equal on every key above video_id in all three orders) are stored first, and T2 after T, so a missing video_id or instance_domain tie-break leaves storage order, the wrong way round. C's id is below D's while C has the more views, so popular without its views key puts D first.
LABELS = ("E", "A", "B", "C", "D", "F", "T", "N")
# Derived by hand from VIDEOS. hot: A and E 30 (A's id higher), B 1+25, C 20, F 15, T2/T 12, D 10. popular: B 2+50, C 20 likes/900 views, D 20/500, T2/T 10, A and E 8/50, F 1. recent: A and E, F, T2/T, B, dropping C (NULL) and D (future).
EXPECTED = {
    "hot": ["A", "E", "B", "C", "F", "T2", "T", "D"],
    "popular": ["B", "C", "D", "T2", "T", "A", "E", "F"],
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

