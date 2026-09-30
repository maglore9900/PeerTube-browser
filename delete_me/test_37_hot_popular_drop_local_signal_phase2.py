"""Rows from the random, popular and ordered reads report the crawled like count, and the popular and ordered rows carry no interaction signal score.

- `fetch_random_rows`, `fetch_popular_videos` and `fetch_ordered_page` for hot, popular and recent each report `likes` as the video's stored `videos.likes`: 3 for a video whose `interaction_signals` row holds 50 likes, and 11 for a video with no signal row. This holds with no error threshold and with one.
- `fetch_popular_videos` and `fetch_ordered_page` for hot, popular and recent return rows with no `interaction_signal_score` key, while each row still carries `video_id`, `likes` and `popularity`, with no error threshold and with one.

The database is a temporary copy of two real videos out of `whitelist.db`, set to the values in `VIDEOS`; the signal row is written straight into `interaction_signals`, keyed to the copied video.
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

PUBLISHED_MS = 1_700_000_000_000
# crawled likes per label. X carries a signal of 50 likes (and a score of 50), so a row adding it reads 53.
VIDEOS = {"X": 3, "Y": 11}
SIGNAL_LIKES = 50
SIGNAL_SCORE = 50.0
ORDERS = ("hot", "popular", "recent")
# Both videos are stored with error_count 0, so a threshold keeps them while every read takes its filtered WHERE and parameter list.
THRESHOLDS = (None, 3)


def _two_video_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict[tuple[str, str], str]]:
    """A database holding X and Y and X's signal row, returned with the label of each (video_id, instance_domain)."""
    conn = sqlite3.connect(tmp_path / "engine.db")
    conn.row_factory = sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{WHITELIST_DB}?mode=ro' AS src")
    picks = conn.execute(
        "SELECT v.video_id, v.instance_domain FROM src.videos v JOIN src.video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.video_uuid IS NOT NULL ORDER BY v.rowid LIMIT ?", (len(VIDEOS),)
    ).fetchall()
    keys = dict(zip(VIDEOS, ((pick["video_id"], pick["instance_domain"]) for pick in picks)))
    assert len(set(keys.values())) == len(VIDEOS)  # control: two distinct videos
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
    # A past published_at keeps both in recent, which leaves out undated and future rows.
    for label, likes in VIDEOS.items():
        conn.execute("UPDATE videos SET likes = ?, published_at = ?, error_count = 0 WHERE video_id = ? AND instance_domain = ?",
                     (likes, PUBLISHED_MS, *keys[label]))
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) "
                 "SELECT video_uuid, instance_domain, ?, ?, 0 FROM videos WHERE video_id = ? AND instance_domain = ?",
                 (SIGNAL_LIKES, SIGNAL_SCORE, *keys["X"]))
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
        for order in ORDERS:
            reads[(order, threshold)] = random_videos.fetch_ordered_page(conn, order, 10, 0, error_threshold=threshold)
    return reads


def _by_label(rows: list[dict], label_of: dict[tuple[str, str], str]) -> dict[str, dict]:
    return {label_of[(row["video_id"], row["instance_domain"])]: row for row in rows}


def test_every_read_reports_each_video_s_crawled_likes_whatever_its_signal_likes(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        likes = {label: row["likes"] for label, row in _by_label(rows, label_of).items()}
        assert likes == VIDEOS, name  # C1


def test_popular_and_ordered_rows_carry_no_interaction_signal_score(tmp_path):
    conn, label_of = _two_video_db(tmp_path)
    for name, rows in _reads(conn).items():
        if name[0] == "random":
            continue
        by_label = _by_label(rows, label_of)
        assert set(by_label) == set(VIDEOS), name  # control: both videos came back, X with its signal row included
        for label, row in by_label.items():
            assert {"video_id", "likes", "popularity"} <= set(row), (name, label)  # control: the row is the full read, not an empty shell
            assert "interaction_signal_score" not in row, (name, label)  # C2
