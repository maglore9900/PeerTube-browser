"""The crawler's compiled `crawlVideos`, run under node against local PeerTube stand-ins.

Two stand-ins whose channels share channel_id "7":

- Every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row, and no video carries the other host's name.
- Every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row, and no video carries the other host's URL.

Language (the store `dist/db.js` migrates crawl.db and writes the rows):

- A crawl stores `language.id` per video: "en" for a video carrying it, NULL for `{"id": null}`, NULL for a video with no `language`.
- On a crawl.db seeded from `schema.sql` with any `language` line removed (so the table really lacks the column) and holding two videos, the crawl adds the column, keeps the video it did not revisit with `language` NULL, and stores "de" on the one it did.

A missing node or git, a missing or stale dist, or a nonzero node exit fails the test rather than skipping it.
"""
from __future__ import annotations

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
CRAWLER_DIR = ROOT / "engine" / "crawler"
SCHEMA = CRAWLER_DIR / "schema.sql"
SRC = CRAWLER_DIR / "src" / "videos-worker.ts"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
# (source, compiled) pairs a language crawl runs through: the worker, and the store that migrates crawl.db and writes the rows.
BUILD_PAIRS = [(SRC, DIST), (CRAWLER_DIR / "src" / "db.ts", CRAWLER_DIR / "dist" / "db.js")]
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
LANGUAGE_LINE = r"^[ \t]*language\b[^\n]*\n"
# maxRetries 0 keeps the crawler's https-first attempt against these plain-http servers to one fast failure before its http fallback.
CRAWL_OPTIONS = {"excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str, src: Path = SRC, dist: Path = DIST) -> bool:
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


def _crawl(node: str, db_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps({"dbPath": str(db_path), **CRAWL_OPTIONS}), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})


def _stop(*servers: ThreadingHTTPServer) -> None:
    for server in servers:
        server.shutdown()
        server.server_close()


def _column_names(conn: sqlite3.Connection) -> list:
    return [row[1] for row in conn.execute("PRAGMA table_info(videos)").fetchall()]


def _instance(slug: str, videos: list[dict]) -> ThreadingHTTPServer:
    """A PeerTube stand-in serving one channel's videos page; the videos carry no `channel`, so the stored name and URL can only come from the channels row."""
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


def test_crawl_writes_each_hosts_own_channel_name(tmp_path):
    node = shutil.which("node")
    assert node is not None, f"node is not on PATH; install Node.js, then {BUILD_HINT}"
    assert DIST.is_file(), f"{DIST} is missing; {BUILD_HINT}"
    git = shutil.which("git")
    assert git is not None, f"git is not on PATH, so whether {DIST} predates {SRC} cannot be told"
    assert not _dist_is_stale(git), f"{DIST} predates {SRC}; {BUILD_HINT}"

    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one"}, {"uuid": "a-2", "name": "A two"}])
    beta = _instance("beta", [{"uuid": "b-1", "name": "B one"}])
    try:
        host_a = f"127.0.0.1:{alpha.server_address[1]}"
        host_b = f"127.0.0.1:{beta.server_address[1]}"
        url_a = f"http://{host_a}/video-channels/alpha"
        url_b = f"http://{host_b}/video-channels/beta"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executemany("INSERT INTO instances (host) VALUES (?)", [(host_a,), (host_b,)])
            conn.executemany("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES (?, ?, ?, ?, ?, ?)", [("7", "alpha", url_a, "Alpha Display", host_a, 2), ("7", "beta", url_b, "Beta Display", host_b, 1)])
            conn.commit()
        finally:
            conn.close()
        # maxRetries 0 keeps the crawler's https-first attempt against these plain-http servers to one fast failure before its http fallback.
        options = {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
        proc = subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})
    finally:
        alpha.shutdown()
        alpha.server_close()
        beta.shutdown()
        beta.server_close()
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT instance_domain, video_id, channel_name, channel_url FROM videos").fetchall()
    finally:
        conn.close()
    names = {(host, video_id): name for host, video_id, name, _ in rows}
    urls = {(host, video_id): url for host, video_id, _, url in rows}
    assert names == {(host_a, "a-1"): "Alpha Display", (host_a, "a-2"): "Alpha Display", (host_b, "b-1"): "Beta Display"}, f"crawl log: {proc.stdout}"
    assert urls == {(host_a, "a-1"): url_a, (host_a, "a-2"): url_a, (host_b, "b-1"): url_b}, f"crawl log: {proc.stdout}"


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
    assert languages == {"a-1": "en", "a-2": None, "b-1": None}, f"crawl log: {proc.stdout}"


def test_crawl_adds_language_to_existing_db(tmp_path):
    node = _require_built_crawler()
    schema = SCHEMA.read_text(encoding="utf-8")
    # schema.sql carries one language line; stripped, it is the pre-language schema, which the column check below confirms.
    old_schema, removed = re.subn(LANGUAGE_LINE, "", schema, flags=re.M)
    assert removed <= 1, f"{SCHEMA} carries {removed} language lines, so stripping them does not give the pre-language schema"

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
        assert "language" in _column_names(conn), f"crawl log: {proc.stdout}"
        rows = conn.execute("SELECT video_id, title, language FROM videos ORDER BY video_id").fetchall()
    finally:
        conn.close()
    assert rows == [("a-0", "Old one", None), ("a-1", "A one", "de")], f"crawl log: {proc.stdout}"
