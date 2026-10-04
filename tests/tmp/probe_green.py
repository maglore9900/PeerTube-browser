import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

FAKE = r'''
import json, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
SUBTITLES_BUSY_TIMEOUT_SECONDS = 30.0
JOB_COLUMNS = (("queued_at", "INTEGER"), ("started_at", "INTEGER"), ("finished_at", "INTEGER"), ("error", "TEXT"), ("detected_language", "TEXT"), ("attempts", "INTEGER NOT NULL DEFAULT 0"))
_KEY = "video_id = ? AND instance_domain = ? AND target_language = ?"
RETRY = RETRY_FLAG
def connect_subtitles_db(path):
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False, timeout=SUBTITLES_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    deadline = time.monotonic() + SUBTITLES_BUSY_TIMEOUT_SECONDS
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchall()
            return conn
        except sqlite3.OperationalError as exc:
            if not RETRY or "locked" not in str(exc) or time.monotonic() > deadline:
                raise
            time.sleep(0.01)
@contextmanager
def _immediate(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
@contextmanager
def _naive(conn):
    yield
    conn.commit()
def ensure_subtitles_schema(conn):
    with (_naive(conn) if NAIVE_FLAG else _immediate(conn)):
        conn.execute("""CREATE TABLE IF NOT EXISTS subtitles (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, target_language TEXT NOT NULL, state TEXT NOT NULL, source TEXT NOT NULL, fetched_at INTEGER NOT NULL, track_text TEXT, cues_json TEXT, PRIMARY KEY (video_id, instance_domain, target_language))""")
        present = {row[1] for row in conn.execute("PRAGMA table_info(subtitles)")}
        for name, declaration in JOB_COLUMNS:
            if name not in present:
                conn.execute(f"ALTER TABLE subtitles ADD COLUMN {name} {declaration}")
        conn.execute("CREATE INDEX IF NOT EXISTS subtitles_state_queued_at ON subtitles (state, queued_at)")
        conn.execute("CREATE TABLE IF NOT EXISTS translate_worker_heartbeat (id INTEGER PRIMARY KEY CHECK (id = 1), beat_at INTEGER NOT NULL, pid INTEGER NOT NULL)")
def fetch_ready_subtitles(conn, video_id, instance_domain, target_language):
    row = conn.execute("SELECT cues_json FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = ? AND state = 'ready'", (video_id, instance_domain, target_language)).fetchone()
    if row is None:
        return None
    try:
        cues = json.loads(row["cues_json"] or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) and cues else None
def store_ready_subtitles(conn, video_id, instance_domain, target_language, source, track_text, cues, fetched_at):
    with conn:
        conn.execute("""INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?) ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE SET state = excluded.state, source = excluded.source, fetched_at = excluded.fetched_at, track_text = excluded.track_text, cues_json = excluded.cues_json""", (video_id, instance_domain, target_language, source, fetched_at, track_text, json.dumps(cues, ensure_ascii=False, separators=(",", ":"))))
def _cues_text(cues):
    return json.dumps(cues, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
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
    with _immediate(conn):
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
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "cues_json = ?, detected_language = ?", (_cues_text(cues), detected_language))
def finish_translate_ready(conn, video_id, instance_domain, target_language, started_at, cues, finished_at):
    return _update_claim(conn, video_id, instance_domain, target_language, started_at, "state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?", (_cues_text(cues), finished_at, finished_at))
def write_translate_heartbeat(conn, beat_at, pid):
    with conn:
        conn.execute("INSERT INTO translate_worker_heartbeat (id, beat_at, pid) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET beat_at = excluded.beat_at, pid = excluded.pid", (beat_at, pid))
'''


@pytest.mark.parametrize("retry,naive", [(False, False), (True, False)])
def test_probe(tmp_path, monkeypatch, retry, naive):
    attempt = (retry, naive)
    lib = tmp_path / "lib"
    (lib / "data").mkdir(parents=True)
    (lib / "data" / "__init__.py").write_text("")
    (lib / "data" / "subtitles.py").write_text(FAKE.replace("RETRY_FLAG", str(retry)).replace("NAIVE_FLAG", str(naive)))
    spec = importlib.util.spec_from_file_location("checkpoint", HERE / "test_49_translate_whisper_worker_phase1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "SERVER_DIR", lib)
    monkeypatch.syspath_prepend(str(lib))
    for name in ("data", "data.subtitles"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    caught = 0
    for r in range(48):
        path = tmp_path / f"r{r}.db"
        module._b1_file(path)
        res = module._run_together([(module.UPGRADE_SCRIPT, [str(path)]), (module.UPGRADE_SCRIPT, [str(path)])], tmp_path, f"r{r}")
        errs = [(rc, err.strip().splitlines()[-3:], sorted(module.json.loads(out)) == sorted(module.ALL_COLUMNS) if rc == 0 else None) for rc, out, err in res if rc != 0 or err.strip() or sorted(module.json.loads(out)) != sorted(module.ALL_COLUMNS)]
        if errs:
            caught += 1
            print("round", r, errs)
    print("attempt", attempt, "rounds caught", caught, "of 48")
    results = {}
    real = module._run_together
    def spy(scripts, tmp, tag):
        res = real(scripts, tmp, tag)
        for rc, out, err in res:
            if rc != 0 or err.strip():
                print("spy", tag, rc, out.strip()[:60], err.strip().splitlines()[-3:])
        return res
    monkeypatch.setattr(module, "_run_together", spy)
    for name in ["test_two_upgraders_racing_on_one_b1_file_both_succeed_and_leave_one_set_of_job_columns"] * 3 + ["test_a_b1_file_upgrades_in_place_to_wal_with_the_job_columns_and_reads_its_old_cues_unchanged"]:
        sub = tmp_path / f"{name[:20]}-{len(results)}"
        sub.mkdir()
        try:
            getattr(module, name)(sub)
            results[f"{name[:40]}-{len(results)}"] = "PASS"
        except BaseException as exc:
            import traceback
            results[f"{name[:40]}-{len(results)}"] = f"FAIL {type(exc).__name__}: {str(exc)[:300]} {traceback.format_exc()[-600:]}"
    print("retry", retry, results)
    assert False
