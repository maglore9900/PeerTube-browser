import importlib.util
import sqlite3
from pathlib import Path

JOBS = Path(__file__).resolve().parents[2] / "engine" / "server" / "db" / "jobs"


def test_probe(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_probe", JOBS / "sync-whitelist.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    conn = sqlite3.connect(tmp_path / "w.db")
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    triggers = lambda: sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'"))
    print("after ensure", triggers(), conn.in_transaction)
    conn.execute("INSERT INTO instances (host) VALUES ('x')")
    sync.drop_videos_fts_triggers(conn)
    print("dropped in txn", triggers(), conn.in_transaction)
    conn.rollback()
    print("after rollback", triggers(), [r[0] for r in conn.execute("SELECT host FROM instances")])
