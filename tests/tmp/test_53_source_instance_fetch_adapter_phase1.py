"""Phase 1 checkpoint of plan 53: `engine/server/data/source_fetch.py`, called directly.

`fetch_bounded` (C1) raises `SourceFetchFailed` whose text is exactly its reason: `HTTP 204` for a returned 204, `HTTP 404` and `HTTP 500` for a raised one, `redirect refused: <target>` for each refused target with the target never opened, `Content-Length 2097153 over 2000000 bytes` with no body read, `body over 2000000 bytes` with nothing read past one chunk over the cap, `deadline passed` for the per-fetch deadline, the request budget, and a budget already spent (or exactly now) with nothing opened, and the exception's own text for an OSError, a timeout, two TLS errors, an HTTPException and a ValueError raised at open. A refused redirect followed by an unserved path reads `HTTP 404`. A same-host redirect, absolute or relative, is followed. With no overrides it sends `Accept: application/json, text/vtt` under a 4 s socket timeout (1 s with a budget 1 s away), returns 2,000,000 bytes whole, declared or streamed, and seven and eight 1 s chunks whole where nine pass its 8 s deadline. Each override takes effect: `max_bytes=10` refuses 11 bytes streamed and declared and returns 10; `deadline_seconds` refuses five 1 s chunks at 2 s, returns twelve at 20 s, and caps the socket timeout; `socket_timeout` is sent as given, capped by the time left; `headers` replace the accept header.

`stream_media` (C2) feeds a body whole to its consumer under a 15 s socket timeout with no wall-clock deadline (40 s of chunks, a declared length equal to `max_bytes`), and raises today's texts exactly: `media download failed: HTTP 204`, `media download failed: HTTP Error 404: Scripted`, `media download failed: <the exception's own text>` for each error `fetch_bounded` is given at open (a reset, a timeout, two TLS errors, an HTTPException and a ValueError) with only the media URL opened and nothing fed, `media over 200000 bytes` from the declared length with no read and from the stream with nothing consumed past the cap (and `media over 10 bytes` for 11 bytes, declared or streamed, under `max_bytes=10`, which feeds 10 whole), and `media download failed: HTTP Error 302: Scripted` for each refused redirect target, never opened, while a same-host redirect is followed. Once `stop` is set nothing more is read. A consumer's BrokenPipeError propagates as that same exception, where a consumer's ValueError reads `media download failed: I/O operation on closed file.`.

The redirect handler returns the target's request for a same-host https 301/302/303/307/308 with `refused` None, and None for each refused target with `refused` set to it. `media_host` returns the raw lowercased hostname, trailing dot kept, and None for each refused form.

The network is severed at the adapter's single patch point, `source_fetch.build_opener`, with test_internal_translate.py's harness: the module's real redirect handler runs inside a real urllib opener whose only fake part is the http/https open step, which serves scripted responses whose reads advance a Clock patched into `time.monotonic`.
"""
from __future__ import annotations

import http.client
import importlib
import re
import ssl
import sys
import threading
import time
import urllib.error
from http.client import HTTPMessage
from pathlib import Path
from types import ModuleType
from urllib.request import Request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import CHUNK, HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, WITHIN_CAP, Clock, Response, ScriptedInstance, _body  # noqa: E402

