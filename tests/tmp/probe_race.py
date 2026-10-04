import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

STORE = r'''
import json, sqlite3, os
from contextlib import contextmanager
VARIANTS = os.environ["VARIANT"].split(",")
VARIANT = "retry_wal" if "retry_wal" in VARIANTS else VARIANTS[0]
if "deferred_claim" in VARIANTS:
    VARIANT_CLAIM = "deferred_claim"
else:
    VARIANT_CLAIM = ""
JOB_COLUMNS = (("queued_at", "INTEGER"), ("started_at", "INTEGER"), ("finished_at", "INTEGER"), ("error", "TEXT"), ("detected_language", "TEXT"), ("attempts", "INTEGER NOT NULL DEFAULT 0"))
_KEY = "video_id = ? AND instance_domain = ? AND target_language = ?"
def connect_subtitles_db(path):
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    if VARIANT == "retry_wal":
        import time
        deadline = time.monotonic() + 30
        while True:
            try:
                conn.execute("PRAGMA journal_mode=WAL").fetchall()
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or time.monotonic() > deadline:
                    raise
                time.sleep(0.01)
    else:
        conn.execute("PRAGMA journal_mode=WAL").fetchall()
    return conn
@contextmanager
def _immediate(conn, kind="IMMEDIATE"):
    conn.execute(f"BEGIN {kind}")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
CREATE = """CREATE TABLE IF NOT EXISTS subtitles (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, target_language TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL, fetched_at INTEGER NOT NULL, track_text TEXT, cues_json TEXT, PRIMARY KEY (video_id, instance_domain, target_language))"""
def ensure_subtitles_schema(conn):
    def body():
        conn.execute(CREATE)
        present = {row[1] for row in conn.execute("PRAGMA table_info(subtitles)")}
        for name, decl in JOB_COLUMNS:
            if name not in present:
                conn.execute(f"ALTER TABLE subtitles ADD COLUMN {name} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS subtitles_state_queued_at ON subtitles (state, queued_at)")
        conn.execute("CREATE TABLE IF NOT EXISTS translate_worker_heartbeat (id INTEGER PRIMARY KEY CHECK (id = 1), beat_at INTEGER NOT NULL, pid INTEGER NOT NULL)")
    if VARIANT == "naive_ensure":
        body()
        conn.commit()
    else:
        with _immediate(conn):
            body()
def store_ready_subtitles(conn, video_id, instance_domain, target_language, source, track_text, cues, fetched_at):
    with conn:
        conn.execute("""INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?) ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE SET state = excluded.state, source = excluded.source, fetched_at = excluded.fetched_at, track_text = excluded.track_text, cues_json = excluded.cues_json""", (video_id, instance_domain, target_language, source, fetched_at, track_text, json.dumps(cues, separators=(",", ":"))))
def enqueue_translate_job(conn, video_id, instance_domain, target_language, cap, queued_at):
    with _immediate(conn):
        row = conn.execute(f"SELECT state FROM subtitles WHERE {_KEY}", (video_id, instance_domain, target_language)).fetchone()
        if row is not None:
            return "exists", row[0]
        (queued,) = conn.execute("SELECT COUNT(*) FROM subtitles WHERE state = 'queued'").fetchone()
        if queued >= cap:
            return "cap", None
        conn.execute("INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, queued_at, attempts) VALUES (?, ?, ?, 'queued', 'whisper', ?, ?, 0) ON CONFLICT(video_id, instance_domain, target_language) DO NOTHING", (video_id, instance_domain, target_language, queued_at, queued_at))
    return "queued", "queued"
def claim_translate_job(conn, target_language, started_at):
    kind = "DEFERRED" if VARIANT_CLAIM == "deferred_claim" else "IMMEDIATE"
    with _immediate(conn, kind):
        row = conn.execute("SELECT video_id, instance_domain FROM subtitles WHERE state = 'queued' AND target_language = ? ORDER BY queued_at, rowid LIMIT 1", (target_language,)).fetchone()
        if row is None:
            return None
        key = (row[0], row[1], target_language)
        conn.execute(f"UPDATE subtitles SET state = 'running', started_at = ?, attempts = attempts + 1 WHERE {_KEY}", (started_at, *key))
        return conn.execute(f"SELECT video_id, instance_domain, started_at, attempts FROM subtitles WHERE {_KEY}", key).fetchone()
def _update_claim(conn, video_id, instance_domain, target_language, started_at, assignments, values):
    with conn:
        cursor = conn.execute(f"UPDATE subtitles SET {assignments} WHERE {_KEY} AND state = 'running' AND started_at = ?", (*values, video_id, instance_domain, target_language, started_at))
    return cursor.rowcount == 1
def store_running_cues(conn, video_id, instance_domain, target_language, started_at, cues, detected_language):
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "cues_json = ?, detected_language = ?", (json.dumps(cues), detected_language))
def finish_translate_ready(conn, video_id, instance_domain, target_language, started_at, cues, finished_at):
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?", (json.dumps(cues), finished_at, finished_at))
def write_translate_heartbeat(conn, beat_at, pid):
    with conn:
        conn.execute("INSERT INTO translate_worker_heartbeat (id, beat_at, pid) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET beat_at = excluded.beat_at, pid = excluded.pid", (beat_at, pid))
'''

