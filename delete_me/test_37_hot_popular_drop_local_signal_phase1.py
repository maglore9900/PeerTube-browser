"""Hot, the Recommendations popular pool and Popular rank on stored counts, whatever `interaction_signals` holds.

- Hot pages and `fetch_popular_videos` rank by `popularity`, then crawled `likes`, then views: a video with a `signal_score` of 1000 stays at its popularity's place, among lower and among equal popularities, and a video whose `likes_count` would outscore a popularity rival's crawled likes stays behind it.
- Popular pages rank by crawled `likes`, then views: a video with a `likes_count` of 100 stays at its crawled likes' place.

The database is a temporary copy of seven real videos out of `whitelist.db`, set to the values in `VIDEOS`; the signal rows are written straight into `interaction_signals`, keyed to the copied videos.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"

from data import random_videos  # noqa: E402
from data.interaction_events import ensure_interaction_event_schema  # noqa: E402

# popularity, crawled likes, views. Labels are assigned to the picked videos in video_id order, so C's id is below G's and B's below C's.
VIDEOS = {
    "A": (30.0, 5, 100),
    "B": (20.0, 9, 100),
    "C": (20.0, 4, 900),
    "D": (10.0, 1, 50),
    "E": (5.0, 2, 10),
    "F": (1.0, 7, 300),
    "G": (20.0, 4, 100),
}
PUBLISHED_MS = 1_700_000_000_000
# signal_score, likes_count. D's 1000 counts as 25 under a capped signal (35, ahead of A); G's 1000, inside the popularity-20 group, would lead that group were the signal a tie-break below popularity; C's 10 likes put it ahead of B on likes (14 against 9); E's 100 likes lead Popular.
SIGNALS = {
    "D": (1000.0, 0),
    "G": (1000.0, 0),
    "C": (0.0, 10),
    "E": (0.0, 100),
}
# Derived by hand from VIDEOS alone.
# hot: A 30; B, C, G 20 with B's 9 likes first, then C and G on 4 likes with C's 900 views first; D 10; E 5; F 1.
# popular: B 9, F 7, A 5, C and G on 4 with C's 900 views first, E 2, D 1.
EXPECTED = {
    "hot": ["A", "B", "C", "G", "D", "E", "F"],
    "popular": ["B", "F", "A", "C", "G", "E", "D"],
}


def _signal_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[tuple[str, str], str]]:
    """A database holding the labelled videos and their signal rows, returned with the label of each (video_id, instance_domain)."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT ?", (len(VIDEOS),)
    ).fetchall()
    picks = sorted((pick["video_id"], pick["instance_domain"]) for pick in picks)
    assert len({video_id for video_id, _ in picks}) == len(VIDEOS)  # control: distinct ids, so the id order is strict
    keys = dict(zip(sorted(VIDEOS), picks))
    conn.execute("CREATE TABLE videos AS SELECT * FROM src.videos WHERE 0")
    conn.execute("CREATE TABLE video_embeddings AS SELECT * FROM src.video_embeddings WHERE 0")
    for label in VIDEOS:
        conn.execute("INSERT INTO videos SELECT * FROM src.videos WHERE video_id = ? AND instance_domain = ?", keys[label])
        conn.execute("INSERT INTO video_embeddings SELECT * FROM src.video_embeddings WHERE video_id = ? AND instance_domain = ?", keys[label])
    conn.execute("CREATE TABLE channels AS SELECT DISTINCT c.* FROM src.channels c JOIN videos v "
                 "ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain")
    conn.commit()
    conn.execute("DETACH DATABASE src")
    ensure_interaction_event_schema(conn)
    # One published_at for all, so where views should decide, a missing views key falls through to video_id rather than to a date.
    for label, (popularity, likes, views) in VIDEOS.items():
        conn.execute("UPDATE videos SET popularity = ?, likes = ?, views = ?, published_at = ?, error_count = 0 WHERE video_id = ? AND instance_domain = ?",
                     (popularity, likes, views, PUBLISHED_MS, *keys[label]))
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


def _labels(rows: list[dict], label_of: dict[tuple[str, str], str]) -> list[str]:
    return [label_of.get((row["video_id"], row["instance_domain"]), row["video_id"]) for row in rows]


def _paged(conn: sqlite3.Connection, order: str, limit: int, label_of: dict[tuple[str, str], str]) -> list[str]:
    rows = []
    # One offset past the last row, so a page beyond the end must come back empty.
    for offset in range(0, len(VIDEOS) + limit, limit):
        page = random_videos.fetch_ordered_page(conn, order, limit, offset)
        assert len(page) <= limit, (order, limit, offset)
        rows += page
    return _labels(rows, label_of)


def test_hot_pages_and_the_popular_pool_rank_by_popularity_then_crawled_likes_then_views_whatever_the_signal(tmp_path):
    conn, label_of = _signal_db(tmp_path)
    for limit in (1, 2, 3):
        assert _paged(conn, "hot", limit, label_of) == EXPECTED["hot"], limit  # C1
    for limit in range(1, len(VIDEOS) + 1):
        kept = set(_labels(random_videos.fetch_popular_videos(conn, limit), label_of))
        assert kept == set(EXPECTED["hot"][:limit]), (limit, kept)  # C1


def test_popular_pages_rank_by_crawled_likes_then_views_whatever_the_signal_likes(tmp_path):
    conn, label_of = _signal_db(tmp_path)
    for limit in (1, 2, 3):
        assert _paged(conn, "popular", limit, label_of) == EXPECTED["popular"], limit  # C2
