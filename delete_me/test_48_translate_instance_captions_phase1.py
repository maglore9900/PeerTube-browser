"""`engine/server/api/handlers/internal_translate.py`: an instance's English WebVTT track becomes plain-text cues sorted by start, or None for the whole track, and the bounded fetch answers None for anything outside the AC6 bounds. "translate" in this file's name is plan 48's build identifier (the Translate toggle); nothing here translates, because phase 1 only fetches and parses an English track the instance already has.

Parse (`parse_webvtt`):

- A CRLF track with a BOM, a `WEBVTT - title` header, NOTE/STYLE/REGION blocks, a cue identifier with cue settings, hours present and absent, a zero-length cue and cues out of order gives exactly four `{start, end, text}` cues, in start order 1.0, 5.5, 10.0, 3723.004, with float times and the identifier, settings and skipped blocks absent from the text.
- `<b>x</b>&lt;i&gt;` gives the text `x<i>`.
- With one good cue present, the whole track is None for: no header, a `WEBVTTX` header, a blank line before the header, two-digit milliseconds, minutes of 60, an end 1 ms before its start, an identifier containing `-->`, an identifier with no timing line, and a stray text block; the good cue alone parses.
- A header alone, a header with only a NOTE, cues with no text, and a cue of markup only each give None.

Caption pick (`pick_english_track_path`), the parser's input path: the first entry whose `language.id` is exactly `en` gives its `captionPath`, past `en-US`, `fr` and a second `en`; a `fileUrl` on the same host over https gives its path; a `fileUrl` off the host, a host-prefixed lookalike, http, an explicit port or userinfo, a protocol-relative `captionPath`, and a listing with no `en` track give None, while the same entry pointing on the host as `en` gives its path.

Fetch (`fetch_bounded`, and `SameHostRedirectHandler.redirect_request` called directly):

- The redirect handler returns a request for a same-host https target on 301, 302, 303, 307 and 308, and None for an off-host, host-prefixed lookalike, http, ported or userinfo target.
- A fetch reads `https://<host><path>` and returns its chunks joined; it follows a same-host redirect, absolute or relative, and returns the target's body; it returns None for a redirect to each refused target without ever requesting it.
- A declared `Content-Length` over 2 MB gives None with no body read; a body streamed past 2 MB with no length gives None; 2,000,000 bytes, declared or streamed, comes back whole.
- A body still arriving past the per-fetch deadline gives None, and so does one that would finish inside that deadline but is still arriving when the request's budget runs out mid-read; seven 1 s chunks come back whole; a fetch whose budget is already spent gives None and opens nothing, while the same fetch with budget left returns the body.

The instance is stood in for at `internal_translate.build_opener`: the module's own handlers go into a real urllib opener whose only fake part is the http/https open step, so urllib's real redirect and error processing run. That step serves scripted responses whose body reads advance a monotonic clock, which stands in for `time.monotonic`.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from types import ModuleType
from urllib.request import HTTPHandler, HTTPSHandler, Request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
for _path in (SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

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


class Instance:
    """The scripted instance: answers each URL from its routes (404 for any other) and records every URL opened, in order."""

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


def _translate(instance: Instance | None = None) -> ModuleType:
    """The module under test, imported inside each test so that before phase 1 every test fails on its absence instead of collection stopping; given an instance, the module's build_opener opens through it."""
    module = importlib.import_module("handlers.internal_translate")
    if instance is not None:
        instance.monkeypatch.setattr(module, "build_opener", instance.build_opener)
    return module


@pytest.fixture
def instance(monkeypatch) -> Instance:
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    return Instance(clock, monkeypatch)


def _body(size: int) -> list[bytes]:
    data = bytes(i % 251 for i in range(size))
    return [data[i:i + CHUNK] for i in range(0, size, CHUNK)]


def _listing(*entries: dict) -> bytes:
    return json.dumps({"total": len(entries), "data": list(entries)}).encode("utf-8")


