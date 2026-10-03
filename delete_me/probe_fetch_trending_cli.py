import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.ann_ids import create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

JOB = SERVER_DIR / "db" / "jobs" / "fetch-trending.py"


def _ready(path):
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "engine" / "crawler" / "schema.sql").read_text(encoding="utf-8"))
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    conn.commit()
    return conn


def test_probe_cli(tmp_path):
    _ready(tmp_path / "ready.db").close()
    ok = subprocess.run([sys.executable, str(JOB), "--db", str(tmp_path / "ready.db")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    print("OK rc", ok.returncode, "stderr", ok.stderr)
    bad = subprocess.run([sys.executable, str(JOB), "--db", str(tmp_path / "absent.db")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    print("MISSING rc", bad.returncode, "stderr", bad.stderr, "exists", (tmp_path / "absent.db").exists())


def test_probe_schema_under_lock(tmp_path):
    path = tmp_path / "w.db"
    conn = _ready(path)
    ensure_trending_schema(conn)
    conn.close()
    conn = sqlite3.connect(path, timeout=0.2)
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        ensure_trending_schema(conn)
        print("SCHEMA under lock: no error")
    except sqlite3.OperationalError as exc:
        print("SCHEMA under lock:", exc)
    try:
        conn.execute("BEGIN IMMEDIATE")
        print("BEGIN under lock: no error")
    except sqlite3.OperationalError as exc:
        print("BEGIN under lock:", exc)
    holder.rollback()
