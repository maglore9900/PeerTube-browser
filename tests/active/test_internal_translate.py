"""`engine/server/api/handlers/internal_translate.py`: an instance's English WebVTT track becomes plain-text cues sorted by start, or None for the whole track; the bounded fetch answers None for anything outside its bounds; `/internal/translate` answers 404 `Video not found` with no instance fetch until the video resolves and its host is not denied, stores only a `ready` track in subtitles.db and serves it from there with no fetch; every 200 it gives says whether a translate worker is serving (a heartbeat 0 to 15 000 ms old), a stored job answers its state from the store, and a running one its cues from `after` with the stored `total`; `/internal/translate/enqueue` queues a job for a resolved video only while a worker is serving; an Engine start creates that store at its configured path and routes both routes behind the bridge gate. Nothing here translates: the cues served are an English track the instance already holds or a job's stored cues.

Parse (`parse_webvtt`):

- A CRLF track with a BOM, a `WEBVTT - title` header, NOTE/STYLE/REGION blocks, a cue identifier with cue settings, hours present and absent, a zero-length cue and cues out of order gives exactly four `{start, end, text}` cues, in start order 1.0, 5.5, 10.0, 3723.004, with float times and the identifier, settings and skipped blocks absent from the text.
- `<b>x</b>&lt;i&gt;` gives the text `x<i>`.
- With one good cue present, the whole track is None for: no header, a `WEBVTTX` header, a blank line before the header, two-digit milliseconds, minutes of 60, an end 1 ms before its start, an identifier containing `-->`, an identifier with no timing line, and a stray text block; the good cue alone parses.
- A header alone, a header with only a NOTE, cues with no text, and a cue of markup only each give None.

Caption pick (`pick_english_track_path`), the parser's input path: the first entry whose `language.id` is exactly `en` gives its `captionPath`, past `en-US`, `fr` and a second `en`; a `fileUrl` off the host, a host-prefixed lookalike, http, an explicit port or userinfo, a protocol-relative `captionPath`, and a listing with no `en` track give None, while the same entry pointing on the host as `en` gives its path.

Fetch (`fetch_bounded`, and `SameHostRedirectHandler.redirect_request` called directly):

- The redirect handler returns a request for a same-host https target on 301, 302, 303, 307 and 308, and None for an off-host, host-prefixed lookalike, http, ported or userinfo target.
- A fetch follows a same-host redirect, absolute or relative, and returns the target's body; it returns None for a redirect to each refused target without ever requesting it.
- A declared `Content-Length` over 2 MB gives None with no body read; a body streamed past 2 MB with no length gives None; 2,000,000 bytes, declared or streamed, comes back whole.
- A body still arriving past the per-fetch deadline gives None, and so does one that would finish inside that deadline but is still arriving when the request's budget runs out mid-read; seven 1 s chunks come back whole; a fetch whose budget is already spent gives None and opens nothing, while the same fetch with budget left reads `https://<host><path>` and returns the body.

For the fetch, the instance is stood in for at `internal_translate.build_opener`: the module's own handlers go into a real urllib opener whose only fake part is the http/https open step, so urllib's real redirect and error processing run. That step serves scripted responses whose body reads advance a monotonic clock, which stands in for `time.monotonic`.

Gate (`handle_internal_translate`, `fetch_bounded` recording every fetch):

- An unknown id, and a known uuid on a host it does not belong to, each answer exactly `404 {"error": "Video not found"}` with no fetch; the same server then fetches twice for the video that resolves.
- A video whose host is in the denylist, stored as `DENIED.EXAMPLE` and active, answers the same 404 with no fetch. With the row inactive the same request answers `ready`, fetched from `denied.example`, and stores a row; active again, it answers 404 with no further fetch, so the stored track is not served either.

Store (subtitles.db opened with `connect_subtitles_db` and `ensure_subtitles_schema`, as server.py does):

- A miss for uuid `u-1` requested as host `PEER.Example.` answers `ready` with the two cues the track parses to, sorted, markup stripped; both fetches (caption list and track) go to the row's `peer.example`.
- It stores exactly one row: `v-1` (the row's canonical id, not the requested uuid), `peer.example`, `en`, `ready`, `instance`, the original track text, and cues_json that loads to those cues with no whitespace.
- A fresh connection to that file answers the same cues by uuid and by canonical id with no further fetch; a server over an empty subtitles file fetches again, so those answers came from the file.
- No en track, a track with two-digit milliseconds, a failed caption-list fetch and a failed track fetch each answer exactly `{"state": "none", "available": false}` after fetching the caption list, and leave the table empty.

Job state (`handle_internal_translate`, the wall clock pinned at the module's `now_ms`, rows written by the store's own writers):

- For a key with no row, `available` is true for a beat 0 ms and 15 000 ms old, and false for no beat, a beat 15 001 ms old and a beat 1 ms ahead. A closed store answers `none` with `available` false, where the same server answers true once its store is back.
- Each of ten branches (no row, ready, queued, running, failed, already_english, a ready row whose cues do not load; failed, already_english and no row each with and without an instance track) answers exactly its state, its cues and `total` where it has them, and `available` true with a fresh beat and false with none. Ready, queued and running rows answer from the store with no fetch even when the instance holds a track; failed and already_english rows answer their state after a fetch finds no track, and `ready` with the instance cues when it finds one; a ready row whose cues do not load answers `none` after the fetch.
- A running key stored out of start order answers its stored cues from `after` on, in stored order, with `total` 3, for `after` absent, 0, 1, 3 and 5, and fetches nothing; once that job is failed the same server fetches the caption list. A running key whose cues_json is unset, `[]`, not JSON or not a list answers no cues and `total` 0 with no fetch; once that job is failed the same server fetches.
- `after` given as true, false, -1, "1", null or 1.0 answers 400 with an error and no fetch for a running, a failed and an unrowed key, where `after` 1 answers 200 and the failed and unrowed keys then fetch the caption list; the same values for an unknown video answer exactly 404 `Video not found` with no fetch.

Enqueue (`handle_internal_translate_enqueue`, the same harness and pinned clock):

- With no beat, a beat 15 001 ms old, a beat 1 ms ahead, and a closed store under a fresh beat, the answer is exactly `{"state": "none", "available": false}` and subtitles.db holds no row; the same server then queues once a fresh beat is written or the store is back.
- With a beat 0 ms or 15 000 ms old, uuid `u-1` requested as `PEER.Example.` answers exactly `{"state": "queued", "available": true}` and stores one row, under canonical `v-1` and `peer.example`: `en`, `queued`, source `whisper`, fetched_at and queued_at now, attempts 0, every other column unset. A key already `queued`, `running`, `ready`, `failed` or `already_english` answers exactly that state with `available` true and leaves its row byte for byte as it was, with no second row. With `SUBTITLE_QUEUE_CAP` other keys queued it answers exactly `{"state": "busy", "available": true}` and stores nothing; with one fewer the same server queues it.
- A store error from the enqueue itself (the subtitles table moved away under a fresh beat) answers 503 with an `error` and stores nothing; with the table back the same request queues.
- Invalid JSON, a JSON array, a missing id, a blank host, a numeric id, an invalid host, an unknown video and a known uuid on another host each answer the literal 400 or 404 the state route gives for the same body, with a fresh beat and no row stored; an actively denylisted host answers 404 `Video not found` from both routes and stores nothing, and queues once its denylist row is inactive.

Startup: server.py run with `DEFAULT_SUBTITLES_DB_PATH` overridden to a missing file answers health, has created that file with a `subtitles` table, answers `/internal/translate` and `/internal/translate/enqueue` with the token for an unknown video `404 Video not found` (an Engine without the route answers `404 Not found`), and each without the token 401.

For the handler, the instance is stood in for at `internal_translate.fetch_bounded`, so the real caption pick and WebVTT parse run; the server is a `SimpleNamespace` over a temporary whitelist.db (videos, channels, instance_denylist) and a temporary subtitles.db, and the handler gets a stand-in for the stdlib request handler so the real body reader and responder run. Stored rows are read back through a separate read-only connection.
"""
from __future__ import annotations

