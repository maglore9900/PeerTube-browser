"""POST /api/analytics/event on a real ClientBackendServer over a socket: one server-stamped row per accepted event, none per refused request.

- A valid outbound_click or page_view, sent as application/json, text/plain;charset=UTF-8 or application/x-www-form-urlencoded, gets 204 with an empty body and leaves exactly one row: its type, track_id, href and page_path as sent (track_id and href NULL on a page_view), created_at inside the [before, after] now_ms() window around the request and not the client timestamp 1, and user_agent and referer equal to the request headers, each NULL when that header was sent empty or not sent at all.
- Each refused body (empty, `{`, `[]`, `\\xff`, and the valid baseline with one of type, track_id, href (a non-http scheme, a lone surrogate), page_path or timestamp broken, or a page_view carrying a track_id) gets 400 with a JSON string `error` and leaves the table empty, while a valid event posted after it on the same server is stored.
- Under the production route limiter (90 requests per address within its window, whose length is not asserted here), the 91st valid post from 203.0.113.18 gets 429 `{"error": "Rate limit exceeded"}` after the 90 before it each got 204, and the table holds those 90 rows only, while 203.0.113.19 is still stored.
- Regression line, not a clause: GET of the path is 404 `{"error": "Not found"}` and stores nothing.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest

ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

# client_backend is the conftest fixture itself, imported so pytest serves it here as it does under tests/active.
from conftest import CLOSED_ENGINE, RateLimiter, client_backend, client_server, ensure_user_schema  # noqa: E402,F401
from lib.time_utils import now_ms  # noqa: E402

EVENT_PATH = "/api/analytics/event"
STORED = "SELECT type, track_id, href, page_path, created_at, user_agent, referer FROM analytics_events ORDER BY id"
# No default headers: urllib otherwise adds `User-agent: Python-urllib/3.x`; observed, this opener sends neither User-Agent nor Referer unless a test adds one.
OPENER = urllib.request.build_opener()
OPENER.addheaders = []
MISSING = object()
# Far outside any request window, so a row stamped from the body is told apart from one stamped by the server.
CLIENT_TIMESTAMP = 1
USER_AGENT = "Mozilla/5.0 analytics-test"
REFERER = "https://example.org/about"
JSON_HEADERS = {"Content-Type": "application/json"}
TEXT_HEADERS = {"Content-Type": "text/plain;charset=UTF-8"}
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
LIMITED_ADDRESS = "203.0.113.18"
OTHER_ADDRESS = "203.0.113.19"
CLICK = {"type": "outbound_click", "track_id": "about_patreon", "href": "https://www.patreon.com/x", "page_path": "/about", "timestamp": CLIENT_TIMESTAMP}
VIEW = {"type": "page_view", "page_path": "/about.html", "timestamp": CLIENT_TIMESTAMP}


def _body(event: dict[str, Any], **overrides: Any) -> bytes:
    """`event` with `overrides` applied as JSON bytes; MISSING drops the key."""
    merged = {**event, **overrides}
    return json.dumps({key: value for key, value in merged.items() if value is not MISSING}).encode("utf-8")


def _send(base: str, method: str, raw: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    """Send one request with exactly `headers`; return the status and the raw response body."""
    req = urllib.request.Request(base + EVENT_PATH, data=raw, method=method)
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with OPENER.open(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _rows(db_path: Path) -> list[tuple]:
    """Every analytics_events row, read through a connection of its own."""
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(STORED).fetchall()


@contextmanager
def _serving_limited(tmp_path: Path):
    """A Client backend built as conftest's `client_backend` is, but with the production route limiter."""
    db_path = tmp_path / "users.db"
    conn = client_server.connect_db(db_path)
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, CLOSED_ENGINE, "bridge", RateLimiter(client_server.RATE_LIMIT_MAX_REQUESTS, client_server.RATE_LIMIT_WINDOW_SECONDS))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", db_path
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()


