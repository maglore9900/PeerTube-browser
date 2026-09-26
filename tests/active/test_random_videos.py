"""A like that is undone is neutral in the Engine's random and popular reads.

- After a `Like` and its `UndoLike` are ingested for a video, `fetch_random_rows` reports that
  video's `likes` as its crawled `likes`, as it does before either event; a later `Like`
  still counts.
- `fetch_popular_videos` places the higher-viewed of two videos tied on popularity and crawled
  likes first, whichever of the two holds the views, and still after a `Like` of it, which the
  read saw land, has been undone.

The database is a temporary copy of two real videos out of `whitelist.db`, set to equal
popularity and crawled likes; events go through the real ingest.
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

from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402
from data.random_videos import fetch_popular_videos, fetch_random_rows  # noqa: E402

CRAWLED_LIKES = 7
POPULARITY = 3.0


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
