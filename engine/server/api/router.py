"""Route Engine HTTP requests to their handlers.

SimilarHandler hands every GET and POST here, inside its statement deadline. A route is one entry in GET_ROUTES or POST_ROUTES keyed by exact path (query string ignored, no trailing-slash match) whose value takes (handler, server); a path in neither table, or sent with the other method, answers 404 {"error": "Not found"}.

Routes:
- POST /recommendations: recommendation feed and debug payloads; own per-IP rate-limit check.
- POST /videos/similar: extended similar route; own per-IP rate-limit check.
- GET /videos/{id}/similar: id-based similar alias; the one pattern route, tried after an exact miss, with its own per-IP rate-limit check.
- GET /api/health: health check. [rate-limit gate]
- GET /api/channels: channels listing. [rate-limit gate]
- GET /api/v1/search/videos: hybrid text search (q) or exact-tag search (tag). [rate-limit gate]
- GET /api/video: single video metadata. [rate-limit gate]
- GET /api/video/refresh: single video metadata refreshed from its instance. [rate-limit gate]
- POST /internal/videos/resolve: internal Client read lookup by video_id/uuid(+host). [bridge gate]
- POST /internal/videos/metadata: internal Client metadata batch lookup. [bridge gate]
- POST /internal/channels/resolve: internal Client confirmation of one channel by its exact (instance_domain, channel_id), for following a channel named by its key. [bridge gate]
- POST /internal/dislikes/centroids: internal Client clustering of a visitor's disliked videos into taste centroids; nothing stored. [bridge gate]
- POST /internal/translate: internal Client read of a video's English translate state and whether a translate worker is serving; cues from a stored job, or from its own instance (cached). [bridge gate]
- POST /internal/translate/enqueue: internal Client request to queue a video's whisper translate job while a translate worker is serving. [bridge gate]
- POST /internal/translate/cancel: internal Client request to shorten a video's translate viewer lease to the cancel grace. [bridge gate]
- POST /internal/events/ingest: internal bridge ingest for normalized events; 501 outside ENGINE_INGEST_MODE=bridge. [bridge gate]

Gates:
- bridge gate: every POST /internal/* path, unknown ones included, needs the shared X-Bridge-Token first: 503 when the Engine has none configured, 401 when it is missing or wrong.
- rate-limit gate: every GET /api/* path, unknown ones included, passes the per-IP limiter first: 429.
- GET /internal/* has no gate and answers 404.
"""
import hmac
import logging
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from data.channels import fetch_channels
from data.time import now_ms
from http_utils import parse_int, parse_non_negative_int, respond_json
from server_config import BRIDGE_TOKEN_HEADER, ENGINE_BRIDGE_TOKEN
from handlers.internal_events import handle_internal_events_ingest
from handlers.internal_client_reads import (
    handle_internal_channel_resolve,
    handle_internal_dislike_centroids,
    handle_internal_video_resolve,
    handle_internal_videos_metadata,
)
from handlers.internal_translate import handle_internal_translate, handle_internal_translate_cancel, handle_internal_translate_enqueue
from handlers.video import handle_video_refresh_request, handle_video_request


SIMILAR_POST_ROUTES = {"/recommendations", "/videos/similar"}


def handle_health(handler: Any, server: Any) -> None:
    """Answer the health check with the loaded embedding count and dimension."""
    payload = {
        "ok": True,
        "total": server.embeddings_count,
        "embeddingDim": server.embeddings_dim,
    }
    respond_json(handler, 200, payload)


def handle_channels(handler: Any, server: Any) -> None:
    """Answer a page of the channels listing."""
    params = parse_qs(urlparse(handler.path).query)
    limit = parse_int(params.get("limit", [None])[0])
    if limit <= 0:
        limit = 100
    limit = min(limit, 500)
    offset = parse_int(params.get("offset", [None])[0])
    max_videos = parse_non_negative_int(params.get("maxVideos", [None])[0])
    with server.db_lock:
        rows, total = fetch_channels(
            server.db,
            limit=limit,
            offset=offset,
            query=params.get("q", [""])[0] or "",
            instance=params.get("instance", [""])[0] or "",
            min_followers=parse_int(params.get("minFollowers", [None])[0]),
            min_videos=parse_int(params.get("minVideos", [None])[0]),
            max_videos=max_videos,
            sort=params.get("sort", ["followers"])[0] or "followers",
            direction=params.get("dir", ["desc"])[0] or "desc",
        )
    respond_json(
        handler,
        200,
        {
            "generatedAt": now_ms(),
            "total": total,
            "rows": rows,
        },
    )


def _similar_post(handler: Any, server: Any) -> None:
    """Serve a recommendations or extended-similar POST through the handler's similarity path."""
    handler._handle_similar_request(method="POST")


