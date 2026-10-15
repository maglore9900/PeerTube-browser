"""With `--increments 7`, `updater-worker.py` `main()` logs one `pointer not advanced` record for every run that read the pointer and did not advance it, and holds a failed pointer write until the global post-merge steps have run.

- A run stopped by `--fail-before-merge` or by the merge child exiting 1 logs exactly one record containing that failure's reason; a run refused at `--lock-file`, which logs no `increment read`, and a completed run log none, while a `--fail-before-merge` run in the same test logs one.
- With the pointer write's `os.replace` onto the pointer raising `OSError("disk full")`, the ANN build child and the trending child run and the similarity stage swaps its cache in, and then the run raises a `RuntimeError` containing `increment pointer not advanced`. It logs no `worker completed` record and exactly one `pointer not advanced` record, which carries `disk full`.

`main` runs in-process down its full crawl and merge path with `--skip-systemctl`, the phase-2 `_run_increment_main` harness: real `schema.sql` staging and prod, an empty fake crawler `dist/`, a jobs dir under tmp_path, and `subprocess.run` replaced. The real `write_increment_pointer` and `run_similarity_stage` run; the fake precompute child writes an empty shadow cache. Log records are read from caplog at INFO.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# parse_args imports server_config from the repo the module's script_dir sits in; a relocated jobs dir has none, so the real one must already be importable.
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from data.ann_ids import create_video_embeddings_table  # noqa: E402

JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
PYTHON_BIN = "/opt/updater-python"
JOB_SCRIPTS = ("merge-staging-db.py", "build-video-embeddings.py", "recompute-popularity.py", "precompute-similar-ann.py", "build-ann-index.py", "fetch-trending.py")
# int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % 7, computed outside the helper: a.example 4, c.example 0, f.example 1, h.example 3, j.example 2, k.example 4.
HOSTS = ["a.example", "c.example", "f.example", "h.example", "j.example", "k.example"]
# last_group 3 of 7: the run crawls group 4.
PRIOR_POINTER = b'{"last_group": 3, "increments": 7, "completed_at": "2026-10-01T20:00:00Z"}\n'
NOT_ADVANCED = "pointer not advanced"


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_increments_phase3", "updater-worker.py")


def _jobs(tmp_path: Path) -> Path:
    # Laid out like the repo, so the module's script_dir.parents[3] is a repo root here too.
    jobs = tmp_path / "repo" / "engine" / "server" / "db" / "jobs"
    jobs.mkdir(parents=True)
    for name in JOB_SCRIPTS:
        (jobs / name).write_bytes(b"")
    (jobs / "merge_rules.json").write_text("{}", encoding="utf-8")
    return jobs


def _is(cmd: list[str], name: str) -> bool:
    return any(Path(part).name == name for part in cmd)


def _snapshot(state: Path) -> bytes | None:
    return state.read_bytes() if state.exists() else None


def _run_increment_main(updater, monkeypatch, tmp_path: Path, *, state: Path, increments: int = 7, extra: list[str] = (), fail_merge: bool = False) -> dict:
    """Run `main` with `--increments <increments>` down the crawl and merge path; return what it raised, every child argv in order, the staging hosts at each channels child, the pointer bytes (None when absent) at each merge and popularity child, and whether the similarity stage swapped a cache in."""
    jobs = _jobs(tmp_path)
    monkeypatch.setattr(updater, "script_dir", jobs)
    crawler = tmp_path / "crawler"
    (crawler / "dist").mkdir(parents=True)
    (crawler / "schema.sql").write_bytes((ROOT / "engine" / "crawler" / "schema.sql").read_bytes())
    for name in ("instances-cli.js", "channels-cli.js", "videos-cli.js", "channels-videos-count-cli.js"):
        (crawler / "dist" / name).write_bytes(b"")
    prod = tmp_path / "prod.db"
    conn = sqlite3.connect(prod.as_posix())
    try:
        conn.executescript((crawler / "schema.sql").read_text(encoding="utf-8"))
        create_video_embeddings_table(conn)
        conn.commit()
    finally:
        conn.close()
    staging = tmp_path / "staging.db"
    similarity_db = tmp_path / "similarity-cache.db"
    run = {"error": None, "calls": [], "hosts_at_channels": [], "pointer_at_merge": [], "pointer_at_popularity": [], "similarity_swapped": False}

    def fake_run(cmd, **kwargs):
        run["calls"].append(list(cmd))
        if _is(cmd, "instances-cli.js"):
            # Stands in for the instances crawl writing every whitelist host into staging.
            built = sqlite3.connect(staging.as_posix())
            try:
                built.executemany("INSERT OR IGNORE INTO instances(host) VALUES (?)", [(host,) for host in HOSTS])
                built.commit()
            finally:
                built.close()
        if _is(cmd, "channels-cli.js"):
            seen = sqlite3.connect(staging.as_posix())
            try:
                run["hosts_at_channels"].append(sorted(row[0] for row in seen.execute("SELECT host FROM instances")))
            finally:
                seen.close()
        if _is(cmd, "build-video-embeddings.py"):
            # Stands in for the embeddings job's own schema step, which the staging delta count reads.
            built = sqlite3.connect(staging.as_posix())
            try:
                create_video_embeddings_table(built)
                built.commit()
            finally:
                built.close()
        if _is(cmd, "merge-staging-db.py"):
            run["pointer_at_merge"].append(_snapshot(state))
            if fail_merge:
                # What subprocess.run(check=True) raises for a merge child exiting 1.
                raise subprocess.CalledProcessError(1, cmd)
        if _is(cmd, "recompute-popularity.py"):
            run["pointer_at_popularity"].append(_snapshot(state))
        if _is(cmd, "precompute-similar-ann.py"):
            # Stands in for the precompute child writing its shadow: the two tables the similarity gate requires, with no sources.
            built = sqlite3.connect(cmd[cmd.index("--out") + 1])
            try:
                built.executescript("CREATE TABLE video_keys (video_id TEXT); CREATE TABLE similarity_sources (video_id TEXT);")
                built.commit()
            finally:
                built.close()
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--skip-systemctl", "--cpu", "--python-bin", PYTHON_BIN, "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", staging.as_posix(), "--similarity-db", similarity_db.as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix(), "--increments", str(increments), "--increment-state", state.as_posix(), *extra])
    try:
        updater.main()
    except BaseException as exc:
        # BaseException: an argparse refusal is SystemExit, which must read as a red here, not end the session.
        run["error"] = exc
    # No cache existed before the run, so a cache file here is the similarity stage's own swap.
    run["similarity_swapped"] = similarity_db.exists()
    return run


def _pointer(tmp_path: Path, prior: bytes | None) -> Path:
    # Not the default next to --prod-db, so a run that ignores --increment-state neither reads nor writes this file.
    state = tmp_path / "pointer" / "p.json"
    state.parent.mkdir()
    if prior is not None:
        state.write_bytes(prior)
    return state


def _messages(caplog, needle: str) -> list[str]:
    return [record.getMessage() for record in caplog.records if needle in record.getMessage()]


# (stop, a literal the failure's own message carries): the injected RuntimeError's text, and the exit status str(CalledProcessError) names.
PRE_MERGE_STOPS = [("fail-before-merge", "Injected failure: before merge stage"), ("merge-child-fails", "exit status 1")]


@pytest.mark.parametrize(("stop", "reason"), PRE_MERGE_STOPS, ids=[stop for stop, _ in PRE_MERGE_STOPS])
def test_a_run_failing_before_the_merge_commits_logs_one_pointer_not_advanced_line_with_the_reason(updater, monkeypatch, tmp_path, caplog, stop, reason):
    """A `--increments 7` run that read the pointer and was stopped by `--fail-before-merge` or by the merge child exiting 1 logs exactly one `pointer not advanced` record, and that record contains the failure's reason."""
    caplog.set_level(logging.INFO)
    state = _pointer(tmp_path, PRIOR_POINTER)
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state, extra=["--fail-before-merge"] if stop == "fail-before-merge" else [], fail_merge=stop == "merge-child-fails")

    # Controls: the run read the pointer (crawled group 4) and stopped where its case says, so the count below is about the stop and not an earlier refusal.
    assert run["hosts_at_channels"] == [["a.example", "k.example"]], (repr(run["error"]), run["calls"])
    if stop == "fail-before-merge":
        assert type(run["error"]) is RuntimeError and str(run["error"]) == "Injected failure: before merge stage", repr(run["error"])
        assert run["pointer_at_merge"] == [], run["calls"]
    else:
        assert type(run["error"]) is subprocess.CalledProcessError and run["error"].returncode == 1, repr(run["error"])
        assert run["pointer_at_merge"] == [PRIOR_POINTER] and run["pointer_at_popularity"] == [], run["calls"]
    lines = _messages(caplog, NOT_ADVANCED)
    assert len(lines) == 1, lines  # C1: one line, not none and not one from both an inner and an outer handler
    assert reason in lines[0], lines  # C1: the line carries the failure's reason


