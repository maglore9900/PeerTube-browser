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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_fetch_trending import FAILURES, TRENDING_URL, job  # noqa: E402,F401

PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
BODY = b'{"total": 1, "data": [{"uuid": "x"}]}'


def _scripted(outcomes, routes=None):
    calls = []
    pending = list(outcomes)
    routes = routes or {}

    class Scripted(HTTPSHandler):
        def https_open(self, req):
            calls.append((req.full_url, req.timeout, req.get_header("User-agent")))
            outcome = routes[req.full_url] if req.full_url in routes else pending.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, bytes):
                outcome = {"body": outcome}
            headers = Message()
            for name, value in outcome.get("headers", {}).items():
                headers[name] = value
            resp = addinfourl(io.BytesIO(outcome.get("body", b"")), headers, req.full_url, outcome.get("status", 200))
            resp.msg = "Scripted"
            return resp

    def opener(*handlers):
        return build_opener(Scripted(), *[h for h in handlers if not isinstance(h, HTTPSHandler)])

    return opener, calls


def _sever(monkeypatch):
    def unreachable(*a, **k):
        raise OSError("severed")
    monkeypatch.setattr(socket, "getaddrinfo", unreachable)


def test_probe_adapter(monkeypatch):
    _sever(monkeypatch)
    sf = importlib.import_module("data.source_fetch")
    print("FETCH_MAX_BYTES", sf.FETCH_MAX_BYTES)
    opener, calls = _scripted([BODY, {"status": 302, "headers": {"Location": "https://tube.example/moved"}}, {"status": 302, "headers": {"Location": "https://cdn.example/x"}}, BODY + b" " * 100])
    monkeypatch.setattr(sf, "build_opener", opener)
    print("plain", sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25, headers={"User-Agent": "peertube-browser-trending/1.0"}))
    print("no-ua", sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25) if False else "skip")
    calls_routes = calls
    # same-host redirect, target from routes
    opener2, calls2 = _scripted([{"status": 302, "headers": {"Location": "https://tube.example/moved"}}], {"https://tube.example/moved": BODY})
    monkeypatch.setattr(sf, "build_opener", opener2)
    print("same-host", sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25, headers={"User-Agent": "peertube-browser-trending/1.0"}), calls2)
    opener3, calls3 = _scripted([{"status": 302, "headers": {"Location": "https://cdn.example/x"}}], {"https://cdn.example/x": BODY})
    monkeypatch.setattr(sf, "build_opener", opener3)
    try:
        sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25, headers={"User-Agent": "peertube-browser-trending/1.0"})
    except sf.SourceFetchFailed as exc:
        print("off-host", repr(exc), calls3)
    opener4, calls4 = _scripted([BODY])
    monkeypatch.setattr(sf, "build_opener", opener4)
    sf.fetch_bounded("tube.example", PATH)
    print("default-ua", calls4)
    opener5, calls5 = _scripted([BODY, BODY])
    monkeypatch.setattr(sf, "build_opener", opener5)
    ticks = itertools.count(1.0)
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    try:
        sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25)
    except sf.SourceFetchFailed as exc:
        print("ticking", repr(exc), calls5)
    monkeypatch.setattr(time, "monotonic", lambda: 5.0)
    print("frozen", sf.fetch_bounded("tube.example", PATH, deadline_seconds=0.25, socket_timeout=0.25), calls5)
    opener6, calls6 = _scripted([FAILURES["http-500"], FAILURES["url-error"], FAILURES["timeout"]])
    monkeypatch.setattr(sf, "build_opener", opener6)
    for _ in range(3):
        try:
            sf.fetch_bounded("tube.example", PATH)
        except sf.SourceFetchFailed as exc:
            print("failure", repr(exc))


def test_probe_todays_job(job, monkeypatch):
    _sever(monkeypatch)
    sf = importlib.import_module("data.source_fetch")
    opener, calls = _scripted([BODY] * 5)
    monkeypatch.setattr(sf, "build_opener", opener)
    print("job result", job.fetch_host_list("tube.example", timeout_s=0.25, max_retries=2), calls, hasattr(job, "TRENDING_MAX_BYTES"))
