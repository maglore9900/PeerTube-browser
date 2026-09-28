"""`migrate_whitelist_schema` (engine/server/db/jobs/whitelist_migrations.py) gives the whitelist `videos` table a nullable `language` column without disturbing its rows or its FTS index.

- On a whitelist.db whose `videos` table predates `language` (error columns present, FTS index and its three triggers in place, two rows seeded), `migrate_whitelist_schema(conn, "instances")` adds a nullable `language` column; the rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL, the three `videos_fts_*` triggers still exist, a title MATCH still finds the preserved row and a row inserted afterwards, and a second run leaves `table_info`, the rows and the triggers identical.

`sync-whitelist.py`'s schema helpers build the fixture DB only.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

# The whitelist videos table as `ensure_content_schema` created it before `language` existed: error columns present, `language` absent.
PRE_LANGUAGE_VIDEOS_SQL = """
CREATE TABLE videos (
  video_id TEXT NOT NULL,
  video_uuid TEXT,
  video_numeric_id INTEGER,
  instance_domain TEXT NOT NULL,
  channel_id TEXT,
  channel_name TEXT,
  channel_url TEXT,
  account_name TEXT,
  account_url TEXT,
  title TEXT,
  description TEXT,
  tags_json TEXT,
  category TEXT,
  published_at INTEGER,
  video_url TEXT,
  duration INTEGER,
  thumbnail_url TEXT,
  embed_path TEXT,
  views INTEGER,
  likes INTEGER,
  dislikes INTEGER,
  comments_count INTEGER,
  nsfw INTEGER,
  preview_path TEXT,
  popularity REAL NOT NULL DEFAULT 0,
  last_checked_at INTEGER NOT NULL,
  last_error TEXT,
  last_error_at INTEGER,
  error_count INTEGER NOT NULL DEFAULT 0,
  invalid_reason TEXT,
  invalid_at INTEGER,
  PRIMARY KEY (video_id, instance_domain)
);
"""
TRIGGERS_SQL = "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'videos_fts_%' ORDER BY name"
EXPECTED_TRIGGERS = [("videos_fts_ad",), ("videos_fts_ai",), ("videos_fts_au",)]
ROWS_SQL = "SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id"
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_info(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA table_info(videos)").fetchall()


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in _table_info(conn)]


def _matches(conn: sqlite3.Connection, word: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'title : "{word}"',))}


def test_migration_adds_language_column(tmp_path):
    sync_job = _load_job("sync_whitelist_for_test_whitelist_migrations", "sync-whitelist.py")
    migrations = _load_job("whitelist_migrations_for_test_whitelist_migrations", "whitelist_migrations.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        conn.executescript(PRE_LANGUAGE_VIDEOS_SQL)
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.executemany("INSERT INTO videos (video_id, instance_domain, title, tags_json, category, last_checked_at) VALUES (?, 'a.example', ?, ?, ?, 1)", [("v1", "Alpine walk", '["hike"]', "Travels"), ("v2", "Harbour night", None, None)])
        conn.commit()
        assert "language" not in _column_names(conn), "the pre-language videos table already has language"
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS, "the FTS triggers were not in place before the migration"

        migrations.migrate_whitelist_schema(conn, "instances")

        language = [row for row in _table_info(conn) if row[1] == "language"]
        assert len(language) == 1
        assert language[0][3] == 0, "language is NOT NULL"
        assert conn.execute(ROWS_SQL).fetchall() == [("v1", "Alpine walk", '["hike"]', "Travels", None), ("v2", "Harbour night", None, None, None)]
        # A rebuild of `videos` takes the triggers and the external-content index down with it.
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS
        assert _matches(conn, "Alpine") == {"v1"}
        conn.execute("INSERT INTO videos (video_id, instance_domain, title, last_checked_at, language) VALUES ('v3', 'a.example', 'Lantern festival', 1, 'fr')")
        assert _matches(conn, "Lantern") == {"v3"}, "the insert trigger no longer feeds videos_fts"
        conn.commit()

        info_after_first = _table_info(conn)
        rows_after_first = conn.execute(ROWS_SQL).fetchall()
        migrations.migrate_whitelist_schema(conn, "instances")
        assert _table_info(conn) == info_after_first
        assert conn.execute(ROWS_SQL).fetchall() == rows_after_first
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS
        assert _matches(conn, "Alpine") == {"v1"} and _matches(conn, "Lantern") == {"v3"}, "the second run left videos_fts unbuilt"
    finally:
        conn.close()
