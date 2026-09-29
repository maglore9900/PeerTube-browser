"""The three global feed orders page through `fetch_ordered_page` as one total order over the rows each may serve.

- `ORDERED_FEED_ORDER_BY` holds exactly hot, popular and recent. For each, with no error threshold and with a threshold of 3, pages of 1, 2 and 3 rows fetched at increasing offsets, one page past the end included, concatenate with no `(video_id, instance_domain)` repeated into the hand-derived order: for hot, popularity plus the interaction signal capped at 25 descending; for popular, crawled plus signal likes descending, then views, then `video_id`; for recent, `published_at` descending. In every order two rows of one domain equal on every key above `video_id` come out higher `video_id` first, and two rows equal in all but `instance_domain` come out higher domain first.
- Hot is the order `fetch_popular_videos` ranks by, tie-break included: for every k, its LIMIT k keeps exactly hot's first k rows.
- A single page of every order holds exactly the embedded rows whose error count is under the threshold, when one is given: a video with no embedding and, under the threshold, a video with an error count equal to it are left out, while one at the threshold minus one stays; recent also leaves out a NULL and a future `published_at`.
- `test_the_popular_order_caps_the_interaction_signal` from `tests/active/test_random_videos.py` still passes.

The database is a temporary copy of eight real videos out of `whitelist.db`, set to the values in `VIDEOS`, plus a copy of one of them under a higher `instance_domain`; the signal is written straight into `interaction_signals`.
"""
from __future__ import annotations

import importlib.util
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
CAP_TEST_FILE = ROOT / "tests" / "active" / "test_random_videos.py"

from data import random_videos  # noqa: E402
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
    assert set(ORDERS) == set(EXPECTED), ORDERS  # C1: the three orders, each carried below
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
        assert len(labels) == len(set(labels)), (limit, labels)  # C1: no row repeated
        assert labels == expected, (limit, labels)  # C1
        assert labels.index("T2") + 1 == labels.index("T"), labels  # C1: the tie comes out instance_domain DESC
    if order == "hot":
        # fetch_popular_videos returns its rows unordered, so its ranking shows only in which rows its LIMIT keeps; N, unembedded, ranks last and takes no slot ahead of them.
        for limit in range(1, len(expected) + 1):
            kept = set(_labels(random_videos.fetch_popular_videos(conn, limit, error_threshold=threshold), label_of))
            assert kept == set(expected[:limit]), (limit, kept)  # C1: hot is the order fetch_popular_videos ranks by


@pytest.mark.parametrize("threshold", (None, THRESHOLD))
@pytest.mark.parametrize("order", ORDERS)
def test_a_page_holds_exactly_the_embedded_rows_under_the_threshold(tmp_path, order, threshold):
    conn, label_of = _feed_db(tmp_path)
    served = set(_labels(random_videos.fetch_ordered_page(conn, order, 100, 0, error_threshold=threshold), label_of))
    left_out = {"N"} | ({"E"} if threshold is not None else set()) | ({"C", "D"} if order == "recent" else set())
    assert served == set(VIDEOS) - left_out | {"T2"}, served  # C2
    assert not served & left_out, served  # C2: no unembedded, at-threshold, NULL or future row


def test_the_popular_order_still_caps_the_interaction_signal(tmp_path):
    spec = importlib.util.spec_from_file_location("active_test_random_videos", CAP_TEST_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.test_the_popular_order_caps_the_interaction_signal(tmp_path)
