"""`updater-worker.py` builds its similarity precompute argv with `--refresh-existing` and never `--recreate-out-db`, and its CPU retry keeps that flag; it clears a crashed similarity build's leftovers, builds the cache in a shadow that only a passing gate swaps in, runs that stage once the Engine serves again, and re-prunes prod's current denylist from the shadow.

- `similarity_precompute_cmd` returns, token for token, the precompute argv with `--refresh-existing` after `--search-batch-size 1024`, ending in `--gpu --gpu-device 0` or `--cpu`, and without `--recreate-out-db`.
- `_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included.
- `main` calls `similarity_precompute_cmd`, and no `--recreate-out-db` literal is left anywhere in the module.
- `cleanup_similarity_leftovers` removes a `<cache>.building` marker holding a dead PID, `garbage`, the empty string, `0`, `-1` or `99999999999`, logging its path and pid; it keeps a live-PID marker; it removes `.next.db` and `.next.db-journal` each on its own, and never touches the active file.
- `run_similarity_stage` with a passing build makes the precompute's shadow file the active cache and keeps the replaced inode as `.prev.db`; with no active file it writes none; a forced gate, fewer sources, a corrupt shadow or a failed precompute raises and leaves the active file byte-identical with no `.prev.db`; no shadow, journal or marker outlives any run.
- `main` runs `run_similarity_stage` once, after the `try` whose `finally` starts the service, with no precompute left inside that `try`; a host denied in prod during the build has no row in the cache the stage swaps in.

With `--engine-upstream-snippet` it stops and starts the `peertube-engine@<port>` instance the snippet names, under the blue/green deploy flock.

- `parse_upstream_snippet` returns the port for every accepted case of `tests/active/upstream_snippet_cases.json` and of the inline case table, and raises ValueError for every rejected one and for a missing file.
- `engine_instance_unit` spells 7070 and 7071 exactly as the sudoers rule does, with no `.service`, and refuses 7069 and 7072; the resolved unit reaches `systemctl_cmd` as the literal sudoers argv.
- `parse_args` takes `--engine-upstream-snippet` and defaults `--deploy-lock-file` to the repo's `engine/server/db/engine-deploy.lock`.
- `acquire_deploy_lock` raises exactly RuntimeError when another holder keeps the flock through the wait, whether the wait is zero or a bounded positive one, returns an fd that really holds the flock once it is free, including on a 0444 file, and `release_deploy_lock` frees it and closes the fd.
- Run with the lock free and a 7071 snippet, `main` runs the sudoers stop and start of `peertube-engine@7071` as its first and last child, the lock held at both, and the start stays on 7071 when the snippet is rewritten after the stop; the lock is free once `main` is done.
- Run with the lock held through the worker's wait, `main` raises exactly RuntimeError out of the lock wait and runs no child at all, so nothing is stopped.
- In `main`'s source, the lock is taken with a positive finite wait before the snippet is parsed and before the stop, the unit is resolved once from the snippet file, both `systemctl_cmd` calls pass that one `engine_unit`, and the release runs in the `finally` of the `try` that starts it.

The module is loaded in-process from its file, the way `test_host_normalisation._load_job` does. For the stage, only the child process is replaced, at `subprocess.run`, so the updater's own `run_with_cpu_fallback` and `run_cmd` run for real. A live PID is a sleeping child; a dead PID is a child already waited on. Every cache file lives under `tmp_path`. The deploy flock holder is a second open file description in the test process, which conflicts with the module's own exactly as another process would; `main` runs in-process down its sync-join path, which reaches the stop without crawling.
"""
from __future__ import annotations

import ast
import fcntl
import importlib.util
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest
from conftest import ROOT

SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import ensure_moderation_schema, purge_similarity_for_host  # noqa: E402
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402

JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"
UPDATER = JOBS_DIR / "updater-worker.py"
HOST = "h.example"
# None is a reaped child's PID. os.kill(0, 0) and os.kill(-1, 0) succeed and 99999999999 raises OverflowError, so each needs the parser's own guard.
NON_BLOCKING = [None, "garbage", "", "0", "-1", "99999999999"]
NON_BLOCKING_IDS = ["dead-pid", "garbage", "empty", "zero", "negative", "oversized"]
REPRUNE_SOURCES = [("v1", "bad.example"), ("v2", "ok.example"), ("v3", "lifted.example")]
REPRUNE_ITEMS = [("v1", "bad.example", "v2", "ok.example"), ("v2", "ok.example", "v1", "bad.example"), ("v2", "ok.example", "v3", "lifted.example"), ("v3", "lifted.example", "v2", "ok.example")]


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def updater():
    return _load_job("updater_worker_precompute", "updater-worker.py")


def _paths(tmp_path: Path) -> dict[str, Path]:
    # Four distinct paths, so a builder that swaps two of them fails the exact comparison.
    return {"script_path": tmp_path / "jobs" / "precompute-similar-ann.py", "db_path": tmp_path / "prod.db", "index_path": tmp_path / "ann.faiss", "out_path": tmp_path / "similarity-cache.db"}


@pytest.mark.parametrize(("use_gpu", "suffix"), [(True, ["--gpu", "--gpu-device", "0"]), (False, ["--cpu"])], ids=["gpu", "cpu"])
def test_updater_builds_refresh_command(updater, tmp_path: Path, use_gpu: bool, suffix: list[str]) -> None:
    """The builder's argv is the precompute command token for token, with `--refresh-existing` and never `--recreate-out-db`, and the accelerator suffix for `use_gpu`."""
    cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=use_gpu, **_paths(tmp_path))

    assert cmd == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", *suffix]
    assert "--recreate-out-db" not in cmd


def test_cpu_fallback_keeps_refresh(updater, tmp_path: Path) -> None:
    """`_to_cpu_cmd` over the GPU argv gives exactly the CPU argv, `--refresh-existing` still in its slot."""
    gpu_cmd = updater.similarity_precompute_cmd(python_bin="python3", use_gpu=True, **_paths(tmp_path))
    # `run_with_cpu_fallback` retries only a command carrying `--gpu`; without it the retry below is never taken.
    assert gpu_cmd[-3:] == ["--gpu", "--gpu-device", "0"], gpu_cmd

    assert updater._to_cpu_cmd(gpu_cmd) == ["python3", f"{tmp_path}/jobs/precompute-similar-ann.py", "--db", f"{tmp_path}/prod.db", "--index", f"{tmp_path}/ann.faiss", "--out", f"{tmp_path}/similarity-cache.db", "--top-k", "1000", "--nprobe", "16", "--search-batch-size", "1024", "--refresh-existing", "--cpu"]


