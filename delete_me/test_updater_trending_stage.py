"""`updater-worker.py` runs `fetch-trending.py` against the prod DB, with the run's concurrency, timeout and retry flags, once the Engine is started again and before the similarity stage; a failed trending child still lets the similarity stage run once, and only then does the run raise `RuntimeError("trending stage failed")`.

- A run that succeeds runs exactly one trending child, `<python-bin> <jobs>/fetch-trending.py` with exactly `--db <prod> --concurrency --timeout-ms --max-retries` as the run passed them (4/5000/3 by default, 7/1234/5 when given), after the systemctl start and before the one similarity stage call, and logs "worker completed".
- In `main`'s source, the `run_cmd` call naming `fetch-trending.py` sits after the whole `try` whose `finally` starts the service and before the `run_similarity_stage` call; run with a failure injected inside that `try`, `main` runs no trending child and no similarity stage.
- With `fetch-trending.py` missing from the jobs dir, `main` raises FileNotFoundError naming it before any child runs.
- With the trending child failing, the similarity stage runs exactly once, after it, and `main` then raises exactly `RuntimeError("trending stage failed")` without logging "worker completed".

`main` runs in-process down its sync-join path (one stale prod host, an empty join list), which reaches the stop without crawling. Only the child processes are replaced, at `subprocess.run`, and `run_similarity_stage` is a recorder, since its own behaviour is gated by `tests/active/test_updater_worker.py`. The module's `script_dir` points at a jobs dir under `tmp_path` laid out like the repo's, so a required script can be left out and the child argv names a path the test wrote down itself.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# parse_args imports server_config from the repo the module's script_dir sits in; the relocated jobs dir has none, so the real one must already be importable.
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

JOBS_DIR = SERVER_DIR / "db" / "jobs"
UPDATER = JOBS_DIR / "updater-worker.py"
SYSTEMCTL = "/usr/bin/systemctl"
PYTHON_BIN = "/opt/updater-python"
STOP = ["sudo", "-n", SYSTEMCTL, "stop", "peertube-engine"]
START = ["sudo", "-n", SYSTEMCTL, "start", "peertube-engine"]
JOB_SCRIPTS = ("merge-staging-db.py", "build-video-embeddings.py", "recompute-popularity.py", "precompute-similar-ann.py", "build-ann-index.py")
# (flags passed to the updater, the values the trending child must carry): the defaults, and values no stage hard-codes.
RUN_FLAGS = [([], {"--concurrency": "4", "--timeout-ms": "5000", "--max-retries": "3"}), (["--concurrency", "7", "--timeout-ms", "1234", "--max-retries", "5"], {"--concurrency": "7", "--timeout-ms": "1234", "--max-retries": "5"})]


@pytest.fixture(scope="module")
def updater():
    spec = importlib.util.spec_from_file_location("updater_worker_trending_phase3", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jobs(tmp_path: Path, *, with_trending: bool = True) -> Path:
    # Laid out like the repo, so the module's script_dir.parents[3] is a repo root here too.
    jobs = tmp_path / "repo" / "engine" / "server" / "db" / "jobs"
    jobs.mkdir(parents=True)
    for name in JOB_SCRIPTS + (("fetch-trending.py",) if with_trending else ()):
        (jobs / name).write_bytes(b"")
    (jobs / "merge_rules.json").write_text("{}", encoding="utf-8")
    return jobs


def _is_trending(cmd: list[str]) -> bool:
    return any(Path(part).name == "fetch-trending.py" for part in cmd)


def _run(updater, monkeypatch, tmp_path: Path, *, extra: list[str] = (), with_trending: bool = True, fail_trending: bool = False) -> dict:
    """Run `main` down the sync-join path with the jobs dir relocated; return what it raised and, in order, every child argv and every similarity stage call."""
    jobs = _jobs(tmp_path, with_trending=with_trending)
    monkeypatch.setattr(updater, "script_dir", jobs)
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
    run = {"error": None, "events": [], "jobs": jobs, "prod": prod}

    def fake_run(cmd, **kwargs):
        run["events"].append(("child", list(cmd)))
        if fail_trending and _is_trending(list(cmd)):
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    def similarity(**kwargs):
        run["events"].append(("similarity", kwargs))

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(updater, "run_similarity_stage", similarity)
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--service-name", "peertube-engine", "--systemctl-bin", SYSTEMCTL, "--systemctl-use-sudo", "--sync-join-whitelist", "--yes", "--whitelist-url", join.as_uri(), "--cpu", "--python-bin", PYTHON_BIN, "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", (tmp_path / "staging.db").as_posix(), "--similarity-db", (tmp_path / "similarity-cache.db").as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix(), *extra])
    try:
        updater.main()
    except Exception as exc:
        run["error"] = exc
    return run


def _children(run: dict) -> list[list[str]]:
    return [payload for kind, payload in run["events"] if kind == "child"]


def _position(run: dict, match) -> list[int]:
    return [index for index, event in enumerate(run["events"]) if match(event)]


def _completed(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if "worker completed" in record.getMessage()]


@pytest.mark.parametrize(("flags", "expected"), RUN_FLAGS, ids=["default-flags", "given-flags"])
def test_trending_child_runs_against_prod_with_the_run_flags_after_the_engine_start_and_before_similarity(updater, monkeypatch, tmp_path, caplog, flags, expected):
    """A succeeding run runs one `<python-bin> <jobs>/fetch-trending.py` with exactly `--db <prod>` and the run's concurrency, timeout and retry values, after the systemctl start and before the one similarity stage call, and completes."""
    caplog.set_level(logging.INFO)
    run = _run(updater, monkeypatch, tmp_path, extra=flags)

    assert run["error"] is None, repr(run["error"])  # control: the run went through to the end
    assert _completed(caplog), [record.getMessage() for record in caplog.records]  # control: a completed run logs it, so its absence in the failure test is observable
    trending = [cmd for cmd in _children(run) if _is_trending(cmd)]
    assert len(trending) == 1, _children(run)  # C1 the trending child runs, once
    cmd = trending[0]
    assert cmd[:2] == [PYTHON_BIN, (run["jobs"] / "fetch-trending.py").as_posix()], cmd  # C1 the job script under the run's interpreter
    options = cmd[2:]
    assert len(options) % 2 == 0, cmd
    assert dict(zip(options[::2], options[1::2])) == {"--db": run["prod"].as_posix(), **expected} and len(options) == 8, cmd  # C1 the prod DB, not staging, and the run's own concurrency, timeout and retries
    starts = _position(run, lambda event: event == ("child", START))
    trending_at = _position(run, lambda event: event[0] == "child" and _is_trending(event[1]))
    similarity_at = _position(run, lambda event: event[0] == "similarity")
    assert len(starts) == 1 and len(similarity_at) == 1, run["events"]  # control: one start and one similarity stage to order against
    assert starts[0] < trending_at[0] < similarity_at[0], run["events"]  # C1 the Engine serves again before the trending child, and similarity follows it


