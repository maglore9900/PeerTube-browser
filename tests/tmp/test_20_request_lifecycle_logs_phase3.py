"""Every request the in-process Client backend serves is logged as one `request.start`, then its work records, then one `request.end`, all with one top-level `request_id`.

The real `ClientBackendServer` from the `client_backend` fixture, with `_client_logging` capturing the production `ClientLogFormatter` output, is sent, one connection each: GET /api/health with `X-Request-ID: probe.id-1` and a spaced User-Agent; GET /api/health with no header, then with `bad id`, 65×`a` and `a/b`; GET /nope; GET /api/user-profile while `_rate_limit_check` refuses; POST /api/user-action with body `{`; POST /recommendations with body `{}`, which logs `recommendations.incoming_likes` and, after one retry against the closed Engine port, an `engine.proxy` record. Each request's lines are taken once its handler thread has finished, since request.end is written after the response.

- Each request's records are exactly one `request.start` ("request started") first and one `request.end` ("request finished") last, with no `client.access` record. The start's context is exactly ip, method and url, plus the user agent when one was sent. The end's context is exactly `{status, duration_ms}`: status is the int the client received (200 ×5, 404, 429, 400, 502), and duration_ms is an int no larger than the test's wall-clock time for the request, and at least the 250 ms retry delay on the 502.
- Every record of a request, the 502's two work records included, has a top-level request_id equal to its start's. The valid id is used verbatim; every other id is 32 lowercase hex and distinct from all the rest. No rejected header value appears anywhere in the log.
- On one HTTP/1.1 connection (a test-only `KeepAliveClientHandler` subclass), GET /api/health with `X-Request-ID: ka.first-1` then with no header leave one client port. Each request passes the same window checks, the two ids differ, and the three `[probe] after request` records the handler thread logs after each request and after the client closes carry no request_id.
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path

ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

# client_backend is the conftest fixture itself, imported so pytest serves it here as it does under tests/active.
from conftest import CLOSED_ENGINE, RateLimiter, client_backend, client_server, ensure_user_schema  # noqa: E402,F401
from test_server import _client_logging  # noqa: E402

HEX32_RE = re.compile(r"[0-9a-f]{32}")
VALID_ID = "probe.id-1"
KEEPALIVE_ID = "ka.first-1"
USER_AGENT = "probe agent/1.0 (X11; Linux x86_64)"
REJECTED_IDS = ["bad id", "a" * 65, "a/b"]
JSON_HEADERS = {"Content-Type": "application/json"}
# The proxy sleeps this long before its one retry against the closed Engine port (observed: the 502 answered after 257 ms).
RETRY_DELAY_MS = 250
PROXY_WORK_EVENTS = {"recommendations.incoming_likes", "engine.proxy"}
PROBE_MESSAGE = "[probe] after request"
SETTLE_SECONDS = 10

# Method, path, headers, body, the status the client must get, and the id the request must log (None: a generated one).
SINGLE = [
    {"method": "GET", "path": "/api/health", "headers": {"X-Request-ID": VALID_ID, "User-Agent": USER_AGENT}, "body": None, "status": 200, "id": VALID_ID},
    {"method": "GET", "path": "/api/health", "headers": {}, "body": None, "status": 200, "id": None},
    *({"method": "GET", "path": "/api/health", "headers": {"X-Request-ID": value}, "body": None, "status": 200, "id": None} for value in REJECTED_IDS),
    {"method": "GET", "path": "/nope", "headers": {}, "body": None, "status": 404, "id": None},
    {"method": "GET", "path": "/api/user-profile", "headers": {}, "body": None, "status": 429, "id": None, "refused": True},
    {"method": "POST", "path": "/api/user-action", "headers": JSON_HEADERS, "body": "{", "status": 400, "id": None},
    {"method": "POST", "path": "/recommendations", "headers": JSON_HEADERS, "body": "{}", "status": 502, "id": None},
]
PROXIED = len(SINGLE) - 1
KEEPALIVE = [
    {"method": "GET", "path": "/api/health", "headers": {"X-Request-ID": KEEPALIVE_ID}, "status": 200, "id": KEEPALIVE_ID},
    {"method": "GET", "path": "/api/health", "headers": {}, "status": 200, "id": None},
]


class KeepAliveClientHandler(client_server.ClientBackendHandler):
    """The production handler on HTTP/1.1, so one connection's requests share one handler instance and thread."""

    protocol_version = "HTTP/1.1"

    def handle_one_request(self):
        # Logged on the handler thread once a request has returned, where its id must be gone.
        super().handle_one_request()
        logging.info(PROBE_MESSAGE)


def _settle(baseline: int) -> bool:
    """Wait, bounded, until only `baseline` threads are alive: request.end is logged on the handler thread after the response."""
    deadline = time.time() + SETTLE_SECONDS
    while threading.active_count() > baseline and time.time() < deadline:
        time.sleep(0.01)
    return threading.active_count() == baseline


def _send(port: int, case: dict) -> int:
    """Send one request on its own connection and return the status received."""
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    body = case["body"].encode() if case["body"] is not None else None
    client.request(case["method"], case["path"], body=body, headers=case["headers"])
    resp = client.getresponse()
    resp.read()
    client.close()
    return resp.status


def _is_probe(record: dict) -> bool:
    """Whether the record is the keep-alive handler's after-request marker."""
    return record.get("message") == PROBE_MESSAGE


