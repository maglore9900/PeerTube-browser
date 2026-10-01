import sqlite3
import subprocess

import pytest


def test_probe(tmp_path):
    print("cpe str:", repr(str(subprocess.CalledProcessError(1, ["precompute-similar-ann.py"]))))
    garbage = tmp_path / "g.db"
    garbage.write_bytes(b"not a sqlite database\n" * 64)
    conn = sqlite3.connect(f"file:{garbage.as_posix()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA integrity_check").fetchall()
        print("integrity: no raise")
    except sqlite3.Error as exc:
        print("integrity raise:", type(exc).__name__, repr(str(exc)))
    finally:
        conn.close()
    with pytest.raises(RuntimeError) as excinfo:
        raise NotImplementedError
    print("stub caught by raises(RuntimeError):", excinfo.type.__name__, "type is RuntimeError:", excinfo.type is RuntimeError)
    msg = "Similarity gate failed: shadow unreadable: file is not a database"
    with pytest.raises(RuntimeError, match=r"^Similarity gate failed: shadow unreadable: .*not a database") as excinfo:
        raise RuntimeError(msg)
    print("match ok")
