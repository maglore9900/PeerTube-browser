"""The Client passes at most the first 50 like entries of one request body to the Engine, on each of the three paths that read `MAX_CLIENT_LIKES`.

- A likes-page body of 60 likes reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the first 50, and is answered 200 with those 50 videos' rows.
- An import of 60 likes reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the first 50, answers `{"imported": 50}`, and leaves the profile liking exactly those 50 videos.
- A keyless `POST /recommendations` carrying 60 likes is answered 200 and forwards one request whose `likes` are the first 50 `{uuid, host}` pairs.

The three paths are listed by hand: they are the `MAX_CLIENT_LIKES` readers the plan's grep found. Every like is well formed, so the Client's sanitising drops none and the first 50 submitted are the first 50 forwarded. The Engine is a stdlib stand-in that records every request it gets and answers the metadata route as the Engine does; the Client is a real `ClientBackendServer` over a `users.db` under `tmp_path`.
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import load_liked_keys  # noqa: E402

HOST = "h.example"
METADATA = "/internal/videos/metadata"
# Sixty known videos; the Engine rows' video_id differs from the uuid, so a stored like is keyed on the row.
VIDEOS = [{"video_id": f"id-{i:02d}", "video_uuid": f"u-{i:02d}", "instance_domain": HOST, "title": f"V{i}"} for i in range(60)]


def _like(uuid: str) -> dict:
    return {"uuid": uuid, "host": HOST}


def _entry(uuid: str) -> dict:
    return {"video_uuid": uuid, "instance_domain": HOST}


LIKES = [_like(f"u-{i:02d}") for i in range(60)]


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
def _client_backend(tmp_path, engine_base):
    """A Client backend on 127.0.0.1:0, as conftest's `client_backend` is built but with its Engine chosen here."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield ClientBackend(base, db_path)
    finally:
        conn.close()


@contextmanager
def _engine(videos):
    """A stand-in Engine that records `(path, json body)` for every request and answers the metadata route from `videos` by uuid and host, in entry order, each video once; any other route gets no rows."""
    table = {f"{v['video_uuid']}::{v['instance_domain']}": v for v in videos}
    received = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"null")
            received.append((self.path, body))
            rows = []
            if self.path == METADATA:
                for entry in body["entries"]:
                    row = table.get(f"{entry.get('video_uuid')}::{entry.get('instance_domain')}")
                    if row is not None and row not in rows:
                        rows.append(row)
            self._answer({"ok": True, "count": len(rows), "rows": rows})

        def do_GET(self):  # noqa: N802
            received.append((self.path, None))
            self._answer({"rows": []})

        def _answer(self, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as base:
        yield base, received


def test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": LIKES})
    # Observed: 60 entries reach the Engine at the current cap of 200; a cap of 49 or 51, or keeping the last 50, also fails here.
    assert received == [(METADATA, {"entries": [_entry(f"u-{i:02d}") for i in range(50)]})]  # C1
    assert (status, [row["video_id"] for row in body["likes"]]) == (200, [f"id-{i:02d}" for i in range(50)])  # C1


def test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": LIKES})
        conn = client_server.connect_db(client.db_path)
        try:
            liked = load_liked_keys(conn, resolve_profile(conn, minted["key"]))
        finally:
            conn.close()
    assert received == [(METADATA, {"entries": [_entry(f"u-{i:02d}") for i in range(50)]})]  # C1
    assert (status, body) == (200, {"imported": 50})  # C1
    assert liked == {(f"id-{i:02d}", HOST) for i in range(50)}  # C1


def test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes(tmp_path):
    with _engine(VIDEOS) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, _ = client.request("POST", "/recommendations", body={"likes": LIKES})
    assert status == 200  # C1
    # The Client adds its own `?limit=48` page size to the forwarded path (observed), which this clause does not concern.
    assert [(urlparse(path).path, body["likes"]) for path, body in received] == [("/recommendations", [_like(f"u-{i:02d}") for i in range(50)])]  # C1
