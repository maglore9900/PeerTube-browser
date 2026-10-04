"""Plan 50 phase 3 checkpoint: the Client's `/api/translate` carries the Engine's job states to the page on GET and asks the Engine to queue generation on POST.

A real Client backend holding one minted profile (`_keyed_client_backend` from test_server.py) in front of a stand-in Engine that records each request as (method, path, X-Bridge-Token, X-Request-ID, JSON body) and answers per path, with 404 `{"error": "Not found"}` on any path it was not given, as an Engine without that route does; `ENGINE_BRIDGE_TOKEN` is set by the `bridge_token` fixture.

GET (C1):

- `after=3` and `after=0` reach POST `/internal/translate` with the bridge token in a body of exactly id, host and that `after` as a JSON int; no `after`, `after=` and `after=%20` reach it as exactly `{id, host}`.
- `after` given as an Arabic-Indic digit one, `-1`, `x`, `+1` or `1.5` each answers 400 with an `error`, and no request reaches the Engine; the same server's `after=1` then reaches it with `after` 1.
- Each of `none`, `queued`, `running` (stored-order cues and a `total` above their count, or no cues and `total` 0), `ready`, `already_english` and `failed`, with `available` true and with it false, answers 200 with exactly the Engine's answer.
- The same six without `available` answer with `available` false.
- 404 `Video not found` answers 200 `{"state": "none", "available": false}`; 404 `Not found`, an `available` that is a string, 1 or null, a running `total` that is missing, -1, true, a string or 1.5, and the state `bogus` each answer 502 `{"error": "Engine translate failed"}`. Each of these answers comes from exactly one call to the state route.

POST (C2):

- Under a one-request limiter, after a keyless valid request answers 401, a keyless request with invalid JSON and a keyed valid request each answer 429 `Rate limit exceeded` with no Engine call; emptied, the limiter lets the keyed request through to the enqueue route.
- With no key or a wrong key, a valid body, invalid JSON, `{}`, a numeric id and a 201-character id each answer 401 `Profile key required`, never 400, with no Engine call.
- Keyed, `{}`, no body, invalid JSON, a JSON array, a numeric id, a list host, a null id, a blank id, a whitespace host, a missing host, a 201-character id and a 201-character host each answer 400 with an `error` (`Invalid JSON body` for the two that are not a JSON object), with no Engine call; a 200-character id then reaches POST `/internal/translate/enqueue` with the bridge token and the request id, in a body of exactly id and host.
- The Engine's enqueue answers `queued`, `running`, `ready`, `failed`, `already_english` and `busy` with `available` true, and `none` with it false, reach the page unchanged; 404 `Video not found` answers `{"state": "none", "available": false}`; 503 and an old Engine's 404 `Not found` answer 502 `{"error": "Engine translate failed"}`. Each comes from exactly one call, to the enqueue route and not to the state route.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from conftest import RateLimiter  # noqa: E402
from test_server import _keyed_client_backend, _serving, _translate_get  # noqa: E402

BRIDGE_TOKEN = "translate-bridge-token"
STATE_ROUTE = "/internal/translate"
ENQUEUE_ROUTE = "/internal/translate/enqueue"
VALID = "id=uuid-1&host=peer.example"
BODY = {"id": "uuid-1", "host": "peer.example"}
FAILED = (502, {"error": "Engine translate failed"})
UNAUTHORIZED = (401, {"error": "Profile key required"})
RATE_LIMITED = (429, {"error": "Rate limit exceeded"})
NONE_AVAILABLE = {"state": "none", "available": True}
NONE_UNAVAILABLE = {"state": "none", "available": False}
QUEUED = {"state": "queued", "available": True}
READY_CUES = [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3, "end": 4.25, "text": "World"}]
# Stored order, not sorted by start: the running list is append-only, so the Client must not reorder it.
RUNNING_CUES = [{"start": 3.0, "end": 4.0, "text": "Third"}, {"start": 2.0, "end": 3.5, "text": "Second"}]
# Each state the state route answers, without `available`; total 4 over two cues is a poll with after=2.
STATE_ANSWERS = {
    "none": {"state": "none"},
    "queued": {"state": "queued"},
    "running": {"state": "running", "cues": RUNNING_CUES, "total": 4},
    "running with no cues yet": {"state": "running", "cues": [], "total": 0},
    "ready": {"state": "ready", "cues": READY_CUES},
    "already_english": {"state": "already_english"},
    "failed": {"state": "failed"},
}


class _RoutedEngine(BaseHTTPRequestHandler):
    """Records each request as (method, path, X-Bridge-Token, X-Request-ID, JSON body) and answers `server.replies[path]`, a (status, payload) pair; a path it was not given answers 404 Not found."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, self.headers.get("X-Bridge-Token"), self.headers.get("X-Request-ID"), json.loads(raw) if raw else None))
        status, payload = self.server.replies.get(self.path, (404, {"error": "Not found"}))
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # A route that called the Engine by GET instead of the bridge POST would be recorded too.
    do_GET = do_POST

    def log_message(self, *args):
        pass


