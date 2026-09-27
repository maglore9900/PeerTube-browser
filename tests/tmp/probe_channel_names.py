import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRAWLER_DIR = ROOT / "engine" / "crawler"
SRC = CRAWLER_DIR / "src" / "videos-worker.ts"
DIST = CRAWLER_DIR / "dist" / "videos-worker.js"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { crawlVideos } = await import(process.env.VIDEOS_WORKER_URL);
await crawlVideos(JSON.parse(readFileSync(0, "utf8")));
"""


def _server(slug, videos, hits):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path.split("?", 1)[0] != f"/api/v1/video-channels/{slug}/videos":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"total": len(videos), "data": videos}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_probe(tmp_path):
    print("node", shutil.which("node"), "git", shutil.which("git"))
    print("dist exists", DIST.is_file(), "src mtime", SRC.stat().st_mtime, "dist mtime", DIST.stat().st_mtime)
    print("git status", subprocess.run(["git", "status", "--porcelain", "--", str(SRC), str(DIST)], cwd=ROOT, capture_output=True, text=True).stdout)
    hits_a, hits_b = [], []
    a = _server("alpha", [{"uuid": "a-1", "name": "A one"}, {"uuid": "a-2", "name": "A two"}], hits_a)
    b = _server("beta", [{"uuid": "b-1", "name": "B one"}], hits_b)
    host_a = f"127.0.0.1:{a.server_address[1]}"
    host_b = f"127.0.0.1:{b.server_address[1]}"
    db = tmp_path / "crawl.db"
    conn = sqlite3.connect(db)
    conn.executescript((CRAWLER_DIR / "schema.sql").read_text())
    conn.executemany("INSERT INTO instances (host) VALUES (?)", [(host_a,), (host_b,)])
    conn.executemany("INSERT INTO channels (channel_id, channel_name, channel_url, display_name, instance_domain, videos_count) VALUES (?, ?, ?, ?, ?, ?)", [("7", "alpha", f"http://{host_a}/video-channels/alpha", "Alpha Display", host_a, 2), ("7", "beta", f"http://{host_b}/video-channels/beta", "Beta Display", host_b, 1)])
    conn.commit()
    conn.close()
    options = {"dbPath": str(db), "excludeHostsFile": None, "existingDbPath": None, "concurrency": 2, "timeoutMs": 5000, "maxRetries": 0, "resume": False, "errorsOnly": False, "newOnly": False, "stopAfterFullPages": 0, "sort": "-publishedAt", "maxInstances": 0, "maxChannels": 0, "maxVideosPages": 0, "tagsOnly": False, "updateTags": False, "commentsOnly": False, "hostDelayMs": 0}
    t0 = time.time()
    proc = subprocess.run([shutil.which("node"), "--input-type=module", "-e", NODE_SCRIPT], cwd=CRAWLER_DIR, input=json.dumps(options), capture_output=True, text=True, timeout=120, env={**os.environ, "VIDEOS_WORKER_URL": DIST.as_uri()})
    print("elapsed", time.time() - t0, "rc", proc.returncode)
    print("STDOUT", proc.stdout)
    print("STDERR", proc.stderr)
    print("hits_a", hits_a, "hits_b", hits_b)
    a.shutdown(); b.shutdown()
    conn = sqlite3.connect(db)
    print("videos", conn.execute("SELECT instance_domain, video_id, channel_id, channel_name, channel_url FROM videos ORDER BY 1, 2").fetchall())
    print("progress", conn.execute("SELECT * FROM video_crawl_progress").fetchall())
    print("channels order", conn.execute("SELECT channel_id, instance_domain, display_name FROM channels").fetchall())
    conn.close()
    assert False, "probe"
