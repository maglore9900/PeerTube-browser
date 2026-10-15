"""Every shipped launcher hands the updater worker `--increments 7`, and both installers' default updater timer fires daily at 20:00.

- `engine/install-updater-service.sh --mode prod --dry-run`, run directly or as the exact updater command the central `scripts/install-service.sh --mode prod --dry-run` echoes: the timer preview's only OnCalendar line is `OnCalendar=*-*-* 20:00:00`, the `ExecStart` worker argv gives `--increments` exactly once with `7`, and the worker's real `parse_args` reads `increments == 7`.
- The dev updater preview (`--with-updater-timer --force`): the worker argv ends `--max-retries 3 --increments 7`, `parse_args` reads 7, and the timer's only OnCalendar line is the same daily one.
- `scripts/run-catalog-update.sh --foreground --skip-build -- --increments 0` hands the worker `--increments 7` then `--increments 0`, so `parse_args` reads 0; without `--` it hands `--increments 7` once and `parse_args` reads 7.

The installers run through the `tests/active/test_install_updater_service.py` harness: a fake `--project-dir`, one stub behind systemctl, nginx and logger on PATH. `run-catalog-update.sh` is copied into a temp tree's `scripts/` (it resolves the repo from its own location) with a recording stub `venv/bin/python3`, a stub `node` on PATH and an empty `engine/crawler/dist/`. The updater worker is loaded in-process from its file, only for `parse_args`.
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
DAILY = "OnCalendar=*-*-* 20:00:00"

# The installer harness is the durable test's own (Tree, preview and argv readers), loaded as a module so its tests are not collected again here.
_spec = importlib.util.spec_from_file_location("install_updater_harness_phase4", ROOT / "tests" / "active" / "test_install_updater_service.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

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
    spec = importlib.util.spec_from_file_location("updater_worker_increments_phase4", harness.UPDATER_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse(worker, monkeypatch, worker_args: list[str], report: str):
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", *worker_args])
    try:
        return worker.parse_args()
    except SystemExit as exc:
        # An argparse refusal is SystemExit; read it as a red, not the end of the session.
        pytest.fail(f"updater-worker parse_args refused {worker_args} (exit {exc.code})\n{report}")


def _on_calendar(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("OnCalendar=")]


@pytest.mark.parametrize("via_central", [False, True], ids=["defaults", "central-argv"])
def test_prod_updater_unit_runs_one_increment_of_seven_daily_at_20(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker, via_central: bool) -> None:
    """A prod updater install `--dry-run`, with defaults or with the exact updater command the central installer's prod `--dry-run` echoes, exits 0; its timer preview's only OnCalendar line is `OnCalendar=*-*-* 20:00:00`, its `ExecStart` worker argv gives `--increments` once with `7`, and the worker's `parse_args` reads `increments == 7`."""
    tree = harness.Tree(tmp_path)
    script, args = harness.UPDATER_INSTALLER, ["--mode", "prod", "--service-user", tree.user]
    if via_central:
        central = tree.run(harness.CENTRAL_INSTALLER, ["--mode", "prod", "--service-user", tree.user])
        updaters = harness._sub_installer_argvs(central.stdout, "engine/install-updater-service.sh")
        assert central.returncode == 0 and [harness._values(argv, "--mode") for argv in updaters] == [["prod"]], harness._report(tree, central)  # control: the central prod dry-run echoes one prod updater command
        # Run the echoed command verbatim: the central installer passes its own --updater-oncalendar and --updater-flags, so its defaults are what reach the unit.
        script, args = Path(updaters[0][1]), updaters[0][2:]

    run = tree.run(script, args)
    report = harness._report(tree, run)
    previews = harness._previews(run.stdout)

    assert run.returncode == 0, report  # control
    assert _on_calendar(previews.get("timer", [])) == [DAILY], report  # C1: daily at 20:00, not the weekly `Fri *-*-* 20:00:00` left in place
    argv = harness._worker_argv(harness._exec_start(previews.get("service", []), report), report)
    assert argv[:2] == [tree.venv_py, f"{tree.real_project}/engine/server/db/jobs/updater-worker.py"], report  # control: the worker command
    assert harness._values(argv, "--increments") == ["7"], report  # C1: given once, as 7
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 7, report  # C1: the worker reads one increment of seven


def test_dev_updater_unit_runs_one_increment_of_seven_daily_at_20(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker) -> None:
    """A dev updater install `--dry-run --with-updater-timer --force` exits 0; its `ExecStart` worker argv ends `--max-retries 3 --increments 7`, the worker's `parse_args` reads `increments == 7`, and its timer preview's only OnCalendar line is `OnCalendar=*-*-* 20:00:00`."""
    tree = harness.Tree(tmp_path)

    run = tree.run(harness.UPDATER_INSTALLER, ["--mode", "dev", "--service-user", tree.user, "--with-updater-timer", "--force"])
    report = harness._report(tree, run)
    previews = harness._previews(run.stdout)

    assert run.returncode == 0, report  # control
    argv = harness._worker_argv(harness._exec_start(previews.get("service", []), report), report)
    assert harness._values(argv, "--mode") == ["dev"], report  # control: the dev unit
    assert argv[-4:] == ["--max-retries", "3", "--increments", "7"], report  # C1: appended after today's last flag
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 7, report  # C1
    assert _on_calendar(previews.get("timer", [])) == [DAILY], report  # C1: daily at 20:00, not weekly


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
    run = subprocess.run([harness.BASH, str(repo / "scripts" / "run-catalog-update.sh"), "--foreground", "--skip-build", *extra], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    recorded = [json.loads(line) for line in argv_log.read_text().splitlines()] if argv_log.exists() else []
    report = f"exit={run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}\nrecorded:\n{recorded}"
    assert run.returncode == 0 and len(recorded) == 1, report  # control: the script ran the worker once through the recording interpreter
    argv = recorded[0]
    assert argv[:2] == [str(venv_py), f"{repo}/engine/server/db/jobs/updater-worker.py"], report  # control: the venv interpreter ran the repo's worker
    return argv, report


def test_catalog_update_passes_increments_seven_ahead_of_operator_flags_so_increments_zero_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker) -> None:
    """`run-catalog-update.sh --foreground --skip-build -- --increments 0` hands the worker `--increments 7` then `--increments 0`, and the worker's `parse_args` reads `increments == 0`."""
    argv, report = _run_catalog_update(tmp_path, ["--", "--increments", "0"])

    assert harness._values(argv, "--increments") == ["7", "0"], report  # C2: 7 is passed, and ahead of the operator's flag rather than after it
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 0, report  # C2: the operator's full-crawl override wins


def test_catalog_update_without_operator_flags_passes_increments_seven(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker) -> None:
    """`run-catalog-update.sh --foreground --skip-build` with no `--` hands the worker `--increments 7` once, and the worker's `parse_args` reads `increments == 7`."""
    argv, report = _run_catalog_update(tmp_path, [])

    assert harness._values(argv, "--increments") == ["7"], report  # C2: 7 alone, not missing and not doubled
    assert _parse(worker, monkeypatch, argv[2:], report).increments == 7, report  # C2