import fcntl
import importlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.request import HTTPHandler, HTTPSHandler, Request

import pytest
from conftest import ENGINE_PY, ENGINE_START_LOCK

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
for _path in (SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from server_config import SUBTITLE_QUEUE_CAP  # noqa: E402

HOST = "peer.example"
TRACK_PATH = "/lazy-static/video-captions/en.vtt"
TRACK_URL = f"https://{HOST}{TRACK_PATH}"
# Brackets "2 MB" whichever way it is counted: 2,000,000 bytes is inside it, one byte past 2 MiB is over it.
WITHIN_CAP = 2_000_000
OVER_CAP = 2 * 1024 * 1024 + 1
CHUNK = 65_536
REFUSED_TARGETS = {
    "off-host": "https://evil.example/track.vtt",
    "host-prefixed lookalike": "https://peer.example.evil.example/track.vtt",
    "http": "http://peer.example/track.vtt",
    "ported": "https://peer.example:8443/track.vtt",
    "userinfo": "https://user@peer.example/track.vtt",
}
WELL_FORMED = (
    "\ufeffWEBVTT - Instance captions\r\n"
    "\r\n"
    "NOTE translated by the channel\r\n"
    "spanning a second line\r\n"
    "\r\n"
    "STYLE\r\n"
    "::cue { color: yellow }\r\n"
    "\r\n"
    "REGION\r\n"
    "id:bottom width:40%\r\n"
    "\r\n"
    "cue-2\r\n"
    "00:00:05.500 --> 00:00:07.250 align:start line:90%\r\n"
    "Second line\r\n"
    "\r\n"
    "01:02:03.004 --> 01:02:04.000\r\n"
    "An hour in\r\n"
    "\r\n"
    "00:10.000 --> 00:10.000\r\n"
    "Instant\r\n"
    "\r\n"
    "00:01.000 --> 00:02.000\r\n"
    "First line\r\n"
)
GOOD = "WEBVTT\n\n00:01.000 --> 00:02.000\nKept\n"
REJECTED = {
    "no header": "00:01.000 --> 00:02.000\nKept\n",
    "WEBVTTX header": "WEBVTTX\n\n00:01.000 --> 00:02.000\nKept\n",
    "blank line before the header": "\n" + GOOD,
    "two-digit milliseconds": GOOD + "\n00:03.00 --> 00:04.000\nBad\n",
    "minutes of 60": GOOD + "\n00:60:00.000 --> 00:60:01.000\nBad\n",
    "end before start": GOOD + "\n00:05.000 --> 00:04.999\nBad\n",
    "identifier containing -->": GOOD + "\nid --> x\n00:03.000 --> 00:04.000\nBad\n",
    "identifier with no timing": GOOD + "\ncue-9\nNo timing line\n",
    "stray block": GOOD + "\nStray text\n",
}
NO_TEXT = {
    "header only": "WEBVTT\n",
    "header and a NOTE": "WEBVTT\n\nNOTE nothing to show\n",
    "cues with no text": "WEBVTT\n\n00:01.000 --> 00:02.000\n\n00:03.000 --> 00:04.000\n",
    "markup only": "WEBVTT\n\n00:01.000 --> 00:02.000\n<i> </i>\n",
}
# Each refused listing entry beside the entry that differs only in pointing on the host as `en`, which picks TRACK_PATH.
PICK_REFUSED = {
    **{name: ({"language": {"id": "en"}, "fileUrl": target}, {"language": {"id": "en"}, "fileUrl": TRACK_URL}) for name, target in REFUSED_TARGETS.items()},
    "protocol-relative captionPath": ({"language": {"id": "en"}, "captionPath": "//evil.example/track.vtt"}, {"language": {"id": "en"}, "captionPath": TRACK_PATH}),
    "no en track": ({"language": {"id": "fr"}, "captionPath": TRACK_PATH}, {"language": {"id": "en"}, "captionPath": TRACK_PATH}),
}

ENGINE_SERVER = API_DIR / "server.py"
BRIDGE_TOKEN = "translate-bridge-token"
HEALTHY_WITHIN_SECONDS = 120
STOP_WITHIN_SECONDS = 30
THRESHOLD = 3
DENIED_HOST = "denied.example"
# (video_id, video_uuid, instance_domain): the uuid differs from the id, so a row keyed on the request id instead of the canonical one shows.
PEER_VIDEO = ("v-1", "u-1", HOST)
DENIED_VIDEO = ("d-1", "du-1", DENIED_HOST)
TRACK = "WEBVTT\n\n00:03.000 --> 00:04.000\n<i>World</i>\n\n00:01.000 --> 00:02.500\nHello\n"
# TRACK parsed: sorted by start, markup stripped. No text holds a space, so any space in the stored cues_json is padding.
CUES = [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3.0, "end": 4.0, "text": "World"}]
VIDEO_NOT_FOUND = [[404, {"error": "Video not found"}]]
# The test store has the heartbeat table and no beat unless a test writes one, so these answers read generation as not available; NONE is also what the enqueue route answers with no serving worker.
NONE = [[200, {"state": "none", "available": False}]]
READY = [[200, {"state": "ready", "cues": CUES, "available": False}]]
EN_LISTING = json.dumps({"total": 1, "data": [{"language": {"id": "en", "label": "English"}, "captionPath": TRACK_PATH}]}).encode("utf-8")
FR_LISTING = json.dumps({"total": 1, "data": [{"language": {"id": "fr", "label": "French"}, "captionPath": "/lazy-static/video-captions/fr.vtt"}]}).encode("utf-8")
# Each way the instance answers `none`: what its caption list and its track fetch return (None is a failed fetch).
NONE_PATHS = {
    "no en track": (FR_LISTING, TRACK.encode("utf-8")),
    "track fails to parse": (EN_LISTING, b"WEBVTT\n\n00:01.00 --> 00:02.000\nTwo-digit milliseconds\n"),
    "caption list fetch failed": (None, TRACK.encode("utf-8")),
    "track fetch failed": (EN_LISTING, None),
}


