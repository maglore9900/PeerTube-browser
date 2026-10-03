"""Probe: how a real urllib opener behaves when only its http/https open step is faked."""
import sys
import time
import urllib.request
from http.client import HTTPMessage
from urllib.request import HTTPRedirectHandler, Request

import pytest


class Resp:
    def __init__(self, url, code, headers, chunks):
        self.url = url
        self.code = self.status = code
        self.msg = "M"
        self.headers = HTTPMessage()
        for k, v in headers.items():
            self.headers[k] = v
        self.chunks = list(chunks)
        self.reads = 0

    def info(self):
        return self.headers

    def geturl(self):
        return self.url

    def read1(self, n=-1):
        self.reads += 1
        return self.chunks.pop(0) if self.chunks else b""

    def read(self, n=-1):
        self.reads += 1
        out = b"".join(self.chunks)
        self.chunks = []
        return out

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SCRIPT = {
    "https://peer.example/start": (302, {"Location": "https://evil.example/x"}, []),
    "https://peer.example/rel": (302, {"Location": "/final"}, []),
    "https://peer.example/final": (200, {}, [b"ok"]),
    "https://evil.example/x": (200, {}, [b"LEAKED"]),
    "http://peer.example/x": (200, {}, [b"LEAKED-HTTP"]),
    "https://user@peer.example/x": (200, {}, [b"LEAKED-USER"]),
    "https://peer.example:8443/x": (200, {}, [b"LEAKED-PORT"]),
}
SEEN = []


def _serve(req):
    SEEN.append((req.full_url, req.timeout))
    code, headers, chunks = SCRIPT[req.full_url]
    return Resp(req.full_url, code, headers, chunks)


class FakeHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return _serve(req)


class FakeHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return _serve(req)


class Refuse(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        print("refuse got newurl", newurl)
        return None


def test_probe():
    print("python", sys.version)
    SEEN.clear()
    opener = urllib.request.build_opener(FakeHTTPS(), FakeHTTP())
    with opener.open(Request("https://peer.example/start"), timeout=3) as r:
        print("default follows off-host:", r.status, r.read1(10), SEEN)
    SEEN.clear()
    opener = urllib.request.build_opener(FakeHTTPS(), FakeHTTP(), Refuse())
    try:
        opener.open(Request("https://peer.example/start"), timeout=3)
    except Exception as exc:
        print("refused ->", type(exc).__mro__, exc, SEEN)
    SEEN.clear()
    with urllib.request.build_opener(FakeHTTPS(), FakeHTTP()).open(Request("https://peer.example/rel"), timeout=3) as r:
        print("relative:", r.status, r.read1(), SEEN)
    for target in ["http://peer.example/x", "https://user@peer.example/x", "https://peer.example:8443/x"]:
        SCRIPT["https://peer.example/start"] = (302, {"Location": target}, [])
        SEEN.clear()
        with urllib.request.build_opener(FakeHTTPS(), FakeHTTP()).open(Request("https://peer.example/start"), timeout=3) as r:
            print("default follows", target, "->", r.read1(), SEEN)
    h = HTTPRedirectHandler()
    req = Request("https://peer.example/a")
    for code in (301, 302, 303, 307, 308):
        new = h.redirect_request(req, None, code, "M", HTTPMessage(), "https://peer.example/b")
        print(code, type(new), new.full_url if new is not None else None)
    m = HTTPMessage()
    m["Content-Length"] = "5"
    print("header get lower:", m.get("content-length"))
    print("monotonic", time.monotonic)
    print("approx dict w/ str:", end=" ")
    try:
        print({"a": 1.0, "t": "x"} == pytest.approx({"a": 1.0000000001, "t": "x"}))
    except Exception as exc:
        print("raises", exc)
    print("float 3723.004:", 1 * 3600 + 2 * 60 + 3 + 4 / 1000 == 3723.004, round(1 * 3600 + 2 * 60 + 3 + 4 / 1000, 3) == 3723.004)
    sys.path[:0] = ["engine/server", "engine/server/api"]
    from handlers import video  # noqa: F401
    import data.moderation  # noqa: F401
    print("engine imports ok; numpy loaded:", "numpy" in sys.modules)
