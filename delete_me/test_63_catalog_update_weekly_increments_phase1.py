"""With `--increments N`, `updater-worker.py` `main()` crawls one host group and refuses an untrustworthy pointer or flag set before any child runs.

- With `--increments 7` and a pointer file holding `last_group` 3, 1 or 6 at `--increment-state`, the hosts in staging `instances` when the `channels-cli.js` child runs are exactly the HOSTS whose sha1 of the stored host string, mod 7, is 4, 2 or 0: `last_group + 1` wrapped mod 7, hashed on the string as stored and not on its normalised spelling.
- A corrupt pointer file, `--increments -1`, `--increments 7 --sync-join-whitelist`, or an `--increment-state` in a directory that does not exist makes `main` raise RuntimeError with no child process run, and a pointer file written beforehand is byte-identical afterwards (no file appears in the missing directory).

`main` runs in-process down its full crawl path to `--fail-before-merge`, the `_run_crawl_main` harness of `tests/active/test_updater_worker.py` with `extra` and `state` arguments: real `schema.sql` staging and prod, an empty fake crawler `dist/`, a jobs dir under tmp_path, and only `subprocess.run` replaced. The fake `instances-cli.js` child inserts HOSTS into staging `instances`; the fake `channels-cli.js` child reads them back.
"""
from __future__ import annotations

import importlib.util
import json
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
# int(hashlib.sha1(host.encode("utf-8")).hexdigest(), 16) % 7, computed outside the helper: a.example 4, c.example 0, f.example 1, h.example 3, j.example 2, k.example 4, Mixed.Example. 4, Watch.Example. 3.
# The two unnormalised spellings swap groups when re-normalised first: mixed.example is 2, watch.example is 4.
HOSTS = ["a.example", "c.example", "f.example", "h.example", "j.example", "k.example", "Mixed.Example.", "Watch.Example."]
# (stored last_group, the hosts the channels child must see): 3 -> group 4, 1 -> group 2, 6 wraps to group 0.
GROUP_CASES = [(3, ["Mixed.Example.", "a.example", "k.example"]), (1, ["j.example"]), (6, ["c.example"])]
VALID_POINTER = b'{"last_group": 3, "increments": 7, "completed_at": "2026-10-01T20:00:00Z"}\n'
CORRUPT_POINTER = b'{"last_group": 3, "increments": '


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_increments_phase1", "updater-worker.py")


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


def _run_crawl_main(updater, monkeypatch, tmp_path: Path, *, extra: list[str] = (), state: Path | None = None) -> dict:
    """Run `main` down the crawl path to the injected before-merge failure; return what it raised, every child argv in order, and the staging hosts at each channels child."""
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
    run = {"error": None, "calls": [], "hosts_at_channels": []}

    def fake_run(cmd, **kwargs):
        run["calls"].append(list(cmd))
        if _is(cmd, "instances-cli.js"):
            # Stands in for the instances crawl writing every whitelist host into staging, stored spellings as given.
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
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    state_args = ["--increment-state", state.as_posix()] if state is not None else []
    monkeypatch.setattr(sys, "argv", ["updater-worker.py", "--skip-systemctl", "--fail-before-merge", "--cpu", "--python-bin", PYTHON_BIN, "--crawler-dir", crawler.as_posix(), "--prod-db", prod.as_posix(), "--staging-db", staging.as_posix(), "--similarity-db", (tmp_path / "similarity-cache.db").as_posix(), "--index-path", (tmp_path / "ann.faiss").as_posix(), "--index-meta-path", (tmp_path / "ann.faiss.json").as_posix(), "--lock-file", (tmp_path / "run.lock").as_posix(), "--logs", (tmp_path / "updater.log").as_posix(), *state_args, *extra])
    try:
        updater.main()
    except BaseException as exc:
        # BaseException: an argparse refusal is SystemExit, which must read as a red here, not end the session.
        run["error"] = exc
    return run


