"""`run_job` in `engine/server/db/jobs/translate-worker.py`, plan 49 phase 3: a claimed job is refused at every AC5 bound with that bound's error text and no remote request after the refusal, and a transcribed job rewrites its running row's cues after each speech chunk and ends in exactly one state.

Seam: `run_job(conn, job, args, runner, stop, progress)` called in-process on a job enqueued and claimed with the store's own functions (queued_at 1000, started_at 2000), over a tmp whitelist.db (v-1/u-1 on peer.example; d-1 on denied.example, actively denied, stored uppercase) and a tmp subtitles.db. The instance is a scripted https host behind `internal_translate.build_opener`, the media host a second one behind the worker module's `build_opener`; each records every URL opened, in order, and urllib's real redirect handling runs. ffmpeg is real and decodes a 4 s 16 kHz WAV clip generated with `ffmpeg -f lavfi` (sine in seconds 0 and 2, exact silence in seconds 1 and 3); the test fails if ffmpeg is missing. Whisper and VAD are a stub runner: speech is any non-zero sample in the window, and transcribe answers two segments out of order, (0.6, 0.9) and (0.1234, 0.5678), with language `fr` unless told otherwise. Args: max_duration 5, max_bytes the clip's size, max_chunk_seconds 1. The video JSON declares duration 5 and one file.

Bounds (C1): each case ends the row `failed` with its text (exactly, or that text followed by `: ` and detail), and the instance and media host saw exactly the URLs listed, so nothing was requested after the refusing step:

- a key no longer in whitelist.db (`not in whitelist`) and a denied host (`host denied`): no URL at all;
- JSON with no duration (`video duration unknown`), JSON duration 6 (`duration 6s over 5s`), and a single file that is http, an IPv4 or IPv6 literal, a decimal, dotted-numeric or hex host, a single-label host, an explicit port, userinfo, or `hasAudio: false` (`no usable https media file`), and a video JSON redirected off peer.example (`video JSON fetch failed`, the target never requested though it serves a valid JSON): the caption list and the video JSON only;
- a Content-Length one byte over max_bytes (`media over <max_bytes> bytes`, with the body never read), the same body streamed with no length (same text), a JSON duration of 3 under max_duration 3 with 4 s of audio decoded (`audio longer than 3s`), and a redirect off the media host (`media download failed`, the target never requested): those two and the media URL only.

A video JSON redirect that stays on peer.example, and a media redirect that stays on the media host, are each followed and the job ends ready. `pick_media_url` takes the smallest declared size across `files[]` and `streamingPlaylists[].files[]`, sorts a file with no size after any sized one, and still picks it when it is the only file.

Outcomes (C2):

- Transcribed: the row read at each transcribe call and at each silent window is, in order, running with no cues; running with chunk 1's two cues (silent second); running with chunk 1's cues again (third second, transcribed); running with chunks 1 and 3's four cues (silent fourth second). So it grew by exactly each speech chunk's cues, each transcribe got one second of PCM, and the silent windows got no transcribe call. Chunk 3's times are the segment times plus 2.0 s, rounded to ms (2.123, 2.568, 2.6, 2.9). The row ends ready/whisper with all four cues sorted by start and a finished_at taken during the run.
- `en` detected: already_english, cues_json NULL, and no write ever set cues_json to a value (the trigger that would show one is shown recording a write afterwards).
- No speech anywhere: failed `no speech detected`, VAD asked about all four windows, transcribe never called.
- CUDA out of memory raised by transcribe: failed with that text, unload called exactly once.
- The instance holds an English track: ready/instance with the parsed cues and track text, finished_at taken during the run, the caption list and the track fetched, and nothing fetched from the media host.
- B1's route stores ready/instance during the first transcribe: every column of the row reads the same afterwards, and the worker stops that job instead of transcribing the third second.
- stop set during the first transcribe: queued again with attempts back to 0 and queued_at still 1000.

Every database is under `tmp_path`, never the repo's own.
"""
from __future__ import annotations

import array
import importlib
import importlib.util
import json
import shutil
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
SERVER_DIR = ROOT / "engine" / "server"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

HOST = "peer.example"
DENIED_HOST = "denied.example"
# (video_id, video_uuid, instance_domain): the uuid differs from the id, so an instance URL built from the id instead of the uuid shows.
PEER_VIDEO = ("v-1", "u-1", HOST)
DENIED_VIDEO = ("d-1", "du-1", DENIED_HOST)
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
# Sine in seconds 0 and 2, silence in 1 and 3. WAV, not a lossy codec: probed through the plan's FFMPEG_ARGS over stdin it decodes to exactly 64000 samples, seconds 1 and 3 all zero, so one-second windows line up with the speech.
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

