"""In prod the Client installer, and the central installer's Client command, default `--engine-url` to the 127.0.0.1:7079 listener while dev stays on 7171; the prod updater installer's unit hands the worker `--engine-upstream-snippet` and its sudoers rule is exactly the four instance stop/start entries, while dev keeps its single-name rule; all in `--dry-run`.

- `client/install-client-service.sh --dry-run` reports `engine_url=` and an `ExecStart` ending `--engine-url http://127.0.0.1:7079 --publish-mode bridge` in prod and `…7171…` in dev; an explicit prod `--engine-url` is still the one written.
- `scripts/install-service.sh --dry-run` for `prod`, `dev` and `all` echoes one Client command per contour carrying exactly one `--engine-url`: 7079 for prod, 7171 for dev; the prod Engine command carries no `--host`/`--port`, the dev one `--host 127.0.0.1 --port 7171`.
- `engine/install-updater-service.sh --mode prod --dry-run`, with defaults or the argv the central installer passes, and with the snippet override set or unset: the sudoers preview is exactly `<user> ALL=(root) NOPASSWD: <systemctl> stop peertube-engine@7070, <systemctl> stop peertube-engine@7071, <systemctl> start peertube-engine@7070, <systemctl> start peertube-engine@7071`, the same four commands the worker's own `systemctl_cmd` builds under `sudo -n`; the `ExecStart` worker argv names the snippet (the override, else /etc/nginx/peertube-engine-upstream.conf) once, and the worker's real `parse_args` reads it with sudo on and systemctl not skipped.
- The dev updater preview, with the override set, keeps today's single-name sudoers rule and today's `ExecStart` exactly, with no snippet.

The repo's scripts run as subprocesses against a fake `--project-dir` (an executable stub `venv/bin/python3`, empty entrypoints, and copies of the sub-installers the central installer runs for default names). One stub stands behind systemctl, nginx and logger on PATH and logs every call. The updater worker is loaded in-process from its file, only for `parse_args`, `systemctl_cmd` and `engine_instance_unit`.
"""
from __future__ import annotations

import importlib.util
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
CENTRAL_INSTALLER = ROOT / "scripts" / "install-service.sh"
UPDATER_INSTALLER = ROOT / "engine" / "install-updater-service.sh"
UPDATER_WORKER = ROOT / "engine" / "server" / "db" / "jobs" / "updater-worker.py"
# The central installer runs these from --project-dir (for default unit names), so the fake tree carries the real ones.
CENTRAL_DEPENDENCIES = ("engine/install-engine-service.sh", "engine/engine-upstream.sh", "engine/install-updater-service.sh", "client/install-client-service.sh")
BASH = shutil.which("bash", path="/usr/bin:/bin")
PROD_SNIPPET = "/etc/nginx/peertube-engine-upstream.conf"
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


