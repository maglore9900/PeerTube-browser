import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CRAWLER_DIR = ROOT / "engine" / "crawler"
SRC = CRAWLER_DIR / "src" / "host-filters.ts"
DIST = CRAWLER_DIR / "dist" / "host-filters.js"
BUILD_HINT = "cd engine/crawler && npm install && npm run build"
FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"
PAIRS = json.loads(FIXTURE.read_text(encoding="utf-8"))
VARIANT = os.environ.get("PROBE_VARIANT", "correct")
NODE_SCRIPT = """
import { readFileSync } from "node:fs";
const { normalizeHostToken } = await import(process.env.HOST_FILTERS_URL);
const inputs = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(inputs.map((value) => normalizeHostToken(value))));
"""


def _commit_time(git, path):
    out = subprocess.run([git, "log", "-1", "--format=%ct", "--", str(path)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    return int(out) if out else None


def _dist_staleness():
    if VARIANT == "mtime_only":
        return "older" if DIST.stat().st_mtime < SRC.stat().st_mtime else None
    git = shutil.which("git")
    if git is None:
        return "git is not on PATH, so the freshness of dist/host-filters.js cannot be checked"
    src_dirty = subprocess.run([git, "status", "--porcelain", "--", str(SRC)], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    src_time = _commit_time(git, SRC)
    dist_time = _commit_time(git, DIST)
    if VARIANT == "git_only":
        return "stale" if src_time and dist_time and src_time > dist_time else None
    if src_dirty or src_time is None or dist_time is None:
        if DIST.stat().st_mtime < SRC.stat().st_mtime:
            return "dist/host-filters.js is older on disk than the edited src/host-filters.ts"
        return None
    if VARIANT == "equal_is_stale" and src_time >= dist_time:
        return "stale"
    if src_time > dist_time:
        return "src/host-filters.ts was committed after dist/host-filters.js was last rebuilt and committed"
    return None


def test_crawler_dist_returns_pinned_values():
    node = shutil.which("node")
    if node is None:
        if VARIANT == "skip":
            pytest.skip("no node")
        pytest.fail(f"node is not on PATH; install Node.js, then run: {BUILD_HINT}")
    if VARIANT == "no_dist_check":
        hint = "cd engine/crawler && npm install && npm run build"
    elif not DIST.is_file():
        pytest.fail(f"{DIST} is missing; run: {BUILD_HINT}")
    stale = _dist_staleness()
    if stale:
        pytest.fail(f"{stale}; run: {BUILD_HINT}")
    inputs = [pair["input"] for pair in (PAIRS[:-1] if VARIANT == "subset" else PAIRS)]
    proc = subprocess.run([node, "--input-type=module", "-e", NODE_SCRIPT], input=json.dumps(inputs), capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "HOST_FILTERS_URL": DIST.as_uri()})
    assert proc.returncode == 0, proc.stderr
    if VARIANT == "no_compare":
        return
    assert dict(zip(inputs, json.loads(proc.stdout))) == {pair["input"]: pair["expected"] for pair in PAIRS if pair["input"] in inputs}
