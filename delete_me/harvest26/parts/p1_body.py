CASES_FILE = ROOT / "tests" / "active" / "upstream_snippet_cases.json"
SNIPPET = "/etc/nginx/peertube-engine-upstream.conf"
SYSTEMCTL = "/usr/bin/systemctl"

# The plan's case table (§7.1), written here so the expected ports do not come only from the file the implementation ships with.
PLAN_CASES = [
    ("active-7070", "upstream peertube_engine {\n    server 127.0.0.1:7070;\n}\n", 7070),
    ("active-7071", "upstream peertube_engine {\n    server 127.0.0.1:7071;\n}\n", 7071),
    ("tabs-no-final-newline", "upstream peertube_engine {\n\tserver\t127.0.0.1:7071;\t\n}", 7071),
    ("foreign-port", "upstream peertube_engine {\n    server 127.0.0.1:7072;\n}\n", None),
    ("foreign-host", "upstream peertube_engine {\n    server 0.0.0.0:7070;\n}\n", None),
    ("two-servers", "upstream peertube_engine {\n    server 127.0.0.1:7070;\n    server 127.0.0.1:7071;\n}\n", None),
    ("server-params", "upstream peertube_engine {\n    server 127.0.0.1:7070 max_fails=0;\n}\n", None),
    ("commented-out", "upstream peertube_engine {\n#    server 127.0.0.1:7070;\n}\n", None),
    # The bash parser greps line by line, so a CR before the end of line fails it; Path.read_text would translate CRLF away and accept this.
    ("crlf", "upstream peertube_engine {\r\n    server 127.0.0.1:7070;\r\n}\r\n", None),
    ("empty", "", None),
]


def _file_cases() -> list:
    # A missing file must fail its own test, not abort collection of the lock and scan tests with it.
    if not CASES_FILE.exists():
        return [pytest.param(None, id="json-case-file-missing")]
    return [pytest.param(case, id=f"json-{case['id']}") for case in json.loads(CASES_FILE.read_text(encoding="utf-8"))]


SNIPPET_CASES = [pytest.param({"id": case_id, "text": text, "port": port}, id=f"plan-{case_id}") for case_id, text, port in PLAN_CASES] + _file_cases()

def _write(path: Path, text: str) -> Path:
    # Bytes, so the CRLF case reaches the parser as written.
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.parametrize("case", SNIPPET_CASES)
def test_parse_upstream_snippet_cases(updater, tmp_path: Path, case) -> None:
    """Every accepted snippet case parses to its port as an int; every rejected one raises ValueError."""
    assert case is not None, f"{CASES_FILE} is missing: phase 1 adds it as a JSON list of {{id, text, port}}, port null for a rejected snippet"
    snippet = _write(tmp_path / "peertube-engine-upstream.conf", case["text"])

    if case["port"] is None:
        with pytest.raises(ValueError):
            updater.parse_upstream_snippet(snippet)
    else:
        port = updater.parse_upstream_snippet(snippet)
        assert type(port) is int and port == case["port"], repr(port)  # 7070.0 or "7070" would spell another unit


def test_missing_snippet_raises_value_error(updater, tmp_path: Path) -> None:
    """A snippet path that does not exist raises ValueError, not an OSError."""
    with pytest.raises(ValueError):
        updater.parse_upstream_snippet(tmp_path / "absent.conf")


def test_engine_instance_unit_is_the_sudoers_spelling(updater, tmp_path: Path) -> None:
    """`engine_instance_unit` gives `peertube-engine@7070` and `@7071` with no `.service`, refuses 7069 and 7072, and the unit resolved from a 7071 snippet builds the literal sudoers stop argv."""
    assert updater.engine_instance_unit(7070) == "peertube-engine@7070"
    assert updater.engine_instance_unit(7071) == "peertube-engine@7071"
    for port in (7069, 7072):
        with pytest.raises(ValueError):
            updater.engine_instance_unit(port)  # only the fixed pair

    unit = updater.engine_instance_unit(updater.parse_upstream_snippet(_write(tmp_path / "peertube-engine-upstream.conf", "upstream peertube_engine {\n    server 127.0.0.1:7071;\n}\n")))

    # sudo matches argv literally against `<systemctl> stop peertube-engine@7071`, so any suffix or reordering is a refused stop.
    assert updater.systemctl_cmd(systemctl_bin="/usr/bin/systemctl", service_name=unit, action="stop", use_sudo=True) == ["sudo", "-n", "/usr/bin/systemctl", "stop", "peertube-engine@7071"]


