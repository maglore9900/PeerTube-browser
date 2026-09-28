"""The Client backend proxies GET `/api/video/refresh` to the Engine with only `id` and `host`, and sends a refresh that times out at the proxy to the Engine once.

- `?id=…&host=…` reaches the Engine as `/api/video/refresh` with exactly those two params, and the browser gets the Engine's 200 body. The same query plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400 and reaches the Engine not at all.
- With the refresh's entry in `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` patched to 0.3 s and an Engine that sleeps 1.5 s before answering, the refresh answers 502 and the Engine saw it once. `/api/video` against that Engine, with `ENGINE_PROXY_TIMEOUT_SECONDS` at 0.3 s, answers 502 after two attempts.

Each runs a real Client backend (test_server's `_client_backend`) in front of a stub Engine that records each GET's path and query.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# The active suite's conftest and harness, importable whether this file runs from tests/tmp or tests/active.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import RateLimiter, client_server  # noqa: E402
from test_server import _client_backend, _serving, _status  # noqa: E402

REFRESH_ROUTE = "/api/video/refresh"
QUERY = "id=uuid-1&host=tube.example"
FORWARDED = {"id": ["uuid-1"], "host": ["tube.example"]}
ANSWER = {"videoUuid": "uuid-1", "title": "Refreshed"}


def _engine_stub(received, delay):
    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            received.append((url.path, parse_qs(url.query)))
            time.sleep(delay)
            body = json.dumps(ANSWER).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The proxy gave up on a slow answer and closed the socket, which is the case under test.
                pass

        def log_message(self, format, *args):
            pass

    return EngineStub


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400(tmp_path):
    received = []
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 0))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # The /api/video allow-list takes user_id and refresh_cache (observed 200, user_id forwarded), foo is in no allow-list, and each allowed key is repeated once; unrouted, all answer 404 (observed).
        refused = [_status(base, "GET", f"{REFRESH_ROUTE}?{query}", {}) for query in (f"{QUERY}&user_id=u-1", f"{QUERY}&refresh_cache=1", f"{QUERY}&foo=1", f"id=uuid-2&{QUERY}", f"{QUERY}&host=other.example")]
        answered = _get(base, f"{REFRESH_ROUTE}?{QUERY}")
    assert refused == [400, 400, 400, 400, 400]  # C1
    assert answered == (200, ANSWER)  # C1
    # Sent before the allowed refresh, a refused one reaching the Engine would stand first here.
    assert received == [(REFRESH_ROUTE, FORWARDED)]  # C1


def test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502(tmp_path, monkeypatch):
    received = []
    # The mapping is a module global read per request (plan); raising=False lets the pre-phase run reach the refresh's own answer instead of stopping on the missing name.
    monkeypatch.setattr(client_server, "ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS", {**getattr(client_server, "ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS", {}), REFRESH_ROUTE: 0.3}, raising=False)
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 1.5))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # Under the shared 10 s timeout the 1.5 s answer arrives and this is 200; under the shared retry it is sent twice.
        refresh_status = _status(base, "GET", f"{REFRESH_ROUTE}?{QUERY}", {})
        refresh_sent = list(received)
        received.clear()
        monkeypatch.setattr(client_server, "ENGINE_PROXY_TIMEOUT_SECONDS", 0.3)
        video_status = _status(base, "GET", f"/api/video?{QUERY}", {})
    assert refresh_status == 502  # C2
    assert refresh_sent == [(REFRESH_ROUTE, FORWARDED)]  # C2
    # guard: the same sleeping Engine still gets /api/video twice, so the single refresh is the refresh's own retry count and not retries dropped for every route (observed 502 after two on the pre-phase code).
    assert (video_status, received) == (502, [("/api/video", FORWARDED)] * 2)
