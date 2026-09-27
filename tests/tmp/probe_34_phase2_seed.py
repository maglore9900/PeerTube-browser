import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"

CHANNELS = [("7", "a.example", "Alphachan"), ("7", "b.example", "Betachan"), ("8", "a.example", ""), ("9", "a.example", None)]
VIDEOS = [("v1", "a.example", "7", "Betachan"), ("v2", "b.example", "7", "Alphachan"), ("v3", "b.example", "7", "Betachan"), ("v4", "a.example", "8", "Stalename"), ("v5", "a.example", "9", "Stalename"), ("v6", "a.example", "404", "Orphanname"), ("v7", "a.example", "7", None)]

GUARD = "c.display_name IS NOT NULL AND c.display_name <> '' AND c.display_name IS NOT videos.channel_name"
VARIANTS = {
    "draft": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", GUARD, True),
    "ne_not_isnot": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", "c.display_name IS NOT NULL AND c.display_name <> '' AND c.display_name != videos.channel_name", True),
    "no_empty_guard": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", "c.display_name IS NOT NULL AND c.display_name IS NOT videos.channel_name", True),
    "no_null_guard": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", "c.display_name <> '' AND c.display_name IS NOT videos.channel_name", True),
    "id_only_join": ("c.channel_id = videos.channel_id", GUARD, True),
    "no_commit": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", GUARD, False),
    "unguarded_all": ("c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain", "1", True),
}


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("shape", ["crawl", "whitelist"])
@pytest.mark.parametrize("variant", list(VARIANTS))
def test_probe(shape, variant, tmp_path):
    sync = _load("sync_probe", "sync-whitelist.py")
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    if shape == "crawl":
        conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    else:
        sync.ensure_content_schema(conn)
    conn.executemany("INSERT INTO channels (channel_id, instance_domain, display_name) VALUES (?, ?, ?)", CHANNELS)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, channel_name, title, description, last_checked_at) VALUES (?, ?, ?, ?, 'clip ' || ?1, 'plain text', 1)", VIDEOS)
    conn.commit()
    conn.close()
    conn = sqlite3.connect(db)
    print(shape, variant, "seeded", dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall()))
    print(shape, variant, "titles", conn.execute("SELECT video_id, title FROM videos").fetchall())
    before = conn.execute("SELECT * FROM channels ORDER BY channel_id, instance_domain").fetchall()
    print(shape, variant, "channels", before)
    join, guard, commit = VARIANTS[variant]
    sql = f"UPDATE videos SET channel_name = (SELECT c.display_name FROM channels c WHERE {join}) WHERE EXISTS (SELECT 1 FROM channels c WHERE {join} AND {guard})"
    rc = conn.execute(sql).rowcount
    if commit:
        conn.commit()
    conn.close()
    conn = sqlite3.connect(db)
    print(shape, variant, "rowcount", rc, "after", dict(conn.execute("SELECT video_id, channel_name FROM videos").fetchall()))
    rc2 = conn.execute(sql).rowcount
    conn.commit()
    print(shape, variant, "second", rc2, "fts", conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='videos_fts'").fetchone())
    conn.close()
    assert False, "probe"