def test_well_formed_track_parses_to_plain_text_cues_sorted_by_start():
    internal_translate = _translate()
    cues = internal_translate.parse_webvtt(WELL_FORMED)
    assert [c["text"] for c in cues] == ["First line", "Second line", "Instant", "An hour in"]  # C1
    assert [c["start"] for c in cues] == pytest.approx([1.0, 5.5, 10.0, 3723.004])  # C1
    assert [c["end"] for c in cues] == pytest.approx([2.0, 7.25, 10.0, 3724.0])  # C1
    assert all(set(c) == {"start", "end", "text"} and isinstance(c["start"], float) and isinstance(c["end"], float) for c in cues), cues  # C1


def test_markup_is_stripped_and_entities_decoded_to_plain_text():
    internal_translate = _translate()
    cues = internal_translate.parse_webvtt("WEBVTT\n\n00:01.000 --> 00:02.000\n<b>x</b>&lt;i&gt;\n")
    assert [c["text"] for c in cues] == ["x<i>"]  # C1


def test_the_good_cue_the_rejected_tracks_share_parses_alone():
    internal_translate = _translate()
    assert [c["text"] for c in internal_translate.parse_webvtt(GOOD)] == ["Kept"]  # C1


@pytest.mark.parametrize("track", REJECTED.values(), ids=REJECTED.keys())
def test_any_failing_part_rejects_the_whole_track(track):
    internal_translate = _translate()
    assert [c["text"] for c in internal_translate.parse_webvtt(GOOD)] == ["Kept"]
    assert internal_translate.parse_webvtt(track) is None  # C1


@pytest.mark.parametrize("track", NO_TEXT.values(), ids=NO_TEXT.keys())
def test_a_track_with_no_cue_text_is_none(track):
    internal_translate = _translate()
    assert [c["text"] for c in internal_translate.parse_webvtt(GOOD)] == ["Kept"]
    assert internal_translate.parse_webvtt(track) is None  # C1


def test_caption_pick_takes_the_first_exact_en_track():
    internal_translate = _translate()
    listing = _listing(
        {"language": {"id": "en-US", "label": "English (US)"}, "captionPath": "/lazy-static/video-captions/us.vtt"},
        {"language": {"id": "fr", "label": "French"}, "captionPath": "/lazy-static/video-captions/fr.vtt"},
        {"language": {"id": "en", "label": "English"}, "captionPath": "/lazy-static/video-captions/en-1.vtt"},
        {"language": {"id": "en", "label": "English"}, "captionPath": "/lazy-static/video-captions/en-2.vtt"},
    )
    assert internal_translate.pick_english_track_path(listing, HOST) == "/lazy-static/video-captions/en-1.vtt"  # C1


def test_caption_pick_takes_a_same_host_https_file_url():
    internal_translate = _translate()
    listing = _listing({"language": {"id": "en"}, "fileUrl": f"https://{HOST}/lazy-static/video-captions/en.vtt"})
    assert internal_translate.pick_english_track_path(listing, HOST) == "/lazy-static/video-captions/en.vtt"  # C1


@pytest.mark.parametrize("entry, on_host", PICK_REFUSED.values(), ids=PICK_REFUSED.keys())
def test_caption_pick_refuses_anything_off_the_host(entry, on_host):
    internal_translate = _translate()
    assert internal_translate.pick_english_track_path(_listing(on_host), HOST) == TRACK_PATH
    assert internal_translate.pick_english_track_path(_listing(entry), HOST) is None  # C1


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_handler_follows_a_same_host_https_target(code):
    internal_translate = _translate()
    target = f"https://{HOST}/lazy-static/video-captions/moved.vtt"
    new = internal_translate.SameHostRedirectHandler(HOST).redirect_request(Request(TRACK_URL), None, code, "Moved", HTTPMessage(), target)
    assert isinstance(new, Request) and new.full_url == target  # C2


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_redirect_handler_refuses_an_off_host_or_non_https_target(target):
    internal_translate = _translate()
    handler = internal_translate.SameHostRedirectHandler(HOST)
    same_host = f"https://{HOST}/lazy-static/video-captions/moved.vtt"
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), same_host).full_url == same_host
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), target) is None  # C2