def test_parse_args_takes_snippet_and_deploy_lock(updater, monkeypatch) -> None:
    """`--engine-upstream-snippet` is taken as given and absent by default, and `--deploy-lock-file` defaults to the deploy script's lock path, distinct from `--lock-file`."""
    # --service-name given, so parse_args does not shell out to the installer for the default name.
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--service-name", "peertube-engine", "--engine-upstream-snippet", SNIPPET])
    args = updater.parse_args()

    assert args.engine_upstream_snippet == SNIPPET
    assert Path(args.deploy_lock_file) == ROOT / "engine" / "server" / "db" / "engine-deploy.lock"  # the same file the deploy script flocks
    assert Path(args.deploy_lock_file) != Path(args.lock_file)  # the updater's own single-run lock is a different file

    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--service-name", "peertube-engine"])
    assert updater.parse_args().engine_upstream_snippet is None  # without the flag the dev path is not switched over


@pytest.fixture
def holder(tmp_path: Path):
    """A second open file description holding the deploy flock, as a running deploy would."""
    lock = tmp_path / "engine-deploy.lock"
    fd = os.open(lock.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = {"lock": lock, "fd": fd}
    try:
        yield state
    finally:
        if state["fd"] is not None:
            os.close(state["fd"])


def _locked_by_someone(lock: Path) -> bool:
    fd = os.open(lock.as_posix(), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def test_held_lock_raises_and_free_lock_is_taken(updater, holder) -> None:
    """With the flock held elsewhere, `acquire_deploy_lock(wait_seconds=0)` raises exactly RuntimeError; once the holder lets go, the same call returns an fd that holds the flock."""
    lock = holder["lock"]
    assert _locked_by_someone(lock)  # control: the holder really holds it

    with pytest.raises(RuntimeError) as excinfo:
        updater.acquire_deploy_lock(lock, wait_seconds=0)
    assert excinfo.type is RuntimeError, excinfo  # not a subclass such as a stub's NotImplementedError

    os.close(holder["fd"])
    holder["fd"] = None
    fd = updater.acquire_deploy_lock(lock, wait_seconds=0)
    try:
        assert _locked_by_someone(lock)  # the returned fd holds the flock, so the earlier raise was the hold and not a refusal of every call
    finally:
        updater.release_deploy_lock(fd)


def test_bounded_wait_runs_out_then_raises(updater, holder) -> None:
    """A lock held through a 0.3 s wait raises exactly RuntimeError, no sooner than the wait and well inside a few seconds."""
    start = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        updater.acquire_deploy_lock(holder["lock"], wait_seconds=0.3, poll_seconds=0.05)
    elapsed = time.monotonic() - start

    assert excinfo.type is RuntimeError, excinfo
    assert 0.3 <= elapsed < 3.0, elapsed  # it waited the bound, and the bound held


def test_lock_released_during_wait_is_taken(updater, holder) -> None:
    """A lock its holder releases 0.2 s into a 5 s wait is taken: the wait polls rather than failing at the first refusal."""
    start = time.monotonic()

    def let_go() -> None:
        os.close(holder["fd"])
        holder["fd"] = None

    timer = threading.Timer(0.2, let_go)
    timer.start()
    try:
        fd = updater.acquire_deploy_lock(holder["lock"], wait_seconds=5, poll_seconds=0.05)
    finally:
        timer.join()
    elapsed = time.monotonic() - start
    try:
        assert 0.2 <= elapsed < 4.0, elapsed  # control: the holder still held it when the wait began, and the return came on release, not at the deadline
        assert _locked_by_someone(holder["lock"])
    finally:
        updater.release_deploy_lock(fd)


def test_read_only_lock_file_is_locked_and_released(updater, tmp_path: Path) -> None:
    """On a 0444 lock file, as root leaves it for the service user, `acquire_deploy_lock` returns an fd holding the flock, and `release_deploy_lock` frees the flock and closes the fd."""
    lock = tmp_path / "engine-deploy.lock"
    lock.write_bytes(b"")
    lock.chmod(0o444)
    with pytest.raises(PermissionError):
        os.close(os.open(lock.as_posix(), os.O_WRONLY))  # control: this user cannot open it for writing

    fd = updater.acquire_deploy_lock(lock, wait_seconds=0)
    assert _locked_by_someone(lock)  # it holds the flock through a read-only fd

    updater.release_deploy_lock(fd)

    assert not _locked_by_someone(lock)  # released
    with pytest.raises(OSError):
        os.fstat(fd)  # closed


def _main() -> ast.FunctionDef:
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")


def _calls(main: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [node for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name]


def _kw(call: ast.Call, name: str):
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _attrs(node: ast.AST) -> set[str]:
    return {sub.attr for sub in ast.walk(node) if isinstance(sub, ast.Attribute)}


def _inside(node: ast.AST, stmts: list[ast.stmt]) -> bool:
    return any(sub is node for stmt in stmts for sub in ast.walk(stmt))


def test_main_stops_and_starts_the_snippet_unit_under_the_lock(updater) -> None:
    """In `main` the deploy lock is taken with a positive finite wait before the snippet is parsed and before the stop; `engine_unit` is resolved once from `--engine-upstream-snippet` and never rebound after the stop; both `systemctl_cmd` calls pass it; the release sits in the `finally` of the `try` that starts it."""
    # rat-tail: a source scan for what the two runs of `main` below cannot observe: the 30-minute bound itself, the parse sitting under the lock, and the release on a start that raises; runs with a fake clock and a failing start would replace it.
    main = _main()
    systemctl_calls = _calls(main, "systemctl_cmd")
    by_action = {_kw(call, "action").value: call for call in systemctl_calls if isinstance(_kw(call, "action"), ast.Constant)}
    assert len(systemctl_calls) == 2 and set(by_action) == {"stop", "start"}, [ast.dump(call) for call in systemctl_calls]  # control: the scan sees the one stop and the one start
    stop, start = by_action["stop"], by_action["start"]

    for call in (stop, start):
        value = _kw(call, "service_name")
        assert isinstance(value, ast.Name) and value.id == "engine_unit", ast.dump(value)  # both act on the one local

    resolved = [node for node in ast.walk(main) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "engine_unit" for target in node.targets) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "engine_instance_unit" and node.value.args and isinstance(node.value.args[0], ast.Call) and isinstance(node.value.args[0].func, ast.Name) and node.value.args[0].func.id == "parse_upstream_snippet"]
    assert len(resolved) == 1, [node.lineno for node in resolved]  # resolved once, as engine_instance_unit(parse_upstream_snippet(...))
    assert "engine_upstream_snippet" in _attrs(resolved[0].value.args[0])  # from the --engine-upstream-snippet file
    stores = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Name) and node.id == "engine_unit" and isinstance(node.ctx, ast.Store)]
    assert max(stores) < stop.lineno, (stores, stop.lineno)  # no rebinding between the stop and the start

    acquires = _calls(main, "acquire_deploy_lock")
    assert len(acquires) == 1, [call.lineno for call in acquires]
    acquire = acquires[0]
    assert "deploy_lock_file" in _attrs(acquire)  # the deploy lock, not the updater's own --lock-file
    wait = _kw(acquire, "wait_seconds")
    assert wait is not None, ast.dump(acquire)
    bound = wait.value if isinstance(wait, ast.Constant) else getattr(updater, wait.id, None) if isinstance(wait, ast.Name) else None
    assert isinstance(bound, (int, float)) and 0 < bound < float("inf"), ast.dump(wait)  # a real, finite wait, so a deploy that never lets go ends in the RuntimeError rather than an updater blocked forever
    stopped = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "service_stopped" for target in node.targets) and isinstance(node.value, ast.Constant) and node.value.value is True]
    assert len(stopped) == 1, stopped  # control
    assert acquire.lineno < resolved[0].lineno, (acquire.lineno, resolved[0].lineno)  # the snippet is read under the lock, so a deploy cannot flip it between the parse and the stop
    assert acquire.lineno < stop.lineno and acquire.lineno < stopped[0], (acquire.lineno, stop.lineno, stopped)  # a lock timeout raises before anything is stopped

    releases = _calls(main, "release_deploy_lock")
    assert len(releases) == 1 and releases[0].lineno > start.lineno, ([call.lineno for call in releases], start.lineno)  # held until after the start
    trys = [node for node in ast.walk(main) if isinstance(node, ast.Try)]
    assert any(_inside(start, node.body) and _inside(releases[0], node.finalbody) for node in trys)  # released even when the start raises


