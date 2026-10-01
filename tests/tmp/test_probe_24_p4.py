"""Probe: the phase 4 checkpoint's C1 scan expressions, verbatim, against the current `main`, and the swapped cache's rows under the current stage."""
from __future__ import annotations

import ast
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
UPDATER = SERVER_DIR / "db" / "jobs" / "updater-worker.py"

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402

SOURCES = [("v1", "bad.example"), ("v2", "ok.example"), ("v3", "lifted.example")]
ITEMS = [("v1", "bad.example", "v2", "ok.example"), ("v2", "ok.example", "v1", "bad.example"), ("v2", "ok.example", "v3", "lifted.example"), ("v3", "lifted.example", "v2", "ok.example")]


def test_probe_c1() -> None:
    tree = ast.parse(UPDATER.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    service_trys = [node for node in ast.walk(main) if isinstance(node, ast.Try) and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "systemctl_cmd" and any(kw.arg == "action" and isinstance(kw.value, ast.Constant) and kw.value.value == "start" for kw in call.keywords) for stmt in node.finalbody for call in ast.walk(stmt))]
    service_try = service_trys[0]
    inside_constants = {node.value for node in ast.walk(service_try) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    inside_calls = {node.func.id for node in ast.walk(service_try) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    out = {"SERVICE_TRYS": [(n.lineno, n.end_lineno) for n in service_trys], "ANN_SEEN": "build-ann-index.py" in inside_constants, "PRECOMPUTE_INSIDE": sorted(v for v in inside_constants if "precompute-similar-ann" in v), "FALLBACK_SEEN": "run_with_cpu_fallback" in inside_calls, "CALLS_INSIDE": sorted(inside_calls & {"similarity_precompute_cmd", "run_similarity_stage"})}
    assert False, out


def test_probe_c2(monkeypatch, tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("updater_worker_probe4", UPDATER)
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    active = tmp_path / "similarity-cache.db"
    prod = tmp_path / "prod.db"
    conn = sqlite3.connect(prod.as_posix())
    ensure_moderation_schema(conn)
    conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('lifted.example', 0, 1, 1)")
    conn.commit()
    conn.close()
    conn = sqlite3.connect(active.as_posix())
    ensure_similarity_schema(conn)
    conn.executemany("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES (?, ?, 1)", SOURCES)
    conn.executemany("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES (?, ?, ?, ?, 0.5, 1)", ITEMS)
    conn.commit()
    conn.close()

    def fake(cmd, **_kwargs):
        c = sqlite3.connect(prod.as_posix())
        c.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('bad.example', 1, 2, 2)")
        c.commit()
        c.close()

    monkeypatch.setattr(updater.subprocess, "run", fake)
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=Path("x.py"), db_path=prod, index_path=tmp_path / "ann.faiss", out_path=tmp_path / "similarity-cache.next.db", use_gpu=False)
    updater.run_similarity_stage(similarity_db=active, prod_db=prod, precompute_cmd=cmd, repo_root=ROOT, fail_gate=False)
    conn = sqlite3.connect(active.as_posix())
    out = {"SOURCES": sorted(conn.execute("SELECT video_id, instance_domain FROM similarity_sources").fetchall()), "ITEMS": sorted(conn.execute("SELECT source_video_id, source_instance_domain, similar_video_id, similar_instance_domain FROM similarity_items").fetchall()), "DENY": conn.execute("SELECT 1").fetchall(), "FILES": sorted(p.name for p in tmp_path.iterdir()), "ino": os.stat(active).st_ino > 0}
    conn.close()
    assert False, out
