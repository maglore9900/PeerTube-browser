"""Probe: an Engine whose startup nprobe is 16 instead of DEFAULT_NPROBE; what do its log lines read?"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ENGINE_SERVER, ClientBackend, _free_port  # noqa: E402

LAUNCH = """
import runpy, sys
from pathlib import Path
server, nprobe = sys.argv[1], int(sys.argv[2])
sys.path[:0] = [str(Path(server).resolve().parents[1]), str(Path(server).resolve().parent)]
import data.ann
real = data.ann.set_nprobe
data.ann.set_nprobe = lambda index, _configured: real(index, nprobe)
sys.argv = [server] + sys.argv[3:]
runpy.run_path(server, run_name="__main__")
"""


def test_probe(tmp_path):
    log_path = tmp_path / "engine.log"
    log = open(log_path, "w")
    port = _free_port()
    started = time.time()
    proc = subprocess.Popen([str(ENGINE_PY), "-c", LAUNCH, str(ENGINE_SERVER), "16", "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], stdout=log, stderr=log, env={**__import__("os").environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": "x", "RECOMMENDATIONS_DEBUG": "1"})
    http = ClientBackend(f"http://127.0.0.1:{port}", log_path)
    try:
        while proc.poll() is None and time.time() < started + 120:
            try:
                if http.request("GET", "/api/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        print("healthy after", round(time.time() - started, 1), "s; poll", proc.poll())
        if proc.poll() is not None:
            log.flush()
            print(log_path.read_text(errors="replace")[-3000:])
        status, body = http.request("GET", f"/api/v1/search/videos?q={quote('linux')}&limit=1")
        print("search", status)
        seed = body["rows"][0]
        for route in ("/recommendations", "/videos/similar"):
            status, page = http.request("POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8", body={})
            print(route, status, len(page["rows"]))
        time.sleep(1)
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        log.close()
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            message = json.loads(line).get("message", "")
        except ValueError:
            print("RAW", line[:300])
            continue
        if any(key in message for key in ("nprobe", "ann_fallback", "] start ", "upnext", "done")):
            print("MSG", message[:300])
    assert False, "probe"
