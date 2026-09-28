"""Similarity HTTP handler for Engine read surface.

Routes:
- /recommendations (POST): recommendation feed and debug payloads.
- /videos/{id}/similar (GET): id-based similar alias.
- /videos/similar (POST): extended similar route.
- /api/health: health check.
- /api/channels: channels listing.
- /api/video: single video metadata.
- /api/video/refresh: single video metadata refreshed from its instance.
- /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host).
- /internal/videos/metadata: internal Client metadata batch lookup.
- /internal/events/ingest: internal bridge ingest for normalized events.

Key steps:
- Parse seed/params, resolve likes (client JSON or users DB).
- Build candidate pools, score, mix, and return stable rows.
"""
import hashlib
import hmac
import logging
import json
import math
import sqlite3
from time import perf_counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np

from data.ann import search_index
from data.channels import fetch_channels
from data.db import is_interrupted_error, statement_deadline
from data.embeddings import fetch_embeddings_by_ids, normalize_vector, resolve_seed
from data.metadata import fetch_metadata
from data.random_videos import fetch_random_rows, fetch_random_rows_from_cache
from data.search import LEXICAL_SORTS, SearchIndexMissing, search_videos
from data.serving_moderation import apply_serving_moderation_filters
from data.similarity_candidates import UpnextPoolPolicy, get_upnext_candidates
from data.time import now_ms
from recommendations.debug import attach_debug_info
from recommendations.dislike_profile import MAX_CENTROIDS, apply_dislike_penalty
from recommendations.keys import like_key
from recommendations.profile import resolve_profile_config_with_guest
from recommendations.related_personalization import PERSONALIZED_SCORE_KEY, rerank_related_videos
from recommendations.scoring import score_and_rank_list
from server_config import (
    BRIDGE_TOKEN_HEADER,
    DEFAULT_CLIENT_EXCLUDE_MAX,
    DEFAULT_CLIENT_LIKES_BODY_LIMIT,
    DEFAULT_CLIENT_LIKES_MAX,
    DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    DISLIKE_SIMILARITY_FLOOR,
    ENGINE_BRIDGE_TOKEN,
    INCLUDE_DYNAMIC_STATS,
    MAX_LIKES,
    SEARCH_CANDIDATE_POOL,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_ENABLED,
    SEARCH_MAX_LIMIT,
    SEARCH_MAX_QUERY_TOKENS,
    SEARCH_MAX_TOKEN_LENGTH,
    SEARCH_RRF_K,
    SEARCH_WEIGHT_LEXICAL,
    SEARCH_WEIGHT_VECTOR,
    SIMILAR_VIDEO_MAX_NPROBE,
    SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
    SIMILAR_VIDEO_MIN_SCORE,
    SIMILAR_VIDEO_NPROBE,
    SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR,
    SIMILAR_VIDEO_SEARCH_LIMIT,
    SIMILAR_VIDEO_TAIL_MIN_SCORE,
    SIMILAR_VIDEO_TARGET_MIN_POOL,
    SIMILAR_VIDEO_TOP_K,
)
from http_utils import read_json_body, respond_json, respond_options, resolve_user_id
from request_context import (
    clear_request_context,
    fetch_recent_likes_request,
    fetch_request_dislike_centroids,
    fetch_request_excluded_keys,
    fetch_request_id,
    set_request_client_likes,
    set_request_dislike_centroids,
    set_request_excluded_keys,
    set_request_id,
)
from handlers.internal_events import handle_internal_events_ingest
from handlers.internal_client_reads import (
    handle_internal_dislike_centroids,
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)
from handlers.video import handle_video_refresh_request, handle_video_request


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}
# ValueError texts from seed resolution that describe the caller's vector; any other ValueError is a server fault.
SIMILAR_BAD_REQUEST_ERRORS = frozenset({
    "Invalid vector parameter",
    "Vector dimension does not match embeddings",
    "Vector norm is zero",
})
# The body of every 500 the similarity handler answers; the cause goes to the Engine log only.
SIMILAR_FAILED_MESSAGE = "Recommendations request failed"


STABLE_VIDEO_FIELDS = (
    "video_id",
    "video_uuid",
    "instance_domain",
    "channel_id",
    "account_url",
    "title",
    "thumbnail_url",
    "preview_path",
    "channel_avatar_url",
    "channel_name",
    "channel_display_name",
    "channel_url",
    "published_at",
    "duration",
    "video_url",
    "embed_path",
)

if INCLUDE_DYNAMIC_STATS:
    STABLE_VIDEO_FIELDS = STABLE_VIDEO_FIELDS + ("views", "likes", "dislikes")