MOVED_URL = f"https://{HOST}/moved/en.vtt"
UNSERVED_URL = f"https://{HOST}/unserved.vtt"
MEDIA_URL = f"https://{HOST}/static/web-videos/v-1-240.mp4"
MEDIA_MOVED_URL = f"https://{HOST}/static/streaming-playlists/v-1-240.mp4"
# Four reads of _body's CHUNK-sized slices (three whole, one of 3,392 bytes), so a cap of MEDIA_SIZE is crossed mid-body by one byte more.
MEDIA_SIZE = 200_000
# Each error the open step raises, and its text: one per member of the caught tuple (OSError, ValueError, HTTPException), plus a timeout and TLS failures as urllib surfaces them.
OPEN_ERRORS = {
    "connection reset": (ConnectionResetError("connection reset by peer"), "connection reset by peer"),
    "socket timeout": (TimeoutError("timed out"), "timed out"),
    "TLS verification, wrapped by urllib": (urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")), "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"),
    "TLS error": (ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number"), "[SSL: WRONG_VERSION_NUMBER] wrong version number"),
    "HTTPException": (http.client.IncompleteRead(b"ab", 5), "IncompleteRead(2 bytes read, 5 more expected)"),
    "ValueError": (ValueError("label empty or too long"), "label empty or too long"),
}
# (status served, or None for an unserved path, and the reason): a 204 is returned by urllib, a 404 or 500 raised as an HTTPError.
STATUSES = {"returned 204": (204, "HTTP 204"), "unserved 404": (None, "HTTP 404"), "raised 500": (500, "HTTP 500")}
# Today's media texts for a non-200: a returned status is named by the worker, a raised one keeps urllib's HTTPError text with the harness's reason phrase.
MEDIA_STATUSES = {"returned 204": (204, "media download failed: HTTP 204"), "raised 404": (404, "media download failed: HTTP Error 404: Scripted")}
# The same errors raised at open on a media URL, and today's AudioPipe._feed text for each, as observed through this harness.
MEDIA_OPEN_ERRORS = {
    "connection reset": (OPEN_ERRORS["connection reset"][0], "media download failed: connection reset by peer"),
    "socket timeout": (OPEN_ERRORS["socket timeout"][0], "media download failed: timed out"),
    "TLS verification, wrapped by urllib": (OPEN_ERRORS["TLS verification, wrapped by urllib"][0], "media download failed: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"),
    "TLS error": (OPEN_ERRORS["TLS error"][0], "media download failed: [SSL: WRONG_VERSION_NUMBER] wrong version number"),
    "HTTPException": (OPEN_ERRORS["HTTPException"][0], "media download failed: IncompleteRead(2 bytes read, 5 more expected)"),
    "ValueError": (OPEN_ERRORS["ValueError"][0], "media download failed: label empty or too long"),
}
MEDIA_HOSTS = {
    "lowercase": ("https://media.example/v.mp4", "media.example"),
    "mixed case": ("https://Media.EXAMPLE/v.mp4", "media.example"),
    "trailing dot, raw not normalized": ("https://media.example./v.mp4", "media.example."),
    "punycode TLD": ("https://media.xn--p1ai/v.mp4", "media.xn--p1ai"),
}
REFUSED_MEDIA_URLS = {
    "http": "http://media.example/v.mp4",
    "IPv4 literal": "https://203.0.113.7/v.mp4",
    "IPv6 literal": "https://[2001:db8::7]/v.mp4",
    "decimal host": "https://2130706433/v.mp4",
    "dotted numeric host": "https://127.1/v.mp4",
    "hex host": "https://0x7f.0x1/v.mp4",
    "single-label host": "https://media/v.mp4",
    "explicit port": "https://media.example:8443/v.mp4",
    "explicit default port": "https://media.example:443/v.mp4",
    "userinfo": "https://user@media.example/v.mp4",
    "user and password": "https://user:pw@media.example/v.mp4",
    "unparseable port": "https://media.example:bad/v.mp4",
    "empty": "",
    "not a URL": "not a url",
}


class SourceInstance(ScriptedInstance):
    """The scripted instance, also keeping every request it is handed (for its headers) and the socket timeout each was opened under, and raising a scripted error at open for a URL given one."""

    def __init__(self, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(clock, monkeypatch)
        self.requests: list[Request] = []
        # Kept here rather than as the harness's planned `timeouts`, so the checkpoint does not depend on an edit to test_internal_translate.py and cannot count a timeout twice once that edit lands.
        self.socket_timeouts: list[float] = []
        self.errors: dict[str, BaseException] = {}

    def fail(self, url: str, error: BaseException) -> None:
        self.errors[url] = error

    def open(self, req: Request) -> Response:
        self.requests.append(req)
        self.socket_timeouts.append(req.timeout)
        if req.full_url in self.errors:
            self.opened.append(req.full_url)
            raise self.errors[req.full_url]
        return super().open(req)


@pytest.fixture
def scripted_instance(monkeypatch) -> SourceInstance:
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    return SourceInstance(clock, monkeypatch)


def _adapter(instance: SourceInstance | None = None) -> ModuleType:
    """The module under test, imported inside each test so that a missing module fails each test instead of stopping collection; given an instance, its build_opener opens through it."""
    module = importlib.import_module("data.source_fetch")
    if instance is not None:
        instance.monkeypatch.setattr(module, "build_opener", instance.build_opener)
    return module


def _exactly(text: str) -> str:
    """A pytest.raises match pattern for exactly this reason, nothing before or after it."""
    return rf"^{re.escape(text)}\Z"


def _budget(clock: Clock, seconds: float | None) -> dict[str, float]:
    """The budget_at keyword for a budget `seconds` from now, or none at all."""
    return {} if seconds is None else {"budget_at": clock.now + seconds}


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_handler_follows_a_same_host_https_target(code):
    handler = _adapter().SameHostRedirectHandler(HOST)
    new = handler.redirect_request(Request(TRACK_URL), None, code, "Moved", HTTPMessage(), MOVED_URL)
    assert isinstance(new, Request) and new.full_url == MOVED_URL  # C1
    assert handler.refused is None  # C1


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_redirect_handler_refuses_an_off_host_or_non_https_target_and_keeps_it_as_refused(target):
    handler = _adapter().SameHostRedirectHandler(HOST)
    # Control: the same handler follows a same-host target and has refused nothing.
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), MOVED_URL).full_url == MOVED_URL  # C1
    assert handler.refused is None  # C1
    assert handler.redirect_request(Request(TRACK_URL), None, 302, "Found", HTTPMessage(), target) is None  # C1
    assert handler.refused == target  # C1


@pytest.mark.parametrize("location", [MOVED_URL, "/moved/en.vtt"], ids=["absolute", "relative"])
def test_fetch_follows_a_same_host_redirect(scripted_instance, location):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, status=302, headers={"Location": location})
    scripted_instance.serve(MOVED_URL, chunks=[b"WEBVTT\n"])
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH) == b"WEBVTT\n"  # C1
    assert scripted_instance.opened == [TRACK_URL, MOVED_URL]  # C1


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_fetch_names_a_refused_redirect_target_and_never_opens_it(scripted_instance, target):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, status=302, headers={"Location": target})
    scripted_instance.serve(target, chunks=[b"LEAKED"])
    # Not `HTTP 302` and not urllib's `HTTP Error 302: ...`: the refused redirect is its own reason.
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(f"redirect refused: {target}")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    assert scripted_instance.opened == [TRACK_URL]  # C1