def _layout(source: str) -> tuple[list[int], list[int], list[int]]:
    """Return, for `main` in `source`, the end lines of the `try`s whose `finally` starts the service, the lines of the `run_similarity_stage` calls, and the lines of the `run_cmd` calls naming `fetch-trending.py` directly or through a name assigned from it."""
    main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    service_trys = [node.end_lineno for node in ast.walk(main) if isinstance(node, ast.Try) and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "systemctl_cmd" and any(kw.arg == "action" and isinstance(kw.value, ast.Constant) and kw.value.value == "start" for kw in call.keywords) for stmt in node.finalbody for call in ast.walk(stmt))]
    stage_calls = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_similarity_stage"]
    names: set[str] = set()

    def names_trending(node: ast.AST) -> bool:
        return any((isinstance(sub, ast.Constant) and sub.value == "fetch-trending.py") or (isinstance(sub, ast.Name) and sub.id in names) for sub in ast.walk(node))

    # Followed to a fixed point, so `script = ... "fetch-trending.py"`, `cmd = [..., script.as_posix()]`, `run_cmd(cmd)` is found as well as the inline argv the other stages use.
    while True:
        found = {target.id for node in ast.walk(main) if isinstance(node, ast.Assign) and names_trending(node.value) for target in node.targets if isinstance(target, ast.Name)}
        if found <= names:
            break
        names |= found
    trending_calls = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_cmd" and names_trending(node)]
    return service_trys, stage_calls, trending_calls


