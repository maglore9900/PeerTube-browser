from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402


def _source(tmp_path):
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT)")
    for index in range(1, 21):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example')", (f"v{index}",))
    conn.commit()
    return conn


def _run(tmp_path, cache, hold):
    source = _source(tmp_path)
    ensure_random_cache_schema(cache)
    cache.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(p, 999) for p in range(1, 6)])
    cache.commit()
    holder = sqlite3.connect(tmp_path / "cache.db", isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    release = threading.Timer(hold, lambda: holder.execute("ROLLBACK"))
    started = time.monotonic()
    release.start()
    try:
        try:
            built = populate_random_cache(source, cache, 100, True, True, 0, 100)
            outcome = f"built={built}"
        except Exception as exc:
            outcome = f"raised {type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started
    finally:
        release.join()
        holder.close()
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    print(f"PROBE hold={hold} {outcome} elapsed={elapsed:.2f} positions={[r[0] for r in rows]} rowids={sorted(r[1] for r in rows)}")


def test_probe_current_connection(tmp_path):
    cache = connect_random_cache_db(tmp_path / "cache.db")
    print("PROBE busy_timeout", cache.execute("PRAGMA busy_timeout").fetchone()[0])
    _run(tmp_path, cache, 6.0)


def test_probe_long_timeout_connection(tmp_path):
    cache = sqlite3.connect((tmp_path / "cache.db").as_posix(), timeout=3600, check_same_thread=False)
    cache.row_factory = sqlite3.Row
    print("PROBE busy_timeout", cache.execute("PRAGMA busy_timeout").fetchone()[0])
    _run(tmp_path, cache, 6.0)
