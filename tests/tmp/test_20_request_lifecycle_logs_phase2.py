"""Every request a real `SimilarHandler` serves is logged as one `request.start`, then its work records, then one `request.end`, all under one request id that is gone once the request returns.

An Engine child runs `SimilarServer`s on ephemeral ports with an `EngineJsonFormatter` handler on a `StringIO` as the only root handler, and sends, one connection each: GET /api/health with `X-Request-ID: probe.id-1` and a spaced User-Agent; GET /api/health with no header, then with `bad id`, 65×`a` and `a/b`; GET /nope; GET /api/channels with the real `RateLimiter` already spent for that key; POST /recommendations with body `{`; POST /recommendations?mode=bogus with body `{}`, which reaches `_handle_similar`; GET /api/channels on a server with a 0.2 s statement timeout while the child holds its `db_lock` for 0.3 s, so the real progress handler interrupts the real channels count over 20 000 rows; and, on one HTTP/1.1 connection, GET /nope with `X-Request-ID: ka.first-1`, then after 300 ms idle GET /api/health with no header. Every handler logs `[probe] after request` on its own thread after each `handle_one_request` returns.

- Each request's records are exactly one `request.start` first and one `request.end` last, with no `access`/`access.start` record. The start's context is exactly ip, method and url, plus the user agent when one was sent. The end's context is exactly `{status, duration_ms}`: status is the int the client received (200, 404, 429, 400, 400, 503, then 404 and 200 on the keep-alive connection), and duration_ms is an int no larger than the child's wall-clock time for the request and at least the 200 ms statement timeout on the interrupted 503.
- Every record of a request carries its request id. That covers the 503's `statement.timeout.info` WARNING, and the bogus-mode request's `[recommendations]` record, its `[similar-server][<id>]` record and its `request.end`, logged after `_handle_similar` clears its context. The valid ids are used verbatim. Every other id is 32 lowercase hex and distinct from all the rest. No rejected header value appears anywhere in the log.
- Both keep-alive requests leave one client port and are served by one handler thread, which logs three markers. Each one's duration_ms is bounded by its own wall-clock time, from its send to the next response (or the thread settling), so the idle gap is not in the second's. The two ids differ, and the records of each carry only that request's id. Every `[probe] after request` record, on HTTP/1.0 and on the keep-alive thread between and after its requests, carries no request id.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
HEX32_RE = re.compile(r"[0-9a-f]{32}")
VALID_ID = "probe.id-1"
KEEPALIVE_ID = "ka.first-1"
USER_AGENT = "probe agent/1.0 (X11; Linux x86_64)"
REJECTED_IDS = ["bad id", "a" * 65, "a/b"]
STATEMENT_TIMEOUT_MS = 200
LOCK_HOLD_MS = 300
KEEPALIVE_GAP_MS = 300
PROBE_MESSAGE = "[probe] after request"

# Sends each request on its own connection, waits for its handler thread to finish (request.end is written after the response), and prints each request's log lines.
_LIFECYCLE_CHILD = r'''
import http.client, inspect, io, json, logging, sys, threading, time
from pathlib import Path
import server
from data.db import connect_db
from handlers.similar import SimilarHandler
from http_utils import RateLimiter
from logging_profiles import EngineJsonFormatter

stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(EngineJsonFormatter())
root = logging.getLogger()
root.handlers[:] = [handler]
root.setLevel(logging.INFO)
cases = json.loads(sys.argv[2])

class ProbeHandler(SimilarHandler):
    # Logged on the handler thread once a request has returned, where its id must be gone.
    def handle_one_request(self):
        super().handle_one_request()
        logging.info("[probe] after request")

class KeepAliveHandler(ProbeHandler):
    protocol_version = "HTTP/1.1"

conn = connect_db(Path(sys.argv[1]))
# Enough rows that the channels count runs past the progress handler's 10 000-instruction interval, where an expired deadline interrupts it.
conn.execute("CREATE TABLE channels (channel_id TEXT, channel_name TEXT, display_name TEXT, instance_domain TEXT, videos_count INTEGER, followers_count INTEGER, avatar_url TEXT, health_status TEXT, health_checked_at INTEGER, health_error TEXT, channel_url TEXT, last_error TEXT, last_error_at INTEGER, last_error_source TEXT)")
conn.execute("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20000) INSERT INTO channels (channel_id, channel_name, videos_count, followers_count) SELECT 'c' || i, 'c' || i, i, i FROM n")
conn.commit()
args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
def start(cls):
    srv = server.SimilarServer(("127.0.0.1", 0), cls, **{**args, "db": conn, "default_limit": 8})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
servers = {"main": start(ProbeHandler), "interrupted": start(ProbeHandler), "keepalive": start(KeepAliveHandler)}
servers["interrupted"].statement_timeout_seconds = cases["statement_timeout_ms"] / 1000
baseline = threading.active_count()

def settle():
    deadline = time.time() + 10
    while threading.active_count() > baseline and time.time() < deadline:
        time.sleep(0.01)
    return threading.active_count() == baseline

def lines():
    return stream.getvalue().splitlines()

out = {"ports": {name: srv.server_address[1] for name, srv in servers.items()}, "requests": []}
for case in cases["single"]:
    srv = servers[case["server"]]
    srv.rate_limiter = None
    if case.get("spent"):
        # The real limiter, its one slot for this ip and path already taken.
        srv.rate_limiter = RateLimiter(1, 3600)
        srv.rate_limiter.allow("127.0.0.1:" + case["path"].split("?")[0])
    if case.get("hold_lock"):
        # The handler waits on the lock past its deadline, so the query it then runs is interrupted by the real progress handler.
        srv.db_lock.acquire()
        threading.Timer(cases["lock_hold_ms"] / 1000, srv.db_lock.release).start()
    before = len(lines())
    started = time.perf_counter()
    client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
    body = case["body"].encode() if case["body"] is not None else None
    client.request(case["method"], case["path"], body=body, headers=case["headers"])
    resp = client.getresponse()
    resp.read()
    client.close()
    settled = settle()
    out["requests"].append({"status": resp.status, "settled": settled, "ms": (time.perf_counter() - started) * 1000, "lines": lines()[before:]})

before = len(lines())
client = http.client.HTTPConnection("127.0.0.1", servers["keepalive"].server_address[1], timeout=30)
statuses, client_ports, sent, answered = [], [], [], []
for index, case in enumerate(cases["keepalive"]):
    if index:
        # Idle on the open connection: a timer started when the connection opened, or before the next request line arrived, counts this gap.
        time.sleep(cases["keepalive_gap_ms"] / 1000)
    sent.append(time.perf_counter())
    client.request("GET", case["path"], headers=case["headers"])
    # Read before getresponse, which drops the socket when the server closes; http.client then reconnects from a new port.
    client_ports.append(client.sock.getsockname()[1])
    resp = client.getresponse()
    resp.read()
    answered.append(time.perf_counter())
    statuses.append(resp.status)
client.close()
settled = settle()
# On one thread a request's end is logged before the next request is read, so before the next response arrives; the last one's before the thread settles.
bounds = answered[1:] + [time.perf_counter()]
out["keepalive"] = {"statuses": statuses, "client_ports": client_ports, "settled": settled, "ms": [(bound - at) * 1000 for at, bound in zip(sent, bounds)], "lines": lines()[before:]}
print(json.dumps(out))
'''

# Server, method, path, headers, body, the status the client must get, and the id the request must log (None: a generated one).
SINGLE = [
    {"server": "main", "method": "GET", "path": "/api/health", "headers": {"X-Request-ID": VALID_ID, "User-Agent": USER_AGENT}, "body": None, "status": 200, "id": VALID_ID},
    {"server": "main", "method": "GET", "path": "/api/health", "headers": {}, "body": None, "status": 200, "id": None},
    *({"server": "main", "method": "GET", "path": "/api/health", "headers": {"X-Request-ID": value}, "body": None, "status": 200, "id": None} for value in REJECTED_IDS),
    {"server": "main", "method": "GET", "path": "/nope", "headers": {}, "body": None, "status": 404, "id": None},
    {"server": "main", "method": "GET", "path": "/api/channels", "headers": {}, "body": None, "status": 429, "id": None, "spent": True},
    {"server": "main", "method": "POST", "path": "/recommendations", "headers": {"Content-Type": "application/json"}, "body": "{", "status": 400, "id": None},
    {"server": "main", "method": "POST", "path": "/recommendations?mode=bogus", "headers": {"Content-Type": "application/json"}, "body": "{}", "status": 400, "id": None},
    {"server": "interrupted", "method": "GET", "path": "/api/channels", "headers": {}, "body": None, "status": 503, "id": None, "hold_lock": True},
]
KEEPALIVE = [
    {"path": "/nope", "headers": {"X-Request-ID": KEEPALIVE_ID}, "status": 404, "id": KEEPALIVE_ID},
    {"path": "/api/health", "headers": {}, "status": 200, "id": None},
]
BOGUS_MODE, INTERRUPTED = 8, 9


def _run_child(tmp_path: Path) -> dict:
    """Run the lifecycle child on a DB holding only a channels table and return its report."""
    cases = {"single": SINGLE, "keepalive": KEEPALIVE, "statement_timeout_ms": STATEMENT_TIMEOUT_MS, "lock_hold_ms": LOCK_HOLD_MS, "keepalive_gap_ms": KEEPALIVE_GAP_MS}
    run = subprocess.run([str(ENGINE_PY), "-c", _LIFECYCLE_CHILD, str(tmp_path / "engine.db"), json.dumps(cases)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-4000:]
    return json.loads(run.stdout)


def _is_probe(record: dict) -> bool:
    """Whether the record is the child's after-request marker."""
    return record.get("message") == PROBE_MESSAGE


