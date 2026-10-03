"""`GET /api/translate` on a real Client backend answers 429, then 401, then 400, each without calling the Engine; a valid keyed request reaches the Engine's `/internal/translate` once, with the bridge token, its own request id and exactly `{id, host}` stripped, and the Engine's answer reaches the visitor as `none`, as `ready` cues of start, end and text only, or as a fixed 502.

Order (C1), the Engine stub's request log checked empty after each refusal:

- Under a one-request limiter, a keyless request answers 401, then a keyless request with an unknown param and a keyed valid request each answer 429 `Rate limit exceeded`.
- A keyless or wrong-key request with an unknown param, a repeated `id`, a missing `host` or no params answers 401 `Profile key required`, never 400; the same server's keyed valid request then reaches the Engine.
- Keyed, an unknown param answers 400 `Unknown query parameter: lang`, a repeated `id` 400 `Multiple values are not allowed for query parameter: id`, and a blank `id`, a whitespace `id`, a missing `host`, no params, a 201-character `id` and a 201-character `host` each answer 400.
- After those, the Engine has seen exactly two requests: POST `/internal/translate` with the configured `X-Bridge-Token`, the `X-Request-ID` each request sent, and the body `{"id": "uuid-1", "host": "peer.example"}` from ` uuid-1 ` / ` peer.example `, then a 200-character `id`.

Answers (C2), each from an Engine that was called exactly once:

- 404 `{"error": "Video not found"}` and 200 `{"state": "none"}` answer 200 `{"state": "none"}`.
- 404 `{"error": "Not found"}`, 500, a state of `queued`, cues that are an object, a `start` of `true` and a `text` of 7 each answer 502 `{"error": "Engine translate failed"}`; so does an Engine on a closed port.
- A `ready` whose cues carry `id`, `voice` and `settings` answers 200 with exactly those cues' start, end and text.

The Engine is a `BaseHTTPRequestHandler` stub recording each request and answering one scripted reply, as in `tests/active/test_server.py`; the Client is `ClientBackendServer` over a temporary users.db holding one minted profile, entered over HTTP.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
# Loaded by file under its own name: the Engine's api dir, which other tmp checkpoints put on sys.path, also holds a `server` module.
_spec = importlib.util.spec_from_file_location("client_backend_server_phase3", BACKEND_DIR / "server.py")
client_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(client_server)
from lib.http_utils import RateLimiter  # noqa: E402
from lib.profiles import mint_profile  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

ROUTE = "/api/translate"
BRIDGE_TOKEN = "phase3-bridge-token"
# Refuses at once (observed: `[Errno 111] Connection refused`), as conftest's CLOSED_ENGINE.
CLOSED_ENGINE = "http://127.0.0.1:9"
VALID = "id=uuid-1&host=peer.example"
FAILED = (502, {"error": "Engine translate failed"})
NONE = (200, {"state": "none"})
UNAUTHORIZED = (401, {"error": "Profile key required"})
RATE_LIMITED = (429, {"error": "Rate limit exceeded"})
READY = {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": "Hello"}]}
# Each bad query a keyed request is refused 400 for, and the error text where the shared allow-list rule fixes it (None: any error text).
BAD_QUERIES = {
    "unknown param": (f"{VALID}&lang=fr", "Unknown query parameter: lang"),
    "repeated id": ("id=uuid-1&id=uuid-2&host=peer.example", "Multiple values are not allowed for query parameter: id"),
    "blank id": ("id=&host=peer.example", None),
    "whitespace id": ("id=%20%20&host=peer.example", None),
    "missing host": ("id=uuid-1", None),
    "no params": ("", None),
    "201-character id": (f"id={'a' * 201}&host=peer.example", None),
    "201-character host": (f"id=uuid-1&host={'h' * 201}", None),
}
# What the Engine answers -> what the visitor gets.
ENGINE_ANSWERS = {
    "video not found": ((404, {"error": "Video not found"}), NONE),
    "engine none": ((200, {"state": "none"}), NONE),
    "route missing": ((404, {"error": "Not found"}), FAILED),
    "engine 500": ((500, {"error": "phase3-engine-sentinel"}), FAILED),
    "unknown state": ((200, {"state": "queued"}), FAILED),
    "cues not a list": ((200, {"state": "ready", "cues": {"start": 1.0, "end": 2.5, "text": "Hello"}}), FAILED),
    "start true": ((200, {"state": "ready", "cues": [{"start": True, "end": 2.5, "text": "Hello"}]}), FAILED),
    "text not a string": ((200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": 7}]}), FAILED),
}


class EngineStub(BaseHTTPRequestHandler):
    """Records each request as (method, path, X-Bridge-Token, X-Request-ID, JSON body) and answers `server.reply`, a (status, payload) pair."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, self.headers.get("X-Bridge-Token"), self.headers.get("X-Request-ID"), json.loads(raw) if raw else None))
        status, payload = self.server.reply
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # A route that proxied by GET instead of the bridge POST would be recorded too.
    do_GET = do_POST

    def log_message(self, *args):
        pass


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@contextmanager
def _engine(reply):
    """An EngineStub on 127.0.0.1:0 answering `reply`; yields its base URL and its request log."""
    stub = ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)
    stub.seen = []
    stub.reply = reply
    with _serving(stub) as base:
        yield base, stub.seen