class Clock:
    """The monotonic clock the fetch reads; it moves only when a scripted body read says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Response:
    """One instance response as urllib's http(s) open step hands it on: status, headers, and a body that arrives one scripted chunk per read, each read moving the clock."""

    def __init__(self, url: str, status: int, headers: dict[str, str], chunks: list[bytes], clock: Clock, seconds_per_chunk: float) -> None:
        self.url = url
        self.code = self.status = status
        self.msg = "Scripted"
        self.headers = HTTPMessage()
        for name, value in headers.items():
            self.headers[name] = value
        self.chunks = list(chunks)
        self.clock = clock
        self.seconds_per_chunk = seconds_per_chunk
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
        self.clock.now += self.seconds_per_chunk
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


class ScriptedInstance:
    """The scripted instance behind `build_opener`: answers each URL from its routes (404 for any other) and records every URL opened, in order."""

    def __init__(self, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = clock
        self.monkeypatch = monkeypatch
        self.routes: dict[str, tuple] = {}
        self.opened: list[str] = []
        self.responses: list[Response] = []

    def serve(self, url: str, status: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None, seconds_per_chunk: float = 0.0) -> None:
        self.routes[url] = (status, headers or {}, chunks or [], seconds_per_chunk)

    def open(self, req: Request) -> Response:
        self.opened.append(req.full_url)
        status, headers, chunks, seconds_per_chunk = self.routes.get(req.full_url, (404, {}, [], 0.0))
        response = Response(req.full_url, status, headers, chunks, self.clock, seconds_per_chunk)
        self.responses.append(response)
        return response

    def build_opener(self, *handlers: object) -> urllib.request.OpenerDirector:
        scripted = self

        class InstanceHTTPS(HTTPSHandler):
            def https_open(self, req: Request) -> Response:
                return scripted.open(req)

        class InstanceHTTP(HTTPHandler):
            def http_open(self, req: Request) -> Response:
                return scripted.open(req)

        return urllib.request.build_opener(InstanceHTTPS(), InstanceHTTP(), *[handler for handler in handlers if not _socket_handler(handler)])


def _socket_handler(handler: object) -> bool:
    """Whether a handler build_opener was given opens connections itself, so it must give way to the scripted instance."""
    kind = handler if isinstance(handler, type) else type(handler)
    return issubclass(kind, (HTTPHandler, HTTPSHandler))


def _translate(instance: ScriptedInstance | None = None) -> ModuleType:
    """The module under test, imported inside each test so that a missing module fails each test instead of stopping collection; given an instance, the module's build_opener opens through it."""
    module = importlib.import_module("handlers.internal_translate")
    if instance is not None:
        instance.monkeypatch.setattr(module, "build_opener", instance.build_opener)
    return module


@pytest.fixture
def scripted_instance(monkeypatch) -> ScriptedInstance:
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    return ScriptedInstance(clock, monkeypatch)


def _body(size: int) -> list[bytes]:
    data = bytes(i % 251 for i in range(size))
    return [data[i:i + CHUNK] for i in range(0, size, CHUNK)]


def _listing(*entries: dict) -> bytes:
    return json.dumps({"total": len(entries), "data": list(entries)}).encode("utf-8")


def test_well_formed_track_parses_to_plain_text_cues_sorted_by_start():
    internal_translate = _translate()
    cues = internal_translate.parse_webvtt(WELL_FORMED)
    assert [c["text"] for c in cues] == ["First line", "Second line", "Instant", "An hour in"]
    assert [c["start"] for c in cues] == pytest.approx([1.0, 5.5, 10.0, 3723.004])
    assert [c["end"] for c in cues] == pytest.approx([2.0, 7.25, 10.0, 3724.0])
    assert all(set(c) == {"start", "end", "text"} and isinstance(c["start"], float) and isinstance(c["end"], float) for c in cues), cues


def test_markup_is_stripped_and_entities_decoded_to_plain_text():
    internal_translate = _translate()
    cues = internal_translate.parse_webvtt("WEBVTT\n\n00:01.000 --> 00:02.000\n<b>x</b>&lt;i&gt;\n")
    assert [c["text"] for c in cues] == ["x<i>"]


@pytest.mark.parametrize("track", REJECTED.values(), ids=REJECTED.keys())
def test_any_failing_part_rejects_the_whole_track(track):
    internal_translate = _translate()
    assert [c["text"] for c in internal_translate.parse_webvtt(GOOD)] == ["Kept"]
    assert internal_translate.parse_webvtt(track) is None


@pytest.mark.parametrize("track", NO_TEXT.values(), ids=NO_TEXT.keys())
def test_a_track_with_no_cue_text_is_none(track):
    internal_translate = _translate()
    assert [c["text"] for c in internal_translate.parse_webvtt(GOOD)] == ["Kept"]
    assert internal_translate.parse_webvtt(track) is None


def test_caption_pick_takes_the_first_exact_en_track():
    internal_translate = _translate()
    listing = _listing(
        {"language": {"id": "en-US", "label": "English (US)"}, "captionPath": "/lazy-static/video-captions/us.vtt"},
        {"language": {"id": "fr", "label": "French"}, "captionPath": "/lazy-static/video-captions/fr.vtt"},
        {"language": {"id": "en", "label": "English"}, "captionPath": "/lazy-static/video-captions/en-1.vtt"},
        {"language": {"id": "en", "label": "English"}, "captionPath": "/lazy-static/video-captions/en-2.vtt"},
    )
    assert internal_translate.pick_english_track_path(listing, HOST) == "/lazy-static/video-captions/en-1.vtt"


@pytest.mark.parametrize("entry, on_host", PICK_REFUSED.values(), ids=PICK_REFUSED.keys())
def test_caption_pick_refuses_anything_off_the_host(entry, on_host):
    internal_translate = _translate()
    assert internal_translate.pick_english_track_path(_listing(on_host), HOST) == TRACK_PATH
    assert internal_translate.pick_english_track_path(_listing(entry), HOST) is None


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_handler_follows_a_same_host_https_target(code):
    internal_translate = _translate()
    target = f"https://{HOST}/lazy-static/video-captions/moved.vtt"
    new = internal_translate.SameHostRedirectHandler(HOST).redirect_request(Request(TRACK_URL), None, code, "Moved", HTTPMessage(), target)
    assert isinstance(new, Request) and new.full_url == target


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_redirect_handler_refuses_an_off_host_or_non_https_target(target):
    internal_translate = _translate()
    handler = internal_translate.SameHostRedirectHandler(HOST)
    same_host = f"https://{HOST}/lazy-static/video-captions/moved.vtt"
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), same_host).full_url == same_host
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), target) is None


