"""Step-8 probe, attempt 3: what the shared similarity-cache.db is now, and whether any short-cache candidate is on disk."""
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "engine/server/db/similarity-cache.db"


def _describe(path: Path) -> str:
    if not os.path.lexists(path):
        return f"{path}: absent"
    st = path.stat()
    return f"{path}: link={path.is_symlink()} real={os.path.realpath(path)} size={st.st_size} mtime={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}"


def test_probe_cache_state():
    print(_describe(CACHE))
    for directory in (ROOT / "engine/server/db", ROOT / "delete_me", Path(os.path.realpath(CACHE)).parent):
        if directory.is_dir():
            print(directory, sorted(p.name for p in directory.iterdir() if "similar" in p.name))
    conn = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    try:
        print("tables", [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")])
        print("computed_at", conn.execute("SELECT MIN(computed_at), MAX(computed_at) FROM similarity_sources").fetchone())
        rows = conn.execute("SELECT source_key FROM similarity_sources ORDER BY source_key LIMIT 200").fetchall()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(similarity_items)")] if conn.execute("SELECT 1 FROM sqlite_master WHERE name='similarity_items'").fetchone() else None
        print("similarity_items cols", cols)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            print(table, [r[1] for r in conn.execute(f"PRAGMA table_info({table})")])
        print("sample sources", len(rows))
    finally:
        conn.close()
    assert False, "probe: read the printed output"