@pytest.fixture(scope="module")
def worker():
    spec = importlib.util.spec_from_file_location("updater_worker_phase4", UPDATER_WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _worker_argv(exec_start: str, report: str) -> list[str]:
    """The worker command inside the updater unit's `/usr/bin/bash -lc 'set -euo pipefail; <command>'`, as argv."""
    wrapper = shlex.split(exec_start)
    assert wrapper[:2] == ["/usr/bin/bash", "-lc"] and len(wrapper) == 3, report  # control: today's wrapper
    prelude, _, command = wrapper[2].partition("; ")
    assert prelude == "set -euo pipefail", report  # control
    return shlex.split(command)


def _sub_installer_argvs(stdout: str, installer: str) -> list[list[str]]:
    """The central installer's `[dry-run]` command lines that run `installer`, in order, as argv."""
    found = []
    for line in stdout.splitlines():
        if line.startswith("[dry-run] "):
            argv = shlex.split(line[len("[dry-run] "):])
            if len(argv) > 1 and argv[0] == "bash" and argv[1].endswith("/" + installer):
                found.append(argv)
    return found


@pytest.mark.parametrize(("mode", "port", "engine_url"), [("prod", 7072, LISTENER_URL), ("dev", 7172, DEV_ENGINE_URL)], ids=["prod", "dev"])
def test_client_installer_dry_run_defaults_engine_url_per_contour(tmp_path: Path, mode: str, port: int, engine_url: str) -> None:
    """With no `--engine-url`, a Client install `--dry-run` reports `engine_url=` and writes an `ExecStart` whose `--engine-url` is http://127.0.0.1:7079 in prod and http://127.0.0.1:7171 in dev, the rest of the line as today."""
    tree = Tree(tmp_path)

    run = tree.run(CLIENT_INSTALLER, ["--mode", mode, "--service-user", tree.user])
    report = _report(tree, run)

    assert run.returncode == 0, report  # control
    assert re.findall(r"^\s*engine_url=(\S*)\s*$", run.stdout, re.M) == [engine_url], report  # C1
    exec_start = _exec_start(_previews(run.stdout).get("unit", []), report)
    assert exec_start == f"{tree.venv_py} {tree.real_project}/client/backend/server.py --host 127.0.0.1 --port {port} --engine-url {engine_url} --publish-mode bridge", report  # C1: the unit the Client runs with


def test_client_installer_prod_dry_run_keeps_explicit_engine_url(tmp_path: Path) -> None:
    """A prod Client install `--dry-run --engine-url http://127.0.0.1:7075` (a URL no version of the installer defaults to) writes that URL, once, into `ExecStart`."""
    tree = Tree(tmp_path)

    run = tree.run(CLIENT_INSTALLER, ["--mode", "prod", "--service-user", tree.user, "--engine-url", "http://127.0.0.1:7075"])
    report = _report(tree, run)

    assert run.returncode == 0, report  # control
    exec_start = _exec_start(_previews(run.stdout).get("unit", []), report)
    assert _values(shlex.split(exec_start), "--engine-url") == ["http://127.0.0.1:7075"], report  # C1: 7079 is the prod default, not forced over an explicit URL


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
        assert _values(client, "--engine-url") == [engine_url], f"contour={contour}\n{report}"  # C1: prod through the 7079 listener, dev still 7171
        assert (_values(engine, "--host"), _values(engine, "--port")) == (hosts, ports), f"contour={contour}\n{report}"  # C1: no --host/--port for the prod Engine; dev keeps 127.0.0.1:7171


@pytest.mark.parametrize("snippet_override", [True, False], ids=["snippet-override", "default-snippet"])
@pytest.mark.parametrize("via_central", [False, True], ids=["defaults", "central-argv"])
def test_updater_installer_prod_dry_run_passes_snippet_and_allows_only_instance_stop_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker, via_central: bool, snippet_override: bool) -> None:
    """A prod updater install `--dry-run`, with defaults or with the exact updater command the central installer's prod `--dry-run` echoes (its `--updater-flags`, names and OnCalendar included), and with the snippet override set or unset, exits 0; its sudoers preview is exactly the four `stop|start peertube-engine@7070|7071` entries, which are the commands the worker's `systemctl_cmd` runs under `sudo -n`; its `ExecStart` hands the worker `--engine-upstream-snippet` once (the override, else /etc/nginx/peertube-engine-upstream.conf), and the worker's `parse_args` reads that path with sudo on, systemctl not skipped and the stub systemctl."""
    tree = Tree(tmp_path)
    snippet = str(tree.snippet) if snippet_override else PROD_SNIPPET
    systemctl = tree.systemctl
    expected_rule = f"{tree.user} ALL=(root) NOPASSWD: {systemctl} stop peertube-engine@7070, {systemctl} stop peertube-engine@7071, {systemctl} start peertube-engine@7070, {systemctl} start peertube-engine@7071"
    worker_commands = {" ".join(worker.systemctl_cmd(systemctl_bin=systemctl, service_name=worker.engine_instance_unit(port), action=action, use_sudo=True)[2:]) for action in ("stop", "start") for port in (7070, 7071)}
    script, args = UPDATER_INSTALLER, ["--mode", "prod", "--service-user", tree.user]
    if via_central:
        central = tree.run(CENTRAL_INSTALLER, ["--mode", "prod", "--service-user", tree.user], snippet_override=snippet_override)
        updaters = _sub_installer_argvs(central.stdout, "engine/install-updater-service.sh")
        assert central.returncode == 0 and [_values(argv, "--mode") for argv in updaters] == [["prod"]], _report(tree, central)  # control: the central prod dry-run echoes one prod updater command
        # Run the echoed command verbatim (the fake tree's copy of the real installer), so a snippet carried only in the updater's own UPDATER_FLAGS default is lost here as it would be in a central install.
        script, args = Path(updaters[0][1]), updaters[0][2:]

    run = tree.run(script, args, snippet_override=snippet_override)
    report = _report(tree, run)
    previews = _previews(run.stdout)

    assert run.returncode == 0, report  # control
    assert set(expected_rule.split("NOPASSWD: ", 1)[1].split(", ")) == worker_commands, report  # control: the expected rule is the argv the worker runs under sudo -n, no `.service` suffix
    assert [line for line in previews.get("sudoers", []) if line.strip()] == [expected_rule], report  # C2: exactly the four instance stop/start entries, nothing broader
    argv = _worker_argv(_exec_start(previews.get("service", []), report), report)
    assert argv[:2] == [tree.venv_py, f"{tree.real_project}/engine/server/db/jobs/updater-worker.py"], report  # control: the worker command
    assert _values(argv, "--engine-upstream-snippet") == [snippet], report  # C2
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", *argv[2:]])
    args = worker.parse_args()
    assert (args.engine_upstream_snippet, args.skip_systemctl, args.systemctl_use_sudo, args.systemctl_bin) == (snippet, False, True, systemctl), report  # C2: the worker reads the snippet and stops/starts through the sudo rule's systemctl


def test_updater_installer_dev_dry_run_keeps_single_name_rule(tmp_path: Path) -> None:
    """A dev updater install `--dry-run --with-updater-timer --force`, with the snippet override set, exits 0 with today's single-name sudoers rule for `peertube-engine-dev` and today's `ExecStart` exactly, with no `--engine-upstream-snippet`."""
    tree = Tree(tmp_path)
    systemctl = tree.systemctl

    run = tree.run(UPDATER_INSTALLER, ["--mode", "dev", "--service-user", tree.user, "--with-updater-timer", "--force"])
    report = _report(tree, run)
    previews = _previews(run.stdout)

    assert run.returncode == 0, report  # control
    assert [line for line in previews.get("sudoers", []) if line.strip()] == [f"{tree.user} ALL=(root) NOPASSWD: {systemctl} stop peertube-engine-dev, {systemctl} start peertube-engine-dev"], report  # C2: dev keeps its single-name rule
    assert _exec_start(previews.get("service", []), report) == f"/usr/bin/bash -lc 'set -euo pipefail; {tree.venv_py} {tree.real_project}/engine/server/db/jobs/updater-worker.py --mode dev --service-name peertube-engine-dev --systemctl-bin {systemctl} --systemctl-use-sudo --gpu --skip-local-dead --concurrency 5 --timeout-ms 15000 --max-retries 3'", report  # C2: dev unchanged, no snippet even with the override set