def _search(handler: Any, server: Any) -> None:
    """Serve a video search with the request's query parameters."""
    handler._handle_search(parse_qs(urlparse(handler.path).query))


def _video(handler: Any, server: Any) -> None:
    """Serve single video metadata with the request's query parameters."""
    handle_video_request(handler, server, parse_qs(urlparse(handler.path).query))


def _video_refresh(handler: Any, server: Any) -> None:
    """Serve refreshed single video metadata with the request's query parameters."""
    handle_video_refresh_request(handler, server, parse_qs(urlparse(handler.path).query))


def _events_ingest(handler: Any, server: Any) -> None:
    """Serve bridge ingest, answering 501 when the Engine is not in bridge ingest mode."""
    mode = getattr(server, "engine_ingest_mode", "bridge")
    if mode != "bridge":
        respond_json(
            handler,
            501,
            {
                "error": "Bridge ingest is disabled in current ENGINE_INGEST_MODE",
                "mode": mode,
            },
        )
        return
    handle_internal_events_ingest(handler, server)


# Exact path -> callable(handler, server); read per request, so a test may add or replace an entry at run time.
GET_ROUTES: dict[str, Callable[[Any, Any], Any]] = {
    "/api/health": handle_health,
    "/api/channels": handle_channels,
    "/api/v1/search/videos": _search,
    "/api/video": _video,
    "/api/video/refresh": _video_refresh,
}

POST_ROUTES: dict[str, Callable[[Any, Any], Any]] = {
    **dict.fromkeys(SIMILAR_POST_ROUTES, _similar_post),
    "/internal/videos/resolve": handle_internal_video_resolve,
    "/internal/videos/metadata": handle_internal_videos_metadata,
    "/internal/channels/resolve": handle_internal_channel_resolve,
    "/internal/dislikes/centroids": handle_internal_dislike_centroids,
    "/internal/translate": handle_internal_translate,
    "/internal/translate/enqueue": handle_internal_translate_enqueue,
    "/internal/translate/cancel": handle_internal_translate_cancel,
    "/internal/events/ingest": _events_ingest,
}


def _extract_video_id_from_similar_path(path: str) -> str | None:
    """Resolve /videos/{id}/similar route shape to seed video id."""
    if not path.startswith("/videos/") or not path.endswith("/similar"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "videos" or parts[2] != "similar":
        return None
    video_id = parts[1].strip()
    return video_id or None


def bridge_authorized(handler: Any) -> bool:
    """Check the shared secret on internal bridge routes.

    These routes write to the interaction event stream and read across the
    Client/Engine boundary, so an unset secret fails closed: accepting them
    unauthenticated is what let any browser rewrite the global ranking.
    """
    configured = getattr(handler.server, "bridge_token", ENGINE_BRIDGE_TOKEN)
    if not configured:
        logging.error(
            "[bridge.auth] ENGINE_BRIDGE_TOKEN is not set; rejecting %s", handler.path
        )
        respond_json(
            handler, 503, {"error": "Bridge token is not configured on the Engine"}
        )
        return False
    presented = handler.headers.get(BRIDGE_TOKEN_HEADER, "").strip()
    if not presented or not hmac.compare_digest(presented, configured):
        logging.warning(
            "[bridge.auth] rejected %s from ip=%s", handler.path, handler._get_client_ip()
        )
        respond_json(handler, 401, {"error": "Unauthorized"})
        return False
    return True


def route_post(handler: Any) -> None:
    """Route a POST through the /internal/ bridge gate to its POST_ROUTES entry, or 404."""
    url = urlparse(handler.path)
    if url.path.startswith("/internal/") and not bridge_authorized(handler):
        return
    route = POST_ROUTES.get(url.path)
    if route is not None:
        route(handler, handler.server)
        return
    respond_json(handler, 404, {"error": "Not found"})


def route_get(handler: Any) -> None:
    """Route a GET through the /api/ rate-limit gate to its GET_ROUTES entry, the /videos/{id}/similar pattern, or 404."""
    url = urlparse(handler.path)
    if url.path.startswith("/api/") and not handler._rate_limit_check(url.path):
        respond_json(handler, 429, {"error": "Rate limit exceeded"})
        return
    route = GET_ROUTES.get(url.path)
    if route is not None:
        route(handler, handler.server)
        return
    # rat-tail: one hard-coded pattern route; an ordered list of (matcher, callable) pairs tried after the exact lookup once a second parameterised path appears.
    video_path_id = _extract_video_id_from_similar_path(url.path)
    if video_path_id is not None:
        if not handler._rate_limit_check(url.path):
            respond_json(handler, 429, {"error": "Rate limit exceeded"})
            return
        params = parse_qs(url.query)
        params.setdefault("id", [video_path_id])
        handler._handle_similar(params)
        return
    respond_json(handler, 404, {"error": "Not found"})
