"""`engine/server/db/jobs/translate-worker.py enqueue` and the queue in `engine/server/data/subtitles.py`, plan 49 phase 2: the command queues a whitelisted video under its canonical key with one stdout line and one exit code per outcome, and the store claims oldest first and recovers a crashed job once before failing it.

Enqueue (the script run under `ENGINE_PY` as `translate-worker.py --whitelist-db <tmp> --subtitles-db <tmp> enqueue --id --host`, against a tmp whitelist.db with videos, channels and instance_denylist built as test_internal_translate.py's `_whitelist` builds it):

- Requested by uuid `u-1` as host `PEER.Example.`, it exits 0 with the one line `queued ...` and leaves exactly one row: `v-1`, `peer.example`, `en`, `queued`, `whisper`, attempts 0, and a queued_at equal to fetched_at in wall-clock ms taken during the run.
- For a key already held as queued, running, ready/whisper, failed, already_english, or a B1 ready/instance row, it exits 3 with the one line `already present: <state> ...`, and every column of every row, rowid included, reads the same afterwards.
- With 49 jobs queued (plus a running and a ready row, which do not count), one more is queued with exit 0; at 50 queued the next exits 4 with `refused: queue cap ...` and the row count is unchanged.
- An unknown id, a known uuid on another host, a denied host (stored `DENIED.EXAMPLE`, active), a stored duration of 601 s under `--max-duration 600`, and an empty host each exit 5 with one `refused: ...` line and write no row, each naming its reason (`not in whitelist`, `not in whitelist`, `host denied`, `duration`, `invalid id or host`); the same store then queues the request that differs in one thing (the video's own host, the deny row lifted, a stored duration of exactly 600 s, a real host).

Queue (store functions called directly on a tmp subtitles.db opened with `connect_subtitles_db` + `ensure_subtitles_schema`):

- Three queued jobs inserted out of queued_at order are claimed oldest queued_at first, each becoming running with the given started_at and its attempts plus one; a failed and a running row with older queued_at are never claimed, and a fourth claim answers None.
- `recover_translate_jobs` requeues a running job with attempts 1 (attempts kept, no error, no finished_at) and answers (1, 0); claimed again (attempts 2) and recovered again beside two attempts-1 running jobs, it becomes failed with "worker stopped while running twice" and that finished_at while the other two are requeued, answering (2, 1); a queued and a ready row are untouched by both.

Every database is under `tmp_path`, never the repo's own.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

HOST = "peer.example"
DENIED_HOST = "denied.example"
# (video_id, video_uuid, instance_domain, duration): each uuid differs from its id, so a row keyed on the request id instead of the canonical one shows.
PEER_VIDEO = ("v-1", "u-1", HOST, 600)
SECOND_VIDEO = ("v-2", "u-2", HOST, None)
DENIED_VIDEO = ("d-1", "du-1", DENIED_HOST, None)
LONG_VIDEO = ("l-1", "lu-1", HOST, 601)
AT_MAX_VIDEO = ("m-1", "mu-1", HOST, 600)
EXIT_QUEUED = 0
EXIT_EXISTS = 3
EXIT_CAP = 4
EXIT_REFUSED = 5
# The plan's default SUBTITLE_QUEUE_CAP; the cap test runs the command without --cap.
QUEUE_CAP = 50
RECOVERY_TEXT = "worker stopped while running twice"

# A row already holding PEER_VIDEO's key in each state, every column it carries set to a value of its own.
PRESENT = {
    "queued": {"state": "queued", "source": "whisper", "fetched_at": 1111, "queued_at": 1111, "attempts": 0},
    "running": {"state": "running", "source": "whisper", "fetched_at": 1112, "queued_at": 1112, "started_at": 2112, "cues_json": '[{"start":1.0,"end":2.0,"text":"partial"}]', "detected_language": "fr", "attempts": 1},
    "ready": {"state": "ready", "source": "whisper", "fetched_at": 3113, "queued_at": 1113, "started_at": 2113, "finished_at": 3113, "cues_json": '[{"start":1.0,"end":2.0,"text":"done"}]', "detected_language": "it", "attempts": 1},
    "failed": {"state": "failed", "source": "whisper", "fetched_at": 1114, "queued_at": 1114, "started_at": 2114, "finished_at": 3114, "error": "video JSON fetch failed", "attempts": 2},
    "already_english": {"state": "already_english", "source": "whisper", "fetched_at": 1115, "queued_at": 1115, "started_at": 2115, "finished_at": 3115, "detected_language": "en", "attempts": 1},
    "B1 ready/instance": {"state": "ready", "source": "instance", "fetched_at": 1700000000000, "track_text": "WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n", "cues_json": '[{"start":1.0,"end":2.0,"text":"Hello"}]'},
}

# (refused request, the reason its line leads with, the request differing in one thing that queues, lift the deny row before it).
REFUSALS = {
    "unknown id": (["--id", "no-such-video", "--host", HOST], "refused: not in whitelist", ["--id", "u-1", "--host", HOST], False),
    "known uuid on another host": (["--id", "u-1", "--host", "other.example"], "refused: not in whitelist", ["--id", "u-1", "--host", HOST], False),
    "denied host": (["--id", "du-1", "--host", DENIED_HOST], "refused: host denied", ["--id", "du-1", "--host", DENIED_HOST], True),
    "stored duration over --max-duration": (["--id", "lu-1", "--host", HOST, "--max-duration", "600"], "refused: duration", ["--id", "mu-1", "--host", HOST, "--max-duration", "600"], False),
    # normalize_host("") is None, and fetch_video_row with a None host matches the id on any host, so the command refuses it before the lookup; the reason is the plan's command_enqueue text.
    "empty host": (["--id", "u-1", "--host", ""], "refused: invalid id or host", ["--id", "u-1", "--host", HOST], False),
}
# The canonical key each control request queues under.
CONTROL_KEYS = {"unknown id": ("v-1", HOST), "known uuid on another host": ("v-1", HOST), "denied host": ("d-1", DENIED_HOST), "stored duration over --max-duration": ("m-1", HOST), "empty host": ("v-1", HOST)}


def _whitelist(path: Path) -> None:
    """A whitelist.db built as test_internal_translate.py's `_whitelist`, holding every video above with its stored duration and an active deny row for DENIED_HOST stored uppercase."""
    from data.moderation import ensure_moderation_schema

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    for video_id, uuid, host, duration in (PEER_VIDEO, SECOND_VIDEO, DENIED_VIDEO, LONG_VIDEO, AT_MAX_VIDEO):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, title, duration, error_count) VALUES (?, ?, ?, ?, ?, 0)", (video_id, uuid, host, f"title:{video_id}", duration))
    conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 1, 0, 0)", (DENIED_HOST.upper(),))
    conn.commit()
    conn.close()


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


