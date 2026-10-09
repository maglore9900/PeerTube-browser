"""Source-instance fetch (CONTEXT.md): the one rule for every request to a PeerTube instance, or to a media host its JSON names, both untrusted.

https only, no explicit port, no userinfo, redirects followed only to https on the same host, a time bound, and a failure that says why (SourceFetchFailed). fetch_bounded buffers a JSON or WebVTT body under a byte cap and a wall-clock deadline; stream_media hands a media download to a consumer chunk by chunk, uncapped, under a socket timeout only. Both open through _open, so this module's build_opener is the one place tests stub the network. Not bounded by the wall clock: DNS resolution and a TLS handshake stalling across several records (stdlib has no DNS timeout); accepted gap.
"""
from __future__ import annotations

import http.client
import logging
import re
import threading
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from data.moderation import normalize_host

FETCH_MAX_BYTES = 2_000_000
FETCH_DEADLINE_SECONDS = 8.0
SOCKET_TIMEOUT_SECONDS = 4.0
READ_CHUNK_BYTES = 65_536
# The only stall bound on the download; there is no whole-job deadline.
MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0
# A DNS name's last label is letters or punycode, never digits or hex.
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
# OSError covers HTTPError, URLError, timeouts, resets and ssl errors; ValueError covers InvalidURL and IDNA UnicodeError; HTTPException covers IncompleteRead and RemoteDisconnected.
_FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)


class SourceFetchFailed(Exception):
    """A source-instance fetch failed; the message is the short reason."""


def same_host_https(url: str, host: str) -> bool:
    """Whether url is https on exactly host, with no explicit port and no userinfo (R5)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


def media_host(url: str) -> str | None:
    """The raw urlsplit hostname of an acceptable media URL (https, a DNS name, no port, no userinfo), else None; raw, not normalize_host's, so SameHostRedirectHandler's exact compare holds."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None
    labels = host.rstrip(".").split(".")
    # same_host_https against the URL's own hostname is the https, no-port, no-userinfo check alone.
    if not same_host_https(url, host) or normalize_host(host) is None:
        return None
    # Two labels or more ending in a real TLD refuses every IP literal, and also 127.1, 2130706433 and 0x7f.0x1, which inet_aton resolves but ipaddress rejects.
    return host if len(labels) >= 2 and _TLD.fullmatch(labels[-1]) else None


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only to https on the same host; any other target ends the fetch as an HTTPError, its URL kept in refused."""

    def __init__(self, host: str) -> None:
        """Bind the handler to the one host its fetch may reach; one handler per fetch, so refused never carries over."""
        super().__init__()
        self.host = host
        self.refused: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        """Refuse an off-host or non-https target; None makes urllib raise the 3xx as an HTTPError."""
        if not same_host_https(newurl, self.host):
            logging.info("[source-fetch] refused redirect host=%s target=%s", self.host, newurl)
            self.refused = newurl
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: Request, handler: SameHostRedirectHandler, timeout: float):  # noqa: ANN202
    """Open request through handler's redirect policy: the one build_opener call, looked up at call time so a stub of this module's build_opener reaches both forms."""
    return build_opener(handler).open(request, timeout=timeout)


def fetch_bounded(host: str, path: str, *, max_bytes: int = FETCH_MAX_BYTES, deadline_seconds: float = FETCH_DEADLINE_SECONDS, budget_at: float | None = None, socket_timeout: float = SOCKET_TIMEOUT_SECONDS, headers: dict[str, str] | None = None) -> bytes:
    """GET https://<host><path> under the rule and return the body; SourceFetchFailed with the reason on a non-200, a refused redirect, a body over max_bytes, a passed deadline (deadline_seconds from now, or the caller's monotonic budget_at when earlier) or a fetch error. headers replace the default accept header."""
    now = time.monotonic()
    # remaining first and the deadline from it: (now + s) - now is not exactly s in floating point, and a caller passing socket_timeout == deadline_seconds must get exactly that timeout.
    remaining = deadline_seconds if budget_at is None else min(deadline_seconds, budget_at - now)
    if remaining <= 0:
        raise SourceFetchFailed("deadline passed")
    deadline = now + remaining
    request = Request(f"https://{host}{path}", headers=headers if headers is not None else {"accept": "application/json, text/vtt"})
    handler = SameHostRedirectHandler(host)
    chunks: list[bytes] = []
    size = 0
    try:
        with _open(request, handler, min(socket_timeout, remaining)) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"HTTP {resp.status}")
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > max_bytes:
                raise SourceFetchFailed(f"Content-Length {length} over {max_bytes} bytes")
            while True:
                if time.monotonic() > deadline:
                    raise SourceFetchFailed("deadline passed")
                # read1 returns what has arrived, so a trickling server cannot hold one read open past the deadline for more than one socket timeout.
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise SourceFetchFailed(f"body over {max_bytes} bytes")
                chunks.append(chunk)
    except HTTPError as exc:
        # urllib raises a 4xx/5xx, and a 3xx the handler refused, instead of returning it; caught before OSError so the reason stays distinct. fp is None on an HTTPError built by hand.
        if exc.fp is not None:
            exc.close()
        raise SourceFetchFailed(f"redirect refused: {handler.refused}" if handler.refused is not None else f"HTTP {exc.code}") from exc
    except _FETCH_ERRORS as exc:
        raise SourceFetchFailed(str(exc) or type(exc).__name__) from exc
    return b"".join(chunks)


def stream_media(url: str, host: str, consume: Callable[[bytes], object], stop: threading.Event) -> None:
    """Download url through the same-host redirect policy bound to host (media_host's raw hostname), passing each chunk to consume until EOF or stop is set; SourceFetchFailed on a non-200 or a fetch error. No byte cap, since the consumer streams it and stores nothing, and no wall-clock deadline: MEDIA_SOCKET_TIMEOUT_SECONDS is the only stall bound. A BrokenPipeError from consume propagates unchanged."""
    try:
        with _open(Request(url), SameHostRedirectHandler(host), MEDIA_SOCKET_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"media download failed: HTTP {resp.status}")
            while not stop.is_set():
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                consume(chunk)
    except BrokenPipeError:
        # The consumer's pipe closed, not the download; an OSError, so it must pass before the tuple below.
        raise
    except _FETCH_ERRORS as exc:
        # A refused redirect is an HTTPError here too and keeps its "HTTP Error 302: ..." text (TRANSLATE_WORKER.md Error Texts).
        raise SourceFetchFailed(f"media download failed: {exc}") from exc
