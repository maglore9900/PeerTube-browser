"""`engine/server/db/jobs/translate-worker.py`: `enqueue` queues a whitelisted video under its canonical key with one stdout line and one exit code per outcome; `run_job` refuses a claimed job at every AC5 bound with that bound's error text and no remote request after the refusal, and rewrites a transcribed job's running cues after each speech chunk until exactly one end state; a locked or unopenable whitelist.db at claim requeues the job unspent and `serve` waits out a back-off, staying live, before reclaiming it; `run` is one worker at a time under an flock, beating its heartbeat row every 5 s while idle and not beating once its main loop has stalled.

Enqueue (the script run under `ENGINE_PY` as `translate-worker.py --whitelist-db <tmp> --subtitles-db <tmp> enqueue --id --host`, against a tmp whitelist.db with videos, channels and instance_denylist built as test_internal_translate.py's `_whitelist` builds it):

- Requested by uuid `u-1` as host `PEER.Example.`, it exits 0 with the one line `queued ...` and leaves exactly one row: `v-1`, `peer.example`, `en`, `queued`, `whisper`, attempts 0, and a queued_at equal to fetched_at in wall-clock ms taken during the run.
- For a key already held as queued, running, ready/whisper, failed, already_english, or a B1 ready/instance row, it exits 3 with the one line `already present: <state> ...`, and every column of every row, rowid included, reads the same afterwards.
- With 49 jobs queued (plus a running and a ready row, which do not count), one more is queued with exit 0; at 50 queued the next exits 4 with `refused: queue cap ...` and the row count is unchanged.
- An unknown id, a known uuid on another host, a denied host (stored `DENIED.EXAMPLE`, active), a stored duration of 601 s under `--max-duration 600`, and an empty host each exit 5 with one `refused: ...` line and write no row, each naming its reason (`not in whitelist`, `not in whitelist`, `host denied`, `duration`, `invalid id or host`); the same store then queues the request that differs in one thing (the video's own host, the deny row lifted, a stored duration of exactly 600 s, a real host).

Job pipeline: `run_job(conn, job, args, runner, stop, progress)` called in-process on a job enqueued and claimed with the store's own functions (queued_at 1000, started_at 2000), over a tmp whitelist.db (v-1/u-1 on peer.example; d-1 on denied.example, actively denied, stored uppercase; both with NULL stored durations) and a tmp subtitles.db. The instance and the media host are two scripted https hosts behind one dispatching opener on the adapter's single patch point, `data.source_fetch.build_opener`, which hands each URL to the host serving it; each records every URL opened, in order, and urllib's real redirect handling runs. ffmpeg is real and decodes a 4 s 16 kHz WAV clip generated with `ffmpeg -f lavfi` (sine in seconds 0 and 2, exact silence in seconds 1 and 3); the test fails if ffmpeg is missing. Whisper and VAD are a stub runner: speech is any non-zero sample in the window, and transcribe answers two segments out of order, (0.6, 0.9) and (0.1234, 0.5678), with language `fr` unless told otherwise. Args: max_duration 5, max_bytes the clip's size, max_chunk_seconds 1. The video JSON declares duration 5 and one file.

Bounds: each case ends the row `failed` with its text (exactly, or that text followed by `: ` and detail), and the instance and media host saw exactly the URLs listed, so nothing was requested after the refusing step:

- a key no longer in whitelist.db (`not in whitelist`) and a denied host (`host denied`): no URL at all;
- JSON with no duration (`video duration unknown`), JSON duration 6 (`duration 6s over 5s`), and a single file that is http, an IPv4 or IPv6 literal, a decimal, dotted-numeric or hex host, a single-label host, an explicit port, userinfo, or `hasAudio: false` (`no usable https media file`), and a video JSON redirected off peer.example (`video JSON fetch failed: redirect refused: ...`, the target never requested though it serves a valid JSON): the caption list and the video JSON only;
- a Content-Length one byte over max_bytes (`media over <max_bytes> bytes`, with the body never read), the same body streamed with no length (same text), a JSON duration of 3 under max_duration 3 with 4 s of audio decoded (`audio longer than 3s`), and a redirect off the media host (`media download failed`, the target never requested): those two and the media URL only.

A video JSON redirect that stays on peer.example, and a media redirect that stays on the media host, are each followed and the job ends ready. `pick_media_url` takes a file from `streamingPlaylists[].files[]` over any in `files[]`, sized or not, and `files[]` only when no HLS file is usable; within the chosen group it takes the smallest declared size, sorts a file with no size after any sized one, and still picks it when it is the only file.

Outcomes:

- Transcribed: the row read at each transcribe call and at each silent window is, in order, running with no cues; running with chunk 1's two cues (silent second); running with chunk 1's cues again (third second, transcribed); running with chunks 1 and 3's four cues (silent fourth second). So it grew by exactly each speech chunk's cues, each transcribe got one second of PCM, and the silent windows got no transcribe call. Chunk 3's times are the segment times plus 2.0 s, rounded to ms (2.123, 2.568, 2.6, 2.9). The row ends ready/whisper with all four cues sorted by start and a finished_at taken during the run.
- `en` detected: already_english, cues_json NULL, and no write ever set cues_json to a value (the trigger that would show one is shown recording a write afterwards).
- No speech anywhere: failed `no speech detected`, VAD asked about all four windows, transcribe never called.
- Media ffmpeg decodes to nothing (the clip as a PCM .mov with its moov atom at the end, which ffmpeg reads from stdin as zero samples and still exits 0): failed `no audio decoded`, VAD and transcribe never called; the same .mov with +faststart ends ready/whisper.
- CUDA out of memory raised by transcribe: failed with that text, unload called exactly once.
- The instance holds an English track: ready/instance with the parsed cues and track text, finished_at taken during the run, the caption list and the track fetched, and nothing fetched from the media host.
- B1's route stores ready/instance during the first transcribe: every column of the row reads the same afterwards, and the worker stops that job instead of transcribing the third second.
- stop set during the first transcribe: queued again with attempts back to 0 and queued_at still 1000.

Whitelist at claim: `run_job` (through `Rig.run`, which hands back its bool) on a claimed v-1 whose whitelist.db is broken before the lookup.

- Transient (the file deleted, or held under `BEGIN EXCLUSIVE` past the lookup's 30 s busy timeout): queued with attempts 0, queued_at 1000, no error and no finished_at; neither host requested; exactly one WARNING naming `[translate-worker]`, the key and the error text, nothing at ERROR; `run_job` returns True.
- Any other OperationalError (videos without video_uuid, a zero-byte file): failed with `OperationalError: <text>`, one ERROR record carrying the exception, no WARNING; `run_job` returns False.

Back-off: `serve` run in-process on a daemon thread over the rig's connection with `POLL_SECONDS` 0.05 and `TRANSIENT_BACKOFF_SECONDS` lowered on the loaded module, and `resolve_video` wrapped by a recorder of each lookup's time and key.

- After a whitelist.db requeue (injected `database is locked` or a deleted file), the next lookup comes no sooner than the back-off after the first and is again v-1, never d-1 queued behind it; the row stays queued with attempts 0 and queued_at 1000.
- During the back-off `progress["at"]` is never more than two slices old, so the heartbeat does not read the wait as a stall; a stop set during it ends `serve` within 0.5 s without another lookup.

Service: the script run under `ENGINE_PY` as `translate-worker.py --whitelist-db <tmp> --subtitles-db <tmp> run --lock <tmp> --log <tmp>` with an empty queue, so no job is claimed and the model is never loaded; and the same `run` started through a `-c` driver that loads the script, lowers its `STALL_SECONDS` to 4 s and calls its `main()`, so the worker's own main loop can be stalled within the test.

- Held lock: while the test process holds an flock on the lock file, `run` exits 6 and its log file names the lock's path. With no subtitles.db beforehand, none is created; with a B1-shaped one, it is byte-identical afterwards, still has exactly B1's eight columns and no heartbeat table, and no `-wal`, `-shm` or `-journal` file appears beside it.
- Heartbeat: on an idle queue, `run` writes a `translate_worker_heartbeat` row whose pid is the subprocess's own; within 14 s of the first beat the row shows three distinct `beat_at` values, each a wall-clock ms stamp taken during the run, consecutive ones 4.5 to 6.5 s apart. The worker holds the lock while it runs; after SIGTERM it exits 0 within the unit's 60 s, and the lock is then free to a fresh non-blocking flock.
- Stall: a driven `run` beats while idle. Once its main loop claims a queued job and blocks in that job's whitelist lookup, which the test holds on an EXCLUSIVE lock, the heartbeat row keeps the same `beat_at` over 11 s, two due 5 s ticks, while the worker is alive and the job is still `running`. After the lock is released the job ends `failed` with `not in whitelist`, and within 8 s the row gets a new `beat_at`, no earlier than the release, carrying the subprocess's pid.

Every database, lock and log path the tests hand the worker is under `tmp_path`, never the repo's own.
"""
from __future__ import annotations

