"""Probe: the nsfw GET /videos/{id}/similar sequence and the home/random feeds against a fresh Engine on the current checkout state, with the Engine log kept under tests/tmp."""

import itertools
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, WHITELIST_DB, ClientBackend, _free_port  # noqa: E402

LOG = ROOT / "tests" / "tmp" / "probe_step8_engine.log"
CACHE = ROOT / "engine" / "server" / "db" / "random-cache.db"
SEED_ID, SEED_HOST = "59b6239b-15c6-4bc4-b5e6-6ebac4ea9751", "810video.com"
IPS = (f"198.18.200.{n + 1}" for n in itertools.count())


def test_probe():
    rc = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    print("random-cache tables", rc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), "count", rc.execute("SELECT COUNT(*) FROM random_ann_ids").fetchone())
    rc.close()
    db = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    flagged = {(a, b) for a, b in db.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    print("seed flagged", (SEED_ID, SEED_HOST) in flagged, "flagged total", len(flagged))
    log = open(LOG, "w")
    port = _free_port()
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    proc = subprocess.Popen([str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
    http = ClientBackend(f"http://127.0.0.1:{port}", LOG)
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if http.request("GET", "/api/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        for path in ("/recommendations", "/recommendations?random=1"):
            t = time.time()
            status, body = http.request("POST", path, headers={"X-Client-IP": next(IPS)}, body={})
            print("feed", path, status, len(body.get("rows", [])) if isinstance(body, dict) else body, f"{time.time() - t:.2f}s")
        base = f"/videos/{SEED_ID}/similar?host={SEED_HOST}&limit=96&seed=11"
        for suffix in ("&nsfw=1", "", "&nsfw=", "&nsfw=0", "&nsfw=true", "&nsfw=%201", "&nsfw=1", ""):
            t = time.time()
            status, body = http.request("GET", base + suffix, headers={"X-Client-IP": next(IPS)})
            rows = body.get("rows", []) if isinstance(body, dict) else []
            keys = {(r["video_id"], r["instance_domain"]) for r in rows}
            print("GET", repr(suffix), status, "rows", len(rows), "flagged", len(keys & flagged), "body" if status != 200 else "", body if status != 200 else "", f"{time.time() - t:.2f}s")
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        log.close()
    lines = LOG.read_text(errors="replace").splitlines()
    print("log lines", len(lines))
    for line in lines:
        if any(word in line for word in ("random cache", "ERROR", "Traceback", "Error", "upnext_pool", "interrupt")):
            print("LOG", line[:400])
    assert False, "probe"
