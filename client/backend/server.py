#!/usr/bin/env python3
"""Client backend service for write/profile endpoints and bridge publishing."""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import sqlite3
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from datetime import datetime

from lib.blocks import (KINDS as BLOCK_KINDS, BlockKeys, BlockLimitReached, MAX_BLOCKS,
                        add_block, block_target, filter_blocked, list_blocks, load_block_keys,
                        remove_block)
from lib.dislikes import (MAX_DISLIKES, DislikeLimitReached, delete_dislike, dislike_entries,
                          filter_disliked, is_disliked, load_centroids, load_disliked_keys,
                          write_dislike)
from lib.engine_api_client import (EngineApiError, bridge_headers, compute_dislike_centroids,
                                   fetch_metadata_for_entries,
                                   resolve_video_seed, resolve_videos_by_uuid_host)
from lib.http_utils import (RateLimiter, read_json_body, respond_bytes, respond_json,
                            respond_options)
from lib.profiles import delete_profile, mint_profile, resolve_profile, rotate_key
from lib.time_utils import now_ms
from lib.users_store import (clear_likes, ensure_user_schema, fetch_recent_likes,
                             get_or_create_user, record_like, remove_like, video_reaction)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent

DEFAULT_CLIENT_HOST = "127.0.0.1"
DEFAULT_CLIENT_PORT = 7172
DEFAULT_ENGINE_INGEST_BASE = "http://127.0.0.1:7070"
DEFAULT_USERS_DB_PATH = "client/backend/db/users.db"
DEFAULT_CLIENT_PUBLISH_MODE = os.environ.get("CLIENT_PUBLISH_MODE", "bridge").strip().lower()
MAX_LIKES = 100
MAX_CLIENT_LIKES = 200
# rat-tail: mirrors the Engine's DEFAULT_CLIENT_LIKES_MAX, the most likes a feed request may
# carry; the browser samples the same number from its local likes.
ENGINE_FEED_LIKES_MAX = 5
USER_ACTIONS = frozenset(("like", "undo_like", "dislike", "undo_dislike"))
DISLIKE_ACTIONS = frozenset(("dislike", "undo_dislike"))
RATE_LIMIT_MAX_REQUESTS = 90
RATE_LIMIT_WINDOW_SECONDS = 60
PROFILE_MINT_MAX_REQUESTS = 5
PROFILE_MINT_WINDOW_SECONDS = 3600
BLOCK_REFERENCE_MAX_LENGTH = 200
# rat-tail: mirrors the Engine's home `batch_size` (engine/server/api/server_config.py);
# fetch it from the Engine if the two ever need to differ.
FEED_PAGE_SIZE = 48
FEED_OVERFETCH_FACTOR = 2
FEED_ROUTES = frozenset(("/recommendations", "/videos/similar"))
FILTERED_ROUTES = FEED_ROUTES | {"/api/v1/search/videos"}
# A profile's blocked channels and accounts, and its disliked `(video_id, instance_domain)`s.
RowFilter = tuple[BlockKeys, set[tuple[str, str]]]
ENGINE_PROXY_TIMEOUT_SECONDS = 10
ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000
ENGINE_PROXY_RETRY_COUNT = 1
ENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25
PROXY_READ_GET_ROUTES = frozenset(
    ("/api/video", "/api/channels", "/api/v1/search/videos")
)
PROXY_READ_POST_ROUTES = frozenset(("/recommendations", "/videos/similar"))
PROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {
    "/recommendations": {"id", "host", "limit", "random", "debug", "mode", "user_id"},
    "/videos/similar": {"id", "host", "limit", "random", "debug", "mode", "user_id"},
    "/api/video": {"id", "host", "refresh_cache", "user_id"},
    "/api/v1/search/videos": {"q", "page", "limit", "sort"},
    "/api/channels": {
        "limit",
        "offset",
        "q",
        "instance",
        "minFollowers",
        "minVideos",
        "maxVideos",
        "sort",
        "dir",
    },
}
PROXY_ALLOWED_BODY_KEYS: dict[str, set[str]] = {
    "/recommendations": {"likes", "user_id", "mode"},
    "/videos/similar": {"likes", "user_id", "mode"},
}


def _resolve_mode(value: str, default: str = "bridge") -> str:
    """Handle resolve mode."""
    normalized = value.strip().lower()
    return normalized if normalized in {"bridge", "activitypub"} else default


