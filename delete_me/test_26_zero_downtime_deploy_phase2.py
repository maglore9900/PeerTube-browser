"""`scripts/deploy-bluegreen.sh --blue-green` moves nginx's upstream to the other Engine instance and stops the old one only after 127.0.0.1:7079 has named the target; every refusal, and every failure before that, ends non-zero with the old instance running and the snippet as it was.

- In both directions (7070→7071, 7071→7070) a clean run exits 0, and calls.log shows the target's start, then the nginx reload, then a 7079 200 naming the target, then the old instance's stop, the target's enable and the old's disable. The snippet is exactly the target's three lines at mode 0644 (under umask 077), nginx loaded it, and `random-cache.tmp.<old MainPID>.db` and its `-journal` are removed while the new instance's, an unrelated pid's and the live cache stay.
- A readiness timeout, a failed unit, an `nginx -t` failure, a reload failure, a 7079 502, 7079 naming the old instance and a failure inside rollback each end non-zero, with the original snippet bytes, the old instance never stopped and still running, and nginx's loaded upstream on the old port; rollback stops the target, and a failed restore logs `ROLLBACK FAILED`.
- The refusals (deploy lock held by a real flock, updater active or activating, every rejected case of tests/active/upstream_snippet_cases.json and a missing snippet, the Client not on 7079, non-root) end non-zero and change no unit and no nginx state; a foreign listener on the target port is refused before anything is started or switched. Each refusal's tree, with its one change undone, then deploys.
- Without `--blue-green` the exit is 2 and no lock file is created.
- The bash `read_active_port` agrees with every case of the shared JSON and rejects a missing file.

The script and engine/engine-upstream.sh are copied into a temp repository and run as a subprocess. systemctl, nginx, curl, logger and id are one stub on PATH that keeps unit, nginx and listener state in files and logs every call in order to calls.log; curl on 7079 answers from the snippet nginx last loaded, with that upstream in `X-Engine-Upstream`. Each failure test changes the clean tree of the C1 test in one place.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SRC = ROOT / "scripts" / "deploy-bluegreen.sh"
LIB_SRC = ROOT / "engine" / "engine-upstream.sh"
CASES_FILE = ROOT / "tests" / "active" / "upstream_snippet_cases.json"
BASH = shutil.which("bash", path="/usr/bin:/bin")
RUN_ARGS = ["--blue-green", "--drain", "0", "--warmup", "0", "--timeout", "3"]
OLD_PID = "4242"
NEW_PID = "5151"
# Every systemctl action that changes a unit or nginx; the stub logs `nginx -s reload` as `reload nginx` too.
MUTATING = {"start", "stop", "restart", "try-restart", "reload-or-restart", "kill", "reload", "enable", "disable"}
STOPPING = {"stop", "restart", "try-restart", "reload-or-restart", "kill"}

# One stub behind systemctl, nginx, curl, logger and id (symlinks; the basename picks the role). State lives under $STUB_DIR, and every call that matters is appended in order to calls.log.
STUB = r'''
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

STATE = Path(os.environ["STUB_DIR"])
NAME = os.path.basename(sys.argv[0])
ARGS = sys.argv[1:]


def log(line):
    with open(STATE / "calls.log", "a") as handle:
        handle.write(line + "\n")


def seq(name, default):
    # One line per call; the last line is sticky.
    path = STATE / name
    if not path.exists():
        return default
    lines = path.read_text().splitlines() or [default]
    counter = STATE / (name + ".count")
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    return lines[min(n, len(lines) - 1)]


def unit(name):
    return name[: -len(".service")] if name.endswith(".service") else name


def state(name):
    path = STATE / "state" / name
    return path.read_text().strip() if path.exists() else "inactive"


def set_state(name, value):
    (STATE / "state").mkdir(exist_ok=True)
    (STATE / "state" / name).write_text(value)


def loaded_port():
    path = STATE / "nginx-loaded"
    match = re.search(r"127\.0\.0\.1:(\d+)", path.read_text()) if path.exists() else None
    return match.group(1) if match else None


def reload_nginx():
    log("reload nginx")
    code = int(seq("reload-nginx", "0"))
    # A reload that succeeds loads whatever the snippet holds now, unless the test pins nginx to its old config.
    if code == 0 and not (STATE / "reload-noop").exists():
        shutil.copyfile(os.environ["PEERTUBE_ENGINE_UPSTREAM_SNIPPET"], STATE / "nginx-loaded")
    return code


def systemctl():
    words, props, i = [], [], 0
    while i < len(ARGS):
        arg = ARGS[i]
        i += 1
        if arg in ("-p", "--property"):
            props.append(ARGS[i])
            i += 1
        elif arg.startswith("--property="):
            props.append(arg.split("=", 1)[1])
        elif not arg.startswith("-"):
            words.append(arg)
    action, units = words[0], [unit(word) for word in words[1:]]
    if action == "reload" and units == ["nginx"]:
        return reload_nginx()
    log(" ".join([action] + units))
    if action == "is-active":
        states = [state(name) for name in units]
        if not ({"-q", "--quiet"} & set(ARGS)):
            print("\n".join(states))
        return 0 if all(value == "active" for value in states) else 3
    if action == "is-failed":
        states = [state(name) for name in units]
        print("\n".join(states))
        return 0 if "failed" in states else 1
    if action in ("start", "restart", "try-restart", "reload-or-restart"):
        for name in units:
            set_state(name, "failed" if (STATE / "fail-start" / name).exists() else "active")
        return 0
    if action in ("stop", "kill"):
        for name in units:
            set_state(name, "inactive")
        return 0
    if action == "show":
        for name in units:
            for prop in props or ["MainPID"]:
                pid_file = STATE / "pid" / name
                # systemd reports MainPID 0 for a unit that is not running.
                value = pid_file.read_text().strip() if prop == "MainPID" and pid_file.exists() and state(name) == "active" else "0"
                print(value if "--value" in ARGS else f"{prop}={value}")
        return 0
    return 0


def nginx():
    if "-t" in ARGS:
        log("nginx -t")
        code = int(seq("nginx-t", "0"))
        print("nginx: configuration file test " + ("is successful" if code == 0 else "failed"), file=sys.stderr)
        return code
    if "-s" in ARGS and ARGS[ARGS.index("-s") + 1] == "reload":
        return reload_nginx()
    log("nginx " + " ".join(ARGS))
    return 0


VALUE_SHORT = set("oDwmHXAeudr")
VALUE_LONG = {"--output", "--dump-header", "--write-out", "--max-time", "--connect-timeout", "--header", "--request", "--retry", "--retry-delay", "--retry-max-time", "--user-agent", "--referer", "--user", "--data", "--range"}
HEADER_CODES = {"200", "201", "204", "206", "301", "302", "303", "304", "307", "308"}


def render(fmt, status, upstream):
    out = fmt.replace("%{http_code}", status).replace("%{response_code}", status)
    out = re.sub(r"%header\{([^}]*)\}", lambda m: (upstream or "") if m.group(1).lower() == "x-engine-upstream" else "", out)
    return out.replace("\\n", "\n").replace("\\r", "\r")


def curl():
    opt, flags, url, i = {}, set(), None, 0
    while i < len(ARGS):
        arg = ARGS[i]
        i += 1
        if arg.startswith("--"):
            name, eq, value = arg.partition("=")
            if name in VALUE_LONG:
                if not eq:
                    value = ARGS[i]
                    i += 1
                opt[name] = value
            else:
                flags.add(name)
        elif arg.startswith("-") and len(arg) > 1:
            j = 1
            while j < len(arg):
                char = arg[j]
                j += 1
                if char in VALUE_SHORT:
                    if j < len(arg):
                        opt[char] = arg[j:]
                    else:
                        opt[char] = ARGS[i]
                        i += 1
                    break
                flags.add(char)
        else:
            url = arg
    out = opt.get("o") or opt.get("--output")
    dump = opt.get("D") or opt.get("--dump-header")
    fmt = opt.get("w") or opt.get("--write-out")
    port = urlsplit(url).port
    status, upstream = None, None
    if port in (7070, 7071):
        # A foreign process on the port answers whatever the unit's state is.
        if (STATE / "foreign" / str(port)).exists() or state(f"peertube-engine@{port}") == "active":
            status = seq(f"curl.{port}", "200")
    elif port == 7079:
        loaded = loaded_port()
        if (STATE / "curl.7079").exists():
            status = seq("curl.7079", "200")
        else:
            status = "200" if loaded and state(f"peertube-engine@{loaded}") == "active" else "502"
        # add_header without `always` is not sent on nginx's own 5xx.
        upstream = f"127.0.0.1:{loaded}" if loaded and status in HEADER_CODES else None
    log(f"curl {port} {status or '000'} upstream={upstream or '-'}")
    if status is None:
        if fmt:
            sys.stdout.write(render(fmt, "000", None))
        return 7
    head = f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n" + (f"X-Engine-Upstream: {upstream}\r\n" if upstream else "") + "\r\n"
    body = '{"status": "ok"}' if status == "200" else '{"error": "x"}'
    failed = ({"f", "--fail"} & flags) and int(status) >= 400
    if dump == "-":
        sys.stdout.write(head)
    elif dump:
        Path(dump).write_text(head)
    if not failed:
        if {"i", "--include"} & flags:
            sys.stdout.write(head)
        if out and out != "-":
            with open(out, "w") as handle:
                handle.write(body)
        else:
            sys.stdout.write(body)
    if fmt:
        sys.stdout.write(render(fmt, status, upstream))
    return 22 if failed else 0


LOGGER_VALUE = {"-t", "--tag", "-p", "--priority", "-n", "--server", "-P", "--port", "-f", "--file", "-S", "--size", "--msgid", "--socket", "--sd-id", "--sd-param"}


def logger():
    words, rest, i = [], False, 0
    while i < len(ARGS):
        arg = ARGS[i]
        i += 1
        if rest or not arg.startswith("-"):
            words.append(arg)
        elif arg == "--":
            rest = True
        elif arg in LOGGER_VALUE:
            i += 1
    message = " ".join(words) if words else sys.stdin.read()
    with open(STATE / "journal.log", "a") as handle:
        handle.write(message.rstrip("\n") + "\n")
    return 0


def ident():
    if ARGS == ["-u"]:
        path = STATE / "uid"
        print(path.read_text().strip() if path.exists() else "0")
        return 0
    os.execv("/usr/bin/id", ["id", *ARGS])


sys.exit({"systemctl": systemctl, "nginx": nginx, "curl": curl, "logger": logger, "id": ident}[NAME]())
'''


def snippet_bytes(port: int) -> bytes:
    # The plan's snippet_text, written out here rather than taken from the library under test.
    return f"upstream peertube_engine {{\n    server 127.0.0.1:{port};\n}}\n".encode()


def unit(port: int) -> str:
    return f"peertube-engine@{port}"


def client_unit_text(port: int) -> str:
    # The ExecStart client/install-client-service.sh writes.
    return f"[Service]\nExecStart=/srv/peertube-browser/venv/bin/python3 /srv/peertube-browser/client/backend/server.py --host 127.0.0.1 --port 7072 --engine-url http://127.0.0.1:{port} --publish-mode bridge\n"


class Tree:
    """A temp repository with the script, the library, a db dir, a snippet naming `active`, the stubs, and a Client unit on 7079: a clean deploy, which each failure test changes in one place."""

    def __init__(self, root: Path, active: int) -> None:
        assert SCRIPT_SRC.is_file(), f"{SCRIPT_SRC} does not exist: phase 2 adds it"
        assert LIB_SRC.is_file(), f"{LIB_SRC} does not exist: phase 2 adds it"
        self.root = root
        self.old, self.target = active, 7071 if active == 7070 else 7070
        (root / "scripts").mkdir()
        self.script = root / "scripts" / "deploy-bluegreen.sh"
        shutil.copy(SCRIPT_SRC, self.script)
        (root / "engine").mkdir()
        shutil.copy(LIB_SRC, root / "engine" / "engine-upstream.sh")
        self.db = root / "engine" / "server" / "db"
        self.db.mkdir(parents=True)
        self.lock = self.db / "engine-deploy.lock"
        (root / "nginx").mkdir()
        self.snippet = root / "nginx" / "peertube-engine-upstream.conf"
        self.snippet.write_bytes(snippet_bytes(active))
        self.snippet.chmod(0o644)
        self.client_unit = root / "peertube-client.service"
        self.client_unit.write_text(client_unit_text(7079))
        self.stub = root / "stub"
        self.stub.mkdir()
        # nginx has loaded the snippet as it stands, and the old instance is the one running.
        self.put("nginx-loaded", snippet_bytes(active).decode())
        self.put(f"state/{unit(self.old)}", "active")
        self.put(f"pid/{unit(self.old)}", OLD_PID)
        self.put(f"pid/{unit(self.target)}", NEW_PID)
        stub_py = root / "stubbin" / "stub.py"
        stub_py.parent.mkdir()
        stub_py.write_text(f"#!{sys.executable}\n{STUB}")
        stub_py.chmod(0o755)
        self.bin = root / "bin"
        self.bin.mkdir()
        for name in ("systemctl", "nginx", "curl", "logger", "id"):
            (self.bin / name).symlink_to(stub_py)

    def put(self, rel: str, text: str) -> None:
        path = self.stub / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run(self, args: list[str] = RUN_ARGS) -> subprocess.CompletedProcess:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root), "LC_ALL": "C", "STUB_DIR": str(self.stub), "PEERTUBE_ENGINE_UPSTREAM_SNIPPET": str(self.snippet), "PEERTUBE_CLIENT_UNIT_PATH": str(self.client_unit)}
        # umask 077, so a 0644 snippet comes from the script and not from the caller's umask.
        return subprocess.run([BASH, str(self.script), *args], cwd=self.root, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90, preexec_fn=lambda: os.umask(0o077))

    def calls(self) -> list[str]:
        path = self.stub / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def journal(self) -> str:
        path = self.stub / "journal.log"
        return path.read_text() if path.exists() else ""

    def state(self, port: int) -> str:
        path = self.stub / "state" / unit(port)
        return path.read_text().strip() if path.exists() else "inactive"

    def loaded_port(self) -> int | None:
        match = re.search(r"127\.0\.0\.1:(\d+)", (self.stub / "nginx-loaded").read_text())
        return int(match.group(1)) if match else None


def _report(tree: Tree, run: subprocess.CompletedProcess) -> str:
    return f"exit={run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}\ncalls:\n" + "\n".join(tree.calls()) + f"\njournal:\n{tree.journal()}"


def _first(calls: list[str], line: str, after: int = -1) -> int:
    for index, call in enumerate(calls):
        if index > after and call == line:
            return index
    pytest.fail(f"{line!r} not in calls.log after line {after}:\n" + "\n".join(calls))


def _mutations(calls: list[str]) -> list[str]:
    return [call for call in calls if call.split()[0] in MUTATING]


def _assert_old_kept(tree: Tree, run: subprocess.CompletedProcess, original: bytes | None) -> None:
    report = _report(tree, run)
    assert run.returncode != 0, report  # C2: ends non-zero
    if original is None:
        assert not tree.snippet.exists(), report  # C2: a missing snippet is not created
    else:
        assert tree.snippet.read_bytes() == original, report  # C2: the original snippet is in place
    old = unit(tree.old)
    assert not [call for call in tree.calls() if call.split()[0] in STOPPING and old in call.split()[1:]], report  # C2: the old instance is never stopped
    assert tree.state(tree.old) == "active", report  # C2: the old instance still runs
    assert tree.loaded_port() == tree.old, report  # C2: what nginx last loaded still names the old instance


def _assert_clean_deploy(tree: Tree, run: subprocess.CompletedProcess) -> None:
    """The control every refusal test ends with: the same tree, its one change undone, deploys."""
    assert run.returncode == 0, _report(tree, run)
    assert tree.snippet.read_bytes() == snippet_bytes(tree.target), _report(tree, run)


@pytest.mark.parametrize("old,target", [(7070, 7071), (7071, 7070)], ids=["7070-to-7071", "7071-to-7070"])
def test_clean_run_switches_then_stops_old_after_7079_names_target(tmp_path: Path, old: int, target: int) -> None:
    """A clean run exits 0; calls.log has start of the target, then the nginx reload, then a 7079 answer of 200 naming the target, then the stop of the old instance, the enable of the target and the disable of the old. The snippet is exactly the target's three lines at mode 0644, nginx has loaded it, the target runs and the old does not, and the old instance's random-cache temp file and its journal are gone while the new instance's and an unrelated one stay."""
    tree = Tree(tmp_path, active=old)
    leftovers = [tree.db / f"random-cache.tmp.{OLD_PID}.db", tree.db / f"random-cache.tmp.{OLD_PID}.db-journal"]
    # The new instance's own build in progress, an unrelated pid's, and the live cache: none is the old instance's.
    keep = [tree.db / f"random-cache.tmp.{NEW_PID}.db", tree.db / "random-cache.tmp.999.db", tree.db / "random-cache.db"]
    for path in leftovers + keep:
        path.write_bytes(b"x")

    run = tree.run()
    report = _report(tree, run)
    calls = tree.calls()

    assert run.returncode == 0, report  # C1
    start = _first(calls, f"start {unit(target)}")
    reload = _first(calls, "reload nginx")
    confirmed = _first(calls, f"curl 7079 200 upstream=127.0.0.1:{target}", after=reload)
    stop_old = _first(calls, f"stop {unit(old)}")
    enable = _first(calls, f"enable {unit(target)}")
    disable = _first(calls, f"disable {unit(old)}")
    assert start < reload, report  # C1: the target is started before traffic moves
    assert confirmed < stop_old, report  # C1: the first stop of the old instance comes after 7079 has named the target
    assert stop_old < enable < disable, report  # C1: boot enablement follows the switch
    assert tree.snippet.read_bytes() == snippet_bytes(target), report  # C1: the snippet names the target, and only it
    assert stat.S_IMODE(tree.snippet.stat().st_mode) == 0o644, oct(tree.snippet.stat().st_mode)  # C1: the updater (service user) can still read it
    assert tree.loaded_port() == target, report  # C1: the snippet was written before the reload that loaded it
    assert tree.state(target) == "active" and tree.state(old) == "inactive", report  # C1
    assert [path.name for path in leftovers if path.exists()] == [], report  # C1: random-cache.tmp.<old MainPID>.db and -journal removed
    assert [path.name for path in keep if not path.exists()] == [], report  # C1: only the old instance's pair