# Body, request headers, and the row's (type, track_id, href, page_path, user_agent, referer).
ACCEPTED = [
    pytest.param(CLICK, {**JSON_HEADERS, "User-Agent": USER_AGENT, "Referer": REFERER}, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about", USER_AGENT, REFERER), id="click-json-headers-sent"),
    pytest.param(VIEW, {**TEXT_HEADERS, "User-Agent": USER_AGENT, "Referer": REFERER}, ("page_view", None, None, "/about.html", USER_AGENT, REFERER), id="view-text-plain-headers-sent"),
    pytest.param(CLICK, {**TEXT_HEADERS, "User-Agent": "", "Referer": ""}, ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about", None, None), id="click-text-plain-headers-empty"),
    pytest.param(VIEW, JSON_HEADERS, ("page_view", None, None, "/about.html", None, None), id="view-json-headers-absent"),
    pytest.param({**VIEW, "track_id": None, "href": None}, {**FORM_HEADERS, "User-Agent": USER_AGENT}, ("page_view", None, None, "/about.html", USER_AGENT, None), id="view-form-nulls-referer-absent"),
]

REJECTED = [
    pytest.param(b"", id="empty-body"),
    pytest.param(b"{", id="invalid-json"),
    pytest.param(b"[]", id="non-object"),
    pytest.param(b"\xff", id="non-utf8"),
    pytest.param(_body(CLICK, type="click"), id="type-unknown"),
    pytest.param(_body(CLICK, track_id="About_Patreon"), id="track-id-uppercase"),
    pytest.param(_body(CLICK, href="mailto:a@b.c"), id="href-mailto"),
    pytest.param(_body(CLICK, href="https://x.y/\ud800"), id="href-lone-surrogate"),
    pytest.param(_body(CLICK, page_path="about"), id="page-path-no-slash"),
    pytest.param(_body(CLICK, timestamp=MISSING), id="timestamp-missing"),
    pytest.param(_body(CLICK, timestamp=True), id="timestamp-bool"),
    pytest.param(_body(VIEW, track_id="about_x"), id="view-with-track-id"),
]


@pytest.mark.parametrize(("event", "headers", "expected"), ACCEPTED)
def test_accepted_event_stores_one_server_stamped_row(client_backend, event: dict[str, Any], headers: dict[str, str], expected: tuple) -> None:
    """A valid event under any Content-Type gets 204 with an empty body and exactly one row: its fields as sent, created_at in the request's now_ms() window and not the client timestamp, user_agent and referer from the headers or NULL when empty or absent."""
    before = now_ms()
    status, body = _send(client_backend.base, "POST", json.dumps(event).encode("utf-8"), headers)
    after = now_ms()
    assert (status, body) == (204, b"")  # C1
    rows = _rows(client_backend.db_path)
    assert len(rows) == 1  # C1: exactly one row per accepted request
    event_type, track_id, href, page_path, created_at, user_agent, referer = rows[0]
    assert (event_type, track_id, href, page_path, user_agent, referer) == expected  # C1: fields as sent, UA and Referer from the headers, NULL when empty or absent
    assert isinstance(created_at, int) and before <= created_at <= after  # C1: server receive time
    assert created_at != CLIENT_TIMESTAMP  # C1: not the client's clock


@pytest.mark.parametrize("raw", REJECTED)
def test_invalid_body_gets_400_and_stores_nothing(client_backend, raw: bytes) -> None:
    """A refused body gets 400 with a JSON string `error` and leaves the table empty; a valid event posted after it on the same server is stored, so the empty table is the refusal and not a route that never writes."""
    status, body = _send(client_backend.base, "POST", raw, JSON_HEADERS)
    assert status == 400  # C2
    error = json.loads(body)["error"]
    assert isinstance(error, str) and error  # C2: a JSON error message, not an empty body
    assert _rows(client_backend.db_path) == []  # C2: no row added
    assert _send(client_backend.base, "POST", _body(VIEW), JSON_HEADERS) == (204, b"")  # control: the route stores, so the empty table above is the refusal
    assert len(_rows(client_backend.db_path)) == 1  # control


def test_91st_post_from_one_address_gets_429_and_stores_nothing(tmp_path: Path) -> None:
    """Under the production limiter, the 91st valid post from one address gets 429 `{"error": "Rate limit exceeded"}` after the 90 before it each got 204, and the table holds those 90 rows only; another address is still stored."""
    limited = {**JSON_HEADERS, "X-Forwarded-For": LIMITED_ADDRESS}
    with _serving_limited(tmp_path) as (base, db_path):
        accepted = [_send(base, "POST", _body(CLICK), limited)[0] for _ in range(90)]
        status, body = _send(base, "POST", _body(CLICK), limited)
        assert (status, json.loads(body)) == (429, {"error": "Rate limit exceeded"})  # C2
        assert accepted == [204] * 90  # control: all 90 within the limit were accepted, each storing one row
        assert len(_rows(db_path)) == 90  # C2: the refused 91st added no row to the 90
        assert _send(base, "POST", _body(CLICK), {**JSON_HEADERS, "X-Forwarded-For": OTHER_ADDRESS}) == (204, b"")  # control: the 429 is the per-address limit, not a stopped server
        assert len(_rows(db_path)) == 91  # control


def test_get_of_event_path_is_not_a_route(client_backend) -> None:
    """GET of the event path is 404 `{"error": "Not found"}` and stores nothing."""
    status, body = _send(client_backend.base, "GET", None, {})
    assert (status, json.loads(body)) == (404, {"error": "Not found"})  # regression line, no clause
    assert _rows(client_backend.db_path) == []  # regression line, no clause
