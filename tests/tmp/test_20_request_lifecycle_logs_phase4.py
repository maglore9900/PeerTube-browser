"""Every Engine call the Client makes while serving a request carries that request's id in `X-Request-ID`, and none outside a request, so one request's id opens and closes a window in both services' logs.

A recording stub Engine, in front of a real `ClientBackendServer` with `ENGINE_PROXY_TIMEOUT_SECONDS` at 0.3 s, sleeps 1 s on the first GET /api/video attempt so the Client retries it, and answers resolve and metadata with one fixed video and ingest with `{"ok": true}`:

- GET /api/video with `X-Request-ID: p4.video-1` reaches the stub twice, each attempt carrying exactly that one header value. The likes page with `p4.likes-1` reaches `/internal/videos/metadata` with it (`_post_json`). An anonymous like with `p4.like-1` reaches `/internal/videos/resolve` and `/internal/events/ingest` (`_publish_to_engine_bridge`) with it.
- GET /api/channels with the rejected `bad id` reaches the stub with the Client's own generated 32-hex id from its request.start, never `bad id`.
- `fetch_metadata_for_entries` and `_publish_to_engine_bridge` called on a fresh thread, and the proxied GET /api/channels on a handler whose `_run_request` sets no id, each reach the stub with no `X-Request-ID` header at all, not an empty one.

Against `engine_client` (the in-process Client in front of the session Engine), with `_client_logging` capturing the Client and the session Engine's log file read for the Engine:

- POST /recommendations?limit=5 and GET /api/video for a whitelist.db video, each with `X-Request-ID: v1.<uuid hex>`, then POST /recommendations?limit=5 and that GET /api/video each with no header and with `bad id`, each log one request.start first and one request.end last in the Client, every record under one id. That id is the supplied one, or 32 lowercase hex distinct from every other. The Engine logs one request.start first and one request.end last under the same id, for the same path, starting no earlier than the Client's request.start and no later than the Client's `engine.proxy` record.
- GET /api/health with `v1.<uuid hex>` logs its Client window under that id, and the id never appears in the Engine log.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

# engine, engine_client and dataset are the conftest fixtures themselves, imported so pytest serves them here as it does under tests/active.
from conftest import ClientBackend, RateLimiter, client_server, dataset, engine, engine_client, ensure_user_schema  # noqa: E402,F401
from lib.engine_api_client import fetch_metadata_for_entries  # noqa: E402
from test_server import _client_logging, _serving  # noqa: E402

REQUEST_ID = "X-Request-ID"
HEX32_RE = re.compile(r"[0-9a-f]{32}")
VIDEO_PATH = "/api/video?id=v1&host=h.example"
VIDEO_ID, LIKES_ID, ACTION_ID = "p4.video-1", "p4.likes-1", "p4.like-1"
REJECTED_ID = "bad id"
# The first /api/video attempt outlasts the patched timeout, so the Client retries it. A dropped connection is not retried (observed: one attempt, 502).
PROXY_TIMEOUT_SECONDS = 0.3
FIRST_ATTEMPT_SLEEP_SECONDS = 1.0
SEED = {"video_id": "v1", "instance_domain": "h.example", "video_uuid": "u1", "video_url": "https://h.example/w/u1"}
LIKES_BODY = {"likes": [{"uuid": "u1", "host": "h.example"}]}
LIKE_ACTION = {"action": "like", "uuid": "u1", "host": "h.example"}
SETTLE_SECONDS = 10


class _RecordingEngine(BaseHTTPRequestHandler):
    """Records each request's method, path and every `X-Request-ID` value in `server.seen`; the first GET /api/video is left unanswered past the Client's timeout."""

    def _answer(self, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self.server.seen.append((self.command, self.path, self.headers.get_all(REQUEST_ID) or []))
        if self.path == VIDEO_PATH and not self.server.dropped:
            self.server.dropped = True
            time.sleep(FIRST_ATTEMPT_SLEEP_SECONDS)
            self.close_connection = True
            return
        self._answer({"rows": []} if self.path.startswith("/api/channels") else {})

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, self.headers.get_all(REQUEST_ID) or []))
        if self.path == "/internal/videos/resolve":
            self._answer({"video": SEED})
        elif self.path == "/internal/videos/metadata":
            self._answer({"ok": True, "count": 1, "rows": [SEED]})
        else:
            self._answer({"ok": True})

    def log_message(self, *args):
        pass


class NoIdClientHandler(client_server.ClientBackendHandler):
    """The production handler with no request id ever set, so its Engine calls run as code outside a request does."""

    def _run_request(self, serve):
        serve()


@contextmanager
def _client(db_path: Path, engine_base: str, handler: type):
    """A Client backend on 127.0.0.1:0 in bridge mode over `engine_base`, served by `handler`."""
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    try:
        with _serving(client_server.ClientBackendServer(("127.0.0.1", 0), handler, conn, engine_base, "bridge", RateLimiter(1000, 60))) as base:
            yield ClientBackend(base, db_path)
    finally:
        conn.close()


def _take(stub) -> list[tuple[str, str, list[str]]]:
    """The requests the stub recorded since the last take."""
    seen = stub.seen[:]
    stub.seen.clear()
    return seen


def _new_start(stream, before: int) -> dict:
    """The first request.start logged after line `before`: the previous request's request.end may trail its response, but its start cannot."""
    records = [json.loads(line) for line in stream.getvalue().splitlines()[before:]]
    return next(record for record in records if record.get("event") == "request.start")