def _run_armed(updater, monkeypatch, tmp_path: Path) -> dict:
    """Run a `--fail-before-merge` stop in its own directory under tmp_path, unlocked and with the prior pointer: the positive control that this harness, on the code under test, does log `increment read` and `pointer not advanced`."""
    armed = tmp_path / "armed"
    armed.mkdir()
    return _run_increment_main(updater, monkeypatch, armed, state=_pointer(armed, PRIOR_POINTER), extra=["--fail-before-merge"])


def test_a_run_refused_by_the_run_lock_logs_no_pointer_not_advanced_line(updater, monkeypatch, tmp_path, caplog):
    """A `--increments 7` run refused because `--lock-file` holds a live pid logs no `increment read` record, so it never read the pointer, and no `pointer not advanced` record; the same harness unlocked and stopped by `--fail-before-merge` then logs one of each."""
    caplog.set_level(logging.INFO)
    state = _pointer(tmp_path, PRIOR_POINTER)
    # single_run_lock creates the file O_EXCL and writes its pid; an existing file naming a live pid is a running updater. This process's pid is live.
    (tmp_path / "run.lock").write_text(str(os.getpid()), encoding="utf-8")
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state)

    assert type(run["error"]) is RuntimeError and str(run["error"]).startswith(f"Another updater run is active (pid={os.getpid()})"), repr(run["error"])  # control: refused at the lock
    assert run["calls"] == [], run["calls"]
    assert len(_messages(caplog, "worker start")) == 1, caplog.messages  # control: caplog sees this run's INFO records, so the absences below are not a capture gap
    assert _messages(caplog, "increment read") == [], caplog.messages  # the refused run never read the pointer
    assert _messages(caplog, NOT_ADVANCED) == []  # C1: a run that never read the pointer logs no such line

    armed = _run_armed(updater, monkeypatch, tmp_path)
    assert str(armed["error"]) == "Injected failure: before merge stage", (repr(armed["error"]), armed["calls"])  # control: the unlocked run reached the injected stop
    assert len(_messages(caplog, "increment read")) == 1, caplog.messages  # positive control: a run that reads the pointer logs this record, so its absence above means no read
    lines = _messages(caplog, NOT_ADVANCED)
    assert len(lines) == 1 and "Injected failure: before merge stage" in lines[0], lines  # positive control: the code under test logs the record when it must, so the empty count above is a decline


