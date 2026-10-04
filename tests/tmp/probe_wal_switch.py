import sqlite3
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

SCRIPT = r"""
import sqlite3, sys, time
from pathlib import Path
db, ready, go = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
ready.touch()
while not go.exists():
    time.sleep(0.001)
conn = sqlite3.connect(db, timeout=30)
try:
    print("result", conn.execute("PRAGMA journal_mode=WAL").fetchall())
except Exception as exc:
    print("raised", type(exc).__name__, exc)
"""


def test_probe(tmp_path):
    outcomes = {}
    for i in range(60):
        db = tmp_path / f"p{i}.db"
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE t (a)")
        c.execute("INSERT INTO t VALUES (1)")
        c.commit()
        c.close()
        go = tmp_path / f"p{i}.go"
        readies = [tmp_path / f"p{i}.r{j}" for j in range(2)]
        procs = [subprocess.Popen([str(ENGINE_PY), "-c", SCRIPT, str(db), str(r), str(go)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for r in readies]
        while not all(r.exists() for r in readies):
            time.sleep(0.002)
        go.touch()
        for p in procs:
            out, err = p.communicate(timeout=60)
            key = (out.strip(), err.strip()[-200:])
            outcomes[key] = outcomes.get(key, 0) + 1
    print(outcomes)
    assert False, outcomes
