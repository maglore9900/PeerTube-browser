"""Hold the rule that accepts an incoming X-Request-ID for the Client."""
from __future__ import annotations

import re
import uuid

# rat-tail: REQUEST_ID_HEADER, REQUEST_ID_PATTERN and resolve_request_id mirror engine/server/api/request_context.py (no shared module: the boundary check keeps Client and Engine code apart), so editing only one copy lets them drift; a cross-service test compares both, and a shared package is the upgrade once a third consumer appears.
REQUEST_ID_HEADER = "X-Request-ID"
# Ids are for log correlation only: neither unique nor authenticated. nginx's $request_id (32 hex) fits, and no character here can break a log line.
REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{1,64}"
_REQUEST_ID_RE = re.compile(REQUEST_ID_PATTERN)


def resolve_request_id(header_value: str | None) -> str:
    """Return `header_value` when it fully matches REQUEST_ID_PATTERN, else a fresh uuid4 hex; a rejected value is never logged."""
    # fullmatch, not match with ^…$: `$` also matches before a trailing newline, so "abc\n" would pass.
    if header_value and _REQUEST_ID_RE.fullmatch(header_value):
        return header_value
    return uuid.uuid4().hex