def test_every_engine_call_sends_the_current_request_id_and_none_outside_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(client_server, "ENGINE_PROXY_TIMEOUT_SECONDS", PROXY_TIMEOUT_SECONDS)
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingEngine)
    stub.seen, stub.dropped = [], False
    outside: dict[str, object] = {}

    def call_outside_a_request():
        outside["rows"] = fetch_metadata_for_entries(engine_base, [{"video_uuid": "u1", "instance_domain": "h.example"}])
        outside["rows_seen"] = _take(stub)
        outside["published"] = client_server._publish_to_engine_bridge(engine_base, {"event_type": "Like"})
        outside["published_seen"] = _take(stub)

    with _client_logging(monkeypatch, None) as stream, _serving(stub) as engine_base:
        with _client(tmp_path / "users.db", engine_base, client_server.ClientBackendHandler) as client:
            video = client.request("GET", VIDEO_PATH, headers={REQUEST_ID: VIDEO_ID})
            video_seen = _take(stub)
            likes = client.request("POST", "/api/user-profile/likes", headers={REQUEST_ID: LIKES_ID}, body=LIKES_BODY)
            likes_seen = _take(stub)
            action = client.request("POST", "/api/user-action", headers={REQUEST_ID: ACTION_ID}, body=LIKE_ACTION)
            action_seen = _take(stub)
            before = len(stream.getvalue().splitlines())
            rejected = client.request("GET", "/api/channels", headers={REQUEST_ID: REJECTED_ID})
            rejected_seen = _take(stub)
            generated = _new_start(stream, before).get("request_id")
        # A fresh thread, never a handler's, so no request id was ever set on it.
        worker = threading.Thread(target=call_outside_a_request)
        worker.start()
        worker.join(30)
        with _client(tmp_path / "no-id.db", engine_base, NoIdClientHandler) as no_id_client:
            no_id = no_id_client.request("GET", "/api/channels")
            no_id_seen = _take(stub)

    # Control: the timed-out first attempt and the retry both reached the stub, and the retry was answered.
    assert video == (200, {}), video
    assert [(method, path) for method, path, _ in video_seen] == [("GET", VIDEO_PATH)] * 2, video_seen
    assert [headers for _, _, headers in video_seen] == [[VIDEO_ID]] * 2, video_seen  # C1

    # Control: the likes page made its one metadata call and answered its row.
    assert likes[0] == 200 and likes[1]["likes"] == [SEED], likes
    assert likes_seen == [("POST", "/internal/videos/metadata", [LIKES_ID])], likes_seen  # C1

    # Control: the like was resolved and its publish reached ingest, which accepted it.
    assert action[0] == 200 and action[1]["bridge_ok"] is True, action
    assert [path for _, path, _ in action_seen] == ["/internal/videos/resolve", "/internal/events/ingest"], action_seen
    assert [headers for _, _, headers in action_seen] == [[ACTION_ID]] * 2, action_seen  # C1

    # Control: the rejected header was replaced by a generated id, so a raw copy of the incoming header differs from the current id.
    assert rejected[0] == 200 and isinstance(generated, str) and HEX32_RE.fullmatch(generated), (rejected, generated)
    assert rejected_seen == [("GET", "/api/channels", [generated])], rejected_seen  # C1

    # Control: both calls outside a request reached the stub and got its answer.
    assert not worker.is_alive(), "the outside-a-request calls did not finish"
    assert outside["rows"] == [SEED] and outside["published"] == {"ok": True, "response": {"ok": True}}, outside
    # [] is no header at all: an empty or `None` value would be recorded as one.
    assert outside["rows_seen"] == [("POST", "/internal/videos/metadata", [])], outside  # C1
    assert outside["published_seen"] == [("POST", "/internal/events/ingest", [])], outside  # C1

    assert no_id[0] == 200, no_id
    assert no_id_seen == [("GET", "/api/channels", [])], no_id_seen  # C1


