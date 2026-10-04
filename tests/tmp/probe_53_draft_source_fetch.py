"""The plan 53 draft of data/source_fetch.py, copied verbatim for a probe run of the phase 1 checkpoint; not the module under test."""
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
MEDIA_SOCKET_TIMEOUT_SECONDS = 15.0
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
_FETCH_ERRORS = (OSError, ValueError, http.client.HTTPException)
MUTATION = None


class SourceFetchFailed(Exception):
    pass


def same_host_https(url: str, host: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


def media_host(url: str) -> str | None:
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


class SameHostRedirectHandler(HTTPRedirectHandler):
    def __init__(self, host: str) -> None:
        super().__init__()
        self.host = host
        self.refused: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not same_host_https(newurl, self.host):
            logging.info("[source-fetch] refused redirect host=%s target=%s", self.host, newurl)
            self.refused = newurl
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SHARED: dict = {}


def _open(request, handler, timeout):  # noqa: ANN001, ANN202
    return build_opener(handler).open(request, timeout=timeout)


def fetch_bounded(host: str, path: str, *, max_bytes: int = FETCH_MAX_BYTES, deadline_seconds: float = FETCH_DEADLINE_SECONDS, budget_at: float | None = None, socket_timeout: float = SOCKET_TIMEOUT_SECONDS, headers: dict[str, str] | None = None) -> bytes:
    now = time.monotonic()
    remaining = deadline_seconds if budget_at is None else min(deadline_seconds, budget_at - now)
    if remaining <= 0:
        raise SourceFetchFailed("deadline passed")
    deadline = now + remaining
    request = Request(f"https://{host}{path}", headers=headers if headers is not None else {"accept": "application/json, text/vtt"})
    handler = _SHARED.setdefault(host, SameHostRedirectHandler(host)) if MUTATION == "shared handler" else SameHostRedirectHandler(host)
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
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes and MUTATION != "read past cap":
                    raise SourceFetchFailed(f"body over {max_bytes} bytes")
                chunks.append(chunk)
            if MUTATION == "read past cap" and size > max_bytes:
                raise SourceFetchFailed(f"body over {max_bytes} bytes")
    except HTTPError as exc:
        if exc.fp is not None:
            exc.close()
        raise SourceFetchFailed(f"redirect refused: {handler.refused}" if handler.refused is not None else f"HTTP {exc.code}") from exc
    except _FETCH_ERRORS as exc:
        raise SourceFetchFailed(str(exc) or type(exc).__name__) from exc
    return b"".join(chunks)


def stream_media(url: str, host: str, max_bytes: int, consume: Callable[[bytes], object], stop: threading.Event) -> None:
    if MUTATION == "constant media cap":
        max_bytes = 200_000
    try:
        with _open(Request(url), SameHostRedirectHandler(host), MEDIA_SOCKET_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                raise SourceFetchFailed(f"media download failed: HTTP {resp.status}")
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > max_bytes:
                raise SourceFetchFailed(f"media over {max_bytes} bytes")
            size = 0
            while MUTATION == "ignore stop" or not stop.is_set():
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if MUTATION == "consume before check":
                    consume(chunk)
                if size > max_bytes:
                    raise SourceFetchFailed(f"media over {max_bytes} bytes")
                if MUTATION != "consume before check":
                    consume(chunk)
    except BrokenPipeError:
        if MUTATION == "wrap broken pipe":
            raise SourceFetchFailed("media download failed: broken pipe")
        raise
    except _FETCH_ERRORS as exc:
        raise SourceFetchFailed(f"media download failed: {exc}") from exc