def test_a_refused_redirect_does_not_carry_into_the_next_fetch(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    target = REFUSED_TARGETS["off-host"]
    scripted_instance.serve(TRACK_URL, status=302, headers={"Location": target})
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(f"redirect refused: {target}")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    # A handler shared across fetches would still hold the refused target and misname this 404.
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("HTTP 404")):  # C1
        source_fetch.fetch_bounded(HOST, "/unserved.vtt")
    assert scripted_instance.opened == [TRACK_URL, UNSERVED_URL]  # C1


@pytest.mark.parametrize("status, reason", STATUSES.values(), ids=STATUSES.keys())
def test_fetch_names_the_status_of_a_non_200_answer(scripted_instance, status, reason):
    source_fetch = _adapter(scripted_instance)
    if status is not None:
        scripted_instance.serve(TRACK_URL, status=status, chunks=[b"WEBVTT\n"])
    scripted_instance.serve(MOVED_URL, chunks=[b"WEBVTT\n"])
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(reason)):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    # Control: the same instance answers a 200 path with its body.
    assert source_fetch.fetch_bounded(HOST, "/moved/en.vtt") == b"WEBVTT\n"  # C1


def test_fetch_refuses_a_declared_length_over_the_cap_without_reading(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, headers={"Content-Length": str(OVER_CAP)}, chunks=_body(OVER_CAP))
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("Content-Length 2097153 over 2000000 bytes")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    assert [response.reads for response in scripted_instance.responses] == [0]  # C1