def _check_window(records: list[dict], case: dict, port: int, ms: float) -> str:
    """Assert one request's records (markers removed) open with its request.start, close with its request.end and all carry one id; return that id."""
    events = [record.get("event") for record in records]
    assert events and events[0] == "request.start" and events[-1] == "request.end", (case["path"], events)  # C1
    # One start and one end: the old send_response-time access line is gone, not kept beside the new end.
    assert events.count("request.start") == 1 and events.count("request.end") == 1, (case["path"], events)  # C1
    assert not {"access", "access.start"} & set(events), (case["path"], events)  # C1
    start, end = records[0], records[-1]
    expected_start = {"ip": "127.0.0.1", "method": case["method"], "url": f"http://127.0.0.1:{port}{case['path']}"}
    if "User-Agent" in case["headers"]:
        expected_start["user_agent"] = case["headers"]["User-Agent"]
    assert start.get("context") == expected_start, (case["path"], start)  # C1
    duration = (end.get("context") or {}).get("duration_ms")
    # The old access line carried status as the string "200" and bytes beside it.
    assert end.get("context") == {"status": case["status"], "duration_ms": duration}, (case["path"], end)  # C1
    assert type(duration) is int and 0 <= duration <= ms, (case["path"], duration, ms)  # C1

    request_id = start.get("request_id")
    assert isinstance(request_id, str) and request_id, (case["path"], start)  # C2
    # Work records included: a record with no id, or another id (the old 6-hex `[similar-server][id]`), fails here.
    assert [record.get("request_id") for record in records] == [request_id] * len(records), (case["path"], [(record.get("event"), record.get("request_id")) for record in records])  # C2
    if case["id"] is not None:
        assert request_id == case["id"], (case["path"], request_id)  # C2
    else:
        assert HEX32_RE.fullmatch(request_id), (case["path"], case["headers"], request_id)  # C2
    return request_id


