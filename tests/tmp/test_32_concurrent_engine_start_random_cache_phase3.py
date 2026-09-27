"""Eight Engines started at once against the checkout, with refresh off and no start lock, all answer `/api/health` 200 within 120 s while another connection holds the write lock on the checkout's random-cache.db.

- Controls: the session `engine` has left the checkout's cache non-empty but short of `DEFAULT_RANDOM_CACHE_SIZE`, and while the test holds `BEGIN IMMEDIATE` on it a `timeout=0` write fails "locked".
- None of the eight exits (the failure shows each one's log tail), and every one answers `/api/health` 200 within 120 s of the first launch.

An Engine start that writes the cache waits on the held lock and never becomes healthy, and a start that only skips the rebuild for a full cache writes this short one; one that reuses the non-empty cache only reads it. The Engines are real processes on the repo's dataset, each started as `server.py --host 127.0.0.1 --port <own port> --no-random-cache-refresh` with `ENGINE_INGEST_MODE=bridge`, the bridge token and `RECOMMENDATIONS_DEBUG=1`; the lock holder is a real second connection.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
API_DIR = ROOT / "engine" / "server" / "api"
for path in (ACTIVE_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# `engine` is imported so this file, outside tests/active, gets the session Engine that leaves the checkout's cache non-empty.
from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ClientBackend, _free_port, engine  # noqa: E402,F401
import server_config  # noqa: E402

RANDOM_CACHE_DB = ROOT / "engine" / "server" / "db" / "random-cache.db"
ENGINE_COUNT = 8
HEALTHY_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
LOG_TAIL_LINES = 20


def _log_tail(log_path: Path) -> str:
    """The last lines one Engine wrote to its log."""
    return "\n".join(log_path.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:])


def test_engines_starting_at_once_all_become_healthy(engine, tmp_path: Path) -> None:
    """Eight Engines launched at once with refresh off, no start lock and the checkout's non-empty cache write-locked by another connection: none exits and all answer `/api/health` 200 within 120 s."""
    cache = sqlite3.connect(f"file:{RANDOM_CACHE_DB}?mode=ro", uri=True)
    cached_rows = cache.execute("SELECT COUNT(*) FROM random_rowids").fetchone()[0]
    cache.close()
    # Control: a non-empty cache is the one a refresh-off start may reuse; an empty one is built, and that write would wait on the lock below.
    assert cached_rows > 0, "the session Engine left the checkout's random-cache.db empty"
    # Control: a full cache is already read-only for the old start, which skips its rebuild at `existing >= size`, so only a short one tells reuse from that skip.
    assert cached_rows < server_config.DEFAULT_RANDOM_CACHE_SIZE, f"the checkout's random-cache.db holds {cached_rows} rows, not short of {server_config.DEFAULT_RANDOM_CACHE_SIZE}, so the old start would not write it either"

    holder = sqlite3.connect(RANDOM_CACHE_DB, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    procs: list[subprocess.Popen] = []
    try:
        # Control: the lock is armed, so a start that writes the cache waits on it rather than finishing.
        control = sqlite3.connect(RANDOM_CACHE_DB, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                control.execute("DELETE FROM random_rowids WHERE 0")
        finally:
            control.close()

        env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
        # Distinct ports, so no Engine exits on a port another one took.
        ports: set[int] = set()
        while len(ports) < ENGINE_COUNT:
            ports.add(_free_port())
        engines: list[ClientBackend] = []
        log_paths: list[Path] = []
        deadline = time.time() + HEALTHY_WITHIN_SECONDS
        for port in sorted(ports):
            log_path = tmp_path / f"engine-{port}.log"
            with open(log_path, "w") as log:
                procs.append(subprocess.Popen(
                    [str(ENGINE_PY), str(ENGINE_SERVER), "--host", "127.0.0.1", "--port", str(port),
                     "--no-random-cache-refresh"],
                    env=env, stdout=log, stderr=log,
                ))
            engines.append(ClientBackend(f"http://127.0.0.1:{port}", log_path))
            log_paths.append(log_path)

        pending = set(range(ENGINE_COUNT))
        while pending and time.time() < deadline and all(proc.poll() is None for proc in procs):
            for index in sorted(pending):
                try:
                    if engines[index].request("GET", "/api/health")[0] == 200:
                        pending.discard(index)
                except OSError:
                    pass
            time.sleep(0.25)

        exited = {index: proc.returncode for index, proc in enumerate(procs) if proc.poll() is not None}
        assert exited == {}, "\n\n".join(f"Engine on {engines[index].base} exited {code}; log tail:\n{_log_tail(log_paths[index])}" for index, code in sorted(exited.items()))  # C1
        assert pending == set(), f"{len(pending)} of {ENGINE_COUNT} Engines not healthy within {HEALTHY_WITHIN_SECONDS}s: {[engines[index].base for index in sorted(pending)]}"  # C1
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        # A start still waiting on the held lock is inside sqlite's busy wait and does not act on SIGTERM until it returns, so a straggler is killed.
        stop_deadline = time.time() + STOP_WITHIN_SECONDS
        for proc in procs:
            try:
                proc.wait(timeout=max(0.0, stop_deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        holder.execute("ROLLBACK")
        holder.close()