def _rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return [tuple(row) for row in conn.execute("SELECT video_id, instance_domain, target_language, state, source, attempts FROM subtitles ORDER BY rowid")]
    finally:
        conn.close()


@pytest.fixture
def dbs(tmp_path) -> dict[str, Path]:
    paths = {"whitelist": tmp_path / "whitelist.db", "subtitles": tmp_path / "subtitles.db"}
    _whitelist(paths["whitelist"])
    _subtitles(paths["subtitles"]).close()
    return paths


def _enqueue(dbs: dict[str, Path], args: list[str]) -> tuple[int, list[str], str]:
    """Run the enqueue command as an operator does; its exit code, its stdout lines and its stderr."""
    assert ENGINE_PY.exists(), f"the Engine interpreter is missing at {ENGINE_PY}"
    result = subprocess.run([str(ENGINE_PY), str(WORKER), "--whitelist-db", str(dbs["whitelist"]), "--subtitles-db", str(dbs["subtitles"]), "enqueue", *args], capture_output=True, text=True, timeout=60, cwd=dbs["whitelist"].parent)
    return result.returncode, result.stdout.splitlines(), result.stderr


def _leads(lines: list[str], prefix: str) -> bool:
    """One stdout line, which is `prefix` or `prefix` followed by a space and detail."""
    return len(lines) == 1 and (lines[0] == prefix or lines[0].startswith(prefix + " "))


def test_enqueue_by_uuid_and_unnormalised_host_queues_one_whisper_row_under_the_canonical_key(dbs):
    before_ms = time.time_ns() // 1_000_000
    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", "PEER.Example."])
    after_ms = time.time_ns() // 1_000_000

    assert returncode == EXIT_QUEUED, (returncode, lines, err)  # C1
    assert _leads(lines, "queued"), lines  # C1
    # Keyed on the row's canonical `v-1` and `peer.example`, not the requested uuid or host.
    assert _rows(dbs["subtitles"]) == [("v-1", HOST, "en", "queued", "whisper", 0)]  # C1
    conn = sqlite3.connect(dbs["subtitles"])
    queued_at, fetched_at = conn.execute("SELECT queued_at, fetched_at FROM subtitles").fetchone()
    conn.close()
    # Claim orders on queued_at, so it is the enqueue's own wall-clock ms (data.time.now_ms), as fetched_at is.
    assert isinstance(queued_at, int) and before_ms <= queued_at <= after_ms and fetched_at == queued_at, (before_ms, queued_at, fetched_at, after_ms)  # C1


