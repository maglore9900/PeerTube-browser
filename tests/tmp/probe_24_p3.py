import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "engine" / "server" / "db" / "jobs" / "updater-worker.py"


def test_probe(tmp_path):
    spec = importlib.util.spec_from_file_location("updater_probe_p3", UPDATER)
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    from data.similarity_cache import ensure_similarity_schema
    print("has run_similarity_stage:", hasattr(updater, "run_similarity_stage"))
    prod = tmp_path / "prod.db"
    print("denied on empty prod:", updater.load_denied_hosts(prod), "prod exists:", prod.exists())
    cmd = updater.similarity_precompute_cmd(python_bin=sys.executable, script_path=tmp_path / "p.py", db_path=prod, index_path=tmp_path / "ann.faiss", out_path=tmp_path / "similarity-cache.next.db", use_gpu=False)
    print("out:", cmd[cmd.index("--out") + 1])
    active = tmp_path / "similarity-cache.db"
    conn = sqlite3.connect(active)
    ensure_similarity_schema(conn)
    conn.executemany("INSERT INTO similarity_sources VALUES (?, ?, 1)", [("a", "h.example"), ("b", "h.example")])
    conn.commit()
    conn.close()
    print("files after create:", sorted(p.name for p in tmp_path.iterdir()))
    garbage = tmp_path / "g.db"
    garbage.write_bytes(b"not a sqlite database\n" * 64)
    ro = sqlite3.connect(f"file:{garbage.as_posix()}?mode=ro", uri=True)
    try:
        ro.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        print("garbage:", type(exc).__name__, exc)
    ro.close()
    os.link(active, tmp_path / "linked.db")
    print("link ok, same ino:", os.stat(active).st_ino == os.stat(tmp_path / "linked.db").st_ino)
