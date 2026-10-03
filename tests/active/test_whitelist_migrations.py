"""`migrate_whitelist_schema` (engine/server/db/jobs/whitelist_migrations.py) gives the whitelist `videos` table a nullable `language` column without disturbing its rows or its FTS index, and rebuilds a six-column `video_embeddings` into the guarded ann_id shape, keeping every rowid, in one transaction a failed backfill rolls back whole.

- On a whitelist.db whose `videos` table predates `language` (error columns present, FTS index and its three triggers in place, two rows seeded), `migrate_whitelist_schema(conn, "instances")` adds a nullable `language` column; the rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL, the three `videos_fts_*` triggers still exist, a title MATCH still finds the preserved row and a row inserted afterwards, and a second run leaves `table_info`, the rows and the triggers identical.
- On a whitelist.db whose `video_embeddings` predates `ann_id` and holds three rows at rowids 2, 5 and 9, `migrate_whitelist_schema(conn, "instances")` leaves the six old columns followed by a NOT NULL `ann_id`; every `(rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at)` row reads back exactly as seeded; each row's `ann_id` is the pinned blake2b id of its key, `v3`'s taken from the normalised host `b.example`, not the stored `B.Example.`; `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision` sit on `video_embeddings`; no `video_embeddings_new` is left; a second run leaves `table_info`, the rows and `sqlite_master` identical.
- On a DB without `video_embeddings`, `migrate_video_embeddings_schema` leaves `sqlite_master` as it was and no transaction open; once the six-column table exists, the same step rebuilds it.
- With a fourth row `(v1, A.Example.)` seeded, a distinct primary key whose real `compute_ann_id` equals `v1::a.example`'s, `migrate_whitelist_schema` raises IntegrityError and leaves the six-column table, its four rows as seeded, `sqlite_master` exactly as before (no `video_embeddings_new`, no index, no trigger) and no transaction open; that row deleted, a re-run on the same DB migrates it, so the refusal was the collision's.

`sync-whitelist.py`'s schema helpers build the fixture DB only.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

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


# video_embeddings as `ensure_content_schema` created it before `ann_id` existed.
OLD_VIDEO_EMBEDDINGS_SQL = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dim INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (video_id, instance_domain),
  FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
);
"""
OLD_EMBEDDING_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
# Non-contiguous rowids, so a copy that renumbers to 1, 2, 3 shows; v3's host is stored unnormalised.
EMBEDDING_SEED = [(2, "v1", "a.example", b"\x01\x02", 2, "m", "t1"), (5, "v2", "a.example", b"\x03\x04", 2, "m", "t2"), (9, "v3", "B.Example.", b"\x05\x06", 2, "m", "t3")]
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example, v2::a.example, v3::b.example, run outside the helper; the raw `v3::B.Example.` would give 5421220993327846826.
EXPECTED_ANN_IDS = [(2, 8241284212183890047), (5, 8744784223012906678), (9, 3553096638009034147)]
# A distinct (video_id, instance_domain) under the old primary key, but it normalises to v1::a.example, so the real backfill gives it rowid 2's ann_id.
COLLIDING_ROW = (12, "v1", "A.Example.", b"\x07\x08", 2, "m", "t4")
EMBEDDINGS_ROWS_SQL = "SELECT rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at FROM video_embeddings ORDER BY rowid"
# rootpage is kept because a re-run that rebuilds again copies identical rows and SQL; only the table's new pages show it.
MASTER_SQL = "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY type, name"
REBUILD_NAMES_SQL = "SELECT type, name, tbl_name FROM sqlite_master WHERE name IN ('video_embeddings_new', 'idx_video_embeddings_ann_id', 'video_embeddings_ann_id_collision') ORDER BY name"
EXPECTED_GUARDS = [("index", "idx_video_embeddings_ann_id", "video_embeddings"), ("trigger", "video_embeddings_ann_id_collision", "video_embeddings")]


def _migrations():
    return _load_job("whitelist_migrations_for_test_whitelist_migrations_ann_id", "whitelist_migrations.py")