@pytest.mark.parametrize("location", [f"https://{HOST}/moved/en.vtt", "/moved/en.vtt"], ids=["absolute", "relative"])
def test_fetch_follows_a_same_host_redirect(scripted_instance, location):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, status=302, headers={"Location": location})
    scripted_instance.serve(f"https://{HOST}/moved/en.vtt", chunks=[b"WEBVTT\n"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) == b"WEBVTT\n"
    assert scripted_instance.opened == [TRACK_URL, f"https://{HOST}/moved/en.vtt"]


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_fetch_refuses_an_off_host_or_non_https_redirect(scripted_instance, target):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, status=302, headers={"Location": target})
    scripted_instance.serve(target, chunks=[b"LEAKED"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) is None
    assert scripted_instance.opened == [TRACK_URL]


def test_fetch_refuses_a_declared_length_over_the_cap_without_reading(scripted_instance):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, headers={"Content-Length": str(OVER_CAP)}, chunks=_body(OVER_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) is None
    assert [response.reads for response in scripted_instance.responses] == [0]


def test_fetch_refuses_a_body_streamed_past_the_cap(scripted_instance):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=_body(OVER_CAP))
    scripted_instance.serve(f"https://{HOST}/within.vtt", chunks=_body(WITHIN_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) is None
    assert scripted_instance.opened == [TRACK_URL]
    assert internal_translate.fetch_bounded(HOST, "/within.vtt", scripted_instance.clock.now + 1000) == b"".join(_body(WITHIN_CAP))


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "streamed"])
def test_fetch_returns_a_body_of_2_000_000_bytes_whole(scripted_instance, declared):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, headers={"Content-Length": str(WITHIN_CAP)} if declared else {}, chunks=_body(WITHIN_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) == b"".join(_body(WITHIN_CAP))


# The request-budget body is five 1 s chunks, inside the per-fetch deadline that seven 1 s chunks show is not exceeded, so only the budget can refuse it. Each refused fetch sits beside an on-time one that differs in one thing: two chunks instead of ten, or a far budget instead of 2 s.
@pytest.mark.parametrize("seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds", [(3.0, 10, 1000.0, 2, 1000.0), (1.0, 5, 2.0, 5, 1000.0)], ids=["per-fetch deadline", "request budget"])
def test_fetch_refuses_a_body_still_arriving_past_its_deadline(scripted_instance, seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(f"https://{HOST}/on-time.vtt", chunks=[f"c{i}".encode() for i in range(on_time_chunk_count)], seconds_per_chunk=seconds_per_chunk)
    scripted_instance.serve(TRACK_URL, chunks=[f"c{i}".encode() for i in range(chunk_count)], seconds_per_chunk=seconds_per_chunk)
    assert internal_translate.fetch_bounded(HOST, "/on-time.vtt", scripted_instance.clock.now + on_time_budget_seconds) == b"".join(f"c{i}".encode() for i in range(on_time_chunk_count))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + budget_seconds) is None
    assert scripted_instance.opened == [f"https://{HOST}/on-time.vtt", TRACK_URL]


def test_fetch_returns_a_body_finished_inside_its_deadline(scripted_instance):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[f"c{i}".encode() for i in range(7)], seconds_per_chunk=1.0)
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) == b"c0c1c2c3c4c5c6"


def test_fetch_with_its_budget_spent_opens_nothing(scripted_instance):
    internal_translate = _translate(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now - 1) is None
    assert scripted_instance.opened == []
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, scripted_instance.clock.now + 1000) == b"WEBVTT\n"
    assert scripted_instance.opened == [TRACK_URL]


class HandlerRequest:
    """The parts of a BaseHTTPRequestHandler that http_utils reads and writes: each send_response opens a [status, payload] response."""

    def __init__(self, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"content-length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.responses: list[list] = []
        self.wfile = SimpleNamespace(write=lambda data: self.responses[-1].append(json.loads(data)))

    def send_response(self, status: int) -> None:
        self.responses.append([status])

    def send_header(self, name: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


class RecordingInstance:
    """The video instances as `fetch_bounded` reaches them: each (host, path) answers its served bytes, any other None, and every fetch is recorded in order."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], bytes | None] = {}
        self.fetched: list[tuple[str, str]] = []

    def serve(self, video: tuple[str, str, str], listing: bytes | None, track: bytes | None) -> None:
        _, uuid, host = video
        self.routes[(host, f"/api/v1/videos/{uuid}/captions")] = listing
        self.routes[(host, TRACK_PATH)] = track

    def fetch_bounded(self, host: str, path: str, budget_at: float) -> bytes | None:
        self.fetched.append((host, path))
        return self.routes.get((host, path))

    def hosts(self) -> list[str]:
        return [host for host, _ in self.fetched]


def _handler_module(instance: RecordingInstance, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The handler module, imported inside each test so that a missing module fails each test on its own; its fetch reaches the recording instance."""
    module = importlib.import_module("handlers.internal_translate")
    monkeypatch.setattr(module, "fetch_bounded", instance.fetch_bounded)
    return module


def _whitelist(path: Path) -> sqlite3.Connection:
    """A whitelist.db holding PEER_VIDEO and DENIED_VIDEO, with an inactive denylist row for DENIED_HOST stored uppercase."""
    from data.moderation import ensure_moderation_schema

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, instance_domain TEXT, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, embed_path TEXT, published_at TEXT, video_url TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, tags_json TEXT, category TEXT, nsfw INTEGER, language TEXT, duration INTEGER, thumbnail_url TEXT, last_checked_at TEXT, error_count INTEGER, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, channel_name TEXT, display_name TEXT, followers_count INTEGER, avatar_url TEXT)")
    ensure_moderation_schema(conn)
    for video_id, uuid, host in (PEER_VIDEO, DENIED_VIDEO):
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, title, error_count) VALUES (?, ?, ?, ?, 0)", (video_id, uuid, host, f"title:{video_id}"))
    conn.execute("INSERT INTO instance_denylist (host, is_active, created_at, updated_at) VALUES (?, 0, 0, 0)", (DENIED_HOST.upper(),))
    conn.commit()
    return conn


