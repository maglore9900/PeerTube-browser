import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "server"))

from data import source_fetch  # noqa: E402
from data.moderation import normalize_host  # noqa: E402

_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")


def old_media_host(url):
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname or ""
    labels = host.rstrip(".").split(".")
    if parts.scheme != "https" or port is not None or parts.username is not None or parts.password is not None or normalize_host(host) is None:
        return None
    return host if len(labels) >= 2 and _TLD.fullmatch(labels[-1]) else None


URLS = [
    "https://media.example/v.mp4", "https://Media.Example./v.mp4", "https://MEDIA.EXAMPLE/v.mp4", "http://media.example/v.mp4",
    "https://203.0.113.7/v.wav", "https://[2001:db8::7]/v.wav", "https://2130706433/v.wav", "https://127.1/v.wav", "https://0x7f.0x1/v.wav",
    "https://media/v.wav", "https://media.example:8443/v.wav", "https://media.example:443/v.wav", "https://media.example:/v.wav", "https://user@media.example/v.wav",
    "https://user:pw@media.example/v.wav", "https://:pw@media.example/v.wav", "https://@media.example/v.wav", "https:///v.wav", "https://", "", "//media.example/v.wav",
    "https://[::1/v.wav", "https://media.example:99999/v.wav", "https://media.example:abc/v.wav", "https://xn--bcher-kva.example/v", "https://media.xn--p1ai/v",
    "https://bücher.example/v", "https://media.example\n/v", "ftp://media.example/v", "HTTPS://media.example/v", "https://media..example/v", "https://.example/v",
    "https://media.example#frag", "https://media.example?q=1", "https://a.b.c.example/v", "https://media.123/v", "https://media.e/v",
]


def test_new_media_host_matches_old_on_every_url():
    diffs = []
    for url in URLS:
        try:
            old = ("ok", old_media_host(url))
        except Exception as exc:  # noqa: BLE001
            old = ("raised", type(exc).__name__)
        try:
            new = ("ok", source_fetch.media_host(url))
        except Exception as exc:  # noqa: BLE001
            new = ("raised", type(exc).__name__)
        print(repr(url), old, new)
        if old != new:
            diffs.append((url, old, new))
    assert diffs == []