def _check_window(records: list[dict], case: dict, port: int, ms: float) -> str:
    """Assert one request's records open with its request.start, close with its request.end and all carry one top-level id; return that id."""
    events = [record.get("event") for record in records]
    assert events and events[0] == "request.start" and events[-1] == "request.end", (case["path"], events)  # C1
    # One start and one end: the old send_response-time access line is gone, not kept beside the new end.
    assert events.count("request.start") == 1 and events.count("request.end") == 1, (case["path"], events)  # C1
    assert "client.access" not in events, (case["path"], events)  # C1
    start, end = records[0], records[-1]
    assert (start.get("message"), end.get("message")) == ("request started", "request finished"), (case["path"], start, end)  # C1
    expected_start = {"ip": "127.0.0.1", "method": case["method"], "url": f"http://127.0.0.1:{port}{case['path']}"}
    if "User-Agent" in case["headers"]:
        expected_start["user_agent"] = case["headers"]["User-Agent"]
    assert start.get("context") == expected_start, (case["path"], start)  # C1
    duration = (end.get("context") or {}).get("duration_ms")
    # The old access line carried status as the string "200" and bytes beside it.
    assert end.get("context") == {"status": case["status"], "duration_ms": duration}, (case["path"], end)  # C1
    # One ms of slack: observed requests finish in under 1 ms, where a duration rounded up rather than truncated could exceed the client's own clock.
    assert type(duration) is int and 0 <= duration <= ms + 1, (case["path"], duration, ms)  # C1

    request_id = start.get("request_id")
    assert isinstance(request_id, str) and request_id, (case["path"], start)  # C2
    # Top level on every record, work records included: an id only in context, or none, fails here.
    assert [record.get("request_id") for record in records] == [request_id] * len(records), (case["path"], [(record.get("event"), record.get("request_id")) for record in records])  # C2
    if case["id"] is not None:
        assert request_id == case["id"], (case["path"], request_id)  # C2
    else:
        assert HEX32_RE.fullmatch(request_id), (case["path"], case["headers"], request_id)  # C2
    return request_id


def test_client_logs_one_request_start_and_end_per_request_under_one_top_level_id(client_backend, monkeypatch):
    port = int(client_backend.base.rsplit(":", 1)[1])
    results = []
    with _client_logging(monkeypatch, None) as stream:
        for case in SINGLE:
            before = len(stream.getvalue().splitlines())
            baseline = threading.active_count()
            started = time.perf_counter()
            with monkeypatch.context() as patch:
                if case.get("refused"):
                    patch.setattr(client_server.ClientBackendHandler, "_rate_limit_check", lambda self, path: False)
                status = _send(port, case)
            settled = _settle(baseline)
            ms = (time.perf_counter() - started) * 1000
            results.append({"status": status, "settled": settled, "ms": ms, "lines": stream.getvalue().splitlines()[before:]})
        all_lines = stream.getvalue().splitlines()

    # Control: every request got the status its exit path answers, and every handler thread finished before its lines were taken.
    assert [result["status"] for result in results] == [case["status"] for case in SINGLE], [result["status"] for result in results]
    assert all(result["settled"] for result in results), results
    # Control: every line came through the production JSON formatter.
    assert all(isinstance(json.loads(line), dict) for line in all_lines), all_lines

    ids = []
    for case, result in zip(SINGLE, results):
        ids.append(_check_window([json.loads(line) for line in result["lines"]], case, port, result["ms"]))

    proxied = [json.loads(line) for line in results[PROXIED]["lines"]]
    # Control: the 502 window holds real work records, so the every-record id check above covered more than start and end.
    assert PROXY_WORK_EVENTS <= {record.get("event") for record in proxied[1:-1]}, proxied
    # Measured from the start record: the retry sleep falls inside the request, so a 0 or a seconds value fails.
    assert proxied[-1]["context"]["duration_ms"] >= RETRY_DELAY_MS, proxied[-1]  # C1

    # A constant fallback gives every headerless or rejected request the same id.
    assert len(set(ids)) == len(ids), ids  # C2
    for value in REJECTED_IDS:
        assert all(value not in line for line in all_lines), value  # C2


def test_client_keep_alive_requests_get_distinct_ids_that_never_cross(tmp_path, monkeypatch):
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), KeepAliveClientHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(1000, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        with _client_logging(monkeypatch, None) as stream:
            baseline = threading.active_count()
            started = time.perf_counter()
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            statuses, client_ports = [], []
            for case in KEEPALIVE:
                client.request(case["method"], case["path"], headers=case["headers"])
                # Read before getresponse, which drops the socket when the server closes; http.client then reconnects from a new port.
                client_ports.append(client.sock.getsockname()[1])
                resp = client.getresponse()
                resp.read()
                statuses.append(resp.status)
            client.close()
            settled = _settle(baseline)
            ms = (time.perf_counter() - started) * 1000
            lines = stream.getvalue().splitlines()
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()

    # Control: both requests answered, and the handler thread finished before the lines were taken.
    assert statuses == [case["status"] for case in KEEPALIVE] and settled, (statuses, settled)
    # One connection: both requests left the same client port (observed). A server closing after each response makes http.client reconnect from a new port.
    assert len(client_ports) == 2 and client_ports[0] == client_ports[1], client_ports  # C2
    records = [json.loads(line) for line in lines]
    markers = [index for index, record in enumerate(records) if _is_probe(record)]
    # One handler thread logged a marker after each request and a third after the client closed (observed: three on one connection).
    assert len(markers) == 3 and markers[-1] == len(records) - 1 and markers[2] == markers[1] + 1, [(record.get("event"), record.get("message")) for record in records]  # C2
    # The id is cleared when each request ends, so the next request's records on this thread cannot inherit it.
    assert all("request_id" not in records[index] for index in markers), [records[index] for index in markers]  # C2

    first_id = _check_window(records[:markers[0]], KEEPALIVE[0], port, ms)
    second_id = _check_window(records[markers[0] + 1:markers[1]], KEEPALIVE[1], port, ms)
    # The second request sent no header; carrying the first's id over the connection fails here.
    assert first_id != second_id, (first_id, second_id)  # C2
