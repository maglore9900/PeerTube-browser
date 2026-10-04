"""Phase 4 checkpoint of plan 53: `fetch_host_list` fetches each attempt through `data.source_fetch`, so an attempt that breaks the adapter's rule or passes `timeout_s` on the clock fails and is retried.

- Through the adapter, every attempt opens exactly the trending URL under a `timeout_s` socket timeout with the `peertube-browser-trending/1.0` User-Agent: one attempt for a list (`[]` included), `max_retries + 1` then None for each of test_fetch_trending.py's FAILURES, one with `max_retries` 0, and two when a retry succeeds.
- C1: a 302 to cdn.example on every attempt ends in None after 3 attempts, the target never opened though it serves a list, while a 302 to tube.example/moved returns the list; a body of `TRENDING_MAX_BYTES + 1` ends in None after 3 attempts, while the same list padded to exactly `TRENDING_MAX_BYTES` is returned.
- C2: with `time.monotonic` advancing 1 s per call and `timeout_s` 0.25, the same body that a frozen clock returns ends in None after 3 attempts.

The network is severed at the adapter's single patch point, `data.source_fetch.build_opener`: a real urllib opener, the module's real redirect handler included, whose only fake part is the https open step, answering each attempt with the next scripted outcome. Name resolution fails, so a fetch that goes around the adapter reaches no host and records nothing.
"""
from __future__ import annotations

import importlib
import io
import itertools
import socket
import sys
import time
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_fetch_trending import FAILURES, TRENDING_URL, job  # noqa: E402,F401

USER_AGENT = "peertube-browser-trending/1.0"
MOVED_URL = "https://tube.example/moved"
CDN_URL = "https://cdn.example/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
LIST_BODY = b'{"total": 1, "data": [{"uuid": "x"}]}'


def _redirect(location: str) -> dict:
    return {"status": 302, "headers": {"Location": location}}


def _padded(size: int) -> bytes:
    """LIST_BODY followed by JSON whitespace up to exactly size bytes, so it still parses to the one-entry list."""
    return LIST_BODY + b" " * (size - len(LIST_BODY))


def _scripted(monkeypatch, outcomes: list[object], routes: dict[str, bytes] | None = None) -> list[tuple[str, object, str | None]]:
    """Open through a scripted https step: a URL in routes is answered with its body, any other open with the next outcome (raised when an exception, a 200 body when bytes, else a status and headers); return the record of each open's (full_url, timeout, User-Agent)."""
    attempts: list[tuple[str, object, str | None]] = []
    pending = list(outcomes)
    fixed = routes or {}

    def unreachable(*args: object, **kwargs: object) -> list:
        raise OSError("network severed by the checkpoint")

    class Scripted(HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001, ANN202
            attempts.append((req.full_url, req.timeout, req.get_header("User-agent")))
            outcome = fixed[req.full_url] if req.full_url in fixed else pending.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            answer = {"body": outcome} if isinstance(outcome, bytes) else outcome
            headers = Message()
            for name, value in answer.get("headers", {}).items():
                headers[name] = value
            resp = addinfourl(io.BytesIO(answer.get("body", b"")), headers, req.full_url, answer.get("status", 200))
            resp.msg = "Scripted"
            return resp

    def opener(*handlers: object):  # noqa: ANN202
        return build_opener(Scripted(), *[handler for handler in handlers if not isinstance(handler, HTTPSHandler)])

    monkeypatch.setattr(socket, "getaddrinfo", unreachable)
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", opener)
    return attempts


def test_fetch_host_list_reads_the_trending_page_through_the_adapter(job, monkeypatch):
    attempts = _scripted(monkeypatch, [b'{"total": 2, "data": [{"uuid": "x"}, {"id": 3}]}', b'{"total": 0, "data": []}'])
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}, {"id": 3}]  # seam
    # Today's urlopen goes around the adapter and records nothing; a missing User-Agent reads Python-urllib's, a dropped timeout_s reads 4.0.
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]  # seam
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == []  # seam
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 2  # seam


@pytest.mark.parametrize("failure", list(FAILURES.values()), ids=list(FAILURES))
def test_fetch_host_list_returns_none_after_max_retries_plus_one_failed_attempts(job, monkeypatch, failure):
    attempts = _scripted(monkeypatch, [failure] * 10)
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) is None  # seam
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 3  # seam


def test_fetch_host_list_with_no_retries_makes_one_attempt(job, monkeypatch):
    attempts = _scripted(monkeypatch, [URLError("connection refused")] * 10)
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=0) is None  # seam
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]  # seam


def test_fetch_host_list_returns_the_list_when_a_retry_succeeds(job, monkeypatch):
    attempts = _scripted(monkeypatch, [URLError("connection refused"), LIST_BODY])
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}]  # seam
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 2  # seam


def test_an_off_host_redirect_fails_every_attempt_and_its_target_is_never_opened(job, monkeypatch):
    # The target serves a list, so following the redirect would return it and record the cdn.example URL.
    attempts = _scripted(monkeypatch, [_redirect(CDN_URL)] * 10, {CDN_URL: LIST_BODY})
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) is None  # C1
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 3  # C1
    # Control: the same redirect to the same host is followed to its list, so the None above is the refusal's doing.
    attempts = _scripted(monkeypatch, [_redirect(MOVED_URL)] * 10, {MOVED_URL: LIST_BODY})
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}]  # C1: control
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT), (MOVED_URL, 0.25, USER_AGENT)]  # C1: control


def test_a_body_one_byte_over_trending_max_bytes_fails_every_attempt(job, monkeypatch):
    cap = job.TRENDING_MAX_BYTES
    # Control: the cap leaves room for the list itself, so both bodies below parse to it once padded.
    assert isinstance(cap, int) and cap > len(LIST_BODY), cap  # C1: control
    attempts = _scripted(monkeypatch, [_padded(cap + 1)] * 10)
    # A fetch under the adapter's default 2,000,000-byte cap returns this list whenever TRENDING_MAX_BYTES is below it.
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) is None  # C1
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 3  # C1
    # Control: one byte less is returned, so the None above is the cap's doing; a default cap below TRENDING_MAX_BYTES fails here.
    attempts = _scripted(monkeypatch, [_padded(cap)] * 10)
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}]  # C1: control
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]  # C1: control


def test_an_attempt_whose_clock_passes_timeout_s_fails_on_the_deadline_and_is_retried(job, monkeypatch):
    ticks = itertools.count(1.0)
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    attempts = _scripted(monkeypatch, [LIST_BODY] * 10)
    # Under the adapter's default 8 s deadline the body is read within a few ticks and returned.
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) is None  # C2
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)] * 3  # C2
    # Control: the same body on a frozen clock is returned, so the None above is the deadline's doing.
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    attempts = _scripted(monkeypatch, [LIST_BODY] * 10)
    assert job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2) == [{"uuid": "x"}]  # C2: control
    assert attempts == [(TRENDING_URL, 0.25, USER_AGENT)]  # C2: control
