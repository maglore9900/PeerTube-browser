"""HTTP client helpers for Client -> Engine read/bridge contracts."""
from __future__ import annotations

import json
import math
import os
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .request_context import REQUEST_ID_HEADER

BRIDGE_TOKEN_HEADER = "X-Bridge-Token"
# Holds the id of the request the current handler thread is serving; set and cleared only by ClientBackendHandler._run_request. It lives here, not in server.py, because every Engine call reads it and lib cannot import server.
REQUEST_CONTEXT = threading.local()
# The Engine's translate route spends at most a 15 s fetch budget plus one 4 s socket timeout; scripts/deploy-bluegreen.sh's 30 s drain must stay above this.
TRANSLATE_TIMEOUT_SECONDS = 20
# The 404 body the Engine answers for an unknown or denylisted video (VIDEO_NOT_FOUND in engine/server/api/handlers/internal_translate.py); any other 404, such as an Engine without the route, is a failure.
TRANSLATE_NOT_FOUND_ERROR = "Video not found"
TRANSLATE_STATES = frozenset(("none", "queued", "running", "ready", "already_english", "failed"))
# busy is the enqueue route's full-queue answer and is never stored; the cancel route answers TRANSLATE_STATES.
TRANSLATE_REQUEST_STATES = TRANSLATE_STATES | {"busy"}


class EngineApiError(RuntimeError):
    """Engine API request failed."""


def request_id_headers() -> dict[str, str]:
    """Return the `X-Request-ID` header carrying the serving request's id, so the Engine logs this call under it; empty outside a request."""
    request_id = getattr(REQUEST_CONTEXT, "request_id", None)
    return {REQUEST_ID_HEADER: request_id} if request_id else {}


def bridge_headers() -> dict[str, str]:
    """Return request headers for an Engine `/internal/*` bridge call.

    The Engine rejects these routes without the shared secret, so every bridge call
    site must go through here rather than building its own header dict.

    :returns: Content type, the bridge token when one is configured, and the request id when the call is made while serving a request.
    """
    headers = {"content-type": "application/json"}
    token = os.environ.get("ENGINE_BRIDGE_TOKEN", "").strip()
    if token:
        headers[BRIDGE_TOKEN_HEADER] = token
    headers.update(request_id_headers())
    return headers


