"""The Engine's popular order adds a video's interaction signal only up to a cap of 25.

- `fetch_popular_videos` ranks a video with popularity 0 and a signal of 1000 below a video with popularity 30 and no signal, with and without an error threshold; the row still reports the raw signal of 1000.
- The same video ranks above popularity 24.5 and below popularity 25.5, which pins the cap at 25 to within half a point.
- A signal of 10, under the cap, counts in full: it ranks above popularity 5 and below popularity 15.

The module is named for its build, plan 13 (deterministic event ids), whose second change is this cap; nothing here asserts anything about event ids.

The database is a temporary copy of two real videos out of `whitelist.db`; the signal is written straight into `interaction_signals`.
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

from data.interaction_events import ensure_interaction_event_schema  # noqa: E402
from data.random_videos import fetch_popular_videos  # noqa: E402

SIGNAL = 1000.0
# The requirement's cap: a signal counts for at most this much in the popular order.
CAP = 25.0
SUB_CAP_SIGNAL = 10.0


def _two_video_db(tmp_path: Path) -> tuple[sqlite3.Connection, dict, dict]:
    """A database holding two real videos, in rowid order."""
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
    return conn, dict(rows[0]), dict(rows[1])


def _set_popularity(conn: sqlite3.Connection, *popularities: tuple[dict, float]) -> None:
    # error_count 0 keeps both rows under an error threshold of 1.
    for video, popularity in popularities:
        conn.execute("UPDATE videos SET popularity = ?, error_count = 0 WHERE rowid = ?", (popularity, video["rowid"]))
    conn.commit()


def _set_signal(conn: sqlite3.Connection, video: dict, signal: float) -> None:
    conn.execute("UPDATE interaction_signals SET signal_score = ? WHERE video_uuid = ? AND instance_domain = ?", (signal, video["video_uuid"], video["instance_domain"]))
    conn.commit()


def test_the_popular_order_caps_the_interaction_signal(tmp_path):
    conn, first, second = _two_video_db(tmp_path)
    conn.execute("INSERT INTO interaction_signals (video_uuid, instance_domain, likes_count, signal_score, updated_at) VALUES (?, ?, 0, ?, 0)",
                 (first["video_uuid"], first["instance_domain"], SIGNAL))
    conn.commit()

    for threshold in (None, 1):
        _set_signal(conn, first, SIGNAL)
        _set_popularity(conn, (first, 0.0), (second, 30.0))
        rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
        assert [row["video_id"] for row in rows] == [second["video_id"], first["video_id"]], threshold  # C1
        scores = {row["video_id"]: row["interaction_signal_score"] for row in rows}
        assert scores == {first["video_id"]: SIGNAL, second["video_id"]: 0}, threshold  # control: the returned score stays raw

        # Half a point either side of the cap pins it at 25: a cap of 24 or less (a dropped signal, or the threshold 1 or the limit 10 bound in the cap's slot) fails the first case, a cap of 26 or more the second.
        # A signal under the cap counts in full: 10 beats popularity 5 but not 15, where a flat bonus of the cap for any signal would still win.
        for signal, popularity, leader, trailer in ((SIGNAL, CAP - 0.5, first, second), (SIGNAL, CAP + 0.5, second, first), (SUB_CAP_SIGNAL, 5.0, first, second), (SUB_CAP_SIGNAL, 15.0, second, first)):
            _set_signal(conn, first, signal)
            _set_popularity(conn, (first, 0.0), (second, popularity))
            rows = fetch_popular_videos(conn, 10, error_threshold=threshold)
            assert [row["video_id"] for row in rows] == [leader["video_id"], trailer["video_id"]], (threshold, signal, popularity)  # D1a, D1b
