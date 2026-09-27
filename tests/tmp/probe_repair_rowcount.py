import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS = ROOT / "engine" / "server" / "db" / "jobs"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, JOBS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe(tmp_path):
    sync = _load("probe_sync", "sync-whitelist.py")
    repair = _load("probe_repair", "repair-video-channel-names.py")
    for shape in ("crawl", "whitelist"):
        db = tmp_path / f"{shape}.db"
        conn = sqlite3.connect(db)
        if shape == "crawl":
            conn.executescript((ROOT / "engine" / "crawler" / "schema.sql").read_text())
        else:
            sync.ensure_content_schema(conn)
        conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", [("7", "a", "A"), ("7", "b", "B"), ("8", "a", ""), ("9", "a", None)])
        conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, last_checked_at) VALUES (?, ?, ?, ?, 't', 1)", [("v1", "a", "7", "B"), ("v2", "b", "7", "A"), ("v3", "b", "7", "B"), ("v4", "a", "8", "x"), ("v5", "a", "9", "x"), ("v6", "a", "404", "o"), ("v7", "a", "7", None)])
        conn.commit()
        print(shape, "first", repair.repair_channel_names(conn), "fts", repair.has_videos_fts(conn))
        conn.close()
        conn = sqlite3.connect(db)
        print(shape, "names", conn.execute("SELECT video_id, channel_name FROM videos ORDER BY 1").fetchall())
        print(shape, "second", repair.repair_channel_names(conn))
        if shape == "whitelist":
            print("fts match A", conn.execute("SELECT rowid FROM videos_fts WHERE videos_fts MATCH 'channel_name:A'").fetchall())
            print("integrity", conn.execute("INSERT INTO videos_fts (videos_fts, rank) VALUES ('integrity-check', 1)").rowcount)
        conn.close()
    assert False, "probe"
