"""Probe: a heavy AFTER UPDATE trigger under an expired deadline on today's code, and a real similars stack (faiss + strategy) over a temp DB."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
HOST = "tube.example"
UUID = "uuid-v1"

CHILD = r'''
import http.client, inspect, json, sys, threading, time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import faiss, numpy as np
import server
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler
reports = []

def get(port, path):
    started = time.monotonic()
    try:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        client.request("GET", path)
        resp = client.getresponse()
        raw = resp.read()
        client.close()
        return {"status": resp.status, "body": json.loads(raw or b"null"), "elapsed": time.monotonic() - started}
    except Exception as exc:
        return {"status": None, "body": repr(exc), "elapsed": time.monotonic() - started}

def similars_stack(conn):
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    rows = conn.execute("SELECT rowid, embedding FROM video_embeddings").fetchall()
    index.add_with_ids(np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]), np.array([r["rowid"] for r in rows], dtype=np.int64))
    deps = server.RecommendationBuilderDeps(fetch_recent_likes=server.fetch_recent_likes_request, fetch_seed_embedding=server.fetch_seed_embedding, fetch_seed_embeddings_for_likes=server.fetch_seed_embeddings_for_likes, get_similar_candidates=server.get_similar_candidates, like_key=server.like_key, fetch_embeddings_by_ids=server.fetch_embeddings_by_ids, fetch_random_rows=server.fetch_random_rows, fetch_random_rows_from_cache=server.fetch_random_rows_from_cache, fetch_recent_videos=server.fetch_recent_videos, fetch_popular_videos=server.fetch_popular_videos, fetch_dislike_centroids=server.fetch_request_dislike_centroids, fetch_excluded_keys=server.fetch_request_excluded_keys)
    settings = server.RecommendationBuilderSettings(max_likes=server.MAX_LIKES, max_likes_for_recs=server.MAX_LIKES_FOR_RECS, similar_per_like=server.SIMILAR_PER_LIKE, default_similar_from_likes_source=server.DEFAULT_USE_SIMILARITY_CACHE, video_error_threshold=server.VIDEO_ERROR_THRESHOLD, fresh_pool_size=server.DEFAULT_FRESH_POOL_SIZE, dislike_similarity_floor=server.DISLIKE_SIMILARITY_FLOOR)
    strategy = server.build_recommendation_strategy(server.RECOMMENDATION_PIPELINE, deps, settings)
    strategy.settings = settings
    return {"index": index, "embeddings_dim": 4, "embeddings_count": len(rows), "default_limit": 8, "normalize_queries": True, "similarity_search_limit": 0, "similarity_max_per_author": 0, "similarity_exclude_source_author": False, "similarity_require_full_cache": False, "recommendation_strategy": strategy}

for case in json.loads(sys.stdin.read()):
    conn = connect_db(Path(case["db"]))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    extra = similars_stack(conn) if case.get("stack") else {}
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0, **extra})
    if case.get("timeout") is not None:
        srv.statement_timeout_seconds = case["timeout"]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    calls = []
    entered = threading.Event()
    def stub(host, api_path):
        calls.append([host, api_path])
        entered.set()
        if case.get("hold_lock"):
            with srv.db_lock:
                time.sleep(case.get("delay", 0))
        else:
            time.sleep(case.get("delay", 0))
        return case["answers"].get(api_path)
    report = {}
    try:
        with patch.object(video, "fetch_instance_json", stub):
            if case.get("similar") and case.get("path"):
                holder = {}
                worker = threading.Thread(target=lambda: holder.update(get(port, case["path"])))
                worker.start()
                report["entered"] = entered.wait(10)
                report["similar"] = get(port, case["similar"])
                report["calls_at_similar"] = [list(c) for c in calls]
                worker.join(30)
                report["refresh"] = holder
            elif case.get("similar"):
                report["similar"] = get(port, case["similar"])
            else:
                report["refresh"] = get(port, case["path"])
        report["calls"] = calls
        reports.append(report)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''


def _sync():
    spec = importlib.util.spec_from_file_location("probe_sync_11b", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(sync, path: Path, heavy: bool = False) -> None:
    conn = sqlite3.connect(path)
    sync.ensure_whitelist_schema(conn)
    sync.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 123, 'crawler')", (HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
    conn.execute(
        "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
        (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
    )
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, embed_path, views, likes, dislikes, last_checked_at) VALUES ('v2', 'uuid-v2', ?, 'c2', 'Neighbour', 1700000000000, '/videos/embed/uuid-v2', 5, 1, 0, 1)", (HOST,))
    conn.execute("INSERT INTO video_embeddings VALUES ('v1', ?, ?, 4, 'm', 'now')", (HOST, array("f", [1, 0, 0, 0]).tobytes()))
    conn.execute("INSERT INTO video_embeddings VALUES ('v2', ?, ?, 4, 'm', 'now')", (HOST, array("f", [0.8, 0.6, 0, 0]).tobytes()))
    if heavy:
        conn.execute("CREATE TABLE heavy (n INTEGER)")
        conn.executemany("INSERT INTO heavy VALUES (?)", [(i,) for i in range(300)])
        conn.execute("CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END")
    conn.commit()
    conn.close()


def _rows(path: Path) -> dict:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    out = {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table}")] for table in ("videos", "channels", "instances")}
    conn.close()
    return out


DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
ANSWERING = {f"/api/v1/videos/{UUID}": DETAIL, "/api/v1/video-channels/live_slug": {"displayName": "Live Chan Detail", "followersCount": 77}}
REFRESH = f"/api/video/refresh?id={UUID}&host={HOST}"
SIMILAR = f"/videos/v1/similar?host={HOST}"


def test_probe(tmp_path):
    sync = _sync()
    specs = [
        ("similar_during_locked_refresh", {"path": REFRESH, "answers": {f"/api/v1/videos/{UUID}": DETAIL}, "delay": 2, "similar": SIMILAR, "stack": True, "hold_lock": True}, {}),
    ]
    cases = []
    befores = []
    for name, case, seed_kw in specs:
        db = tmp_path / f"{name}.db"
        _seed(sync, db, **seed_kw)
        befores.append(_rows(db))
        cases.append({**case, "db": str(db)})
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], input=json.dumps(cases), cwd=API_DIR, capture_output=True, text=True, timeout=300)
    print("RC", run.returncode)
    print("STDERR", run.stderr[-4000:])
    for (name, _case, _kw), before, report in zip(specs, befores, json.loads(run.stdout)):
        after = _rows(tmp_path / f"{name}.db")
        print("CASE", name)
        print("  REPORT", json.dumps(report, sort_keys=True)[:3000])
        print("  CHANGED", before != after)
        print("  AFTER_V1", json.dumps([r for r in after["videos"] if r["video_id"] == "v1"], sort_keys=True))
    assert False, "probe"
