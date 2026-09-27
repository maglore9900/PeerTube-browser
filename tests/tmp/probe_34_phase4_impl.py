import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPAIR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "repair-video-channel-names.py"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]


def test_probe(tmp_path):
    spec = importlib.util.spec_from_file_location("r", REPAIR_JOB)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    print("inproc load ok", m.repair_channel_names)
    db = tmp_path / "crawl.db"
    conn = sqlite3.connect(db)
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)
    conn.commit()
    conn.close()
    for args in ([], ["--db", str(tmp_path / "missing.db")], ["--db", str(db)], ["--db", str(db)]):
        p = subprocess.run([sys.executable, str(REPAIR_JOB), *args], capture_output=True, text=True, cwd=tmp_path)
        print(args, p.returncode, repr(p.stdout), repr(p.stderr))
    print("missing created?", (tmp_path / "missing.db").exists())
    assert False, "probe"
