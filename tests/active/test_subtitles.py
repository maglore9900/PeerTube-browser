"""`engine/server/data/subtitles.py`: a B1 subtitles.db is upgraded in place to a WAL file carrying the translate-job columns, even under racing upgraders; an Engine and a translate worker write it at once without a lock error; the queue hands jobs out oldest first, and start-up recovery requeues a running job once and fails it the second time it is found running.

Upgrade (store functions called directly, on a file built with B1's exact CREATE TABLE and two B1 `ready`/`instance` rows, in rollback-journal mode before the upgrade):

- After `connect_subtitles_db` + `ensure_subtitles_schema`, run twice as two Engine starts would, the table has exactly B1's eight columns plus `queued_at`, `started_at`, `finished_at`, `error`, `detected_language` and `attempts`, an index covers exactly `(state, queued_at)`, and `translate_worker_heartbeat` has `id`, `beat_at` and `pid`.
- A fresh plain connection reads `PRAGMA journal_mode` as `wal`.
- The old rows keep their rowids and every B1 column byte for byte, read NULL in the five nullable job columns and 0 in `attempts`, and `fetch_ready_subtitles` returns the same cues for them before and after the upgrade.
- Once the last writer has closed, a `mode=ro` connection still reads the file as `wal` with those cues, in pytest's Python and in a subprocess under `ENGINE_PY`.

Concurrent upgrade: in each of twenty-four rounds, two `ENGINE_PY` subprocesses released together from one barrier, which both must have reached before release, open and upgrade the same fresh B1 file. Both exit 0 with neither `duplicate column` nor `database is locked` on stderr, each sees exactly the fourteen columns afterwards, and so does the file, which a fresh plain connection then reads as `wal`.

Concurrent writers: two `ENGINE_PY` subprocesses released together from the same kind of barrier run for 5 s against one B1 file and overlap for at least 3 s. The Engine script runs `ensure_subtitles_schema`, then `store_ready_subtitles` on its own keys. The worker script runs `ensure_subtitles_schema`, then per key `enqueue_translate_job`, `claim_translate_job` (whose handle must carry that key), the handle's `write_running_cues` and `end_ready`, and `write_translate_heartbeat`. Each must write at least 100 keys. Both exit 0 with no `database is locked` on stderr. Afterwards every Engine key reads `ready`/`instance` with its own cue, every worker key reads `ready`/`whisper` with its full two-cue list, no other row exists besides B1's two (which still read their cues), and the single heartbeat row holds the worker's pid and its last beat.

Queue (store functions called directly on a tmp subtitles.db opened with `connect_subtitles_db` + `ensure_subtitles_schema`):

- Three queued jobs inserted out of queued_at order are claimed oldest queued_at first, each becoming running with the given started_at and its attempts plus one; a failed and a running row with older queued_at are never claimed, and a fourth claim answers None.
- Recovery runs only through `open_translate_worker_store`, under the worker lock's flock the test holds: `open_subtitles_db` on the same file leaves a claimed job running; the worker opener then requeues it with attempts 1 (attempts kept, no error, no finished_at) and answers (1, 0); claimed again (attempts 2) and recovered again beside two attempts-1 running jobs, it becomes failed with "worker stopped while running twice" and that finished_at while the other two are requeued, answering (2, 1); a queued and a ready row are untouched by both.

Claim handle (v-1 queued at 1000 and claimed at 2000):

- After `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the running row, each of the six `TranslateJob` methods (running cues, ready, already_english, failed, requeue, ready from the instance track) returns False and every column of every row, rowid included, reads the same; the same method on a fresh claim returns True and changes the row.
- With the claim held, `end_ready_from_instance` returns True and leaves exactly ready, instance, the track text, compact cues, fetched_at and finished_at both the given time, and detected_language, error, attempts, queued_at and started_at as the running job had them.

Openers:

- `open_subtitles_db` on `a/b/subtitles.db` with neither directory present creates both, and the file has the fourteen columns, the `(state, queued_at)` index, the heartbeat table and journal mode `wal`; on a rollback-journal B1 file the same four facts hold afterwards and both connections read B1's cues unchanged.
- While a separate `os.open` description of the worker lock holds LOCK_EX, `open_translate_worker_store` raises BlockingIOError (bounded by an alarm) and neither the file nor its directory exists; once the holder is closed the same call returns (0, 0), and a third description is then refused the lock.

Readers (store functions called directly on the same kind of tmp subtitles.db), which the state route reads a key and the worker's availability through:

- `fetch_subtitle_state` gives None for a key with no row, and for the same video under another language or host; a queued key gives `("queued", None)`; a running key whose cues_json was hand-damaged gives `("running", "{not json")`, the text unparsed.
- `fetch_translate_heartbeat` gives None on a fresh schema, then the beat_at last written: 1234, then 5678.

The concurrent cases run as explicit scripts under `ENGINE_PY`, the interpreter the Engine and the worker run under, never through multiprocessing. Every database is under `tmp_path`, never the repo's own subtitles.db.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# B1's CREATE TABLE as delivered (subtitles.py before the translate-job columns), so the file under test is the shape the Engine already wrote in production.
B1_CREATE = """
CREATE TABLE IF NOT EXISTS subtitles (
  video_id TEXT NOT NULL,
  instance_domain TEXT NOT NULL,
  target_language TEXT NOT NULL,
  state TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  track_text TEXT,
  cues_json TEXT,
  PRIMARY KEY (video_id, instance_domain, target_language)
)
"""
B1_COLUMNS = ["video_id", "instance_domain", "target_language", "state", "source", "fetched_at", "track_text", "cues_json"]
JOB_COLUMN_NAMES = {"queued_at", "started_at", "finished_at", "error", "detected_language", "attempts"}
ALL_COLUMNS = set(B1_COLUMNS) | JOB_COLUMN_NAMES
B1_ROWS = [
    ("v-1", "peer.example", "en", "ready", "instance", 1700000000000, "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello\n", '[{"start":1.0,"end":2.5,"text":"Hello"}]'),
    ("v-2", "other.example", "en", "ready", "instance", 1700000000001, "WEBVTT\n\n00:00:00.500 --> 00:00:01.000\nOne\n\n00:00:03.000 --> 00:00:04.250\nTwo\n", '[{"start":0.5,"end":1.0,"text":"One"},{"start":3.0,"end":4.25,"text":"Two"}]'),
]
B1_CUES = {
    ("v-1", "peer.example"): [{"start": 1.0, "end": 2.5, "text": "Hello"}],
    ("v-2", "other.example"): [{"start": 0.5, "end": 1.0, "text": "One"}, {"start": 3.0, "end": 4.25, "text": "Two"}],
}
# A check-then-alter left outside one IMMEDIATE transaction raced into "duplicate column" in about 40% of rounds when probed, so 24 rounds miss it about once in 200,000 runs; a `PRAGMA journal_mode=WAL` switch with no retry on "database is locked" also failed here, in 1 of 48 probed rounds.
UPGRADE_ROUNDS = 24
WRITE_SECONDS = 5.0
BEAT_BASE = 1700000500000
ENGINE_HOST = "engine.example"
WORKER_HOST = "worker.example"
HOST = "peer.example"
RECOVERY_TEXT = "worker stopped while running twice"
# A row as B1's route stores it: ready/instance, with no job column set.
B1_READY_INSTANCE = {"state": "ready", "source": "instance", "fetched_at": 1700000000000, "track_text": "WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n", "cues_json": '[{"start":1.0,"end":2.0,"text":"Hello"}]'}

# Each script: argv is server_dir, db, ready file, go file; it imports, touches its ready file, waits for go, then works, so both processes hit the file at the same moment.
UPGRADE_SCRIPT = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from data.subtitles import connect_subtitles_db, ensure_subtitles_schema
db, ready, go = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
ready.touch()
while not go.exists():
    time.sleep(0.001)
conn = connect_subtitles_db(db)
ensure_subtitles_schema(conn)
print(json.dumps([row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]))
conn.close()
"""

