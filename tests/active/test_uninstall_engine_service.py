"""The prod Engine uninstaller previews removing both instances, the `peertube-engine@.service` template, the 127.0.0.1:7079 listener and the upstream snippet, in that order, in `--dry-run`, which writes nothing.

- A prod uninstall `--dry-run`, with and without `--service-name peertube-engine`, lists stop and disable for `peertube-engine@7070` and `@7071`, then `rm` of the template, then the listener, then the snippet, then `nginx -t`, and changes nothing.

The repo's uninstaller runs as a subprocess against a fake `--project-dir`. `PEERTUBE_ENGINE_UPSTREAM_SNIPPET` points into tmp. One stub stands behind systemctl, nginx and logger on PATH and logs every call.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNINSTALLER = ROOT / "engine" / "uninstall-engine-service.sh"
BASH = shutil.which("bash", path="/usr/bin:/bin")
TEMPLATE = "/etc/systemd/system/peertube-engine@.service"
LISTENER = "/etc/nginx/conf.d/peertube-engine-internal.conf"
# Host paths a prod install manages; a dry-run leaves each as it found it.
HOST_PATHS = (TEMPLATE, LISTENER, "/etc/nginx/peertube-engine-upstream.conf", "/etc/systemd/system/peertube-engine.service")
SYSTEMCTL_MUTATING = {"start", "stop", "restart", "try-restart", "reload-or-restart", "kill", "reload", "enable", "disable", "daemon-reload", "reset-failed", "mask", "unmask", "link", "preset"}

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

    def run(self, script: Path, args: list[str]) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root), "LC_ALL": "C", "STUB_DIR": str(self.stub), "PEERTUBE_ENGINE_UPSTREAM_SNIPPET": str(self.snippet)}
        return subprocess.run([BASH, str(script), *args, "--dry-run", "--project-dir", str(self.project)], cwd=self.root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def uninstall(self, *extra: str) -> subprocess.CompletedProcess:
        return self.run(UNINSTALLER, ["--mode", "prod", *extra])

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


def _dry_run_events(stdout: str) -> list[tuple[str, str]]:
    """The `[dry-run]` command lines in order, one (action, target) per unit or path, so `rm -f a b` counts as two removals in that order."""
    events = []
    for line in stdout.splitlines():
        if not line.startswith("[dry-run] "):
            continue
        argv = shlex.split(line[len("[dry-run] "):])
        tool, args = os.path.basename(argv[0]), argv[1:]
        words = [arg for arg in args if not arg.startswith("-")]
        if tool == "systemctl" and words:
            events += [(words[0], unit[: -len(".service")] if unit.endswith(".service") else unit) for unit in words[1:]]
        elif tool == "rm":
            events += [("rm", path) for path in words]
        else:
            events.append((tool, " ".join(args)))
    return events


def _index(events: list[tuple[str, str]], event: tuple[str, str], report: str) -> int:
    if event not in events:
        pytest.fail(f"{event!r} not in the dry-run actions {events}\n{report}")
    return events.index(event)


@pytest.mark.parametrize("extra", [[], ["--service-name", "peertube-engine"]], ids=["defaults", "explicit-service-name"])
def test_prod_uninstall_dry_run_removes_instances_template_listener_then_snippet(tmp_path: Path, extra: list[str]) -> None:
    """A prod uninstall `--dry-run`, with defaults or with an explicit `--service-name peertube-engine`, exits 0 and lists stop and disable for `peertube-engine@7070` and `@7071`, then `rm` of the template, then the listener, then the snippet, then `nginx -t`; the snippet, the tree, the host paths and the stubs' state are unchanged."""
    tree = Tree(tmp_path)
    tree.snippet.write_bytes(snippet_bytes(7070))
    before, host_before = tree.snapshot(), _host_state()

    run = tree.uninstall(*extra)
    report = _report(tree, run)
    events = _dry_run_events(run.stdout)

    assert run.returncode == 0, report
    instance_actions = [_index(events, (action, f"peertube-engine@{port}"), report) for port in (7070, 7071) for action in ("stop", "disable")]  # both instances stopped and disabled
    rm_template = _index(events, ("rm", TEMPLATE), report)
    rm_listener = _index(events, ("rm", LISTENER), report)
    rm_snippet = _index(events, ("rm", str(tree.snippet)), report)  # the snippet this host uses
    nginx_test = _index(events, ("nginx", "-t"), report)
    assert max(instance_actions) < rm_template, report  # instances down before their template goes
    assert rm_template < rm_listener < rm_snippet, report  # the listener goes before the snippet it includes
    assert rm_snippet < nginx_test, report  # nginx is validated without either file
    assert tree.snippet.read_bytes() == snippet_bytes(7070), report  # a preview only
    assert tree.snapshot() == before, report
    assert _mutations(tree.calls()) == [], report
    assert _host_state() == host_before, report
