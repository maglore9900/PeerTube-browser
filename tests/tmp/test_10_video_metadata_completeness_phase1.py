"""The whitelist and crawl.db `videos` tables gain a nullable `language` column, and a crawl fills crawl.db's with the PeerTube language code.

- On a whitelist.db whose `videos` table predates `language` (error columns present, FTS index and its three triggers in place, two rows seeded), `migrate_whitelist_schema(conn, "instances")` adds a nullable `language` column; the rows' `(video_id, title, tags_json, category)` read back unchanged with `language` NULL, the three `videos_fts_*` triggers still exist, a title MATCH still finds the preserved row and a row inserted afterwards, and a second run leaves `table_info`, the rows and the triggers identical.
- The built `dist/videos-worker.js`, no older than its source, run under node against local PeerTube stand-ins, stores `language.id` per video: "en" for a video carrying it, NULL for `{"id": null}`, NULL for a video with no `language`.
- On a crawl.db seeded from `schema.sql` with any `language` line removed (so the table really lacks the column) and holding two videos, the crawl adds the column, keeps the video it did not revisit with `language` NULL, and stores "de" on the one it did.
- A missing node or git, a missing or stale dist, or a nonzero node exit fails the test rather than skipping it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
CRAWLER_DIR = ROOT / "engine" / "crawler"
SCHEMA = CRAWLER_DIR / "schema.sql"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
# (source, compiled) pairs the crawl runs through: the worker, and the store that migrates crawl.db and writes the rows.
BUILD_PAIRS = [(CRAWLER_DIR / "src" / "videos-worker.ts", DIST), (CRAWLER_DIR / "src" / "db.ts", CRAWLER_DIR / "dist" / "db.js")]
BUILD_HINT = "cd engine/crawler && npm install && npm run build"

# The whitelist videos table as `ensure_content_schema` created it before this build: error columns present, `language` absent.
PRE_CHANGE_VIDEOS_SQL = """
CREATE TABLE videos (
  video_id TEXT NOT NULL,
  video_uuid TEXT,
  video_numeric_id INTEGER,
  instance_domain TEXT NOT NULL,
  channel_id TEXT,
  channel_name TEXT,
  channel_url TEXT,
  account_name TEXT,
  account_url TEXT,
  title TEXT,
  description TEXT,
  tags_json TEXT,
  category TEXT,
  published_at INTEGER,
  video_url TEXT,
  duration INTEGER,
  thumbnail_url TEXT,
  embed_path TEXT,
  views INTEGER,
  likes INTEGER,
  dislikes INTEGER,
  comments_count INTEGER,
  nsfw INTEGER,
  preview_path TEXT,
  popularity REAL NOT NULL DEFAULT 0,
  last_checked_at INTEGER NOT NULL,
  last_error TEXT,
  last_error_at INTEGER,
  error_count INTEGER NOT NULL DEFAULT 0,
  invalid_reason TEXT,
  invalid_at INTEGER,
  PRIMARY KEY (video_id, instance_domain)
);
"""
TRIGGERS_SQL = "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'videos_fts_%' ORDER BY name"
EXPECTED_TRIGGERS = [("videos_fts_ad",), ("videos_fts_ai",), ("videos_fts_au",)]
ROWS_SQL = "SELECT video_id, title, tags_json, category, language FROM videos ORDER BY video_id"
MATCH_SQL = "SELECT v.video_id FROM videos_fts JOIN videos v ON v.rowid = videos_fts.rowid WHERE videos_fts MATCH ?"
LANGUAGE_LINE = r"^[ \t]*language\b[^\n]*\n"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_info(conn: sqlite3.Connection) -> list:
    return conn.execute("PRAGMA table_info(videos)").fetchall()


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in _table_info(conn)]


def _matches(conn: sqlite3.Connection, word: str) -> set:
    return {row[0] for row in conn.execute(MATCH_SQL, (f'title : "{word}"',))}


def test_migration_adds_language_column(tmp_path):
    sync_job = _load_job("sync_whitelist_language", "sync-whitelist.py")
    migrations = _load_job("whitelist_migrations_language", "whitelist_migrations.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        conn.executescript(PRE_CHANGE_VIDEOS_SQL)
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.executemany("INSERT INTO videos (video_id, instance_domain, title, tags_json, category, last_checked_at) VALUES (?, 'a.example', ?, ?, ?, 1)", [("v1", "Alpine walk", '["hike"]', "Travels"), ("v2", "Harbour night", None, None)])
        conn.commit()
        assert "language" not in _column_names(conn), "the pre-change videos table already has language"
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS, "the FTS triggers were not in place before the migration"

        migrations.migrate_whitelist_schema(conn, "instances")

        language = [row for row in _table_info(conn) if row[1] == "language"]
        assert len(language) == 1  # C1
        assert language[0][3] == 0, "language is NOT NULL"  # C1
        assert conn.execute(ROWS_SQL).fetchall() == [("v1", "Alpine walk", '["hike"]', "Travels", None), ("v2", "Harbour night", None, None, None)]  # C1
        # A rebuild of `videos` takes the triggers and the external-content index down with it.
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS  # C1
        assert _matches(conn, "Alpine") == {"v1"}  # C1
        conn.execute("INSERT INTO videos (video_id, instance_domain, title, last_checked_at, language) VALUES ('v3', 'a.example', 'Lantern festival', 1, 'fr')")
        assert _matches(conn, "Lantern") == {"v3"}, "the insert trigger no longer feeds videos_fts"  # C1
        conn.commit()

        info_after_first = _table_info(conn)
        rows_after_first = conn.execute(ROWS_SQL).fetchall()
        migrations.migrate_whitelist_schema(conn, "instances")
        assert _table_info(conn) == info_after_first  # C1
        assert conn.execute(ROWS_SQL).fetchall() == rows_after_first  # C1
        assert conn.execute(TRIGGERS_SQL).fetchall() == EXPECTED_TRIGGERS  # C1
        assert _matches(conn, "Alpine") == {"v1"} and _matches(conn, "Lantern") == {"v3"}, "the second run left videos_fts unbuilt"  # C1
    finally:
        conn.close()


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str, src: Path, dist: Path) -> bool:
    """Whether dist predates src: by commit time when both are committed and clean, since a checkout sets mtimes arbitrarily; otherwise by time on disk."""
    dirty = _git(git, "status", "--porcelain", "--", str(src), str(dist))
    src_committed = _git(git, "log", "-1", "--format=%ct", "--", str(src))
    dist_committed = _git(git, "log", "-1", "--format=%ct", "--", str(dist))
    if dirty or not src_committed or not dist_committed:
        return src.stat().st_mtime > dist.stat().st_mtime
    return int(src_committed) > int(dist_committed)


def _require_built_crawler() -> str:
    node = shutil.which("node")
    assert node is not None, f"node is not on PATH; install Node.js, then {BUILD_HINT}"
    git = shutil.which("git")
    assert git is not None, "git is not on PATH, so whether the dist predates its source cannot be told"
    for src, dist in BUILD_PAIRS:
        assert dist.is_file(), f"{dist} is missing; {BUILD_HINT}"
        assert not _dist_is_stale(git, src, dist), f"{dist} predates {src}; {BUILD_HINT}"
    return node


def _instance(slug: str, videos: list[dict]) -> ThreadingHTTPServer:
    """A PeerTube stand-in serving one channel's videos page."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] != f"/api/v1/video-channels/{slug}/videos":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"total": len(videos), "data": videos}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _crawl(node: str, db_path: Path) -> subprocess.CompletedProcess:
    # maxRetries 0 keeps the crawler's https-first attempt against these plain-http servers to one fast failure before its http fallback.
    options = {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
    return subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})