def _readiness_timeout(tree: Tree) -> None:
    tree.put(f"curl.{tree.target}", "503")


def _unit_failed(tree: Tree) -> None:
    tree.put(f"fail-start/{unit(tree.target)}", "")


def _nginx_test_failed(tree: Tree) -> None:
    tree.put("nginx-t", "1\n0")


def _reload_failed(tree: Tree) -> None:
    tree.put("reload-nginx", "1\n0")


def _post_switch_502(tree: Tree) -> None:
    tree.put("curl.7079", "502")


def _wrong_upstream(tree: Tree) -> None:
    # The reload reports success but nginx keeps serving the old config, so 7079 answers 200 from the old instance.
    tree.put("reload-noop", "")


def _rollback_failed(tree: Tree) -> None:
    tree.put("nginx-t", "1\n1")


# (setup, the calls.log line showing the run got as far as the failure, whether rollback reaches the stop of the target)
FAILURES = {
    "readiness-timeout": (_readiness_timeout, "curl 7071 503 upstream=-", True),
    "unit-failed": (_unit_failed, "start peertube-engine@7071", True),
    "nginx-test-failed": (_nginx_test_failed, "nginx -t", True),
    "reload-failed": (_reload_failed, "reload nginx", True),
    "post-switch-502": (_post_switch_502, "curl 7079 502 upstream=-", True),
    "post-switch-wrong-upstream": (_wrong_upstream, "curl 7079 200 upstream=127.0.0.1:7070", True),
    "rollback-failed": (_rollback_failed, "nginx -t", False),
}