def test_updater_main_uses_builder() -> None:
    """`main` calls `similarity_precompute_cmd`, and the module holds no `--recreate-out-db` string literal."""
    # rat-tail: a source scan, because reaching the precompute stage through `main` means running the whole crawl/merge/ANN pipeline; a pipeline harness with the stage commands shimmed would replace it.
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    called = {node.func.id for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    assert "similarity_precompute_cmd" in called, sorted(called)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
    # `_to_cpu_cmd` matches the `--gpu-device` literal, so the scan below is shown to see the module's string constants.
    assert "--gpu-device" in constants
    assert "--recreate-out-db" not in constants


@pytest.fixture
def live_pid():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        os.kill(child.pid, 0)  # control: raises unless the child is running
        yield child.pid
    finally:
        child.terminate()
        child.wait()


def _marker_text(content: str | None) -> str:
    if content is not None:
        return content
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    with pytest.raises(ProcessLookupError):  # control: the reaped child's PID is dead
        os.kill(child.pid, 0)
    return str(child.pid)


def _files(tmp_path: Path) -> dict[str, Path]:
    # The names are the documented contract (UPDATER_WORKER.md, ADR-0008), not derived through the module under test.
    return {"active": tmp_path / "similarity-cache.db", "marker": tmp_path / "similarity-cache.db.building", "shadow": tmp_path / "similarity-cache.next.db", "journal": tmp_path / "similarity-cache.next.db-journal", "prev": tmp_path / "similarity-cache.prev.db"}


@pytest.mark.parametrize("content", NON_BLOCKING, ids=NON_BLOCKING_IDS)
def test_cleanup_removes_dead_or_unparseable_marker_and_shadow(updater, tmp_path, caplog, content):
    """`cleanup_similarity_leftovers` removes a marker whose PID is dead or unparseable, logging its path and pid, and removes the shadow and its journal while leaving the active cache alone."""
    caplog.set_level(logging.INFO)
    files = _files(tmp_path)
    files["active"].write_bytes(b"active")
    files["shadow"].write_bytes(b"shadow")
    files["journal"].write_bytes(b"journal")
    text = _marker_text(content)
    files["marker"].write_text(text, encoding="ascii")

    updater.cleanup_similarity_leftovers(similarity_db=files["active"])

    assert not files["marker"].exists()
    assert not files["shadow"].exists()
    assert not files["journal"].exists()
    assert files["active"].read_bytes() == b"active"  # the served cache is not a leftover
    messages = [record.getMessage() for record in caplog.records]
    removal = [message for message in messages if f"path={files['marker']}" in message and "pid=" in message]
    assert removal, messages  # the removal is logged with path and pid
    if content is None:
        assert any(f"pid={text}" in message for message in removal), removal  # a parseable dead PID is logged as itself


def test_cleanup_keeps_live_marker_and_removes_shadow(updater, tmp_path, live_pid):
    """`cleanup_similarity_leftovers` keeps a marker whose PID is live, byte for byte, and still removes the shadow and its journal."""
    files = _files(tmp_path)
    files["active"].write_bytes(b"active")
    files["shadow"].write_bytes(b"shadow")
    files["journal"].write_bytes(b"journal")
    files["marker"].write_text(str(live_pid), encoding="ascii")

    updater.cleanup_similarity_leftovers(similarity_db=files["active"])

    assert files["marker"].read_text(encoding="ascii") == str(live_pid)
    assert not files["shadow"].exists()  # a crashed build's shadow goes even beside a live marker
    assert not files["journal"].exists()
    assert files["active"].read_bytes() == b"active"


@pytest.mark.parametrize("leftovers", [("shadow", "journal"), ("shadow",), ("journal",), ()], ids=["both", "shadow-only", "journal-only", "none"])
def test_cleanup_removes_each_leftover_on_its_own(updater, tmp_path, leftovers):
    """With no marker, `cleanup_similarity_leftovers` removes the shadow and the journal whether either is present alone or both are, and leaves only the active cache."""
    files = _files(tmp_path)
    files["active"].write_bytes(b"active")
    for name in leftovers:
        files[name].write_bytes(name.encode())

    updater.cleanup_similarity_leftovers(similarity_db=files["active"])

    assert sorted(path.name for path in tmp_path.iterdir()) == ["similarity-cache.db"]  # any leftover goes, with or without the other and with no marker
    assert files["active"].read_bytes() == b"active"


def _cache(path: Path, video_ids: list[str]) -> None:
    conn = sqlite3.connect(path.as_posix())
    try:
        ensure_similarity_schema(conn)
        for video_id in video_ids:
            store_similarity_cache(conn, {"video_id": video_id, "instance_domain": HOST}, [{"video_id": "z", "instance_domain": HOST, "score": 0.5, "rank": 1}], 1)
    finally:
        conn.close()


def _sources(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT k.video_id FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key ORDER BY k.video_id")]
    finally:
        conn.close()


def _leftovers(tmp_path: Path) -> list[str]:
    files = _files(tmp_path)
    return [files[name].name for name in ("shadow", "journal", "marker") if files[name].exists()]


def _fake_precompute(updater, monkeypatch, tmp_path: Path, action) -> dict:
    seen: dict = {}
    marker = _files(tmp_path)["marker"]

    def fake(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--out") + 1])
        seen["marker"] = marker.read_text(encoding="ascii").strip() if marker.exists() else None
        seen["shadow_sources"] = _sources(out) if out.exists() else None
        action(out)
        seen["shadow_ino"] = os.stat(out).st_ino if out.exists() else None

    # The precompute child needs numpy, faiss and a built index; the pytest interpreter has none, so the process boundary is the seam.
    monkeypatch.setattr(updater.subprocess, "run", fake)
    return seen


def _run(updater, tmp_path: Path, *, fail_gate: bool = False) -> None:
    files = _files(tmp_path)
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=JOBS_DIR / "precompute-similar-ann.py", db_path=tmp_path / "prod.db", index_path=tmp_path / "ann.faiss", out_path=files["shadow"], use_gpu=False)
    updater.run_similarity_stage(similarity_db=files["active"], prod_db=tmp_path / "prod.db", precompute_cmd=cmd, repo_root=ROOT, fail_gate=fail_gate)


def _add_source(out: Path) -> None:
    conn = sqlite3.connect(out.as_posix())
    try:
        store_similarity_cache(conn, {"video_id": "c", "instance_domain": HOST}, [], 2)
    finally:
        conn.close()


def _create_with_source(out: Path) -> None:
    _cache(out, ["c"])


def _delete_source(out: Path) -> None:
    conn = sqlite3.connect(out.as_posix())
    try:
        conn.execute("DELETE FROM similarity_sources WHERE source_key = (SELECT key FROM video_keys WHERE video_id = 'b')")
        conn.commit()
    finally:
        conn.close()


def _write_garbage(out: Path) -> None:
    out.write_bytes(b"not a sqlite database\n" * 64)


def _crash(out: Path) -> None:
    # A precompute that dies mid-transaction leaves its rollback journal beside the shadow; run(check=True) then raises on its exit status.
    out.with_name(out.name + "-journal").write_bytes(b"journal")
    raise subprocess.CalledProcessError(1, ["precompute-similar-ann.py"])


@pytest.mark.parametrize("stale_prev", [False, True], ids=["no-prev", "stale-prev"])
def test_passing_build_becomes_active_and_prev_is_old_inode(updater, monkeypatch, tmp_path, stale_prev):
    """A shadow build that passes the gate becomes the active cache as the very file the precompute wrote, and `.prev.db` is the replaced active inode, an older `.prev.db` replaced."""
    files = _files(tmp_path)
    _cache(files["active"], ["a", "b"])
    if stale_prev:
        _cache(files["prev"], ["old"])
    old_ino = os.stat(files["active"]).st_ino
    seen = _fake_precompute(updater, monkeypatch, tmp_path, _add_source)

    _run(updater, tmp_path)

    assert seen["marker"] == str(os.getpid()), seen  # control: the marker existed during the build, so its absence below was a removal
    assert seen["shadow_sources"] == ["a", "b"], seen  # control: the precompute ran on a copy of the active cache
    assert _sources(files["active"]) == ["a", "b", "c"]  # the shadow's content is now the active cache
    assert os.stat(files["active"]).st_ino == seen["shadow_ino"]  # the active path names the file the precompute wrote, not a copy of it
    assert _sources(files["prev"]) == ["a", "b"]  # .prev.db holds the replaced content, a stale one replaced
    assert os.stat(files["prev"]).st_ino == old_ino  # .prev.db is the replaced active inode
    assert _leftovers(tmp_path) == []  # no shadow, journal or marker after a pass either


def test_missing_active_is_created_without_prev(updater, monkeypatch, tmp_path):
    """With no active cache, a passing build is swapped in as the active cache and no `.prev.db` is written, since nothing was replaced."""
    files = _files(tmp_path)
    seen = _fake_precompute(updater, monkeypatch, tmp_path, _create_with_source)

    _run(updater, tmp_path)

    assert seen["marker"] == str(os.getpid()), seen  # control
    assert _sources(files["active"]) == ["c"]  # a build with no active cache to replace becomes the active cache
    assert os.stat(files["active"]).st_ino == seen["shadow_ino"]  # by swap of the file the precompute wrote
    assert not files["prev"].exists()  # nothing was replaced, so no .prev.db
    assert _leftovers(tmp_path) == []


# Each refusal is pinned to its own cause: a stub's NotImplementedError is a RuntimeError, and a gate that refuses everything would raise one too, so the type alone proves nothing.
@pytest.mark.parametrize(("action", "fail_gate", "error", "reason"), [(_add_source, True, RuntimeError, r"^Similarity gate failed: .*--fail-similarity-gate"), (_delete_source, False, RuntimeError, r"^Similarity gate failed: .*fewer sources"), (_write_garbage, False, RuntimeError, r"^Similarity gate failed: .*not a database"), (_crash, False, subprocess.CalledProcessError, r"precompute-similar-ann\.py.*non-zero exit status 1")], ids=["forced-gate", "fewer-sources", "corrupt-shadow", "precompute-fails"])
def test_failed_build_raises_and_leaves_active_untouched(updater, monkeypatch, tmp_path, action, fail_gate, error, reason):
    """A forced gate, a shadow with fewer sources, a corrupt shadow or a failed precompute raises its own error, leaves the active cache byte-identical, writes no `.prev.db` and leaves no shadow, journal or marker behind."""
    files = _files(tmp_path)
    _cache(files["active"], ["a", "b"])
    before = files["active"].read_bytes()
    seen = _fake_precompute(updater, monkeypatch, tmp_path, action)

    with pytest.raises(error, match=reason) as excinfo:
        _run(updater, tmp_path, fail_gate=fail_gate)

    assert excinfo.type is error, excinfo  # exactly the gate's RuntimeError or the child's CalledProcessError, not a subclass such as NotImplementedError

    # .get, not [], so a stage that raised the expected type before the precompute fails on this control with what the fake saw.
    assert seen.get("marker") == str(os.getpid()), seen  # control: the stage reached the precompute with the marker written, so the raise is not an earlier crash
    assert seen.get("shadow_sources") == ["a", "b"], seen  # control: a shadow existed, so its absence below was a removal
    assert files["active"].read_bytes() == before  # the active cache is byte-identical
    assert not files["prev"].exists()  # no swap, so no .prev.db
    assert _leftovers(tmp_path) == []  # no shadow, journal or marker left behind


def test_main_runs_similarity_stage_after_service_start() -> None:
    """`main` runs `run_similarity_stage` once, after the whole `try` whose `finally` starts the service, and leaves no precompute command or call inside that `try`."""
    # rat-tail: a source scan, because reaching the similarity stage through `main` means running the whole crawl/merge/ANN pipeline; a pipeline harness with the stage commands shimmed would replace it.
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    service_trys = [node for node in ast.walk(main) if isinstance(node, ast.Try) and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "systemctl_cmd" and any(kw.arg == "action" and isinstance(kw.value, ast.Constant) and kw.value.value == "start" for kw in call.keywords) for stmt in node.finalbody for call in ast.walk(stmt))]
    assert len(service_trys) == 1, [node.lineno for node in service_trys]  # control: the service-start `try` is identified, and only one
    service_try = service_trys[0]
    stage_calls = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_similarity_stage"]

    assert len(stage_calls) == 1, stage_calls  # `main` runs the stage, once
    assert stage_calls[0] > service_try.end_lineno, (stage_calls, service_try.end_lineno)  # after the whole `try`, its `finally` included, so the Engine is up

    inside_constants = {node.value for node in ast.walk(service_try) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    # The ANN build stays inside the `try`, so the scan below is shown to see that `try`'s string constants.
    assert "build-ann-index.py" in inside_constants  # control
    assert not {value for value in inside_constants if "precompute-similar-ann" in value}  # no precompute command or stage label left under the stopped service
    inside_calls = {node.func.id for node in ast.walk(service_try) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "run_with_cpu_fallback" in inside_calls, sorted(inside_calls)  # control: the call scan sees the ANN build's call inside the `try`
    assert not inside_calls & {"similarity_precompute_cmd", "run_similarity_stage"}, sorted(inside_calls)  # nor any call that builds or runs it


def _rows(path: Path) -> tuple[list, list]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        sources = sorted(tuple(row) for row in conn.execute("SELECT k.video_id, k.instance_domain FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key"))
        items = sorted(
            (video_id, domain, entry["video_id"], entry["instance_domain"])
            for video_id, domain in sources
            for entry in fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, 1000)
        )
        return sources, items
    finally:
        conn.close()


def _execute(path: Path, *statements: str) -> None:
    conn = sqlite3.connect(path.as_posix())
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def test_host_denied_during_build_is_pruned_from_swapped_cache(updater, monkeypatch, tmp_path: Path) -> None:
    """A host denied in prod while the shadow builds has no row, as source or as similar, in the cache the stage swaps in; a lifted deny row prunes nothing."""
    active = tmp_path / "similarity-cache.db"
    shadow = tmp_path / "similarity-cache.next.db"
    prod = tmp_path / "prod.db"
    conn = sqlite3.connect(prod.as_posix())
    try:
        ensure_moderation_schema(conn)
        # A lifted deny row: only the active denylist is the current one.
        conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('lifted.example', 0, 1, 1)")
        conn.commit()
    finally:
        conn.close()
    conn = sqlite3.connect(active.as_posix())
    try:
        ensure_similarity_schema(conn)
        for video_id, domain in REPRUNE_SOURCES:
            items = [item for item in REPRUNE_ITEMS if item[:2] == (video_id, domain)]
            store_similarity_cache(conn, {"video_id": video_id, "instance_domain": domain}, [{"video_id": item[2], "instance_domain": item[3], "score": 0.5, "rank": rank} for rank, item in enumerate(items, start=1)], 1)
    finally:
        conn.close()
    seen: dict = {}

    def fake(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--out") + 1])
        seen["shadow"] = _rows(out)
        # The Engine's moderation deny while the build runs: prod gains the row, the active file is purged, the shadow copy is not.
        _execute(prod, "INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('bad.example', 1, 2, 2)")
        purged = sqlite3.connect(active.as_posix())
        try:
            purge_similarity_for_host(purged, "bad.example")
        finally:
            purged.close()
        seen["shadow_ino"] = os.stat(out).st_ino

    # The precompute child needs numpy, faiss and a built index; the pytest interpreter has none, so the process boundary is the seam.
    monkeypatch.setattr(updater.subprocess, "run", fake)
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=JOBS_DIR / "precompute-similar-ann.py", db_path=prod, index_path=tmp_path / "ann.faiss", out_path=shadow, use_gpu=False)

    updater.run_similarity_stage(similarity_db=active, prod_db=prod, precompute_cmd=cmd, repo_root=ROOT, fail_gate=False)

    assert seen.get("shadow") == (sorted(REPRUNE_SOURCES), sorted(REPRUNE_ITEMS)), seen  # control: the shadow held bad.example rows in both tables when the deny landed
    assert os.stat(active).st_ino == seen["shadow_ino"]  # control: the active file is the swapped-in shadow, not the file the fake purged
    sources, items = _rows(active)
    assert [row for row in sources if "bad.example" in row] == []  # no bad.example source
    assert [row for row in items if "bad.example" in row] == []  # no bad.example item, as source or as similar
    assert (sources, items) == ([("v2", "ok.example"), ("v3", "lifted.example")], [("v2", "ok.example", "v3", "lifted.example"), ("v3", "lifted.example", "v2", "ok.example")])  # only the denied host's rows go; a lifted deny row prunes nothing


CASES_FILE = ROOT / "tests" / "active" / "upstream_snippet_cases.json"
SNIPPET = "/etc/nginx/peertube-engine-upstream.conf"
SYSTEMCTL = "/usr/bin/systemctl"

# The snippet case table, written here so the expected ports do not come only from the shared case file the bash parser is held to as well.
INLINE_CASES = [
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


SNIPPET_CASES = [pytest.param({"id": case_id, "text": text, "port": port}, id=f"inline-{case_id}") for case_id, text, port in INLINE_CASES] + _file_cases()

def _write(path: Path, text: str) -> Path:
    # Bytes, so the CRLF case reaches the parser as written.
    path.write_bytes(text.encode("utf-8"))
    return path


@pytest.mark.parametrize("case", SNIPPET_CASES)
def test_parse_upstream_snippet_cases(updater, tmp_path: Path, case) -> None:
    """Every accepted snippet case parses to its port as an int; every rejected one raises ValueError."""
    assert case is not None, f"{CASES_FILE} is missing: it is the shared snippet case table, a JSON list of {{id, text, port}}, port null for a rejected snippet"
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