@contextmanager
def _client(tmp_path, engine_base, rate_limiter):
    """A Client backend on 127.0.0.1:0 over `engine_base`, holding one minted profile; yields its base URL and that profile's key header."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    _, key = mint_profile(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", rate_limiter)) as base:
            yield base, {"X-Profile-Key": key}
    finally:
        conn.close()


def _get(base, query, headers):
    req = urllib.request.Request(f"{base}{ROUTE}?{query}" if query else base + ROUTE, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


@pytest.fixture(autouse=True)
def bridge_token(monkeypatch):
    monkeypatch.setenv("ENGINE_BRIDGE_TOKEN", BRIDGE_TOKEN)


def test_a_rate_limited_request_is_429_before_the_profile_and_param_checks_with_no_engine_call(tmp_path):
    limiter = RateLimiter(1, 60)
    with _engine((200, READY)) as (engine_base, seen), _client(tmp_path, engine_base, limiter) as (base, key):
        first = _get(base, VALID, {})
        limited = {"keyless with an unknown param": _get(base, f"{VALID}&lang=fr", {}), "keyed and valid": _get(base, VALID, key)}
        limited_seen = list(seen)
        # Emptied, the limiter lets the same keyed valid request through, so the empty log above is the 429's doing.
        limiter.requests.clear()
        unlimited = _get(base, VALID, key)
    assert limited == dict.fromkeys(limited, RATE_LIMITED)  # C1: 429, not 401 or 400
    assert limited_seen == []  # C1
    # Control: the limiter let the first request through, so the route's own keyless answer is 401, and an unlimited keyed valid request reaches the Engine.
    assert first == UNAUTHORIZED
    assert unlimited == (200, READY)
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_a_keyless_request_with_bad_params_is_401_not_400_with_no_engine_call(tmp_path):
    with _engine((200, READY)) as (engine_base, seen), _client(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        keyless = {name: _get(base, query, {}) for name, query in (("unknown param", f"{VALID}&lang=fr"), ("repeated id", "id=uuid-1&id=uuid-2&host=peer.example"), ("missing host", "id=uuid-1"), ("no params", ""))}
        wrong_key = _get(base, f"{VALID}&lang=fr", {"X-Profile-Key": "not-a-profile-key"})
        refused_seen = list(seen)
        allowed = _get(base, VALID, key)
    assert keyless == dict.fromkeys(keyless, UNAUTHORIZED)  # C1
    assert wrong_key == UNAUTHORIZED  # C1
    assert refused_seen == []  # C1
    # Control: the same server's keyed valid request does reach the Engine, so the empty log above is the 401's doing.
    assert allowed == (200, READY)
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_each_bad_param_is_400_with_no_engine_call_and_a_valid_request_reaches_the_bridge_route_with_token_request_id_and_stripped_id_host(tmp_path):
    with _engine((200, READY)) as (engine_base, seen), _client(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        refused = {name: _get(base, query, key) for name, (query, _) in BAD_QUERIES.items()}
        refused_seen = list(seen)
        # Sent after every refusal, so a refused request reaching the Engine would stand first in its log.
        stripped = _get(base, "id=%20uuid-1%20&host=%20peer.example%20", {**key, "X-Request-ID": "phase3-req-1"})
        longest = _get(base, f"id={'a' * 200}&host=peer.example", {**key, "X-Request-ID": "phase3-req-2"})
    assert {name: status for name, (status, _) in refused.items()} == dict.fromkeys(BAD_QUERIES, 400)  # C1
    assert {name: body.get("error") for name, (_, body) in refused.items() if BAD_QUERIES[name][1]} == {name: text for name, (_, text) in BAD_QUERIES.items() if text}  # C1: the shared allow-list texts
    assert all(isinstance(body.get("error"), str) and body["error"] for _, body in refused.values()), refused  # C1
    assert refused_seen == []  # C1
    # Control: valid requests, the 200-character id included (one under the 201 refused above), reach the Engine's bridge route.
    assert stripped == (200, READY)
    assert longest == (200, READY)
    assert seen == [
        ("POST", "/internal/translate", BRIDGE_TOKEN, "phase3-req-1", {"id": "uuid-1", "host": "peer.example"}),
        ("POST", "/internal/translate", BRIDGE_TOKEN, "phase3-req-2", {"id": "a" * 200, "host": "peer.example"}),
    ]


@pytest.mark.parametrize("engine_reply, expected", ENGINE_ANSWERS.values(), ids=ENGINE_ANSWERS.keys())
def test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502(tmp_path, engine_reply, expected):
    with _engine(engine_reply) as (engine_base, seen), _client(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _get(base, VALID, key)
    assert answered == expected  # C2
    # Control: the answer under test is the Engine's, from one bridge call.
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]


def test_an_unreachable_engine_is_a_fixed_502(tmp_path):
    with _client(tmp_path, CLOSED_ENGINE, RateLimiter(1000, 60)) as (base, key):
        assert _get(base, VALID, key) == FAILED  # C2


def test_a_ready_answer_reaches_the_visitor_with_only_start_end_and_text_per_cue(tmp_path):
    engine_cues = [
        {"start": 1.0, "end": 2.5, "text": "Hello", "id": "c1", "voice": "narrator"},
        {"start": 3, "end": 4.25, "text": "World", "settings": "line:0"},
    ]
    with _engine((200, {"state": "ready", "cues": engine_cues})) as (engine_base, seen), _client(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):
        answered = _get(base, VALID, key)
    assert answered == (200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": "Hello"}, {"start": 3, "end": 4.25, "text": "World"}]})  # C2
    # Control: the answer under test is the Engine's, from one bridge call.
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]
