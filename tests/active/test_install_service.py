"""In prod the central installer's Client command defaults `--engine-url` to the 127.0.0.1:7079 listener and its Engine command carries no `--host`/`--port`, while dev stays on 127.0.0.1:7171; all in `--dry-run`.

- `scripts/install-service.sh --dry-run` for `prod`, `dev` and `all` echoes one Client command per contour carrying exactly one `--engine-url`: 7079 for prod, 7171 for dev; the prod Engine command carries no `--host`/`--port`, the dev one `--host 127.0.0.1 --port 7171`.

The installer runs as a subprocess against a fake `--project-dir` (an executable stub `venv/bin/python3`, empty entrypoints, and copies of the sub-installers the central installer runs for default names). One stub stands behind systemctl, nginx and logger on PATH and logs every call.
"""
from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CENTRAL_INSTALLER = ROOT / "scripts" / "install-service.sh"
# The central installer runs these from --project-dir (for default unit names), so the fake tree carries the real ones.
CENTRAL_DEPENDENCIES = ("engine/install-engine-service.sh", "engine/engine-upstream.sh", "engine/install-updater-service.sh", "client/install-client-service.sh")
BASH = shutil.which("bash", path="/usr/bin:/bin")
LISTENER_URL = "http://127.0.0.1:7079"
DEV_ENGINE_URL = "http://127.0.0.1:7171"
# Per contour: the Client's --engine-url, then the Engine command's --host and --port values.
CENTRAL_EXPECTED = {"prod": (LISTENER_URL, [], []), "dev": (DEV_ENGINE_URL, ["127.0.0.1"], ["7171"])}

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
        for rel in CENTRAL_DEPENDENCIES:
            shutil.copy(ROOT / rel, self.project / rel)
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


def _values(argv: list[str], option: str) -> list[str]:
    """Every value given to `option` in argv, in order."""
    return [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == option]


def _sub_installer_argvs(stdout: str, installer: str) -> list[list[str]]:
    """The central installer's `[dry-run]` command lines that run `installer`, in order, as argv."""
    found = []
    for line in stdout.splitlines():
        if line.startswith("[dry-run] "):
            argv = shlex.split(line[len("[dry-run] "):])
            if len(argv) > 1 and argv[0] == "bash" and argv[1].endswith("/" + installer):
                found.append(argv)
    return found


@pytest.mark.parametrize("mode", ["prod", "dev", "all"])
def test_central_installer_dry_run_points_client_at_contour_engine(tmp_path: Path, mode: str) -> None:
    """A central install `--dry-run` echoes one Engine and one Client command per contour (prod then dev for `all`); the prod Client gets exactly `--engine-url http://127.0.0.1:7079` and the prod Engine no `--host`/`--port`, the dev Client `--engine-url http://127.0.0.1:7171` and the dev Engine `--host 127.0.0.1 --port 7171`."""
    tree = Tree(tmp_path)
    contours = ["prod", "dev"] if mode == "all" else [mode]

    run = tree.run(CENTRAL_INSTALLER, ["--mode", mode, "--service-user", tree.user])
    report = _report(tree, run)
    clients = _sub_installer_argvs(run.stdout, "client/install-client-service.sh")
    engines = _sub_installer_argvs(run.stdout, "engine/install-engine-service.sh")

    assert run.returncode == 0, report  # control
    assert [_values(argv, "--mode") for argv in clients] == [[contour] for contour in contours], report  # control: one Client command per contour, in order
    assert [_values(argv, "--mode") for argv in engines] == [[contour] for contour in contours], report  # control: one Engine command per contour, in order
    for contour, client, engine in zip(contours, clients, engines):
        engine_url, hosts, ports = CENTRAL_EXPECTED[contour]
        assert _values(client, "--engine-url") == [engine_url], f"contour={contour}\n{report}"  # prod through the 7079 listener, dev still 7171
        assert (_values(engine, "--host"), _values(engine, "--port")) == (hosts, ports), f"contour={contour}\n{report}"  # no --host/--port for the prod Engine; dev keeps 127.0.0.1:7171
