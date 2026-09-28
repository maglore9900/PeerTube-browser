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
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"
NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _instance(slug, videos):
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


def test_probe(tmp_path):
    alpha = _instance("alpha", [{"uuid": "a-1", "name": "A one", "language": {"id": "de", "label": "German"}}, {"uuid": "a-2", "name": "A two", "language": {"id": None, "label": "Unknown"}}])
    try:
        host = f"127.0.0.1:{alpha.server_address[1]}"
        db_path = tmp_path / "crawl.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO instances (host) VALUES (?)", (host,))
        conn.execute("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES ('7', 'alpha', ?, 'Alpha Display', ?, 2)", (f"http://{host}/video-channels/alpha", host))
        conn.execute("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES ('a-0', ?, '7', 'Old one', 1)", (host,))
        conn.execute("INSERT INTO videos (video_id, instance_domain, channel_id, title, last_checked_at) VALUES ('a-1', ?, '7', 'Stale title', 1)", (host,))
        conn.commit()
        conn.close()
        options = {"dbPath": str(db_path), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
        proc = subprocess.run([shutil.which("node"), "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, encoding="utf-8", timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})
    finally:
        alpha.shutdown()
        alpha.server_close()
    print("rc", proc.returncode, "stdout", proc.stdout, "stderr", proc.stderr)
    conn = sqlite3.connect(db_path)
    print("cols", [r[1] for r in conn.execute("PRAGMA table_info(videos)")])
    print("rows", conn.execute("SELECT video_id, title FROM videos ORDER BY video_id").fetchall())
    conn.close()
    assert False
