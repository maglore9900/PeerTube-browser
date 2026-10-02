import importlib.util
import sqlite3
from pathlib import Path

JOBS_DIR = Path(__file__).resolve().parents[2] / "engine" / "server" / "db" / "jobs"
OLD = """
CREATE TABLE videos (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain));
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


def _mod():
    spec = importlib.util.spec_from_file_location("wm_probe", JOBS_DIR / "whitelist_migrations.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _db(tmp_path, rows):
    conn = sqlite3.connect(tmp_path / "w.db")
    conn.executescript(OLD)
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, x'01', 1, 'm', 't')", rows)
    conn.commit()
    return conn


def test_probe(tmp_path):
    m = _mod()
    print("sqlite", sqlite3.sqlite_version)
    conn = _db(tmp_path, [(2, "v1", "a.example"), (9, "v3", "B.Example.")])
    print("before", conn.execute("SELECT type, name, tbl_name FROM sqlite_master ORDER BY name").fetchall())
    m.migrate_video_embeddings_schema(conn)
    print("after", conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name").fetchall())
    print("rows", conn.execute("SELECT rowid, video_id, instance_domain, ann_id FROM video_embeddings").fetchall())
    print("in_tx", conn.in_transaction)
    conn.close()

    (tmp_path / "w.db").unlink()
    conn = _db(tmp_path, [(2, "v1", "a.example"), (12, "v1", "A.Example.")])
    before = conn.execute("SELECT * FROM sqlite_master").fetchall()
    try:
        m.migrate_video_embeddings_schema(conn)
        print("collision: no raise")
    except Exception as exc:
        print("collision raised", type(exc).__name__, exc)
    print("in_tx", conn.in_transaction, "master same", conn.execute("SELECT * FROM sqlite_master").fetchall() == before)
    conn.close()