UPGRADER = r'''
import sys, time, os
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from fakestore import connect_subtitles_db, ensure_subtitles_schema
go = Path(sys.argv[2])
while not go.exists():
    time.sleep(0.001)
conn = connect_subtitles_db(Path(sys.argv[1]))
ensure_subtitles_schema(conn)
conn.close()
'''

ENGINE = r'''
import sys, time, os
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from fakestore import connect_subtitles_db, ensure_subtitles_schema, store_ready_subtitles
go = Path(sys.argv[2])
while not go.exists():
    time.sleep(0.001)
conn = connect_subtitles_db(Path(sys.argv[1]))
ensure_subtitles_schema(conn)
start = time.time(); n = 0
while time.time() - start < 5:
    store_ready_subtitles(conn, f"e-{n}", "peer.example", "en", "instance", "WEBVTT", [{"start": float(n), "end": n + 0.5, "text": f"engine {n}"}], 1)
    n += 1
    time.sleep(0.001)
print(n)
'''

WORKER = r'''
import sys, time, os
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from fakestore import *
go = Path(sys.argv[2])
while not go.exists():
    time.sleep(0.001)
conn = connect_subtitles_db(Path(sys.argv[1]))
ensure_subtitles_schema(conn)
start = time.time(); n = 0
while time.time() - start < 5:
    time.sleep(0.001)
    enqueue_translate_job(conn, f"w-{n}", "peer.example", "en", 50, n)
    job = claim_translate_job(conn, "en", 1000 + n)
    store_running_cues(conn, f"w-{n}", "peer.example", "en", 1000 + n, [{"start": 0.0, "end": 1.0, "text": "a"}], "fr")
    finish_translate_ready(conn, f"w-{n}", "peer.example", "en", 1000 + n, [{"start": 0.0, "end": 1.0, "text": "a"}], 2)
    write_translate_heartbeat(conn, n, os.getpid())
    n += 1
print(n)
'''

B1_CREATE = "CREATE TABLE subtitles (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, target_language TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL, fetched_at INTEGER NOT NULL, track_text TEXT, cues_json TEXT, PRIMARY KEY (video_id, instance_domain, target_language))"


def _b1(path):
    c = sqlite3.connect(path)
    c.execute(B1_CREATE)
    c.commit()
    c.close()


def _pair(tmp, variant, scripts, rounds, tag):
    lib = tmp / "lib"
    lib.mkdir(exist_ok=True)
    (lib / "fakestore.py").write_text(STORE)
    bad = 0
    out = []
    for r in range(rounds):
        db = tmp / f"{tag}-{variant}-{r}.db"
        go = tmp / f"{tag}-{variant}-{r}.go"
        _b1(db)
        procs = [subprocess.Popen([str(ENGINE_PY), "-c", s, str(db), str(go), str(lib)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={"VARIANT": variant}) for s in scripts]
        time.sleep(0.3)
        go.touch()
        res = [p.communicate(timeout=60) + (p.returncode,) for p in procs]
        failed = [(rc, err.strip().splitlines()[-4:]) for _, err, rc in res if rc != 0 or "locked" in err or "duplicate" in err]
        if failed:
            bad += 1
            out.append(failed)
        else:
            out.append([o.strip() for o, _, _ in res])
    return bad, out[:4]


def test_probe(tmp_path):
    print("r8 good", _pair(tmp_path, "retry_wal", [ENGINE, WORKER], 3, "r8a"))
    print("r8 deferred", _pair(tmp_path, "retry_wal,deferred_claim", [ENGINE, WORKER], 4, "r8b"))
    assert False
