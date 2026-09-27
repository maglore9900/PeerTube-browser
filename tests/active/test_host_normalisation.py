"""The Engine's port of the crawler's host normalisation, the crawler it ports, and the two jobs that read the JoinPeerTube hosts list through it.

- `data.moderation.normalize_host_token` returns the pinned value for every pair in `host_tokens.json`, and None where the pinned value is null.
- The crawler's compiled `normalizeHostToken` in `engine/crawler/dist/host-filters.js`, run under node, returns the same pinned values; a missing node or git, or a missing or stale dist, fails the test rather than skipping it.
- sync-whitelist.py's `fetch_hosts` reads `https://Tube.Example/` and `tube.example` as the one host `tube.example`, which `sync_hosts` stores as one row.
- Entries that normalise to None are dropped, and updater-worker.py's `fetch_join_hosts` returns the same host set as `fetch_hosts`; a list with no usable host still makes `fetch_hosts` raise.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from conftest import ROOT

SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host_token  # noqa: E402

FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"
PAIRS = json.loads(FIXTURE.read_text(encoding="utf-8"))

SRC = ROOT / "engine" / "crawler" / "src" / "host-filters.ts"
DIST = ROOT / "engine" / "crawler" / "dist" / "host-filters.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
JOBS_DIR = SERVER_DIR / "db" / "jobs"

NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""


@pytest.mark.parametrize("pair", PAIRS, ids=[repr(pair["input"]) for pair in PAIRS])
def test_python_port_returns_pinned_value(pair):
    assert normalize_host_token(pair["input"]) == pair["expected"]


def _git(git: str, *args: str) -> str:
    proc = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _dist_is_stale(git: str) -> bool:
    """Whether DIST predates SRC: by commit time when both are committed and clean, since a checkout sets mtimes arbitrarily; otherwise by time on disk."""
    dirty = _git(git, "status", "--porcelain", "--", str(SRC), str(DIST))
    src_committed = _git(git, "log", "-1", "--format=%ct", "--", str(SRC))
    dist_committed = _git(git, "log", "-1", "--format=%ct", "--", str(DIST))
    if dirty or not src_committed or not dist_committed:
        return SRC.stat().st_mtime > DIST.stat().st_mtime
    return int(src_committed) > int(dist_committed)


def test_crawler_dist_returns_pinned_values():
    node = shutil.which("node")
    assert node is not None, f"node is not on PATH; install Node.js, then {BUILD_HINT}"
    assert DIST.is_file(), f"{DIST} is missing; {BUILD_HINT}"
    git = shutil.which("git")
    assert git is not None, f"git is not on PATH, so whether {DIST} predates {SRC} cannot be told"
    assert not _dist_is_stale(git), f"{DIST} predates {SRC}; {BUILD_HINT}"
    inputs = [pair["input"] for pair in PAIRS]
    proc = subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "HOST_FILTERS_URL": DIST.as_uri()})
    assert proc.returncode == 0, f"node could not run {DIST}: {proc.stderr}; {BUILD_HINT}"
    wrong = [f"{pair['input']!r} -> {actual!r}, expected {pair['expected']!r}" for pair, actual in zip(PAIRS, json.loads(proc.stdout), strict=True) if actual != pair["expected"]]
    assert not wrong, f"{DIST} disagrees with {FIXTURE.name}: " + "; ".join(wrong)


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load_job("sync_whitelist_job", "sync-whitelist.py"), _load_job("updater_worker_job", "updater-worker.py")


def _payload_url(tmp_path, payload) -> str:
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_uri()


def test_sync_job_stores_one_spelling_per_host(jobs, tmp_path):
    sync, _ = jobs
    hosts = sync.fetch_hosts(_payload_url(tmp_path, ["https://Tube.Example/", "tube.example"]))
    assert hosts == {"tube.example"}
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        sync.ensure_whitelist_schema(conn)
        # sync_hosts returns (total, removed, added) despite its two-element annotation.
        assert sync.sync_hosts(conn, hosts) == (1, 0, 1)
        assert conn.execute(f"SELECT host FROM {sync.TABLE_NAME}").fetchall() == [("tube.example",)]
    finally:
        conn.close()


def test_jobs_drop_entries_that_normalise_to_none(jobs, tmp_path):
    sync, updater = jobs
    entries = ["", "   ", ".", "https://", "tube.example.", "https://Other.Example/videos"]
    url = _payload_url(tmp_path, {"data": [{"host": entry} for entry in entries]})
    assert sync.fetch_hosts(url) == {"tube.example", "other.example"}
    assert updater.fetch_join_hosts(url) == {"tube.example", "other.example"}


def test_sync_job_still_rejects_a_list_with_no_usable_host(jobs, tmp_path):
    sync, _ = jobs
    with pytest.raises(ValueError, match="^Whitelist contained no hosts\\.$"):
        sync.fetch_hosts(_payload_url(tmp_path, ["", "   ", ".", "https://"]))
