from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import similarity_candidates  # noqa: E402
from data.db import connect_similarity_db  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402
from data.similarity_cache_manager import SimilarityCachePolicy  # noqa: E402


def _kill(pid):
    try:
        os.kill(pid, 0)
        return "ok"
    except BaseException as exc:
        return type(exc).__name__


def test_probe(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    print("ROOT", ROOT)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        print("dead", dead.pid, _kill(dead.pid))
        print("live", live.pid, _kill(live.pid))
        for pid in (0, -1, 99999999999):
            print("pid", pid, _kill(pid))
    finally:
        live.terminate()
        live.wait()
    path = tmp_path / "similarity-cache.db"
    conn = connect_similarity_db(path)
    ensure_similarity_schema(conn)
    conn.commit()
    stat = os.stat(path)
    server = SimpleNamespace(similarity_db=conn, similarity_db_lock=threading.Lock(), similarity_db_path=path, similarity_db_identity=(stat.st_dev, stat.st_ino))
    source = {"video_id": "S", "instance_domain": "h.example"}
    entries = [{"video_id": "A", "instance_domain": "h.example", "score": 0.9, "rank": 1}, {"video_id": "B", "instance_domain": "h.example", "score": 0.8, "rank": 2}]
    similarity_candidates._write_cache(server, source, entries, SimilarityCachePolicy())
    print("sources", [tuple(r) for r in conn.execute("SELECT video_id, instance_domain FROM similarity_sources")])
    print("items", [tuple(r) for r in conn.execute("SELECT * FROM similarity_items ORDER BY rank")])
    print("logs", [r.getMessage() for r in caplog.records])
    spec = importlib.util.spec_from_file_location("updater_probe", SERVER_DIR / "db" / "jobs" / "updater-worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print("has cleanup", hasattr(module, "cleanup_similarity_leftovers"), "pid_alive(0)", module._pid_alive(0))
    assert False, "probe"