ENGINE_SCRIPT = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from data.subtitles import connect_subtitles_db, ensure_subtitles_schema, store_ready_subtitles
db, ready, go, seconds, host = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
ready.touch()
while not go.exists():
    time.sleep(0.001)
start = time.time()
conn = connect_subtitles_db(db)
ensure_subtitles_schema(conn)
n = 0
while time.time() - start < seconds:
    store_ready_subtitles(conn, f"e-{n}", host, "en", "instance", f"WEBVTT {n}", [{"start": float(n), "end": n + 0.5, "text": f"engine {n}"}], 1700000000000 + n)
    n += 1
    # A pause per write so the two processes interleave instead of one starving the other on the write lock.
    time.sleep(0.001)
conn.close()
print(json.dumps({"n": n, "start": start, "end": time.time()}))
"""

WORKER_SCRIPT = r"""
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, write_translate_heartbeat
db, ready, go, seconds, host, beat_base = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), float(sys.argv[5]), sys.argv[6], int(sys.argv[7])
ready.touch()
while not go.exists():
    time.sleep(0.001)
start = time.time()
conn = connect_subtitles_db(db)
ensure_subtitles_schema(conn)
n = 0
while time.time() - start < seconds:
    key = f"w-{n}"
    outcome = enqueue_translate_job(conn, key, host, "en", 50, 1700000000000 + n)
    if tuple(outcome) != ("queued", "queued"):
        raise SystemExit(f"enqueue {key}: {outcome!r}")
    job = claim_translate_job(conn, "en", 1700000100000 + n)
    if job is None or (job.video_id, job.instance_domain) != (key, host):
        raise SystemExit(f"claim after enqueue {key}: {None if job is None else (job.video_id, job.instance_domain)!r}")
    first = [{"start": n + 0.0, "end": n + 0.4, "text": f"worker {n} a"}]
    if not job.write_running_cues(first, "fr"):
        raise SystemExit(f"write_running_cues {key} matched no row")
    full = first + [{"start": n + 0.5, "end": n + 0.9, "text": f"worker {n} b"}]
    if not job.end_ready(full, 1700000200000 + n):
        raise SystemExit(f"end_ready {key} matched no row")
    write_translate_heartbeat(conn, beat_base + n, os.getpid())
    n += 1
    time.sleep(0.001)