@contextmanager
def _engine(replies):
    """A _RoutedEngine on 127.0.0.1:0 answering `replies` by path; yields its base URL and its request log."""
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _RoutedEngine)
    stub.seen = []
    stub.replies = replies
    with _serving(stub) as base:
        yield base, stub.seen


def _translate_post(base, body, headers):
    """POST /api/translate with `body` as JSON, or as these raw bytes."""
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + "/api/translate", data=data, method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


@pytest.fixture
def bridge_token(monkeypatch):
    monkeypatch.setenv("ENGINE_BRIDGE_TOKEN", BRIDGE_TOKEN)


# X-Request-ID -> (query suffix, the Engine body it must produce); each key is a valid request id so the Client forwards it unchanged.
AFTER_FORWARDED = {
    "after-3": ("&after=3", {**BODY, "after": 3}),
    "after-0": ("&after=0", {**BODY, "after": 0}),
    "no-after": ("", BODY),
    "after-empty": ("&after=", BODY),
    "after-space": ("&after=%20", BODY),
}


def test_get_forwards_an_ascii_digit_after_to_the_engine_as_an_int_and_leaves_out_an_absent_or_blank_one(tmp_path, bridge_token):
    with _engine({STATE_ROUTE: (200, NONE_AVAILABLE)}) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = {name: _translate_get(base, f"{VALID}{suffix}", {**key, "X-Request-ID": name}) for name, (suffix, _) in AFTER_FORWARDED.items()}
    assert answered == dict.fromkeys(AFTER_FORWARDED, (200, NONE_AVAILABLE))  # C1
    assert seen == [("POST", STATE_ROUTE, BRIDGE_TOKEN, name, body) for name, (_, body) in AFTER_FORWARDED.items()]  # C1
    # 3.0 == 3 in a dict comparison, so the JSON type is checked on its own.
    assert [type(entry[4]["after"]) for entry in seen[:2]] == [int, int]  # C1


# Each `after` value that is not ASCII digits, percent-encoded for the query; "+" is %2B, since a bare + decodes to a space.
AFTER_REFUSED = {
    "Arabic-Indic digit one": quote("\u0661"),
    "-1": "-1",
    "x": "x",
    "+1": "%2B1",
    "1.5": "1.5",
}


def test_get_refuses_an_after_that_is_not_ascii_digits_400_with_no_engine_call(tmp_path, bridge_token):
    with _engine({STATE_ROUTE: (200, NONE_AVAILABLE)}) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        refused = {name: _translate_get(base, f"{VALID}&after={value}", key) for name, value in AFTER_REFUSED.items()}
        refused_seen = list(seen)
        # Sent after every refusal, so a refused request reaching the Engine would stand first in its log.
        allowed = _translate_get(base, f"{VALID}&after=1", {**key, "X-Request-ID": "after-1"})
    # First, since it also arms the refusals: an ASCII-digit `after` is forwarded, so the 400s below are the value's doing, not an unknown-parameter refusal.
    assert allowed == (200, NONE_AVAILABLE)  # C1
    assert seen == [("POST", STATE_ROUTE, BRIDGE_TOKEN, "after-1", {**BODY, "after": 1})]  # C1
    assert {name: status for name, (status, _) in refused.items()} == dict.fromkeys(AFTER_REFUSED, 400)  # C1
    assert all(isinstance(body.get("error"), str) and body["error"] for _, body in refused.values()), refused
    assert refused_seen == []  # C1


@pytest.mark.parametrize("available", [True, False], ids=["available", "not available"])
@pytest.mark.parametrize("answer", STATE_ANSWERS.values(), ids=STATE_ANSWERS.keys())
def test_get_passes_each_engine_state_through_unchanged_with_its_available_flag(tmp_path, bridge_token, answer, available):
    engine_answer = {**answer, "available": available}
    with _engine({STATE_ROUTE: (200, engine_answer)}) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_get(base, VALID, key)
    assert answered == (200, engine_answer)  # C1
    # Control: the answer under test is the state route's, from one bridge call.
    assert [entry[:3] for entry in seen] == [("POST", STATE_ROUTE, BRIDGE_TOKEN)]