def _emit_client_log(
    level: int,
    event: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Emit one structured JSON log line for Client backend service."""
    payload: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level),
        "service": "client-backend",
        "event": event,
        "message": message,
    }
    if context:
        payload["context"] = context
    logging.log(level, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def parse_args() -> argparse.Namespace:
    """Handle parse args."""
    parser = argparse.ArgumentParser(description="Run PeerTube Client backend service.")
    parser.add_argument("--host", default=DEFAULT_CLIENT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CLIENT_PORT)
    parser.add_argument("--engine-url", dest="engine_ingest_base", default=DEFAULT_ENGINE_INGEST_BASE)
    parser.add_argument("--publish-mode", default=_resolve_mode(DEFAULT_CLIENT_PUBLISH_MODE))
    return parser.parse_args()


def connect_db(path: Path) -> sqlite3.Connection:
    """Handle connect db."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class ClientBackendServer(ThreadingHTTPServer):
    """Threaded server with shared DB handles and config."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        user_db: sqlite3.Connection,
        engine_ingest_base: str,
        publish_mode: str,
        rate_limiter: RateLimiter,
    ) -> None:
        """Initialize the instance."""
        super().__init__(server_address, handler_class)
        self.user_db = user_db
        self.engine_ingest_base = engine_ingest_base.rstrip("/")
        self.publish_mode = _resolve_mode(publish_mode)
        self.rate_limiter = rate_limiter
        # Minting writes a durable row on an unauthenticated call, so it gets its own,
        # far tighter budget than the read routes.
        self.mint_rate_limiter = RateLimiter(PROFILE_MINT_MAX_REQUESTS, PROFILE_MINT_WINDOW_SECONDS)


class ClientBackendHandler(BaseHTTPRequestHandler):
    """HTTP handler for Client backend write/profile endpoints."""

    def _get_client_ip(self) -> str:
        """Handle get client ip."""
        forwarded_for = self.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first:
                return first
        real_ip = self.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        if self.client_address:
            return self.client_address[0]
        return "unknown"

    def _get_full_url(self) -> str:
        """Handle get full url."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def log_message(self, format: str, *args: Any) -> None:
        """Emit readable access logs instead of BaseHTTPRequestHandler defaults."""
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        _emit_client_log(
            logging.INFO,
            "client.access",
            "request finished",
            {
                "ip": self._get_client_ip(),
                "method": self.command or "-",
                "url": self._get_full_url(),
                "status": str(status),
                "bytes": str(size),
            },
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle do options."""
        respond_options(self)

    def do_GET(self) -> None:  # noqa: N802
        """Handle do get."""
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path in PROXY_READ_GET_ROUTES:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_engine_read_proxy_get(url.path, params)
            return
        if url.path == "/api/health":
            respond_json(
                self,
                200,
                {
                    "ok": True,
                    "service": "client-backend",
                    "engine_ingest_base": self.server.engine_ingest_base,
                    "publish_mode": self.server.publish_mode,
                },
            )
            return
        if url.path == "/api/user-profile":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            user_id = self._require_profile()
            if user_id is None:
                return
            with self.server.user_db:
                get_or_create_user(self.server.user_db, user_id)
                likes = fetch_recent_likes(self.server.user_db, user_id, MAX_LIKES)
            respond_json(self, 200, {"user_id": user_id, "likes": likes, "updatedAt": now_ms()})
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_get(params)
            return
        if url.path == "/api/profile/blocks":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            profile_id = self._require_profile()
            if profile_id is not None:
                respond_json(self, 200, {"blocks": list_blocks(self.server.user_db, profile_id)})
            return
        if url.path == "/api/profile/reaction":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_reaction_get(params)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        """Handle do post."""
        url = urlparse(self.path)
        if url.path in PROXY_READ_POST_ROUTES:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_engine_read_proxy_post(url.path, url)
            return
        if url.path == "/api/profile":
            peer = self.client_address[0] if self.client_address else "unknown"
            if not self.server.mint_rate_limiter.allow(peer):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            profile_id, key = mint_profile(self.server.user_db)
            respond_json(self, 201, {"profile_id": profile_id, "key": key})
            return
        if url.path == "/api/profile/rotate":
            profile_id = self._require_profile()
            if profile_id is not None:
                respond_json(self, 200, {"key": rotate_key(self.server.user_db, profile_id)})
            return
        if url.path == "/api/profile/delete":
            profile_id = self._require_profile()
            if profile_id is not None:
                delete_profile(self.server.user_db, profile_id)
                respond_bytes(self, 204, b"")
            return
        if url.path == "/api/user-action":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_action()
            return
        if url.path == "/api/user-profile/reset":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_reset()
            return
        if url.path == "/api/user-profile/likes":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_user_profile_likes_from_client()
            return
        if url.path == "/api/profile/likes/import":
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            self._handle_likes_import()
            return
        if url.path in ("/api/profile/blocks", "/api/profile/blocks/remove"):
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            if url.path == "/api/profile/blocks":
                self._handle_block_add()
            else:
                self._handle_block_remove()
            return
        # /client/events/publish is deliberately absent: it forwarded an arbitrary
        # browser-supplied body straight to the Engine's bridge ingest, which let any
        # anonymous caller write the global ranking signal. Events are published from
        # _handle_user_action, where the video identity has already been validated.
        respond_json(self, 404, {"error": "Not found"})

    def _require_profile(self) -> str | None:
        """Return the profile proved by `X-Profile-Key`, or answer 401 and return None.

        One response for every failure, so a caller cannot tell a malformed key from an
        unknown one or learn whether a profile exists.
        """
        profile_id = resolve_profile(self.server.user_db, self.headers.get("X-Profile-Key"))
        if profile_id is None:
            respond_json(self, 401, {"error": "Profile key required"})
        return profile_id

    def _rate_limit_check(self, path: str) -> bool:
        """Handle rate limit check."""
        ip = self.client_address[0] if self.client_address else "unknown"
        key = f"{ip}:{path}"
        return self.server.rate_limiter.allow(key)

    def _handle_engine_read_proxy_get(self, path: str, params: dict[str, list[str]]) -> None:
        """Handle handle engine read proxy get."""
        allowed = PROXY_ALLOWED_QUERY_PARAMS.get(path, set())
        sanitized: dict[str, str] = {}
        for key, values in params.items():
            if key not in allowed:
                respond_json(self, 400, {"error": f"Unknown query parameter: {key}"})
                return
            if not values:
                continue
            if len(values) != 1:
                respond_json(self, 400, {"error": f"Multiple values are not allowed for query parameter: {key}"})
                return
            value = values[0].strip()
            if value:
                sanitized[key] = value
        proceed, row_filter, page_size, _ = self._profile_filter(path, sanitized)
        if proceed:
            self._proxy_engine_request("GET", path, sanitized_query=sanitized,
                                       row_filter=row_filter, page_size=page_size)

    def _profile_filter(
        self, path: str, query: dict[str, str]
    ) -> tuple[bool, RowFilter | None, int | None, str | None]:
        """Decide how a read is filtered for the presented profile, adjusting `query`.

        Blocks apply to feeds and search; dislikes to feeds only.

        :returns: ``(proceed, row_filter, page_size, profile_id)``. ``proceed`` is False when
            a key was presented and refused, and the 401 has been sent. ``row_filter`` is None
            when the response passes through untouched.
        """
        page_size = None
        if path in FEED_ROUTES:
            # The Engine serves up to twice a page for the over-fetch below; a browser gets one page.
            page_size = min(_parse_int(query.get("limit")) or FEED_PAGE_SIZE, FEED_PAGE_SIZE)
            query["limit"] = str(page_size)
        if path not in FILTERED_ROUTES or self.headers.get("X-Profile-Key") is None:
            return True, None, None, None
        profile_id = self._require_profile()
        if profile_id is None:
            return False, None, None, None
        block_keys = load_block_keys(self.server.user_db, profile_id)
        disliked = load_disliked_keys(self.server.user_db, profile_id) if path in FEED_ROUTES else set()
        if not block_keys[0] and not block_keys[1] and not disliked:
            return True, None, None, profile_id
        if page_size is not None:
            query["limit"] = str(page_size * FEED_OVERFETCH_FACTOR)
        return True, (block_keys, disliked), page_size, profile_id

    def _handle_engine_read_proxy_post(self, path: str, url: Any) -> None:
        """Handle handle engine read proxy post."""
        query_params = parse_qs(url.query)
        allowed_query = PROXY_ALLOWED_QUERY_PARAMS.get(path, set())
        sanitized_query: dict[str, str] = {}
        for key, values in query_params.items():
            if key not in allowed_query:
                respond_json(self, 400, {"error": f"Unknown query parameter: {key}"})
                return
            if not values:
                continue
            if len(values) != 1:
                respond_json(self, 400, {"error": f"Multiple values are not allowed for query parameter: {key}"})
                return
            value = values[0].strip()
            if value:
                sanitized_query[key] = value
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        if not isinstance(body, dict):
            respond_json(self, 400, {"error": "Invalid JSON body"})
            return
        allowed_body_keys = PROXY_ALLOWED_BODY_KEYS.get(path, set())
        sanitized_body: dict[str, Any] = {}
        for key, value in body.items():
            if key not in allowed_body_keys:
                respond_json(self, 400, {"error": f"Unknown body field: {key}"})
                return
            sanitized_body[key] = value
        likes = sanitized_body.get("likes")
        if likes is not None:
            if not isinstance(likes, list):
                respond_json(self, 400, {"error": "Invalid likes payload"})
                return
            sanitized_likes: list[dict[str, str]] = []
            for entry in likes[:MAX_CLIENT_LIKES]:
                if not isinstance(entry, dict):
                    continue
                uuid = entry.get("uuid")
                host = entry.get("host")
                if not isinstance(uuid, str) or not uuid.strip():
                    continue
                if not isinstance(host, str) or not host.strip():
                    continue
                sanitized_likes.append({"uuid": uuid.strip(), "host": host.strip()})
            sanitized_body["likes"] = sanitized_likes
        if path == "/recommendations":
            likes_count, likes_list, likes_omitted = _summarize_proxy_likes(
                sanitized_body.get("likes")
            )
            _emit_client_log(
                logging.INFO,
                "recommendations.incoming_likes",
                "incoming likes payload",
                {
                    "likes_count": likes_count,
                    "likes": likes_list,
                    "likes_omitted": likes_omitted,
                    "user_id": sanitized_body.get("user_id"),
                    "mode": sanitized_body.get("mode"),
                },
            )
        proceed, row_filter, page_size, profile_id = self._profile_filter(path, sanitized_query)
        if not proceed:
            return
        if profile_id is not None:
            # A profile's own likes and centroids replace anything the browser sent, and are
            # added after sanitising, so the browser cannot supply either.
            stored = fetch_recent_likes(self.server.user_db, profile_id, MAX_LIKES)
            sample = random.sample(stored, min(ENGINE_FEED_LIKES_MAX, len(stored)))
            sanitized_body["likes"] = [{"uuid": like["video_uuid"], "host": like["instance_domain"]}
                                       for like in sample if like["video_uuid"] and like["instance_domain"]]
            centroids = load_centroids(self.server.user_db, profile_id)
            if centroids is not None:
                sanitized_body["dislike_centroids"] = centroids
        self._proxy_engine_request(
            "POST",
            path,
            sanitized_query=sanitized_query,
            body=sanitized_body,
            row_filter=row_filter,
            page_size=page_size,
        )

    def _proxy_engine_request(
        self,
        method: str,
        path: str,
        sanitized_query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        row_filter: RowFilter | None = None,
        page_size: int | None = None,
    ) -> None:
        """Handle proxy engine request."""
        sanitized_query = sanitized_query or {}
        upstream = f"{self.server.engine_ingest_base}{path}"
        if sanitized_query:
            upstream = f"{upstream}?{urlencode(sanitized_query)}"
        started_at = time.perf_counter()
        request_data: bytes | None = None
        # The Engine sees this process as its only peer, so without a forwarded
        # identity its per-IP rate limiter degenerates into one bucket shared by
        # every visitor. The Engine is loopback-bound, so this header is only ever
        # set by us.
        headers = {"accept": "application/json", "x-client-ip": self._get_client_ip()}
        if method == "POST":
            request_data = json.dumps(body or {}).encode("utf-8")
            if len(request_data) > ENGINE_PROXY_MAX_BODY_BYTES:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return
            headers["content-type"] = "application/json"
        request = Request(
            upstream,
            data=request_data,
            method=method,
            headers=headers,
        )
        last_transport_error: Exception | None = None
        for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1):
            try:
                with urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS) as response:
                    payload = response.read()
                    status = int(response.status)
                    if row_filter is not None and status == 200:
                        filtered = _filter_payload(payload, row_filter, page_size)
                        if filtered is None:
                            # Never pass an unreadable page through: it could hold blocked rows.
                            respond_json(self, 502, {"error": "Engine read proxy returned an invalid page",
                                                     "code": "ENGINE_PROXY_INVALID"})
                            return
                        payload = filtered
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    content_type = response.headers.get("content-type", "application/json; charset=utf-8")
                    if not respond_bytes(self, status, payload, content_type):
                        _emit_client_log(
                            logging.INFO,
                            "engine.proxy",
                            "client disconnected before proxy response write",
                            {
                                "method": method,
                                "path": path,
                                "status": status,
                                "attempt": attempt + 1,
                                "duration_ms": duration_ms,
                            },
                        )
                        return
                    _emit_client_log(
                        logging.INFO,
                        "engine.proxy",
                        "proxy request completed",
                        {
                            "method": method,
                            "path": path,
                            "status": status,
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                        },
                    )
                    return
            except HTTPError as exc:
                payload = exc.read() if exc.fp else b""
                if payload:
                    content_type = exc.headers.get("content-type", "application/json; charset=utf-8")
                    duration_ms = int((time.perf_counter() - started_at) * 1000)
                    if not respond_bytes(self, int(exc.code), payload, content_type):
                        _emit_client_log(
                            logging.INFO,
                            "engine.proxy",
                            "client disconnected before proxy response write",
                            {
                                "method": method,
                                "path": path,
                                "status": int(exc.code),
                                "attempt": attempt + 1,
                                "duration_ms": duration_ms,
                            },
                        )
                        return
                    _emit_client_log(
                        logging.INFO,
                        "engine.proxy",
                        "proxy request completed",
                        {
                            "method": method,
                            "path": path,
                            "status": int(exc.code),
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                        },
                    )
                    return
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _emit_client_log(
                    logging.WARNING,
                    "engine.proxy",
                    "proxy request failed",
                    {
                        "method": method,
                        "path": path,
                        "status": int(exc.code),
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "error": "no-payload",
                    },
                )
                respond_json(self, int(exc.code), {"error": f"Engine read proxy HTTP {int(exc.code)}"})
                return
            except (URLError, TimeoutError) as exc:
                last_transport_error = exc
                if attempt < ENGINE_PROXY_RETRY_COUNT:
                    time.sleep(ENGINE_PROXY_RETRY_DELAY_SECONDS)
                    continue
                break
            except Exception as exc:  # pragma: no cover
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                _emit_client_log(
                    logging.ERROR,
                    "engine.proxy",
                    "proxy request exception",
                    {
                        "method": method,
                        "path": path,
                        "status": 502,
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                respond_json(
                    self,
                    502,
                    {"error": "Engine read proxy failed", "code": "ENGINE_PROXY_FAILURE", "detail": str(exc)},
                )
                return
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        _emit_client_log(
            logging.WARNING,
            "engine.proxy",
            "proxy request unavailable",
            {
                "method": method,
                "path": path,
                "status": 502,
                "attempts": ENGINE_PROXY_RETRY_COUNT + 1,
                "duration_ms": duration_ms,
                "error": str(last_transport_error) if last_transport_error is not None else "unknown transport error",
            },
        )
        respond_json(
            self,
            502,
            {
                "error": "Engine read proxy failed",
                "code": "ENGINE_PROXY_UNAVAILABLE",
                "detail": str(last_transport_error) if last_transport_error is not None else "Unknown transport error",
            },
        )
        return

    def _handle_user_action(self) -> None:
        """Handle handle user action."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        action = str(body.get("action") or "").strip().lower()
        if action not in USER_ACTIONS:
            respond_json(self, 400, {"error": "Unsupported action"})
            return
        video_id = body.get("video_id")
        host = body.get("host")
        uuid = body.get("uuid")
        if not video_id and not uuid:
            respond_json(self, 400, {"error": "Missing video_id or uuid"})
            return
        if action in DISLIKE_ACTIONS:
            profile_id = self._require_profile()
            if profile_id is None:
                return
        else:
            # Optional for a like: without a key the event is still published, but nothing
            # is kept server-side, since there is no profile to keep it in.
            profile_id = resolve_profile(self.server.user_db, self.headers.get("X-Profile-Key"))

        try:
            seed = resolve_video_seed(
                self.server.engine_ingest_base,
                str(video_id) if video_id is not None else None,
                str(host) if host is not None else None,
                str(uuid) if uuid is not None else None,
            )
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine resolve failed: {exc}"})
            return

        if not seed:
            respond_json(self, 404, {"error": "Video not found in Engine"})
            return

        canonical_video_id = str(seed.get("video_id") or "")
        canonical_host = str(seed.get("instance_domain") or "")
        canonical_uuid = str(seed.get("video_uuid") or "")
        if not canonical_video_id or not canonical_host:
            respond_json(self, 502, {"error": "Engine resolve returned incomplete identity"})
            return

        video = {
            "video_id": canonical_video_id,
            "video_uuid": canonical_uuid,
            "instance_domain": canonical_host,
        }
        publish = action in ("like", "undo_like")
        if profile_id is not None:
            try:
                like_removed = self._store_reaction(profile_id, action, video)
            except DislikeLimitReached:
                respond_json(self, 400, {"error": f"Dislike limit reached ({MAX_DISLIKES})"})
                return
            except EngineApiError as exc:
                respond_json(self, 502, {"error": f"Engine centroids failed: {exc}"})
                return
            # A dislike is private and publishes nothing, except to withdraw a like it replaced.
            publish = publish or like_removed
        if not publish:
            respond_json(self, 200, {"ok": True, "updatedAt": now_ms()})
            return

        event_type = "Like" if action == "like" else "UndoLike"
        event_payload = {
            "event_id": f"client-{uuid4()}",
            "event_type": event_type,
            "actor_id": profile_id or "anonymous",
            "object": {
                "video_uuid": canonical_uuid,
                "instance_domain": canonical_host,
                "canonical_url": seed.get("video_url"),
            },
            "published_at": now_ms(),
            "source_instance": canonical_host,
            "raw_payload": body,
        }
        bridge_result = _publish_event(
            self.server.publish_mode,
            self.server.engine_ingest_base,
            event_payload,
        )
        status = 200 if bridge_result.get("ok") else 502
        respond_json(
            self,
            status,
            {
                "ok": bridge_result.get("ok", False),
                "bridge_ok": bridge_result.get("ok", False),
                "bridge_error": bridge_result.get("error"),
                "updatedAt": now_ms(),
            },
        )

    def _store_reaction(self, profile_id: str, action: str, video: dict[str, str]) -> bool:
        """Apply one action to the profile's likes and dislikes, which exclude each other.

        The Engine is asked for the new centroids before anything is written, so a failed
        request leaves the profile as it was.

        :returns: Whether a dislike removed a like.
        :raises DislikeLimitReached: A new dislike on a profile at `MAX_DISLIKES`.
        :raises EngineApiError: The centroids could not be computed.
        """
        conn = self.server.user_db
        key = (video["video_id"], video["instance_domain"])
        if action == "undo_like" or (action == "like" and not is_disliked(conn, profile_id, *key)):
            with conn:
                if action == "like":
                    record_like(conn, profile_id, "like", video, MAX_LIKES)
                else:
                    remove_like(conn, profile_id, *key)
            return False
        # The dislike set without this video; a re-dislike is therefore never over the cap.
        entries = [e for e in dislike_entries(conn, profile_id)
                   if (e["video_id"], e["instance_domain"]) != key]
        # rat-tail: read, compute and write are not serialised per profile; two concurrent
        # dislikes by one visitor can leave the centroids one dislike stale until the next.
        if action == "dislike":
            if len(entries) >= MAX_DISLIKES:
                raise DislikeLimitReached
            entries.append({"video_id": key[0], "instance_domain": key[1]})
            centroids = compute_dislike_centroids(self.server.engine_ingest_base, entries)
            with conn:
                like_removed = remove_like(conn, profile_id, *key)
                write_dislike(conn, profile_id, video, centroids)
            return like_removed
        # undo_dislike, or a like replacing a dislike.
        centroids = compute_dislike_centroids(self.server.engine_ingest_base, entries) if entries else None
        with conn:
            delete_dislike(conn, profile_id, *key, centroids)
            if action == "like":
                record_like(conn, profile_id, "like", video, MAX_LIKES)
        return False

    def _handle_likes_import(self) -> None:
        """Record a browser's local likes in the presented profile.

        Nothing is published: each like was published when the browser made it. A video the
        profile dislikes is skipped, since a like and a dislike exclude each other.
        """
        profile_id = self._require_profile()
        if profile_id is None:
            return
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        try:
            resolved = resolve_videos_by_uuid_host(self.server.engine_ingest_base, likes)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine resolve failed: {exc}"})
            return
        conn = self.server.user_db
        imported = 0
        with conn:
            for video in resolved:
                if is_disliked(conn, profile_id, video["video_id"], video["instance_domain"]):
                    continue
                record_like(conn, profile_id, "like", video, MAX_LIKES)
                imported += 1
        respond_json(self, 200, {"imported": imported})

    def _handle_reaction_get(self, params: dict[str, list[str]]) -> None:
        """Answer whether the presented profile likes and dislikes one video."""
        profile_id = self._require_profile()
        if profile_id is None:
            return
        uuid = (params.get("uuid") or [""])[0]
        host = (params.get("host") or [""])[0]
        for value in (uuid, host):
            if not value.strip() or len(value) > BLOCK_REFERENCE_MAX_LENGTH:
                respond_json(self, 400, {"error": "uuid and host must be non-empty strings"})
                return
        respond_json(self, 200, video_reaction(self.server.user_db, profile_id, uuid.strip(), host.strip()))

    def _read_block_body(self) -> dict[str, Any] | None:
        """Return the JSON body with a valid `kind`, or answer 400 and return None."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return None
        if body.get("kind") not in BLOCK_KINDS:
            respond_json(self, 400, {"error": "kind must be channel or account"})
            return None
        return body

    def _handle_block_add(self) -> None:
        """Block the channel or the account of a video named by uuid and host.

        The target is read from the Engine's own record of the video, so the browser never
        supplies a channel id or an account URL.
        """
        profile_id = self._require_profile()
        if profile_id is None:
            return
        body = self._read_block_body()
        if body is None:
            return
        uuid = body.get("uuid")
        host = body.get("host")
        for value in (uuid, host):
            if not isinstance(value, str) or not value.strip() or len(value) > BLOCK_REFERENCE_MAX_LENGTH:
                respond_json(self, 400, {"error": "uuid and host must be non-empty strings"})
                return
        try:
            seed = resolve_video_seed(self.server.engine_ingest_base, None, host.strip(), uuid.strip())
            rows = fetch_metadata_for_entries(
                self.server.engine_ingest_base,
                [{"video_id": seed["video_id"], "instance_domain": seed["instance_domain"]}],
            ) if seed else []
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine lookup failed: {exc}"})
            return
        target = block_target(body["kind"], rows[0]) if rows else None
        if target is None:
            respond_json(self, 404, {"error": "Video not found in Engine"})
            return
        try:
            add_block(self.server.user_db, profile_id, target)
        except BlockLimitReached:
            respond_json(self, 400, {"error": f"Block limit reached ({MAX_BLOCKS})"})
            return
        respond_json(self, 201, {"block": target})

    def _handle_block_remove(self) -> None:
        """Remove one block, named by the key fields `GET /api/profile/blocks` returns."""
        profile_id = self._require_profile()
        if profile_id is None:
            return
        body = self._read_block_body()
        if body is None:
            return
        remove_block(self.server.user_db, profile_id, body)
        respond_bytes(self, 204, b"")

    def _handle_user_profile_reset(self) -> None:
        """Clear the likes of the profile proved by `X-Profile-Key`."""
        user_id = self._require_profile()
        if user_id is None:
            return
        try:
            read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            clear_likes(self.server.user_db, user_id)
        respond_json(
            self,
            200,
            {"user_id": user_id, "likes": [], "updatedAt": now_ms()},
        )

    def _handle_user_profile_likes_get(self, params: dict[str, list[str]]) -> None:
        """Return the likes of the profile proved by `X-Profile-Key`, with Engine metadata."""
        user_id = self._require_profile()
        if user_id is None:
            return
        limit = _parse_int(params.get("limit", [None])[0])
        limit = min(limit, MAX_LIKES) if limit > 0 else MAX_LIKES
        with self.server.user_db:
            get_or_create_user(self.server.user_db, user_id)
            likes = fetch_recent_likes(self.server.user_db, user_id, limit)
        try:
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine metadata failed: {exc}"})
            return
        respond_json(self, 200, {"user_id": user_id, "likes": rows, "updatedAt": now_ms()})

    def _handle_user_profile_likes_from_client(self) -> None:
        """Handle handle user profile likes from client."""
        try:
            body = read_json_body(self)
        except ValueError as exc:
            respond_json(self, 400, {"error": str(exc)})
            return
        likes = _parse_client_likes(body, MAX_CLIENT_LIKES)
        if not likes:
            respond_json(self, 200, {"likes": [], "updatedAt": now_ms()})
            return
        try:
            resolved = resolve_videos_by_uuid_host(self.server.engine_ingest_base, likes)
            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, resolved)
        except EngineApiError as exc:
            respond_json(self, 502, {"error": f"Engine metadata failed: {exc}"})
            return
        respond_json(self, 200, {"likes": rows, "updatedAt": now_ms()})


def _publish_to_engine_bridge(engine_ingest_base: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Handle publish to engine bridge."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{engine_ingest_base}/internal/events/ingest",
        data=data,
        method="POST",
        headers=bridge_headers(),
    )
    try:
        with urlopen(request, timeout=6) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return {"ok": bool(parsed.get("ok", True)), "response": parsed}
    except HTTPError as exc:
        return {"ok": False, "error": f"engine bridge HTTP {exc.code}"}
    except (URLError, TimeoutError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def _publish_event(
    publish_mode: str, engine_ingest_base: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Handle publish event."""
    if _resolve_mode(publish_mode) != "bridge":
        return {
            "ok": False,
            "error": "CLIENT_PUBLISH_MODE=activitypub is not implemented yet",
            "mode": _resolve_mode(publish_mode),
        }
    return _publish_to_engine_bridge(engine_ingest_base, payload)


def _filter_payload(payload: bytes, row_filter: RowFilter, page_size: int | None) -> bytes | None:
    """Return the Engine's JSON page without blocked or disliked rows, cut to `page_size`.

    :returns: The re-encoded page, or None when the payload is not a page of row objects.
    """
    try:
        page = json.loads(payload)
    except ValueError:
        return None
    rows = page.get("rows") if isinstance(page, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    block_keys, disliked = row_filter
    rows = filter_disliked(filter_blocked(rows, block_keys), disliked)
    if page_size is not None:
        rows = rows[:page_size]
    page["rows"] = rows
    if "count" in page:
        page["count"] = len(rows)
    return json.dumps(page).encode("utf-8")


def _parse_int(value: str | None) -> int:
    """Handle parse int."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_client_likes(payload: dict[str, Any], max_items: int) -> list[dict[str, str]]:
    """Handle parse client likes."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw[: max_items if max_items > 0 else None]:
        if not isinstance(entry, dict):
            continue
        uuid = entry.get("uuid")
        host = entry.get("host")
        if not isinstance(uuid, str) or not uuid.strip():
            continue
        if not isinstance(host, str) or not host.strip():
            continue
        likes.append({"video_uuid": uuid.strip(), "instance_domain": host.strip()})
    return likes


def _summarize_proxy_likes(
    raw_likes: Any, max_items: int = 6
) -> tuple[int, list[str], int]:
    """Return compact like list and omitted count for client service logs."""
    if not isinstance(raw_likes, list):
        return 0, [], 0
    parts: list[str] = []
    total = 0
    for entry in raw_likes:
        if not isinstance(entry, dict):
            continue
        uuid = str(entry.get("uuid") or "").strip()
        host = str(entry.get("host") or "").strip()
        if not uuid or not host:
            continue
        total += 1
        if len(parts) < max_items:
            parts.append(f"{uuid}@{host}")
    omitted = total - len(parts)
    return total, parts, omitted


def main() -> None:
    """Handle main."""
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = str(uuid4())
    stop_reason = "unknown"

    def _signal_name(signum: int) -> str:
        """Return a stable signal name for lifecycle logging."""
        try:
            return signal.Signals(signum).name
        except ValueError:
            return str(signum)

    def _handle_shutdown_signal(signum: int, _frame: Any) -> None:
        """Translate SIGTERM/SIGINT into KeyboardInterrupt for graceful shutdown."""
        nonlocal stop_reason
        stop_reason = f"signal:{_signal_name(signum)}"
        raise KeyboardInterrupt

    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)

    users_db_path = (ROOT_DIR / DEFAULT_USERS_DB_PATH).resolve()
    users_db_path.parent.mkdir(parents=True, exist_ok=True)
    user_db = connect_db(users_db_path)
    ensure_user_schema(user_db)
    server = ClientBackendServer(
        (args.host, int(args.port)),
        ClientBackendHandler,
        user_db,
        args.engine_ingest_base,
        args.publish_mode,
        RateLimiter(RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS),
    )
    _emit_client_log(
        logging.INFO,
        "service.start",
        "client backend listening",
        {
            "host": args.host,
            "port": int(args.port),
            "engine_ingest_base": args.engine_ingest_base,
            "publish_mode": _resolve_mode(args.publish_mode),
            "run_id": run_id,
            "pid": os.getpid(),
        },
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if stop_reason == "unknown":
            stop_reason = "keyboard_interrupt"
        _emit_client_log(
            logging.INFO,
            "service.stop",
            "client backend shutting down",
            {
                "reason": stop_reason,
                "run_id": run_id,
                "pid": os.getpid(),
            },
        )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
        user_db.close()


if __name__ == "__main__":
    main()