def stable_video_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project a row to stable fields returned to clients."""
    return {field: row.get(field) for field in STABLE_VIDEO_FIELDS}


def stable_video_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a list of rows to stable response fields."""
    return [stable_video_row(row) for row in rows]


def maybe_attach_debug(
    stable_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    enabled: bool,
) -> list[dict[str, Any]]:
    """Attach debug info when enabled."""
    if not enabled:
        return stable_rows
    return attach_debug_info(stable_rows, source_rows)


def _parse_client_likes(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Validate client likes JSON to uuid/host pairs."""
    raw = payload.get("likes")
    if not isinstance(raw, list):
        return []
    likes: list[dict[str, str]] = []
    for entry in raw:
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


def _parse_excluded_keys(payload: dict[str, Any]) -> set[str]:
    """Return a request's `exclude` entries as `video_id::instance_domain` keys (the `like_key` form).

    Malformed entries are skipped, as malformed likes are.
    """
    raw = payload.get("exclude")
    if not isinstance(raw, list):
        return set()
    keys: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("id")
        host = entry.get("host")
        if isinstance(video_id, str) and video_id.strip() and isinstance(host, str) and host.strip():
            keys.add(f"{video_id.strip()}::{host.strip()}")
    return keys


def _parse_dislike_centroids(raw: Any, space: str | None, dim: int) -> np.ndarray | None:
    """Return a request's dislike centroids as unit rows, or None when they are unusable.

    Centroids are accepted only from the embedding space this Engine serves: vectors from
    another model share the dimension but not the meaning.
    """
    if not isinstance(raw, dict) or not space or dim <= 0 or raw.get("space") != space:
        return None
    vectors = raw.get("vectors")
    if not isinstance(vectors, list) or not 1 <= len(vectors) <= MAX_CENTROIDS:
        return None
    if not all(isinstance(v, list) and len(v) == dim for v in vectors):
        return None
    try:
        matrix = np.array(vectors, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if not np.all(np.isfinite(matrix)) or np.any(norms == 0):
        return None
    return matrix / norms


def _recommendations_likes_payload_error(
    path: str, payload: dict[str, Any], max_items: int
) -> dict[str, Any] | None:
    """Return API error payload for an invalid likes payload on any similar POST route."""
    if path not in SIMILAR_POST_ROUTES or max_items <= 0:
        return None
    raw_likes = payload.get("likes")
    if not isinstance(raw_likes, list):
        return None
    received = len(raw_likes)
    if received <= max_items:
        for index, entry in enumerate(raw_likes):
            if not isinstance(entry, dict):
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes entry must be an object",
                    "index": index,
                }
            uuid = entry.get("uuid")
            if not isinstance(uuid, str) or not uuid.strip():
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes.uuid must be a non-empty string",
                    "index": index,
                }
            host = entry.get("host")
            if not isinstance(host, str) or not host.strip():
                return {
                    "error": "Invalid likes payload",
                    "reason": "likes.host must be a non-empty string",
                    "index": index,
                }
        return None
    return {
        "error": "Too many likes in request body",
        "max_allowed": max_items,
        "received": received,
    }


def _resolve_client_likes(server: Any, likes: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Resolve client likes (uuid/host) to internal video_id rows."""
    if not likes:
        return []
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in likes:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)

    conditions = " OR ".join(["(video_uuid = ? AND instance_domain = ?)"] * len(unique))
    params: list[Any] = []
    for entry in unique:
        params.append(entry["video_uuid"])
        params.append(entry["instance_domain"])
    with server.db_lock:
        rows = server.db.execute(
            f"""
            SELECT video_id, video_uuid, instance_domain
            FROM videos
            WHERE {conditions}
            """,
            params,
        ).fetchall()
    lookup = {
        f"{row['video_uuid']}::{row['instance_domain']}": row["video_id"]
        for row in rows
    }
    resolved: list[dict[str, Any]] = []
    for entry in unique:
        key = f"{entry['video_uuid']}::{entry['instance_domain']}"
        video_id = lookup.get(key)
        if not video_id:
            continue
        resolved.append(
            {
                "video_id": str(video_id),
                "video_uuid": entry["video_uuid"],
                "instance_domain": entry["instance_domain"],
            }
        )
    return resolved


