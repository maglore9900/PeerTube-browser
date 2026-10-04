import importlib
import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import Clock, ScriptedInstance  # noqa: E402
from test_video import API_DIR, PARAMS, PEER_HOST, SOURCE, VIDEO_PATH, VIDEO_URL, _snapshot, _video, responses, server, sync_job, video  # noqa: E402,F401
from conftest import ENGINE_PY  # noqa: E402

CDN = "https://cdn.example/api/v1/videos/uuid-1"


class Recording(ScriptedInstance):
    def __init__(self, clock, monkeypatch):
        super().__init__(clock, monkeypatch)
        self.calls = []

    def open(self, req):
        self.calls.append((req.full_url, req.timeout))
        return super().open(req)


def _padded(size):
    raw = json.dumps(SOURCE).encode("utf-8")
    return raw + b" " * (size - len(raw))


def test_observe_fetch_bounded(monkeypatch):
    sf = importlib.import_module("data.source_fetch")
    for name, routes in {
        "redirect": {VIDEO_URL: dict(status=302, headers={"Location": CDN}), CDN: dict(chunks=[json.dumps(SOURCE).encode()])},
        "declared": {VIDEO_URL: dict(headers={"Content-Length": "2000001"}, chunks=[json.dumps(SOURCE).encode()])},
        "streamed": {VIDEO_URL: dict(chunks=[_padded(2_000_001)])},
        "at-cap": {VIDEO_URL: dict(chunks=[_padded(2_000_000)])},
        "declared-at-cap": {VIDEO_URL: dict(headers={"Content-Length": "2000000"}, chunks=[json.dumps(SOURCE).encode()])},
    }.items():
        inst = Recording(Clock(), monkeypatch)
        for url, kw in routes.items():
            inst.serve(url, **kw)
        monkeypatch.setattr(sf, "build_opener", inst.build_opener)
        try:
            body = sf.fetch_bounded(PEER_HOST, VIDEO_PATH, headers={"accept": "application/json"})
            outcome = ("ok", len(body), json.loads(body) == SOURCE)
        except sf.SourceFetchFailed as exc:
            outcome = ("failed", str(exc))
        print(name, outcome, inst.calls)


def test_observe_current_handler(server, responses, monkeypatch):
    sf = importlib.import_module("data.source_fetch")
    inst = Recording(Clock(), monkeypatch)
    inst.serve(VIDEO_URL, chunks=[json.dumps(SOURCE).encode()])
    monkeypatch.setattr(sf, "build_opener", inst.build_opener)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(OSError("severed")))
    video.handle_video_request(None, server, PARAMS)
    print("current handler", responses[0][0], responses[0][1].get("title"), inst.calls, _video(server.db)["title"])


CHILD = r'''
import io, json, socket
from email.message import Message
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl
from unittest.mock import patch
import server
from data import source_fetch
calls = []
routes = {
  "https://tube.example/r": (302, {"Location": "https://cdn.example/x"}, b""),
  "https://cdn.example/x": (200, {}, b'{"a": 1}'),
  "https://tube.example/d": (200, {"Content-Length": "2000001"}, b'{"a": 1}'),
  "https://tube.example/s": (200, {}, b"{}" + b" " * 1999999),
  "https://tube.example/ok": (200, {}, b'{"a": 1}'),
}
class Scripted(HTTPSHandler):
    def https_open(self, req):
        calls.append([req.host, req.selector, req.timeout])
        status, headers, body = routes.get(req.full_url, (404, {}, b""))
        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        resp = addinfourl(io.BytesIO(body), msg, req.full_url, status)
        resp.msg = "Scripted"
        return resp
def opener(*handlers):
    return build_opener(Scripted(), *[h for h in handlers if not isinstance(h, HTTPSHandler)])
out = {}
with patch.object(source_fetch, "build_opener", opener):
    for p in ["/r", "/d", "/s", "/ok", "/missing"]:
        del calls[:]
        try:
            out[p] = ["ok", source_fetch.fetch_bounded("tube.example", p).decode()[:20], list(calls)]
        except source_fetch.SourceFetchFailed as exc:
            out[p] = ["failed", str(exc), list(calls)]
real = socket.getaddrinfo
def guarded(host, *a, **k):
    if host != "127.0.0.1":
        raise OSError("severed")
    return real(host, *a, **k)
socket.getaddrinfo = guarded
import http.client
try:
    socket.getaddrinfo("tube.example", 443)
except OSError as exc:
    out["guard"] = str(exc)
print(json.dumps(out))
'''


def test_observe_child():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print("rc", run.returncode)
    print(run.stdout)
    print(run.stderr[-3000:])
