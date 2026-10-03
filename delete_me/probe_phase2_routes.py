"""Probe: what today's Engine (no /internal/translate route) answers for that route, with and without the bridge token."""
import fcntl
import json
import os
import subprocess
import time
import urllib.request

from test_48_translate_instance_captions_phase2 import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, _free_port, _post


def test_probe(tmp_path):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}
    with open(tmp_path / "engine.log", "w") as log, open(ENGINE_START_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen([str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
        healthy = False
        deadline = time.time() + 120
        while not healthy and time.time() < deadline and proc.poll() is None:
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                    healthy = resp.status == 200
            except OSError:
                time.sleep(0.1)
    try:
        body = {"id": "no-such-video", "host": "no-such-host.invalid"}
        seen = {"healthy": healthy, "with token": _post(base, "/internal/translate", body, {"X-Bridge-Token": BRIDGE_TOKEN}), "no token": _post(base, "/internal/translate", body, {}), "resolve with token": _post(base, "/internal/videos/resolve", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN})}
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    assert False, json.dumps(seen)
