"""Probe: what the installers' dry-run and run-catalog-update.sh actually emit, today and with the target flags forced in."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("harness_probe", ROOT / "tests" / "active" / "test_install_updater_service.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def _show(label, tree, run):
    previews = H._previews(run.stdout)
    print(f"=== {label} exit={run.returncode}")
    print("service:", previews.get("service"))
    print("timer:", previews.get("timer"))
    if run.returncode != 0:
        print(run.stderr)


def test_installers(tmp_path, monkeypatch):
    for label, script, args in [
        ("prod-today", H.UPDATER_INSTALLER, ["--mode", "prod"]),
        ("dev-today", H.UPDATER_INSTALLER, ["--mode", "dev", "--with-updater-timer", "--force"]),
        ("prod-forced", H.UPDATER_INSTALLER, ["--mode", "prod", "--updater-oncalendar", "*-*-* 20:00:00", "--updater-flags", "--gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3 --increments 7"]),
    ]:
        root = tmp_path / label
        root.mkdir()
        tree = H.Tree(root)
        run = tree.run(script, [*args, "--service-user", tree.user])
        _show(label, tree, run)
    root = tmp_path / "central"
    root.mkdir()
    tree = H.Tree(root)
    central = tree.run(H.CENTRAL_INSTALLER, ["--mode", "prod", "--service-user", tree.user])
    print("central exit", central.returncode, H._sub_installer_argvs(central.stdout, "engine/install-updater-service.sh"))
    spec2 = importlib.util.spec_from_file_location("worker_probe", H.UPDATER_WORKER)
    worker = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(worker)
    run = tree.run(H.UPDATER_INSTALLER, ["--mode", "prod", "--service-user", tree.user, "--updater-flags", "--gpu --max-retries 3 --increments 7"])
    argv = H._worker_argv(H._exec_start(H._previews(run.stdout)["service"], ""), "")
    print("forced argv", argv)
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", *argv[2:]])
    print("parsed increments", worker.parse_args().increments)


RECORDER = r'''
import json
import os
import sys
with open(os.environ["ARGV_LOG"], "a") as handle:
    handle.write(json.dumps(sys.argv) + "\n")
'''


def test_catalog_script(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "run-catalog-update.sh", repo / "scripts" / "run-catalog-update.sh")
    py = repo / "venv" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    py.write_text(f"#!{sys.executable}\n{RECORDER}")
    py.chmod(0o755)
    (repo / "engine" / "crawler" / "dist").mkdir(parents=True)
    stubbin = tmp_path / "bin"
    stubbin.mkdir()
    (stubbin / "node").write_text("#!/bin/sh\nexit 0\n")
    (stubbin / "node").chmod(0o755)
    log = tmp_path / "argv.log"
    env = {"PATH": f"{stubbin}:/usr/bin:/bin", "HOME": str(tmp_path), "LC_ALL": "C", "ARGV_LOG": str(log)}
    for extra in (["--", "--increments", "0"], [], ["--", "--increments", "7", "--increments", "0"]):
        run = subprocess.run([H.BASH, str(repo / "scripts" / "run-catalog-update.sh"), "--foreground", "--skip-build", *extra], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        print("=== extra", extra, "exit", run.returncode)
        print(run.stdout, run.stderr)
    print("log:")
    for line in log.read_text().splitlines():
        print(json.loads(line))
    spec2 = importlib.util.spec_from_file_location("worker_probe2", H.UPDATER_WORKER)
    worker = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(worker)
    for line in log.read_text().splitlines():
        sys.argv = ["updater-worker.py", *json.loads(line)[2:]]
        print("parsed", worker.parse_args().increments)
    print("which python3 on PATH:", shutil.which("python3", path=env["PATH"]))
    print("pixi present:", os.path.exists(repo / ".pixi"))
