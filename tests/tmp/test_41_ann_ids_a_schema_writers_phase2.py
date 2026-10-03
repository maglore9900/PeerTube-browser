"""`migrate_whitelist_schema` (engine/server/db/jobs/whitelist_migrations.py) rebuilds a six-column `video_embeddings` into the guarded ann_id shape, keeping every rowid, in one transaction a failed backfill rolls back whole.

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
OLD_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
# Non-contiguous rowids, so a copy that renumbers to 1, 2, 3 shows; v3's host is stored unnormalised.
SEED = [(2, "v1", "a.example", b"\x01\x02", 2, "m", "t1"), (5, "v2", "a.example", b"\x03\x04", 2, "m", "t2"), (9, "v3", "B.Example.", b"\x05\x06", 2, "m", "t3")]
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example, v2::a.example, v3::b.example, run outside the helper; the raw `v3::B.Example.` would give 5421220993327846826.
EXPECTED_ANN_IDS = [(2, 8241284212183890047), (5, 8744784223012906678), (9, 3553096638009034147)]
# A distinct (video_id, instance_domain) under the old primary key, but it normalises to v1::a.example, so the real backfill gives it rowid 2's ann_id.
COLLIDING_ROW = (12, "v1", "A.Example.", b"\x07\x08", 2, "m", "t4")
ROWS_SQL = "SELECT rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at FROM video_embeddings ORDER BY rowid"
# rootpage is kept because a re-run that rebuilds again copies identical rows and SQL; only the table's new pages show it.
MASTER_SQL = "SELECT type, name, tbl_name, rootpage, sql FROM sqlite_master ORDER BY type, name"
REBUILD_NAMES_SQL = "SELECT type, name, tbl_name FROM sqlite_master WHERE name IN ('video_embeddings_new', 'idx_video_embeddings_ann_id', 'video_embeddings_ann_id_collision') ORDER BY name"
EXPECTED_GUARDS = [("index", "idx_video_embeddings_ann_id", "video_embeddings"), ("trigger", "video_embeddings_ann_id_collision", "video_embeddings")]


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrations():
    return _load_job("whitelist_migrations_for_test_41_phase2", "whitelist_migrations.py")


def _table_info(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA table_info(video_embeddings)").fetchall()


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in _table_info(conn)]


def _content_db(path: Path) -> sqlite3.Connection:
    sync_job = _load_job("sync_whitelist_for_test_41_phase2", "sync-whitelist.py")
    conn = sqlite3.connect(path)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    return conn


@pytest.fixture
def old_db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A whitelist.db whose six-column video_embeddings holds SEED, its videos present."""
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    conn.close()
    conn = _content_db(tmp_path / "whitelist.db")
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", [(row[1], row[2]) for row in SEED])
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", SEED)
    conn.commit()
    assert _column_names(conn) == OLD_COLUMNS, "the fixture's video_embeddings is not the six-column table"
    assert conn.execute(ROWS_SQL).fetchall() == SEED, "the fixture did not keep the seeded rowids"
    yield conn
    conn.close()


def test_migration_backfills_derived_ann_ids_keeping_rowids_and_guards(old_db):
    migrations = _migrations()
    migrations.migrate_whitelist_schema(old_db, "instances")

    assert _column_names(old_db) == OLD_COLUMNS + ["ann_id"]  # C1
    assert [row[3] for row in _table_info(old_db) if row[1] == "ann_id"] == [1], "ann_id is nullable"  # C1
    assert old_db.execute(ROWS_SQL).fetchall() == SEED, "a row was renumbered, lost or altered by the rebuild"  # C1
    assert old_db.execute("SELECT rowid, ann_id FROM video_embeddings ORDER BY rowid").fetchall() == EXPECTED_ANN_IDS  # C1
    assert old_db.execute(REBUILD_NAMES_SQL).fetchall() == EXPECTED_GUARDS, "the guards are missing or video_embeddings_new was left behind"  # C1

    info_after_first = _table_info(old_db)
    rows_after_first = old_db.execute("SELECT rowid, * FROM video_embeddings ORDER BY rowid").fetchall()
    master_after_first = old_db.execute(MASTER_SQL).fetchall()
    migrations.migrate_whitelist_schema(old_db, "instances")
    assert _table_info(old_db) == info_after_first  # C1
    assert old_db.execute("SELECT rowid, * FROM video_embeddings ORDER BY rowid").fetchall() == rows_after_first  # C1
    assert old_db.execute(MASTER_SQL).fetchall() == master_after_first, "the second run rebuilt or re-created something"  # C1


def test_missing_video_embeddings_is_left_alone(tmp_path):
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
        assert _column_names(conn) == OLD_COLUMNS + ["ann_id"], "control: the same step rebuilds once the table exists, so the no-op above was the missing table's"
    finally:
        conn.close()


def test_failed_backfill_rolls_back_to_the_six_column_table(old_db):
    old_db.execute("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", COLLIDING_ROW[1:3])
    old_db.execute("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", COLLIDING_ROW)
    old_db.commit()
    seeded = SEED + [COLLIDING_ROW]
    assert old_db.execute(ROWS_SQL).fetchall() == seeded, "the fixture did not keep the colliding row"
    master_before = old_db.execute(MASTER_SQL).fetchall()
    migrations = _migrations()

    with pytest.raises(sqlite3.IntegrityError):
        migrations.migrate_whitelist_schema(old_db, "instances")  # C2

    assert old_db.in_transaction is False, "the failed rebuild left a transaction open"  # C2
    assert _column_names(old_db) == OLD_COLUMNS, "the failed rebuild left a changed video_embeddings"  # C2
    assert old_db.execute(ROWS_SQL).fetchall() == seeded, "the failed rebuild lost or altered rows"  # C2
    assert old_db.execute(REBUILD_NAMES_SQL).fetchall() == [], "the failed rebuild left video_embeddings_new or a guard"  # C2
    assert old_db.execute(MASTER_SQL).fetchall() == master_before  # C2

    old_db.execute("DELETE FROM video_embeddings WHERE rowid = ?", (COLLIDING_ROW[0],))
    old_db.commit()
    migrations.migrate_whitelist_schema(old_db, "instances")
    assert old_db.execute("SELECT rowid, ann_id FROM video_embeddings ORDER BY rowid").fetchall() == EXPECTED_ANN_IDS  # control: without the colliding row the same DB migrates, so the refusal was the collision's
