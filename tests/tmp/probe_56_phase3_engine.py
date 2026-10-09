"""Probe: a started Engine over the repo whitelist and a test subtitles store, reached directly and through the real Client backend."""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_internal_translate import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, HEALTHY_WITHIN_SECONDS, STOP_WITHIN_SECONDS, VARIANT_RUNNER, _free_port, _post, _subtitles_db  # noqa: E402
from test_server import _keyed_client_backend, translate_bridge_token  # noqa: E402,F401
from conftest import WHITELIST_DB, RateLimiter  # noqa: E402

from data.subtitles import enqueue_translate_job  # noqa: E402


def _dump(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT rowid, * FROM subtitles")]
    finally:
        conn.close()


def test_started_engine(tmp_path, translate_bridge_token):
    ro = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    print("DENYLIST COLS", ro.execute("PRAGMA table_info(instance_denylist)").fetchall())
    video = ro.execute("SELECT video_id, video_uuid, instance_domain FROM videos WHERE COALESCE(error_count, 0) = 0 AND lower(instance_domain) NOT IN (SELECT lower(host) FROM instance_denylist WHERE is_active = 1) ORDER BY video_id LIMIT 1").fetchone()
    ro.close()
    print("VIDEO", video)
    video_id, uuid, host = video
    subtitles_path = tmp_path / "subtitles.db"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "engine.log"
    started = time.time()
    with open(log_path, "w") as log, open(ENGINE_START_LOCK, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(subtitles_path)}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env={**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}, stdout=log, stderr=log)
        healthy = False
        deadline = time.time() + HEALTHY_WITHIN_SECONDS
        while proc.poll() is None and time.time() < deadline and not healthy:
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                    healthy = resp.status == 200
            except OSError:
                time.sleep(0.1)
    try:
        print("HEALTHY", healthy, "after", time.time() - started)
        store = _subtitles_db(subtitles_path)
        seeded_at = int(time.time() * 1000)
        print("enqueue", enqueue_translate_job(store, video_id, host, "en", 50, seeded_at, wanted_at=seeded_at))
        store.close()
        body = {"id": uuid, "host": host}
        print("STATE direct", _post(base, "/internal/translate", body, {"X-Bridge-Token": BRIDGE_TOKEN}), _dump(subtitles_path))
        print("CANCEL direct no token", _post(base, "/internal/translate/cancel", body, {}))
        print("CANCEL direct token", _post(base, "/internal/translate/cancel", body, {"X-Bridge-Token": BRIDGE_TOKEN}))
        with _keyed_client_backend(tmp_path, base, RateLimiter(1000, 60)) as (client_base, key):
            req = urllib.request.Request(client_base + "/api/translate/cancel", data=json.dumps(body).encode(), method="POST", headers={"content-type": "application/json", **key})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    print("CLIENT cancel", resp.status, resp.read())
            except urllib.error.HTTPError as exc:
                print("CLIENT cancel", exc.code, exc.read())
        print("ROWS", _dump(subtitles_path), "seeded_at", seeded_at)
    finally:
        proc.terminate()
        proc.wait(timeout=STOP_WITHIN_SECONDS)
        print("LOG", log_path.read_text()[-1500:])