def _set_denied(whitelist: sqlite3.Connection, active: bool) -> None:
    whitelist.execute("UPDATE instance_denylist SET is_active = ? WHERE host = ?", (int(active), DENIED_HOST.upper()))
    whitelist.commit()


def _subtitles_db(path: Path) -> sqlite3.Connection:
    """The subtitles store as server.py opens it at startup."""
    from data.subtitles import connect_subtitles_db, ensure_subtitles_schema

    conn = connect_subtitles_db(path)
    ensure_subtitles_schema(conn)
    return conn


def _server(whitelist: sqlite3.Connection, subtitles_path: Path) -> SimpleNamespace:
    """The server attributes the handler reads, over a fresh connection to the subtitles file at `subtitles_path`."""
    return SimpleNamespace(db=whitelist, db_lock=threading.Lock(), video_error_threshold=THRESHOLD, subtitles_db=_subtitles_db(subtitles_path), subtitles_db_lock=threading.Lock(), statement_timeout_seconds=5.0)


def _handle(module: ModuleType, server: SimpleNamespace, body: dict) -> list[list]:
    request = HandlerRequest(body)
    module.handle_internal_translate(request, server)
    return request.responses


def _stored(subtitles_path: Path) -> list[tuple]:
    """Every subtitles row, read through a separate read-only connection."""
    conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT video_id, instance_domain, target_language, state, source, track_text, cues_json FROM subtitles ORDER BY video_id").fetchall()
    finally:
        conn.close()


@pytest.fixture
def whitelist(tmp_path) -> sqlite3.Connection:
    conn = _whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


