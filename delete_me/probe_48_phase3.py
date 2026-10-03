from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
_spec = importlib.util.spec_from_file_location("probe_client_server", BACKEND_DIR / "server.py")
client_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(client_server)
from lib.http_utils import RateLimiter  # noqa: E402
from lib.profiles import mint_profile  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402
from lib import engine_api_client  # noqa: E402


def _get(base, path, headers):
    req = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_probe(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGINE_BRIDGE_TOKEN", "probe-token")
    seen = []

    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append((self.command, self.path, dict(self.headers), body))
            data = json.dumps({"video": {"video_id": "v1", "instance_domain": "h.example", "video_uuid": "u1"}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    stub = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    engine_base = f"http://127.0.0.1:{stub.server_address[1]}"
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    _, key = mint_profile(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    print("translate keyless:", _get(base, "/api/translate?id=a&host=b", {}))
    print("translate keyed:", _get(base, "/api/translate?id=a&host=b", {"X-Profile-Key": key}))
    print("user-profile 1:", _get(base, "/api/user-profile", {}))
    print("user-profile 2:", _get(base, "/api/user-profile", {}))
    # An existing bridge call, to see the headers the stub receives.
    print("block add:", _get(base, "/api/health", {}))
    req = urllib.request.Request(base + "/api/profile/blocks", data=json.dumps({"kind": "channel", "uuid": "u1", "host": "h.example"}).encode(), method="POST", headers={"X-Profile-Key": key, "X-Request-ID": "probe-req-1", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("block add status", resp.status)
    except urllib.error.HTTPError as exc:
        print("block add status", exc.code, exc.read())
    for method, path, headers, body in seen:
        print("stub saw", method, path, {k: v for k, v in headers.items() if k.lower() in ("x-bridge-token", "x-request-id", "content-type")}, body)
    started = time.monotonic()
    try:
        engine_api_client._post_json("http://127.0.0.1:9/internal/translate", {"id": "a"})
    except engine_api_client.EngineApiError as exc:
        print("closed port:", repr(exc), "after", round(time.monotonic() - started, 3), "s")
    print("has fetch_translate:", hasattr(engine_api_client, "fetch_translate"), "has _sanitize_query:", hasattr(client_server, "_sanitize_query"))
    srv.shutdown()
    srv.server_close()
    stub.shutdown()
    stub.server_close()
    conn.close()