def _run_main(updater, monkeypatch, tmp_path: Path, lock: Path) -> dict:
    """Run `main` against a 7071 snippet and `lock` as the deploy lock, replacing only the child processes; return what it raised, every child argv, and whether the lock was held at each systemctl call."""
    crawler = tmp_path / "crawler"
    (crawler / "dist").mkdir(parents=True)
    shutil.copy(ROOT / "engine" / "crawler" / "schema.sql", crawler / "schema.sql")
    for name in ("instances-cli.js", "channels-cli.js", "videos-cli.js", "channels-videos-count-cli.js"):
        (crawler / "dist" / name).write_bytes(b"")
    prod = tmp_path / "prod.db"
    conn = sqlite3.connect(prod.as_posix())
    try:
        conn.executescript((crawler / "schema.sql").read_text(encoding="utf-8"))
        # A prod host missing from an empty join list: one stale host to purge and no new host to crawl, so the sync-join path goes straight to the stop.
        conn.execute("INSERT INTO instances(host) VALUES ('stale.example')")
        conn.commit()
    finally:
        conn.close()
    join = tmp_path / "join.json"
    join.write_text("[]", encoding="utf-8")
    snippet = _write(tmp_path / "peertube-engine-upstream.conf", "upstream peertube_engine {\n    server 127.0.0.1:7071;\n}\n")
    run = {"error": None, "calls": [], "held": []}

    def fake_run(cmd, **kwargs):
        run["calls"].append(list(cmd))
        if list(cmd[:3]) == ["sudo", "-n", SYSTEMCTL]:
            run["held"].append(lock.exists() and _locked_by_someone(lock))
            if cmd[3] == "stop":
                # Rewritten once the stop has run, so a start that re-reads the snippet lands on 7070, not on the stopped 7071.
                _write(snippet, "upstream peertube_engine {\n    server 127.0.0.1:7070;\n}\n")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--service-name", "peertube-engine", "--systemctl-bin", SYSTEMCTL, "--systemctl-use-sudo", "--engine-upstream-snippet", snippet.as_posix(), "--deploy-lock-file", lock.as_posix(), "--sync-join-whitelist", "--yes", "--whitelist-url", join.as_uri(), "--fail-after-merge-before-similarity", "--cpu", "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", (tmp_path / "staging.db").as_posix(), "--similarity-db", (tmp_path / "similarity-cache.db").as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix()])

    def target() -> None:
        try:
            updater.main()
        except BaseException as exc:
            run["error"] = exc

    # A thread, so a wait the test did not shorten fails here instead of blocking the suite for 30 minutes.
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "main still running after 10 s"
    return run