@pytest.mark.parametrize("case", list(FAILURES))
def test_failure_before_7079_confirms_keeps_old_serving(tmp_path: Path, case: str) -> None:
    """Each failure between the start of the target and a 7079 answer naming it (readiness timeout, failed unit, `nginx -t`, reload, a 7079 502, 7079 naming the old instance, and a failure inside rollback) ends non-zero with the original snippet bytes, the old instance never stopped and still running, and nginx's loaded upstream on the old port; the run reached that failure, and rollback stops the target where it gets that far."""
    setup, reached, stops_target = FAILURES[case]
    tree = Tree(tmp_path, active=7070)
    setup(tree)

    run = tree.run()
    calls = tree.calls()

    assert reached in calls, _report(tree, run)  # control: the run got as far as this failure, so the exit is not an earlier refusal
    assert f"start {unit(tree.target)}" in calls, _report(tree, run)  # control: the target was started, so this is a rollback and not a refusal
    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    if stops_target:
        assert tree.state(tree.target) == "inactive" and f"stop {unit(tree.target)}" in calls, _report(tree, run)  # C2 (rollback): the new instance is stopped again
    if case == "rollback-failed":
        assert calls.count("nginx -t") >= 2, _report(tree, run)  # control: the restore's own `nginx -t` ran and failed
        assert "ROLLBACK FAILED" in tree.journal(), _report(tree, run)  # C2: a failure inside rollback is logged loudly


