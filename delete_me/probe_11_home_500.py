from __future__ import annotations

import fcntl
import os
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, WHITELIST_DB, ClientBackend, _free_port  # noqa: E402

# Patches the statement budget before server.py and its handlers import it, then runs server.py as __main__.
LAUNCH = textwrap.dedent(
    """
    import runpy, sys
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/.."]
    import server_config
    server_config.DEFAULT_STATEMENT_TIMEOUT_SECONDS = float(sys.argv[2])
    sys.argv = [sys.argv[3]] + sys.argv[4:]
    runpy.run_path(sys.argv[0], run_name="__main__")
    """
)


def _start(tmp_path, budget):
    log_path = tmp_path / f"engine-{budget}.log"
    log = open(log_path, "w")
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    with open(ENGINE_START_LOCK, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        port = _free_port()
        proc = subprocess.Popen([str(ENGINE_PY), "-c", LAUNCH, str(ENGINE_SERVER.parent), str(budget), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log, cwd=str(ENGINE_SERVER.parent))
        http = ClientBackend(f"http://127.0.0.1:{port}", log_path)
        deadline = time.time() + 120
        while proc.poll() is None and time.time() < deadline:
            try:
                if http.request("GET", "/api/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
    assert proc.poll() is None, log_path.read_text()[-4000:]
    return proc, log, http, log_path


def _likes():
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    rows = conn.execute("SELECT v.video_uuid, v.instance_domain FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain WHERE v.video_uuid IS NOT NULL LIMIT 5").fetchall()
    conn.close()
    return [{"uuid": uuid, "host": host} for uuid, host in rows]


def _run(tmp_path, budget, calls):
    proc, log, http, log_path = _start(tmp_path, budget)
    try:
        likes = _likes()
        for index in range(calls):
            started = time.monotonic()
            status, body = http.request("POST", "/recommendations", body={"likes": likes})
            elapsed = time.monotonic() - started
            print(f"PROBE budget={budget} call={index} status={status} elapsed={elapsed:.3f} body={body if status != 200 else len(body['rows'])}")
        for line in log_path.read_text().splitlines():
            if "ERROR" in line or "interrupted" in line or "statement.timeout" in line:
                print(f"PROBE LOG budget={budget}", line[:3000])
    finally:
        proc.terminate()
        proc.wait(timeout=30)
        log.close()


def test_probe_default_budget(tmp_path):
    _run(tmp_path, 5.0, 5)


def test_probe_tiny_budget(tmp_path):
    _run(tmp_path, 0.001, 2)
