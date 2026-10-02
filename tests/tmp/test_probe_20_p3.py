import http.client
import json
import logging
import sys
import threading
import time
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
sys.path.insert(0, str(ACTIVE))
from conftest import CLOSED_ENGINE, RateLimiter, client_backend, client_server, ensure_user_schema  # noqa: E402,F401
from test_server import _client_logging  # noqa: E402


def _send(base, method, path, headers, body=None):
    port = int(base.rsplit(":", 1)[1])
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


def test_probe_single(client_backend, monkeypatch):
    with _client_logging(monkeypatch, None) as stream:
        cases = [
            ("GET", "/api/health", {"X-Request-ID": "probe.id-1", "User-Agent": "probe agent/1.0 (X11; Linux x86_64)"}, None),
            ("GET", "/api/health", {}, None),
            ("GET", "/nope", {}, None),
            ("POST", "/api/user-action", {"Content-Type": "application/json"}, b"{"),
            ("POST", "/recommendations", {"Content-Type": "application/json"}, b"{}"),
        ]
        for method, path, headers, body in cases:
            before = len(stream.getvalue().splitlines())
            started = time.perf_counter()
            status = _send(client_backend.base, method, path, headers, body)
            got = time.perf_counter()
            time.sleep(0.3)
            print("CASE", method, path, status, "resp_ms", round((got - started) * 1000), "base", client_backend.base)
            for line in stream.getvalue().splitlines()[before:]:
                print("  LINE", line)
        with monkeypatch.context() as m:
            m.setattr(client_server.ClientBackendHandler, "_rate_limit_check", lambda self, path: False)
            before = len(stream.getvalue().splitlines())
            status = _send(client_backend.base, "GET", "/api/user-profile", {}, None)
            time.sleep(0.3)
            print("CASE 429", status)
            for line in stream.getvalue().splitlines()[before:]:
                print("  LINE", line)
    print("MAIN THREAD", threading.current_thread().name)
    assert False


class KeepAliveClientHandler(client_server.ClientBackendHandler):
    protocol_version = "HTTP/1.1"

    def handle_one_request(self):
        super().handle_one_request()
        logging.info("[probe] after request")


def test_probe_keepalive(tmp_path, monkeypatch):
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), KeepAliveClientHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(1000, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with _client_logging(monkeypatch, None) as stream:
            client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            ports = []
            for headers in ({"X-Request-ID": "ka.first-1"}, {}):
                client.request("GET", "/api/health", headers=headers)
                ports.append(client.sock.getsockname()[1])
                resp = client.getresponse()
                resp.read()
                print("STATUS", resp.status, resp.getheader("connection"))
            client.close()
            time.sleep(0.5)
            print("PORTS", ports)
            for line in stream.getvalue().splitlines():
                print("  LINE", line)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
    assert False
