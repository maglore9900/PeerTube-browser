"""Checkpoint for plan 06, Phase 2 — refuse every other presentation, and bound minting.

must_prove:
  C1 — On `GET /api/user-profile`, `GET /api/user-profile/likes` and
       `POST /api/user-profile/reset`, an absent header, a malformed key, an unknown
       well-formed key, and a valid key sent in the query string or body instead of the
       header all receive the same status and the same body.
  C2 — The sixth `POST /api/profile` from one client address within an hour is refused
       with 429, and the first five succeed.
"""
from __future__ import annotations

import http.client
import json
import secrets
from datetime import datetime as real_datetime

import pytest
from lib import http_utils

PROFILE_ROUTES = [
    ("GET", "/api/user-profile"),
    ("GET", "/api/user-profile/likes"),
    ("POST", "/api/user-profile/reset"),
]


def _mint(client) -> tuple[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return body["profile_id"], body["key"]


@pytest.mark.parametrize(("method", "path"), PROFILE_ROUTES)
def test_every_presentation_but_a_valid_header_gets_the_same_refusal(client_backend, method, path):
    profile_id, key = _mint(client_backend)
    body = {} if method == "POST" else None

    # Control: the route serves a profile when the key arrives in the header.
    status, _ = client_backend.request(method, path, headers={"X-Profile-Key": key}, body=body)
    assert status == 200

    malformed = {
        "empty": "",
        "short": key[:42],
        "long": key + "A",
        "bad char": key[:42] + "!",
        "not a key": "not-a-key",
    }
    responses = {
        "absent": client_backend.request(method, path, body=body),
        **{f"malformed {name}": client_backend.request(
            method, path, headers={"X-Profile-Key": value}, body=body)
           for name, value in malformed.items()},
        "unknown": client_backend.request(
            method, path, headers={"X-Profile-Key": secrets.token_urlsafe(32)}, body=body),
        "key in query": client_backend.request(method, f"{path}?key={key}", body=body),
        "id in query": client_backend.request(method, f"{path}?user_id={profile_id}", body=body),
        "in body": client_backend.request(
            method, path, body={"key": key, "user_id": profile_id}),
    }
    refusals = {(status, json.dumps(payload, sort_keys=True)) for status, payload in responses.values()}
    assert len(refusals) == 1, responses  # C1
    assert responses["absent"][0] == 401  # C1


class _Clock:
    """Stands in for the wall clock the rate limiter reads: a system boundary."""

    def __init__(self, start: float) -> None:
        self.now_ts = start

    def now(self, tz=None):
        return real_datetime.fromtimestamp(self.now_ts, tz)


def _mint_from(client, source_ip: str) -> int:
    """Mint over a connection bound to `source_ip`, so the server sees that address."""
    host, port = client.base.removeprefix("http://").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10, source_address=(source_ip, 0))
    try:
        conn.request("POST", "/api/profile", body=b"", headers={"content-type": "application/json"})
        return conn.getresponse().status
    finally:
        conn.close()


def test_a_sixth_mint_from_one_address_within_the_hour_is_refused(client_backend, monkeypatch):
    clock = _Clock(1_800_000_000.0)
    monkeypatch.setattr(http_utils, "datetime", clock)

    first_five = [_mint_from(client_backend, "127.0.0.1") for _ in range(5)]
    clock.now_ts += 3599
    sixth = _mint_from(client_backend, "127.0.0.1")
    other_address = _mint_from(client_backend, "127.0.0.2")
    clock.now_ts += 2
    after_the_hour = _mint_from(client_backend, "127.0.0.1")

    assert first_five == [201] * 5  # C2
    assert sixth == 429  # C2
    # The limit is per address: another address still mints while the first is refused.
    assert other_address == 201  # C2
    # The window is an hour: one second past it, the first address mints again.
    assert after_the_hour == 201  # C2