# (video JSON, the URL picked); every URL is acceptable, so only size decides.
PICKS = {
    "smallest in files[], listed after a larger one": ({"files": [{"fileUrl": "https://media.example/a-720.mp4", "size": 300}, {"fileUrl": "https://media.example/b-240.mp4", "size": 100}], "streamingPlaylists": [{"files": [{"fileUrl": "https://media.example/c-480.mp4", "size": 200}]}]}, "https://media.example/b-240.mp4"),
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

    def build_opener(self, *handlers: object) -> urllib.request.OpenerDirector:
        scripted = self

        class ScriptedHTTPS(HTTPSHandler):
            def https_open(self, req: Request) -> Response:
                return scripted.open(req)

        class ScriptedHTTP(HTTPHandler):
            def http_open(self, req: Request) -> Response:
                return scripted.open(req)

        return urllib.request.build_opener(ScriptedHTTPS(), ScriptedHTTP(), *[handler for handler in handlers if not _socket_handler(handler)])


def _socket_handler(handler: object) -> bool:
    """Whether a handler build_opener was given opens connections itself, so it must give way to the scripted host."""
    kind = handler if isinstance(handler, type) else type(handler)
    return issubclass(kind, (HTTPHandler, HTTPSHandler))


def _worker() -> ModuleType:
    """The worker script as a module; its hyphenated name rules out a plain import."""
    spec = importlib.util.spec_from_file_location("translate_worker", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _whitelist(path: Path) -> None:
    """A whitelist.db built as test_internal_translate.py's `_whitelist`, holding PEER_VIDEO and DENIED_VIDEO with NULL stored durations and an active deny row for DENIED_HOST stored uppercase."""
    from data.moderation import ensure_moderation_schema

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    for video_id, uuid, host in (PEER_VIDEO, DENIED_VIDEO):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, title, error_count) VALUES (?, ?, ?, ?, 0)", (video_id, uuid, host, f"title:{video_id}"))
    conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 1, 0, 0)", (DENIED_HOST.upper(),))
    conn.commit()
    conn.close()


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _leads(error: str | None, text: str) -> bool:
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


