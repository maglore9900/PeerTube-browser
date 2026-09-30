import sqlite3
from pathlib import Path


def test_probe(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    seed = sqlite3.connect(path)
    seed.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    seed.execute("INSERT INTO random_rowids VALUES (1, 7)")
    seed.commit()
    seed.close()
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    conn = sqlite3.connect(path, timeout=0)
    try:
        mode = conn.execute("PRAGMA journal_mode=MEMORY").fetchall()
        print("mode", mode, "in_transaction", conn.in_transaction)
        print("count", conn.execute("SELECT COUNT(*) FROM random_rowids").fetchall())
    except sqlite3.Error as exc:
        print("error", repr(exc))
    finally:
        conn.close()
        holder.execute("ROLLBACK")
        holder.close()
    print("sidecars", sorted(p.name for p in tmp_path.iterdir()))
    assert False, "probe"