@pytest.fixture
def recording_instance() -> RecordingInstance:
    instance = RecordingInstance()
    instance.serve(PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    instance.serve(DENIED_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    return instance


def test_an_unknown_video_is_404_video_not_found_with_no_fetch(tmp_path, whitelist, recording_instance, monkeypatch):
    internal_translate = _handler_module(recording_instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, {"id": "no-such-video", "host": HOST}) == VIDEO_NOT_FOUND
    assert _handle(internal_translate, server, {"id": PEER_VIDEO[1], "host": "other.example"}) == VIDEO_NOT_FOUND  # a known id on a host it does not belong to
    assert recording_instance.fetched == []
    # Control: the same server and instance fetch for a video that resolves, so the empty list above is the gate's doing.
    assert _handle(internal_translate, server, {"id": PEER_VIDEO[1], "host": HOST}) == READY
    assert recording_instance.hosts() == [HOST, HOST]


def test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track(tmp_path, whitelist, recording_instance, monkeypatch):
    internal_translate = _handler_module(recording_instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = {"id": DENIED_VIDEO[1], "host": DENIED_HOST}
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND  # denylist row stored as DENIED.EXAMPLE
    assert recording_instance.fetched == []
    # Control: with the row inactive the same request fetches from the video's host and stores a ready track.
    _set_denied(whitelist, False)
    assert _handle(internal_translate, server, body) == READY
    assert recording_instance.hosts() == [DENIED_HOST, DENIED_HOST]
    assert [row[:2] for row in _stored(tmp_path / "subtitles.db")] == [DENIED_VIDEO[::2]]
    # Denied again, the stored track is not served and nothing more is fetched: the denylist is checked before the store and the network.
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND
    assert recording_instance.hosts() == [DENIED_HOST, DENIED_HOST]


def test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_from_subtitles_db_without_a_fetch(tmp_path, whitelist, recording_instance, monkeypatch):
    internal_translate = _handler_module(recording_instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    # The request host differs from the row's `peer.example` in case and a trailing dot, so fetching the request host would show.
    body = {"id": PEER_VIDEO[1], "host": "PEER.Example."}
    assert _handle(internal_translate, _server(whitelist, subtitles_path), body) == READY
    assert recording_instance.hosts() == [HOST, HOST]  # the caption list and the track, both from the row's instance_domain
    (row,) = _stored(subtitles_path)
    # Keyed on the row's canonical video_id `v-1`, not the requested uuid `u-1`; the original track text, markup and order included.
    assert row[:6] == ("v-1", HOST, "en", "ready", "instance", TRACK)
    assert json.loads(row[6]) == CUES
    assert " " not in row[6] and "\n" not in row[6], row[6]  # compact
    # A fresh connection to the same file, as after a restart: the uuid request and the canonical-id request both answer the stored cues with no fetch.
    reopened = _server(whitelist, subtitles_path)
    assert _handle(internal_translate, reopened, body) == READY
    assert _handle(internal_translate, reopened, {"id": PEER_VIDEO[0], "host": HOST}) == READY
    assert len(recording_instance.fetched) == 2
    # Control: a server over an empty subtitles file fetches again, so the answers above came from what subtitles.db holds, not from process memory.
    assert _handle(internal_translate, _server(whitelist, tmp_path / "empty-subtitles.db"), body) == READY
    assert recording_instance.hosts() == [HOST] * 4


@pytest.mark.parametrize("listing, track", NONE_PATHS.values(), ids=NONE_PATHS.keys())
def test_each_none_path_answers_none_and_stores_nothing(tmp_path, whitelist, monkeypatch, listing, track):
    instance = RecordingInstance()
    instance.serve(PEER_VIDEO, listing, track)
    internal_translate = _handler_module(instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    assert _handle(internal_translate, _server(whitelist, subtitles_path), {"id": PEER_VIDEO[1], "host": HOST}) == NONE
    assert instance.fetched[0] == (HOST, f"/api/v1/videos/{PEER_VIDEO[1]}/captions")  # control: the answer came from the instance, past the gate
    assert _stored(subtitles_path) == []


VIDEO_ID, VIDEO_UUID = PEER_VIDEO[:2]
BODY = {"id": VIDEO_UUID, "host": HOST}
CAPTIONS = (HOST, f"/api/v1/videos/{VIDEO_UUID}/captions")
TRACK_FETCHES = [CAPTIONS, (HOST, TRACK_PATH)]
# The wall clock is a system boundary: pinned, a beat's age is exact, so the 0 and 15 000 ms edges are tested without a race against the real clock, and so is the queued_at the enqueue route writes.
NOW = 1_760_000_000_000
# Stored in chunk order, not start order, so an answer that re-sorts the running cues shows.
RUNNING = [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}]
# Differs from CUES (the instance track), so a stored ready answer that was fetched instead shows.
STORED_READY = [{"start": 7.0, "end": 8.0, "text": "Stored"}]
BAD_AFTER = {"true": True, "false": False, "negative": -1, "string": "1", "null": None, "float": 1.0}
QUEUED = [[200, {"state": "queued", "available": True}]]
# Every subtitles column, in table order, of the row a new key leaves.
QUEUED_ROW = (VIDEO_ID, HOST, "en", "queued", "whisper", NOW, None, None, NOW, None, None, None, None, 0)
MISSING = [[400, {"error": "Missing id or host"}]]
INVALID_JSON = [[400, {"error": "Invalid JSON body"}]]


def _instance(track: bool) -> RecordingInstance:
    """The video's instance: a caption list whose en track parses to CUES, or one with no en entry."""
    instance = RecordingInstance()
    instance.serve(PEER_VIDEO, EN_LISTING if track else FR_LISTING, TRACK.encode("utf-8") if track else None)
    return instance


def _route(instance: RecordingInstance, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The handler module with its fetch reaching `instance` and its clock pinned at NOW."""
    module = _handler_module(instance, monkeypatch)
    monkeypatch.setattr(module, "now_ms", lambda: NOW)
    return module


def _damage(store: sqlite3.Connection, cues_json: str) -> None:
    """Overwrite the key's cues_json by hand, as only a damaged file would hold it."""
    with store:
        store.execute("UPDATE subtitles SET cues_json = ? WHERE video_id = ?", (cues_json, VIDEO_ID))


def _claimed(store: sqlite3.Connection) -> int:
    """Queue and claim the key's job; its started_at."""
    from data.subtitles import claim_translate_job, enqueue_translate_job

    enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000)
    return claim_translate_job(store, "en", NOW - 1000)["started_at"]


def _seed(store: sqlite3.Connection, row: str) -> None:
    """Leave the key in one stored state, written by the store's own writers."""
    from data.subtitles import enqueue_translate_job, finish_translate_already_english, finish_translate_failed, store_ready_subtitles, store_running_cues

    if row == "ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", "WEBVTT stored", STORED_READY, NOW - 1000)
    elif row == "corrupt ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", "WEBVTT stored", STORED_READY, NOW - 1000)
        _damage(store, "{not json")
    elif row == "queued":
        enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000)
    elif row == "running":
        assert store_running_cues(store, VIDEO_ID, HOST, "en", _claimed(store), RUNNING, "fr")
    elif row == "failed":
        assert finish_translate_failed(store, VIDEO_ID, HOST, "en", _claimed(store), "boom", NOW - 500)
    elif row == "already_english":
        assert finish_translate_already_english(store, VIDEO_ID, HOST, "en", _claimed(store), "en", NOW - 500)
    else:
        assert row == "no row", row


def _beat(subtitles_path: Path, age: int | None) -> None:
    """Write the worker's heartbeat age ms before NOW (negative is ahead of it); None writes none."""
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(subtitles_path)
    if age is not None:
        write_translate_heartbeat(store, NOW - age, 1)
    store.close()


def _rows(subtitles_path: Path) -> list[tuple]:
    """Every subtitles row, every column, read through a separate read-only connection."""
    conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT * FROM subtitles ORDER BY video_id, instance_domain").fetchall()
    finally:
        conn.close()


def _write(subtitles_path: Path, sql: str) -> None:
    """One statement through a plain connection of its own, as another process would run it."""
    conn = sqlite3.connect(subtitles_path)
    try:
        with conn:
            conn.execute(sql)
    finally:
        conn.close()


def _request(body: dict | bytes) -> HandlerRequest:
    """A request carrying body as JSON, or as these raw bytes."""
    request = HandlerRequest(body if isinstance(body, dict) else {})
    if isinstance(body, bytes):
        request.rfile = io.BytesIO(body)
        request.headers = {"content-length": str(len(body))}
    return request


def _enqueue(module: ModuleType, server: SimpleNamespace, body: dict | bytes) -> list[list]:
    request = _request(body)
    module.handle_internal_translate_enqueue(request, server)
    return request.responses


def _state(module: ModuleType, server: SimpleNamespace, body: dict | bytes) -> list[list]:
    request = _request(body)
    module.handle_internal_translate(request, server)
    return request.responses


# Age in ms of the beat at answer time; negative is a beat dated ahead of now.
BEATS = {"no beat": (None, False), "0 ms old": (0, True), "15 000 ms old": (15_000, True), "15 001 ms old": (15_001, False), "1 ms ahead": (-1, False)}


@pytest.mark.parametrize("age, available", BEATS.values(), ids=BEATS.keys())
def test_available_is_true_only_for_a_heartbeat_0_to_15000_ms_old(tmp_path, whitelist, monkeypatch, age, available):
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    if age is not None:
        write_translate_heartbeat(store, NOW - age, 1)
    internal_translate = _route(_instance(False), monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), BODY) == [[200, {"state": "none", "available": available}]]


def test_a_closed_store_answers_none_and_not_available(tmp_path, whitelist, monkeypatch):
    from data.subtitles import write_translate_heartbeat

    write_translate_heartbeat(_subtitles_db(tmp_path / "subtitles.db"), NOW, 1)
    internal_translate = _route(_instance(False), monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    open_store = server.subtitles_db
    server.subtitles_db = None  # as server.py leaves it at shutdown
    assert _handle(internal_translate, server, BODY) == NONE
    # Control: the same server reads the fresh beat once its store is back, so the false above is the closed store's doing.
    server.subtitles_db = open_store
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "none", "available": True}]]