def test_fetch_refuses_a_body_streamed_past_the_cap_reading_no_further(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=_body(OVER_CAP))
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("body over 2000000 bytes")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    (response,) = scripted_instance.responses
    read = OVER_CAP - sum(len(chunk) for chunk in response.chunks)
    # Stopped within the chunk that crossed the cap; reading the body out first would leave nothing unread.
    assert WITHIN_CAP < read <= WITHIN_CAP + CHUNK, read  # C1


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "streamed"])
def test_fetch_returns_a_body_of_2_000_000_bytes_whole(scripted_instance, declared):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, headers={"Content-Length": str(WITHIN_CAP)} if declared else {}, chunks=_body(WITHIN_CAP))
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH) == b"".join(_body(WITHIN_CAP))  # C1


# The request-budget body is five 1 s chunks, inside the 8 s per-fetch deadline, so only the budget can refuse it. Each refused fetch sits beside an on-time one that differs in one thing: two chunks instead of ten, or no budget instead of 2 s.
@pytest.mark.parametrize("seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds", [(3.0, 10, None, 2, None), (1.0, 5, 2.0, 5, None)], ids=["per-fetch deadline", "request budget"])
def test_fetch_names_a_deadline_passed_while_the_body_is_still_arriving(scripted_instance, seconds_per_chunk, chunk_count, budget_seconds, on_time_chunk_count, on_time_budget_seconds):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(f"https://{HOST}/on-time.vtt", chunks=[f"c{i}".encode() for i in range(on_time_chunk_count)], seconds_per_chunk=seconds_per_chunk)
    scripted_instance.serve(TRACK_URL, chunks=[f"c{i}".encode() for i in range(chunk_count)], seconds_per_chunk=seconds_per_chunk)
    assert source_fetch.fetch_bounded(HOST, "/on-time.vtt", **_budget(scripted_instance.clock, on_time_budget_seconds)) == b"".join(f"c{i}".encode() for i in range(on_time_chunk_count))  # C1
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("deadline passed")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH, **_budget(scripted_instance.clock, budget_seconds))
    assert scripted_instance.opened == [f"https://{HOST}/on-time.vtt", TRACK_URL]  # C1


def test_with_no_overrides_the_deadline_is_8_seconds(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    for count in (7, 8, 9):
        scripted_instance.serve(f"https://{HOST}/{count}.vtt", chunks=[f"c{i}".encode() for i in range(count)], seconds_per_chunk=1.0)
    # Today's fetch_bounded returns seven and eight 1 s chunks and refuses nine.
    assert source_fetch.fetch_bounded(HOST, "/7.vtt") == b"c0c1c2c3c4c5c6"  # C1
    assert source_fetch.fetch_bounded(HOST, "/8.vtt") == b"c0c1c2c3c4c5c6c7"  # C1
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("deadline passed")):  # C1
        source_fetch.fetch_bounded(HOST, "/9.vtt")


@pytest.mark.parametrize("spent_seconds", [1.0, 0.0], ids=["a second ago", "exactly now"])
def test_fetch_with_its_budget_spent_names_the_deadline_and_opens_nothing(scripted_instance, spent_seconds):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("deadline passed")):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH, budget_at=scripted_instance.clock.now - spent_seconds)
    assert scripted_instance.opened == []  # C1
    # Control: the same fetch with budget left opens the URL and returns the body.
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH, budget_at=scripted_instance.clock.now + 1000) == b"WEBVTT\n"  # C1
    assert scripted_instance.opened == [TRACK_URL]  # C1


