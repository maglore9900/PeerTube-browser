from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _h(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big") & ((1 << 63) - 1)


def test_values():
    for key in ["v1::a.example", "v2::a.example", "v3::b.example", "v3::B.Example."]:
        print("HASH", key, _h(key))
    from data.ann_ids import compute_ann_id
    for v, h in [("v1", "a.example"), ("v2", "a.example"), ("v3", "B.Example.")]:
        print("COMPUTE", v, h, compute_ann_id(v, h))


def test_unique_index_error_class():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(7,), (7,)])
    try:
        conn.execute("CREATE UNIQUE INDEX i ON t (a)")
    except Exception as exc:
        print("ERROR", type(exc).__module__, type(exc).__name__, exc)


def test_rowid_copy_and_table_info():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a TEXT NOT NULL, PRIMARY KEY (a))")
    conn.executemany("INSERT INTO t (rowid, a) VALUES (?, ?)", [(2, "x"), (5, "y"), (9, "z")])
    conn.execute("CREATE TABLE t_new (a TEXT NOT NULL, b INTEGER NOT NULL, PRIMARY KEY (a))")
    conn.execute("INSERT INTO t_new (rowid, a, b) SELECT rowid, a, 1 FROM t")
    print("ROWS", conn.execute("SELECT rowid, * FROM t_new ORDER BY rowid").fetchall())
    print("INFO", conn.execute("PRAGMA table_info(t_new)").fetchall())
    print("INTX", conn.in_transaction)
