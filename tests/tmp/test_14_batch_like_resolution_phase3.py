"""The Client resolves a request's browser likes with one Engine call, to `/internal/videos/metadata`, and an import records a like from each returned row whose video the profile has not disliked.

- A likes-page body of three likes, a repeat and an unknown one reaches the Engine as one `/internal/videos/metadata` request whose `entries` are the five submitted `{video_uuid, instance_domain}` pairs, in order, and is answered 200 with the three known rows in submitted order.
- An empty body, an empty `likes` list, and a list of only malformed likes are each answered 200 with `likes == []` and reach the Engine not at all; a well-formed like sent next does reach it.
- Importing two clean likes, one the profile dislikes and an unknown one reaches the Engine as one `/internal/videos/metadata` request carrying the four pairs, answers `{"imported": 2}`, and leaves the profile liking exactly the two clean videos, stored with the `video_id` of their Engine rows and with a non-null `video_uuid` and `instance_domain` (which the row and the submitted like share, so which one they are taken from is not told apart).

The Engine is a stdlib stand-in that records every request it gets and answers the metadata route as the Engine does: one row per known uuid entry, in entry order, each video once. The Client is a real `ClientBackendServer` over a `users.db` under `tmp_path`.
"""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402
from lib.dislikes import write_dislike  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import load_liked_keys  # noqa: E402

HOST = "h.example"
METADATA = "/internal/videos/metadata"
# Engine rows; each video_id differs from its uuid, so a like stored from the browser's entry rather than the row is told apart.
A = {"video_id": "id-a", "video_uuid": "u-a", "instance_domain": HOST, "title": "A"}
B = {"video_id": "id-b", "video_uuid": "u-b", "instance_domain": HOST, "title": "B"}
C = {"video_id": "id-c", "video_uuid": "u-c", "instance_domain": HOST, "title": "C"}


def _like(uuid: str) -> dict:
    return {"uuid": uuid, "host": HOST}


def _entry(uuid: str) -> dict:
    return {"video_uuid": uuid, "instance_domain": HOST}


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


def test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order(tmp_path):
    likes = [_like("u-c"), _like("u-a"), _like("u-c"), _like("u-x"), _like("u-b")]
    with _engine([A, B, C]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, body = client.request("POST", "/api/user-profile/likes", body={"likes": likes})
    # The per-like resolve loop records a `/internal/videos/resolve` request first (observed: it then answers 502 here).
    assert received == [(METADATA, {"entries": [_entry("u-c"), _entry("u-a"), _entry("u-c"), _entry("u-x"), _entry("u-b")]})]  # C1
    assert (status, body["likes"]) == (200, [C, A, B])  # C1: submitted order, not the table's [A, B, C]; the repeat and u-x omitted


def test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine(tmp_path):
    malformed = ["x", {"uuid": "u-a"}, {"host": HOST}, {"uuid": "   ", "host": HOST}, {"uuid": "u-a", "host": 7}]
    with _engine([A]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        replies = [client.request("POST", "/api/user-profile/likes", body=body) for body in ({}, {"likes": []}, {"likes": malformed})]
        assert received == []  # C1
        client.request("POST", "/api/user-profile/likes", body={"likes": [_like("u-a")]})
    assert [(status, body["likes"]) for status, body in replies] == [(200, [])] * 3  # C1
    assert received, "control: a well-formed like reaches this Engine and is recorded, so the empty record above is not a deaf Engine"
    assert received == [(METADATA, {"entries": [_entry("u-a")]})]  # C1


def test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked(tmp_path):
    with _engine([A, B, C]) as (engine_base, received), _client_backend(tmp_path, engine_base) as client:
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        conn = client_server.connect_db(client.db_path)
        try:
            profile_id = resolve_profile(conn, minted["key"])
            assert profile_id == minted["profile_id"]  # control: the second connection sees the minted profile
            with conn:
                write_dislike(conn, profile_id, B, None)
            # The disliked video sits between the clean ones, so skipping the first or the last returned row imports one, not two.
            status, body = client.request("POST", "/api/profile/likes/import", headers={"X-Profile-Key": minted["key"]}, body={"likes": [_like("u-a"), _like("u-b"), _like("u-x"), _like("u-c")]})
            liked = load_liked_keys(conn, profile_id)
            stored = {(row["video_id"], row["video_uuid"], row["instance_domain"]) for row in conn.execute("SELECT video_id, video_uuid, instance_domain FROM likes WHERE user_id = ?", (profile_id,))}
        finally:
            conn.close()
    assert received == [(METADATA, {"entries": [_entry("u-a"), _entry("u-b"), _entry("u-x"), _entry("u-c")]})]  # C1
    assert (status, body) == (200, {"imported": 2})  # C2: observed 3 when the dislike is ignored or a like is keyed on the uuid, 1 when the first or last row is skipped
    assert liked == {("id-a", HOST), ("id-c", HOST)}  # C2: the rows' video_ids, and not id-b, which the profile dislikes
    assert stored == {("id-a", "u-a", HOST), ("id-c", "u-c", HOST)}  # C2: each like carries its video_uuid and host, not nulls; row and entry share them, so their source is not told apart