class SimilarHandler(BaseHTTPRequestHandler):
    """HTTP handler for Engine read endpoints and bridge ingest."""

    def _get_client_ip(self) -> str:
        """Resolve the client IP: the Client backend's `X-Client-IP`, else the TCP peer.

        `X-Client-IP` is the address the Client backend resolved for the original
        caller. It is trusted because the Engine binds loopback and the gateway is
        its only reachable peer; without it every proxied request looks like
        127.0.0.1 and shares one rate-limit bucket.

        `X-Forwarded-For` and `X-Real-IP` are not read: a direct caller chooses them, so keying on them let it pick its own rate-limit bucket.
        """
        client_ip = self.headers.get("X-Client-IP", "").strip()
        if client_ip:
            return client_ip
        if self.client_address:
            return self.client_address[0]
        return "unknown"

    def _get_full_url(self) -> str:
        """Build absolute URL from forwarded headers and request path."""
        host = self.headers.get("Host", "").strip()
        if not host:
            return self.path
        proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip() or "http"
        return f"{proto}://{host}{self.path}"

    def _log_access_start(self) -> None:
        """Emit request-start access line before request processing begins."""
        logging.info(
            "[access.start] ip=%s method=%s url=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
        )

    def log_message(self, format: str, *args: Any) -> None:
        """Emit structured access logs with real client IP and full URL."""
        status = args[1] if len(args) > 1 else "-"
        size = args[2] if len(args) > 2 else "-"
        logging.info(
            "[access] ip=%s method=%s url=%s status=%s bytes=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
            status,
            size,
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Answer OPTIONS 204 with no CORS headers."""
        self._log_access_start()
        respond_options(self)

    def _statement_deadline(self):
        """Guard this request thread's database work with the configured time budget."""
        return statement_deadline(
            getattr(
                self.server,
                "statement_timeout_seconds",
                DEFAULT_STATEMENT_TIMEOUT_SECONDS,
            )
        )

    def _respond_interrupted(self) -> None:
        """Report a request whose database work exceeded the time budget."""
        logging.warning(
            "[statement.timeout] ip=%s method=%s url=%s",
            self._get_client_ip(),
            self.command or "-",
            self._get_full_url(),
        )
        respond_json(self, 503, {"error": "Query time limit exceeded"})

    def do_POST(self) -> None:  # noqa: N802
        """Handle similarity and internal bridge ingest endpoints under the time budget."""
        try:
            with self._statement_deadline():
                self._dispatch_post()
        except sqlite3.OperationalError as exc:
            if not is_interrupted_error(exc):
                raise
            self._respond_interrupted()

    def _bridge_authorized(self) -> bool:
        """Check the shared secret on internal bridge routes.

        These routes write to the interaction event stream and read across the
        Client/Engine boundary, so an unset secret fails closed: accepting them
        unauthenticated is what let any browser rewrite the global ranking.
        """
        configured = getattr(self.server, "bridge_token", ENGINE_BRIDGE_TOKEN)
        if not configured:
            logging.error(
                "[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s", self.path
            )
            respond_json(
                self, 503, {"error": "Bridge token is not configured on the Engine"}
            )
            return False
        presented = self.headers.get(BRIDGE_TOKEN_HEADER, "").strip()
        if not presented or not hmac.compare_digest(presented, configured):
            logging.warning(
                "[bridge.auth] rejected %s from ip=%s", self.path, self._get_client_ip()
            )
            respond_json(self, 401, {"error": "Unauthorized"})
            return False
        return True

    def _dispatch_post(self) -> None:
        """Route a POST request to its endpoint handler."""
        self._log_access_start()
        url = urlparse(self.path)
        if url.path.startswith("/internal/") and not self._bridge_authorized():
            return
        if url.path in SIMILAR_POST_ROUTES:
            self._handle_similar_request(method="POST")
            return
        if url.path == "/internal/videos/resolve":
            handle_internal_video_resolve(self, self.server)
            return
        if url.path == "/internal/videos/metadata":
            handle_internal_videos_metadata(self, self.server)
            return
        if url.path == "/internal/dislikes/centroids":
            handle_internal_dislike_centroids(self, self.server)
            return
        if url.path == "/internal/events/ingest":
            if getattr(self.server, "engine_ingest_mode", "bridge") != "bridge":
                respond_json(
                    self,
                    501,
                    {
                        "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                        "mode": getattr(self.server, "engine_ingest_mode", "bridge"),
                    },
                )
                return
            handle_internal_events_ingest(self, self.server)
            return
        respond_json(self, 404, {"error": "Not found"})

    def do_GET(self) -> None:  # noqa: N802
        """Handle health, profile, and similarity endpoints under the time budget."""
        try:
            with self._statement_deadline():
                self._dispatch_get()
        except sqlite3.OperationalError as exc:
            if not is_interrupted_error(exc):
                raise
            self._respond_interrupted()

    def _dispatch_get(self) -> None:
        """Route a GET request to its endpoint handler."""
        self._log_access_start()
        url = urlparse(self.path)
        if url.path.startswith("/api/") and not self._rate_limit_check(url.path):
            respond_json(self, 429, {"error": "Rate limit exceeded"})
            return
        if url.path == "/api/health":
            payload = {
                "ok": True,
                "total": self.server.embeddings_count,
                "embeddingDim": self.server.embeddings_dim,
            }
            respond_json(self, 200, payload)
            return

        params = parse_qs(url.query)
        if url.path == "/api/channels":
            limit = _parse_int(params.get("limit", [None])[0])
            if limit <= 0:
                limit = 100
            limit = min(limit, 500)
            offset = _parse_int(params.get("offset", [None])[0])
            max_videos = _parse_non_negative_int(params.get("maxVideos", [None])[0])
            with self.server.db_lock:
                rows, total = fetch_channels(
                    self.server.db,
                    limit=limit,
                    offset=offset,
                    query=params.get("q", [""])[0] or "",
                    instance=params.get("instance", [""])[0] or "",
                    min_followers=_parse_int(params.get("minFollowers", [None])[0]),
                    min_videos=_parse_int(params.get("minVideos", [None])[0]),
                    max_videos=max_videos,
                    sort=params.get("sort", ["followers"])[0] or "followers",
                    direction=params.get("dir", ["desc"])[0] or "desc",
                )
            respond_json(
                self,
                200,
                {
                    "generatedAt": now_ms(),
                    "total": total,
                    "rows": rows,
                },
            )
            return

        if url.path == "/api/v1/search/videos":
            self._handle_search(params)
            return

        if url.path == "/api/video":
            handle_video_request(self, self.server, params)
            return

        if url.path == "/api/video/refresh":
            handle_video_refresh_request(self, self.server, params)
            return

        video_path_id = _extract_video_id_from_similar_path(url.path)
        if video_path_id is not None:
            if not self._rate_limit_check(url.path):
                respond_json(self, 429, {"error": "Rate limit exceeded"})
                return
            params.setdefault("id", [video_path_id])
            self._handle_similar(params)
            return

        respond_json(self, 404, {"error": "Not found"})

    def _handle_search(self, params: dict[str, list[str]]) -> None:
        """Answer a hybrid video search request.

        Runs inside the caller's statement deadline, like every other read route, so a
        pathological query cannot hold the shared database lock indefinitely.
        """
        if not SEARCH_ENABLED:
            respond_json(self, 503, {"error": "Search is disabled"})
            return

        raw_query = (params.get("q", [""])[0] or "").strip()
        if not raw_query:
            respond_json(self, 400, {"error": "Missing query parameter q"})
            return

        sort = params.get("sort", ["relevance"])[0] or "relevance"
        if sort not in LEXICAL_SORTS and sort != "relevance":
            respond_json(self, 400, {"error": "Unsupported sort"})
            return

        limit = _parse_int(params.get("limit", [None])[0])
        if limit <= 0:
            limit = SEARCH_DEFAULT_LIMIT
        limit = min(limit, SEARCH_MAX_LIMIT)
        page = _parse_int(params.get("page", [None])[0])
        if page <= 0:
            page = 1

        try:
            rows, total = search_videos(
                self.server,
                raw_query,
                page=page,
                limit=limit,
                sort=sort,
                max_tokens=SEARCH_MAX_QUERY_TOKENS,
                max_token_length=SEARCH_MAX_TOKEN_LENGTH,
                candidate_pool=SEARCH_CANDIDATE_POOL,
                rrf_k=SEARCH_RRF_K,
                lexical_weight=SEARCH_WEIGHT_LEXICAL,
                vector_weight=SEARCH_WEIGHT_VECTOR,
            )
        except SearchIndexMissing as exc:
            logging.warning("[search] index missing: %s", exc)
            respond_json(self, 503, {"error": "Search index is not built yet"})
            return
        filtered_rows, _stats = apply_serving_moderation_filters(
            self.server,
            rows,
            request_id=fetch_request_id(),
        )
        encoder = getattr(self.server, "query_encoder", None)
        respond_json(
            self,
            200,
            {
                "generatedAt": now_ms(),
                "total": total,
                "page": page,
                "limit": limit,
                "sort": sort,
                "vectorSearch": bool(encoder is not None and encoder.enabled),
                "rows": stable_video_rows(filtered_rows),
            },
        )

    def _rate_limit_check(self, path: str) -> bool:
        """Check per-IP rate limit for a path."""
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None:
            return True
        ip = self._get_client_ip()
        key = f"{ip}:{path}"
        return limiter.allow(key)

    def _handle_similar_request(self, method: str) -> None:
        """Parse client likes and dispatch to similarity handler."""
        url = urlparse(self.path)
        if not self._rate_limit_check(url.path):
            respond_json(self, 429, {"error": "Rate limit exceeded"})
            return
        params = parse_qs(url.query)
        client_likes: list[dict[str, Any]] = []
        use_client_likes = bool(getattr(self.server, "use_client_likes", False))
        if method == "POST":
            length = self.headers.get("content-length")
            size = int(length or "0")
            if size > DEFAULT_CLIENT_LIKES_BODY_LIMIT:
                respond_json(self, 400, {"error": "Invalid JSON body"})
                return
            try:
                body = read_json_body(self)
            except ValueError as exc:
                respond_json(self, 400, {"error": str(exc)})
                return
            if isinstance(body, dict):
                likes_payload_error = _recommendations_likes_payload_error(
                    url.path, body, DEFAULT_CLIENT_LIKES_MAX
                )
                if likes_payload_error is not None:
                    respond_json(self, 400, likes_payload_error)
                    return
                raw_exclude = body.get("exclude")
                if isinstance(raw_exclude, list) and len(raw_exclude) > DEFAULT_CLIENT_EXCLUDE_MAX:
                    respond_json(self, 400, {
                        "error": "Too many exclude entries in request body",
                        "max_allowed": DEFAULT_CLIENT_EXCLUDE_MAX,
                        "received": len(raw_exclude),
                    })
                    return
                incoming_payload = {
                    "likes": body.get("likes", []),
                    "user_id": body.get("user_id"),
                    "mode": body.get("mode"),
                }
                logging.info(
                    "[recommendations] incoming likes body=%s",
                    json.dumps(incoming_payload, ensure_ascii=True, separators=(",", ":")),
                )
            parsed = _parse_client_likes(body)
            client_likes = _resolve_client_likes(self.server, parsed)
            if isinstance(body, dict) and "dislike_centroids" in body:
                set_request_dislike_centroids(_parse_dislike_centroids(
                    body["dislike_centroids"],
                    getattr(self.server, "embeddings_model", None),
                    int(getattr(self.server, "embeddings_dim", 0) or 0),
                ))
        set_request_client_likes(client_likes, use_client_likes)
        set_request_excluded_keys(_parse_excluded_keys(body) if method == "POST" and isinstance(body, dict) else set())

        try:
            self._handle_similar(params)
        finally:
            clear_request_context()

    def _fetch_random_rows(self, limit: int) -> list[dict[str, Any]]:
        """Fetch random rows from cache or DB."""
        rows = fetch_random_rows_from_cache(
            self.server, limit, error_threshold=self.server.video_error_threshold
        )
        if rows:
            return rows
        with self.server.db_lock:
            return fetch_random_rows(
                self.server.db,
                limit,
                error_threshold=self.server.video_error_threshold,
            )

    def _respond_rows(
        self,
        rows: list[dict[str, Any]],
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        seed_payload: dict[str, Any],
    ) -> None:
        """Serialize rows and write HTTP response."""
        filtered_rows, _ = apply_serving_moderation_filters(
            self.server, rows, request_id=request_id
        )

        stable_rows = stable_video_rows(filtered_rows)
        stable_rows = maybe_attach_debug(stable_rows, filtered_rows, include_debug)
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        logging.info(
            "[similar-server][%s] done count=%d duration_ms=%d",
            request_id,
            len(stable_rows),
            duration_ms,
        )
        respond_json(
            self,
            200,
            {
                "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "total": self.server.embeddings_count,
                "count": len(stable_rows),
                "seed": seed_payload,
                "rows": stable_rows,
            },
        )

    def _handle_random(
        self,
        limit: int,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
    ) -> None:
        """Handle explicit random feed requests."""
        rows = self._fetch_random_rows(limit)
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload={"random": True},
        )

    def _handle_home(
        self,
        user_id: str,
        limit: int,
        refresh_cache: bool,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        mode: str,
    ) -> None:
        """Handle home feed recommendations."""
        rows = self.server.recommendation_strategy.generate_recommendations(
            self.server, user_id, limit, refresh_cache, mode=mode
        )
        if not rows:
            rows = self._fetch_random_rows(limit)
            self._respond_rows(
                rows,
                include_debug,
                request_id,
                started_at,
                seed_payload={"user_id": user_id, "random": True, "mode": mode},
            )
            return
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload={"user_id": user_id, "mode": mode},
        )

    def _handle_seed_with_embedding(
        self,
        seed: dict[str, Any],
        user_id: str,
        limit: int,
        refresh_cache: bool,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
        mode: str,
        draw_seed: int | None = None,
    ) -> None:
        """Handle similar videos when seed embedding is available."""
        recent_likes = fetch_recent_likes_request(user_id, MAX_LIKES)
        likes_available = bool(recent_likes)
        profile_name, profile_config = resolve_profile_config_with_guest(
            self.server.recommendation_strategy.config, mode, likes_available
        )
        logging.info(
            "[recommendations] profile=%s likes=%s",
            profile_name,
            "yes" if likes_available else "no",
        )
        settings = getattr(self.server.recommendation_strategy, "settings", None)
        similar_per_like = int(getattr(settings, "similar_per_like", 0) or 0)
        pool_policy = UpnextPoolPolicy(
            top_k=SIMILAR_VIDEO_TOP_K,
            target_min_pool=SIMILAR_VIDEO_TARGET_MIN_POOL,
            nprobe=SIMILAR_VIDEO_NPROBE,
            search_limit=SIMILAR_VIDEO_SEARCH_LIMIT,
            max_nprobe=SIMILAR_VIDEO_MAX_NPROBE,
            max_search_limit=SIMILAR_VIDEO_MAX_SEARCH_LIMIT,
            min_score=SIMILAR_VIDEO_MIN_SCORE,
            tail_min_score=SIMILAR_VIDEO_TAIL_MIN_SCORE,
            cache_limit=similar_per_like,
            refresh_cache=refresh_cache,
        )
        related_start = perf_counter()
        # Excluded rows leave the pool before it is counted, so the fallback fills past them and the ranked pool refills the page.
        rows, pool_stats = get_upnext_candidates(
            self.server, seed, pool_policy, fetch_request_excluded_keys(), request_id
        )
        related_ms = int((perf_counter() - related_start) * 1000)
        if rows:
            score_start = perf_counter()
            centroids = fetch_request_dislike_centroids()

            def penalise(candidates: list[dict[str, Any]], settings: Any) -> None:
                apply_dislike_penalty(
                    self.server,
                    candidates,
                    centroids,
                    settings.similarity_weight,
                    fetch_embeddings_by_ids,
                    DISLIKE_SIMILARITY_FLOOR,
                )

            rows = score_and_rank_list(
                rows, profile_config, layer_name=mode, now_ms_value=now_ms(), adjust=penalise
            )
            score_ms = int((perf_counter() - score_start) * 1000)
            for row in rows:
                row["debug_profile"] = profile_name
            logging.info(
                "[similar-server][%s] related_entries=%d limit=%d",
                request_id,
                len(rows),
                limit,
            )
            logging.info(
                "[similar-server][%s] timing related=%dms score=%dms total=%dms",
                request_id,
                related_ms,
                score_ms,
                related_ms + score_ms,
            )
            window = rows[: min(SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR * limit, len(rows))]
            likes_reranked = False
            if (
                self.server.related_personalization_enabled
                and self.server.related_personalization_deps is not None
            ):
                personalize_start = perf_counter()
                window = rerank_related_videos(
                    self.server,
                    user_id,
                    window,
                    self.server.related_personalization_deps,
                )
                # The rerank returns early, unstamped, when the request's likes resolved to nothing usable.
                likes_reranked = any(PERSONALIZED_SCORE_KEY in row for row in window)
                personalize_ms = int((perf_counter() - personalize_start) * 1000)
                logging.info(
                    "[similar-server][%s] timing personalize=%dms",
                    request_id,
                    personalize_ms,
                )
            rows = _draw_page(window, limit, draw_seed)
            _log_upnext_pool(request_id, pool_stats, draw_seed, len(window), likes_reranked, rows)
            seed_payload = dict(seed.get("meta") or {})
            seed_payload["mode"] = mode
            self._respond_rows(
                rows,
                include_debug,
                request_id,
                started_at,
                seed_payload=seed_payload,
            )
            return
        _log_upnext_pool(request_id, pool_stats, draw_seed, 0, False, [])
        respond_json(
            self,
            200,
            {
                "generatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "total": self.server.embeddings_count,
                "count": 0,
                "seed": seed.get("meta"),
                "rows": [],
            },
        )

    def _handle_vector_search(
        self,
        seed: dict[str, Any],
        limit: int,
        include_debug: bool,
        request_id: str,
        started_at: datetime,
    ) -> None:
        """Handle raw vector ANN search path."""
        if seed["vector"] is None:
            respond_json(
                self,
                400,
                {
                    "error": "Missing vector or video reference",
                    "hint": "Provide ?id=...&host=... or ensure a user profile exists",
                },
            )
            return
        vector = seed["vector"]
        if self.server.normalize_queries:
            vector = normalize_vector(vector)

        search_start = perf_counter()
        with self.server.index_lock:
            rowids, scores = search_index(
                self.server.index, vector, limit, seed["exclude_rowid"]
            )
        search_ms = int((perf_counter() - search_start) * 1000)

        meta_start = perf_counter()
        with self.server.db_lock:
            metadata = fetch_metadata(
                self.server.db,
                rowids,
                error_threshold=self.server.video_error_threshold,
            )
        meta_ms = int((perf_counter() - meta_start) * 1000)
        logging.info(
            "[similar-server][%s] timing ann=%dms meta=%dms total=%dms",
            request_id,
            search_ms,
            meta_ms,
            search_ms + meta_ms,
        )
        rows = []
        for rowid, score in zip(rowids, scores):
            meta = metadata.get(rowid)
            if not meta:
                continue
            rows.append({**meta, "score": score})
        self._respond_rows(
            rows,
            include_debug,
            request_id,
            started_at,
            seed_payload=seed["meta"],
        )

    def _handle_similar(self, params: dict[str, list[str]]) -> None:
        """Main similarity request handler (home, seed, vector, random)."""
        limit = _parse_int(params.get("limit", [str(self.server.default_limit)])[0])
        if limit == 0:
            limit = self.server.default_limit
        # Twice the page, so the Client can refill a page after removing a visitor's blocks.
        max_limit = self.server.default_limit * 2
        if self.server.default_limit > 0 and limit > max_limit:
            limit = max_limit
        vector_param = params.get("vector", [None])[0]
        id_param = params.get("id", params.get("video_id", [None]))[0]
        host_param = params.get("host", params.get("instance_domain", [None]))[0]
        uuid_param = params.get("uuid", params.get("video_uuid", [None]))[0]
        user_id = resolve_user_id(
            params.get("user_id", params.get("userId", [None]))[0]
        )
        random_param = params.get("random", [None])[0]
        refresh_cache = (
            _parse_bool(params.get("refresh_cache", [None])[0])
            or self.server.refresh_similarity_cache
        )
        debug_requested = _parse_bool(params.get("debug", [None])[0])
        debug_enabled = bool(getattr(self.server, "recommendations_debug_enabled", False))
        if debug_requested and not debug_enabled:
            respond_json(self, 403, {"error": "Debug mode is disabled"})
            return
        include_debug = debug_requested
        # An invalid seed is a random draw, not a 400.
        draw_seed = _parse_non_negative_int(params.get("seed", [None])[0])

        request_id = _make_request_id()
        started_at = datetime.now(timezone.utc)
        logging.info(
            "[similar-server][%s] start limit=%s id=%s host=%s uuid=%s",
            request_id,
            limit,
            id_param or "",
            host_param or "",
            uuid_param or "",
        )
        set_request_id(request_id)

        try:
            if random_param and random_param != "0":
                self._handle_random(limit, include_debug, request_id, started_at)
                return
            seed_start = perf_counter()
            with self.server.db_lock:
                seed = (
                    resolve_seed(
                        self.server.db,
                        self.server.embeddings_dim,
                        vector_param,
                        id_param,
                        host_param,
                        uuid_param,
                    )
                    if (vector_param or id_param or uuid_param)
                    else None
                )
            seed_ms = int((perf_counter() - seed_start) * 1000)
            logging.info(
                "[similar-server][%s] timing resolve_seed=%dms",
                request_id,
                seed_ms,
            )

            mode = "home" if seed is None else "upnext"

            if seed is None:
                self._handle_home(
                    user_id,
                    limit,
                    refresh_cache,
                    include_debug,
                    request_id,
                    started_at,
                    mode,
                )
                return

            if seed.get("meta") and seed.get("embedding") is not None:
                self._handle_seed_with_embedding(
                    seed,
                    user_id,
                    limit,
                    refresh_cache,
                    include_debug,
                    request_id,
                    started_at,
                    mode,
                    draw_seed,
                )
                return

            if seed.get("random"):
                rows = self._fetch_random_rows(limit)
                self._respond_rows(
                    rows,
                    include_debug,
                    request_id,
                    started_at,
                    seed_payload=seed["meta"],
                )
                return

            self._handle_vector_search(
                seed, limit, include_debug, request_id, started_at
            )
        except ValueError as exc:
            if str(exc) in SIMILAR_BAD_REQUEST_ERRORS:
                respond_json(self, 400, {"error": str(exc)})
            else:
                logging.exception("[similar-server][%s] request failed", request_id)
                respond_json(self, 500, {"error": SIMILAR_FAILED_MESSAGE})
        except Exception:
            logging.exception("server error")
            respond_json(self, 500, {"error": SIMILAR_FAILED_MESSAGE})
        finally:
            clear_request_context()


