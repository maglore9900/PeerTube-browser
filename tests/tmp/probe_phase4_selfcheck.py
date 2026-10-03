import hashlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_41_ann_ids_a_schema_writers_phase4 as t  # noqa: E402


def test_ids():
    from data.ann_ids import compute_ann_id
    for key, pinned in (("v1", t.V1_ID), ("v2", t.V2_ID)):
        raw = int.from_bytes(hashlib.blake2b(f"{key}::a.example".encode(), digest_size=8).digest(), "big") & (2**63 - 1)
        print("ID", key, pinned, raw, compute_ann_id(key, "a.example"), pinned == raw == compute_ann_id(key, "a.example"))


def test_runtime_error_last_line(tmp_path):
    code = "raise RuntimeError('main.video_embeddings has no ann_id column; it predates. ' 'Run migrate-whitelist.py; --resume-staging must be recreated.')"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    print("RC", r.returncode, "LAST", repr(r.stderr.strip().splitlines()[-1]))


def test_sync_collision_state(tmp_path, monkeypatch):
    sj = t._load_job("sync_probe_selfcheck", "sync-whitelist.py")
    target = tmp_path / "w.db"
    t._seed(t._whitelist_db(sj, target), ["v1"], [t.PROD_V1 + (t.V1_ID,)])
    src = t._crawl_source(tmp_path / "c.db", t.V1_ID)
    before = t._state(target)
    try:
        t._run_sync(sj, monkeypatch, src, target)
    except BaseException as exc:
        print("RAISED", type(exc).__name__, exc)
    after = t._state(target)
    for k in before:
        print("KEY", k, "same" if before[k] == after[k] else f"DIFF before={before[k]} after={after[k]}")


def test_merge_ok_stderr(tmp_path):
    sj = t._load_job("sync_probe_selfcheck2", "sync-whitelist.py")
    p, s = tmp_path / "p.db", tmp_path / "s.db"
    t._seed(t._whitelist_db(sj, p), ["v1"], [t.PROD_V1 + (t.V1_ID,)])
    t._seed(t._whitelist_db(sj, s, "unguarded"), ["v1", "v2"], [t.STAGE_V1 + (t.V1_ID,), t.STAGE_V2 + (t.V2_ID,)])
    r = t._merge(p, s)
    print("MERGE OK rc", r.returncode, "stderr", r.stderr)
    t._seed(t._whitelist_db(sj, tmp_path / "p2.db"), ["v1"], [t.PROD_V1 + (t.V1_ID,)])
    t._seed(t._whitelist_db(sj, tmp_path / "s2.db", "unguarded"), ["v1", "v2"], [t.STAGE_V1 + (t.V1_ID,), t.STAGE_V2 + (t.V1_ID,)])
    r = t._merge(tmp_path / "p2.db", tmp_path / "s2.db")
    print("MERGE COLLIDE rc", r.returncode, "stderr", r.stderr)


def test_zz_fail():
    assert False