def _stop(*servers: ThreadingHTTPServer) -> None:
    for server in servers:
        server.shutdown()
        server.server_close()


def test_crawl_stores_each_videos_language(tmp_path):
    node = _require_built_crawler()
    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one", "language": {"id": "en", "label": "English"}}, {"uuid": "a-2", "name": "A two", "language": {"id": None, "label": "Unknown"}}])
    beta = _instance("beta", [{"uuid": "b-1", "name": "B one"}])
    try:
        host_a = f"127.0.0.1:{alpha.server_address[1]}"
        host_b = f"127.0.0.1:{beta.server_address[1]}"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executemany("INSERT INTO instances (host) VALUES (?)", [(host_a,), (host_b,)])
            conn.executemany("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES (?, ?, ?, ?, ?, ?)", [("7", "alpha", f"http://{host_a}/video-channels/alpha", "Alpha Display", host_a, 2), ("7", "beta", f"http://{host_b}/video-channels/beta", "Beta Display", host_b, 1)])
            conn.commit()
        finally:
            conn.close()
        proc = _crawl(node, db_path)
    finally:
        _stop(alpha, beta)
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        assert "language" in _column_names(conn), f"crawl.db has no videos.language after the crawl; crawl log: {proc.stdout}"
        languages = {video_id: language for video_id, language in conn.execute("SELECT video_id, language FROM videos")}
    finally:
        conn.close()
    assert languages == {"a-1": "en", "a-2": None, "b-1": None}, f"crawl log: {proc.stdout}"  # C2


def test_crawl_adds_language_to_existing_db(tmp_path):
    node = _require_built_crawler()
    schema = SCHEMA.read_text(encoding="utf-8")
    # Before the phase schema.sql has no language line, after it has one; either way the stripped schema is the pre-change one, which the column check below confirms.
    old_schema, removed = re.subn(LANGUAGE_LINE, "", schema, flags=re.M)
    assert removed <= 1, f"{SCHEMA} carries {removed} language lines, so stripping them does not give the pre-change schema"

    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one", "language": {"id": "de", "label": "German"}}])
    try:
        host = f"127.0.0.1:{alpha.server_address[1]}"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(old_schema)
            conn.execute("INSERT INTO instances (host) VALUES (?)", (host,))
            conn.execute("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES ('7', 'alpha', ?, 'Alpha Display', ?, 1)", (f"http://{host}/video-channels/alpha", host))
            # a-0 is not served, so it only survives if the column is added without dropping rows; a-1 is served, so its language arrives through the upsert's conflict path.
            conn.executemany("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES (?, ?, '7', ?, 1)", [("a-0", host, "Old one"), ("a-1", host, "Stale title")])
            conn.commit()
            assert "language" not in _column_names(conn), "the stripped schema still created videos.language"
        finally:
            conn.close()
        proc = _crawl(node, db_path)
    finally:
        _stop(alpha)
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        assert "language" in _column_names(conn), f"crawl log: {proc.stdout}"  # C2
        rows = conn.execute("SELECT video_id, title, language FROM videos ORDER BY video_id").fetchall()
    finally:
        conn.close()
    assert rows == [("a-0", "Old one", None), ("a-1", "A one", "de")], f"crawl log: {proc.stdout}"  # C2
