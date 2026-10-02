from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"


def _h(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big") & ((1 << 63) - 1)


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hashes():
    for key in ["v1::a.example", "v2::a.example", "v3::b.example", "v3::B.Example.", "v9::a.example"]:
        print("HASH", key, _h(key))


def _target(path, sync):
    conn = sqlite3.connect(path)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    return conn


def _source(path, with_ann):
    conn = sqlite3.connect(path)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    extra = ",\n ann_id INTEGER NOT NULL" if with_ann else ""
    conn.execute(f"CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL{extra}, PRIMARY KEY (video_id, instance_domain))")
    conn.executemany("INSERT INTO channels (channel_id, instance_domain) VALUES (?, ?)", [("c1", "a.example"), ("c3", "B.Example.")])
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, last_checked_at) VALUES (?, ?, ?, 1)", [("v1", "a.example", "c1"), ("v2", "a.example", "c1"), ("v3", "B.Example.", "c3")])
    rows = [("v1", "a.example", b"\x01", 1, "m", "t1"), ("v2", "a.example", b"\x02", 1, "m", "t2"), ("v3", "B.Example.", b"\x03", 1, "m", "t3")]
    if with_ann:
        conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?, ?)", [r + (100 + i,) for i, r in enumerate(rows)])
    else:
        conn.executemany("INSERT INTO video_embeddings VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_sync_current(tmp_path):
    sync = _load_job("sync_probe3", "sync-whitelist.py")
    conn = _target(tmp_path / "t.db", sync)
    print("TARGET COLUMNS", [r[1] for r in conn.execute("PRAGMA table_info(video_embeddings)")])
    print("MASTER", conn.execute("SELECT type, name FROM sqlite_master WHERE tbl_name = 'video_embeddings'").fetchall())
    _source(tmp_path / "s.db", False)
    conn.execute("ATTACH DATABASE ? AS source", (str(tmp_path / "s.db"),))
    try:
        sync.ensure_schema_compatibility(conn)
        print("COMPAT new target: passes")
    except Exception as exc:
        print("COMPAT new target:", type(exc).__name__, exc)
    try:
        print("REBUILD", sync.rebuild_content_tables(conn, {"a.example", "B.Example."}))
        conn.commit()
        print("ROWS", conn.execute("SELECT * FROM video_embeddings ORDER BY video_id").fetchall())
    except Exception as exc:
        print("REBUILD ERR", type(exc).__name__, exc)
    # format of the exact-check message
    conn2 = sqlite3.connect(tmp_path / "t2.db")
    conn2.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT)")
    sync.ensure_whitelist_schema(conn2)
    sync.ensure_content_schema(conn2)
    conn2.execute("ATTACH DATABASE ? AS source", (str(tmp_path / "s.db"),))
    try:
        sync.ensure_schema_compatibility(conn2)
        print("COMPAT short target: passes")
    except Exception as exc:
        print("COMPAT short target:", type(exc).__name__, repr(str(exc)))


def test_seven_column_target_today(tmp_path):
    sync = _load_job("sync_probe3b", "sync-whitelist.py")
    from data.ann_ids import create_ann_id_guards, create_video_embeddings_table
    conn = sqlite3.connect(tmp_path / "t.db")
    create_video_embeddings_table(conn)
    create_ann_id_guards(conn)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    _source(tmp_path / "s.db", True)
    conn.execute("ATTACH DATABASE ? AS source", (str(tmp_path / "s.db"),))
    try:
        sync.ensure_schema_compatibility(conn)
        print("COMPAT7: passes")
    except Exception as exc:
        print("COMPAT7:", type(exc).__name__, exc)
    try:
        print("REBUILD7", sync.rebuild_content_tables(conn, {"a.example", "B.Example."}))
    except Exception as exc:
        print("REBUILD7 ERR", type(exc).__name__, exc)


def _merge_db(path, sync, rows, videos):
    from data.ann_ids import create_ann_id_guards, create_video_embeddings_table
    conn = sqlite3.connect(path)
    create_video_embeddings_table(conn)
    create_ann_id_guards(conn)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", videos)
    conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, ?, 1, 'm', 't', ?)", rows)
    conn.commit()
    conn.close()


def test_merge_seven_columns(tmp_path):
    sync = _load_job("sync_probe3c", "sync-whitelist.py")
    _merge_db(tmp_path / "prod.db", sync, [("v1", "a.example", b"\x01", _h("v1::a.example"))], [("v1", "a.example")])
    _merge_db(tmp_path / "stage.db", sync, [("v1", "a.example", b"\x11", _h("v1::a.example")), ("v2", "a.example", b"\x02", _h("v2::a.example")), ("v3", "B.Example.", b"\x03", _h("v3::b.example"))], [("v1", "a.example"), ("v2", "a.example"), ("v3", "B.Example.")])
    proc = subprocess.run([sys.executable, str(JOBS_DIR / "merge-staging-db.py"), "--prod-db", str(tmp_path / "prod.db"), "--staging-db", str(tmp_path / "stage.db")], capture_output=True, text=True)
    print("MERGE RC", proc.returncode)
    print("MERGE STDERR", proc.stderr)
    conn = sqlite3.connect(tmp_path / "prod.db")
    print("PROD ROWS", conn.execute("SELECT video_id, instance_domain, embedding, ann_id FROM video_embeddings ORDER BY video_id").fetchall())


def test_inject(tmp_path):
    sync = _load_job("sync_probe3d", "sync-whitelist.py")
    updater = _load_job("updater_probe3", "updater-worker.py")
    _merge_db(tmp_path / "prod.db", sync, [("v3", "B.Example.", b"\x05\x06", _h("v3::b.example"))], [("v3", "B.Example.")])
    _merge_db(tmp_path / "stage.db", sync, [], [])
    try:
        print("INJECT", updater.inject_replace_embedding_for_test(tmp_path / "prod.db", tmp_path / "stage.db"))
    except Exception as exc:
        print("INJECT ERR", type(exc).__name__, exc)
    conn = sqlite3.connect(tmp_path / "stage.db")
    print("STAGE ROWS", conn.execute("SELECT * FROM video_embeddings").fetchall())