def test_a_completed_run_logs_worker_completed_and_no_pointer_not_advanced_line(updater, monkeypatch, tmp_path, caplog):
    """A completed `--increments 7` run logs one `worker completed` record and no `pointer not advanced` record; the same harness stopped by `--fail-before-merge` then logs exactly one."""
    caplog.set_level(logging.INFO)
    state = _pointer(tmp_path, PRIOR_POINTER)
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state)

    assert run["error"] is None, (repr(run["error"]), run["calls"])
    assert len(_messages(caplog, "worker completed")) == 1, caplog.messages  # control: caplog sees this INFO record, so its absence below is not a capture gap
    assert _messages(caplog, NOT_ADVANCED) == []  # C1, C2: a run whose pointer advanced logs no such line

    armed = _run_armed(updater, monkeypatch, tmp_path)
    assert str(armed["error"]) == "Injected failure: before merge stage", (repr(armed["error"]), armed["calls"])  # control: the second run reached the injected stop
    lines = _messages(caplog, NOT_ADVANCED)
    assert len(lines) == 1 and "Injected failure: before merge stage" in lines[0], lines  # positive control: the code under test logs the record when it must, so the empty count above is a decline


def test_a_failed_pointer_write_runs_ann_trending_and_similarity_then_fails_the_run(updater, monkeypatch, tmp_path, caplog):
    """With the pointer write's `os.replace` onto the pointer raising `OSError("disk full")` after the merge, the ANN build child and the trending child run and the similarity stage swaps its cache in. The run then raises a `RuntimeError` containing `increment pointer not advanced`, logs no `worker completed` record, and logs exactly one `pointer not advanced` record, which carries `disk full`."""
    caplog.set_level(logging.INFO)
    state = _pointer(tmp_path, PRIOR_POINTER)
    real_replace = os.replace
    written = []

    def failing_replace(src, dst, *args, **kwargs):
        # Only the replace onto the pointer fails; the similarity swap's own os.replace goes through.
        if Path(dst) == state.resolve():
            written.append(json.loads(Path(src).read_bytes()))
            raise OSError("disk full")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state)

    assert [(payload["last_group"], payload["increments"]) for payload in written] == [(4, 7)], written  # control: the real write reached its replace once, for the crawled group
    assert run["pointer_at_merge"] == [PRIOR_POINTER] and state.read_bytes() == PRIOR_POINTER, run["calls"]  # control: the merge child ran and the failed write left the pointer unadvanced
    assert any(_is(cmd, "build-ann-index.py") for cmd in run["calls"]), (repr(run["error"]), run["calls"])  # C2: not propagated at the write, which would skip the ANN build
    assert any(_is(cmd, "fetch-trending.py") for cmd in run["calls"]), (repr(run["error"]), run["calls"])  # C2: the trending child ran
    assert run["similarity_swapped"] is True, (repr(run["error"]), run["calls"])  # C2: the similarity stage ran to its swap
    assert type(run["error"]) is RuntimeError, repr(run["error"])  # C2: the run fails, not swallowed into a green run
    assert "increment pointer not advanced" in str(run["error"]), str(run["error"])  # C2
    assert _messages(caplog, "worker completed") == [], caplog.messages  # C2: the run did not report completion
    lines = _messages(caplog, NOT_ADVANCED)
    assert len(lines) == 1, lines  # C2: logged once, not by both the write handler and the outer handler
    assert "disk full" in lines[0], lines  # C2: the line carries the write's error