def _parse_int(value: str | None) -> int:
    """Parse a positive integer; return 0 on invalid input."""
    try:
        parsed = int(value or "0")
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _parse_bool(value: str | None) -> bool:
    """Parse boolean-like values from query params."""
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_non_negative_int(value: str | None) -> int | None:
    """Parse a non-negative integer; return None on invalid input."""
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _draw_weight(row: dict[str, Any]) -> float:
    """The final score a row is drawn and ordered by: the likes rerank stamp when present, else the ranked score."""
    value = row.get(PERSONALIZED_SCORE_KEY, row.get("score"))
    return float(value) if value is not None else 0.0


def _seeded_uniform(draw_seed: int, key: str) -> float:
    """A uniform in (0, 1] tied to the draw seed and the row, stable across processes (unlike str hash())."""
    digest = hashlib.blake2b(f"{draw_seed}:{key}".encode("utf-8"), digest_size=8).digest()
    return (int.from_bytes(digest, "big") + 1) / float(1 << 64)


def _draw_page(
    window: list[dict[str, Any]], limit: int, draw_seed: int | None
) -> list[dict[str, Any]]:
    """Draw `limit` rows from the ranked window by weighted sampling without replacement (Efraimidis-Spirakis).

    Each positive-weight row gets key log(u) / weight and the largest keys win; zero-weight rows fill only
    what positive ones cannot, in window order. The weight is `_draw_weight`, and the page is returned ordered by it.
    """
    if len(window) <= limit:
        return list(window)
    # Seeded u is tied to the row's like_key, not its position, so a seed keeps a row's draw when the pool around it shifts.
    rng = np.random.default_rng() if draw_seed is None else None
    keyed: list[tuple[float, int, dict[str, Any]]] = []
    unweighted: list[dict[str, Any]] = []
    for index, row in enumerate(window):
        weight = _draw_weight(row)
        if weight <= 0:
            unweighted.append(row)
            continue
        u = _seeded_uniform(draw_seed, like_key(row)) if rng is None else 1.0 - float(rng.random())
        keyed.append((math.log(u) / weight, index, row))
    keyed.sort(key=lambda item: (-item[0], item[1]))
    chosen = [row for _, _, row in keyed[:limit]]
    chosen.extend(unweighted[: limit - len(chosen)])
    return sorted(chosen, key=lambda row: -_draw_weight(row))


