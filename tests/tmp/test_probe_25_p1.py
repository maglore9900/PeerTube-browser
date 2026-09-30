import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY  # noqa: E402

JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"


def _run(tmp_path, out_path, *args):
    return subprocess.run([str(ENGINE_PY), str(JOB), "--db", str(tmp_path / "source.db"), "--index", str(tmp_path / "missing.faiss"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, timeout=120)


def test_probe(tmp_path):
    print("ENGINE_PY", ENGINE_PY, ENGINE_PY.exists())
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER)")
    conn.commit()
    conn.close()
    out = tmp_path / "similarity-cache.db"
    seed = _run(tmp_path, out, "--reset-only")
    print("SEED rc", seed.returncode, "stderr", repr(seed.stderr), "exists", out.exists())
    conn = sqlite3.connect(out)
    print("TABLES", conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall())
    conn.execute("INSERT INTO similarity_sources VALUES ('sentinel-video', 'sentinel.example', 1)")
    conn.execute("INSERT INTO similarity_items VALUES ('sentinel-video', 'sentinel.example', 'other-video', 'sentinel.example', 0.5, 1)")
    conn.commit()
    conn.close()
    print("DIR", sorted(p.name for p in tmp_path.iterdir()))
    before = (out.read_bytes(), out.stat().st_mtime_ns)
    for flag in ["--incremental", "--reset", "--reset-only", "--recreate-out-db"]:
        run = _run(tmp_path, out, "--refresh-existing", flag, "--cpu")
        print("FLAG", flag, "rc", run.returncode, "stderr", repr(run.stderr))
    print("UNCHANGED", (out.read_bytes(), out.stat().st_mtime_ns) == before)
    absent = tmp_path / "absent.db"
    run = _run(tmp_path, absent, "--reset", "--cpu", "--bogus")
    print("BOGUS rc", run.returncode, "stderr", repr(run.stderr))
    plain = _run(tmp_path, absent, "--cpu")
    print("PLAIN rc", plain.returncode, "stderr tail", repr(plain.stderr[-600:]), "absent exists", absent.exists())