# (stored row, instance holds a track, the answer without `available`, the instance fetches).
BRANCHES = {
    "no row, no track": ("no row", False, {"state": "none"}, [CAPTIONS]),
    "no row, instance track": ("no row", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "ready": ("ready", True, {"state": "ready", "cues": STORED_READY}, []),
    "queued": ("queued", True, {"state": "queued"}, []),
    "running": ("running", True, {"state": "running", "cues": RUNNING, "total": 3}, []),
    "failed, no track": ("failed", False, {"state": "failed"}, [CAPTIONS]),
    "failed, instance track": ("failed", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "already_english, no track": ("already_english", False, {"state": "already_english"}, [CAPTIONS]),
    "already_english, instance track": ("already_english", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "ready with cues that do not load, no track": ("corrupt ready", False, {"state": "none"}, [CAPTIONS]),
}


@pytest.mark.parametrize("available", [True, False], ids=["fresh beat", "no beat"])
@pytest.mark.parametrize("row, track, answer, fetches", BRANCHES.values(), ids=BRANCHES.keys())
def test_each_stored_state_answers_its_state_with_available_and_fetches_only_past_queued_and_running(tmp_path, whitelist, monkeypatch, row, track, answer, fetches, available):
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    _seed(store, row)
    if available:
        write_translate_heartbeat(store, NOW, 1)
    instance = _instance(track)
    internal_translate = _route(instance, monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), BODY) == [[200, {**answer, "available": available}]]
    assert instance.fetched == fetches  # a stored queued or running job is answered with no fetch even with a track on the instance


# `after` (absent when None) and the running cues it answers, written out rather than sliced.
AFTERS = {
    "absent": (None, RUNNING),
    "0": (0, RUNNING),
    "1": (1, [{"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}]),
    "3, the total": (3, []),
    "5, past the total": (5, []),
}


@pytest.mark.parametrize("after, cues", AFTERS.values(), ids=AFTERS.keys())
def test_a_running_key_answers_its_cues_from_after_with_the_stored_total_and_no_fetch(tmp_path, whitelist, monkeypatch, after, cues):
    from data.subtitles import finish_translate_failed, store_running_cues, write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    started_at = _claimed(store)
    assert store_running_cues(store, VIDEO_ID, HOST, "en", started_at, RUNNING, "fr")
    write_translate_heartbeat(store, NOW, 1)
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = BODY if after is None else {**BODY, "after": after}
    assert _handle(internal_translate, server, body) == [[200, {"state": "running", "cues": cues, "total": 3, "available": True}]]
    assert instance.fetched == []
    # Control: the same server and instance fetch once the job has ended failed, so the empty list above is the running branch's doing.
    assert finish_translate_failed(store, VIDEO_ID, HOST, "en", started_at, "boom", NOW)
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": True}]]
    assert instance.fetched == TRACK_FETCHES


# What the running row's cues_json holds: never written (None), or written as this text.
ZERO_CUES = {"unset": None, "empty": "[]", "not JSON": "{not json", "not a list": '{"start": 1.0, "end": 2.0, "text": "x"}'}


@pytest.mark.parametrize("cues_json", ZERO_CUES.values(), ids=ZERO_CUES.keys())
def test_a_running_key_with_unset_empty_or_damaged_cues_answers_no_cues_and_total_0(tmp_path, whitelist, monkeypatch, cues_json):
    from data.subtitles import finish_translate_failed, write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    started_at = _claimed(store)
    if cues_json is not None:
        _damage(store, cues_json)
    write_translate_heartbeat(store, NOW, 1)
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "running", "cues": [], "total": 0, "available": True}]]
    assert instance.fetched == []
    # Control: the same server and instance fetch once the job has ended failed, so the empty list above is the running branch's doing.
    assert finish_translate_failed(store, VIDEO_ID, HOST, "en", started_at, "boom", NOW)
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": True}]]
    assert instance.fetched == TRACK_FETCHES


# Stored row, and what the instance fetches for it once `after` is valid: failed and no row would fetch, so a refusal checked only on the running branch shows.
REFUSED_ROWS = {"running": ("running", []), "failed": ("failed", [CAPTIONS]), "no row": ("no row", [CAPTIONS])}


@pytest.mark.parametrize("row, fetches", REFUSED_ROWS.values(), ids=REFUSED_ROWS.keys())
@pytest.mark.parametrize("after", BAD_AFTER.values(), ids=BAD_AFTER.keys())
def test_after_that_is_not_a_non_negative_json_int_answers_400(tmp_path, whitelist, monkeypatch, after, row, fetches):
    store = _subtitles_db(tmp_path / "subtitles.db")
    _seed(store, row)
    instance = _instance(False)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    (response,) = _handle(internal_translate, server, {**BODY, "after": after})
    assert response[0] == 400, response
    assert set(response[1]) == {"error"}, response
    assert instance.fetched == []
    # Control: the same request with a valid `after` is answered, and for failed and no row the same instance is fetched, so the empty list above is the refusal's doing.
    assert _handle(internal_translate, server, {**BODY, "after": 1})[0][0] == 200
    assert instance.fetched == fetches


@pytest.mark.parametrize("after", BAD_AFTER.values(), ids=BAD_AFTER.keys())
def test_an_unknown_video_with_a_bad_after_answers_404_video_not_found(tmp_path, whitelist, monkeypatch, after):
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), {"id": "no-such-video", "host": HOST, "after": after}) == VIDEO_NOT_FOUND
    assert instance.fetched == []


# Age in ms of the beat at request time; None is no beat, negative a beat dated ahead of now.
UNAVAILABLE_BEATS = {"no beat": None, "15 001 ms old": 15_001, "1 ms ahead": -1}


@pytest.mark.parametrize("age", UNAVAILABLE_BEATS.values(), ids=UNAVAILABLE_BEATS.keys())
def test_without_a_serving_worker_enqueue_answers_none_not_available_and_writes_no_row(tmp_path, whitelist, monkeypatch, age):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, age)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == NONE
    assert _rows(subtitles_path) == []
    # Control: the same server queues once a fresh beat is written, so the answer and the empty table above are the gate's doing.
    _beat(subtitles_path, 0)
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


def test_a_closed_store_enqueue_answers_none_not_available_and_writes_no_row(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    open_store = server.subtitles_db
    server.subtitles_db = None  # as server.py leaves it at shutdown
    assert _enqueue(internal_translate, server, BODY) == NONE
    assert _rows(subtitles_path) == []
    # Control: the same server, its store back, reads the fresh beat and queues.
    server.subtitles_db = open_store
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


FRESH_BEATS = {"0 ms old": 0, "15 000 ms old": 15_000}


@pytest.mark.parametrize("age", FRESH_BEATS.values(), ids=FRESH_BEATS.keys())
def test_with_a_serving_worker_a_new_key_is_queued_under_its_canonical_key(tmp_path, whitelist, monkeypatch, age):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, age)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    # The request host differs from the row's `peer.example` in case and a trailing dot, and the id is the uuid, so a row keyed on the request shows.
    assert _enqueue(internal_translate, _server(whitelist, subtitles_path), {"id": VIDEO_UUID, "host": "PEER.Example."}) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