def _settle(baseline: int) -> bool:
    """Wait, bounded, until only `baseline` threads are alive: request.end is logged on the handler thread after the response."""
    deadline = time.time() + SETTLE_SECONDS
    while threading.active_count() > baseline and time.time() < deadline:
        time.sleep(0.01)
    return threading.active_count() == baseline


def _engine_lines(log_path: Path) -> list[dict]:
    """The session Engine log's JSON records; tracebacks socketserver prints there are skipped."""
    records = []
    for line in log_path.read_text().splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _engine_records(log_path: Path, request_id: str) -> list[dict]:
    """The Engine's records under `request_id`, waiting, bounded, for its request.end, which the Engine logs after its response and so can trail the Client."""
    deadline = time.time() + SETTLE_SECONDS
    while True:
        records = [record for record in _engine_lines(log_path) if record.get("request_id") == request_id]
        if any(record.get("event") == "request.end" for record in records) or time.time() > deadline:
            return records
        time.sleep(0.05)


def _client_window(lines: list[str], expected_id: str | None) -> list[dict]:
    """Assert one request's Client records open with its request.start, close with its request.end and all carry one id, the expected one or a generated 32-hex; return them."""
    records = [json.loads(line) for line in lines]
    events = [record.get("event") for record in records]
    assert events and events[0] == "request.start" and events[-1] == "request.end", events  # C2
    assert events.count("request.start") == 1 and events.count("request.end") == 1, events  # C2
    request_id = records[0].get("request_id")
    assert [record.get("request_id") for record in records] == [request_id] * len(records), [(record.get("event"), record.get("request_id")) for record in records]  # C2
    if expected_id is not None:
        assert request_id == expected_id, (expected_id, request_id)  # C2
    else:
        assert isinstance(request_id, str) and HEX32_RE.fullmatch(request_id), request_id  # C2
    return records


