"""Probe: what PRAGMA table_info/index_list/index_info and the CHECK error report for the plan's settled analytics_events DDL."""
import sqlite3
from contextlib import closing

DDL = """
CREATE TABLE IF NOT EXISTS analytics_events (
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL CHECK (type IN ('outbound_click', 'page_view')),
  track_id TEXT,
  href TEXT,
  page_path TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  user_agent TEXT,
  referer TEXT
);
CREATE INDEX IF NOT EXISTS analytics_events_type_track_created_idx
  ON analytics_events (type, track_id, created_at);
"""


def test_probe(tmp_path):
    db = tmp_path / "users.db"
    with closing(sqlite3.connect(db)) as conn:
        conn.executescript(DDL)
        conn.executescript(DDL)
        print("TABLE_INFO", list(conn.execute("PRAGMA table_info(analytics_events)")))
        print("INDEX_LIST", list(conn.execute("PRAGMA index_list(analytics_events)")))
        for index in conn.execute("PRAGMA index_list(analytics_events)").fetchall():
            print("INDEX_INFO", index[1], list(conn.execute(f"PRAGMA index_info({index[1]})")))
        try:
            with conn:
                conn.execute("INSERT INTO analytics_events (type, page_path, created_at) VALUES ('click', '/about', 2)")
        except sqlite3.IntegrityError as exc:
            print("CHECK_ERR", repr(exc))
        try:
            with conn:
                conn.execute("INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)", ("page_view", None, None, "/rolled-back", 1, None, None))
                print("IN_TXN", conn.in_transaction)
                raise RuntimeError("abort")
        except RuntimeError:
            pass
        with closing(sqlite3.connect(db)) as reader:
            print("AFTER_ROLLBACK", reader.execute("SELECT * FROM analytics_events").fetchall())
        with conn:
            conn.execute("INSERT INTO analytics_events (type, track_id, href, page_path, created_at, user_agent, referer) VALUES (?, ?, ?, ?, ?, ?, ?)", ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about.html", 1767225600123, "Mozilla/5.0 analytics-test", "https://example.org/about"))
        with closing(sqlite3.connect(db)) as reader:
            print("AFTER_COMMIT", reader.execute("SELECT * FROM analytics_events").fetchall())
    assert False, "show output"
