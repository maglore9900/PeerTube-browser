"""A profile's user action publishes a Like or UndoLike only when it opens or closes the profile's like of the video, and every published event's id is `client-` plus the SHA-256 of the JSON list [actor, uuid, host, event type, like generation].

- Two likes of one video by one profile publish one Like, at generation 1, and the video's signal is (1, 1.0).
- like, undo_like, like publishes Like, UndoLike, Like at generations 1, 1 and 2, the two Like ids differ, and the signal ends at (1, 1.0).
- Two anonymous likes both publish the Like id for actor `anonymous` at generation 0; the Engine counts the second as a duplicate and the signal is (1, 1.0).
- A like naming the video by an upper-case uuid and a mixed-case host publishes the id over the uuid and host the Engine resolved them to, not over the spelling sent.
- undo_like of a video the profile never liked answers 200 and publishes nothing; a like afterwards publishes at generation 1.
- A dislike replacing a like publishes the UndoLike id an undo_like would have used (generation 1) and leaves (0, 0.0); a dislike, and an undo_dislike, of a video the profile does not like publish nothing.
- like, reset, like publishes one Like, though the re-like is stored; the undo_like after it publishes that Like's UndoLike and leaves (0, 0.0).
- undo_like of an imported like publishes nothing, though the import stored the like and the undo removed it; a like afterwards publishes at generation 1.

A real Client backend in bridge mode over a tmp users.db talks to a stub Engine: resolve answers the video lower-cased as its canonical identity, centroids are empty, and ingest runs the real `ingest_interaction_event` on a tmp engine.db, recording each payload and result.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
# conftest's Client harness is imported before the Engine dirs go on sys.path: both trees hold a `server` module.
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import ClientBackend, RateLimiter, client_server, ensure_user_schema  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from data.interaction_events import ensure_interaction_event_schema, ingest_interaction_event  # noqa: E402

HOST = "ids.example"


def _event_id(actor: str, video: dict, event_type: str, generation: int) -> str:
    """The id the requirement derives for one event."""
    return "client-" + hashlib.sha256(json.dumps([actor, video["uuid"], video["host"], event_type, generation]).encode("utf-8")).hexdigest()


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def rig(tmp_path):
    engine_db = sqlite3.connect(tmp_path / "engine.db", check_same_thread=False)
    engine_db.row_factory = sqlite3.Row
    ensure_interaction_event_schema(engine_db)
    lock = threading.Lock()
    events = []

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            status = 200
            if self.path == "/internal/videos/resolve":
                # Lower-casing stands in for the Engine's canonicalisation, so a request spelled otherwise resolves to an identity other than the one it named.
                uuid, host = body["uuid"].lower(), body["host"].lower()
                answer = {"video": {"video_id": "vid-" + uuid, "instance_domain": host, "video_uuid": uuid, "video_url": f"https://{host}/w/{uuid}"}}
            elif self.path == "/internal/dislikes/centroids":
                answer = {"space": "test", "centroids": []}
            elif self.path == "/internal/events/ingest":
                # The real ingest, so a repeated id is collapsed by the Engine's own ON CONFLICT.
                with lock:
                    result = ingest_interaction_event(engine_db, body)
                    events.append((body, result))
                answer = {"ok": True, "duplicates": int(result["duplicate"]), "results": [result]}
            else:
                status, answer = 404, {"error": "Not found"}
            data = json.dumps(answer).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    try:
        with _serving(ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)) as engine_base, _serving(client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield SimpleNamespace(client=ClientBackend(base, tmp_path / "users.db"), engine_db=engine_db, events=events)
    finally:
        conn.close()
        engine_db.close()


def _mint(client) -> tuple[str, dict[str, str]]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], {"X-Profile-Key": body["key"]}


def _video() -> dict[str, str]:
    return {"uuid": uuid4().hex, "host": HOST}


def _act(client, headers, action: str, video: dict) -> int:
    return client.request("POST", "/api/user-action", headers, {"action": action, **video})[0]


def _reaction(client, headers, video: dict) -> dict:
    status, body = client.request("GET", f"/api/profile/reaction?uuid={video['uuid']}&host={video['host']}", headers)
    assert status == 200, body
    return body


def _published(events) -> list[tuple[str, str]]:
    return [(payload["event_type"], payload["event_id"]) for payload, _ in events]


def _signal(engine_db, video: dict) -> tuple[int, float]:
    row = engine_db.execute("SELECT likes_count, signal_score FROM interaction_signals WHERE video_uuid = ? AND instance_domain = ?", (video["uuid"], video["host"])).fetchone()
    return (row["likes_count"], row["signal_score"]) if row else (0, 0.0)


def test_a_repeated_like_publishes_one_like_at_generation_1(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert [_act(rig.client, key, "like", video) for _ in range(2)] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]  # C1
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # C2


def test_like_undo_like_like_publishes_like_undolike_like_under_generations_1_1_2(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert [_act(rig.client, key, action, video) for action in ("like", "undo_like", "like")] == [200, 200, 200]
    published = _published(rig.events)
    assert [event_type for event_type, _ in published] == ["Like", "UndoLike", "Like"]  # C1
    assert published[0][1] != published[2][1]  # C2
    assert published == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1)), ("Like", _event_id(pid, video, "Like", 2))]  # C2
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C2


def test_two_anonymous_likes_carry_one_id_and_the_engine_counts_the_second_as_a_duplicate(rig):
    video = _video()
    assert [_act(rig.client, None, "like", video) for _ in range(2)] == [200, 200]
    assert _published(rig.events) == [("Like", _event_id("anonymous", video, "Like", 0))] * 2  # C2
    assert [result["duplicate"] for _, result in rig.events] == [False, True]  # C2
    assert _signal(rig.engine_db, video) == (1, 1.0)  # C2


def test_a_like_named_in_a_non_canonical_spelling_derives_its_id_from_the_resolved_identity(rig):
    pid, key = _mint(rig.client)
    canonical = _video()
    spelled = {"uuid": canonical["uuid"].upper(), "host": "IDS.Example"}
    assert _act(rig.client, key, "like", spelled) == 200
    assert [payload["object"]["video_uuid"] for payload, _ in rig.events] == [canonical["uuid"]]  # control: the Engine's resolved uuid reached the payload
    assert [payload["object"]["instance_domain"] for payload, _ in rig.events] == [canonical["host"]]  # control: and its resolved host
    assert _published(rig.events) == [("Like", _event_id(pid, canonical, "Like", 1))]  # C2


def test_an_undo_like_of_an_unliked_video_answers_200_and_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert _act(rig.client, key, "undo_like", video) == 200  # C1
    assert rig.events == []  # C1
    # This rig does publish an opening like, and the refused undo advanced no generation.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control


def test_a_dislike_replacing_a_like_publishes_the_undo_likes_id_and_one_of_an_unliked_video_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    liked, unliked = _video(), _video()
    assert [_act(rig.client, key, action, liked) for action in ("like", "dislike")] == [200, 200]
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, liked, "Like", 1)), ("UndoLike", _event_id(pid, liked, "UndoLike", 1))]  # C2
    assert _signal(rig.engine_db, liked) == (0, 0.0)  # C2
    assert _act(rig.client, key, "dislike", unliked) == 200
    assert _reaction(rig.client, key, unliked) == {"liked": False, "disliked": True}  # control: the dislike was stored
    assert _act(rig.client, key, "undo_dislike", unliked) == 200
    assert len(rig.events) == 2  # C1


def test_a_like_after_a_reset_publishes_nothing_and_the_next_undo_like_withdraws_the_first(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert _act(rig.client, key, "like", video) == 200
    assert rig.client.request("POST", "/api/user-profile/reset", key, {})[0] == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the reset removed the like
    assert _act(rig.client, key, "like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the re-like is stored
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like"]  # C1
    assert _act(rig.client, key, "undo_like", video) == 200
    assert [event_type for event_type, _ in _published(rig.events)] == ["Like", "UndoLike"]  # C1
    assert _signal(rig.engine_db, video) == (0, 0.0)  # C1
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1)), ("UndoLike", _event_id(pid, video, "UndoLike", 1))]  # C2: the undo withdraws the first like's generation


def test_an_undo_like_of_an_imported_like_publishes_nothing(rig):
    pid, key = _mint(rig.client)
    video = _video()
    assert rig.client.request("POST", "/api/profile/likes/import", key, {"likes": [video]}) == (200, {"imported": 1})
    assert _reaction(rig.client, key, video) == {"liked": True, "disliked": False}  # control: the import stored the like
    assert _act(rig.client, key, "undo_like", video) == 200
    assert _reaction(rig.client, key, video) == {"liked": False, "disliked": False}  # control: the undo removed it
    assert rig.events == []  # C1
    # The import opened no generation, so the first published like is generation 1.
    assert _act(rig.client, key, "like", video) == 200
    assert _published(rig.events) == [("Like", _event_id(pid, video, "Like", 1))]  # control