@pytest.mark.parametrize("error, reason", OPEN_ERRORS.values(), ids=OPEN_ERRORS.keys())
def test_fetch_names_an_error_raised_at_open_by_its_text(scripted_instance, error, reason):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.fail(TRACK_URL, error)
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(reason)):  # C1
        source_fetch.fetch_bounded(HOST, TRACK_PATH)
    assert scripted_instance.opened == [TRACK_URL]  # C1


def test_with_no_overrides_fetch_sends_todays_accept_header_under_a_4s_socket_timeout_capped_by_the_budget(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH) == b"WEBVTT\n"  # C1
    (request,) = scripted_instance.requests
    assert request.full_url == TRACK_URL  # C1
    assert request.get_header("Accept") == "application/json, text/vtt"  # C1
    assert scripted_instance.socket_timeouts == [4.0]  # C1
    # A budget 1 s away leaves 1 s, under the 4 s socket timeout.
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH, budget_at=scripted_instance.clock.now + 1.0) == b"WEBVTT\n"  # C1
    assert scripted_instance.socket_timeouts == [4.0, 1.0]  # C1


def test_a_max_bytes_override_replaces_the_2_000_000_byte_cap(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(f"https://{HOST}/ten.vtt", chunks=[b"0123456789"])
    scripted_instance.serve(f"https://{HOST}/eleven.vtt", chunks=[b"0123456789a"])
    scripted_instance.serve(f"https://{HOST}/eleven-declared.vtt", headers={"Content-Length": "11"}, chunks=[b"0123456789a"])
    assert source_fetch.fetch_bounded(HOST, "/ten.vtt", max_bytes=10) == b"0123456789"  # C1
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("body over 10 bytes")):  # C1
        source_fetch.fetch_bounded(HOST, "/eleven.vtt", max_bytes=10)
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("Content-Length 11 over 10 bytes")):  # C1
        source_fetch.fetch_bounded(HOST, "/eleven-declared.vtt", max_bytes=10)
    assert scripted_instance.responses[2].reads == 0  # C1
    # Control: under the default cap the same eleven bytes come back.
    assert source_fetch.fetch_bounded(HOST, "/eleven.vtt") == b"0123456789a"  # C1


def test_a_deadline_seconds_override_replaces_the_8s_deadline_and_caps_the_socket_timeout(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(f"https://{HOST}/five.vtt", chunks=[f"c{i}".encode() for i in range(5)], seconds_per_chunk=1.0)
    scripted_instance.serve(f"https://{HOST}/twelve.vtt", chunks=[f"c{i}".encode() for i in range(12)], seconds_per_chunk=1.0)
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("deadline passed")):  # C1
        source_fetch.fetch_bounded(HOST, "/five.vtt", deadline_seconds=2.0)
    assert source_fetch.fetch_bounded(HOST, "/five.vtt") == b"c0c1c2c3c4"  # C1: control, the default 8 s returns it
    assert source_fetch.fetch_bounded(HOST, "/twelve.vtt", deadline_seconds=20.0) == b"".join(f"c{i}".encode() for i in range(12))  # C1: past the default 8 s
    assert scripted_instance.socket_timeouts == [2.0, 4.0, 4.0]  # C1


