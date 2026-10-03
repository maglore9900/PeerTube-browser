"""Internal translate endpoint: the English caption track a video's own instance holds, fetched within bounds, parsed as WebVTT once, cached in subtitles.db.

POST /internal/translate {id, host} answers {"state": "ready", "cues": [{start, end, text}]} or {"state": "none"}. An unknown or denylisted video answers 404 {"error": "Video not found"} before any remote fetch or store read. Only ready is stored; every failure is none and is never stored, so a track added later can still change the answer.

Bounds (AC6): https only, to the resolved row's instance_domain only, no redirect off that host, 2 MB per response, an 8 s wall-clock deadline per fetch inside a 15 s budget per request, 4 s per socket operation. Not bounded by the wall clock: DNS resolution inside urlopen and a TLS handshake stalling across several records (stdlib has no DNS timeout); accepted gap.
"""
from __future__ import annotations

import html
import http.client
import json
import logging
import re
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from data.moderation import list_active_denied_hosts, normalize_host
from data.subtitles import fetch_ready_subtitles, store_ready_subtitles
from data.time import now_ms
from handlers.video import resolve_video_row
from http_utils import read_json_body, respond_json

TARGET_LANGUAGE = "en"
SOURCE_INSTANCE = "instance"
FETCH_MAX_BYTES = 2_000_000
FETCH_DEADLINE_SECONDS = 8.0
# Two fetches share it, so the Client's 20 s timeout covers the budget plus one socket timeout past it.
REQUEST_BUDGET_SECONDS = 15.0
SOCKET_TIMEOUT_SECONDS = 4.0
READ_CHUNK_BYTES = 65_536
# The body resolve_video_row answers, reused for a denied host so the route does not reveal which check failed.
VIDEO_NOT_FOUND = {"error": "Video not found"}
_HEADER = re.compile(r"WEBVTT(?:[ \t].*)?")
_SKIPPED_BLOCK = re.compile(r"(?:NOTE|STYLE|REGION)(?:[ \t].*)?")
_TIMESTAMP = r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})"
_TIMING_LINE = re.compile(rf"{_TIMESTAMP}[ \t]+-->[ \t]+{_TIMESTAMP}(?:[ \t].*)?")
_TAG = re.compile(r"<[^>]*>")


def same_host_https(url: str, host: str) -> bool:
    """Whether url is https on exactly host, with no explicit port and no userinfo (R5)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname == host and port is None and parts.username is None and parts.password is None


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Follow a redirect only to https on the same host; any other target ends the fetch as an HTTPError."""

    def __init__(self, host: str) -> None:
        """Bind the handler to the one host its fetch may reach."""
        super().__init__()
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        """Refuse an off-host or non-https target; None makes urllib raise the 3xx as an HTTPError."""
        if not same_host_https(newurl, self.host):
            logging.info("[translate] refused redirect host=%s target=%s", self.host, newurl)
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bounded(host: str, path: str, budget_at: float) -> bytes | None:
    """GET https://<host><path> within the AC6 bounds; None on any failure, non-200, a body over FETCH_MAX_BYTES, or a passed deadline (the per-fetch one or the caller's monotonic budget_at)."""
    deadline = min(time.monotonic() + FETCH_DEADLINE_SECONDS, budget_at)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    request = Request(f"https://{host}{path}", headers={"accept": "application/json, text/vtt"})
    chunks: list[bytes] = []
    size = 0
    try:
        with build_opener(SameHostRedirectHandler(host)).open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, remaining)) as resp:
            if resp.status != 200:
                return None
            length = (resp.headers.get("content-length") or "").strip()
            if length.isdigit() and int(length) > FETCH_MAX_BYTES:
                logging.info("[translate] response over cap host=%s path=%s length=%s", host, path, length)
                return None
            while True:
                if time.monotonic() > deadline:
                    logging.info("[translate] fetch deadline passed host=%s path=%s", host, path)
                    return None
                # read1 returns what has arrived, so a trickling server cannot hold one read open past the deadline for more than one socket timeout.
                chunk = resp.read1(READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > FETCH_MAX_BYTES:
                    logging.info("[translate] response over cap host=%s path=%s", host, path)
                    return None
                chunks.append(chunk)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        # OSError covers HTTPError, URLError, timeouts, resets and ssl errors; ValueError covers InvalidURL and IDNA UnicodeError; HTTPException covers IncompleteRead and RemoteDisconnected.
        logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)
        return None
    return b"".join(chunks)


