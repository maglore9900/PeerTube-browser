from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _load_job(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _db(path, sync, seven, videos, rows):
    from data.ann_ids import create_ann_id_guards, create_video_embeddings_table
    conn = sqlite3.connect(path)
    if seven:
        create_video_embeddings_table(conn)
        create_ann_id_guards(conn)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, last_checked_at) VALUES (?, ?, 1)", videos)
    n = len(rows[0]) if rows else 0
    if rows:
        conn.executemany(f"INSERT INTO video_embeddings VALUES ({', '.join('?' * n)})", rows)
    conn.commit()
    conn.close()


@pytest.mark.parametrize("holds", [False, True])
def test_inject_six(tmp_path, holds):
    sync = _load_job("sync_probe_rows", "sync-whitelist.py")
    updater = _load_job("updater_probe_rows", "updater-worker.py")
    _db(tmp_path / "p.db", sync, False, [("v3", "B.Example.")], [("v3", "B.Example.", b"\x05\x06", 2, "m", "t3")])
    _db(tmp_path / "s.db", sync, False, [("v3", "B.Example.")], [("v3", "B.Example.", b"\x05\x06", 2, "m", "t3")] if holds else [])
    print("INJECT6", holds, updater.inject_replace_embedding_for_test(tmp_path / "p.db", tmp_path / "s.db"))
    print("ROWS6", holds, sqlite3.connect(tmp_path / "s.db").execute("SELECT * FROM video_embeddings").fetchall())


def test_inject_seven_same_key(tmp_path):
    sync = _load_job("sync_probe_rows2", "sync-whitelist.py")
    updater = _load_job("updater_probe_rows2", "updater-worker.py")
    _db(tmp_path / "p.db", sync, True, [("v3", "B.Example.")], [("v3", "B.Example.", b"\x05\x06", 2, "m", "t3", 777)])
    _db(tmp_path / "s.db", sync, True, [("v3", "B.Example.")], [("v3", "B.Example.", b"\x05\x06", 2, "m", "t3", 3553096638009034147)])
    try:
        print("INJECT7", updater.inject_replace_embedding_for_test(tmp_path / "p.db", tmp_path / "s.db"))
    except Exception as exc:
        print("INJECT7 ERR", type(exc).__name__, exc)


def test_merge_full_rows(tmp_path):
    sync = _load_job("sync_probe_rows3", "sync-whitelist.py")
    staged = [("v1", "a.example", b"\x11\x12", 2, "m2", "t9", 8241284212183890047), ("v2", "a.example", b"\x03\x04", 2, "m", "t2", 8744784223012906678), ("v3", "B.Example.", b"\x05\x06", 2, "m", "t3", 3553096638009034147)]
    _db(tmp_path / "p.db", sync, True, [("v1", "a.example")], [("v1", "a.example", b"\x01\x02", 2, "m", "t1", 8241284212183890047)])
    _db(tmp_path / "s.db", sync, True, [("v1", "a.example"), ("v2", "a.example"), ("v3", "B.Example.")], staged)
    proc = subprocess.run([sys.executable, str(JOBS_DIR / "merge-staging-db.py"), "--prod-db", str(tmp_path / "p.db"), "--staging-db", str(tmp_path / "s.db")], capture_output=True, text=True)
    print("MERGE RC", proc.returncode)
    rows = sqlite3.connect(tmp_path / "p.db").execute("SELECT video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id FROM video_embeddings ORDER BY video_id").fetchall()
    print("MERGE ROWS", rows)
    print("MERGE EQUAL STAGED", rows == staged)
