"""Probe: what today's /api/video answers over a seeded whitelist-shaped DB with a patched fetch_instance_json, and what /api/video/refresh answers before the build."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
from conftest import ENGINE_PY  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"

CHILD = r'''
import http.client, inspect, json, sys, threading
from pathlib import Path
from unittest.mock import patch
import server
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler
reports = []
for db_path, path, answers in json.loads(sys.argv[1]):
    conn = connect_db(Path(db_path))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0})
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    calls = []
    def stub(host, api_path):
        calls.append([host, api_path])
        return answers.get(api_path)
    try:
        with patch.object(video, "fetch_instance_json", stub):
            client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            client.request("GET", path)
            resp = client.getresponse()
            body = json.loads(resp.read() or b"null")
            client.close()
        reports.append({"status": resp.status, "body": body, "calls": calls, "timeout": srv.statement_timeout_seconds})
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''

DETAIL_A = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": "https://tube.example/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
CHANNEL_A = {"displayName": "Live Chan Detail", "followersCount": 77}
DETAIL_B = {"name": "Live title B", "likes": 0, "dislikes": 3, "channel": {"name": "live_slug"}}


def _load_job(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(path: Path) -> None:
    sync = _load_job("probe_sync_11", "sync-whitelist.py")
    conn = sqlite3.connect(path)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error) VALUES ('tube.example', 'boom')")
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', 'tube.example', 'db_slug', 'DB Chan', 5, 'https://tube.example/lazy-static/avatars/db.png')")
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', 'uuid-v1', 'tube.example', 'c1', 'DB Chan', 'DB Account', 'https://tube.example/accounts/db', 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, '/videos/embed/uuid-v1', 10, 2, 1, 0, 1)")
    conn.commit()
    conn.close()


def test_probe(tmp_path):
    cases = []
    for i, (path, answers) in enumerate([
        ("/api/video?id=uuid-v1&host=tube.example", {"/api/v1/videos/uuid-v1": DETAIL_A, "/api/v1/video-channels/live_slug": CHANNEL_A}),
        ("/api/video?id=uuid-v1&host=tube.example", {"/api/v1/videos/uuid-v1": DETAIL_B}),
        ("/api/video/refresh?id=uuid-v1&host=tube.example", {"/api/v1/videos/uuid-v1": DETAIL_A}),
        ("/api/video?host=tube.example", {}),
        ("/api/video?id=nope&host=tube.example", {}),
    ]):
        db = tmp_path / f"case{i}.db"
        _seed(db)
        cases.append([str(db), path, answers])
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, json.dumps(cases)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("STDERR", run.stderr[-3000:])
    for report in json.loads(run.stdout):
        print(json.dumps(report, sort_keys=True))
    assert False, "probe"