@pytest.mark.parametrize("state", ["queued", "running", "ready", "failed", "already_english"])
def test_with_a_serving_worker_a_stored_key_answers_its_state_and_its_row_is_unchanged(tmp_path, whitelist, monkeypatch, state):
    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    _seed(store, state)
    store.close()
    _beat(subtitles_path, 0)
    before = _rows(subtitles_path)
    assert [row[:4] for row in before] == [(VIDEO_ID, HOST, "en", state)]  # control: the seeded row is the key in that state
    internal_translate = _route(RecordingInstance(), monkeypatch)
    assert _enqueue(internal_translate, _server(whitelist, subtitles_path), BODY) == [[200, {"state": state, "available": True}]]
    assert _rows(subtitles_path) == before  # never overwritten, no second row


def test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues(tmp_path, whitelist, monkeypatch):
    from data.subtitles import enqueue_translate_job

    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    # Other videos' jobs fill the queue; the store counts every queued row against the cap.
    for index in range(SUBTITLE_QUEUE_CAP):
        assert enqueue_translate_job(store, f"q-{index:03d}", HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 5000) == ("queued", "queued")
    store.close()
    _beat(subtitles_path, 0)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == [[200, {"state": "busy", "available": True}]]
    rows = _rows(subtitles_path)
    assert [row for row in rows if row[0] == VIDEO_ID] == []  # busy stores nothing
    assert len(rows) == SUBTITLE_QUEUE_CAP
    # One fewer queued job: the same server queues the key, so busy above came at exactly the cap.
    _write(subtitles_path, "DELETE FROM subtitles WHERE video_id = 'q-000'")
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert [row for row in _rows(subtitles_path) if row[0] == VIDEO_ID] == [QUEUED_ROW]


def test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    # The heartbeat table stays, so the gate reads a fresh beat and the enqueue itself raises `no such table: subtitles`.
    _write(subtitles_path, "ALTER TABLE subtitles RENAME TO subtitles_away")
    (response,) = _enqueue(internal_translate, server, BODY)
    assert response[0] == 503, response
    assert set(response[1]) == {"error"}, response
    _write(subtitles_path, "ALTER TABLE subtitles_away RENAME TO subtitles")
    assert _rows(subtitles_path) == []
    # Control: with the table back the same request queues.
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


# Each body both routes refuse, and the literal answer.
REFUSED = {
    "invalid JSON": (b"{not json", INVALID_JSON),
    "a JSON array": (b"[1, 2]", INVALID_JSON),
    "no id": ({"host": HOST}, MISSING),
    "blank host": ({"id": VIDEO_UUID, "host": "  "}, MISSING),
    "numeric id": ({"id": 1, "host": HOST}, MISSING),
    "invalid host": ({"id": VIDEO_UUID, "host": "not a host!"}, [[400, {"error": "Invalid host"}]]),
    "unknown video": ({"id": "no-such-video", "host": HOST}, VIDEO_NOT_FOUND),
    "known uuid on another host": ({"id": VIDEO_UUID, "host": "other.example"}, VIDEO_NOT_FOUND),
}


@pytest.mark.parametrize("body, answer", REFUSED.values(), ids=REFUSED.keys())
def test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does(tmp_path, whitelist, monkeypatch, body, answer):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, body) == answer
    assert _state(internal_translate, server, body) == answer  # the same answer the state route gives
    assert _rows(subtitles_path) == []
    # Control: the gate is open, so the same server queues a body that resolves.
    assert _enqueue(internal_translate, server, BODY) == QUEUED


def test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(RecordingInstance(), monkeypatch)
    server = _server(whitelist, subtitles_path)
    body = {"id": DENIED_VIDEO[1], "host": DENIED_HOST}
    _set_denied(whitelist, True)  # stored as DENIED.EXAMPLE
    assert _enqueue(internal_translate, server, body) == VIDEO_NOT_FOUND
    assert _state(internal_translate, server, body) == VIDEO_NOT_FOUND
    assert _rows(subtitles_path) == []
    # Control: with the denylist row inactive the same request queues the video under its own key.
    _set_denied(whitelist, False)
    assert _enqueue(internal_translate, server, body) == QUEUED
    assert [row[:4] for row in _rows(subtitles_path)] == [(DENIED_VIDEO[0], DENIED_HOST, "en", "queued")]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post(base: str, path: str, body: dict, headers: dict[str, str]) -> tuple[int, object]:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"), method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# Runs server.py as __main__ with `server_config` bound to the real file's module and the overrides set on it, as test_random_cache.py's CACHE_VARIANT_RUNNER does.
VARIANT_RUNNER = """
import importlib.util, json, os, runpy, sys
server, overrides = sys.argv[1], json.loads(sys.argv[2])
api = os.path.dirname(server)
sys.path.insert(0, api)
sys.path.insert(0, os.path.dirname(api))
spec = importlib.util.spec_from_file_location("server_config", os.path.join(api, "server_config.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name, value in overrides.items():
    setattr(module, name, value)
sys.modules["server_config"] = module
sys.argv = [server, *sys.argv[3:]]
runpy.run_path(server, run_name="__main__")
"""


def test_an_engine_start_creates_the_subtitles_table_at_its_configured_path_and_routes_internal_translate_and_its_enqueue_behind_the_bridge_gate(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    subtitles_path = tmp_path / "subtitles.db"
    assert not subtitles_path.exists()  # control: only the start can create it
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}
    log_path = tmp_path / "engine.log"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(subtitles_path)}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS
            while proc.poll() is None and time.time() < deadline and not healthy:
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                        healthy = resp.status == 200
                except OSError:
                    time.sleep(0.1)
    try:
        assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"
        assert subtitles_path.exists(), f"the Engine start did not create {subtitles_path}"
        conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
        assert "subtitles" in tables, tables
        # An Engine without the route falls through to 404 {"error": "Not found"}; this video and host resolve to no row, so the handler answers before any fetch.
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN}) == (404, {"error": "Video not found"})
        assert _post(base, "/internal/translate", {"id": "no-such-video", "host": "no-such-host.invalid"}, {}) == (401, {"error": "Unauthorized"})  # behind the bridge gate
        # The enqueue route likewise answers before the store for a video that resolves to no row.
        assert _post(base, "/internal/translate/enqueue", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN}) == (404, {"error": "Video not found"})
        assert _post(base, "/internal/translate/enqueue", {"id": "no-such-video", "host": "no-such-host.invalid"}, {}) == (401, {"error": "Unauthorized"})  # behind the bridge gate
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=STOP_WITHIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
