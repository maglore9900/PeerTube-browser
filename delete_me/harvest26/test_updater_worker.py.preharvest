"""`updater-worker.py` builds its similarity precompute argv with `--refresh-existing` and never `--recreate-out-db`, and its CPU retry keeps that flag; it clears a crashed similarity build's leftovers, builds the cache in a shadow that only a passing gate swaps in, runs that stage once the Engine serves again, and re-prunes prod's current denylist from the shadow.

- `similarity_precompute_cmd` returns, token for token, the precompute argv with `--refresh-existing` after `--search-batch-size 1024`, ending in `--gpu --gpu-device 0` or `--cpu`, and without `--recreate-out-db`.
- `_to_cpu_cmd` turns the GPU argv into exactly the CPU argv, `--refresh-existing` included.
- `main` calls `similarity_precompute_cmd`, and no `--recreate-out-db` literal is left anywhere in the module.
- `cleanup_similarity_leftovers` removes a `<cache>.building` marker holding a dead PID, `garbage`, the empty string, `0`, `-1` or `99999999999`, logging its path and pid; it keeps a live-PID marker; it removes `.next.db` and `.next.db-journal` each on its own, and never touches the active file.
- `run_similarity_stage` with a passing build makes the precompute's shadow file the active cache and keeps the replaced inode as `.prev.db`; with no active file it writes none; a forced gate, fewer sources, a corrupt shadow or a failed precompute raises and leaves the active file byte-identical with no `.prev.db`; no shadow, journal or marker outlives any run.
- `main` runs `run_similarity_stage` once, after the `try` whose `finally` starts the service, with no precompute left inside that `try`; a host denied in prod during the build has no row in the cache the stage swaps in.

The module is loaded in-process from its file, the way `test_host_normalisation._load_job` does. For the stage, only the child process is replaced, at `subprocess.run`, so the updater's own `run_with_cpu_fallback` and `run_cmd` run for real. A live PID is a sleeping child; a dead PID is a child already waited on. Every cache file lives under `tmp_path`.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT

SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402

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
        conn.executemany("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES (?, ?, 1)", [(video_id, HOST) for video_id in video_ids])
        conn.executemany("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES (?, ?, 'z', ?, 0.5, 1)", [(video_id, HOST, HOST) for video_id in video_ids])
        conn.commit()
    finally:
        conn.close()


def _sources(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT video_id FROM similarity_sources ORDER BY video_id")]
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
        conn.execute("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES ('c', ?, 2)", (HOST,))
        conn.commit()
    finally:
        conn.close()


def _create_with_source(out: Path) -> None:
    _cache(out, ["c"])


def _delete_source(out: Path) -> None:
    conn = sqlite3.connect(out.as_posix())
    try:
        conn.execute("DELETE FROM similarity_sources WHERE video_id = 'b'")
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
        return sorted(conn.execute("SELECT video_id, instance_domain FROM similarity_sources").fetchall()), sorted(conn.execute("SELECT source_video_id, source_instance_domain, similar_video_id, similar_instance_domain FROM similarity_items").fetchall())
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
        conn.executemany("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES (?, ?, 1)", REPRUNE_SOURCES)
        conn.executemany("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES (?, ?, ?, ?, 0.5, 1)", REPRUNE_ITEMS)
        conn.commit()
    finally:
        conn.close()
    seen: dict = {}

    def fake(cmd, **_kwargs):
        out = Path(cmd[cmd.index("--out") + 1])
        seen["shadow"] = _rows(out)
        # The Engine's moderation deny while the build runs: prod gains the row, the active file is purged, the shadow copy is not.
        _execute(prod, "INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('bad.example', 1, 2, 2)")
        _execute(active, "DELETE FROM similarity_items WHERE source_instance_domain = 'bad.example' OR similar_instance_domain = 'bad.example'", "DELETE FROM similarity_sources WHERE instance_domain = 'bad.example'")
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