def test_main_run_stops_and_starts_the_snippet_unit_holding_the_lock(updater, monkeypatch, tmp_path: Path) -> None:
    """Run with the deploy lock free and a 7071 snippet, `main`'s first and last child are the sudoers stop and start of `peertube-engine@7071`, with the lock held at both; the start stays on 7071 when the snippet is rewritten after the stop, and the lock is free once `main` is done."""
    lock = tmp_path / "engine-deploy.lock"
    run = _run_main(updater, monkeypatch, tmp_path, lock)

    assert type(run["error"]) is RuntimeError, repr(run["error"])  # control: --fail-after-merge-before-similarity ends the run with the Engine started again
    assert any(Path(part).name == "build-ann-index.py" for cmd in run["calls"] for part in cmd), run["calls"]  # control: the run went through merge and ANN to that injected failure
    assert run["calls"][0] == ["sudo", "-n", SYSTEMCTL, "stop", "peertube-engine@7071"], run["calls"]  # the stop acts on the instance the snippet names, as sudo matches it
    assert run["calls"][-1] == ["sudo", "-n", SYSTEMCTL, "start", "peertube-engine@7071"], run["calls"]  # the start acts on the same unit, though the snippet now names 7070
    assert len(run["held"]) == 2, run["calls"]  # no other systemctl call
    assert run["held"] == [True, True]  # the deploy lock was taken before the stop and is still held at the start
    assert not _locked_by_someone(lock)  # released once the start has run


def test_main_run_with_lock_held_through_the_wait_raises_and_stops_nothing(updater, monkeypatch, tmp_path: Path, holder) -> None:
    """With the deploy lock held elsewhere through the worker's whole wait, `main` raises exactly RuntimeError out of the lock wait and runs no child process: no stop, and so no start."""
    assert _locked_by_someone(holder["lock"])  # control: the holder really holds it
    # The worker's bound is 30 minutes; zero takes the same path, the lock refused until the wait is over.
    monkeypatch.setattr(updater, "DEPLOY_LOCK_WAIT_SECONDS", 0)
    run = _run_main(updater, monkeypatch, tmp_path, holder["lock"])

    assert type(run["error"]) is RuntimeError, repr(run["error"])  # raises, and not a subclass
    assert run["calls"] == [], repr(run["error"])  # nothing stopped, so nothing to start either
    assert "acquire_deploy_lock" in [frame.name for frame in traceback.extract_tb(run["error"].__traceback__)], repr(run["error"])  # control: the raise came out of the lock wait, not out of an earlier refusal that would also stop nothing