def test_engine_logs_one_request_start_and_end_per_request_under_one_id_cleared_after(tmp_path):
    report = _run_child(tmp_path)
    requests = report["requests"]
    # Control: every request got the status its exit path answers, and every handler thread finished before its lines were taken.
    assert [request["status"] for request in requests] == [case["status"] for case in SINGLE], [request["status"] for request in requests]
    assert report["keepalive"]["statuses"] == [case["status"] for case in KEEPALIVE], report["keepalive"]["statuses"]
    assert all(request["settled"] for request in requests) and report["keepalive"]["settled"], report
    all_lines = [line for request in requests for line in request["lines"]] + report["keepalive"]["lines"]
    # Control: every line came through the production formatter.
    parsed = [json.loads(line) for line in all_lines]
    assert all(isinstance(record, dict) for record in parsed), all_lines

    ids = []
    for case, request in zip(SINGLE, requests):
        records = [json.loads(line) for line in request["lines"]]
        markers = [record for record in records if _is_probe(record)]
        # Control: the marker was logged once, after the request returned.
        assert len(markers) == 1 and _is_probe(records[-1]), (case["path"], records)
        assert "request_id" not in markers[0], (case["path"], markers[0])  # C2
        window = [record for record in records if not _is_probe(record)]
        ids.append(_check_window(window, case, report["ports"][case["server"]], request["ms"]))

    # The bogus-mode request reached _handle_similar: its own prefixed record is in the window, so the prefix id is the shared one.
    bogus = [json.loads(line) for line in requests[BOGUS_MODE]["lines"]]
    assert any(record.get("message", "").startswith(f"[similar-server][{ids[BOGUS_MODE]}] start limit=8") for record in bogus), bogus  # C2
    assert any(record.get("event") == "recommendations.incoming_likes_body" for record in bogus), bogus  # C2
    interrupted = [json.loads(line) for line in requests[INTERRUPTED]["lines"]]
    timeouts = [record for record in interrupted if record.get("event") == "statement.timeout.info"]
    assert len(timeouts) == 1 and timeouts[0]["level"] == "WARNING" and timeouts[0].get("request_id") == ids[INTERRUPTED], interrupted  # C2
    # Measured from the start record: the interrupt can only fire once the statement deadline has passed, so a 0 or a seconds value fails.
    assert interrupted[-2]["context"]["duration_ms"] >= STATEMENT_TIMEOUT_MS, interrupted[-2]  # C1

    keep_records = [json.loads(line) for line in report["keepalive"]["lines"]]
    keep_markers = [index for index, record in enumerate(keep_records) if _is_probe(record)]
    # One connection: both requests left the same client port, and one handler thread logged a marker after each request and a third after the client closed. A server closing after each response makes http.client reconnect from a new port, and its two threads log two markers.
    client_ports = report["keepalive"]["client_ports"]
    assert len(client_ports) == 2 and client_ports[0] == client_ports[1], client_ports  # C2
    assert len(keep_markers) == 3 and keep_markers[-1] == len(keep_records) - 1, keep_records  # C2
    assert all("request_id" not in keep_records[index] for index in keep_markers), [keep_records[index] for index in keep_markers]  # C2
    first = keep_records[:keep_markers[0]]
    second = keep_records[keep_markers[0] + 1:keep_markers[1]]
    assert keep_markers[2] == keep_markers[1] + 1, keep_records
    keep_port = report["ports"]["keepalive"]
    first_ms, second_ms = report["keepalive"]["ms"]
    # Per request: the second's bound excludes the idle gap before it, so a duration timed from the connection's open or from the wait for its request line fails.
    assert second_ms < KEEPALIVE_GAP_MS, report["keepalive"]["ms"]
    first_id = _check_window(first, {**KEEPALIVE[0], "method": "GET"}, keep_port, first_ms)
    second_id = _check_window(second, {**KEEPALIVE[1], "method": "GET"}, keep_port, second_ms)
    # The second request sent no header; carrying the first's id over the connection fails here.
    assert first_id != second_id, (first_id, second_id)  # C2
    ids.extend([first_id, second_id])

    # A constant fallback gives every headerless or rejected request the same id.
    assert len(set(ids)) == len(ids), ids  # C2
    for value in REJECTED_IDS:
        assert all(value not in line for line in all_lines), value  # C2
