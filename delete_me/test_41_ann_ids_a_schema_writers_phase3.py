"""`sync-whitelist.py` builds `video_embeddings` with `ann_id` and `ensure_schema_compatibility` refuses a six-column target; sync's reload, `merge-staging-db.py` and `inject_replace_embedding_for_test` write rows carrying the derived `ann_id`.

- On a target from `ensure_whitelist_schema` + `ensure_content_schema`, `video_embeddings` holds the six old columns followed by `ann_id`, and `ensure_schema_compatibility` passes. On a target whose `video_embeddings` is the six-column table, it raises RuntimeError naming `video_embeddings (missing columns: ann_id)` and `engine/server/db/jobs/migrate-whitelist.py`.
- `rebuild_content_tables` from a crawl source whose `video_embeddings` has no `ann_id` stores each row whole with the pinned blake2b id of its key, `v3`'s taken from the normalised host `b.example`, not the stored `B.Example.`. From a source carrying `ann_id`, it stores the source's value, including a sentinel that is not the derived id.
- `merge-staging-db.py`, run as a command over a prod holding v1 and a staging holding a replacement v1 plus v2 and v3, exits 0 and leaves prod with the staging rows, each carrying its pinned id; prod's v1, seeded under a sentinel that is not its derived id, ends under the pinned id, not the old one. Staging already holds the derived ids, which the merge carries across unchanged (AC3), so this does not show the merge deriving them.
- `inject_replace_embedding_for_test` returns True and leaves staging with prod's row under the pinned id of its key, not the sentinel prod stores for it, and with the embedding's first byte flipped, whether staging was empty or already held that key.

Every DB is a tmp file. The crawl source is `engine/crawler/schema.sql` plus a literal `video_embeddings`, attached as `source`.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
MERGE_JOB = JOBS_DIR / "merge-staging-db.py"

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
SOURCE_ANN_ID_EMBEDDINGS_SQL = """
CREATE TABLE video_embeddings (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_dim INTEGER NOT NULL,
  model_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  ann_id INTEGER NOT NULL,
  PRIMARY KEY (video_id, instance_domain)
);
"""
OLD_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
# int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big") & (2**63 - 1) for v1::a.example, v2::a.example, v3::b.example, run outside the helper; the raw `v3::B.Example.` would give 5421220993327846826.
V1_ID = 8241284212183890047
V2_ID = 8744784223012906678
V3_ID = 3553096638009034147
# Not v3's derived id: the reload must copy it from a source that carries it, and the inject must not copy it from prod.
V3_SENTINEL = 777
# Not v1's derived id: prod's v1 holds it before the merge, so a replace that keeps prod's old id is told apart from one that takes the staged V1_ID.
V1_SENTINEL = 555
HOSTS = {"a.example", "B.Example."}
CHANNELS = [("c1", "a.example"), ("c3", "B.Example.")]
VIDEOS = [("v1", "a.example", "c1"), ("v2", "a.example", "c1"), ("v3", "B.Example.", "c3")]
# (video_id, instance_domain, embedding, embedding_dim, model_name, created_at); v3's host is stored unnormalised.
EMBEDDINGS = [("v1", "a.example", b"\x01\x02", 2, "m", "t1"), ("v2", "a.example", b"\x03\x04", 2, "m", "t2"), ("v3", "B.Example.", b"\x05\x06", 2, "m", "t3")]
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
ROWS_SQL = f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_job():
    return _load_job("sync_whitelist_for_test_41_phase3", "sync-whitelist.py")


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_for_test_41_phase3", "updater-worker.py")


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")]


def _target(sync_job, path: Path, old: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if old:
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    return conn


def _source(path: Path, ann_ids: list[int] | None = None) -> Path:
    """A crawl DB holding CHANNELS, VIDEOS and EMBEDDINGS, its video_embeddings carrying `ann_ids` when given."""
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO channels (channel_id, instance_domain) VALUES (?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, last_checked_at) VALUES (?, ?, ?, 1)", VIDEOS)
    if ann_ids is None:
        conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
        conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", EMBEDDINGS)
    else:
        conn.executescript(SOURCE_ANN_ID_EMBEDDINGS_SQL)
        conn.executemany(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, ann_ids)])
    conn.commit()
    conn.close()
    return path


def _attach_source(conn: sqlite3.Connection, path: Path) -> None:
    conn.execute("ATTACH DATABASE ? AS source", (path.as_posix(),))


def _seed(conn: sqlite3.Connection, videos: list[tuple], embeddings: list[tuple]) -> None:
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", videos)
    conn.executemany(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", embeddings)
    conn.commit()


def test_new_target_carries_ann_id_and_passes_the_exact_check(sync_job, tmp_path):
    conn = _target(sync_job, tmp_path / "whitelist.db")
    try:
        _attach_source(conn, _source(tmp_path / "crawl.db"))
        # The previous six-column target also passed this check, so the shape is what makes the pass the new one.
        assert _column_names(conn) == OLD_COLUMNS + ["ann_id"]  # C1
        sync_job.ensure_schema_compatibility(conn)  # C1
    finally:
        conn.close()


def test_six_column_target_is_refused_naming_ann_id_and_the_migration(sync_job, tmp_path):
    conn = _target(sync_job, tmp_path / "whitelist.db", old=True)
    try:
        _attach_source(conn, _source(tmp_path / "crawl.db"))
        assert _column_names(conn) == OLD_COLUMNS, "control: ensure_content_schema left the six-column table in place"

        with pytest.raises(RuntimeError) as refused:
            sync_job.ensure_schema_compatibility(conn)  # C1

        assert "video_embeddings (missing columns: ann_id)" in str(refused.value)  # C1
        assert "engine/server/db/jobs/migrate-whitelist.py" in str(refused.value)  # C1
    finally:
        conn.close()


def test_reload_from_a_source_without_ann_id_stores_the_derived_id(sync_job, tmp_path):
    conn = _target(sync_job, tmp_path / "whitelist.db")
    try:
        _attach_source(conn, _source(tmp_path / "crawl.db"))
        sync_job.rebuild_content_tables(conn, HOSTS)
        conn.commit()

        assert conn.execute(ROWS_SQL).fetchall() == [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, [V1_ID, V2_ID, V3_ID])]  # C2
    finally:
        conn.close()


def test_reload_from_a_source_with_ann_id_stores_the_sources_value(sync_job, tmp_path):
    conn = _target(sync_job, tmp_path / "whitelist.db")
    try:
        source_ids = [V1_ID, V2_ID, V3_SENTINEL]
        _attach_source(conn, _source(tmp_path / "crawl.db", source_ids))
        sync_job.rebuild_content_tables(conn, HOSTS)
        conn.commit()

        assert conn.execute(ROWS_SQL).fetchall() == [row + (ann_id,) for row, ann_id in zip(EMBEDDINGS, source_ids)]  # C2
    finally:
        conn.close()


def test_merge_leaves_prod_rows_carrying_the_derived_id(sync_job, tmp_path):
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    replacement_v1 = ("v1", "a.example", b"\x11\x12", 2, "m2", "t9", V1_ID)
    staged = [replacement_v1, EMBEDDINGS[1] + (V2_ID,), EMBEDDINGS[2] + (V3_ID,)]
    prod = _target(sync_job, prod_db)
    _seed(prod, [("v1", "a.example")], [EMBEDDINGS[0] + (V1_SENTINEL,)])
    prod.close()
    staging = _target(sync_job, staging_db)
    _seed(staging, [row[:2] for row in VIDEOS], staged)
    staging.close()

    result = subprocess.run([sys.executable, str(MERGE_JOB), "--prod-db", str(prod_db), "--staging-db", str(staging_db)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr  # C2
    prod = sqlite3.connect(prod_db)
    try:
        assert prod.execute(ROWS_SQL).fetchall() == staged  # C2
    finally:
        prod.close()


@pytest.mark.parametrize("staging_holds_key", [False, True], ids=["empty-staging", "same-key-staging"])
def test_inject_writes_the_derived_id(sync_job, updater, tmp_path, staging_holds_key):
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    prod = _target(sync_job, prod_db)
    _seed(prod, [("v3", "B.Example.")], [EMBEDDINGS[2] + (V3_SENTINEL,)])
    prod.close()
    staging = _target(sync_job, staging_db)
    _seed(staging, [("v3", "B.Example.")], [EMBEDDINGS[2] + (V3_ID,)] if staging_holds_key else [])
    staging.close()

    assert updater.inject_replace_embedding_for_test(prod_db, staging_db) is True  # C2

    staging = sqlite3.connect(staging_db)
    try:
        # created_at is the inject's datetime('now'); b"\x05" ^ 0xFF is b"\xfa".
        rows = staging.execute("SELECT video_id, instance_domain, embedding, embedding_dim, model_name, ann_id FROM video_embeddings").fetchall()
        assert rows == [("v3", "B.Example.", b"\xfa\x06", 2, "m", V3_ID)]  # C2
    finally:
        staging.close()