@pytest.mark.parametrize("answer", STATE_ANSWERS.values(), ids=STATE_ANSWERS.keys())
def test_get_reads_an_engine_answer_without_available_as_not_available(tmp_path, bridge_token, answer):
    with _engine({STATE_ROUTE: (200, answer)}) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_get(base, VALID, key)
    assert answered == (200, {**answer, "available": False})  # C1
    assert [entry[:2] for entry in seen] == [("POST", STATE_ROUTE)]


# What the state route answers -> what the page gets.
GET_ENGINE_ANSWERS = {
    "video not found": ((404, {"error": "Video not found"}), (200, NONE_UNAVAILABLE)),
    "route missing": ((404, {"error": "Not found"}), FAILED),
    "available a string": ((200, {"state": "none", "available": "true"}), FAILED),
    "available 1": ((200, {"state": "queued", "available": 1}), FAILED),
    "available null": ((200, {"state": "ready", "cues": READY_CUES, "available": None}), FAILED),
    "running total missing": ((200, {"state": "running", "cues": [], "available": True}), FAILED),
    "running total -1": ((200, {"state": "running", "cues": [], "total": -1, "available": True}), FAILED),
    "running total true": ((200, {"state": "running", "cues": [], "total": True, "available": True}), FAILED),
    "running total a string": ((200, {"state": "running", "cues": [], "total": "3", "available": True}), FAILED),
    "running total 1.5": ((200, {"state": "running", "cues": [], "total": 1.5, "available": True}), FAILED),
    "state bogus": ((200, {"state": "bogus", "available": True}), FAILED),
}


@pytest.mark.parametrize("engine_reply, expected", GET_ENGINE_ANSWERS.values(), ids=GET_ENGINE_ANSWERS.keys())
def test_get_answers_video_not_found_as_none_not_available_and_a_malformed_or_failed_answer_502(tmp_path, bridge_token, engine_reply, expected):
    with _engine({STATE_ROUTE: engine_reply}) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_get(base, VALID, key)
    assert answered == expected  # C1
    assert [entry[:2] for entry in seen] == [("POST", STATE_ROUTE)]


# The state route answers something else, so a POST sent there would show in the answer as well as in the log.
POST_REPLIES = {STATE_ROUTE: (200, {"state": "ready", "cues": READY_CUES, "available": True}), ENQUEUE_ROUTE: (200, QUEUED)}


def test_post_is_429_before_the_profile_and_body_checks_with_no_engine_call(tmp_path, bridge_token):
    limiter = RateLimiter(1, 60)
    with _engine(POST_REPLIES) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, limiter) as (base, key):
        first = _translate_post(base, BODY, {})
        limited = {"keyless with invalid JSON": _translate_post(base, b"{not json", {}), "keyed and valid": _translate_post(base, BODY, key)}
        limited_seen = list(seen)
        # Emptied, the limiter lets the same keyed valid request through, so the empty log above is the 429's doing.
        limiter.requests.clear()
        unlimited = _translate_post(base, BODY, {**key, "X-Request-ID": "post-unlimited"})
    assert limited == dict.fromkeys(limited, RATE_LIMITED)  # C2: 429, not 401 or 400
    assert limited_seen == []  # C2
    # Control: the limiter let the first request through, so the route's own keyless answer is 401.
    assert first == UNAUTHORIZED
    assert unlimited == (200, QUEUED)
    assert seen == [("POST", ENQUEUE_ROUTE, BRIDGE_TOKEN, "post-unlimited", BODY)]


# Bodies a keyless request is refused 401 for, before the body is read.
KEYLESS_BODIES = {
    "valid": BODY,
    "invalid JSON": b"{not json",
    "empty object": {},
    "numeric id": {"id": 1, "host": "peer.example"},
    "201-character id": {"id": "a" * 201, "host": "peer.example"},
}


def test_post_without_a_valid_profile_is_401_before_the_body_is_read_with_no_engine_call(tmp_path, bridge_token):
    with _engine(POST_REPLIES) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        refused = {f"{who}, {name}": _translate_post(base, body, headers) for who, headers in (("no key", {}), ("wrong key", {"X-Profile-Key": "not-a-profile-key"})) for name, body in KEYLESS_BODIES.items()}
        refused_seen = list(seen)
        allowed = _translate_post(base, BODY, {**key, "X-Request-ID": "post-keyed"})
    assert refused == dict.fromkeys(refused, UNAUTHORIZED)  # C2: 401, never 400
    assert refused_seen == []  # C2
    # Control: the same server's keyed valid request does reach the Engine, so the empty log above is the 401's doing.
    assert allowed == (200, QUEUED)
    assert seen == [("POST", ENQUEUE_ROUTE, BRIDGE_TOKEN, "post-keyed", BODY)]


