from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

PRE = """
CREATE TABLE videos (
  video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, last_error TEXT, last_error_at INTEGER, error_count INTEGER NOT NULL DEFAULT 0, invalid_reason TEXT, invalid_at INTEGER, PRIMARY KEY (video_id, instance_domain)
);
"""


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe(tmp_path):
    sync = _load("probe_sync", "sync-whitelist.py")
    mig = _load("probe_mig", "whitelist_migrations.py")
    conn = sqlite3.connect(tmp_path / "w.db")
    conn.executescript(PRE)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    conn.executemany("INSERT INTO videos (video_id, instance_domain, title, tags_json, category, last_checked_at) VALUES (?, 'a.example', ?, ?, ?, 1)", [("v1", "Alpine walk", '["hike"]', "Travels"), ("v2", "Harbour night", None, None)])
    conn.commit()
    print("cols before", [r[1] for r in conn.execute("PRAGMA table_info(videos)")])
    print("triggers before", conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'videos_fts_%' ORDER BY name").fetchall())
    mig.migrate_whitelist_schema(conn, "instances")
    print("cols after current migrate", "language" in [r[1] for r in conn.execute("PRAGMA table_info(videos)")])
    conn.execute("ALTER TABLE videos ADD COLUMN language TEXT")
    print("after alter info", [tuple(r) for r in conn.execute("PRAGMA table_info(videos)")][-2:])
    print("triggers after alter", conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'videos_fts_%' ORDER BY name").fetchall())
    print("match", conn.execute("SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?", ('title : "Alpine"',)).fetchall())
    conn.execute("INSERT INTO videos (video_id, instance_domain, title, last_checked_at, language) VALUES ('v3', 'a.example', 'Lantern festival', 1, 'fr')")
    print("match v3", conn.execute("SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?", ('title : "Lantern"',)).fetchall())
    print("rows", conn.execute("SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id").fetchall())
    try:
        conn.execute("ALTER TABLE videos ADD COLUMN language TEXT")
    except sqlite3.OperationalError as exc:
        print("second alter", exc)
    conn.close()
    synthetic = "  preview_path TEXT,\n  language TEXT,\n  last_checked_at INTEGER NOT NULL,\n"
    print("subn", re.subn(r"^[ \t]*language\b[^\n]*\n", "", synthetic, flags=re.M))
    print("node", shutil.which("node"), "git", shutil.which("git"))
    node = shutil.which("node")
    if node:
        print(subprocess.run([node, "--version"], capture_output=True, text=True).stdout)
    print("dist files", sorted(p.name for p in (ROOT / "engine" / "crawler" / "dist").glob("*.js")))
    print("status", subprocess.run(["git", "status", "--porcelain", "--", "engine/crawler"], cwd=ROOT, capture_output=True, text=True).stdout)
    assert False
