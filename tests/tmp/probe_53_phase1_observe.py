"""Probe for plan 53 phase 1: what urllib and today's fetch_bounded / media code do through the ScriptedInstance harness."""
from __future__ import annotations

import http.client
import importlib
import importlib.util
import sys
import urllib.error
from http.client import HTTPMessage
from pathlib import Path
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, Clock, ScriptedInstance, _body, scripted_instance  # noqa: E402,F401


class Recording(ScriptedInstance):
    def __init__(self, clock, monkeypatch):
        super().__init__(clock, monkeypatch)
        self.requests = []
        self.failures = {}

    def open(self, req):
        self.requests.append(req)
        if req.full_url in self.failures:
            self.opened.append(req.full_url)
            raise self.failures[req.full_url]
        return super().open(req)


def test_probe(monkeypatch, scripted_instance):
    it = importlib.import_module("handlers.internal_translate")
    inst = Recording(scripted_instance.clock, monkeypatch)
    monkeypatch.setattr(it, "build_opener", inst.build_opener)
    clock = inst.clock
    for n in (8, 9):
        inst.serve(f"https://{HOST}/n{n}", chunks=[b"x"] * n, seconds_per_chunk=1.0)
        print(f"today {n} x 1s chunks:", it.fetch_bounded(HOST, f"/n{n}", clock.now + 1000))
    print("today budget_at == now:", it.fetch_bounded(HOST, "/n8", clock.now), "opened", len(inst.opened))
    inst.serve(TRACK_URL, status=204)
    inst.requests.clear()
    print("today 204:", it.fetch_bounded(HOST, TRACK_PATH, clock.now + 1000))
    req = inst.requests[0]
    print("timeout:", req.timeout, "Accept:", repr(req.get_header("Accept")), "items:", req.header_items())
    inst.requests.clear()
    it.fetch_bounded(HOST, TRACK_PATH, clock.now + 1.0)
    print("timeout budget+1:", inst.requests[0].timeout)
    opener = inst.build_opener(it.SameHostRedirectHandler(HOST))
    r = opener.open(Request(TRACK_URL, headers={"User-Agent": "ua/1.0"}), timeout=4.0)
    print("204 returned:", r.status, "UA:", inst.requests[-1].get_header("User-agent"), "Accept:", inst.requests[-1].get_header("Accept"))
    try:
        opener.open(Request(f"https://{HOST}/unserved"), timeout=4.0)
    except urllib.error.HTTPError as exc:
        print("404:", type(exc).__name__, exc.code, repr(str(exc)), "fp", exc.fp)
    inst.serve(TRACK_URL, status=302, headers={"Location": REFUSED_TARGETS["off-host"]})
    inst.opened.clear()
    try:
        inst.build_opener(it.SameHostRedirectHandler(HOST)).open(Request(TRACK_URL), timeout=15.0)
    except urllib.error.HTTPError as exc:
        print("refused redirect:", repr(f"media download failed: {exc}"), "opened", inst.opened)
    for exc in (ConnectionResetError("connection reset by peer"), urllib.error.URLError("instance down"), http.client.IncompleteRead(b"ab", 5), ValueError("bad url")):
        inst.failures[f"https://{HOST}/boom"] = exc
        try:
            inst.build_opener(it.SameHostRedirectHandler(HOST)).open(Request(f"https://{HOST}/boom"), timeout=4.0)
        except Exception as raised:
            print("raised at open:", type(raised).__name__, repr(str(raised)), raised is exc)
    handler = it.SameHostRedirectHandler(HOST)
    for code in (301, 302, 303, 307, 308):
        new = handler.redirect_request(Request(TRACK_URL), None, code, "Moved", HTTPMessage(), f"https://{HOST}/moved.vtt")
        print("redirect", code, type(new).__name__, new.full_url)
    print("over cap header:", str(OVER_CAP), "chunks", len(_body(OVER_CAP)))
    assert False, "probe"


def test_probe_media_host():
    root = Path(__file__).resolve().parents[2]
    for p in (root / "engine" / "server", root / "engine" / "server" / "api"):
        sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location("probe_worker", root / "engine" / "server" / "db" / "jobs" / "translate-worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    for url in ["https://media.example/v.mp4", "https://Media.EXAMPLE/v.mp4", "https://media.example./v.mp4", "https://xn--bcher-kva.example/v.mp4", "https://media.xn--p1ai/v.mp4",
                "http://media.example/v.mp4", "https://203.0.113.7/v.mp4", "https://[2001:db8::7]/v.mp4", "https://2130706433/v.mp4", "https://127.1/v.mp4", "https://0x7f.0x1/v.mp4",
                "https://media/v.mp4", "https://media.example:8443/v.mp4", "https://media.example:443/v.mp4", "https://user@media.example/v.mp4", "https://user:pw@media.example/v.mp4", "https://media.example:bad/v.mp4", "", "not a url"]:
        print("media_host", repr(url), "->", repr(worker.media_host(url)))
    assert False, "probe"
