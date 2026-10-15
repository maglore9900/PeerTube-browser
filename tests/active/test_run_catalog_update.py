"""`scripts/run-catalog-update.sh` hands the updater worker `--increments 7` ahead of the operator's `--` flags, so `-- --increments 0` still forces a full crawl.

- `run-catalog-update.sh --foreground --skip-build -- --increments 0` hands the worker `--increments 7` then `--increments 0`, so the worker's real `parse_args` reads 0.
- Without `--` it hands `--increments 7` exactly once, and `parse_args` reads 7.

The script resolves the repo from its own location, so it is copied into a temp tree's `scripts/` with a recording stub `venv/bin/python3`, a stub `node` on PATH and an empty `engine/crawler/dist/`. The updater worker is loaded in-process from its file, only for `parse_args`.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CATALOG_SCRIPT = ROOT / "scripts" / "run-catalog-update.sh"
UPDATER_WORKER = ROOT / "engine" / "server" / "db" / "jobs" / "updater-worker.py"
BASH = shutil.which("bash", path="/usr/bin:/bin")

# Stands in for the venv interpreter run-catalog-update.sh picks: records the worker argv it was handed, one JSON line per call, and exits 0.
RECORDER = r'''
import json
import os
import sys

with open(os.environ["ARGV_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv) + "\n")
'''


@pytest.fixture(scope="module")
def worker():
    spec = importlib.util.spec_from_file_location("updater_worker_catalog_update", UPDATER_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(argv: list[str], option: str) -> list[str]:
    """Every value given to `option` in argv, in order."""
    return [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == option]


def _parse(worker, monkeypatch, worker_args: list[str], report: str):
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", *worker_args])
    try:
        return worker.parse_args()
    except SystemExit as exc:
        # An argparse refusal is SystemExit; read it as a red, not the end of the session.
        pytest.fail(f"updater-worker parse_args refused {worker_args} (exit {exc.code})\n{report}")


def _run_catalog_update(tmp_path: Path, extra: list[str]) -> tuple[list[str], str]:
    """Run a copy of run-catalog-update.sh `--foreground --skip-build <extra>` in a temp repo; return the one worker argv the recording interpreter received, and a report."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(CATALOG_SCRIPT, repo / "scripts" / "run-catalog-update.sh")
    venv_py = repo / "venv" / "bin" / "python3"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text(f"#!{sys.executable}\n{RECORDER}")
    venv_py.chmod(0o755)
    (repo / "engine" / "crawler" / "dist").mkdir(parents=True)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "node").write_text("#!/bin/sh\nexit 0\n")
    (stub_bin / "node").chmod(0o755)
    argv_log = tmp_path / "argv.log"
    env = {"PATH": f"{stub_bin}:/usr/bin:/bin", "HOME": str(tmp_path), "LC_ALL": "C", "ARGV_LOG": str(argv_log)}
    run = subprocess.run([BASH, str(repo / "scripts" / "run-catalog-update.sh"), "--foreground", "--skip-build", *extra], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    recorded = [json.loads(line) for line in argv_log.read_text().splitlines()] if argv_log.exists() else []
    report = f"exit={run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}\nrecorded:\n{recorded}"
    assert run.returncode == 0 and len(recorded) == 1, report  # control: the script ran the worker once through the recording interpreter
    argv = recorded[0]
    assert argv[:2] == [str(venv_py), f"{repo}/engine/server/db/jobs/updater-worker.py"], report  # control: the venv interpreter ran the repo's worker
    return argv, report


def test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker) -> None:
    """`run-catalog-update.sh --foreground --skip-build -- --increments 0` hands the worker `--increments 7` then `--increments 0`, and the worker's `parse_args` reads `increments == 0`."""
    argv, report = _run_catalog_update(tmp_path, ["--", "--increments", "0"])

    assert _values(argv, "--increments") == ["7", "0"], report  # 7 is passed, and ahead of the operator's flag rather than after it
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 0, report  # the operator's full-crawl override wins


def test_catalog_update_without_operator_flags_passes_increments_seven(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker) -> None:
    """`run-catalog-update.sh --foreground --skip-build` with no `--` hands the worker `--increments 7` once, and the worker's `parse_args` reads `increments == 7`."""
    argv, report = _run_catalog_update(tmp_path, [])

    assert _values(argv, "--increments") == ["7"], report  # 7 alone, not missing and not doubled
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 7, report
