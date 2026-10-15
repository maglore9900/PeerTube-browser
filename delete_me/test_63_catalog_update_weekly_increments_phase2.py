"""With `--increments N`, `updater-worker.py` `main()` advances the increment pointer exactly when the merge child has succeeded, and never on a run that stops before it.

- On a run that completes, the pointer file at `--increment-state` is absent (no prior pointer) or byte-identical to the prior one when the `merge-staging-db.py` child runs, and holds `last_group` equal to the group the run crawled and `increments` equal to the run's N when the `recompute-popularity.py` child runs. Read at N 7 with no pointer and with `last_group` 3, and at N 3 over that N-7 pointer, which restarts at group 0.
- A `--increments 7` run stopped by `--fail-before-merge`, by the merge child exiting non-zero, or by a `--lock-file` already holding a live pid raises, and the pointer written beforehand is byte-identical afterwards.

`main` runs in-process down its full crawl and merge path with `--skip-systemctl`, the `_run_trending_main` pattern of `tests/active/test_updater_worker.py`: real `schema.sql` staging and prod, an empty fake crawler `dist/`, a jobs dir under tmp_path, `subprocess.run` replaced, and `run_similarity_stage` replaced by a recorder. The fake children snapshot the pointer file at the merge and popularity children.
"""
from __future__ import annotations

import importlib.util
import json
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
# int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % N, computed outside the helper. N 7: a.example 4, c.example 0, f.example 1, h.example 3, j.example 2, k.example 4. N 3: a.example 2, c.example 2, f.example 0, h.example 0, j.example 1, k.example 0.
HOSTS = ["a.example", "c.example", "f.example", "h.example", "j.example", "k.example"]
PRIOR_POINTER = b'{"last_group": 3, "increments": 7, "completed_at": "2026-10-01T20:00:00Z"}\n'
# (N, prior pointer bytes, the group the run crawls, the hosts the channels child sees in that group): no pointer starts at 0, last_group 3 of 7 crawls 4, and an N-7 pointer read at N 3 restarts at 0.
SUCCESS_CASES = [(7, None, 0, ["c.example"]), (7, PRIOR_POINTER, 4, ["a.example", "k.example"]), (3, PRIOR_POINTER, 0, ["f.example", "h.example", "k.example"])]


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_increments_phase2", "updater-worker.py")


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
    """Run `main` with `--increments <increments>` down the crawl and merge path; return what it raised, every child argv in order, the staging hosts at each channels child, the pointer bytes (None when absent) at each merge and popularity child, and the similarity stage calls."""
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
    run = {"error": None, "calls": [], "hosts_at_channels": [], "pointer_at_merge": [], "pointer_at_popularity": [], "similarity": []}

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
        return subprocess.CompletedProcess(cmd, 0)

    def similarity(**kwargs):
        run["similarity"].append(kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(updater, "run_similarity_stage", similarity)
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--skip-systemctl", "--cpu", "--python-bin", PYTHON_BIN, "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", staging.as_posix(), "--similarity-db", (tmp_path / "similarity-cache.db").as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix(), "--increments", str(increments), "--increment-state", state.as_posix(), *extra])
    try:
        updater.main()
    except BaseException as exc:
        # BaseException: an argparse refusal is SystemExit, which must read as a red here, not end the session.
        run["error"] = exc
    return run


def _pointer(tmp_path: Path, prior: bytes | None) -> Path:
    # Not the default next to --prod-db, so a run that ignores --increment-state neither reads nor writes this file.
    state = tmp_path / "pointer" / "p.json"
    state.parent.mkdir()
    if prior is not None:
        state.write_bytes(prior)
    return state


@pytest.mark.parametrize(("increments", "prior", "group", "hosts"), SUCCESS_CASES, ids=["n7-no-pointer-crawls-0", "n7-last-3-crawls-4", "n3-over-n7-pointer-crawls-0"])
def test_a_completed_run_records_the_crawled_group_after_the_merge_child_and_before_the_popularity_child(updater, monkeypatch, tmp_path, increments, prior, group, hosts):
    """On a completed `--increments N` run, the pointer is absent or still the prior bytes at the merge child, and holds `last_group` = the crawled group and `increments` = N at the popularity child."""
    state = _pointer(tmp_path, prior)
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state, increments=increments)

    assert run["error"] is None, (repr(run["error"]), run["calls"])  # control: the run completed
    assert len(run["similarity"]) == 1, run["similarity"]  # control: down to the similarity stage, past every post-merge step
    assert run["hosts_at_channels"] == [hosts], run["hosts_at_channels"]  # control: the run crawled `group`, independent of what it writes
    assert run["pointer_at_merge"] == [prior], (run["pointer_at_merge"], run["calls"])  # C1: not written before the merge child
    assert len(run["pointer_at_popularity"]) == 1 and run["pointer_at_popularity"][0] is not None, (run["pointer_at_popularity"], run["calls"])  # C1: written by the popularity child, not at the end of the run
    written = json.loads(run["pointer_at_popularity"][0])
    assert written["last_group"] == group, written  # C1: the crawled group, not the prior one or its successor
    assert written["increments"] == increments, written  # the run's N, not the prior pointer's or a constant, so the next run reads the pointer back


STOPS = ["fail-before-merge", "merge-child-fails", "run-lock-held"]


@pytest.mark.parametrize("stop", STOPS)
def test_a_run_that_stops_before_the_merge_commits_leaves_the_pointer_byte_identical(updater, monkeypatch, tmp_path, stop):
    """A `--increments 7` run stopped by `--fail-before-merge`, a merge child exiting 1, or a `--lock-file` holding a live pid raises and leaves the prior pointer byte-identical."""
    state = _pointer(tmp_path, PRIOR_POINTER)
    if stop == "run-lock-held":
        # single_run_lock creates the file O_EXCL and writes its pid; an existing file naming a live pid is a running updater. This process's pid is live.
        (tmp_path / "run.lock").write_text(str(os.getpid()), encoding="utf-8")
    run = _run_increment_main(updater, monkeypatch, tmp_path, state=state, extra=["--fail-before-merge"] if stop == "fail-before-merge" else [], fail_merge=stop == "merge-child-fails")

    # Controls first: each run stopped where its case says, so a red on the identity below is never a run that stopped somewhere else.
    if stop == "fail-before-merge":
        assert type(run["error"]) is RuntimeError and str(run["error"]) == "Injected failure: before merge stage", repr(run["error"])
        assert run["hosts_at_channels"] == [["a.example", "k.example"]] and run["pointer_at_merge"] == [], run["calls"]
    elif stop == "merge-child-fails":
        assert type(run["error"]) is subprocess.CalledProcessError, repr(run["error"])
        assert run["pointer_at_merge"] == [PRIOR_POINTER] and run["pointer_at_popularity"] == [], run["calls"]
    else:
        assert type(run["error"]) is RuntimeError and str(run["error"]).startswith(f"Another updater run is active (pid={os.getpid()})"), repr(run["error"])
        assert run["calls"] == [], run["calls"]
    assert state.read_bytes() == PRIOR_POINTER, state.read_bytes()  # C2