def test_a_socket_timeout_override_is_sent_capped_by_the_time_left(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    source_fetch.fetch_bounded(HOST, TRACK_PATH, socket_timeout=1.5)
    source_fetch.fetch_bounded(HOST, TRACK_PATH, socket_timeout=6.0)
    source_fetch.fetch_bounded(HOST, TRACK_PATH, socket_timeout=6.0, budget_at=scripted_instance.clock.now + 2.0)
    assert scripted_instance.socket_timeouts == [1.5, 6.0, 2.0]  # C1


def test_a_headers_override_replaces_the_default_accept_header(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(TRACK_URL, chunks=[b"WEBVTT\n"])
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH, headers={"User-Agent": "peertube-browser-trending/1.0"}) == b"WEBVTT\n"  # C1
    assert source_fetch.fetch_bounded(HOST, TRACK_PATH, headers={"accept": "application/json"}) == b"WEBVTT\n"  # C1
    user_agent_only, accept_only = scripted_instance.requests
    assert user_agent_only.get_header("User-agent") == "peertube-browser-trending/1.0"  # C1
    assert user_agent_only.get_header("Accept") is None  # C1: replaced, not merged
    assert accept_only.get_header("Accept") == "application/json"  # C1


def test_stream_media_feeds_the_whole_body_under_a_15s_socket_timeout_with_no_wall_clock_deadline(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    # Ten seconds a chunk: the body takes 40 s on the clock, past any 8 s deadline; its declared length equals max_bytes.
    scripted_instance.serve(MEDIA_URL, headers={"Content-Length": str(MEDIA_SIZE)}, chunks=_body(MEDIA_SIZE), seconds_per_chunk=10.0)
    started = scripted_instance.clock.now
    consumed: list[bytes] = []
    assert source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event()) is None  # C2
    assert b"".join(consumed) == b"".join(_body(MEDIA_SIZE))  # C2
    assert scripted_instance.clock.now - started == 40.0  # C2: control, the whole body was read on the clock
    assert scripted_instance.socket_timeouts == [15.0]  # C2


@pytest.mark.parametrize("status, text", MEDIA_STATUSES.values(), ids=MEDIA_STATUSES.keys())
def test_stream_media_names_a_non_200_answer_in_todays_text(scripted_instance, status, text):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, status=status, chunks=_body(MEDIA_SIZE))
    consumed: list[bytes] = []
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(text)):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    assert consumed == []  # C2


@pytest.mark.parametrize("error, text", MEDIA_OPEN_ERRORS.values(), ids=MEDIA_OPEN_ERRORS.keys())
def test_stream_media_names_an_error_raised_at_open_in_todays_text(scripted_instance, error, text):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.fail(MEDIA_URL, error)
    consumed: list[bytes] = []
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly(text)):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    assert scripted_instance.opened == [MEDIA_URL]  # C2
    assert consumed == []  # C2


def test_stream_media_refuses_a_declared_length_over_max_bytes_without_reading(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, headers={"Content-Length": str(MEDIA_SIZE + 1)}, chunks=_body(MEDIA_SIZE + 1))
    consumed: list[bytes] = []
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media over 200000 bytes")):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    assert [response.reads for response in scripted_instance.responses] == [0]  # C2
    assert consumed == []  # C2


def test_stream_media_refuses_a_body_streamed_past_max_bytes_consuming_nothing_past_it(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, chunks=_body(MEDIA_SIZE + 1))
    consumed: list[bytes] = []
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media over 200000 bytes")):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    fed = b"".join(consumed)
    # The chunk that crosses the cap is never handed on; what was handed on is the body's own start.
    assert 0 < len(fed) <= MEDIA_SIZE, len(fed)  # C2
    assert b"".join(_body(MEDIA_SIZE + 1)).startswith(fed)  # C2