def test_trending_call_sits_after_the_service_try_and_before_the_similarity_stage() -> None:
    """In `main`'s source, the one `run_cmd` call naming `fetch-trending.py` comes after the whole `try` whose `finally` starts the service and before the `run_similarity_stage` call."""
    # rat-tail: a source scan for the placement, since a trending call inside that `finally` behind a success guard runs in the same order as the right one; the injected-failure run below observes the consequence.
    service_trys, stage_calls, trending_calls = _layout(UPDATER.read_text(encoding="utf-8"))
    assert len(service_trys) == 1, service_trys  # control: the service-start `try` is identified, and only one
    assert len(stage_calls) == 1, stage_calls  # control

    assert len(trending_calls) == 1, trending_calls  # C1 one run_cmd names the trending script
    assert service_trys[0] < trending_calls[0] < stage_calls[0], (service_trys, trending_calls, stage_calls)  # C1 after the whole service `try`, its `finally` included, and before similarity


def test_a_failure_inside_the_service_try_runs_no_trending_child(updater, monkeypatch, tmp_path) -> None:
    """With a failure injected after the ANN build inside the service `try`, `main` raises with the service started again and runs no trending child and no similarity stage."""
    run = _run(updater, monkeypatch, tmp_path, extra=["--fail-after-merge-before-similarity"])

    assert type(run["error"]) is RuntimeError and "before similarity" in str(run["error"]), repr(run["error"])  # control: the injected failure, not another raise
    assert any(Path(part).name == "build-ann-index.py" for cmd in _children(run) for part in cmd), _children(run)  # control: the run reached the end of the service `try`
    assert _children(run)[-1] == START, _children(run)  # control: the `finally` started the service
    assert not [cmd for cmd in _children(run) if _is_trending(cmd)], _children(run)  # C1 the trending child sits past the `try`, so a raise inside it skips the child
    assert not _position(run, lambda event: event[0] == "similarity"), run["events"]


def test_a_missing_fetch_trending_script_stops_the_run_before_any_child(updater, monkeypatch, tmp_path) -> None:
    """With every other job script present and `fetch-trending.py` absent, `main` raises FileNotFoundError naming it and runs no child."""
    run = _run(updater, monkeypatch, tmp_path, with_trending=False)

    assert type(run["error"]) is FileNotFoundError, repr(run["error"])  # checkpoint coverage, not a clause: the trending script is a required file
    assert "fetch-trending.py" in str(run["error"]), str(run["error"])  # and it is the one reported missing
    assert run["events"] == [], run["events"]  # checked up front, before the Engine is stopped


def test_a_failed_trending_child_still_runs_similarity_once_then_raises_trending_stage_failed(updater, monkeypatch, tmp_path, caplog) -> None:
    """When the trending child exits non-zero, the similarity stage still runs exactly once, after it, and `main` then raises exactly `RuntimeError("trending stage failed")` without logging "worker completed"."""
    caplog.set_level(logging.INFO)
    run = _run(updater, monkeypatch, tmp_path, fail_trending=True)

    assert type(run["error"]) is RuntimeError, repr(run["error"])  # C2 the run fails, with exactly RuntimeError, not the child's CalledProcessError
    assert str(run["error"]) == "trending stage failed", repr(run["error"])  # C2
    trending_at = _position(run, lambda event: event[0] == "child" and _is_trending(event[1]))
    similarity_at = _position(run, lambda event: event[0] == "similarity")
    assert len(trending_at) == 1, _children(run)  # control: the failing child ran, once
    assert _position(run, lambda event: event == ("child", START))[0] < trending_at[0], run["events"]  # control: it failed with the Engine already serving
    assert len(similarity_at) == 1, run["events"]  # C2 similarity still runs, once
    assert trending_at[0] < similarity_at[0], run["events"]  # C2 after the failed trending child
    assert _completed(caplog) == [], _completed(caplog)  # C2 the run does not report completion
