"""Provide request context runtime helpers."""

import re
import threading
import uuid
from typing import Any

_REQUEST_CONTEXT = threading.local()

REQUEST_ID_HEADER = "X-Request-ID"
# Ids are for log correlation only: neither unique nor authenticated. nginx's $request_id (32 hex) fits, and no character here can break a log line or the `[scope][id]` prefix.
REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"
_REQUEST_ID_RE = re.compile(REQUEST_ID_PATTERN)


def resolve_request_id(header_value: str | None) -> str:
    """Return `header_value` when it fully matches REQUEST_ID_PATTERN, else a fresh uuid4 hex; a rejected value is never logged."""
    # fullmatch, not match with ^…$: `$` also matches before a trailing newline, so "abc\n" would pass.
    if header_value and _REQUEST_ID_RE.fullmatch(header_value):
        return header_value
    return uuid.uuid4().hex


def set_request_client_likes(likes: list[dict[str, Any]] | None, use_client: bool) -> None:
    """Handle set request client likes."""
    _REQUEST_CONTEXT.client_likes = likes if use_client else []
    _REQUEST_CONTEXT.use_client_likes = bool(use_client)


def set_request_dislike_centroids(centroids: Any) -> None:
    """Store the request's validated dislike centroids, or None when it carried none."""
    _REQUEST_CONTEXT.dislike_centroids = centroids


def fetch_request_dislike_centroids() -> Any:
    """Return the request's dislike centroids, or None."""
    return getattr(_REQUEST_CONTEXT, "dislike_centroids", None)


def set_request_excluded_keys(keys: set[str]) -> None:
    """Store the `video_id::instance_domain` keys the request's feed must not return."""
    _REQUEST_CONTEXT.excluded_keys = keys


def fetch_request_excluded_keys() -> set[str]:
    """Return the request's excluded keys, or an empty set."""
    return getattr(_REQUEST_CONTEXT, "excluded_keys", None) or set()


def set_request_follows(follows: tuple[list[tuple[str, str]], list[str]] | None) -> None:
    """Store the request's followed channels and accounts, or None when it carried none."""
    _REQUEST_CONTEXT.follows = follows


def fetch_request_follows() -> tuple[list[tuple[str, str]], list[str]] | None:
    """Return the request's followed channels and accounts, or None."""
    return getattr(_REQUEST_CONTEXT, "follows", None)


def set_request_cursor(cursor: tuple[int, str, str] | None) -> None:
    """Store the request's decoded Following cursor, or None."""
    _REQUEST_CONTEXT.cursor = cursor


def fetch_request_cursor() -> tuple[int, str, str] | None:
    """Return the request's decoded Following cursor, or None."""
    return getattr(_REQUEST_CONTEXT, "cursor", None)


def set_request_include_nsfw(value: bool) -> None:
    """Store whether the request opted in to NSFW-flagged rows (nsfw=1)."""
    _REQUEST_CONTEXT.include_nsfw = bool(value)


def fetch_request_include_nsfw() -> bool:
    """Return whether the request includes NSFW-flagged rows; unset means filtered, so a path that never set it fails safe."""
    return bool(getattr(_REQUEST_CONTEXT, "include_nsfw", False))


def set_request_id(request_id: str | None) -> None:
    """Store request id in thread-local context for logging correlation."""
    value = (request_id or "").strip()
    if value:
        _REQUEST_CONTEXT.request_id = value
        return
    if hasattr(_REQUEST_CONTEXT, "request_id"):
        delattr(_REQUEST_CONTEXT, "request_id")


def fetch_request_id() -> str | None:
    """Return the current request id from thread-local context when set."""
    value = getattr(_REQUEST_CONTEXT, "request_id", None)
    if not isinstance(value, str) or not value:
        return None
    return value


def clear_request_context() -> None:
    """Clear request-scoped likes, centroids, excluded keys, follows, the Following cursor and the NSFW flag; the request id belongs to the handler's request wrapper, which clears it with `set_request_id(None)`."""
    for name in ("client_likes", "use_client_likes", "dislike_centroids", "excluded_keys", "follows", "cursor", "include_nsfw"):
        if hasattr(_REQUEST_CONTEXT, name):
            delattr(_REQUEST_CONTEXT, name)


def fetch_recent_likes_request(user_id: str, limit: int) -> list[dict[str, Any]]:
    """Return request-scoped likes only (no Engine users DB fallback)."""
    use_client = bool(getattr(_REQUEST_CONTEXT, "use_client_likes", False))
    if not use_client:
        return []
    likes = getattr(_REQUEST_CONTEXT, "client_likes", None) or []
    if limit <= 0:
        return list(likes)
    return list(likes)[:limit]
