"""In prod the Client installer defaults `--engine-url` to the 127.0.0.1:7079 listener while dev stays on 7171, and an explicit `--engine-url` still wins; all in `--dry-run`.

- `client/install-client-service.sh --dry-run` reports `engine_url=` and an `ExecStart` ending `--engine-url http://127.0.0.1:7079 --publish-mode bridge` in prod and `…7171…` in dev; an explicit prod `--engine-url` is still the one written.

The installer runs as a subprocess against a fake `--project-dir` (an executable stub `venv/bin/python3` and empty entrypoints). One stub stands behind systemctl, nginx and logger on PATH and logs every call.
"""
from __future__ import annotations

import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT_INSTALLER = ROOT / "client" / "install-client-service.sh"
BASH = shutil.which("bash", path="/usr/bin:/bin")
LISTENER_URL = "http://127.0.0.1:7079"
DEV_ENGINE_URL = "http://127.0.0.1:7171"

# One stub behind systemctl, nginx and logger (symlinks; the basename picks the role). It logs every call to $STUB_DIR/calls.log and changes nothing.
STUB = r'''
import os
import sys
from pathlib import Path

NAME = os.path.basename(sys.argv[0])
with open(Path(os.environ["STUB_DIR"]) / "calls.log", "a") as handle:
    handle.write(" ".join([NAME] + sys.argv[1:]) + "\n")
if NAME == "systemctl" and "is-active" in sys.argv[1:]:
    print("inactive")
    sys.exit(3)
sys.exit(0)
'''


class Tree:
    """A fake project, a tmp snippet path, and the stubs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "project"
        venv_py = self.project / "venv" / "bin" / "python3"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("#!/bin/sh\nexit 0\n")
        venv_py.chmod(0o755)
        for rel in ("engine/server/api/server.py", "engine/server/db/jobs/updater-worker.py", "client/backend/server.py"):
            (self.project / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.project / rel).write_text("")
        self.real_project = os.path.realpath(self.project)
        self.venv_py = f"{self.real_project}/venv/bin/python3"
        (root / "nginx").mkdir()
        self.snippet = root / "nginx" / "peertube-engine-upstream.conf"
        self.stub = root / "stub"
        self.stub.mkdir()
        stub_py = root / "stubbin" / "stub.py"
        stub_py.parent.mkdir()
        stub_py.write_text(f"#!{sys.executable}\n{STUB}")
        stub_py.chmod(0o755)
        self.bin = root / "bin"
        self.bin.mkdir()
        for name in ("systemctl", "nginx", "logger"):
            (self.bin / name).symlink_to(stub_py)
        # The installers take `command -v systemctl`, which is this unresolved stub path (observed in a dry-run probe).
        self.systemctl = str(self.bin / "systemctl")
        self.user = pwd.getpwuid(os.getuid()).pw_name

    def run(self, script: Path, args: list[str], snippet_override: bool = True) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root), "LC_ALL": "C", "STUB_DIR": str(self.stub)}
        if snippet_override:
            env["PEERTUBE_ENGINE_UPSTREAM_SNIPPET"] = str(self.snippet)
        return subprocess.run([BASH, str(script), *args, "--dry-run", "--project-dir", str(self.project)], cwd=self.root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def calls(self) -> list[str]:
        path = self.stub / "calls.log"
        return path.read_text().splitlines() if path.exists() else []


def _report(tree: Tree, run: subprocess.CompletedProcess) -> str:
    return f"exit={run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}\ncalls:\n" + "\n".join(tree.calls())


def _previews(stdout: str) -> dict[str, list[str]]:
    """The lines under each `----- <name> preview -----` or `----- updater <name> preview (<path>) -----` marker, up to the next marker."""
    previews: dict[str, list[str]] = {}
    name = None
    for line in stdout.splitlines():
        match = re.fullmatch(r"----- (?:updater )?(\w+) preview(?: \(.*\))? -----", line)
        if match:
            name = match.group(1)
            previews[name] = []
        elif name is not None:
            previews[name].append(line)
    return previews


def _exec_start(lines: list[str], report: str) -> str:
    found = [line[len("ExecStart="):] for line in lines if line.startswith("ExecStart=")]
    assert len(found) == 1, report  # control: one ExecStart to read
    return found[0]


def _values(argv: list[str], option: str) -> list[str]:
    """Every value given to `option` in argv, in order."""
    return [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == option]


@pytest.mark.parametrize(("mode", "port", "engine_url"), [("prod", 7072, LISTENER_URL), ("dev", 7172, DEV_ENGINE_URL)], ids=["prod", "dev"])
def test_client_installer_dry_run_defaults_engine_url_per_contour(tmp_path: Path, mode: str, port: int, engine_url: str) -> None:
    """With no `--engine-url`, a Client install `--dry-run` reports `engine_url=` and writes an `ExecStart` whose `--engine-url` is http://127.0.0.1:7079 in prod and http://127.0.0.1:7171 in dev, the rest of the line as today."""
    tree = Tree(tmp_path)

    run = tree.run(CLIENT_INSTALLER, ["--mode", mode, "--service-user", tree.user])
    report = _report(tree, run)

    assert run.returncode == 0, report  # control
    assert re.findall(r"^\s*engine_url=(\S*)\s*$", run.stdout, re.M) == [engine_url], report
    exec_start = _exec_start(_previews(run.stdout).get("unit", []), report)
    assert exec_start == f"{tree.venv_py} {tree.real_project}/client/backend/server.py --host 127.0.0.1 --port {port} --engine-url {engine_url} --publish-mode bridge", report  # the unit the Client runs with


def test_client_installer_prod_dry_run_keeps_explicit_engine_url(tmp_path: Path) -> None:
    """A prod Client install `--dry-run --engine-url http://127.0.0.1:7075` (a URL no version of the installer defaults to) writes that URL, once, into `ExecStart`."""
    tree = Tree(tmp_path)

    run = tree.run(CLIENT_INSTALLER, ["--mode", "prod", "--service-user", tree.user, "--engine-url", "http://127.0.0.1:7075"])
    report = _report(tree, run)

    assert run.returncode == 0, report  # control
    exec_start = _exec_start(_previews(run.stdout).get("unit", []), report)
    assert _values(shlex.split(exec_start), "--engine-url") == ["http://127.0.0.1:7075"], report  # 7079 is the prod default, not forced over an explicit URL
