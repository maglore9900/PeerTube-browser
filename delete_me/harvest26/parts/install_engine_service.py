"""The prod Engine installer previews the `peertube-engine@.service` template, the snippet and the 127.0.0.1:7079 listener without changing the port an existing snippet names, in `--dry-run`, which writes nothing; dev keeps its single unit.

- A prod install `--dry-run` exits 0 and reports `unit=/etc/systemd/system/peertube-engine@.service`. Its unit preview is today's prod unit with `ExecStart=… --host 127.0.0.1 --port %i`. Its listener preview's only `listen` is `127.0.0.1:7079`, and it includes the snippet path and proxies to `peertube_engine`. With no snippet it reports `active_port=7070 snippet=new`; with each accepted snippet of tests/active/upstream_snippet_cases.json it reports that port and `snippet=existing`, and the snippet preview names the same port. The temp tree, the host's unit and nginx paths and the stubs' state are unchanged; a missing snippet is not created.
- Every rejected snippet of the shared cases, and `--port 7070` in prod, exit 1 and change nothing. The same tree with a valid snippet, or without `--port`, previews.
- The dev install `--dry-run`, with and without `--host 127.0.0.1 --port 7171`, prints exactly today's preview (`--port 7171`, `peertube-engine-dev.service`).

The repo's installer runs as a subprocess against a fake `--project-dir` (an executable stub `venv/bin/python3`, an empty `server.py`). `PEERTUBE_ENGINE_UPSTREAM_SNIPPET` points into tmp. One stub stands behind systemctl, nginx and logger on PATH and logs every call.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "engine" / "install-engine-service.sh"
CASES_FILE = ROOT / "tests" / "active" / "upstream_snippet_cases.json"
BASH = shutil.which("bash", path="/usr/bin:/bin")
TEMPLATE = "/etc/systemd/system/peertube-engine@.service"
LISTENER = "/etc/nginx/conf.d/peertube-engine-internal.conf"
# Host paths a prod install manages; a dry-run leaves each as it found it.
HOST_PATHS = (TEMPLATE, LISTENER, "/etc/nginx/peertube-engine-upstream.conf", "/etc/systemd/system/peertube-engine.service")
SYSTEMCTL_MUTATING = {"start", "stop", "restart", "try-restart", "reload-or-restart", "kill", "reload", "enable", "disable", "daemon-reload", "reset-failed", "mask", "unmask", "link", "preset"}
CASES = json.loads(CASES_FILE.read_text(encoding="utf-8"))
ACCEPTED = [pytest.param(case, id=case["id"]) for case in CASES if case["port"] is not None]
REJECTED = [pytest.param(case, id=case["id"]) for case in CASES if case["port"] is None]

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


def snippet_bytes(port: int) -> bytes:
    # engine-upstream.sh's snippet_text, written out here rather than taken from the library under test.
    return f"upstream peertube_engine {{\n    server 127.0.0.1:{port};\n}}\n".encode()


def unit_text(mode: str, user: str, project: str, port: str) -> str:
    # Today's unit as install-engine-service.sh writes it (observed in a dry-run probe); prod's template differs only in `--port %i`.
    return f"[Unit]\nDescription=PeerTube Engine ({mode})\nAfter=network.target\n\n[Service]\nType=simple\nUser={user}\nWorkingDirectory={project}\nEnvironment=PYTHONUNBUFFERED=1\nEnvironment=ENGINE_INGEST_MODE=bridge\nEnvironmentFile=-{project}/.env.bridge\nExecStart={project}/venv/bin/python3 {project}/engine/server/api/server.py --host 127.0.0.1 --port {port}\nRestart=on-failure\nTimeoutStopSec=20\n\n[Install]\nWantedBy=multi-user.target\n"


class Tree:
    """A fake project, an `nginx/` dir for the snippet, and the stubs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "project"
        venv_py = self.project / "venv" / "bin" / "python3"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("#!/bin/sh\nexit 0\n")
        venv_py.chmod(0o755)
        server_py = self.project / "engine" / "server" / "api" / "server.py"
        server_py.parent.mkdir(parents=True)
        server_py.write_text("")
        # Where a deploy lock would land, so a dry-run that takes one shows up in the snapshot.
        (self.project / "engine" / "server" / "db").mkdir()
        self.real_project = os.path.realpath(self.project)
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
        self.user = pwd.getpwuid(os.getuid()).pw_name

    def run(self, script: Path, args: list[str]) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root), "LC_ALL": "C", "STUB_DIR": str(self.stub), "PEERTUBE_ENGINE_UPSTREAM_SNIPPET": str(self.snippet)}
        return subprocess.run([BASH, str(script), *args, "--dry-run", "--project-dir", str(self.project)], cwd=self.root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def install(self, mode: str, *extra: str) -> subprocess.CompletedProcess:
        return self.run(INSTALLER, ["--mode", mode, "--service-user", self.user, *extra])

    def snapshot(self) -> dict:
        """Every path under the tree outside the stub's own state, with its mode and bytes."""
        return {str(path.relative_to(self.root)): (path.lstat().st_mode, path.read_bytes() if path.is_file() and not path.is_symlink() else None) for path in sorted(self.root.rglob("*")) if self.stub not in path.parents and path != self.stub}

    def calls(self) -> list[str]:
        path = self.stub / "calls.log"
        return path.read_text().splitlines() if path.exists() else []


def _host_state() -> dict:
    return {path: (os.lstat(path).st_mtime_ns, os.lstat(path).st_size) if os.path.lexists(path) else None for path in HOST_PATHS}


def _mutations(calls: list[str]) -> list[str]:
    found = []
    for call in calls:
        words = call.split()
        actions = [word for word in words[1:] if not word.startswith("-")]
        if words[0] == "systemctl" and actions and actions[0] in SYSTEMCTL_MUTATING:
            found.append(call)
        elif words[0] == "nginx" and "-s" in words:
            found.append(call)
    return found


def _report(tree: Tree, run: subprocess.CompletedProcess) -> str:
    return f"exit={run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}\ncalls:\n" + "\n".join(tree.calls())


def _sections(stdout: str) -> dict[str, str]:
    """The text under each `----- <name> preview -----` marker, up to the next marker."""
    sections: dict[str, str] = {}
    name = None
    for line in stdout.splitlines(keepends=True):
        match = re.fullmatch(r"----- (\w+) preview -----\n?", line)
        if match:
            name = match.group(1)
            sections[name] = ""
        elif name is not None:
            sections[name] += line
    return sections


def _statements(nginx_text: str) -> list[str]:
    """nginx directives with comments dropped and whitespace collapsed, so a second `listen` on any line or inside a block is counted."""
    text = re.sub(r"#[^\n]*", "", nginx_text)
    return [" ".join(part.split()) for part in re.split(r"[;{}]", text) if part.strip()]


@pytest.mark.parametrize("case", [pytest.param(None, id="no-snippet")] + ACCEPTED)
def test_prod_install_dry_run_previews_template_listener_and_keeps_snippet_port(tmp_path: Path, case) -> None:
    """With no snippet, or with each accepted shared snippet case, a prod install `--dry-run` exits 0; reports the template unit path and `active_port=<port> snippet=new|existing` (7070 when there is none); previews today's unit with `--port %i`, the snippet naming that port, and a listener whose only `listen` is 127.0.0.1:7079, including the snippet and proxying to `peertube_engine`; and leaves the tree, the host paths and the stubs' state unchanged."""
    tree = Tree(tmp_path)
    if case is not None:
        tree.snippet.write_bytes(case["text"].encode())
    port, state = (7070, "new") if case is None else (case["port"], "existing")
    before, host_before = tree.snapshot(), _host_state()

    run = tree.install("prod")
    report = _report(tree, run)
    sections = _sections(run.stdout)

    assert run.returncode == 0, report
    assert re.findall(r"^\s*unit=(\S+)\s*$", run.stdout, re.M) == [TEMPLATE], report  # the template, not peertube-engine.service
    assert f"active_port={port} snippet={state}" in run.stdout, report  # the existing snippet's port kept; 7070 only when there is none
    assert {"unit", "snippet", "listener"} <= set(sections), report  # control: the three previews are there to read
    assert sections["unit"].rstrip("\n") == unit_text("prod", tree.user, tree.real_project, "%i").rstrip("\n"), report  # today's unit, ExecStart ending `--host 127.0.0.1 --port %i`
    assert sections["snippet"].rstrip("\n").encode() == snippet_bytes(port).rstrip(b"\n"), report  # the snippet previewed names the same port, never the other one
    listener = _statements(sections["listener"])
    assert "listen 127.0.0.1:7079;" in sections["listener"], report
    assert [statement for statement in listener if statement.split()[0] == "listen"] == ["listen 127.0.0.1:7079"], report  # no other listen, loopback or not
    assert f"include {tree.snippet}" in listener, report  # the listener reads the snippet this install manages
    assert "proxy_pass http://peertube_engine" in listener, report  # and proxies to the upstream the snippet defines
    assert tree.snapshot() == before, report  # writes nothing: no snippet created or rewritten, no temp file, no deploy lock
    assert case is not None or not tree.snippet.exists(), report  # a missing snippet stays missing
    assert _mutations(tree.calls()) == [], report  # no systemctl or nginx action ran
    assert _host_state() == host_before, report  # the host's unit and nginx paths are as they were


@pytest.mark.parametrize("case", REJECTED)
def test_prod_install_dry_run_refuses_invalid_snippet(tmp_path: Path, case) -> None:
    """For each rejected shared snippet case, a prod install `--dry-run` exits 1 and leaves the snippet bytes, the tree and the stubs' state unchanged; the same tree with a valid 7070 snippet previews `active_port=7070 snippet=existing`."""
    tree = Tree(tmp_path)
    original = case["text"].encode()
    tree.snippet.write_bytes(original)
    before = tree.snapshot()

    run = tree.install("prod")
    report = _report(tree, run)

    assert run.returncode == 1, report  # an invalid snippet is refused, not replaced with 7070
    assert tree.snippet.read_bytes() == original, report
    assert tree.snapshot() == before, report
    assert _mutations(tree.calls()) == [], report
    tree.snippet.write_bytes(snippet_bytes(7070))
    control = tree.install("prod")
    assert control.returncode == 0 and "active_port=7070 snippet=existing" in control.stdout, _report(tree, control)  # control: the snippet was the reason


def test_prod_install_dry_run_refuses_port_option(tmp_path: Path) -> None:
    """A prod install `--dry-run --port 7070` exits 1, creates no snippet and changes nothing; the same run without `--port` previews `active_port=7070 snippet=new`."""
    tree = Tree(tmp_path)
    before, host_before = tree.snapshot(), _host_state()

    run = tree.install("prod", "--port", "7070")
    report = _report(tree, run)

    assert run.returncode == 1, report  # the prod port pair is fixed
    assert not tree.snippet.exists(), report
    assert tree.snapshot() == before, report
    assert _mutations(tree.calls()) == [], report  # no systemctl or nginx action ran before the refusal
    assert _host_state() == host_before, report  # the host's unit and nginx paths are as they were
    control = tree.install("prod")
    assert control.returncode == 0 and "active_port=7070 snippet=new" in control.stdout, _report(tree, control)  # control: `--port` was the reason


@pytest.mark.parametrize("extra", [[], ["--host", "127.0.0.1", "--port", "7171"]], ids=["defaults", "explicit-host-port"])
def test_dev_install_dry_run_preview_unchanged(tmp_path: Path, extra: list[str]) -> None:
    """A dev install `--dry-run`, with defaults or an explicit `--host 127.0.0.1 --port 7171`, exits 0 and prints exactly today's preview: `peertube-engine-dev.service` and `--port 7171`; it creates no snippet."""
    tree = Tree(tmp_path)
    expected = f"[dry-run] install-engine-service\n  mode=dev\n  service=peertube-engine-dev\n  host=127.0.0.1\n  port=7171\n  user={tree.user}\n  unit=/etc/systemd/system/peertube-engine-dev.service\n----- unit preview -----\n" + unit_text("dev", tree.user, tree.real_project, "7171") + "\n----- end preview -----\n"

    run = tree.install("dev", *extra)

    assert run.returncode == 0, _report(tree, run)
    assert run.stdout == expected, _report(tree, run)  # dev keeps its single unit, host and port options
    assert not tree.snippet.exists(), _report(tree, run)