conn.close()
print(json.dumps({"n": n, "start": start, "end": time.time(), "pid": os.getpid()}))
"""


def _b1_file(path: Path) -> None:
    """A subtitles.db exactly as B1 left it: B1's table, two ready/instance rows, the default rollback journal."""
    conn = sqlite3.connect(path)
    conn.execute(B1_CREATE)
    conn.executemany("INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", B1_ROWS)
    conn.commit()
    conn.close()


def _plain(path: Path) -> sqlite3.Connection:
    """A connection that sets nothing, so what it reads is what the file itself holds."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _old_cues(conn: sqlite3.Connection) -> dict[tuple[str, str], object]:
    from data.subtitles import fetch_ready_subtitles

    return {key: fetch_ready_subtitles(conn, key[0], key[1], "en") for key in B1_CUES}


def _run_together(scripts: list[tuple[str, list[str]]], tmp_path: Path, tag: str) -> tuple[bool, list[tuple[int, str, str]]]:
    """Start each script under ENGINE_PY, release them together once all have imported, and return whether every script reached the barrier before release, with (returncode, stdout, stderr) per script."""
    go = tmp_path / f"{tag}.go"
    readies = [tmp_path / f"{tag}.ready{i}" for i in range(len(scripts))]
    procs = [subprocess.Popen([str(ENGINE_PY), "-c", script, str(SERVER_DIR), args[0], str(ready), str(go), *args[1:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for (script, args), ready in zip(scripts, readies)]
    deadline = time.monotonic() + 30
    while not all(ready.exists() for ready in readies) and time.monotonic() < deadline and all(proc.poll() is None for proc in procs):
        time.sleep(0.005)
    # Read before go is touched: a script that had not reached its ready file by now would start late and run serially.
    synced = all(ready.exists() for ready in readies)
    go.touch()
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        results.append((proc.returncode, out, err))
    return synced, results


def _subtitles(path: Path) -> sqlite3.Connection:
    """The subtitles store as the Engine opens it."""
    from data.subtitles import connect_subtitles_db, ensure_subtitles_schema

    conn = connect_subtitles_db(path)
    ensure_subtitles_schema(conn)
    return conn


def _insert(conn: sqlite3.Connection, video_id: str, instance_domain: str, values: dict) -> None:
    columns = {"video_id": video_id, "instance_domain": instance_domain, "target_language": "en", **values}
    conn.execute(f"INSERT INTO subtitles ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", tuple(columns.values()))
    conn.commit()


def _snapshot(path: Path) -> tuple[list[str], list[tuple]]:
    """Every column name and every row as SQL literals (quote() carries type and bytes), rowid first, through a fresh plain connection."""
    conn = sqlite3.connect(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        rows = [tuple(row) for row in conn.execute(f"SELECT rowid, {', '.join(f'quote({column})' for column in columns)} FROM subtitles ORDER BY rowid")]
        return columns, rows
    finally:
        conn.close()


def test_a_b1_file_upgrades_in_place_to_wal_with_the_job_columns_and_reads_its_old_cues_unchanged(tmp_path):
    from data.subtitles import connect_subtitles_db, ensure_subtitles_schema

    path = tmp_path / "subtitles.db"
    _b1_file(path)
    before = _plain(path)
    # Controls: the file is a rollback-journal B1 file and B1's reader already returns these cues from it.
    assert before.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert _old_cues(before) == B1_CUES
    rows_before = before.execute(f"SELECT rowid, {', '.join(B1_COLUMNS)} FROM subtitles ORDER BY rowid").fetchall()
    before.close()

    conn = connect_subtitles_db(path)
    ensure_subtitles_schema(conn)
    ensure_subtitles_schema(conn)
    assert _old_cues(conn) == B1_CUES
    conn.close()

    after = _plain(path)
    columns = [row[1] for row in after.execute("PRAGMA table_info(subtitles)")]
    assert sorted(columns) == sorted(ALL_COLUMNS)
    indexed = [[info[2] for info in after.execute(f"PRAGMA index_info('{index[1]}')")] for index in after.execute("PRAGMA index_list(subtitles)")]
    assert ["state", "queued_at"] in indexed
    assert [row[1] for row in after.execute("PRAGMA table_info(translate_worker_heartbeat)")] == ["id", "beat_at", "pid"]
    assert after.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert after.execute(f"SELECT rowid, {', '.join(B1_COLUMNS)} FROM subtitles ORDER BY rowid").fetchall() == rows_before
    assert [tuple(row) for row in after.execute("SELECT queued_at, started_at, finished_at, error, detected_language, attempts FROM subtitles ORDER BY rowid")] == [(None, None, None, None, None, 0)] * 2
    after.close()

    # Control: every connection is closed, so SQLite has removed the sidecars and the read-only opener meets the after-last-writer case.
    assert not (tmp_path / "subtitles.db-wal").exists()
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    assert ro.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert _old_cues(ro) == B1_CUES
    ro.close()
    ro_script = "import json, sqlite3, sys\nsys.path.insert(0, sys.argv[1])\nfrom data.subtitles import fetch_ready_subtitles\nconn = sqlite3.connect(f'file:{sys.argv[2]}?mode=ro', uri=True)\nconn.row_factory = sqlite3.Row\nprint(json.dumps([conn.execute('PRAGMA journal_mode').fetchone()[0], fetch_ready_subtitles(conn, 'v-1', 'peer.example', 'en'), fetch_ready_subtitles(conn, 'v-2', 'other.example', 'en')]))\n"
    engine_read = subprocess.run([str(ENGINE_PY), "-c", ro_script, str(SERVER_DIR), str(path)], capture_output=True, text=True, timeout=60)
    assert engine_read.returncode == 0, engine_read.stderr
    assert json.loads(engine_read.stdout) == ["wal", B1_CUES[("v-1", "peer.example")], B1_CUES[("v-2", "other.example")]]


def test_two_upgraders_racing_on_one_b1_file_both_succeed_and_leave_one_set_of_job_columns(tmp_path):
    failures = []
    for round_no in range(UPGRADE_ROUNDS):
        path = tmp_path / f"race-{round_no}.db"
        _b1_file(path)
        synced, results = _run_together([(UPGRADE_SCRIPT, [str(path)]), (UPGRADE_SCRIPT, [str(path)])], tmp_path, f"race-{round_no}")
        if not synced:
            failures.append((round_no, "released before both upgraders reached the barrier"))
        for returncode, out, err in results:
            if returncode != 0 or "duplicate column" in err or "database is locked" in err:
                failures.append((round_no, returncode, err.strip().splitlines()[-1:]))
            elif sorted(json.loads(out)) != sorted(ALL_COLUMNS):
                failures.append((round_no, "columns seen", json.loads(out)))
        final = _plain(path)
        seen = [row[1] for row in final.execute("PRAGMA table_info(subtitles)")]
        mode = final.execute("PRAGMA journal_mode").fetchone()[0]
        final.close()
        if sorted(seen) != sorted(ALL_COLUMNS):
            failures.append((round_no, "file columns", seen))
        if mode != "wal":
            failures.append((round_no, "file journal_mode", mode))
    assert failures == []


def test_an_engine_and_a_worker_writing_one_file_at_once_never_hit_a_lock_and_leave_every_row_ready_with_its_own_cues(tmp_path):
    from data.subtitles import fetch_ready_subtitles

    assert ENGINE_PY.exists(), f"the Engine interpreter is missing at {ENGINE_PY}"
    path = tmp_path / "subtitles.db"
    _b1_file(path)
    synced, ((engine_rc, engine_out, engine_err), (worker_rc, worker_out, worker_err)) = _run_together([(ENGINE_SCRIPT, [str(path), str(WRITE_SECONDS), ENGINE_HOST]), (WORKER_SCRIPT, [str(path), str(WRITE_SECONDS), WORKER_HOST, str(BEAT_BASE)])], tmp_path, "writers")
    assert "database is locked" not in engine_err, engine_err
    assert "database is locked" not in worker_err, worker_err
    assert engine_rc == 0, engine_err
    assert worker_rc == 0, worker_err
    assert synced, "released before both writers reached the barrier"
    engine_run = json.loads(engine_out)
    worker_run = json.loads(worker_out)
    # Concurrency was real: both wrote many keys and their write windows overlapped for most of the run.
    assert engine_run["n"] >= 100 and worker_run["n"] >= 100, (engine_run, worker_run)
    assert min(engine_run["end"], worker_run["end"]) - max(engine_run["start"], worker_run["start"]) >= 3.0, (engine_run, worker_run)

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = {(row["video_id"], row["instance_domain"]): (row["state"], row["source"]) for row in conn.execute("SELECT video_id, instance_domain, state, source FROM subtitles")}
    engine_keys = {(f"e-{n}", ENGINE_HOST) for n in range(engine_run["n"])}
    worker_keys = {(f"w-{n}", WORKER_HOST) for n in range(worker_run["n"])}
    assert set(rows) == engine_keys | worker_keys | set(B1_CUES)
    wrong_engine = []
    for key in sorted(engine_keys):
        n = int(key[0][2:])
        cues = fetch_ready_subtitles(conn, key[0], key[1], "en")
        if rows[key] != ("ready", "instance") or cues != [{"start": float(n), "end": n + 0.5, "text": f"engine {n}"}]:
            wrong_engine.append((key, rows[key], cues))
    assert wrong_engine == []
    wrong_worker = []
    for key in sorted(worker_keys):
        n = int(key[0][2:])
        full = [{"start": n + 0.0, "end": n + 0.4, "text": f"worker {n} a"}, {"start": n + 0.5, "end": n + 0.9, "text": f"worker {n} b"}]
        cues = fetch_ready_subtitles(conn, key[0], key[1], "en")
        if rows[key] != ("ready", "whisper") or cues != full:
            wrong_worker.append((key, rows[key], cues))
    assert wrong_worker == []
    assert _old_cues(conn) == B1_CUES
    assert [tuple(row) for row in conn.execute("SELECT beat_at, pid FROM translate_worker_heartbeat")] == [(BEAT_BASE + worker_run["n"] - 1, worker_run["pid"])]
    conn.close()


def test_claim_hands_out_queued_jobs_oldest_first_each_running_with_its_started_at_and_one_more_attempt(tmp_path):
    from data.subtitles import claim_translate_job

    conn = _subtitles(tmp_path / "subtitles.db")
    # Inserted out of queued_at order, so a claim by rowid shows; b was already claimed once before.
    _insert(conn, "c", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
    _insert(conn, "a", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
    _insert(conn, "b", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 1})
    # Older than every queued job, but not queued.
    _insert(conn, "f", HOST, {"state": "failed", "source": "whisper", "fetched_at": 500, "queued_at": 500, "started_at": 600, "finished_at": 700, "error": "boom", "attempts": 1})
    _insert(conn, "r", HOST, {"state": "running", "source": "whisper", "fetched_at": 400, "queued_at": 400, "started_at": 4000, "attempts": 1})

    claimed = [claim_translate_job(conn, "en", started_at) for started_at in (5001, 5002, 5003, 5004)]

    assert [None if job is None else (job.video_id, job.instance_domain, job.started_at, job.attempts) for job in claimed] == [("a", HOST, 5001, 1), ("b", HOST, 5002, 2), ("c", HOST, 5003, 1), None]
    stored = {row[0]: tuple(row[1:]) for row in conn.execute("SELECT video_id, state, started_at, attempts FROM subtitles")}
    assert stored == {"a": ("running", 5001, 1), "b": ("running", 5002, 2), "c": ("running", 5003, 1), "f": ("failed", 600, 1), "r": ("running", 4000, 1)}
    conn.close()


# Claim handle after a takeover: v-1 on HOST queued at QUEUED_AT and claimed at STARTED_AT.
QUEUED_AT = 1000
STARTED_AT = 2000
TAKEOVER_AT = 8000
FINISHED_AT = 9000
# The Engine's track differs from the worker's cues, so a worker write over the Engine's row shows in track_text and cues_json.
ENGINE_TRACK = "WEBVTT\n\n00:05.000 --> 00:06.000\nEngine\n"
ENGINE_CUES = [{"start": 5.0, "end": 6.0, "text": "Engine"}]
WORKER_CUES = [{"start": 1.0, "end": 2.0, "text": "Hello"}]

# Every claim-conditional write the handle offers, each with values that change the row when the claim holds.
CLAIM_WRITES = {
    "running cues": lambda job: job.write_running_cues(WORKER_CUES, "fr"),
    "ready": lambda job: job.end_ready(WORKER_CUES, FINISHED_AT),
    "already_english": lambda job: job.end_already_english("en", FINISHED_AT),
    "failed": lambda job: job.end_failed("boom", FINISHED_AT),
    "requeue": lambda job: job.requeue(),
    "ready from instance": lambda job: job.end_ready_from_instance("WEBVTT x", WORKER_CUES, FINISHED_AT),
}


def _claimed(path: Path):  # noqa: ANN202
    """A store at `path` with v-1 queued at QUEUED_AT and claimed at STARTED_AT; the worker's connection and its handle."""
    from data.subtitles import claim_translate_job, enqueue_translate_job

    conn = _subtitles(path)
    assert tuple(enqueue_translate_job(conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    return conn, claim_translate_job(conn, "en", STARTED_AT)


def _engine_stores(path: Path, track: str, cues: list[dict], fetched_at: int) -> None:
    """The Engine state route's instance-track store, on a connection of its own as the Engine holds one."""
    from data.subtitles import connect_subtitles_db, store_ready_subtitles

    engine = connect_subtitles_db(path)
    try:
        store_ready_subtitles(engine, "v-1", HOST, "en", "instance", track, cues, fetched_at)
    finally:
        engine.close()


@pytest.mark.parametrize("write", CLAIM_WRITES.values(), ids=CLAIM_WRITES.keys())
def test_every_claim_write_after_an_instance_track_takeover_reports_the_claim_lost_and_leaves_the_row_byte_identical(tmp_path, write):
    from data.subtitles import fetch_ready_subtitles

    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        _engine_stores(path, ENGINE_TRACK, ENGINE_CUES, TAKEOVER_AT)
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == ENGINE_CUES  # control: the Engine's ready/instance row replaced the running one
        taken = _snapshot(path)
        assert write(job) is False
    finally:
        conn.close()
    assert _snapshot(path) == taken

    held_path = tmp_path / "held.db"
    conn, job = _claimed(held_path)
    held_before = _snapshot(held_path)
    try:
        assert write(job) is True  # control: the claim held, so the write matched
    finally:
        conn.close()
    assert _snapshot(held_path) != held_before  # control: with the claim held this write changes the row, so the unchanged row above is the takeover's doing


def test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp_and_the_job_columns_kept(tmp_path):
    from data.subtitles import fetch_ready_subtitles

    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        # A running job with partial cues and a detected language, set directly so the only handle call is the one under test.
        with conn:
            conn.execute("UPDATE subtitles SET cues_json = ?, detected_language = ? WHERE video_id = 'v-1' AND state = 'running'", ('[{"start":0.5,"end":0.9,"text":"partial"}]', "fr"))
        assert job.end_ready_from_instance("WEBVTT t", WORKER_CUES, FINISHED_AT) is True
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == WORKER_CUES
    finally:
        conn.close()
    reader = sqlite3.connect(path)
    reader.row_factory = sqlite3.Row
    try:
        row = dict(reader.execute("SELECT * FROM subtitles").fetchone())
    finally:
        reader.close()
    assert row == {
        "video_id": "v-1",
        "instance_domain": HOST,
        "target_language": "en",
        "state": "ready",
        "source": "instance",
        "fetched_at": FINISHED_AT,
        "track_text": "WEBVTT t",
        "cues_json": '[{"start":1.0,"end":2.0,"text":"Hello"}]',
        "queued_at": QUEUED_AT,
        "started_at": STARTED_AT,
        "finished_at": FINISHED_AT,
        "error": None,
        "detected_language": "fr",
        "attempts": 1,
    }  # one timestamp for fetched_at and finished_at, compact cues, every other job column as the running job had it


# Long enough for a migration on a tmp file; a blocking flock on a held lock never returns at all (probed: SIGALRM interrupts it).
OPENER_SECONDS = 10


@contextmanager
def _bounded() -> Iterator[None]:
    """Fail, rather than hang, when the opener blocks on the flock instead of refusing with LOCK_NB."""

    def ring(signum, frame):  # noqa: ANN001, ANN202
        pytest.fail(f"open_translate_worker_store blocked for {OPENER_SECONDS} s instead of refusing the held flock")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(OPENER_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _schema(path: Path) -> tuple[list[str], list[list[str]], list[str], str]:
    """The file's subtitles columns, index column lists, heartbeat columns and journal mode, through a plain connection."""
    conn = _plain(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        indexed = [[info[2] for info in conn.execute(f"PRAGMA index_info('{index[1]}')")] for index in conn.execute("PRAGMA index_list(subtitles)")]
        heartbeat = [row[1] for row in conn.execute("PRAGMA table_info(translate_worker_heartbeat)")]
        return columns, indexed, heartbeat, conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal(tmp_path):
    from data import subtitles as store

    path = tmp_path / "a" / "b" / "subtitles.db"
    assert not (tmp_path / "a").exists()  # control: neither directory exists, and a bare sqlite3 connect there fails (probed)

    conn = store.open_subtitles_db(path)
    try:
        assert store.fetch_translate_heartbeat(conn) is None  # the returned connection reads the migrated, empty heartbeat table
    finally:
        conn.close()

    assert path.parent.is_dir()
    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)
    assert ["state", "queued_at"] in indexed
    assert heartbeat == ["id", "beat_at", "pid"]
    assert mode == "wal"


def test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues(tmp_path):
    from data import subtitles as store

    path = tmp_path / "subtitles.db"
    _b1_file(path)
    before = _plain(path)
    try:
        # Controls: a rollback-journal B1 file whose rows B1's reader already returns.
        assert before.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert _old_cues(before) == B1_CUES
    finally:
        before.close()

    conn = store.open_subtitles_db(path)
    try:
        assert _old_cues(conn) == B1_CUES  # the returned connection reads the old cues unchanged
    finally:
        conn.close()

    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)
    assert ["state", "queued_at"] in indexed
    assert heartbeat == ["id", "beat_at", "pid"]
    assert mode == "wal"
    after = _plain(path)
    try:
        assert _old_cues(after) == B1_CUES  # the file itself still holds them
    finally:
        after.close()


def test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing(tmp_path):
    from data import subtitles as store

    lock = tmp_path / "worker.lock"
    path = tmp_path / "sub" / "subtitles.db"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    # A second open of the file, not os.dup: a dup shares held's description and so its lock (probed), and would never be refused.
    mine = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        with _bounded(), pytest.raises(BlockingIOError):
            store.open_translate_worker_store(path, mine, 1)
        assert not path.exists()  # the file was never opened
        assert not path.parent.exists()  # nor its directory created, so the flock came before the mkdir

        os.close(held)
        held = -1
        with _bounded():
            opened, counts = store.open_translate_worker_store(path, mine, 1)
        opened.close()
        assert tuple(counts) == (0, 0)  # control: with the lock free the same call on the same descriptor succeeds
        assert path.exists()  # control: so the absence above is the refusal's doing
        other = os.open(lock, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # control: the opener took the lock on mine and kept it
        finally:
            os.close(other)
    finally:
        if held != -1:
            os.close(held)
        os.close(mine)


def test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    from data import subtitles as store

    path = tmp_path / "subtitles.db"
    lock_fd = os.open(tmp_path / "worker.lock", os.O_RDONLY | os.O_CREAT)
    # Set up through the plain connect and migrate, so the claims below run as controls before the opener is reached.
    conn = _subtitles(path)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
        _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})
        _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
        # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
        _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})
        _insert(conn, "b1", HOST, B1_READY_INSTANCE)
        _, before = _snapshot(path)
        bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]
        assert len(bystanders_before) == 2  # control: the quote()d filter finds both rows, so the comparison at the end is not two empty lists

        def job(video_id: str) -> tuple:
            return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

        first = store.claim_translate_job(conn, "en", 5000)
        assert (first.video_id, first.attempts) == ("t", 1)  # control: t is running after one claim

        store.open_subtitles_db(path).close()
        assert job("t") == ("running", 1, None, None)  # the plain opener recovers nothing; the (1, 0) below shows this row was recoverable

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9000)
        opened.close()
        assert tuple(counts) == (1, 0)
        assert job("t") == ("queued", 1, None, None)  # requeued, its one claim still counted

        second = [store.claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
        assert [(row.video_id, row.attempts) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9500)
        opened.close()
        assert tuple(counts) == (2, 1)
        assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)
        assert job("o1") == ("queued", 1, None, None)
        assert job("o2") == ("queued", 1, None, None)
    finally:
        conn.close()
        os.close(lock_fd)
    _, after = _snapshot(path)
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # recovery touches only running rows


