import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
sys.path.insert(0, str(SERVER_DIR))
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402

spec = importlib.util.spec_from_file_location("upd_probe", SERVER_DIR / "db" / "jobs" / "updater-worker.py")
upd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upd)


def _setup(tmp_path):
    active = tmp_path / "similarity-cache.db"
    prod = tmp_path / "prod.db"
    c = sqlite3.connect(prod)
    ensure_moderation_schema(c)
    c.commit()
    c.close()
    c = sqlite3.connect(active)
    ensure_similarity_schema(c)
    c.executemany("INSERT INTO similarity_sources (video_id, instance_domain, computed_at) VALUES (?, ?, 1)", [("v1", "bad.example"), ("v2", "ok.example")])
    c.executemany("INSERT INTO similarity_items (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain, score, rank) VALUES (?, ?, ?, ?, 0.5, 1)", [("v1", "bad.example", "v2", "ok.example"), ("v2", "ok.example", "v1", "bad.example")])
    c.commit()
    c.close()
    cmd = upd.similarity_precompute_cmd(python_bin=sys.executable, script_path=Path("x.py"), db_path=prod, index_path=tmp_path / "i", out_path=upd.similarity_shadow_path(active), use_gpu=False)
    return active, prod, cmd


def test_deny(tmp_path, monkeypatch):
    active, prod, cmd = _setup(tmp_path)

    def fake(cmd, **_k):
        c = sqlite3.connect(prod)
        c.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('bad.example', 1, 2, 2)")
        c.commit()
        c.close()
        c = sqlite3.connect(active)
        c.row_factory = sqlite3.Row
        upd.purge_similarity_for_host(c, "bad.example")
        c.close()

    monkeypatch.setattr(upd.subprocess, "run", fake)
    upd.run_similarity_stage(similarity_db=active, prod_db=prod, precompute_cmd=cmd, repo_root=ROOT, fail_gate=False)
    c = sqlite3.connect(active)
    print("SOURCES", c.execute("SELECT * FROM similarity_sources").fetchall())
    print("ITEMS", c.execute("SELECT source_instance_domain, similar_instance_domain FROM similarity_items").fetchall())
    c.close()
    print("FILES", sorted(p.name for p in tmp_path.iterdir()))


def test_garbage(tmp_path, monkeypatch):
    active, prod, cmd = _setup(tmp_path)
    c = sqlite3.connect(prod)
    c.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES ('ok.example', 1, 2, 2)")
    c.commit()
    c.close()

    def fake(cmd, **_k):
        Path(cmd[cmd.index("--out") + 1]).write_bytes(b"not a sqlite database\n" * 64)

    monkeypatch.setattr(upd.subprocess, "run", fake)
    try:
        upd.run_similarity_stage(similarity_db=active, prod_db=prod, precompute_cmd=cmd, repo_root=ROOT, fail_gate=False)
    except Exception as exc:
        print("RAISED", type(exc).__name__, exc)
    print("FILES", sorted(p.name for p in tmp_path.iterdir()))