def _embeddings_table_info(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA table_info(video_embeddings)").fetchall()


def _embeddings_columns(conn: sqlite3.Connection) -> list:
    return [row[1] for row in _embeddings_table_info(conn)]


def _content_db(path: Path) -> sqlite3.Connection:
    sync_job = _load_job("sync_whitelist_for_test_whitelist_migrations_ann_id", "sync-whitelist.py")
    conn = sqlite3.connect(path)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    return conn


@pytest.fixture
def old_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A whitelist.db whose six-column video_embeddings holds EMBEDDING_SEED, its videos present."""
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    conn.close()
    conn = _content_db(tmp_path / "whitelist.db")
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", [(row[1], row[2]) for row in EMBEDDING_SEED])
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", EMBEDDING_SEED)
    conn.commit()
    assert _embeddings_columns(conn) == OLD_EMBEDDING_COLUMNS, "the fixture's video_embeddings is not the six-column table"
    assert conn.execute(EMBEDDINGS_ROWS_SQL).fetchall() == EMBEDDING_SEED, "the fixture did not keep the seeded rowids"
    yield conn
    conn.close()


def test_migration_backfills_derived_ann_ids_keeping_rowids_and_guards(old_db):
    """A six-column `video_embeddings` is rebuilt with a NOT NULL `ann_id` derived from each normalised key, every rowid and row kept, the guards in place, and a second run changes nothing."""
    migrations = _migrations()
    migrations.migrate_whitelist_schema(old_db, "instances")

    assert _embeddings_columns(old_db) == OLD_EMBEDDING_COLUMNS + ["ann_id"]
    assert [row[3] for row in _embeddings_table_info(old_db) if row[1] == "ann_id"] == [1], "ann_id is nullable"
    assert old_db.execute(EMBEDDINGS_ROWS_SQL).fetchall() == EMBEDDING_SEED, "a row was renumbered, lost or altered by the rebuild"
    assert old_db.execute("SELECT rowid, ann_id FROM video_embeddings ORDER BY rowid").fetchall() == EXPECTED_ANN_IDS
    assert old_db.execute(REBUILD_NAMES_SQL).fetchall() == EXPECTED_GUARDS, "the guards are missing or video_embeddings_new was left behind"

    info_after_first = _embeddings_table_info(old_db)
    rows_after_first = old_db.execute("SELECT rowid, * FROM video_embeddings ORDER BY rowid").fetchall()
    master_after_first = old_db.execute(MASTER_SQL).fetchall()
    migrations.migrate_whitelist_schema(old_db, "instances")
    assert _embeddings_table_info(old_db) == info_after_first
    assert old_db.execute("SELECT rowid, * FROM video_embeddings ORDER BY rowid").fetchall() == rows_after_first
    assert old_db.execute(MASTER_SQL).fetchall() == master_after_first, "the second run rebuilt or re-created something"


def test_missing_video_embeddings_is_left_alone(tmp_path):
    """The ann_id step creates nothing and leaves no transaction open on a DB without `video_embeddings`."""
    conn = _content_db(tmp_path / "whitelist.db")
    try:
        conn.execute("DROP TABLE video_embeddings")
        conn.commit()
        master_before = conn.execute(MASTER_SQL).fetchall()
        migrations = _migrations()

        migrations.migrate_video_embeddings_schema(conn)

        assert conn.execute(MASTER_SQL).fetchall() == master_before, "the step created something on a DB without video_embeddings"
        assert conn.in_transaction is False, "the step left a transaction open"

        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
        migrations.migrate_video_embeddings_schema(conn)
        assert _embeddings_columns(conn) == OLD_EMBEDDING_COLUMNS + ["ann_id"], "control: the same step rebuilds once the table exists, so the no-op above was the missing table's"
    finally:
        conn.close()


def test_failed_backfill_rolls_back_to_the_six_column_table(old_db):
    """A backfill that collides raises and leaves the six-column table, its rows, `sqlite_master` and no open transaction exactly as before."""
    old_db.execute("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", COLLIDING_ROW[1:3])
    old_db.execute("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", COLLIDING_ROW)
    old_db.commit()
    seeded = EMBEDDING_SEED + [COLLIDING_ROW]
    assert old_db.execute(EMBEDDINGS_ROWS_SQL).fetchall() == seeded, "the fixture did not keep the colliding row"
    master_before = old_db.execute(MASTER_SQL).fetchall()
    migrations = _migrations()

    with pytest.raises(sqlite3.IntegrityError):
        migrations.migrate_whitelist_schema(old_db, "instances")

    assert old_db.in_transaction is False, "the failed rebuild left a transaction open"
    assert _embeddings_columns(old_db) == OLD_EMBEDDING_COLUMNS, "the failed rebuild left a changed video_embeddings"
    assert old_db.execute(EMBEDDINGS_ROWS_SQL).fetchall() == seeded, "the failed rebuild lost or altered rows"
    assert old_db.execute(REBUILD_NAMES_SQL).fetchall() == [], "the failed rebuild left video_embeddings_new or a guard"
    assert old_db.execute(MASTER_SQL).fetchall() == master_before

    old_db.execute("DELETE FROM video_embeddings WHERE rowid = ?", (COLLIDING_ROW[0],))
    old_db.commit()
    migrations.migrate_whitelist_schema(old_db, "instances")
    assert old_db.execute("SELECT rowid, ann_id FROM video_embeddings ORDER BY rowid").fetchall() == EXPECTED_ANN_IDS  # control: without the colliding row the same DB migrates, so the refusal was the collision's
