"""Probe: the shape of an import-time SystemExit from server_config in a child."""
import os
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2] / "engine" / "server" / "api"


def test_probe():
    env = {key: val for key, val in os.environ.items() if key != "INTERACTION_RAW_RETENTION_DAYS"}
    env["INTERACTION_RAW_RETENTION_DAYS"] = "abc"
    run = subprocess.run([sys.executable, "-c", "import server_config"], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)
    print("rc:", run.returncode, "stdout:", repr(run.stdout), "stderr lines:", run.stderr.strip().splitlines())