def test_fetch_returns_the_joined_body_of_the_https_url(instance):
    internal_translate = _translate(instance)
    instance.serve(f"https://{HOST}/api/v1/videos/u-1/captions", chunks=[b'{"total": 0,', b' "data": []}'])
    assert internal_translate.fetch_bounded(HOST, "/api/v1/videos/u-1/captions", instance.clock.now + 1000) == b'{"total": 0, "data": []}'  # C2
    assert instance.opened == [f"https://{HOST}/api/v1/videos/u-1/captions"]  # C2


@pytest.mark.parametrize("location", [f"https://{HOST}/moved/en.vtt", "/moved/en.vtt"], ids=["absolute", "relative"])
def test_fetch_follows_a_same_host_redirect(instance, location):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, status=302, headers={"Location": location})
    instance.serve(f"https://{HOST}/moved/en.vtt", chunks=[b"WEBVTT\n"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) == b"WEBVTT\n"  # C2
    assert instance.opened == [TRACK_URL, f"https://{HOST}/moved/en.vtt"]  # C2


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_fetch_refuses_an_off_host_or_non_https_redirect(instance, target):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, status=302, headers={"Location": target})
    instance.serve(target, chunks=[b"LEAKED"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) is None  # C2
    assert instance.opened == [TRACK_URL]  # C2


def test_fetch_refuses_a_declared_length_over_the_cap_without_reading(instance):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, headers={"Content-Length": str(OVER_CAP)}, chunks=_body(OVER_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) is None  # C2
    assert [response.reads for response in instance.responses] == [0]  # C2


def test_fetch_refuses_a_body_streamed_past_the_cap(instance):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, chunks=_body(OVER_CAP))
    instance.serve(f"https://{HOST}/within.vtt", chunks=_body(WITHIN_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) is None  # C2
    assert instance.opened == [TRACK_URL]
    assert internal_translate.fetch_bounded(HOST, "/within.vtt", instance.clock.now + 1000) == b"".join(_body(WITHIN_CAP))


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "streamed"])
def test_fetch_returns_a_body_of_2_000_000_bytes_whole(instance, declared):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, headers={"Content-Length": str(WITHIN_CAP)} if declared else {}, chunks=_body(WITHIN_CAP))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) == b"".join(_body(WITHIN_CAP))  # C2


# The request-budget body is five 1 s chunks, inside the per-fetch deadline that seven 1 s chunks show is not exceeded, so only the budget can refuse it. Each refused fetch sits beside an on-time one that differs in one thing: two chunks instead of ten, or a far budget instead of 2 s.
@pytest.mark.parametrize("seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds", [(3.0, 10, 1000.0, 2, 1000.0), (1.0, 5, 2.0, 5, 1000.0)], ids=["per-fetch deadline", "request budget"])
def test_fetch_refuses_a_body_still_arriving_past_its_deadline(instance, seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds):
    internal_translate = _translate(instance)
    instance.serve(f"https://{HOST}/on-time.vtt", chunks=[f"c{i}".encode() for i in range(on_time_chunk_count)], seconds_per_chunk=seconds_per_chunk)
    instance.serve(TRACK_URL, chunks=[f"c{i}".encode() for i in range(chunk_count)], seconds_per_chunk=seconds_per_chunk)
    assert internal_translate.fetch_bounded(HOST, "/on-time.vtt", instance.clock.now + on_time_budget_seconds) == b"".join(f"c{i}".encode() for i in range(on_time_chunk_count))
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + budget_seconds) is None  # C2
    assert instance.opened == [f"https://{HOST}/on-time.vtt", TRACK_URL]


def test_fetch_returns_a_body_finished_inside_its_deadline(instance):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, chunks=[f"c{i}".encode() for i in range(7)], seconds_per_chunk=1.0)
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) == b"c0c1c2c3c4c5c6"  # C2


def test_fetch_with_its_budget_spent_opens_nothing(instance):
    internal_translate = _translate(instance)
    instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now - 1) is None  # C2
    assert instance.opened == []  # C2
    assert internal_translate.fetch_bounded(HOST, TRACK_PATH, instance.clock.now + 1000) == b"WEBVTT\n"
    assert instance.opened == [TRACK_URL]