@pytest.mark.parametrize("state", ["active", "activating"])
def test_refuses_while_updater_runs(tmp_path: Path, state: str) -> None:
    """With `peertube-updater.service` active or activating (its oneshot run), the run ends non-zero after asking for the updater's state, changes no unit and no nginx state, and keeps the snippet; the same tree with the updater inactive deploys."""
    tree = Tree(tmp_path, active=7070)
    tree.put("state/peertube-updater", state)

    run = tree.run()

    assert "is-active peertube-updater" in tree.calls(), _report(tree, run)  # control: it looked at the updater
    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2: a refusal touches nothing
    tree.put("state/peertube-updater", "inactive")
    _assert_clean_deploy(tree, tree.run())  # control: the updater state was the reason


def _hold(lock: Path) -> int:
    fd = os.open(lock.as_posix(), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def test_refuses_while_deploy_lock_held(tmp_path: Path) -> None:
    """With `engine/server/db/engine-deploy.lock` flocked by another holder, the run ends non-zero, changes no unit and no nginx state, and keeps the snippet; once the holder lets go the same tree deploys."""
    tree = Tree(tmp_path, active=7070)
    fd = _hold(tree.lock)
    try:
        run = tree.run()
    finally:
        os.close(fd)

    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2: a refusal touches nothing
    _assert_clean_deploy(tree, tree.run())  # control: the held lock was the reason, so the script locks this very file


def _case_params() -> list:
    if not CASES_FILE.exists():
        return [pytest.param(None, id="json-case-file-missing")]
    return [pytest.param(case, id=case["id"]) for case in json.loads(CASES_FILE.read_text(encoding="utf-8"))]


INVALID_SNIPPETS = [param for param in _case_params() if param.values[0] is None or param.values[0]["port"] is None] + [pytest.param({"id": "missing", "text": None, "port": None}, id="missing")]


@pytest.mark.parametrize("case", INVALID_SNIPPETS)
def test_refuses_invalid_snippet(tmp_path: Path, case) -> None:
    """For every rejected case in tests/active/upstream_snippet_cases.json, and for a missing snippet, the run ends non-zero, changes no unit and no nginx state, and leaves the snippet bytes (or its absence) as they were; the same tree with a valid 7070 snippet deploys."""
    assert case is not None, f"{CASES_FILE} is missing"
    tree = Tree(tmp_path, active=7070)
    if case["text"] is None:
        tree.snippet.unlink()
        original = None
    else:
        original = case["text"].encode()
        tree.snippet.write_bytes(original)

    run = tree.run()

    _assert_old_kept(tree, run, original)  # C2
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2: a refusal touches nothing
    tree.snippet.write_bytes(snippet_bytes(7070))
    _assert_clean_deploy(tree, tree.run())  # control: the snippet was the reason


def test_refuses_client_not_on_7079(tmp_path: Path) -> None:
    """With the Client unit's `--engine-url` on http://127.0.0.1:7070, the run ends non-zero, changes no unit and no nginx state, and keeps the snippet; the same tree with the Client on 7079 deploys."""
    tree = Tree(tmp_path, active=7070)
    tree.client_unit.write_text(client_unit_text(7070))

    run = tree.run()

    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2: a refusal touches nothing
    tree.client_unit.write_text(client_unit_text(7079))
    _assert_clean_deploy(tree, tree.run())  # control: the Client URL was the reason


def test_refuses_non_root(tmp_path: Path) -> None:
    """With `id -u` printing 1000, the run ends non-zero, changes no unit and no nginx state, and keeps the snippet; the same tree as uid 0 deploys."""
    tree = Tree(tmp_path, active=7070)
    tree.put("uid", "1000")

    run = tree.run()

    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2: a refusal touches nothing
    tree.put("uid", "0")
    _assert_clean_deploy(tree, tree.run())  # control: the uid was the reason


def test_refuses_foreign_listener_on_target_port(tmp_path: Path) -> None:
    """With something answering 200 on 7071 while `peertube-engine@7071` is inactive, the run ends non-zero after probing 7071, never starts the target or reloads nginx, and keeps the snippet; the same tree without that listener deploys."""
    tree = Tree(tmp_path, active=7070)
    tree.put("foreign/7071", "")

    run = tree.run()
    calls = tree.calls()

    assert "curl 7071 200 upstream=-" in calls, _report(tree, run)  # control: the foreign listener answered the script
    _assert_old_kept(tree, run, snippet_bytes(7070))  # C2
    assert [call for call in _mutations(calls) if call.split()[0] in ("start", "reload", "enable", "disable")] == [], _report(tree, run)  # C2: refused before anything is started or switched
    (tree.stub / "foreign" / "7071").unlink()
    _assert_clean_deploy(tree, tree.run())  # control: the foreign listener was the reason


def test_without_blue_green_exits_2_and_creates_no_lock(tmp_path: Path) -> None:
    """Without `--blue-green` the run exits 2, creates no lock file, changes no unit and no nginx state, and keeps the snippet; with the flag the same tree deploys and creates that lock file."""
    tree = Tree(tmp_path, active=7070)

    run = tree.run(["--drain", "0", "--warmup", "0", "--timeout", "3"])

    assert run.returncode == 2, _report(tree, run)  # C2
    assert not tree.lock.exists(), _report(tree, run)  # C2: no side effects, not even the lock file
    assert _mutations(tree.calls()) == [], _report(tree, run)  # C2
    assert tree.snippet.read_bytes() == snippet_bytes(7070)  # C2
    _assert_clean_deploy(tree, tree.run())
    assert tree.lock.exists()  # control: this is the lock path a real run creates, so its absence above is not a wrong path


def _bash_cases() -> list:
    return _case_params() + [pytest.param({"id": "missing", "text": None, "port": None}, id="missing")]


@pytest.mark.parametrize("case", _bash_cases())
def test_bash_read_active_port_matches_shared_cases(tmp_path: Path, case) -> None:
    """Sourced from engine/engine-upstream.sh, `read_active_port` prints the port and exits 0 for every accepted case of tests/active/upstream_snippet_cases.json, and exits non-zero for every rejected case and for a missing file."""
    assert case is not None, f"{CASES_FILE} is missing"
    assert LIB_SRC.is_file(), f"{LIB_SRC} does not exist: phase 2 adds it"
    path = tmp_path / "peertube-engine-upstream.conf"
    if case["text"] is not None:
        path.write_bytes(case["text"].encode())

    run = subprocess.run([BASH, "-c", 'source "$1" && declare -F read_active_port >/dev/null && echo SOURCED >&2 && read_active_port "$2"', "_", str(LIB_SRC), str(path)], env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)

    assert "SOURCED" in run.stderr, run.stderr  # control: the library sourced and defines read_active_port, so a non-zero exit below is the parser's
    if case["port"] is None:
        assert run.returncode != 0, (run.returncode, run.stdout)  # C2: the deploy refuses this snippet
    else:
        assert (run.returncode, run.stdout.strip()) == (0, str(case["port"])), (run.returncode, run.stdout, run.stderr)  # C1: the active port the deploy flips from