def test_stream_media_names_its_own_max_bytes(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(f"https://{HOST}/ten.mp4", chunks=[b"0123456789"])
    scripted_instance.serve(f"https://{HOST}/eleven.mp4", chunks=[b"0123456789a"])
    scripted_instance.serve(f"https://{HOST}/eleven-declared.mp4", headers={"Content-Length": "11"}, chunks=[b"0123456789a"])
    consumed: list[bytes] = []
    source_fetch.stream_media(f"https://{HOST}/ten.mp4", HOST, 10, consumed.append, threading.Event())
    assert consumed == [b"0123456789"]  # C2: control, ten bytes pass a cap of ten
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media over 10 bytes")):  # C2
        source_fetch.stream_media(f"https://{HOST}/eleven.mp4", HOST, 10, consumed.append, threading.Event())
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media over 10 bytes")):  # C2
        source_fetch.stream_media(f"https://{HOST}/eleven-declared.mp4", HOST, 10, consumed.append, threading.Event())
    assert scripted_instance.responses[2].reads == 0  # C2
    assert consumed == [b"0123456789"]  # C2


@pytest.mark.parametrize("target", REFUSED_TARGETS.values(), ids=REFUSED_TARGETS.keys())
def test_stream_media_keeps_todays_text_for_a_refused_redirect_and_never_opens_its_target(scripted_instance, target):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, status=302, headers={"Location": target})
    scripted_instance.serve(target, chunks=[b"LEAKED"])
    consumed: list[bytes] = []
    # urllib's HTTPError text, as today; not the buffered form's `redirect refused: ...`.
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media download failed: HTTP Error 302: Scripted")):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    assert scripted_instance.opened == [MEDIA_URL]  # C2
    assert consumed == []  # C2


def test_stream_media_follows_a_same_host_redirect(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, status=302, headers={"Location": MEDIA_MOVED_URL})
    scripted_instance.serve(MEDIA_MOVED_URL, chunks=_body(MEDIA_SIZE))
    consumed: list[bytes] = []
    source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, threading.Event())
    assert b"".join(consumed) == b"".join(_body(MEDIA_SIZE))  # C2
    assert scripted_instance.opened == [MEDIA_URL, MEDIA_MOVED_URL]  # C2


def test_stream_media_reads_nothing_more_once_stop_is_set(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, chunks=_body(MEDIA_SIZE))
    stop = threading.Event()
    consumed: list[bytes] = []

    def consume_then_stop(chunk: bytes) -> None:
        consumed.append(chunk)
        stop.set()

    assert source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consume_then_stop, stop) is None  # C2
    assert len(consumed) == 1 and b"".join(_body(MEDIA_SIZE)).startswith(consumed[0])  # C2
    assert [response.reads for response in scripted_instance.responses] == [1]  # C2: four chunks were there to read
    # Already set before the call: nothing is read at all.
    assert source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, consumed.append, stop) is None  # C2
    assert [response.reads for response in scripted_instance.responses] == [1, 0]  # C2
    assert len(consumed) == 1  # C2


def test_a_consumers_broken_pipe_propagates_as_itself_not_as_a_download_failure(scripted_instance):
    source_fetch = _adapter(scripted_instance)
    scripted_instance.serve(MEDIA_URL, chunks=_body(MEDIA_SIZE))
    pipe = BrokenPipeError(32, "Broken pipe")

    def broken(chunk: bytes) -> None:
        raise pipe

    def closed(chunk: bytes) -> None:
        raise ValueError("I/O operation on closed file.")

    with pytest.raises(BrokenPipeError) as raised:  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, broken, threading.Event())
    assert raised.value is pipe  # C2
    # Control: any other consumer error is a download failure in today's text, so the pass-through above is BrokenPipeError's own.
    with pytest.raises(source_fetch.SourceFetchFailed, match=_exactly("media download failed: I/O operation on closed file.")):  # C2
        source_fetch.stream_media(MEDIA_URL, HOST, MEDIA_SIZE, closed, threading.Event())


@pytest.mark.parametrize("url, host", MEDIA_HOSTS.values(), ids=MEDIA_HOSTS.keys())
def test_media_host_returns_the_raw_lowercased_hostname(url, host):
    assert _adapter().media_host(url) == host  # seam: the moved media_host case (no clause)


@pytest.mark.parametrize("url", REFUSED_MEDIA_URLS.values(), ids=REFUSED_MEDIA_URLS.keys())
def test_media_host_refuses_anything_but_an_https_dns_name_with_no_port_or_userinfo(url):
    source_fetch = _adapter()
    assert source_fetch.media_host("https://media.example/v.mp4") == "media.example"  # seam: control
    assert source_fetch.media_host(url) is None  # seam: the moved media_host case (no clause)