@pytest.mark.parametrize(("last_group", "expected"), GROUP_CASES, ids=["last-3-crawls-4", "last-1-crawls-2", "last-6-wraps-to-0"])
def test_the_channels_crawl_sees_only_the_hosts_of_the_group_after_the_stored_one(updater, monkeypatch, tmp_path, last_group, expected):
    """With `--increments 7` and a pointer holding `last_group`, the staging hosts at the channels child are exactly the HOSTS whose sha1(stored host) % 7 is (last_group + 1) % 7."""
    # Not the default next to --prod-db, so a run that ignores --increment-state reads no pointer and lands on group 0.
    state = tmp_path / "pointer" / "p.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"last_group": last_group, "increments": 7, "completed_at": "2026-10-01T20:00:00Z"}) + "\n", encoding="utf-8")
    run = _run_crawl_main(updater, monkeypatch, tmp_path, extra=["--increments", "7"], state=state)

    # Without --increments this harness shows all eight HOSTS at the channels child and stops at "Injected failure: before merge stage"; the second assertion holds the increments run to that same full crawl path.
    assert run["hosts_at_channels"] == [expected], (repr(run["error"]), run["hosts_at_channels"], run["calls"])  # C1
    assert type(run["error"]) is RuntimeError and str(run["error"]) == "Injected failure: before merge stage", (repr(run["error"]), run["calls"])  # control


REFUSALS = ["corrupt-pointer", "negative-increments", "with-sync-join", "missing-state-dir"]


@pytest.mark.parametrize("case", REFUSALS)
def test_an_untrustworthy_pointer_or_increment_flag_stops_the_run_before_any_child(updater, monkeypatch, tmp_path, case):
    """A corrupt pointer, `--increments -1`, `--increments 7 --sync-join-whitelist`, or a missing `--increment-state` directory makes `main` raise RuntimeError with no child run, and leaves the pointer file byte-identical."""
    state = tmp_path / ("missing" if case == "missing-state-dir" else "pointer") / "p.json"
    before = {"corrupt-pointer": CORRUPT_POINTER, "negative-increments": VALID_POINTER, "with-sync-join": VALID_POINTER}.get(case)
    if before is not None:
        state.parent.mkdir()
        state.write_bytes(before)
    extra = {"corrupt-pointer": ["--increments", "7"], "negative-increments": ["--increments", "-1"], "with-sync-join": ["--increments", "7", "--sync-join-whitelist"], "missing-state-dir": ["--increments", "7"]}[case]
    if case == "with-sync-join":
        # One join host absent from prod: a sync-join run that is not refused crawls it, so a refusal placed after the instances child shows in the calls; an empty list would run no child either way.
        join = tmp_path / "join-one.json"
        join.write_text('[{"host": "new.example"}]', encoding="utf-8")
        extra = [*extra, "--whitelist-url", join.as_uri()]
    run = _run_crawl_main(updater, monkeypatch, tmp_path, extra=extra, state=state)
    # Positive control in its own tree: a valid pointer in an existing directory with `--increments 7` alone must go ahead to the instances child and the before-merge stop, so a refusal of every `--increments` run cannot pass this test.
    control_state = tmp_path / "control-pointer" / "p.json"
    control_state.parent.mkdir()
    control_state.write_bytes(VALID_POINTER)
    control = _run_crawl_main(updater, monkeypatch, tmp_path / "control", extra=["--increments", "7"], state=control_state)

    assert type(run["error"]) is RuntimeError, repr(run["error"])  # C2: refused, and not by argparse's SystemExit
    assert run["calls"] == [], (repr(run["error"]), run["calls"])  # C2: before the instances child or any other
    if before is not None:
        assert state.read_bytes() == before  # C2
    else:
        assert not state.exists()  # C2: nothing written where the directory is missing
    # The controls come last: before the phase exists `--increments` is an unknown flag, so they can only hold once it is built, and the C2 assertions above are what judge it.
    assert type(control["error"]) is RuntimeError and str(control["error"]) == "Injected failure: before merge stage", (repr(control["error"]), control["calls"])  # control
    assert any(_is(cmd, "instances-cli.js") for cmd in control["calls"]), control["calls"]  # control
