"""`server.py --trending-db PATH`, run by the Engine's own interpreter, stops the start on a PATH that is not an existing SQLite file, and not on one that is:

- Control: `server.py --help` exits 0, and an unknown flag exits 2 with "unrecognized arguments" in stderr, so the absence of that phrase below means argparse accepted `--trending-db`.
- A missing `absent.db` and a 4 KB `junk.db` of non-SQLite bytes each make the start exit non-zero, with that path in stderr and not as argparse's "unrecognized arguments".
- After the failed start `absent.db` still does not exist, and `junk.db` holds exactly the bytes written to it.
- An existing SQLite `valid.db` gets past the check: the start, under the Engine start lock, reaches its `service.lifecycle` start within 120 s and is then terminated.

`_run`, `_free_port` and `_has_started` are the harness in `tests/active/test_server_config.py`, loaded by path so its tests are not collected here. A rejected start that wrongly gets past the check binds a free port and serves until `_run`'s 120 s timeout, which raises instead of hanging.
"""
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
# test_server_config does `from conftest import ...`, and tests/active/conftest.py is not on this directory's path.
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
_HARNESS_SPEC = importlib.util.spec_from_file_location("server_config_harness", ACTIVE_DIR / "test_server_config.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
_HARNESS_SPEC.loader.exec_module(harness)

SERVER_PY = harness.API_DIR / "server.py"
# Not the SQLite header ("SQLite format 3\0"), 4096 bytes.
JUNK = (b"not a sqlite database\n" * 200)[:4096]


def _argv(trending_db: Path) -> list[str]:
    return [str(harness.ENGINE_PY), str(SERVER_PY), "--host", "127.0.0.1", "--port", str(harness._free_port()), "--no-random-cache-refresh", "--trending-db", str(trending_db)]


def _start(trending_db: Path):
    return harness._run(_argv(trending_db), None)


def _starts_serving(trending_db: Path, log_path: Path) -> bool:
    """Start the Engine with --trending-db, logging to log_path, say whether it reached its lifecycle start, and stop it."""
    # This start does reach whitelist.db and the bind, so it takes the start lock like every other Engine start.
    with open(log_path, "w") as log, open(harness.ENGINE_START_LOCK, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        proc = subprocess.Popen(_argv(trending_db), cwd=harness.API_DIR, stdout=log, stderr=log)
        try:
            deadline = time.time() + harness.VARIANT_START_SECONDS
            while proc.poll() is None and time.time() < deadline and not harness._has_started(log_path):
                time.sleep(0.1)
            return harness._has_started(log_path)
        finally:
            proc.terminate()
            proc.wait(timeout=30)


def test_a_trending_db_that_is_missing_or_not_sqlite_stops_the_start_naming_it(tmp_path):
    ok = harness._run([str(harness.ENGINE_PY), str(SERVER_PY), "--help"], None)
    assert ok.returncode == 0, ok.stderr[-2000:]  # control: the entry point runs in this interpreter
    unknown = harness._run([str(harness.ENGINE_PY), str(SERVER_PY), "--no-such-flag", str(tmp_path / "x.db")], None)
    assert unknown.returncode == 2, unknown.stderr[-2000:]  # control: argparse's rejection reaches captured stderr...
    assert "unrecognized arguments" in unknown.stderr, unknown.stderr[-2000:]  # ...in the wording the C1 absence checks below look for

    missing = tmp_path / "absent.db"
    run = _start(missing)
    assert run.returncode != 0, run.stderr[-2000:]  # C1
    assert str(missing) in run.stderr, run.stderr[-2000:]  # C1
    # Observed before the flag existed: exit 2 with the path in stderr, quoted by argparse's rejection.
    assert "unrecognized arguments" not in run.stderr, run.stderr[-2000:]  # C1
    assert not missing.exists()  # C2

    junk = tmp_path / "junk.db"
    junk.write_bytes(JUNK)
    run = _start(junk)
    assert run.returncode != 0, run.stderr[-2000:]  # C1
    assert str(junk) in run.stderr, run.stderr[-2000:]  # C1
    assert "unrecognized arguments" not in run.stderr, run.stderr[-2000:]  # C1
    assert junk.read_bytes() == JUNK  # C2

    # The input that must pass, so a check that rejects every PATH goes red here.
    valid = tmp_path / "valid.db"
    conn = sqlite3.connect(valid)
    conn.execute("CREATE TABLE placeholder (x INTEGER)")
    conn.commit()
    conn.close()
    log_path = tmp_path / "valid_engine.log"
    assert _starts_serving(valid, log_path), log_path.read_text(errors="replace")[-2000:]  # C1