import array
import fcntl
import importlib
import importlib.util
import json
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from argparse import Namespace
from http.client import HTTPMessage
from pathlib import Path
from types import ModuleType
from urllib.request import HTTPHandler, HTTPSHandler, Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from data.moderation import ensure_moderation_schema  # noqa: E402
from data.subtitles import connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema  # noqa: E402

HOST = "peer.example"
DENIED_HOST = "denied.example"

# B1's CREATE TABLE as delivered (subtitles.py before the translate-job columns), so a refused run is shown to leave the shape the Engine wrote in production untouched.
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
B1_ROW = ("v-1", "peer.example", "en", "ready", "instance", 1700000000000, "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello\n", '[{"start":1.0,"end":2.5,"text":"Hello"}]')

# Enqueue: (video_id, video_uuid, instance_domain, duration); each uuid differs from its id, so a row keyed on the request id instead of the canonical one shows.
ENQUEUE_VIDEOS = [
    ("v-1", "u-1", HOST, 600),
    ("v-2", "u-2", HOST, None),
    ("d-1", "du-1", DENIED_HOST, None),
    ("l-1", "lu-1", HOST, 601),
    ("m-1", "mu-1", HOST, 600),
]
EXIT_QUEUED = 0
EXIT_EXISTS = 3
EXIT_CAP = 4
EXIT_REFUSED = 5
# The default SUBTITLE_QUEUE_CAP; the cap test runs the command without --cap.
QUEUE_CAP = 50

# A row already holding v-1's key in each state, every column it carries set to a value of its own.
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
    # normalize_host("") is None, and fetch_video_row with a None host matches the id on any host, so the command refuses it before the lookup; the reason is command_enqueue's text.
    "empty host": (["--id", "u-1", "--host", ""], "refused: invalid id or host", ["--id", "u-1", "--host", HOST], False),
}
# The canonical key each control request queues under.
CONTROL_KEYS = {"unknown id": ("v-1", HOST), "known uuid on another host": ("v-1", HOST), "denied host": ("d-1", DENIED_HOST), "stored duration over --max-duration": ("m-1", HOST), "empty host": ("v-1", HOST)}

# Job pipeline: the uuid differs from the id, so an instance URL built from the id instead of the uuid shows; NULL stored durations, so only the video JSON's duration bounds a job.
JOB_VIDEOS = [("v-1", "u-1", HOST, None), ("d-1", "du-1", DENIED_HOST, None)]
CAPTIONS_URL = f"https://{HOST}/api/v1/videos/u-1/captions"
VIDEO_URL = f"https://{HOST}/api/v1/videos/u-1"
TRACK_PATH = "/lazy-static/video-captions/en.vtt"
TRACK_URL = f"https://{HOST}{TRACK_PATH}"
INSTANCE_THEN_JSON = [CAPTIONS_URL, VIDEO_URL]
MEDIA_HOST = "media.example"
MEDIA_URL = f"https://{MEDIA_HOST}/static/web-videos/v-1-240.wav"
SAME_HOST_TARGET = f"https://{MEDIA_HOST}/static/streaming-playlists/v-1-240.wav"
OFF_HOST_TARGET = "https://cdn.example/static/web-videos/v-1-240.wav"
OFF_DOMAIN_VIDEO_URL = "https://cdn.example/api/v1/videos/u-1"
SAME_DOMAIN_VIDEO_URL = f"https://{HOST}/api/v1/videos/u-1?moved=1"
MEDIA_FILE = {"fileUrl": MEDIA_URL, "size": 4096}
SAMPLE_RATE = 16_000
CHUNK = 65_536
MAX_DURATION = 5
QUEUED_AT = 1000
STARTED_AT = 2000
# Sine in seconds 0 and 2, silence in 1 and 3. WAV, not a lossy codec: probed through the worker's FFMPEG_ARGS over stdin it decodes to exactly 64000 samples, seconds 1 and 3 all zero, so one-second windows line up with the speech.
CLIP_SOURCE = "aevalsrc=exprs='0.5*sin(2*PI*440*t)*(lt(t,1)+gte(t,2)*lt(t,3))':s=16000:d=4"
EN_LISTING = json.dumps({"total": 1, "data": [{"language": {"id": "en", "label": "English"}, "captionPath": TRACK_PATH}]}).encode("utf-8")
TRACK = "WEBVTT\n\n00:03.000 --> 00:04.000\n<i>World</i>\n\n00:01.000 --> 00:02.500\nHello\n"
# TRACK as B1's parser gives it (test_internal_translate.py): sorted by start, markup stripped.
CUES = [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3.0, "end": 4.0, "text": "World"}]
# The stub's segments for its nth transcribe call, out of start order, with times not on a ms boundary.
CHUNK_1 = [{"start": 0.123, "end": 0.568, "text": "call 1 a"}, {"start": 0.6, "end": 0.9, "text": "call 1 b"}]
# The second transcribe call is the clip's third second, so offset 2.0 s.
CHUNK_3 = [{"start": 2.123, "end": 2.568, "text": "call 2 a"}, {"start": 2.6, "end": 2.9, "text": "call 2 b"}]
OOM = "CUDA failed: out of memory"

# Whitelist at claim: (how whitelist.db is broken, the OperationalError text it raises); texts probed through run_job on this rig. The held lock outlasts the lookup's 30 s busy timeout.
REQUEUED = {
    "missing file": ("delete", "unable to open database file"),
    "held EXCLUSIVE lock": ("hold", "database is locked"),
}
FAILED = {
    "videos without video_uuid": ("drop column", "no such column: v.video_uuid"),
    "zero-byte file": ("truncate", "no such table: videos"),
}
LOCKED = "database is locked"

# Serve back-off: POLL_SECONDS on the loaded module, so a stop or a progress refresh is due every slice.
SLICE_SECONDS = 0.05
# TRANSIENT_BACKOFF_SECONDS on the loaded module for the gap test; without a back-off serve was probed reclaiming about 0.1 ms after each requeue.
GAP_BACKOFF_SECONDS = 1.0
# TRANSIENT_BACKOFF_SECONDS on the loaded module for the liveness test, long enough that sampling plus the stop bound fit inside the second back-off.
LIVE_BACKOFF_SECONDS = 1.5
# Ten of the longer back-off and still under the 30 s default, so a serve waiting the default rather than the module's value misses it.
LOOKUP_WAIT_SECONDS = 10 * LIVE_BACKOFF_SECONDS
SAMPLE_SECONDS = 0.25
SAMPLE_EVERY_SECONDS = 0.01
# Two slices: a once-per-slice refresh was probed peaking at 0.050 s; one refreshing every other slice or less would exceed it.
FRESH_SECONDS = 2 * SLICE_SECONDS
# Probed at 0.041 s with a 0.05 s slice; a wait that ignored the stop would run out the remaining ~1.2 s.
STOP_WITHIN_SECONDS = 0.5