@pytest.mark.parametrize("present", PRESENT.values(), ids=PRESENT.keys())
def test_a_key_already_present_in_any_state_is_reported_with_that_state_and_left_untouched(dbs, present):
    conn = sqlite3.connect(dbs["subtitles"])
    _insert(conn, "q-0", "other.example", {"state": "queued", "source": "whisper", "fetched_at": 1, "queued_at": 1, "attempts": 0})
    _insert(conn, "v-1", HOST, present)
    conn.close()
    before = _snapshot(dbs["subtitles"])

    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", "PEER.Example."])

    assert returncode == EXIT_EXISTS, (returncode, lines, err)  # C1
    assert _leads(lines, f"already present: {present['state']}"), lines  # C1
    assert _snapshot(dbs["subtitles"]) == before  # C1: no column of any row rewritten, no row added


def test_enqueue_at_the_queue_cap_is_refused_and_writes_nothing(dbs):
    conn = sqlite3.connect(dbs["subtitles"])
    for n in range(QUEUE_CAP - 1):
        _insert(conn, f"q-{n}", "other.example", {"state": "queued", "source": "whisper", "fetched_at": n, "queued_at": n, "attempts": 0})
    # Rows in other states are not queued jobs and do not count toward the cap.
    _insert(conn, "r-1", "other.example", PRESENT["running"])
    _insert(conn, "b-1", "other.example", PRESENT["B1 ready/instance"])
    conn.close()

    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", HOST])
    assert returncode == EXIT_QUEUED, (returncode, lines, err)  # C1: 49 queued is under the cap
    assert _leads(lines, "queued"), lines  # C1
    rows = _rows(dbs["subtitles"])
    assert len(rows) == QUEUE_CAP + 2 and sum(row[3] == "queued" for row in rows) == QUEUE_CAP, rows  # control: the queue now holds exactly the cap

    returncode, lines, err = _enqueue(dbs, ["--id", "u-2", "--host", HOST])

    assert returncode == EXIT_CAP, (returncode, lines, err)  # C1
    assert _leads(lines, "refused: queue cap"), lines  # C1
    assert _rows(dbs["subtitles"]) == rows  # C1: row count unchanged, no v-2 row


@pytest.mark.parametrize("case", REFUSALS)
def test_a_refused_video_exits_5_naming_its_reason_and_writes_no_row(dbs, case):
    refused, reason, control, lift_deny = REFUSALS[case]
    returncode, lines, err = _enqueue(dbs, refused)

    assert returncode == EXIT_REFUSED, (returncode, lines, err)  # C1
    assert _leads(lines, reason), lines  # C1
    assert _rows(dbs["subtitles"]) == []  # C1: no row written

    # Control: the request differing in that one thing queues, so the refusal above was its reason's doing.
    if lift_deny:
        conn = sqlite3.connect(dbs["whitelist"])
        conn.execute("UPDATE instance_denylist SET is_active = 0")
        conn.commit()
        conn.close()
    returncode, lines, err = _enqueue(dbs, control)
    assert returncode == EXIT_QUEUED, (returncode, lines, err)
    assert _rows(dbs["subtitles"]) == [(*CONTROL_KEYS[case], "en", "queued", "whisper", 0)]


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

    assert [None if job is None else (job["video_id"], job["instance_domain"], job["started_at"], job["attempts"]) for job in claimed] == [("a", HOST, 5001, 1), ("b", HOST, 5002, 2), ("c", HOST, 5003, 1), None]  # C2
    stored = {row[0]: tuple(row[1:]) for row in conn.execute("SELECT video_id, state, started_at, attempts FROM subtitles")}
    assert stored == {"a": ("running", 5001, 1), "b": ("running", 5002, 2), "c": ("running", 5003, 1), "f": ("failed", 600, 1), "r": ("running", 4000, 1)}  # C2
    conn.close()


def test_recovery_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    from data.subtitles import claim_translate_job, recover_translate_jobs

    path = tmp_path / "subtitles.db"
    conn = _subtitles(path)
    _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
    _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})
    _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
    # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
    _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})
    _insert(conn, "b1", HOST, PRESENT["B1 ready/instance"])
    _, before = _snapshot(path)
    bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]

    def job(video_id: str) -> tuple:
        return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

    first = claim_translate_job(conn, "en", 5000)
    assert (first["video_id"], first["attempts"]) == ("t", 1)  # control: t is running after one claim

    assert tuple(recover_translate_jobs(conn, 9000)) == (1, 0)  # C2
    assert job("t") == ("queued", 1, None, None)  # C2: requeued, its one claim still counted

    second = [claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
    assert [(row["video_id"], row["attempts"]) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

    assert tuple(recover_translate_jobs(conn, 9500)) == (2, 1)  # C2
    assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)  # C2
    assert job("o1") == ("queued", 1, None, None)  # C2
    assert job("o2") == ("queued", 1, None, None)  # C2
    conn.close()
    _, after = _snapshot(path)
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # C2: recovery touches only running rows