def _post_json(url: str, payload: dict[str, Any], timeout: int = 6) -> tuple[int, dict[str, Any]]:
    """Handle post json."""
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
        headers=bridge_headers(),
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return status, parsed
            return status, {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        parsed: dict[str, Any] = {}
        if body:
            try:
                maybe = json.loads(body)
                if isinstance(maybe, dict):
                    parsed = maybe
            except json.JSONDecodeError:
                parsed = {}
        return int(exc.code), parsed
    except (URLError, TimeoutError) as exc:
        raise EngineApiError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise EngineApiError(str(exc)) from exc


def resolve_video_seed(
    engine_base_url: str,
    video_id: str | None,
    host: str | None,
    uuid: str | None,
) -> dict[str, Any] | None:
    """Resolve canonical video identity in Engine by id/uuid + host."""
    payload: dict[str, Any] = {}
    if video_id:
        payload["video_id"] = video_id
    if host:
        payload["host"] = host
    if uuid:
        payload["uuid"] = uuid
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/videos/resolve", payload)
    if status == 404:
        return None
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine resolve failed (HTTP {status}): {message or 'unknown error'}")
    video = body.get("video") if isinstance(body, dict) else None
    if not isinstance(video, dict):
        raise EngineApiError("Engine resolve returned invalid payload")
    return video


def resolve_channel(engine_base_url: str, instance_domain: str, channel_id: str) -> dict[str, Any] | None:
    """Return the Engine's own record of one channel by its exact key, or None when the catalogue does not hold it."""
    status, body = _post_json(
        f"{engine_base_url.rstrip('/')}/internal/channels/resolve",
        {"instance_domain": instance_domain, "channel_id": channel_id},
    )
    if status == 404:
        return None
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine channel resolve failed (HTTP {status}): {message or 'unknown error'}")
    channel = body.get("channel") if isinstance(body, dict) else None
    if not isinstance(channel, dict):
        raise EngineApiError("Engine channel resolve returned invalid payload")
    return channel


def fetch_metadata_for_entries(
    engine_base_url: str,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch metadata rows from Engine for {video_id|video_uuid, instance_domain} entries, one row per video in first-entry order."""
    if not entries:
        return []
    status, body = _post_json(
        f"{engine_base_url.rstrip('/')}/internal/videos/metadata",
        {"entries": entries},
    )
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine metadata failed (HTTP {status}): {message or 'unknown error'}")
    rows = body.get("rows") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise EngineApiError("Engine metadata returned invalid payload")
    return [row for row in rows if isinstance(row, dict)]


def compute_dislike_centroids(
    engine_base_url: str,
    entries: list[dict[str, str]],
) -> dict[str, Any] | None:
    """Ask the Engine for the taste centroids of a set of disliked videos.

    :returns: ``{"space", "vectors"}``, or None when none of the videos has an embedding.
    """
    status, body = _post_json(
        f"{engine_base_url.rstrip('/')}/internal/dislikes/centroids",
        {"entries": entries},
    )
    if status != 200:
        message = body.get("error") if isinstance(body, dict) else None
        raise EngineApiError(f"Engine centroids failed (HTTP {status}): {message or 'unknown error'}")
    centroids = body.get("centroids")
    space = body.get("space")
    if not isinstance(centroids, list) or not isinstance(space, str):
        raise EngineApiError("Engine centroids returned invalid payload")
    if not centroids:
        return None
    return {"space": space, "vectors": centroids}


def _is_seconds(value: Any) -> bool:
    """Whether value is a finite JSON number (never a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _translate_available(body: dict[str, Any]) -> bool:
    """The answer's available flag; an Engine from before plan 50 sends none, read as False so it keeps plan 48's behaviour; any non-bool raises."""
    available = body.get("available", False)
    if not isinstance(available, bool):
        raise EngineApiError("Engine translate returned invalid payload")
    return available


def _checked_cues(cues: Any) -> list[dict[str, Any]]:
    """Copy start, end and text of each cue in the Engine's order, so nothing else the Engine adds reaches the browser; a non-list or any malformed cue raises."""
    if not isinstance(cues, list):
        raise EngineApiError("Engine translate returned invalid payload")
    checked: list[dict[str, Any]] = []
    for cue in cues:
        if not isinstance(cue, dict) or not _is_seconds(cue.get("start")) or not _is_seconds(cue.get("end")) or not isinstance(cue.get("text"), str):
            raise EngineApiError("Engine translate returned invalid payload")
        checked.append({"start": cue["start"], "end": cue["end"], "text": cue["text"]})
    return checked


def fetch_translate(engine_base_url: str, video_id: str, host: str, after: int | None = None) -> dict[str, Any]:
    """Ask the Engine for a video's English translate state: one of TRANSLATE_STATES with available, cues for ready and running, total for running; after (a running cue count) is sent only when given. Anything else raises EngineApiError."""
    payload: dict[str, Any] = {"id": video_id, "host": host}
    if after is not None:
        payload["after"] = after
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate", payload, timeout=TRANSLATE_TIMEOUT_SECONDS)
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none", "available": False}
    if status != 200:
        raise EngineApiError(f"Engine translate failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    state = body.get("state")
    if state not in TRANSLATE_STATES:
        raise EngineApiError("Engine translate returned invalid payload")
    answer: dict[str, Any] = {"state": state, "available": _translate_available(body)}
    if state in ("ready", "running"):
        answer["cues"] = _checked_cues(body.get("cues"))
    if state == "running":
        total = body.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise EngineApiError("Engine translate returned invalid payload")
        answer["total"] = total
    return answer


def _post_translate(engine_base_url: str, route: str, operation: str, video_id: str, host: str, states: frozenset[str]) -> dict[str, Any]:
    """POST {id, host} to /internal/translate/<route>: {state, available} with state one of states and no cues; 404 Video not found is none, not available; anything else raises EngineApiError naming `Engine translate <operation>`."""
    status, body = _post_json(f"{engine_base_url.rstrip('/')}/internal/translate/{route}", {"id": video_id, "host": host})
    if status == 404 and body.get("error") == TRANSLATE_NOT_FOUND_ERROR:
        return {"state": "none", "available": False}
    if status != 200:
        raise EngineApiError(f"Engine translate {operation} failed (HTTP {status}): {body.get('error') or 'unknown error'}")
    state = body.get("state")
    if state not in states:
        raise EngineApiError(f"Engine translate {operation} returned invalid payload")
    return {"state": state, "available": _translate_available(body)}


def request_translate(engine_base_url: str, video_id: str, host: str) -> dict[str, Any]:
    """Ask the Engine to queue a whisper job: {state, available} with state one of TRANSLATE_REQUEST_STATES and no cues (an existing ready or running job is read through fetch_translate); anything else raises EngineApiError."""
    return _post_translate(engine_base_url, "enqueue", "request", video_id, host, TRANSLATE_REQUEST_STATES)


def cancel_translate(engine_base_url: str, video_id: str, host: str) -> dict[str, Any]:
    """Ask the Engine to shorten a video's translate viewer lease to its cancel grace: {state, available} with state one of TRANSLATE_STATES (never busy) and no cues; anything else raises EngineApiError."""
    return _post_translate(engine_base_url, "cancel", "cancel", video_id, host, TRANSLATE_STATES)

