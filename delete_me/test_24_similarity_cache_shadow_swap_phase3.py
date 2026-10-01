"""`run_similarity_stage` swaps a shadow build that passes the gate over the active cache and keeps the replaced inode as `.prev.db`; a failed precompute or gate raises, leaves the active cache byte-identical and writes no `.prev.db`; no shadow, journal or marker outlives any run.

- Pass (active holds sources a, b; the fake precompute adds c to the shadow), with and without a stale `.prev.db` holding `old`: the active file holds a, b, c and is the inode the precompute wrote; `.prev.db` holds a, b and is the old active inode.
- Missing active file (the fake creates the schema and source c): the active file appears holding c, and no `.prev.db` is written.
- `fail_gate=True`, a fake that deletes source b and a fake that overwrites the shadow with garbage: the gate refuses and the call raises exactly `RuntimeError`, its message `Similarity gate failed: ` naming that case's reason (the flag, fewer sources, SQLite's "not a database"); a fake that leaves a `-journal` and exits non-zero: `CalledProcessError` propagates. In all four the active file's bytes are unchanged and no `.prev.db` exists.
- Every case: during the precompute the marker held this process's PID and (when the active file existed) the shadow was a copy of it; afterwards no `.next.db`, `.next.db-journal` or `.building` remains.

The updater is loaded in-process from its file, as `test_updater_worker.py` does. Only the child process is replaced, at `subprocess.run`, so the updater's own `run_with_cpu_fallback` and `run_cmd` run for real. The fake records what it saw instead of asserting, so a failed observation cannot be swallowed by the `pytest.raises` around a failing stage. Every file lives under `tmp_path`.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.similarity_cache import ensure_similarity_schema  # noqa: E402

UPDATER = SERVER_DIR / "db" / "jobs" / "updater-worker.py"
HOST = "h.example"


@pytest.fixture(scope="module")
def updater():
    spec = importlib.util.spec_from_file_location("updater_worker_phase3", UPDATER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(tmp_path: Path) -> dict[str, Path]:
    # The names are the documented contract (UPDATER_WORKER.md, ADR-0008), not derived through the module under test.
    return {"active": tmp_path / "similarity-cache.db", "marker": tmp_path / "similarity-cache.db.building", "shadow": tmp_path / "similarity-cache.next.db", "journal": tmp_path / "similarity-cache.next.db-journal", "prev": tmp_path / "similarity-cache.prev.db"}


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
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=SERVER_DIR / "db" / "jobs" / "precompute-similar-ann.py", db_path=tmp_path / "prod.db", index_path=tmp_path / "ann.faiss", out_path=files["shadow"], use_gpu=False)
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
    files = _files(tmp_path)
    _cache(files["active"], ["a", "b"])
    if stale_prev:
        _cache(files["prev"], ["old"])
    old_ino = os.stat(files["active"]).st_ino
    seen = _fake_precompute(updater, monkeypatch, tmp_path, _add_source)

    _run(updater, tmp_path)

    assert seen["marker"] == str(os.getpid()), seen  # C2 control: the marker existed during the build, so its absence below was a removal
    assert seen["shadow_sources"] == ["a", "b"], seen  # C1 control: the precompute ran on a copy of the active cache
    assert _sources(files["active"]) == ["a", "b", "c"]  # C1: the shadow's content is now the active cache
    assert os.stat(files["active"]).st_ino == seen["shadow_ino"]  # C1: the active path names the file the precompute wrote, not a copy of it
    assert _sources(files["prev"]) == ["a", "b"]  # C1: .prev.db holds the replaced content, a stale one replaced
    assert os.stat(files["prev"]).st_ino == old_ino  # C1: .prev.db is the replaced active inode
    assert _leftovers(tmp_path) == []  # C2: no shadow, journal or marker after a pass either


def test_missing_active_is_created_without_prev(updater, monkeypatch, tmp_path):
    files = _files(tmp_path)
    seen = _fake_precompute(updater, monkeypatch, tmp_path, _create_with_source)

    _run(updater, tmp_path)

    assert seen["marker"] == str(os.getpid()), seen  # C2 control
    assert _sources(files["active"]) == ["c"]  # C1: a build with no active cache to replace becomes the active cache
    assert os.stat(files["active"]).st_ino == seen["shadow_ino"]  # C1: by swap of the file the precompute wrote
    assert not files["prev"].exists()  # C1: nothing was replaced, so no .prev.db
    assert _leftovers(tmp_path) == []  # C2


# Each refusal is pinned to its own cause: a stub's NotImplementedError is a RuntimeError, and a gate that refuses everything would raise one too, so the type alone proves nothing.
@pytest.mark.parametrize(("action", "fail_gate", "error", "reason"), [(_add_source, True, RuntimeError, r"^Similarity gate failed: .*--fail-similarity-gate"), (_delete_source, False, RuntimeError, r"^Similarity gate failed: .*fewer sources"), (_write_garbage, False, RuntimeError, r"^Similarity gate failed: .*not a database"), (_crash, False, subprocess.CalledProcessError, r"precompute-similar-ann\.py.*non-zero exit status 1")], ids=["forced-gate", "fewer-sources", "corrupt-shadow", "precompute-fails"])
def test_failed_build_raises_and_leaves_active_untouched(updater, monkeypatch, tmp_path, action, fail_gate, error, reason):
    files = _files(tmp_path)
    _cache(files["active"], ["a", "b"])
    before = files["active"].read_bytes()
    seen = _fake_precompute(updater, monkeypatch, tmp_path, action)

    with pytest.raises(error, match=reason) as excinfo:
        _run(updater, tmp_path, fail_gate=fail_gate)

    assert excinfo.type is error, excinfo  # C2: exactly the gate's RuntimeError or the child's CalledProcessError, not a subclass such as NotImplementedError

    # .get, not [], so a stage that raised the expected type before the precompute fails on this control with what the fake saw.
    assert seen.get("marker") == str(os.getpid()), seen  # C2 control: the stage reached the precompute with the marker written, so the raise is not an earlier crash
    assert seen.get("shadow_sources") == ["a", "b"], seen  # C2 control: a shadow existed, so its absence below was a removal
    assert files["active"].read_bytes() == before  # C2: the active cache is byte-identical
    assert not files["prev"].exists()  # C2: no swap, so no .prev.db
    assert _leftovers(tmp_path) == []  # C2: no shadow, journal or marker left behind