def pick_english_track_path(listing: bytes, host: str) -> str | None:
    """Return the path of the first caption whose language.id is exactly en, or None; a path that is not same-host https is refused (R5)."""
    try:
        payload = json.loads(listing.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    for item in data:
        language = item.get("language") if isinstance(item, dict) else None
        if isinstance(language, dict) and language.get("id") == TARGET_LANGUAGE:
            return _track_path(item, host)
    return None


def _track_path(item: dict[str, Any], host: str) -> str | None:
    """captionPath when it is a rooted path (not protocol-relative), else fileUrl's path when fileUrl is same-host https."""
    caption_path = item.get("captionPath")
    if isinstance(caption_path, str) and caption_path.startswith("/") and not caption_path.startswith("//"):
        return caption_path
    file_url = item.get("fileUrl")
    if isinstance(file_url, str) and same_host_https(file_url, host):
        parts = urlsplit(file_url)
        return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return None


def _seconds(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    """Convert one parsed WebVTT timestamp to seconds."""
    return round(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000, 3)


def _blocks(lines: list[str]) -> list[list[str]]:
    """Split lines into blocks separated by blank lines."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def parse_webvtt(text: str) -> list[dict[str, Any]] | None:
    """Parse a WebVTT track into cues {start, end, text} sorted by start, or None when any part fails (whole-track rejection, AC6) or no cue has text.

    The first line must be WEBVTT, optionally followed by a space or tab and text. After the header block, every block is a NOTE/STYLE/REGION block (skipped) or a cue: an optional identifier without "-->", then a timing line. Anything else rejects the track, and so does an end before its start. Cue text has its tags removed and its entities decoded; it is still untrusted and rendered with textContent only.
    """
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not _HEADER.fullmatch(lines[0]):
        return None
    cues: list[dict[str, Any]] = []
    for block in _blocks(lines)[1:]:
        if _SKIPPED_BLOCK.fullmatch(block[0]):
            continue
        timing_at = 0 if "-->" in block[0] else 1
        match = _TIMING_LINE.fullmatch(block[timing_at]) if len(block) > timing_at else None
        if match is None:
            return None
        start = _seconds(*match.group(1, 2, 3, 4))
        end = _seconds(*match.group(5, 6, 7, 8))
        if end < start:
            return None
        cue_text = html.unescape(_TAG.sub("", "\n".join(block[timing_at + 1:]))).strip()
        if cue_text:
            cues.append({"start": start, "end": end, "text": cue_text})
    # The page binary-searches by start, so the order is fixed here, once.
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    return cues or None


def fetch_instance_track(host: str, video_key: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Read host's caption list for video_key, fetch its first en track and parse it; the track text and cues, or None."""
    budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS
    listing = fetch_bounded(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = pick_english_track_path(listing, host) if listing is not None else None
    raw = fetch_bounded(host, path, budget_at) if path is not None else None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    cues = parse_webvtt(text)
    return (text, cues) if cues is not None else None


def _cached_cues(server: Any, video_id: str, instance_domain: str) -> list[dict[str, Any]] | None:
    """The stored ready cues, or None on a miss, a closed store, or a store error (read as a miss, so the instance answers instead)."""
    try:
        with server.subtitles_db_lock:
            conn = server.subtitles_db
            return fetch_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE) if conn is not None else None
    except sqlite3.Error as exc:
        logging.warning("[translate] cache read failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
        return None


def _store_cues(server: Any, video_id: str, instance_domain: str, track_text: str, cues: list[dict[str, Any]]) -> None:
    """Store a ready track; a failed write (e.g. locked by the other blue/green Engine) is logged and the answer stays ready."""
    try:
        with server.subtitles_db_lock:
            conn = server.subtitles_db
            if conn is not None:
                store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())
    except sqlite3.Error as exc:
        logging.warning("[translate] cache write failed video_id=%s host=%s: %s", video_id, instance_domain, exc)


def handle_internal_translate(handler: Any, server: Any) -> bool:
    """Answer a video's English translate state; nothing is read from the store or the instance until the video resolves and its host is not denied."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True
    video_id = body.get("id").strip() if isinstance(body.get("id"), str) else ""
    raw_host = body.get("host").strip() if isinstance(body.get("host"), str) else ""
    if not video_id or not raw_host:
        respond_json(handler, 400, {"error": "Missing id or host"})
        return True
    host = normalize_host(raw_host)
    if host is None:
        respond_json(handler, 400, {"error": "Invalid host"})
        return True
    resolved = resolve_video_row(handler, server, {"id": [video_id], "host": [host]})
    if resolved is None:
        return True
    row = resolved[0]
    # The row's own domain and canonical id, never the request's: the fetch goes to the video's instance and the store is keyed once per video.
    instance = row["instance_domain"]
    canonical_id = row["video_id"]
    with server.db_lock:
        denied = list_active_denied_hosts(server.db)
    if normalize_host(instance) in denied:
        respond_json(handler, 404, VIDEO_NOT_FOUND)
        return True
    cues = _cached_cues(server, canonical_id, instance)
    if cues is None:
        fetched = fetch_instance_track(instance, row["video_uuid"] or canonical_id)
        if fetched is None:
            respond_json(handler, 200, {"state": "none"})
            return True
        track_text, cues = fetched
        _store_cues(server, canonical_id, instance, track_text, cues)
    respond_json(handler, 200, {"state": "ready", "cues": cues})
    return True
