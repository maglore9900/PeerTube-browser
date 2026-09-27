from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe(tmp_path):
    sync_whitelist = _load("probe_sync_whitelist_job", JOBS_DIR / "sync-whitelist.py")
    updater_worker = _load("probe_updater_worker_job", JOBS_DIR / "updater-worker.py")
    from data.moderation import normalize_host_token
    entries = ["", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos", "https://Tube.Example/", "tube.example"]
    print("NORMALISED", {entry: normalize_host_token(entry) for entry in entries})
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        sync_whitelist.ensure_whitelist_schema(conn)
        print("SYNC_ONE", sync_whitelist.sync_hosts(conn, {"tube.example"}))
        print("ROWS_ONE", conn.execute("SELECT host FROM instances").fetchall())
    finally:
        conn.close()
    conn = sqlite3.connect(tmp_path / "whitelist2.db")
    try:
        sync_whitelist.ensure_whitelist_schema(conn)
        print("SYNC_TWO", sync_whitelist.sync_hosts(conn, {"tube.example", "https://tube.example/"}))
        print("ROWS_TWO", conn.execute("SELECT host FROM instances").fetchall())
    finally:
        conn.close()
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps({"data": [{"host": entry} for entry in ["", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos"]]}), encoding="utf-8")
    print("JOIN_NOW", updater_worker.fetch_join_hosts(path.as_uri()))
    print("SYNC_NOW", sync_whitelist.fetch_hosts(path.as_uri()))
    print("PATH_HAS_SERVER", any(p.endswith("engine/server") for p in sys.path))
    assert False, "probe"