def _log_upnext_pool(
    request_id: str,
    stats: dict[str, Any],
    draw_seed: int | None,
    window_size: int,
    likes_reranked: bool,
    page: list[dict[str, Any]],
) -> None:
    """Log the one up-next pool line: initial pool, fallback steps and restored nprobe, final pool, sampling, rows returned."""
    steps = ",".join(f"{nprobe}/{search_limit}->{pool}" for nprobe, search_limit, pool in stats["steps"]) or "none"
    restored = stats["restored_nprobe"]
    logging.info(
        "[similar-server][%s] upnext_pool initial=%d steps=%s restored_nprobe=%s final=%d tail=%d sampling=%s window=%d likes_rerank=%s returned=%d",
        request_id,
        stats["initial"],
        steps,
        restored if restored is not None else "none",
        stats["final"],
        stats["tail"],
        "random" if draw_seed is None else "seeded",
        window_size,
        "yes" if likes_reranked else "no",
        len({like_key(row) for row in page}),
    )


def _make_request_id() -> str:
    """Generate a short request id for logs."""
    return hex(np.random.randint(0, 0xFFFFFF))[2:].zfill(6)


def _extract_video_id_from_similar_path(path: str) -> str | None:
    """Resolve /videos/{id}/similar route shape to seed video id."""
    if not path.startswith("/videos/") or not path.endswith("/similar"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "videos" or parts[2] != "similar":
        return None
    video_id = parts[1].strip()
    return video_id or None
