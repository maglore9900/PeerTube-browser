import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import RateLimiter, client_server  # noqa: E402
from test_server import _client_backend, _serving, _status  # noqa: E402


def _stub(received, delay):
    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            received.append((url.path, parse_qs(url.query)))
            time.sleep(delay)
            body = json.dumps({"ok": True}).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError) as exc:
                print("stub write failed", repr(exc))

        def log_message(self, format, *args):
            pass
    return EngineStub


def test_probe(tmp_path, monkeypatch):
    print("has route timeout:", hasattr(client_server, "ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS"))
    received = []
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _stub(received, 0))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        for q in ("id=u1&host=h.example", "id=u1&host=h.example&user_id=x", "id=u1&host=h.example&refresh_cache=1", "id=u1&id=u2&host=h.example"):
            print("refresh", q, _status(base, "GET", "/api/video/refresh?" + q, {}))
        print("video", _status(base, "GET", "/api/video?id=u1&host=h.example&user_id=x", {}))
    print("received", received)
    received.clear()
    monkeypatch.setattr(client_server, "ENGINE_PROXY_TIMEOUT_SECONDS", 0.3)
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _stub(received, 1.5))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        started = time.monotonic()
        print("slow video", _status(base, "GET", "/api/video?id=u1&host=h.example", {}), time.monotonic() - started)
        print("received", received)
        started = time.monotonic()
        print("slow refresh", _status(base, "GET", "/api/video/refresh?id=u1&host=h.example", {}), time.monotonic() - started)
        print("received", received)
