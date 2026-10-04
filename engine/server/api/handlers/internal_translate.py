"""Internal translate endpoint: a video's English translate state from subtitles.db, or else the English caption track its own instance holds, fetched within bounds, parsed as WebVTT once, cached in subtitles.db.

POST /internal/translate {id, host, after?} answers a state, one of ready (with cues [{start, end, text}]), queued, running (cues from index after on, in stored order, and total, the stored count), failed, already_english or none, and on every 200 available: whether the translate worker beat within HEARTBEAT_FRESH_MS. An unknown or denylisted video answers 404 {"error": "Video not found"} (resolve_translatable_video, shared with the translate worker) before any remote fetch or store read; then an after that is not a JSON int of 0 or more answers 400. A queued or running row is answered with no fetch; a failed, already_english or missing row still fetches, and an instance track found then is stored ready over it; with the store closed (shutdown) it is answered but not stored, and an info line says so. This route stores only ready; an instance miss is never stored, so a track added later can still change the answer.

POST /internal/translate/enqueue {id, host} validates and resolves exactly as the state route does, then, only while the worker beat within HEARTBEAT_FRESH_MS, queues a whisper job under the canonical key with SUBTITLE_QUEUE_CAP: queued, the key's existing state (never overwritten), or busy at the cap, each with available true. Not available, a closed store included, answers {"state": "none", "available": false} and queues nothing; a store error from the enqueue answers 503.

Bounds (AC6): every instance fetch goes through the source-instance fetch in data/source_fetch.py (https only, to the resolved row's instance_domain only, no redirect off that host, 2 MB per response, an 8 s wall-clock deadline and 4 s per socket operation); this route adds a 15 s budget per request shared by its two fetches. Not bounded by the wall clock: DNS resolution and a TLS handshake stalling across several records; accepted gap.
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote, urlsplit

from data.moderation import list_active_denied_hosts, normalize_host
from data.source_fetch import SourceFetchFailed, fetch_bounded, same_host_https
from data.subtitles import SOURCE_INSTANCE, enqueue_translate_job, fetch_subtitle_state, fetch_translate_heartbeat, store_ready_subtitles
from data.time import now_ms
from handlers.video import fetch_video_row
from http_utils import read_json_body, respond_json
from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP

TARGET_LANGUAGE = "en"
# Two fetches share it, so the Client's 20 s timeout covers the budget plus one socket timeout past it.
REQUEST_BUDGET_SECONDS = 15.0
# Answered for every refusal of resolve_translatable_video, so the route does not reveal which check failed; the body /api/video answers for an unknown video.
VIDEO_NOT_FOUND = {"error": "Video not found"}
_HEADER = re.compile(r"WEBVTT(?:[ \t].*)?")
_SKIPPED_BLOCK = re.compile(r"(?:NOTE|STYLE|REGION)(?:[ \t].*)?")
_TIMESTAMP = r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})"
_TIMING_LINE = re.compile(rf"{_TIMESTAMP}[ \t]+-->[ \t]+{_TIMESTAMP}(?:[ \t].*)?")
_TAG = re.compile(r"<[^>]*>")


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


def _fetch(host: str, path: str, budget_at: float) -> bytes | None:
    """One instance fetch under the request's budget; None, with the adapter's reason logged, on any failure."""
    try:
        return fetch_bounded(host, path, budget_at=budget_at)
    except SourceFetchFailed as exc:
        logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)
        return None


def fetch_instance_track(host: str, video_key: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Read host's caption list for video_key, fetch its first en track and parse it; the track text and cues, or None."""
    budget_at = time.monotonic() + REQUEST_BUDGET_SECONDS
    listing = _fetch(host, f"/api/v1/videos/{quote(video_key, safe='')}/captions", budget_at)
    path = pick_english_track_path(listing, host) if listing is not None else None
    raw = _fetch(host, path, budget_at) if path is not None else None
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    cues = parse_webvtt(text)
    return (text, cues) if cues is not None else None


def resolve_translatable_video(conn: sqlite3.Connection, video_id: str, host: str | None, error_threshold: int | None) -> tuple[dict[str, Any] | None, str | None]:
    """The whitelisted row and None, or None and the refusal: missing host (decided before any lookup, since fetch_video_row with no host matches the id on any host), not in whitelist (fetch_video_row with error_threshold), host denied (the row's normalised domain is actively denied). Shared by both /internal/translate routes and the translate worker; takes no lock and writes no response."""
    if not host:
        return None, "missing host"
    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)
    if row is None:
        return None, "not in whitelist"
    if normalize_host(row["instance_domain"]) in list_active_denied_hosts(conn):
        return None, "host denied"
    return row, None


def _generation_available(conn: sqlite3.Connection) -> bool:
    """Whether a translate worker beat within HEARTBEAT_FRESH_MS (AC1); no beat, a store error, or a beat dated ahead of now is not available, so a wrong clock cannot hold it fresh. The caller holds subtitles_db_lock."""
    try:
        beat_at = fetch_translate_heartbeat(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] heartbeat read failed: %s", exc)
        return False
    return beat_at is not None and 0 <= now_ms() - beat_at <= HEARTBEAT_FRESH_MS