# Each body a keyed request is refused 400 for, and the error text where read_json_body fixes it (None: any error text).
BAD_BODIES = {
    "empty object": (b"{}", None),
    "no body": (b"", None),
    "invalid JSON": (b"{not json", "Invalid JSON body"),
    "JSON array": (b"[1]", "Invalid JSON body"),
    "numeric id": ({"id": 1, "host": "peer.example"}, None),
    "list host": ({"id": "uuid-1", "host": ["peer.example"]}, None),
    "null id": ({"id": None, "host": "peer.example"}, None),
    "blank id": ({"id": "", "host": "peer.example"}, None),
    "whitespace host": ({"id": "uuid-1", "host": "   "}, None),
    "missing host": ({"id": "uuid-1"}, None),
    "201-character id": ({"id": "a" * 201, "host": "peer.example"}, None),
    "201-character host": ({"id": "uuid-1", "host": "h" * 201}, None),
}


def test_post_with_a_bad_body_is_400_with_no_engine_call_and_a_valid_one_reaches_the_enqueue_route_with_the_bridge_token(tmp_path, bridge_token):
    longest = {"id": "a" * 200, "host": "peer.example"}
    with _engine(POST_REPLIES) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        refused = {name: _translate_post(base, body, key) for name, (body, _) in BAD_BODIES.items()}
        refused_seen = list(seen)
        # Sent after every refusal, so a refused request reaching the Engine would stand first in its log.
        allowed = _translate_post(base, longest, {**key, "X-Request-ID": "post-200"})
    assert {name: status for name, (status, _) in refused.items()} == dict.fromkeys(BAD_BODIES, 400)  # C2
    assert {name: body.get("error") for name, (_, body) in refused.items() if BAD_BODIES[name][1]} == {name: text for name, (_, text) in BAD_BODIES.items() if text}
    assert all(isinstance(body.get("error"), str) and body["error"] for _, body in refused.values()), refused
    assert refused_seen == []  # C2
    # Control: the 200-character id, one under the 201 refused above, reaches the enqueue route.
    assert allowed == (200, QUEUED)
    assert seen == [("POST", ENQUEUE_ROUTE, BRIDGE_TOKEN, "post-200", longest)]  # C2


# What the enqueue route answers -> what the page gets.
ENQUEUE_ANSWERS = {
    "queued": ((200, QUEUED), (200, QUEUED)),
    "running": ((200, {"state": "running", "available": True}), (200, {"state": "running", "available": True})),
    "ready": ((200, {"state": "ready", "available": True}), (200, {"state": "ready", "available": True})),
    "failed": ((200, {"state": "failed", "available": True}), (200, {"state": "failed", "available": True})),
    "already_english": ((200, {"state": "already_english", "available": True}), (200, {"state": "already_english", "available": True})),
    "busy": ((200, {"state": "busy", "available": True}), (200, {"state": "busy", "available": True})),
    "none, not available": ((200, NONE_UNAVAILABLE), (200, NONE_UNAVAILABLE)),
    "video not found": ((404, {"error": "Video not found"}), (200, NONE_UNAVAILABLE)),
    "store unavailable": ((503, {"error": "Translate store unavailable"}), FAILED),
    "old Engine without the route": ((404, {"error": "Not found"}), FAILED),
}


@pytest.mark.parametrize("engine_reply, expected", ENQUEUE_ANSWERS.values(), ids=ENQUEUE_ANSWERS.keys())
def test_post_returns_the_engine_enqueue_answer_mapped_for_the_page(tmp_path, bridge_token, engine_reply, expected):
    replies = {**POST_REPLIES, ENQUEUE_ROUTE: engine_reply}
    with _engine(replies) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _translate_post(base, BODY, {**key, "X-Request-ID": "post-enqueue"})
    assert answered == expected  # C2
    # The answer under test is the enqueue route's, from one bridge call with the token, the request id and exactly id and host.
    assert seen == [("POST", ENQUEUE_ROUTE, BRIDGE_TOKEN, "post-enqueue", BODY)]  # C2
