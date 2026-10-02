"""Probe for plan 23-18 phase 3: what a header-less urllib opener sends, and what the route does today."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))

from conftest import client_backend  # noqa: E402,F401

SEEN = []


class Recorder(BaseHTTPRequestHandler):
    def do_POST(self):
        length = self.headers.get("Content-Length")
        body = self.rfile.read(int(length or 0))
        SEEN.append({"ua": self.headers.get("User-Agent"), "referer": self.headers.get("Referer"), "ct": self.headers.get("Content-Type"), "cl": length, "body": body, "all": dict(self.headers.items())})
        self.send_response(204)
        self.send_header("content-length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


def _post(opener, url, data, headers):
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, resp.read(), resp.headers.get("content-type")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("content-type")


def test_probe_headers():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/x"
    opener = urllib.request.build_opener()
    print("default addheaders", opener.addheaders)
    opener.addheaders = []
    _post(opener, url, b'{"a":1}', {"Content-Type": "application/json"})
    _post(opener, url, b'{"a":1}', {"Content-Type": "text/plain;charset=UTF-8", "User-Agent": "", "Referer": ""})
    _post(opener, url, b"", {"Content-Type": "application/json"})
    _post(opener, url, b"\xff", {})
    _post(opener, url, b'{"a":1}', {"User-Agent": "Mozilla/5.0 analytics-test", "Referer": "https://example.org/about"})
    srv.shutdown()
    srv.server_close()
    for s in SEEN:
        print(repr(s))


def test_probe_route_today(client_backend):
    opener = urllib.request.build_opener()
    opener.addheaders = []
    url = client_backend.base + "/api/analytics/event"
    print("valid", _post(opener, url, json.dumps({"type": "page_view", "page_path": "/about", "timestamp": 1}).encode(), {"Content-Type": "application/json"}))
    print("invalid", _post(opener, url, b"{", {"Content-Type": "application/json"}))
    req = urllib.request.Request(url, method="GET")
    try:
        with opener.open(req, timeout=30) as resp:
            print("get", resp.status)
    except urllib.error.HTTPError as exc:
        print("get", exc.code, exc.read())