def _damage(conn: sqlite3.Connection, video_id: str, cues_json: str) -> None:
    """Overwrite a key's cues_json by hand, as only a damaged file would hold it."""
    with conn:
        conn.execute("UPDATE subtitles SET cues_json = ? WHERE video_id = ?", (cues_json, video_id))


def test_fetch_subtitle_state_gives_a_keys_state_and_raw_cues_json_or_none(tmp_path):
    from data.subtitles import claim_translate_job, enqueue_translate_job, fetch_subtitle_state

    conn = _subtitles(tmp_path / "subtitles.db")
    assert fetch_subtitle_state(conn, "v-1", HOST, "en") is None
    enqueue_translate_job(conn, "v-1", HOST, "en", 50, 1000)
    assert tuple(fetch_subtitle_state(conn, "v-1", HOST, "en")) == ("queued", None)
    job = claim_translate_job(conn, "en", 2000)
    assert job.write_running_cues([{"start": 1.0, "end": 2.0, "text": "First"}], "fr")
    _damage(conn, "v-1", "{not json")
    assert tuple(fetch_subtitle_state(conn, "v-1", HOST, "en")) == ("running", "{not json")  # unparsed
    assert fetch_subtitle_state(conn, "v-1", HOST, "fr") is None  # keyed on the language
    assert fetch_subtitle_state(conn, "v-1", "other.example", "en") is None  # keyed on the host
    conn.close()


def test_fetch_translate_heartbeat_gives_none_on_a_fresh_schema_then_the_last_beat(tmp_path):
    from data.subtitles import fetch_translate_heartbeat, write_translate_heartbeat

    conn = _subtitles(tmp_path / "subtitles.db")
    assert fetch_translate_heartbeat(conn) is None
    write_translate_heartbeat(conn, 1234, 7)
    assert fetch_translate_heartbeat(conn) == 1234
    write_translate_heartbeat(conn, 5678, 7)
    assert fetch_translate_heartbeat(conn) == 5678
    conn.close()
