import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
REPAIR_JOB = JOBS_DIR / "repair-video-channel-names.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]


def test_probe(tmp_path):
    db = tmp_path / "crawl.db"
    conn = sqlite3.connect(db)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)
    conn.commit()
    conn.close()
    bare = subprocess.run([sys.executable, str(REPAIR_JOB)], capture_output=True, text=True, cwd=tmp_path)
    print("BARE current", bare.returncode, repr(bare.stdout), repr(bare.stderr))
    withdb = subprocess.run([sys.executable, str(REPAIR_JOB), "--db", str(db)], capture_output=True, text=True, cwd=tmp_path)
    print("WITHDB current", withdb.returncode, repr(withdb.stdout), repr(withdb.stderr))
    ap = subprocess.run([sys.executable, "-c", "import argparse,logging; p=argparse.ArgumentParser(); p.add_argument('--db', required=True); p.parse_args()"], capture_output=True, text=True)
    print("ARGPARSE required", ap.returncode, repr(ap.stderr))
    lg = subprocess.run([sys.executable, "-c", "import logging; logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s'); logging.info('channel names repaired rows=%d', 3)"], capture_output=True, text=True)
    print("LOGGING", repr(lg.stdout), repr(lg.stderr))
    spec = importlib.util.spec_from_file_location("r", REPAIR_JOB)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    conn = sqlite3.connect(db)
    print("inproc first", m.repair_channel_names(conn), "second", m.repair_channel_names(conn))
    print("names", conn.execute("SELECT video_id, channel_name FROM videos ORDER BY video_id").fetchall())
    conn.close()
    assert False, "probe"