# Service: the unit's TimeoutStopSec.
STOP_WINDOW_SECONDS = 60
# A beater on a 5 s wait was probed writing exactly 5000 ms apart; the margin is for a loaded machine, and still refuses a 4 s or a 7 s cadence.
BEAT_GAP_MS = (4500, 6500)
# Three beats at a 5 s cadence span 10 s; 14 s is that plus slack.
BEAT_WINDOW_SECONDS = 14.0
# Interpreter start, imports and the schema upgrade before the first beat; probed at about 1 s.
FIRST_BEAT_SECONDS = 30.0
# Loads the worker as a module, lowers its STALL_SECONDS to argv[2] and runs its main() on the rest of argv, so a stall shows within the test instead of after 600 s; every function it runs is the script's own.
STALL_DRIVER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("translate_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
worker.STALL_SECONDS = float(sys.argv[2])
sys.argv = [sys.argv[1], *sys.argv[3:]]
worker.main()
"""
# Twice the idle loop's 2 s poll, so an idle worker never trips it, and under one 5 s tick, so at most one beat follows the claim.
TEST_STALL_SECONDS = 4.0
# Two 5 s ticks, so an unguarded beater writes at least once in it; with the claim wait and TEST_STALL_SECONDS the whitelist lock is held about 18 s, inside the lookup's 30 s busy timeout.
STALLED_WINDOW_SECONDS = 11.0
# One 5 s tick after the main loop moves on, plus slack.
RESUME_SECONDS = 8.0
# Not in the test's whitelist.db, so the job fails at its lookup and no instance is contacted.
STALL_KEY = ("v-stall", "peer.example")


def _whitelist(path: Path, videos: list[tuple[str, str, str, int | None]], deny: bool) -> None:
    """A whitelist.db built as test_internal_translate.py's `_whitelist`: videos, channels and instance_denylist, each (video_id, video_uuid, instance_domain, duration) in `videos`, and with `deny` an active deny row for DENIED_HOST stored uppercase; left in its default rollback journal, so an EXCLUSIVE lock blocks readers."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    for video_id, uuid, host, duration in videos:
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, title, duration, error_count) VALUES (?, ?, ?, ?, ?, 0)", (video_id, uuid, host, f"title:{video_id}", duration))
    if deny:
        conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 1, 0, 0)", (DENIED_HOST.upper(),))
    conn.commit()
    conn.close()


def _b1_file(path: Path) -> None:
    """A subtitles.db exactly as B1 left it: B1's table, one ready/instance row, the default rollback journal."""
    conn = sqlite3.connect(path)
    conn.execute(B1_CREATE)
    conn.execute("INSERT INTO subtitles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", B1_ROW)
    conn.commit()
    conn.close()


