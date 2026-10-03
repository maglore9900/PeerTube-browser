from __future__ import annotations

import fcntl
import importlib.util
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
_SPEC = importlib.util.spec_from_file_location("server_config_harness_probe", ACTIVE_DIR / "test_server_config.py")
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)
SERVER_PY = harness.API_DIR / "server.py"


def test_probe(tmp_path):
    valid = tmp_path / "valid.db"
    conn = sqlite3.connect(valid)
    conn.execute("CREATE TABLE placeholder (x INTEGER)")
    conn.commit()
    conn.close()
    print("header", valid.read_bytes()[:16])
    log_path = tmp_path / "engine.log"
    t0 = time.time()
    with open(log_path, "w") as log, open(harness.ENGINE_START_LOCK, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        print("lock after", time.time() - t0)
        proc = subprocess.Popen([str(harness.ENGINE_PY), str(SERVER_PY), "--host", "127.0.0.1", "--port", str(harness._free_port()), "--no-random-cache-refresh"], cwd=harness.API_DIR, stdout=log, stderr=log)
        try:
            deadline = time.time() + harness.VARIANT_START_SECONDS
            while proc.poll() is None and time.time() < deadline and not harness._has_started(log_path):
                time.sleep(0.1)
            print("started", harness._has_started(log_path), "poll", proc.poll(), "elapsed", time.time() - t0)
        finally:
            proc.terminate()
            print("rc after terminate", proc.wait(timeout=30))
    text = log_path.read_text(errors="replace")
    print("LOG HEAD", text[:1500])
    print("LOG TAIL", text[-1500:])
    # The same start with the flag, on today's code.
    run = subprocess.run([str(harness.ENGINE_PY), str(SERVER_PY), "--host", "127.0.0.1", "--port", "1", "--no-random-cache-refresh", "--trending-db", str(valid)], cwd=harness.API_DIR, capture_output=True, text=True, timeout=120)
    print("flag rc", run.returncode, "stderr", run.stderr[-500:])
