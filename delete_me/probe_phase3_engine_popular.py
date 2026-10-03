"""Throwaway probe: an Engine on --trending-db <private seed>, its trending pages and popular-layer rows; never writes the shared whitelist.db."""
from __future__ import annotations

import fcntl
import importlib.util
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))
import conftest as cf  # noqa: E402

for _path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data import random_videos, trending  # noqa: E402

FP = "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at), COUNT(CASE WHEN fetched_at > 0 THEN 1 END) FROM main.trending_ranks"


def _fp():
    c = sqlite3.connect(f"file:{cf.WHITELIST_DB}?mode=ro", uri=True)
    try:
        return tuple(c.execute(FP).fetchone())
    finally:
        c.close()


def _keys(rows):
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def test_probe(tmp_path):
    before = _fp()
    private = tmp_path / "trending.db"
    conn = sqlite3.connect(f"file:{private}", uri=True)
    trending.ensure_trending_schema(conn)
    conn.execute("ATTACH DATABASE ? AS shared", (f"file:{cf.WHITELIST_DB}?mode=ro",))
    with conn:
        conn.execute(cf.TRENDING_SEED_SQL)
    conn.close()
    ds = sqlite3.connect(f"file:{cf.WHITELIST_DB}?mode=ro", uri=True)
    ds.row_factory = sqlite3.Row
    trending.attach_trending_override(ds, str(private))
    plain = sqlite3.connect(f"file:{cf.WHITELIST_DB}?mode=ro", uri=True)
    plain.row_factory = sqlite3.Row
    p_pool = set(_keys(random_videos.fetch_popular_videos(ds, 5000, error_threshold=3, include_nsfw=False)))
    s_pool = set(_keys(random_videos.fetch_popular_videos(plain, 5000, error_threshold=3, include_nsfw=False)))
    p_head = _keys(random_videos.fetch_ordered_page(ds, "trending", 36, 0, error_threshold=3, include_nsfw=False))

    log_path = tmp_path / "engine.log"
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": cf.BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    with open(log_path, "w") as log, open(cf.ENGINE_START_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        port = cf._free_port()
        proc = subprocess.Popen([str(cf.ENGINE_PY), str(cf.ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh", "--trending-db", str(private)], env=env, stdout=log, stderr=log)
        http = cf.ClientBackend(f"http://127.0.0.1:{port}", log_path)
        try:
            deadline = time.time() + 120
            while proc.poll() is None and time.time() < deadline:
                try:
                    if http.request("GET", "/api/health")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            fcntl.flock(lock, fcntl.LOCK_UN)
            status, page = http.request("POST", "/recommendations?mode=trending&limit=12", headers={"X-Client-IP": "192.0.2.180"}, body={})
            print("trending status", status, "seed", page.get("seed"), "matches private head[:12]", _keys(page["rows"]) == p_head[:12])
            for limit in (48, 96):
                for _ in range(3):
                    status, body = http.request("POST", f"/recommendations?limit={limit}&debug=1", headers={"X-Client-IP": "192.0.2.181"}, body={})
                    rows = body["rows"]
                    pop = [r for r in rows if r["debug"]["layer"] == "popular"]
                    layers = sorted({str(r["debug"]["layer"]) for r in rows})
                    print("limit", limit, "status", status, "seed", body.get("seed"), "rows", len(rows), "layers", layers, "popular", len(pop), "in private", sum(k in p_pool for k in _keys(pop)), "in shared", sum(k in s_pool for k in _keys(pop)))
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    print("fp before", before, "after", _fp())
    assert False, "probe"
