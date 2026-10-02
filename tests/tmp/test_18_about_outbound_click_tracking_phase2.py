"""server._validate_analytics_event over JSON-decoded event bodies.

- A valid outbound_click returns exactly its (type, track_id, href, page_path) as sent, at the length bounds (track_id 1 and 64, href 2048, page_path 1 and 256), with an upper-case scheme and with unknown keys present; a valid page_view returns (page_view, None, None, page_path) with track_id and href absent, both null, or one of each, and with unknown keys present.
- Each body that breaks one rule (type, track_id, href, page_path, timestamp, or a page_view carrying a track_id or href) returns a non-empty error string and does not raise; that includes a list type, lone surrogates in href and page_path, `http://[::1`, and each length bound plus one.

Each invalid body except the empty object `{}` is the valid baseline with one key changed or removed; the baseline is itself asserted valid, so every such rejection is down to that one key. `{}` lacks every key at once and only shows that a body with nothing in it is rejected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "client" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server as client_server  # noqa: E402

MISSING = object()
# Lone surrogates as json.loads yields them from a beacon body: str values that urlsplit accepts but sqlite3 cannot bind.
SURROGATE_HREF = json.loads('"https://x.y/\\ud800"')
SURROGATE_PATH = json.loads('"/\\ud800"')


def _click(**overrides: Any) -> dict[str, Any]:
    """A valid outbound_click body with `overrides` applied; MISSING drops the key."""
    body = {"type": "outbound_click", "track_id": "about_patreon", "href": "https://www.patreon.com/x", "page_path": "/about", "timestamp": 1767225600123}
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not MISSING}


def _view(**overrides: Any) -> dict[str, Any]:
    """A valid page_view body with `overrides` applied; MISSING drops the key."""
    body = {"type": "page_view", "page_path": "/about", "timestamp": 1767225600123}
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not MISSING}


VALID = [
    pytest.param(_click(), ("outbound_click", "about_patreon", "https://www.patreon.com/x", "/about"), id="click-baseline"),
    pytest.param(_click(track_id="about_github", href="http://github.com/peertube-browser?tab=repositories", page_path="/about.html", timestamp=0, ip="203.0.113.18", session={"id": 1}), ("outbound_click", "about_github", "http://github.com/peertube-browser?tab=repositories", "/about.html"), id="click-unknown-keys-http-timestamp-0"),
    pytest.param(_click(track_id="a", page_path="/"), ("outbound_click", "a", "https://www.patreon.com/x", "/"), id="click-min-lengths"),
    pytest.param(_click(track_id="z9_" * 21 + "a", href="https://x.y/" + "a" * 2036, page_path="/" + "b" * 255), ("outbound_click", "z9_" * 21 + "a", "https://x.y/" + "a" * 2036, "/" + "b" * 255), id="click-max-lengths"),
    pytest.param(_click(href="HTTPS://Example.ORG/Path"), ("outbound_click", "about_patreon", "HTTPS://Example.ORG/Path", "/about"), id="click-uppercase-scheme-verbatim"),
    pytest.param(_view(), ("page_view", None, None, "/about"), id="view-absent"),
    pytest.param(_view(track_id=None, href=None, page_path="/about/"), ("page_view", None, None, "/about/"), id="view-both-null"),
    pytest.param(_view(track_id=None, page_path="/about.html"), ("page_view", None, None, "/about.html"), id="view-track-id-null-href-absent"),
    pytest.param(_view(href=None, referrer="https://example.org/", extra=[1]), ("page_view", None, None, "/about"), id="view-href-null-unknown-keys"),
]

INVALID = [
    pytest.param({}, id="empty-object"),
    pytest.param(_click(type=MISSING), id="type-missing"),
    pytest.param(_click(type="click"), id="type-unknown"),
    pytest.param(_click(type="PAGE_VIEW"), id="type-wrong-case"),
    pytest.param(_click(type=["page_view"]), id="type-list"),
    pytest.param(_click(track_id=MISSING), id="track-id-missing"),
    pytest.param(_click(track_id=None), id="track-id-null-on-click"),
    pytest.param(_click(track_id="About_Patreon"), id="track-id-uppercase"),
    pytest.param(_click(track_id=""), id="track-id-empty"),
    pytest.param(_click(track_id="a" * 65), id="track-id-65"),
    pytest.param(_click(track_id="a-b"), id="track-id-hyphen"),
    pytest.param(_click(track_id="abc\n"), id="track-id-trailing-newline"),
    pytest.param(_click(track_id=5), id="track-id-int"),
    pytest.param(_click(href=MISSING), id="href-missing"),
    pytest.param(_click(href=None), id="href-null-on-click"),
    pytest.param(_click(href="mailto:a@b.c"), id="href-mailto"),
    pytest.param(_click(href="javascript:alert(1)"), id="href-javascript"),
    pytest.param(_click(href="https://"), id="href-no-host"),
    pytest.param(_click(href="/relative"), id="href-relative"),
    pytest.param(_click(href="http://[::1"), id="href-malformed-ipv6"),
    pytest.param(_click(href="https://x.y/" + "a" * 2037), id="href-2049"),
    pytest.param(_click(href="https://x.y/" + "a" * 2040), id="href-2052"),
    pytest.param(_click(href=42), id="href-int"),
    pytest.param(_click(href=SURROGATE_HREF), id="href-lone-surrogate"),
    pytest.param(_click(page_path=MISSING), id="page-path-missing"),
    pytest.param(_click(page_path=""), id="page-path-empty"),
    pytest.param(_click(page_path="about"), id="page-path-no-slash"),
    pytest.param(_click(page_path="/" + "a" * 256), id="page-path-257"),
    pytest.param(_click(page_path=7), id="page-path-int"),
    pytest.param(_click(page_path=SURROGATE_PATH), id="page-path-lone-surrogate"),
    pytest.param(_view(page_path="about"), id="view-page-path-no-slash"),
    pytest.param(_click(timestamp=MISSING), id="timestamp-missing"),
    pytest.param(_click(timestamp="1"), id="timestamp-str"),
    pytest.param(_click(timestamp=1.0), id="timestamp-float"),
    pytest.param(_click(timestamp=True), id="timestamp-bool"),
    pytest.param(_click(timestamp=-1), id="timestamp-negative"),
    pytest.param(_click(timestamp=None), id="timestamp-null"),
    pytest.param(_view(timestamp=MISSING), id="view-timestamp-missing"),
    pytest.param(_view(track_id="about_x"), id="view-with-track-id"),
    pytest.param(_view(href="https://x.y"), id="view-with-href"),
]


@pytest.mark.parametrize(("body", "expected"), VALID)
def test_valid_event_returns_its_storable_values(body: dict[str, Any], expected: tuple[str, str | None, str | None, str]) -> None:
    """A valid outbound_click or page_view body returns exactly (type, track_id, href, page_path), with track_id and href None on a page_view."""
    assert client_server._validate_analytics_event(body) == expected  # C1


@pytest.mark.parametrize("body", INVALID)
def test_invalid_event_returns_error_string(body: dict[str, Any]) -> None:
    """A body breaking one validation rule returns a non-empty error string rather than raising or returning values."""
    result = client_server._validate_analytics_event(body)
    assert isinstance(result, str) and result  # C2
