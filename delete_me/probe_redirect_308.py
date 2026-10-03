"""Probe: does this Python's HTTPRedirectHandler.redirect_request return a Request for every redirect code the checkpoint parametrizes, and does a refused redirect surface as an OSError?"""
import sys
import urllib.request
from http.client import HTTPMessage
from urllib.request import HTTPRedirectHandler, Request


def test_probe():
    print("python", sys.version)
    for code in (301, 302, 303, 307, 308):
        new = HTTPRedirectHandler().redirect_request(Request("https://peer.example/a"), None, code, "M", HTTPMessage(), "https://peer.example/b")
        print(code, type(new).__name__, getattr(new, "full_url", None))
    print("HTTPError is OSError:", issubclass(urllib.request.HTTPError, OSError))
