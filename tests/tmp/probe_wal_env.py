import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

RO_SCRIPT = r"""
import sqlite3, sys
conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(conn.execute("PRAGMA journal_mode").fetchone()[0], conn.execute("SELECT COUNT(*) FROM t").fetchone()[0], sqlite3.sqlite_version)
"""


def test_probe(tmp_path):
    print("pytest python", sys.version, "sqlite", sqlite3.sqlite_version)
    print("ENGINE_PY exists", ENGINE_PY.exists())
    if ENGINE_PY.exists():
        print(subprocess.run([str(ENGINE_PY), "-c", "import sys, sqlite3; print(sys.version, sqlite3.sqlite_version)"], capture_output=True, text=True).stdout)
    path = tmp_path / "x.db"
    conn = sqlite3.connect(path)
    print("set wal ->", conn.execute("PRAGMA journal_mode=WAL").fetchall())
    conn.execute("CREATE TABLE t (a)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    print("files after close", sorted(p.name for p in tmp_path.iterdir()))
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    print("ro pytest", ro.execute("PRAGMA journal_mode").fetchone(), ro.execute("SELECT COUNT(*) FROM t").fetchone())
    ro.close()
    for py in (sys.executable, str(ENGINE_PY)):
        r = subprocess.run([py, "-c", RO_SCRIPT, str(path)], capture_output=True, text=True)
        print("ro sub", py, r.returncode, r.stdout, r.stderr)
    # B1 file default journal mode and current ensure on default file
    b1 = tmp_path / "b1.db"
    c = sqlite3.connect(b1)
    print("b1 default mode", c.execute("PRAGMA journal_mode").fetchone())
    c.close()
    # what does a duplicate ALTER say
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE s (a)")
    c.execute("ALTER TABLE s ADD COLUMN q INTEGER")
    try:
        c.execute("ALTER TABLE s ADD COLUMN q INTEGER")
    except sqlite3.OperationalError as exc:
        print("dup alter:", exc)
    print("index_info shape", c.execute("PRAGMA index_list(s)").fetchall())
    assert False
