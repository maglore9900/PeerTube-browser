"""`main` runs the similarity stage once the service is started again, and the stage keeps a host denied in prod during the build out of the cache it swaps in.

- `main` holds exactly one `run_similarity_stage` call, after the `try` whose `finally` calls `systemctl_cmd(action="start")`, and no `precompute-similar-ann` literal or precompute call is left inside that `try`.
- Active holds sources on `bad.example`, `ok.example` and `lifted.example` (denylisted in prod but inactive), with items crossing hosts both ways. The fake precompute inserts an active `bad.example` denylist row into prod and purges `bad.example` from the active file. After the swap the active file is the shadow's inode, neither of its tables holds a `bad.example` row, and every `ok.example` / `lifted.example` row survives.

The updater is loaded in-process from its file, as `test_updater_worker.py` does. Only the child process is replaced, at `subprocess.run`, as in the phase 3 checkpoint. Every file lives under `tmp_path`.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402

UPDATER = SERVER_DIR / "db" / "jobs" / "updater-worker.py"
SOURCES = [("v1", "bad.example"), ("v2", "ok.example"), ("v3", "lifted.example")]
ITEMS = [("v1", "bad.example", "v2", "ok.example"), ("v2", "ok.example", "v1", "bad.example"), ("v2", "ok.example", "v3", "lifted.example"), ("v3", "lifted.example", "v2", "ok.example")]


@pytest.fixture(scope="module")
def updater():
    spec = importlib.util.spec_from_file_location("updater_worker_phase4", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_main_runs_similarity_stage_after_service_start() -> None:
    # rat-tail: a source scan, because reaching the similarity stage through `main` means running the whole crawl/merge/ANN pipeline; a pipeline harness with the stage commands shimmed would replace it.
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    service_trys = [node for node in ast.walk(main) if isinstance(node, ast.Try) and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "systemctl_cmd" and any(kw.arg == "action" and isinstance(kw.value, ast.Constant) and kw.value.value == "start" for kw in call.keywords) for stmt in node.finalbody for call in ast.walk(stmt))]
    assert len(service_trys) == 1, [node.lineno for node in service_trys]  # C1 control: the service-start `try` is identified, and only one
    service_try = service_trys[0]
    stage_calls = [node.lineno for node in ast.walk(main) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_similarity_stage"]

    assert len(stage_calls) == 1, stage_calls  # C1: `main` runs the stage, once
    assert stage_calls[0] > service_try.end_lineno, (stage_calls, service_try.end_lineno)  # C1: after the whole `try`, its `finally` included, so the Engine is up

    inside_constants = {node.value for node in ast.walk(service_try) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    # The ANN build stays inside the `try`, so the scan below is shown to see that `try`'s string constants.
    assert "build-ann-index.py" in inside_constants  # C1 control
    assert not {value for value in inside_constants if "precompute-similar-ann" in value}  # C1: no precompute command or stage label left under the stopped service
    inside_calls = {node.func.id for node in ast.walk(service_try) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "run_with_cpu_fallback" in inside_calls, sorted(inside_calls)  # C1 control: the call scan sees the ANN build's call inside the `try`
    assert not inside_calls & {"similarity_precompute_cmd", "run_similarity_stage"}, sorted(inside_calls)  # C1: nor any call that builds or runs it


def test_host_denied_during_build_is_pruned_from_swapped_cache(updater, monkeypatch, tmp_path: Path) -> None:
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
        conn.executemany("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES (?, ?, 1)", SOURCES)
        conn.executemany("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES (?, ?, ?, ?, 0.5, 1)", ITEMS)
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
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=SERVER_DIR / "db" / "jobs" / "precompute-similar-ann.py", db_path=prod, index_path=tmp_path / "ann.faiss", out_path=shadow, use_gpu=False)

    updater.run_similarity_stage(similarity_db=active, prod_db=prod, precompute_cmd=cmd, repo_root=ROOT, fail_gate=False)

    assert seen.get("shadow") == (sorted(SOURCES), sorted(ITEMS)), seen  # C2 control: the shadow held bad.example rows in both tables when the deny landed
    assert os.stat(active).st_ino == seen["shadow_ino"]  # C2 control: the active file is the swapped-in shadow, not the file the fake purged
    sources, items = _rows(active)
    assert [row for row in sources if "bad.example" in row] == []  # C2: no bad.example source
    assert [row for row in items if "bad.example" in row] == []  # C2: no bad.example item, as source or as similar
    assert (sources, items) == ([("v2", "ok.example"), ("v3", "lifted.example")], [("v2", "ok.example", "v3", "lifted.example"), ("v3", "lifted.example", "v2", "ok.example")])  # C2: only the denied host's rows go; a lifted deny row prunes nothing
