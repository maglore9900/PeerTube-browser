import json
import re
import sys
from urllib.parse import urlsplit


def _try(label, fn):
    try:
        print(label, "->", repr(fn()))
    except Exception as exc:  # noqa: BLE001
        print(label, "-> RAISES", type(exc).__name__, exc)


def test_probe() -> None:
    print("python", sys.version)
    _try("urlsplit('http://[::1')", lambda: urlsplit("http://[::1"))
    _try("urlsplit('http://[::1').hostname", lambda: urlsplit("http://[::1").hostname)
    _try("urlsplit('https://').hostname", lambda: urlsplit("https://").hostname)
    _try("urlsplit('HTTPS://x.y').scheme,hostname", lambda: (urlsplit("HTTPS://x.y").scheme, urlsplit("HTTPS://x.y").hostname))
    _try("urlsplit('mailto:a@b.c')", lambda: (urlsplit("mailto:a@b.c").scheme, urlsplit("mailto:a@b.c").hostname))
    _try("urlsplit('javascript:alert(1)')", lambda: (urlsplit("javascript:alert(1)").scheme, urlsplit("javascript:alert(1)").hostname))
    _try("urlsplit('/relative')", lambda: (urlsplit("/relative").scheme, urlsplit("/relative").hostname))
    _try("urlsplit('http://[::1]/').hostname", lambda: urlsplit("http://[::1]/").hostname)
    surrogate_href = json.loads('"https://x.y/\\ud800"')
    _try("json surrogate href", lambda: (surrogate_href, len(surrogate_href)))
    _try("surrogate href urlsplit", lambda: (urlsplit(surrogate_href).scheme, urlsplit(surrogate_href).hostname))
    _try("surrogate href encode", lambda: surrogate_href.encode("utf-8"))
    surrogate_path = json.loads('"/\\ud800"')
    _try("surrogate path encode", lambda: surrogate_path.encode("utf-8"))
    _try("fullmatch 'abc\\n'", lambda: re.fullmatch(r"[a-z0-9_]{1,64}", "abc\n"))
    _try("match $ 'abc\\n'", lambda: re.match(r"[a-z0-9_]{1,64}$", "abc\n"))
    _try("list in frozenset", lambda: ["page_view"] in frozenset(("outbound_click", "page_view")))
    _try("json 1.0 type", lambda: type(json.loads('{"t": 1.0}')["t"]))
    _try("json true isinstance int", lambda: isinstance(json.loads("true"), int))
    _try("len href 2048", lambda: len("https://x.y/" + "a" * 2036))
    _try("len href 2049", lambda: len("https://x.y/" + "a" * 2037))
    _try("len draft href", lambda: len("https://x.y/" + "a" * 2040))
    _try("len path 257", lambda: len("/" + "a" * 256))
