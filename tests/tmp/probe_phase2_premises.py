import json
import re
import sqlite3
from urllib.parse import urlsplit


def test_probe() -> None:
    surrogate_href = json.loads('"https://x.y/\\ud800"')
    surrogate_path = json.loads('"/\\ud800"')
    print("lens", len("https://x.y/" + "a" * 2036), len("https://x.y/" + "a" * 2037), len("https://x.y/" + "a" * 2040), len("z9_" * 21 + "a"), len("/" + "b" * 255), len("/" + "a" * 256), len("a" * 65))
    print("surrogate", repr(surrogate_href), repr(surrogate_path), urlsplit(surrogate_href))
    for value in (surrogate_href, surrogate_path):
        try:
            sqlite3.connect(":memory:").execute("select ?", (value,))
            print("sqlite ok", repr(value))
        except Exception as exc:
            print("sqlite raises", type(exc).__name__, exc)
    for href in ("http://[::1", "https://", "HTTPS://Example.ORG/Path", "mailto:a@b.c", "javascript:alert(1)", "/relative"):
        try:
            parts = urlsplit(href)
            print("urlsplit", repr(href), parts.scheme, repr(parts.netloc), repr(parts.hostname))
        except Exception as exc:
            print("urlsplit raises", repr(href), type(exc).__name__, exc)
    print("dollar-newline", bool(re.match(r"^[a-z0-9_]{1,64}$", "abc\n")), bool(re.fullmatch(r"[a-z0-9_]{1,64}", "abc\n")))
    print("bool-is-int", isinstance(True, int))
    assert False, "probe"
