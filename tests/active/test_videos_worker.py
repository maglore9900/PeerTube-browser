"""The crawler's compiled `crawlVideos`, run under node against two local PeerTube stand-ins whose channels share channel_id "7".

- Every video stored for a host has `channel_name` equal to the `display_name` of that host's own channel row, and no video carries the other host's name.
- Every video stored for a host has `channel_url` equal to the `channel_url` of that host's own channel row, and no video carries the other host's URL.
- A missing node or git, a missing or stale dist, or a nonzero node exit fails the test rather than skipping it.
"""
from __future__ import annotations

import json
import os
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
BUILD_HINT = "cd engine/crawler && npm install && npm run build"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str) -> bool:
    """Whether DIST predates SRC: by commit time when both are committed and clean, since a checkout sets mtimes arbitrarily; otherwise by time on disk."""
    dirty = _git(git, "status", "--porcelain", "--", str(SRC), str(DIST))
    src_committed = _git(git, "log", "-1", "--format=%ct", "--", str(SRC))
    dist_committed = _git(git, "log", "-1", "--format=%ct", "--", str(DIST))
    if dirty or not src_committed or not dist_committed:
        return SRC.stat().st_mtime > DIST.stat().st_mtime
    return int(src_committed) > int(dist_committed)


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
