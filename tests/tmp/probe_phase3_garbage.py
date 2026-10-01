import sqlite3


def test_probe(tmp_path):
    path = tmp_path / "x.next.db"
    path.write_bytes(b"not a sqlite database\n" * 64)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        print("ERR", type(exc).__name__, repr(str(exc)))
    finally:
        conn.close()
    print("files", sorted(p.name for p in tmp_path.iterdir()))
    assert False
