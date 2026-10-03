"""`build-video-embeddings.py`'s `init_schema`, the step its `main()` runs before the model loads, refuses a `video_embeddings` that predates `ann_id` and creates the guarded ann_id table on a fresh DB.

- On a six-column table (a staging DB reused with `--resume-staging`) it raises RuntimeError naming `main.video_embeddings`, `migrate-whitelist.py` and `--resume-staging`, and leaves the table, its row and `sqlite_master` untouched.
- On a fresh DB it creates the seven-column table with `idx_video_embeddings_ann_id` and `video_embeddings_ann_id_collision`.

Every DB is a tmp file. Only `init_schema` is called: the model stack is imported inside `main()`, so the row tuple `main()` writes is not proven here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
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
OLD_ROW = ("v1", "a.example", b"\x01", 1, "m", "t1")


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_job():
    return _load_job("build_video_embeddings_for_test_build_video_embeddings", "build-video-embeddings.py")


def _master(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT type, name FROM sqlite_master ORDER BY name").fetchall()


def _old_table_with_a_row(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_VIDEO_EMBEDDINGS_SQL)
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", OLD_ROW)
    conn.commit()
    return conn


def test_build_init_schema_refuses_a_resumed_six_column_staging_table_and_writes_nothing(build_job, tmp_path):
    """A resumed staging DB whose `video_embeddings` predates `ann_id` is refused with the migrate and recreate pointers before anything is written."""
    # build-video-embeddings opens the staging DB as its main connection, so a resumed six-column staging table is `main.video_embeddings` to it.
    conn = _old_table_with_a_row(tmp_path / "staging.db")
    try:
        master_before = _master(conn)

        with pytest.raises(RuntimeError) as refused:
            build_job.init_schema(conn)

        message = str(refused.value)
        assert "main.video_embeddings" in message
        assert "migrate-whitelist.py" in message
        assert "--resume-staging" in message
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS
        assert conn.execute("SELECT * FROM video_embeddings").fetchall() == [OLD_ROW]
        assert _master(conn) == master_before
    finally:
        conn.close()


def test_build_init_schema_creates_the_ann_id_table_on_a_fresh_db(build_job, tmp_path):
    """On a fresh DB `init_schema` creates the seven-column `video_embeddings` with both ann_id guards."""
    conn = sqlite3.connect(tmp_path / "staging.db")
    try:
        build_job.init_schema(conn)
        # control: the writer that refuses the six-column table above creates the guarded seven-column one, so the refusal is the old shape's.
        assert [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")] == OLD_COLUMNS + ["ann_id"]
        assert {("index", "idx_video_embeddings_ann_id"), ("trigger", "video_embeddings_ann_id_collision")} <= set(_master(conn))
    finally:
        conn.close()
