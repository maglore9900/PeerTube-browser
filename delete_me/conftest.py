"""A real Client backend on an ephemeral port, over a users.db under tmp_path.

The Engine address points at a closed port: the profile routes these tests drive either
never call the Engine or refuse before they would.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402
from lib.http_utils import RateLimiter  # noqa: E402
from lib.users_store import ensure_user_schema  # noqa: E402

CLOSED_ENGINE = "http://127.0.0.1:9"


@dataclass
class ClientBackend:
    base: str
    db_path: Path

    def request(self, method: str, path: str, headers: dict[str, str] | None = None,
                body: dict | None = None) -> tuple[int, object]:
        """Send one request; return the status and the parsed JSON body (or None)."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        return status, (json.loads(raw) if raw else None)


@pytest.fixture
def client_backend(tmp_path):
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(
        ("127.0.0.1", 0),
        client_server.ClientBackendHandler,
        conn,
        CLOSED_ENGINE,
        "bridge",
        RateLimiter(1000, 60),
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield ClientBackend(f"http://127.0.0.1:{srv.server_address[1]}", db_path)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
