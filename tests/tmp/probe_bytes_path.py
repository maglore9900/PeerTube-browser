import http.client
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "backend"))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402


def _req(port, method, path, headers, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    out = (resp.status, resp.getheaders(), data)
    conn.close()
    return out


def test_probe(tmp_path):
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, "http://127.0.0.1:9", "bridge", RateLimiter(1000, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    minted = _req(port, "POST", "/api/profile", {}, b"")
    key = json.loads(minted[2])["key"]
    print("MINT", minted[0])
    for origin in ("https://dev.example:8443", "https://evil.example", "*", None):
        headers = {"X-Profile-Key": key}
        if origin is not None:
            headers["Origin"] = origin
        got = _req(port, "POST", "/api/profile/blocks/remove", headers, json.dumps({"kind": "account", "account_url": "https://x.example/a/b"}).encode())
        print("REMOVE", origin, got[0], got[1], got[2])
    got = _req(port, "POST", "/api/profile/blocks/remove", {"X-Profile-Key": key}, b"")
    print("REMOVE-EMPTY-BODY", got[0], got[2])
    srv.shutdown()
    srv.server_close()
    conn.close()

    seen = []

    class Echo(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Origin"))
            self.send_response(200)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    echo = HTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=echo.serve_forever, daemon=True).start()
    for origin in ("HTTP://127.0.0.1:5173", "http://127.0.0.1:5173/"):
        _req(echo.server_address[1], "GET", "/", {"Origin": origin}, None)
    echo.shutdown()
    echo.server_close()
    print("RECEIVED", seen)
    print("PARSER-EXISTS", hasattr(client_server, "parse_cors_origins"))