def _worker() -> ModuleType:
    """The worker script as a module; its hyphenated name rules out a plain import."""
    spec = importlib.util.spec_from_file_location("translate_worker", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


# Enqueue helpers.


def _subtitles(path: Path) -> sqlite3.Connection:
    """The subtitles store as the Engine opens it."""
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
    _whitelist(paths["whitelist"], ENQUEUE_VIDEOS, deny=True)
    _subtitles(paths["subtitles"]).close()
    return paths


def _enqueue(dbs: dict[str, Path], args: list[str]) -> tuple[int, list[str], str]:
    """Run the enqueue command as an operator does; its exit code, its stdout lines and its stderr."""
    assert ENGINE_PY.exists(), f"the Engine interpreter is missing at {ENGINE_PY}"
    result = subprocess.run([str(ENGINE_PY), str(WORKER), "--whitelist-db", str(dbs["whitelist"]), "--subtitles-db", str(dbs["subtitles"]), "enqueue", *args], capture_output=True, text=True, timeout=60, cwd=dbs["whitelist"].parent)
    return result.returncode, result.stdout.splitlines(), result.stderr


def _one_line_leads(lines: list[str], prefix: str) -> bool:
    """One stdout line, which is `prefix` or `prefix` followed by a space and detail."""
    return len(lines) == 1 and (lines[0] == prefix or lines[0].startswith(prefix + " "))


# Job pipeline helpers.


def _video(duration: object = MAX_DURATION, files: list | None = None) -> bytes:
    """The instance's video JSON; duration None leaves the key out."""
    video: dict = {"uuid": "u-1", "files": [MEDIA_FILE] if files is None else files, "streamingPlaylists": []}
    if duration is not None:
        video["duration"] = duration
    return json.dumps(video).encode("utf-8")


# Each a file the instance lists alone; a worker that accepted it would open its URL through the media host, which the recorder would show.
REFUSED_FILES = {
    "http": {"fileUrl": "http://media.example/static/web-videos/v-1-240.wav", "size": 4096},
    "IPv4 literal": {"fileUrl": "https://203.0.113.7/static/web-videos/v-1-240.wav", "size": 4096},
    "IPv6 literal": {"fileUrl": "https://[2001:db8::7]/static/web-videos/v-1-240.wav", "size": 4096},
    "decimal host": {"fileUrl": "https://2130706433/static/web-videos/v-1-240.wav", "size": 4096},
    "dotted numeric host": {"fileUrl": "https://127.1/static/web-videos/v-1-240.wav", "size": 4096},
    "hex host": {"fileUrl": "https://0x7f.0x1/static/web-videos/v-1-240.wav", "size": 4096},
    "single-label host": {"fileUrl": "https://media/static/web-videos/v-1-240.wav", "size": 4096},
    "explicit port": {"fileUrl": "https://media.example:8443/static/web-videos/v-1-240.wav", "size": 4096},
    "userinfo": {"fileUrl": "https://user@media.example/static/web-videos/v-1-240.wav", "size": 4096},
    "hasAudio false": {"fileUrl": MEDIA_URL, "size": 4096, "hasAudio": False},
}

# Each bound: the job's key, the video JSON, how the media host answers, max_bytes below the clip's size, max_duration, the error text, and every URL each host saw (instance defaults to caption list then video JSON).
BOUNDS = {
    "not in whitelist at claim": {"key": ("gone-1", HOST), "error": "not in whitelist", "instance": [], "media": []},
    "host denied at claim": {"key": ("d-1", DENIED_HOST), "error": "host denied", "instance": [], "media": []},
    "JSON duration unknown": {"video": _video(duration=None), "error": "video duration unknown", "media": []},
    "JSON duration over the cap": {"video": _video(duration=MAX_DURATION + 1), "error": "duration 6s over 5s", "media": []},
    **{f"media URL {name}": {"video": _video(files=[file]), "error": "no usable https media file", "media": []} for name, file in REFUSED_FILES.items()},
    "video JSON redirect off the instance domain": {"video_redirect": OFF_DOMAIN_VIDEO_URL, "error": "video JSON fetch failed", "media": []},
    "media Content-Length over max_bytes": {"route": "declared", "under_clip": 1, "error": "media over {max_bytes} bytes", "media": [MEDIA_URL], "unread": True},
    "media streamed past max_bytes": {"route": "streamed", "under_clip": 1, "error": "media over {max_bytes} bytes", "media": [MEDIA_URL]},
    # The JSON's 3 s passes its own check at the cap; the 4 s actually decoded does not.
    "decoded audio past max_duration": {"video": _video(duration=3), "max_duration": 3, "error": "audio longer than 3s", "media": [MEDIA_URL]},
    "media redirect off the media host": {"route": "off-host redirect", "error": "media download failed", "media": [MEDIA_URL]},
}

# (video JSON, the URL picked); every URL is acceptable, so only the group (HLS first) and size decide.
PICKS = {
    "an HLS file over a smaller files[] one": ({"files": [{"fileUrl": "https://media.example/a-720.mp4", "size": 300}, {"fileUrl": "https://media.example/b-240.mp4", "size": 100}], "streamingPlaylists": [{"files": [{"fileUrl": "https://media.example/c-480.mp4", "size": 200}]}]}, "https://media.example/c-480.mp4"),
    "an unsized HLS file over a sized files[] one": ({"files": [{"fileUrl": "https://media.example/b-240.mp4", "size": 100}], "streamingPlaylists": [{"files": [{"fileUrl": "https://media.example/unsized-hls.mp4"}]}]}, "https://media.example/unsized-hls.mp4"),
    "smallest in files[] when no HLS file is usable": ({"files": [{"fileUrl": "https://media.example/a-720.mp4", "size": 300}, {"fileUrl": "https://media.example/b-240.mp4", "size": 100}], "streamingPlaylists": [{"files": [{"fileUrl": "https://media.example/c-480.mp4", "size": 50, "hasAudio": False}]}]}, "https://media.example/b-240.mp4"),
    "smallest in streamingPlaylists[].files[]": ({"files": [{"fileUrl": "https://media.example/a-720.mp4", "size": 300}], "streamingPlaylists": [{"files": [{"fileUrl": "https://media.example/c-480.mp4", "size": 200}, {"fileUrl": "https://media.example/d-144.mp4", "size": 100}]}]}, "https://media.example/d-144.mp4"),
    "no size sorts after a known one, however large": ({"files": [{"fileUrl": "https://media.example/unsized.mp4"}, {"fileUrl": "https://media.example/huge.mp4", "size": 5_000_000_000}], "streamingPlaylists": []}, "https://media.example/huge.mp4"),
    "no size alone is still picked": ({"files": [{"fileUrl": "https://media.example/unsized.mp4"}], "streamingPlaylists": []}, "https://media.example/unsized.mp4"),
}


class Response:
    """One scripted response as urllib's http(s) open step hands it on: status, headers, and a body read one CHUNK at a time, counting reads."""

    def __init__(self, url: str, status: int, headers: dict[str, str], body: bytes) -> None:
        self.url = url
        self.code = self.status = status
        self.msg = "Scripted"
        self.headers = HTTPMessage()
        for name, value in headers.items():
            self.headers[name] = value
        self.chunks = [body[i:i + CHUNK] for i in range(0, len(body), CHUNK)]
        self.reads = 0

    def info(self) -> HTTPMessage:
        return self.headers

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def read1(self, size: int = -1) -> bytes:
        self.reads += 1
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if size is not None and 0 <= size < len(chunk):
            self.chunks.insert(0, chunk[size:])
            chunk = chunk[:size]
        return chunk

    def read(self, size: int | None = -1) -> bytes:
        out = b""
        while size is None or size < 0 or len(out) < size:
            chunk = self.read1(-1 if size is None or size < 0 else size - len(out))
            if not chunk:
                break
            out += chunk
        return out

    def close(self) -> None:
        pass

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class ScriptedHost:
    """A scripted host behind a `build_opener`, in test_internal_translate.py's ScriptedInstance pattern: answers each URL from its routes (404 for any other) and records every URL opened, in order."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
        self.opened: list[str] = []
        self.responses: list[Response] = []

    def serve(self, url: str, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b"") -> None:
        self.routes[url] = (status, headers or {}, body)

    def open(self, req: Request) -> Response:
        self.opened.append(req.full_url)
        status, headers, body = self.routes.get(req.full_url, (404, {}, b""))
        response = Response(req.full_url, status, headers, body)
        self.responses.append(response)
        return response


def _socket_handler(handler: object) -> bool:
    """Whether a handler build_opener was given opens connections itself, so it must give way to the scripted hosts."""
    kind = handler if isinstance(handler, type) else type(handler)
    return issubclass(kind, (HTTPHandler, HTTPSHandler))


def _dispatching_opener(instance: ScriptedHost, media: ScriptedHost):  # noqa: ANN202
    """One build_opener for both scripted hosts, as the adapter's patch point takes it: a URL goes to the host that serves it, else by request host (peer.example to the instance, any other to the media host), so a followed cdn.example redirect shows in the opened list of the host that served it; the adapter's own handlers go into a real urllib opener."""

    def build_opener(*handlers: object) -> urllib.request.OpenerDirector:
        def owner(req: Request) -> ScriptedHost:
            return next((host for host in (instance, media) if req.full_url in host.routes), instance if req.host == HOST else media)

        class DispatchHTTPS(HTTPSHandler):
            def https_open(self, req: Request) -> Response:
                return owner(req).open(req)

        class DispatchHTTP(HTTPHandler):
            def http_open(self, req: Request) -> Response:
                return owner(req).open(req)

        return urllib.request.build_opener(DispatchHTTPS(), DispatchHTTP(), *[handler for handler in handlers if not _socket_handler(handler)])

    return build_opener


def _error_leads(error: str | None, text: str) -> bool:
    """The error is text, or text followed by `: ` and detail."""
    return isinstance(error, str) and (error == text or error.startswith(text + ": "))


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> bytes:
    if shutil.which("ffmpeg") is None:
        pytest.fail("ffmpeg is not on PATH; the translate worker decodes media with it")
    path = tmp_path_factory.mktemp("clip") / "clip.wav"
    made = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", CLIP_SOURCE, "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(path)], capture_output=True, text=True, timeout=60)
    assert made.returncode == 0, made.stderr
    return path.read_bytes()


@pytest.fixture(scope="module")
def mov_clips(tmp_path_factory) -> dict[bool, bytes]:
    """The clip as a 48 kHz stereo PCM .mov (about 770 KB), keyed by faststart: without it ffmpeg writes the moov atom after the media data, as some PeerTube web-video files are. A small AAC file does not reproduce it: ffmpeg buffers all of a 13 KB pipe input and finds the moov anyway."""
    made_dir = tmp_path_factory.mktemp("mov")
    clips = {}
    for faststart in (False, True):
        path = made_dir / f"clip-{faststart}.mov"
        flags = ["-movflags", "+faststart"] if faststart else []
        made = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", CLIP_SOURCE, "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", *flags, str(path)], capture_output=True, text=True, timeout=60)
        assert made.returncode == 0, made.stderr
        body = path.read_bytes()
        assert (body.index(b"moov") < body.index(b"mdat")) == faststart  # control: the index sits where the case says
        clips[faststart] = body
    return clips


class Rig:
    """The tmp databases, both scripted hosts patched in, the worker module, and the job once claimed."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clip: bytes) -> None:
        self.clip = clip
        self.whitelist = tmp_path / "whitelist.db"
        _whitelist(self.whitelist, JOB_VIDEOS, deny=True)
        self.subtitles = tmp_path / "subtitles.db"
        self.conn = connect_subtitles_db(self.subtitles)
        ensure_subtitles_schema(self.conn)
        # Every value cues_json is ever set to, so a write later overwritten (already_english's NULL) still shows.
        with self.conn:
            self.conn.execute("CREATE TABLE cues_writes (state TEXT, cues_json TEXT)")
            self.conn.execute("CREATE TRIGGER log_cues_writes AFTER UPDATE OF cues_json ON subtitles BEGIN INSERT INTO cues_writes (state, cues_json) VALUES (new.state, new.cues_json); END")
        self.instance = ScriptedHost()
        self.instance.serve(VIDEO_URL, body=_video())
        self.media = ScriptedHost()
        self.serve_media("declared")
        self.worker = _worker()
        monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", _dispatching_opener(self.instance, self.media))
        self.key = ("v-1", HOST)
        self.job = None

    def serve_media(self, route: str) -> None:
        if route == "declared":
            self.media.serve(MEDIA_URL, headers={"Content-Length": str(len(self.clip))}, body=self.clip)
        elif route == "streamed":
            self.media.serve(MEDIA_URL, body=self.clip)
        else:
            target = OFF_HOST_TARGET if route == "off-host redirect" else SAME_HOST_TARGET
            self.media.serve(MEDIA_URL, status=302, headers={"Location": target})
            # Served, so a worker that followed it would decode the clip and end ready.
            self.media.serve(target, headers={"Content-Length": str(len(self.clip))}, body=self.clip)

    def redirect_video(self, target: str) -> None:
        self.instance.serve(VIDEO_URL, status=302, headers={"Location": target})
        # Served, so a worker that followed it would read a valid JSON and go on to the media.
        self.instance.serve(target, body=_video())

    def claim(self, video_id: str = "v-1", host: str = HOST) -> None:
        from data.subtitles import claim_translate_job

        assert tuple(enqueue_translate_job(self.conn, video_id, host, "en", 50, QUEUED_AT)) == ("queued", "queued")
        self.job = claim_translate_job(self.conn, "en", STARTED_AT)
        self.key = (video_id, host)
        assert (self.job["video_id"], self.job["instance_domain"], self.job["started_at"], self.job["attempts"]) == (video_id, host, STARTED_AT, 1)  # control: a running job, claimed once

    def run(self, runner: StubRunner, stop: threading.Event | None = None, **overrides: object) -> bool:
        """`run_job` on the claimed job (claiming v-1 first if none is); its return value, True only for a whitelist.db requeue."""
        if self.job is None:
            self.claim()
        # One-second chunks, so the clip's four seconds are four windows.
        args = Namespace(whitelist_db=self.whitelist, max_duration=MAX_DURATION, max_bytes=len(self.clip), max_chunk_seconds=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        return self.worker.run_job(self.conn, self.job, args, runner, stop or threading.Event(), {"at": time.monotonic()})

    def row(self) -> dict:
        """Every column of the job's row, through a fresh plain connection."""
        conn = sqlite3.connect(self.subtitles)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = 'en'", self.key).fetchone()
            return dict(row) if row is not None else {}
        finally:
            conn.close()

    def running(self) -> tuple[str, list | None]:
        """The row's state and cues as a reader sees them now, cues sorted so only their set counts."""
        row = self.row()
        cues = json.loads(row["cues_json"]) if row.get("cues_json") is not None else None
        return row.get("state"), (sorted(cues, key=lambda cue: (cue["start"], cue["end"])) if cues is not None else None)

    def cues_writes(self) -> list[str | None]:
        conn = sqlite3.connect(self.subtitles)
        try:
            return [row[0] for row in conn.execute("SELECT cues_json FROM cues_writes ORDER BY rowid")]
        finally:
            conn.close()


class StubRunner:
    """Stands in for WhisperRunner (model, speech, transcribe, unload): speech is any non-zero sample in the window; transcribe answers two out-of-order segments and `language`, after `on_transcribe`; each transcribe call and each silent window records the row as a reader sees it then."""

    def __init__(self, rig: Rig, language: str = "fr", silent: bool = False, on_transcribe=None) -> None:
        self.model = None
        self.rig = rig
        self.language = language
        self.silent = silent
        self.on_transcribe = on_transcribe
        self.events: list[tuple] = []
        self.transcribes = 0
        self.unloads = 0

    def speech(self, pcm: bytes) -> list[tuple[int, int]]:
        samples = array.array("h", bytes(pcm))
        if self.silent or not any(samples):
            self.events.append(("silence", self.rig.running()))
            return []
        return [(0, len(samples))]

    def transcribe(self, pcm: bytes, language: str | None = None) -> tuple[list[tuple[float, float, str]], str]:
        self.transcribes += 1
        self.events.append(("transcribe", len(pcm) // 2, self.rig.running()))
        if self.on_transcribe is not None:
            self.on_transcribe(self)
        n = self.transcribes
        return [(0.6, 0.9, f"call {n} b"), (0.1234, 0.5678, f"call {n} a")], self.language

    def unload(self) -> None:
        self.unloads += 1


@pytest.fixture
def rig(tmp_path, monkeypatch, clip) -> Rig:
    built = Rig(tmp_path, monkeypatch, clip)
    yield built
    built.conn.close()


# Whitelist at claim and serve back-off helpers.


def _break_whitelist(rig: Rig, how: str) -> sqlite3.Connection | None:
    """Break the rig's whitelist.db as `how` says; the holding connection when it is held, for the caller to close."""
    if how == "drop column":
        conn = sqlite3.connect(rig.whitelist)
        conn.execute("ALTER TABLE videos DROP COLUMN video_uuid")
        conn.commit()
        conn.close()
    elif how == "delete":
        rig.whitelist.unlink()
    elif how == "truncate":
        rig.whitelist.write_bytes(b"")
    else:
        holder = sqlite3.connect(rig.whitelist, isolation_level=None)
        holder.execute("BEGIN EXCLUSIVE")
        return holder
    return None


def _run_broken(rig: Rig, caplog: pytest.LogCaptureFixture, how: str) -> bool:
    """Claim v-1, break whitelist.db as `how` says, and run the job; `run_job`'s return value."""
    caplog.set_level(logging.INFO)
    rig.claim()
    holder = _break_whitelist(rig, how)
    try:
        return rig.run(StubRunner(rig))
    finally:
        if holder is not None:
            holder.close()


def _job_tuple(rig: Rig) -> tuple:
    row = rig.row()
    return row["state"], row["attempts"], row["queued_at"], row["error"], row["finished_at"]


def _recording(resolve, locked_calls: int | None = 0):
    """A resolve_video stand-in noting (monotonic time, video_id, host) per call; it raises `database is locked` for the first `locked_calls` calls (None: every call) and otherwise calls `resolve`."""
    calls: list[tuple[float, str, str]] = []

    def recorded(whitelist_path, video_id, host, max_duration):
        calls.append((time.monotonic(), video_id, host))
        if locked_calls is None or len(calls) <= locked_calls:
            raise sqlite3.OperationalError(LOCKED)
        return resolve(whitelist_path, video_id, host, max_duration)

    recorded.calls = calls
    return recorded


def _until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


# Service helpers.


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {"subtitles": tmp_path / "subtitles.db", "whitelist": tmp_path / "whitelist.db", "lock": tmp_path / "translate-worker.lock", "log": tmp_path / "translate-worker.log"}


def _run_argv(paths: dict[str, Path]) -> list[str]:
    return [str(ENGINE_PY), str(WORKER), "--whitelist-db", str(paths["whitelist"]), "--subtitles-db", str(paths["subtitles"]), "run", "--lock", str(paths["lock"]), "--log", str(paths["log"])]


def _require_tools() -> None:
    assert ENGINE_PY.exists(), f"the Engine interpreter is missing at {ENGINE_PY}"
    # run checks ffmpeg before it takes the lock, so without it every run here would exit 1 for that reason instead.
    if shutil.which("ffmpeg") is None:
        pytest.fail("ffmpeg is not on PATH; the translate worker decodes media with it")


def _locked_by_someone(lock: Path) -> bool:
    fd = os.open(lock.as_posix(), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def _beat(db: Path) -> tuple[int, int] | None:
    """The heartbeat row as (beat_at, pid), or None while the file, the table or the row is missing; mode=ro, so polling never creates the file."""
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    except sqlite3.OperationalError:
        return None
    try:
        row = conn.execute("SELECT beat_at, pid FROM translate_worker_heartbeat WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return (row[0], row[1]) if row is not None else None


def _next_beat(db: Path, proc: subprocess.Popen, after: tuple[int, int] | None, seconds: float) -> tuple[int, int] | None:
    """The first heartbeat row with a beat_at past `after`'s, polled every 0.2 s for up to `seconds` while proc runs; None if none came."""
    deadline = time.monotonic() + seconds
    while proc.poll() is None and time.monotonic() < deadline:
        row = _beat(db)
        if row is not None and (after is None or row[0] > after[0]):
            return row
        time.sleep(0.2)
    return None


def _jobs(db: Path) -> list[tuple[str, str | None]]:
    """Every subtitles row's (state, error), read mode=ro."""
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return conn.execute("SELECT state, error FROM subtitles").fetchall()
    finally:
        conn.close()


def _sidecars(paths: dict[str, Path]) -> list[str]:
    return sorted(path.name for path in paths["subtitles"].parent.iterdir() if path.name.startswith(paths["subtitles"].name) and path != paths["subtitles"])


@pytest.fixture
def holder(tmp_path: Path):
    """A second open file description holding the worker's flock, as a running worker would."""
    lock = _paths(tmp_path)["lock"]
    fd = os.open(lock.as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield lock
    finally:
        os.close(fd)


# Enqueue.


def test_enqueue_by_uuid_and_unnormalised_host_queues_one_whisper_row_under_the_canonical_key(dbs):
    before_ms = _now_ms()
    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", "PEER.Example."])
    after_ms = _now_ms()

    assert returncode == EXIT_QUEUED, (returncode, lines, err)
    assert _one_line_leads(lines, "queued"), lines
    # Keyed on the row's canonical `v-1` and `peer.example`, not the requested uuid or host.
    assert _rows(dbs["subtitles"]) == [("v-1", HOST, "en", "queued", "whisper", 0)]
    conn = sqlite3.connect(dbs["subtitles"])
    queued_at, fetched_at = conn.execute("SELECT queued_at, fetched_at FROM subtitles").fetchone()
    conn.close()
    # Claim orders on queued_at, so it is the enqueue's own wall-clock ms (data.time.now_ms), as fetched_at is.
    assert isinstance(queued_at, int) and before_ms <= queued_at <= after_ms and fetched_at == queued_at, (before_ms, queued_at, fetched_at, after_ms)


@pytest.mark.parametrize("present", PRESENT.values(), ids=PRESENT.keys())
def test_a_key_already_present_in_any_state_is_reported_with_that_state_and_left_untouched(dbs, present):
    conn = sqlite3.connect(dbs["subtitles"])
    _insert(conn, "q-0", "other.example", {"state": "queued", "source": "whisper", "fetched_at": 1, "queued_at": 1, "attempts": 0})
    _insert(conn, "v-1", HOST, present)
    conn.close()
    before = _snapshot(dbs["subtitles"])

    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", "PEER.Example."])

    assert returncode == EXIT_EXISTS, (returncode, lines, err)
    assert _one_line_leads(lines, f"already present: {present['state']}"), lines
    assert _snapshot(dbs["subtitles"]) == before  # no column of any row rewritten, no row added


def test_enqueue_at_the_queue_cap_is_refused_and_writes_nothing(dbs):
    conn = sqlite3.connect(dbs["subtitles"])
    for n in range(QUEUE_CAP - 1):
        _insert(conn, f"q-{n}", "other.example", {"state": "queued", "source": "whisper", "fetched_at": n, "queued_at": n, "attempts": 0})
    # Rows in other states are not queued jobs and do not count toward the cap.
    _insert(conn, "r-1", "other.example", PRESENT["running"])
    _insert(conn, "b-1", "other.example", PRESENT["B1 ready/instance"])
    conn.close()

    returncode, lines, err = _enqueue(dbs, ["--id", "u-1", "--host", HOST])
    assert returncode == EXIT_QUEUED, (returncode, lines, err)  # 49 queued is under the cap
    assert _one_line_leads(lines, "queued"), lines
    rows = _rows(dbs["subtitles"])
    assert len(rows) == QUEUE_CAP + 2 and sum(row[3] == "queued" for row in rows) == QUEUE_CAP, rows  # control: the queue now holds exactly the cap

    returncode, lines, err = _enqueue(dbs, ["--id", "u-2", "--host", HOST])

    assert returncode == EXIT_CAP, (returncode, lines, err)
    assert _one_line_leads(lines, "refused: queue cap"), lines
    assert _rows(dbs["subtitles"]) == rows  # row count unchanged, no v-2 row


@pytest.mark.parametrize("case", REFUSALS)
def test_a_refused_video_exits_5_naming_its_reason_and_writes_no_row(dbs, case):
    refused, reason, control, lift_deny = REFUSALS[case]
    returncode, lines, err = _enqueue(dbs, refused)

    assert returncode == EXIT_REFUSED, (returncode, lines, err)
    assert _one_line_leads(lines, reason), lines
    assert _rows(dbs["subtitles"]) == []  # no row written

    # Control: the request differing in that one thing queues, so the refusal above was its reason's doing.
    if lift_deny:
        conn = sqlite3.connect(dbs["whitelist"])
        conn.execute("UPDATE instance_denylist SET is_active = 0")
        conn.commit()
        conn.close()
    returncode, lines, err = _enqueue(dbs, control)
    assert returncode == EXIT_QUEUED, (returncode, lines, err)
    assert _rows(dbs["subtitles"]) == [(*CONTROL_KEYS[case], "en", "queued", "whisper", 0)]


# Job pipeline: bounds.


@pytest.mark.parametrize("case", BOUNDS.values(), ids=BOUNDS.keys())
def test_a_job_breaking_a_bound_ends_failed_with_that_bounds_text_and_requests_nothing_after_the_refusal(rig, case):
    if "video" in case:
        rig.instance.serve(VIDEO_URL, body=case["video"])
    if "video_redirect" in case:
        rig.redirect_video(case["video_redirect"])
    rig.serve_media(case.get("route", "declared"))
    max_bytes = len(rig.clip) - case.get("under_clip", 0)
    rig.claim(*case.get("key", ("v-1", HOST)))

    rig.run(StubRunner(rig), max_bytes=max_bytes, max_duration=case.get("max_duration", MAX_DURATION))

    row = rig.row()
    assert row.get("state") == "failed", row
    assert _error_leads(row["error"], case["error"].format(max_bytes=max_bytes)), row["error"]
    assert rig.instance.opened == case.get("instance", INSTANCE_THEN_JSON)  # nothing asked of the instance after the refusing step
    assert rig.media.opened == case["media"]  # nothing asked of the media host after the refusing step
    if case.get("unread"):
        # Refused on the declared length: a worker that only counted while streaming would fail with the same text after reading.
        assert [response.reads for response in rig.media.responses] == [0]


def test_a_media_redirect_that_stays_on_the_media_host_is_followed(rig):
    rig.serve_media("same-host redirect")
    rig.run(StubRunner(rig))
    # Control for the off-host case: a redirect as such does not fail the job, its target's host does.
    assert (rig.row()["state"], rig.row()["source"]) == ("ready", "whisper")
    assert rig.media.opened == [MEDIA_URL, SAME_HOST_TARGET]


def test_a_video_json_redirect_that_stays_on_the_instance_domain_is_followed(rig):
    rig.redirect_video(SAME_DOMAIN_VIDEO_URL)
    rig.run(StubRunner(rig))
    # Control for the off-domain case: a redirect as such does not fail the job, its target's domain does.
    assert (rig.row()["state"], rig.row()["source"]) == ("ready", "whisper")
    assert rig.instance.opened == [CAPTIONS_URL, VIDEO_URL, SAME_DOMAIN_VIDEO_URL]


@pytest.mark.parametrize("case", PICKS.values(), ids=PICKS.keys())
def test_pick_media_url_prefers_hls_files_then_the_smallest_and_sorts_unknown_sizes_last(case):
    video, expected = case
    assert _worker().pick_media_url(video) == expected


# Job pipeline: outcomes.


def test_a_transcribed_job_rewrites_the_running_cues_after_each_speech_chunk_skips_silence_and_ends_ready_with_absolute_ms_times(rig):
    runner = StubRunner(rig)
    before_ms = _now_ms()
    rig.run(runner)
    after_ms = _now_ms()

    assert runner.events == [
        ("transcribe", SAMPLE_RATE, ("running", None)),
        ("silence", ("running", CHUNK_1)),
        ("transcribe", SAMPLE_RATE, ("running", CHUNK_1)),
        ("silence", ("running", CHUNK_1 + CHUNK_3)),
    ]  # running cues grow by exactly each speech chunk's cues, at absolute ms times, and a silent window is never transcribed
    row = rig.row()
    assert (row["state"], row["source"]) == ("ready", "whisper"), row
    assert json.loads(row["cues_json"]) == CHUNK_1 + CHUNK_3  # the full list, sorted by start although each chunk's segments came out of order
    assert isinstance(row["finished_at"], int) and before_ms <= row["finished_at"] <= after_ms, (before_ms, row["finished_at"], after_ms)
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # control: the path every bound case is measured against


def test_english_detected_on_the_first_chunk_ends_already_english_without_ever_writing_cues(rig):
    runner = StubRunner(rig, language="en")
    rig.run(runner)
    row = rig.row()
    assert runner.transcribes == 1  # control: detection ran on the first speech chunk
    assert row["state"] == "already_english", row
    assert row["cues_json"] is None
    assert [written for written in rig.cues_writes() if written is not None] == []  # no running rewrite before or after detection
    with rig.conn:
        rig.conn.execute("UPDATE subtitles SET cues_json = '[]' WHERE video_id = ? AND instance_domain = ?", rig.key)
    assert rig.cues_writes()[-1] == "[]"  # control: the trigger the assertion above reads does record a write


def test_audio_with_no_speech_ends_failed_no_speech_detected_without_transcribing(rig):
    runner = StubRunner(rig, silent=True)
    rig.run(runner)
    row = rig.row()
    assert [event[0] for event in runner.events] == ["silence"] * 4  # control: VAD was asked about every one-second window
    assert (row["state"], row["error"]) == ("failed", "no speech detected"), row
    assert runner.transcribes == 0


@pytest.mark.parametrize("faststart", [False, True], ids=["moov at end", "faststart control"])
def test_media_ffmpeg_decodes_to_nothing_ends_failed_no_audio_decoded_without_asking_vad(rig, mov_clips, faststart):
    body = mov_clips[faststart]
    rig.media.serve(MEDIA_URL, headers={"Content-Length": str(len(body))}, body=body)
    runner = StubRunner(rig)
    rig.run(runner, max_bytes=len(body))
    row = rig.row()
    assert rig.media.opened == [MEDIA_URL]
    if faststart:
        # Control: the same audio with its index first decodes and transcribes, so the failure below is the moov position alone.
        assert (row["state"], row["source"]) == ("ready", "whisper"), row
        return
    assert (row["state"], row["error"]) == ("failed", "no audio decoded"), row
    assert runner.events == [] and runner.transcribes == 0


def test_a_cuda_out_of_memory_ends_failed_with_its_text_and_unloads_the_model_once(rig):
    def out_of_memory(runner: StubRunner) -> None:
        raise RuntimeError(OOM)

    runner = StubRunner(rig, on_transcribe=out_of_memory)
    rig.run(runner)
    row = rig.row()
    assert row["state"] == "failed", row
    assert OOM in row["error"], row["error"]
    assert runner.unloads == 1


def test_an_english_instance_track_ends_ready_instance_with_finished_at_and_no_media_fetch(rig):
    rig.instance.serve(CAPTIONS_URL, body=EN_LISTING)
    rig.instance.serve(TRACK_URL, body=TRACK.encode("utf-8"))
    runner = StubRunner(rig)
    before_ms = _now_ms()
    rig.run(runner)
    after_ms = _now_ms()

    row = rig.row()
    assert (row["state"], row["source"]) == ("ready", "instance"), row
    assert json.loads(row["cues_json"]) == CUES and row["track_text"] == TRACK
    assert isinstance(row["finished_at"], int) and before_ms <= row["finished_at"] <= after_ms, (before_ms, row["finished_at"], after_ms)
    assert rig.instance.opened == [CAPTIONS_URL, TRACK_URL]  # no video JSON either
    assert rig.media.opened == []
    assert runner.transcribes == 0


def test_a_b1_takeover_mid_job_leaves_the_ready_instance_row_untouched(rig):
    taken: dict = {}

    def b1_stores_a_track(runner: StubRunner) -> None:
        from data.subtitles import store_ready_subtitles

        if taken:
            return
        b1 = connect_subtitles_db(rig.subtitles)
        store_ready_subtitles(b1, "v-1", HOST, "en", "instance", TRACK, CUES, 1_700_000_000_000)
        b1.close()
        taken.update(rig.row())

    runner = StubRunner(rig, on_transcribe=b1_stores_a_track)
    rig.run(runner)
    assert (taken["state"], taken["source"]) == ("ready", "instance")  # control: B1's write landed mid-job
    assert rig.row() == taken  # every column as B1 left it
    assert runner.transcribes == 1  # the job stopped at the takeover, the third second never transcribed


def test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept(rig):
    stop = threading.Event()
    rig.run(StubRunner(rig, on_transcribe=lambda runner: stop.set()), stop=stop)
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row


# Job pipeline: whitelist.db at claim.


@pytest.mark.parametrize("case", REQUEUED.values(), ids=REQUEUED.keys())
def test_a_locked_or_unopenable_whitelist_at_claim_requeues_the_job_unspent_requests_nothing_logs_one_warning_and_returns_true(rig, caplog, case):
    """A deleted whitelist.db or one held under EXCLUSIVE past the busy timeout at claim puts the job back to queued with attempts 0, queued_at kept and no error or finished_at; neither host is asked anything; exactly one WARNING names the worker, the key and the error text and nothing is logged at ERROR; `run_job` returns True."""
    how, text = case
    result = _run_broken(rig, caplog, how)

    assert _job_tuple(rig) == ("queued", 0, QUEUED_AT, None, None)  # claim unspent, queued_at kept, no error, no finished_at
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, [record.getMessage() for record in warnings]  # one warning, not none and not two
    message = warnings[0].getMessage()
    assert all(part in message for part in ("[translate-worker]", "v-1", HOST, text)), message  # names the worker, the key and the error text
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []  # not routed through the catch-all
    assert rig.instance.opened == [] and rig.media.opened == []  # nothing requested
    assert result is True  # serve reads this to back off


@pytest.mark.parametrize("case", FAILED.values(), ids=FAILED.keys())
def test_any_other_whitelist_error_at_claim_still_fails_the_job_through_the_logged_catch_all_and_returns_false(rig, caplog, case):
    """Any other OperationalError from whitelist.db at claim (a videos table without video_uuid, a zero-byte file read as an empty database) ends the job failed with `OperationalError: <text>` through the catch-all's one ERROR record carrying the exception, with no WARNING; `run_job` returns False."""
    how, text = case
    result = _run_broken(rig, caplog, how)

    row = rig.row()
    assert (row["state"], row["error"]) == ("failed", f"OperationalError: {text}"), row  # failed as before, not requeued or rewrapped
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1 and errors[0].levelno == logging.ERROR, [record.getMessage() for record in errors]  # one ERROR record
    assert errors[0].exc_info is not None and errors[0].exc_info[0] is sqlite3.OperationalError, errors[0].exc_info  # the catch-all's logging.exception
    assert [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING] == []  # the requeue branch's warning did not fire
    assert result is False  # serve does not back off


# Serve back-off after a whitelist.db requeue.


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job(rig, monkeypatch, injected):
    """`serve`, run in-process on a daemon thread, after a whitelist.db requeue looks up the same head job again no sooner than TRANSIENT_BACKOFF_SECONDS later, every lookup is for v-1 and never for d-1 queued behind it, and after a stop the row is queued with attempts 0 and queued_at kept."""
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", GAP_BACKOFF_SECONDS)
    lookups = _recording(rig.worker.resolve_video, locked_calls=None if injected else 0)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    if not injected:
        rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    # Queued behind v-1, so a requeue that lost v-1's place at the head would show as a d-1 lookup.
    assert tuple(enqueue_translate_job(rig.conn, "d-1", DENIED_HOST, "en", 50, QUEUED_AT + 1)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, {"at": time.monotonic()}), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reclaimed within the wait
        assert lookups.calls[1][0] - lookups.calls[0][0] >= GAP_BACKOFF_SECONDS, lookups.calls  # no sooner than the back-off after the first
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()  # control: serve returned, so the row below is at rest
    assert {call[1:] for call in lookups.calls} == {("v-1", HOST)}, lookups.calls  # every lookup was the head job, never d-1
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # the same head job, requeued unspent at its place


def test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim(rig, monkeypatch):
    """Inside `serve`'s second back-off on a deleted whitelist.db, `progress["at"]` read every 0.01 s for five slices is never more than two slices old, so the heartbeat never reads the wait as a stall; a stop set with more than 0.5 s of the back-off left ends `serve` within 0.5 s, with no lookup after the stop and the row queued with attempts 0."""
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", LIVE_BACKOFF_SECONDS)
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reached its second lookup
        assert _until(lambda: rig.row().get("state") == "queued", LIVE_BACKOFF_SECONDS / 2), rig.row()  # control: the second requeue landed, so serve is in the back-off

        ages = []
        end = time.monotonic() + SAMPLE_SECONDS
        while time.monotonic() < end:
            ages.append(time.monotonic() - progress["at"])
            time.sleep(SAMPLE_EVERY_SECONDS)

        assert max(ages) < FRESH_SECONDS, ages  # no read through five slices of the wait found progress older than two slices
        assert len(lookups.calls) == 2, lookups.calls  # control: every read fell in the second back-off, not a fresh claim

        stop_at = time.monotonic()
        left = lookups.calls[1][0] + LIVE_BACKOFF_SECONDS - stop_at
        assert left > STOP_WITHIN_SECONDS, left  # control: a wait ignoring the stop would outlast the bound below
        stop.set()
        thread.join(5)
        elapsed = time.monotonic() - stop_at
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and elapsed < STOP_WITHIN_SECONDS, (thread.is_alive(), elapsed)  # serve returned within about one slice of the stop
    assert len(lookups.calls) == 2, lookups.calls  # no claim after the stop
    row = rig.row()
    assert (row["state"], row["attempts"]) == ("queued", 0), row  # the job is left requeued unspent


# Service.


@pytest.mark.parametrize("b1_file", [False, True], ids=["no-subtitles-db", "b1-subtitles-db"])
def test_run_against_a_held_lock_exits_6_names_the_lock_and_writes_nothing(tmp_path: Path, holder: Path, b1_file: bool) -> None:
    """With the flock held elsewhere, `run` exits 6 and logs the lock's path; an absent subtitles.db is not created, and a B1-shaped one stays byte-identical, with no job column, no heartbeat table and no sidecar file."""
    _require_tools()
    paths = _paths(tmp_path)
    if b1_file:
        _b1_file(paths["subtitles"])
    before = paths["subtitles"].read_bytes() if b1_file else None
    assert _locked_by_someone(holder)  # control: the holder really holds it

    # A run that waited on the lock instead of refusing it raises TimeoutExpired here.
    result = subprocess.run(_run_argv(paths), capture_output=True, text=True, timeout=30, cwd=tmp_path)

    assert result.returncode == 6, (result.returncode, result.stdout, result.stderr)  # the locked exit, not argparse's 2, ffmpeg's 1 or a crash
    log = paths["log"].read_text(encoding="utf-8") if paths["log"].exists() else ""
    assert str(paths["lock"]) in log, (log, result.stdout, result.stderr)  # the log names the held lock
    assert _sidecars(paths) == []  # no -wal, -shm or -journal, so the file was never opened for writing
    if not b1_file:
        assert not paths["subtitles"].exists()  # a refused run creates no subtitles.db
        return
    assert paths["subtitles"].read_bytes() == before  # not one byte written, the WAL switch included
    conn = sqlite3.connect(f"file:{paths['subtitles'].as_posix()}?mode=ro", uri=True)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert columns == B1_COLUMNS, columns  # no job column added
    assert "translate_worker_heartbeat" not in tables, tables  # no heartbeat table, so no heartbeat row


def test_idle_run_beats_with_its_pid_every_5_s_and_releases_the_lock_on_sigterm(tmp_path: Path) -> None:
    """On an idle queue `run` writes heartbeat rows carrying its own pid and a wall-clock ms `beat_at`, three distinct beats 4.5 to 6.5 s apart, holds the lock while it runs, and after SIGTERM exits 0 within 60 s with the lock free."""
    _require_tools()
    paths = _paths(tmp_path)
    start_ms = _now_ms()
    # The worker logs to stdout as well; a file, not a pipe, so a chatty idle loop can never block on a full pipe.
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(_run_argv(paths), stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            beats: list[tuple[int, int, int]] = []
            first_at: float | None = None
            deadline = time.monotonic() + FIRST_BEAT_SECONDS
            while proc.poll() is None and len(beats) < 3 and time.monotonic() < deadline:
                row = _beat(paths["subtitles"])
                if row is not None and (not beats or beats[-1][0] != row[0]):
                    beats.append((row[0], row[1], _now_ms()))
                    if first_at is None:
                        first_at = time.monotonic()
                        deadline = first_at + BEAT_WINDOW_SECONDS
                time.sleep(0.2)
            output = out_path.read_text(encoding="utf-8", errors="replace")
            assert len(beats) == 3, (beats, proc.poll(), output)  # beat_at advanced at least twice within the window
            assert [pid for _, pid, _ in beats] == [proc.pid] * 3, (beats, proc.pid)  # the row carries the running worker's pid
            assert all(start_ms <= beat_at <= seen_ms for beat_at, _, seen_ms in beats), (start_ms, beats)  # beat_at is a wall-clock ms stamp taken during this run
            gaps = [later[0] - earlier[0] for earlier, later in zip(beats, beats[1:])]
            assert all(BEAT_GAP_MS[0] <= gap <= BEAT_GAP_MS[1] for gap in gaps), gaps  # about 5 s apart
            assert proc.poll() is None, (proc.returncode, output)  # control: still serving, so the exit code below answers SIGTERM
            assert _locked_by_someone(paths["lock"])  # control: the running worker holds the lock, so its absence below is a release

            proc.send_signal(signal.SIGTERM)
            try:
                code = proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # a clean stop
            assert not _locked_by_someone(paths["lock"])  # the lock is released, so the next worker can start
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_run_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on(tmp_path: Path) -> None:
    """A `run` with STALL_SECONDS lowered to 4 s beats while idle; while its main loop is held in a claimed job's whitelist lookup the row's `beat_at` stays put over two due ticks; once the lookup returns, the job fails `not in whitelist` and beating resumes with the subprocess's pid."""
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"], [], deny=False)
    argv = [str(ENGINE_PY), "-c", STALL_DRIVER, str(WORKER), str(TEST_STALL_SECONDS), *_run_argv(paths)[2:]]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            idle = _next_beat(paths["subtitles"], proc, first, BEAT_WINDOW_SECONDS) if first is not None else None
            assert idle is not None and idle[1] == proc.pid, (first, idle, proc.poll(), out_path.read_text(encoding="utf-8", errors="replace"))  # the worker beats while idle under the lowered threshold, so the silence below is a stop

            holder = sqlite3.connect(paths["whitelist"], isolation_level=None)
            try:
                holder.execute("BEGIN EXCLUSIVE")
                conn = connect_subtitles_db(paths["subtitles"])
                try:
                    assert enqueue_translate_job(conn, *STALL_KEY, "en", 50, _now_ms()) == ("queued", "queued")  # control: one job on the queue
                finally:
                    conn.close()
                deadline = time.monotonic() + 10.0
                while _jobs(paths["subtitles"]) != [("running", None)] and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop claimed the job and is now in its whitelist lookup
                time.sleep(TEST_STALL_SECONDS + 1.0)
                stalled = _beat(paths["subtitles"])
                time.sleep(STALLED_WINDOW_SECONDS)
                assert proc.poll() is None, (proc.returncode, out_path.read_text(encoding="utf-8", errors="replace"))  # control: the worker is alive, so the silence below is not an exit
                assert _jobs(paths["subtitles"]) == [("running", None)]  # control: the main loop is still held, so it stalled for the whole window
                assert _beat(paths["subtitles"]) == stalled, stalled  # no beat over two due ticks while the worker's own main loop is stalled
                released_ms = _now_ms()
            finally:
                holder.close()

            resumed = _next_beat(paths["subtitles"], proc, stalled, RESUME_SECONDS)
            assert resumed is not None, (stalled, proc.poll(), _jobs(paths["subtitles"]), out_path.read_text(encoding="utf-8", errors="replace"))  # beating resumes once the main loop moves on
            assert resumed[1] == proc.pid, (resumed, proc.pid)  # the running worker's own beat
            assert resumed[0] >= released_ms, (resumed, released_ms)  # written after the main loop was let go
            assert _jobs(paths["subtitles"]) == [("failed", "not in whitelist")]  # control: the main loop finished the job it was held in

            proc.send_signal(signal.SIGTERM)
            try:
                code = proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                pytest.fail(f"run still alive {STOP_WINDOW_SECONDS} s after SIGTERM")
            assert code == 0, (code, out_path.read_text(encoding="utf-8", errors="replace"))  # control: a clean stop, so nothing above ran in a dying worker
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