@contextmanager
def _subtitles_store(server: Any) -> Iterator[sqlite3.Connection | None]:
    """Hold subtitles_db_lock for the whole body and yield subtitles_db, None when the store is closed; errors pass through to the caller's own handler."""
    with server.subtitles_db_lock:
        yield server.subtitles_db


def _read_key(server: Any, video_id: str, instance_domain: str) -> tuple[tuple[str, str | None] | None, bool]:
    """The key's (state, cues_json) and whether generation is available, under one lock hold; a closed store or a store error reads as no row and not available, so the instance answers instead."""
    try:
        with _subtitles_store(server) as conn:
            if conn is None:
                return None, False
            return fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE), _generation_available(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] cache read failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
        return None, False


def _stored_cues(cues_json: str | None) -> list[Any] | None:
    """cues_json loaded as a list, or None when it is unset, does not load, or is not a list."""
    try:
        cues = json.loads(cues_json or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) else None


def _store_cues(server: Any, video_id: str, instance_domain: str, track_text: str, cues: list[dict[str, Any]]) -> None:
    """Store a ready track; a closed store (shutdown) stores nothing and a failed write (e.g. locked by the other blue/green Engine) is logged, and the answer stays ready either way."""
    try:
        with _subtitles_store(server) as conn:
            if conn is None:
                logging.info("[translate] cache closed, track not stored video_id=%s host=%s", video_id, instance_domain)
                return
            store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())
    except sqlite3.Error as exc:
        logging.warning("[translate] cache write failed video_id=%s host=%s: %s", video_id, instance_domain, exc)


def _resolve_translate_key(handler: Any, server: Any) -> tuple[dict[str, Any], str, str, str] | None:
    """Validate the {id, host} body and resolve its video as both translate routes must: (body, canonical video_id, instance_domain, the instance's video key); None once a 400 or 404 was answered."""
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return None
    video_id = body.get("id").strip() if isinstance(body.get("id"), str) else ""
    raw_host = body.get("host").strip() if isinstance(body.get("host"), str) else ""
    if not video_id or not raw_host:
        respond_json(handler, 400, {"error": "Missing id or host"})
        return None
    host = normalize_host(raw_host)
    if host is None:
        respond_json(handler, 400, {"error": "Invalid host"})
        return None
    with server.db_lock:
        row, _ = resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)
    if row is None:
        respond_json(handler, 404, VIDEO_NOT_FOUND)
        return None
    # The row's own domain and canonical id, never the request's: the fetch goes to the video's instance and the store is keyed once per video.
    canonical_id = row["video_id"]
    return body, canonical_id, row["instance_domain"], row["video_uuid"] or canonical_id


def handle_internal_translate(handler: Any, server: Any) -> bool:
    """Answer a video's English translate state with whether generation is available; nothing is read from the store or the instance until the video resolves and its host is not denied."""
    resolved = _resolve_translate_key(handler, server)
    if resolved is None:
        return True
    body, canonical_id, instance, video_key = resolved
    after = body.get("after", 0)
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        respond_json(handler, 400, {"error": "Invalid after"})
        return True
    stored_row, available = _read_key(server, canonical_id, instance)
    state = stored_row[0] if stored_row is not None else None
    stored = _stored_cues(stored_row[1]) if stored_row is not None else None
    if state == "ready" and stored:
        respond_json(handler, 200, {"state": "ready", "cues": stored, "available": available})
        return True
    # A queued or running job is answered from the store with no instance fetch; the worker checks the instance itself when it claims the job.
    if state == "queued":
        respond_json(handler, 200, {"state": "queued", "available": available})
        return True
    if state == "running":
        cues = stored or []
        respond_json(handler, 200, {"state": "running", "cues": cues[after:], "total": len(cues), "available": available})
        return True
    fetched = fetch_instance_track(instance, video_key)
    if fetched is not None:
        track_text, cues = fetched
        _store_cues(server, canonical_id, instance, track_text, cues)
        respond_json(handler, 200, {"state": "ready", "cues": cues, "available": available})
        return True
    # A ready row whose cues do not load reads as none: a ready answer without cues is refused downstream.
    respond_json(handler, 200, {"state": state if state in ("failed", "already_english") else "none", "available": available})
    return True


def handle_internal_translate_enqueue(handler: Any, server: Any) -> bool:
    """Queue a whisper job for a video when a translate worker is serving: queued, the existing state (a row is never overwritten), or busy when the queue is full; not available (a closed store included) queues nothing."""
    resolved = _resolve_translate_key(handler, server)
    if resolved is None:
        return True
    _, canonical_id, instance, _ = resolved
    try:
        # One lock hold, so availability cannot flip between the beat read and the enqueue.
        with _subtitles_store(server) as conn:
            outcome = enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if conn is not None and _generation_available(conn) else None
    except sqlite3.Error as exc:
        logging.warning("[translate] enqueue failed video_id=%s host=%s: %s", canonical_id, instance, exc)
        respond_json(handler, 503, {"error": "Translate store unavailable"})
        return True
    if outcome is None:
        respond_json(handler, 200, {"state": "none", "available": False})
        return True
    kind, state = outcome
    respond_json(handler, 200, {"state": "busy" if kind == "cap" else state, "available": True})
    return True
