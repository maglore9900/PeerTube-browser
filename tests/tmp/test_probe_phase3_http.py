from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402


def _req(base, method, path, headers):
    req = urllib.request.Request(base + path, method=method, data=b"{}" if method == "POST" else None)
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_probe(tmp_path):
    captured = []

    class Engine(BaseHTTPRequestHandler):
        def do_GET(self):
            captured.append(dict(self.headers.items()))
            body = json.dumps({"rows": []}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    eng = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
    threading.Thread(target=eng.serve_forever, daemon=True).start()
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, f"http://127.0.0.1:{eng.server_address[1]}", "bridge", RateLimiter(2, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    out = []
    out.append([_req(base, "GET", "/api/user-profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}) for i in (1, 2, 3)])
    out.append(_req(base, "GET", "/api/user-profile", {"X-Forwarded-For": "198.51.100.4, 203.0.113.10"}))
    out.append([_req(base, "POST", "/api/profile", {"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"})[0] for i in range(1, 7)])
    out.append(_req(base, "POST", "/api/profile", {"X-Forwarded-For": "198.51.100.9, 203.0.113.10"})[0])
    srv2 = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, f"http://127.0.0.1:{eng.server_address[1]}", "bridge", RateLimiter(100, 60))
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    base2 = f"http://127.0.0.1:{srv2.server_address[1]}"
    out.append(_req(base2, "GET", "/api/channels", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}))
    out.append(_req(base2, "GET", "/api/channels", {}))
    out.append(_req(base2, "GET", "/api/channels", {"X-Real-IP": "6.6.6.6"}))
    print("OUT", out)
    print("CAPTURED", captured)
    for s in (srv, srv2, eng):
        s.shutdown()
        s.server_close()
    conn.close()
    assert False
