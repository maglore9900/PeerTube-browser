"""Probe: what the phase-3 checkpoint's helpers and the stdlib swap primitives actually do; prints, asserts nothing it has not seen."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_24_similarity_cache_shadow_swap_phase3 as t  # noqa: E402


def test_probe(tmp_path, monkeypatch):
    files = t._files(tmp_path)
    t._cache(files["active"], ["a", "b"])
    old_ino = os.stat(files["active"]).st_ino
    src = sqlite3.connect(f"file:{files['active'].as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(files["shadow"].as_posix())
    src.backup(dst, pages=1024)
    dst.close()
    src.close()
    print("shadow after backup", t._sources(files["shadow"]))
    t._add_source(files["shadow"])
    shadow_ino = os.stat(files["shadow"]).st_ino
    print("shadow after add", t._sources(files["shadow"]), "journal exists", files["journal"].exists())
    t._cache(files["prev"], ["old"])
    files["prev"].unlink()
    os.link(files["active"], files["prev"])
    os.replace(files["shadow"], files["active"])
    print("active", t._sources(files["active"]), "active ino == shadow ino", os.stat(files["active"]).st_ino == shadow_ino, "prev", t._sources(files["prev"]), "prev ino == old", os.stat(files["prev"]).st_ino == old_ino)

    g = tmp_path / "g.db"
    t._cache(g, ["a", "b"])
    t._delete_source(g)
    print("after delete", t._sources(g))
    t._write_garbage(g)
    try:
        conn = sqlite3.connect(f"file:{g.as_posix()}?mode=ro", uri=True)
        print("garbage integrity", conn.execute("PRAGMA integrity_check").fetchall())
    except sqlite3.Error as exc:
        print("garbage raises", type(exc).__name__, exc)
    n = tmp_path / "n.db"
    t._create_with_source(n)
    print("created", t._sources(n))

    spec = importlib.util.spec_from_file_location("updater_probe", t.UPDATER)
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    calls = []

    def fake(cmd, **kwargs):
        calls.append((cmd[cmd.index("--out") + 1], kwargs))
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(updater.subprocess, "run", fake)
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=Path("x.py"), db_path=tmp_path / "p.db", index_path=tmp_path / "i", out_path=files["shadow"], use_gpu=False)
    try:
        updater.run_with_cpu_fallback(cmd, stage="precompute-similar-ann", cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print("propagated", type(exc).__name__)
    print("calls", calls)
    print("has run_similarity_stage", hasattr(updater, "run_similarity_stage"))
