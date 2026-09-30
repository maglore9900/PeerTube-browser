import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    sys.path.insert(0, str(path))

import data.random_cache as random_cache  # noqa: E402


def test_probe(tmp_path: Path) -> None:
    src = sqlite3.connect(tmp_path / "source.db")
    src.row_factory = sqlite3.Row
    src.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    src.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT)")
    for index in range(1, 21):
        src.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        src.execute("INSERT INTO video_embeddings VALUES (?, 'a.example')", (f"v{index}",))
    src.commit()
    cache_path = tmp_path / "c" / "x.tmp.1.db"
    cache_path.parent.mkdir()
    cache = random_cache.connect_random_cache_db(cache_path)
    count = random_cache.populate_random_cache(src, cache, 100, True, True, 0, 100)
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    print("PROBE count", count, "positions", [r[0] for r in rows], "rowids", sorted(r[1] for r in rows))
    print("PROBE after commit", sorted(p.name for p in cache_path.parent.iterdir()))
    cache.execute("INSERT INTO random_rowids (position, video_rowid) VALUES (21, 999)")
    print("PROBE uncommitted", sorted(p.name for p in cache_path.parent.iterdir()), "in_transaction", cache.in_transaction)
    cache.close()
    print("PROBE after close", sorted(p.name for p in cache_path.parent.iterdir()))
    bad = tmp_path / "c" / "bad.db"
    bad.write_bytes(b"not a sqlite database" * 10)
    try:
        conn = random_cache.connect_random_cache_db(bad)
        random_cache.ensure_random_cache_schema(conn)
        print("PROBE bad file accepted")
    except sqlite3.Error as exc:
        print("PROBE bad file", type(exc).__name__, exc)
    assert False, "show output"