def test_one_request_id_spans_the_client_and_engine_windows(engine_client, engine, dataset, monkeypatch):
    row = dataset.execute("SELECT video_id, instance_domain FROM videos LIMIT 1").fetchone()
    video_path = f"/api/video?id={row['video_id']}&host={row['instance_domain']}"
    supplied_rec, supplied_video, supplied_health = ("v1." + uuid4().hex for _ in range(3))
    # The conftest `engine` fixture carries its log file as `db_path`.
    engine_log = Path(engine.db_path)
    # Health precedes the headerless requests, so by the time their Engine windows are read any Engine line under the health id would be there too.
    cases = [
        {"method": "POST", "path": "/recommendations?limit=5", "body": {}, "headers": {REQUEST_ID: supplied_rec}, "id": supplied_rec, "engine_path": "/recommendations"},
        {"method": "GET", "path": video_path, "body": None, "headers": {REQUEST_ID: supplied_video}, "id": supplied_video, "engine_path": "/api/video"},
        {"method": "GET", "path": "/api/health", "body": None, "headers": {REQUEST_ID: supplied_health}, "id": supplied_health, "engine_path": None},
        {"method": "POST", "path": "/recommendations?limit=5", "body": {}, "headers": {}, "id": None, "engine_path": "/recommendations"},
        {"method": "POST", "path": "/recommendations?limit=5", "body": {}, "headers": {REQUEST_ID: REJECTED_ID}, "id": None, "engine_path": "/recommendations"},
        {"method": "GET", "path": video_path, "body": None, "headers": {}, "id": None, "engine_path": "/api/video"},
        {"method": "GET", "path": video_path, "body": None, "headers": {REQUEST_ID: REJECTED_ID}, "id": None, "engine_path": "/api/video"},
    ]
    results = []
    with _client_logging(monkeypatch, None) as stream:
        for case in cases:
            before = len(stream.getvalue().splitlines())
            baseline = threading.active_count()
            status, _ = engine_client.request(case["method"], case["path"], headers=case["headers"], body=case["body"])
            settled = _settle(baseline)
            results.append({"status": status, "settled": settled, "lines": stream.getvalue().splitlines()[before:]})

    # Control: the feeds and health answered, and every handler thread finished before its lines were taken. GET /api/video is not checked: the session Engine's whitelist.db has no videos.language column, so it drops the connection (observed: Client 502, Engine request.end status "-"), and both windows are still logged.
    assert [result["status"] for case, result in zip(cases, results) if case["engine_path"] != "/api/video"] == [200] * 4, [result["status"] for result in results]
    assert all(result["settled"] for result in results), results

    ids = []
    for case, result in zip(cases, results):
        client_records = _client_window(result["lines"], case["id"])
        request_id = client_records[0]["request_id"]
        ids.append(request_id)
        if case["engine_path"] is None:
            continue
        proxy = [record for record in client_records if record.get("event") == "engine.proxy"]
        # Control: the Client made one Engine call inside this window.
        assert len(proxy) == 1, (case["path"], client_records)
        engine_records = _engine_records(engine_log, request_id)
        events = [record.get("event") for record in engine_records]
        # An Engine that never received the id logs this request under its own, so nothing is found under the Client's.
        assert events and events[0] == "request.start" and events[-1] == "request.end", (case["path"], request_id, events)  # C2
        assert events.count("request.start") == 1 and events.count("request.end") == 1, (case["path"], events)  # C2
        assert urlparse(engine_records[0]["context"]["url"]).path == case["engine_path"], (case["path"], engine_records[0])  # C2
        # Same wall clock, ms-truncated alike: the Engine's window opens inside the Client's, before the Client logs the Engine's answer.
        assert client_records[0]["ts"] <= engine_records[0]["ts"] <= proxy[0]["ts"], (case["path"], client_records[0]["ts"], engine_records[0]["ts"], proxy[0]["ts"])  # C2

    # A constant fallback gives the four generated requests one id; reusing a supplied one fails too.
    assert len(set(ids)) == len(ids), ids  # C2
    # Control: an id is found in the Engine log only when the Client sent it there, so the windows found above are not there by default.
    assert [record for record in _engine_lines(engine_log) if record.get("request_id") == supplied_health] == []
