"""The Client backend over live HTTP from 127.0.0.1, a trusted peer under the default set: which address its rate limiters and its Engine requests attribute a request to.

- The per-route limiter and the profile-mint limiter bucket by the last untrusted `X-Forwarded-For` hop: requests differing only in their first hop, or in a trusted hop appended after it, share a bucket, and a different last untrusted hop gets its own.
- The `x-client-ip` the Engine receives is that resolved address, not the forgeable first hop nor a trusted last hop; with no `X-Forwarded-For` it is the peer, whatever `X-Real-IP` claims.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

CLOSED_ENGINE = "http://127.0.0.1:9"


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
def _client_backend(tmp_path, engine_base, rate_limiter):
    """A Client backend on 127.0.0.1:0 under the default trusted set, as `tests/active/conftest.py` builds `client_backend`."""
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", rate_limiter)) as base:
            yield base
    finally:
        conn.close()


def _status(base, method, path, headers):
    req = urllib.request.Request(base + path, data=b"{}" if method == "POST" else None, method=method)
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_route_limiter_buckets_by_last_hop(tmp_path):
    with _client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(2, 60)) as base:
        # Without a profile key an allowed request is 401, so 429 is the limiter and nothing else.
        statuses = [_status(base, "GET", "/api/user-profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}) for i in (1, 2, 3)]
        assert statuses == [401, 401, 429]  # C1
        # A trusted hop after 203.0.113.9 is stripped by the resolver; keying on the raw last hop would open a fresh 127.0.0.1 bucket and answer 401.
        assert _status(base, "GET", "/api/user-profile", {"X-Forwarded-For": "198.51.100.4, 203.0.113.9, 127.0.0.1"}) == 429  # C1
        # Unfixed code keys on the socket peer, 127.0.0.1 for every request, and answers 429 here.
        assert _status(base, "GET", "/api/user-profile", {"X-Forwarded-For": "198.51.100.1, 203.0.113.10"}) == 401  # C1


def test_mint_limiter_buckets_by_last_hop(tmp_path):
    with _client_backend(tmp_path, CLOSED_ENGINE, RateLimiter(1000, 60)) as base:
        statuses = [_status(base, "POST", "/api/profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}) for i in range(1, 7)]
        assert statuses == [201] * 5 + [429]  # C1
        assert _status(base, "POST", "/api/profile", {"X-Forwarded-For": "198.51.100.7, 203.0.113.9, 127.0.0.1"}) == 429  # C1
        assert _status(base, "POST", "/api/profile", {"X-Forwarded-For": "198.51.100.1, 203.0.113.10"}) == 201  # C1


def test_engine_receives_the_resolved_address_as_x_client_ip(tmp_path):
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            received.append(self.headers.get("x-client-ip"))
            body = json.dumps({"rows": []}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        assert _status(base, "GET", "/api/channels", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}) == 200
        assert _status(base, "GET", "/api/channels", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9, 127.0.0.1"}) == 200
        assert _status(base, "GET", "/api/channels", {}) == 200
        assert _status(base, "GET", "/api/channels", {"X-Real-IP": "6.6.6.6"}) == 200
    # Unfixed code sends the first hop, 6.6.6.6, and trusts X-Real-IP from any caller; a raw last-hop read would send 127.0.0.1 second.
    assert received == ["203.0.113.9", "203.0.113.9", "127.0.0.1", "127.0.0.1"]  # C2