class Rig:
    """The tmp databases, both scripted hosts patched in, the worker module, and the job once claimed."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clip: bytes) -> None:
        from data.subtitles import connect_subtitles_db, ensure_subtitles_schema

        self.clip = clip
        self.whitelist = tmp_path / "whitelist.db"
        _whitelist(self.whitelist)
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
        monkeypatch.setattr(importlib.import_module("handlers.internal_translate"), "build_opener", self.instance.build_opener)
        monkeypatch.setattr(self.worker, "build_opener", self.media.build_opener)
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
        from data.subtitles import claim_translate_job, enqueue_translate_job

        assert tuple(enqueue_translate_job(self.conn, video_id, host, "en", 50, QUEUED_AT)) == ("queued", "queued")
        self.job = claim_translate_job(self.conn, "en", STARTED_AT)
        self.key = (video_id, host)
        assert (self.job["video_id"], self.job["instance_domain"], self.job["started_at"], self.job["attempts"]) == (video_id, host, STARTED_AT, 1)  # control: a running job, claimed once

    def run(self, runner: StubRunner, stop: threading.Event | None = None, **overrides: object) -> None:
        if self.job is None:
            self.claim()
        # One-second chunks, so the clip's four seconds are four windows.
        args = Namespace(whitelist_db=self.whitelist, max_duration=MAX_DURATION, max_bytes=len(self.clip), max_chunk_seconds=1)
        for name, value in overrides.items():
            setattr(args, name, value)
        self.worker.run_job(self.conn, self.job, args, runner, stop or threading.Event(), {"at": time.monotonic()})

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
    assert row.get("state") == "failed", row  # C1
    assert _leads(row["error"], case["error"].format(max_bytes=max_bytes)), row["error"]  # C1
    assert rig.instance.opened == case.get("instance", INSTANCE_THEN_JSON)  # C1: nothing asked of the instance after the refusing step
    assert rig.media.opened == case["media"]  # C1: nothing asked of the media host after the refusing step
    if case.get("unread"):
        # Refused on the declared length: a worker that only counted while streaming would fail with the same text after reading.
        assert [response.reads for response in rig.media.responses] == [0]  # C1


def test_a_media_redirect_that_stays_on_the_media_host_is_followed(rig):
    rig.serve_media("same-host redirect")
    rig.run(StubRunner(rig))
    # Control for the off-host case: a redirect as such does not fail the job, its target's host does.
    assert (rig.row()["state"], rig.row()["source"]) == ("ready", "whisper")  # C1
    assert rig.media.opened == [MEDIA_URL, SAME_HOST_TARGET]  # C1


def test_a_video_json_redirect_that_stays_on_the_instance_domain_is_followed(rig):
    rig.redirect_video(SAME_DOMAIN_VIDEO_URL)
    rig.run(StubRunner(rig))
    # Control for the off-domain case: a redirect as such does not fail the job, its target's domain does.
    assert (rig.row()["state"], rig.row()["source"]) == ("ready", "whisper")  # C1
    assert rig.instance.opened == [CAPTIONS_URL, VIDEO_URL, SAME_DOMAIN_VIDEO_URL]  # C1


@pytest.mark.parametrize("case", PICKS.values(), ids=PICKS.keys())
def test_pick_media_url_takes_the_smallest_file_and_sorts_unknown_sizes_last(case):
    video, expected = case
    assert _worker().pick_media_url(video) == expected  # C1


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
    ]  # C2: running cues grow by exactly each speech chunk's cues, at absolute ms times, and a silent window is never transcribed
    row = rig.row()
    assert (row["state"], row["source"]) == ("ready", "whisper"), row  # C2
    assert json.loads(row["cues_json"]) == CHUNK_1 + CHUNK_3  # C2: the full list, sorted by start although each chunk's segments came out of order
    assert isinstance(row["finished_at"], int) and before_ms <= row["finished_at"] <= after_ms, (before_ms, row["finished_at"], after_ms)  # C2
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # control: the path every bound case is measured against


def test_english_detected_on_the_first_chunk_ends_already_english_without_ever_writing_cues(rig):
    runner = StubRunner(rig, language="en")
    rig.run(runner)
    row = rig.row()
    assert runner.transcribes == 1  # control: detection ran on the first speech chunk
    assert row["state"] == "already_english", row  # C2
    assert row["cues_json"] is None  # C2
    assert [written for written in rig.cues_writes() if written is not None] == []  # C2: no running rewrite before or after detection
    with rig.conn:
        rig.conn.execute("UPDATE subtitles SET cues_json = '[]' WHERE video_id = ? AND instance_domain = ?", rig.key)
    assert rig.cues_writes()[-1] == "[]"  # control: the trigger the assertion above reads does record a write


def test_audio_with_no_speech_ends_failed_no_speech_detected_without_transcribing(rig):
    runner = StubRunner(rig, silent=True)
    rig.run(runner)
    row = rig.row()
    assert [event[0] for event in runner.events] == ["silence"] * 4  # control: VAD was asked about every one-second window
    assert (row["state"], row["error"]) == ("failed", "no speech detected"), row  # C2
    assert runner.transcribes == 0  # C2


def test_a_cuda_out_of_memory_ends_failed_with_its_text_and_unloads_the_model_once(rig):
    def out_of_memory(runner: StubRunner) -> None:
        raise RuntimeError(OOM)

    runner = StubRunner(rig, on_transcribe=out_of_memory)
    rig.run(runner)
    row = rig.row()
    assert row["state"] == "failed", row  # C2
    assert OOM in row["error"], row["error"]  # C2
    assert runner.unloads == 1  # C2


def test_an_english_instance_track_ends_ready_instance_with_finished_at_and_no_media_fetch(rig):
    rig.instance.serve(CAPTIONS_URL, body=EN_LISTING)
    rig.instance.serve(TRACK_URL, body=TRACK.encode("utf-8"))
    runner = StubRunner(rig)
    before_ms = _now_ms()
    rig.run(runner)
    after_ms = _now_ms()

    row = rig.row()
    assert (row["state"], row["source"]) == ("ready", "instance"), row  # C2
    assert json.loads(row["cues_json"]) == CUES and row["track_text"] == TRACK  # C2
    assert isinstance(row["finished_at"], int) and before_ms <= row["finished_at"] <= after_ms, (before_ms, row["finished_at"], after_ms)  # C2
    assert rig.instance.opened == [CAPTIONS_URL, TRACK_URL]  # C2: no video JSON either
    assert rig.media.opened == []  # C2
    assert runner.transcribes == 0  # C2


def test_a_b1_takeover_mid_job_leaves_the_ready_instance_row_untouched(rig):
    taken: dict = {}

    def b1_stores_a_track(runner: StubRunner) -> None:
        from data.subtitles import connect_subtitles_db, store_ready_subtitles

        if taken:
            return
        b1 = connect_subtitles_db(rig.subtitles)
        store_ready_subtitles(b1, "v-1", HOST, "en", "instance", TRACK, CUES, 1_700_000_000_000)
        b1.close()
        taken.update(rig.row())

    runner = StubRunner(rig, on_transcribe=b1_stores_a_track)
    rig.run(runner)
    assert (taken["state"], taken["source"]) == ("ready", "instance")  # control: B1's write landed mid-job
    assert rig.row() == taken  # C2: every column as B1 left it
    assert runner.transcribes == 1  # C2: the job stopped at the takeover, the third second never transcribed


def test_a_stop_mid_job_requeues_with_its_attempt_restored_and_its_queued_at_kept(rig):
    stop = threading.Event()
    rig.run(StubRunner(rig, on_transcribe=lambda runner: stop.set()), stop=stop)
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # C2
