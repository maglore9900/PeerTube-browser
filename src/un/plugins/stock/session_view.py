"""`view:transcript`: the session record rendered for reading (Ctrl-T in the REPL). Writes nothing.

Shows what the conversation view omits: the system prompt, thinking, hook fires, verdicts and usage. Output is (theme role, line) pairs, so `Surface` stays the only rich holder (ADR-0012). Fields are read with `.get`, and unknown kinds print their JSON rather than vanish.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from un import service

# The record format's keys, duplicated from `transcript.py` because importing it would register it.
AT_KEY, EVENT_KEY, USAGE_KEY = "un_at", "un_event", "un_usage"

# Body indent, and the column where a labelled field's value starts.
INDENT = "    "
LABEL = 8

# Theme roles: stanza head, labelled fields, machinery, failures.
HEAD, FIELDS, QUIET, BAD = "tool", "tool_result", "status", "error"

# Message role -> body theme role; unknown roles read as the assistant.
BODY = {"user": "user_text", "assistant": "assistant", "system": "status"}

# Usage counters shown per turn; missing ones show 0.
COUNTS = (("in", "input_tokens"), ("out", "output_tokens"),
          ("cache-w", "cache_creation_input_tokens"),
          ("cache-r", "cache_read_input_tokens"))

# (path, width) -> (bytes read, rendered lines). Module state because the caller is a key binding.
# rat-tail: never evicted; one process holds one session.
_CACHE: dict[tuple[str, int], tuple[int, list[tuple[str, str]]]] = {}


def _read(path: Path, offset: int) -> tuple[int, list[dict]]:
    """Rows appended since the byte `offset`, and the new offset. A trailing partial line (a write in flight) is left for next time; read errors return nothing."""
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return offset, []
    complete, newline, _in_flight = data.rpartition(b"\n")
    if not newline:
        return offset, []
    rows = []
    for line in complete.split(b"\n"):
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return offset + len(complete) + len(newline), rows


def _time(stamp: str) -> str:
    """HH:MM:SS from an ISO stamp, local when it has an offset, as written when naive; "" when absent."""
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        at = None
    if at is not None and at.tzinfo is not None:
        return at.astimezone().strftime("%H:%M:%S")
    return stamp[11:19] if len(stamp) >= 19 else ""


def _head(*parts) -> str:
    """A stanza's opening line: the parts that are present, two spaces apart."""
    return "  ".join(str(part) for part in parts if part not in (None, ""))


def _json(value) -> str:
    """`value` as text. A string is already text; anything else is rendered as JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _line(text: str, width: int, role: str) -> list[tuple[str, str]]:
    """One full-width line, WRAPPED rather than cut, so nothing is lost off the edge."""
    return [(role, piece) for piece in _wrap(text, width)]


def _wrap(text: str, room: int) -> list[str]:
    """`text` in pieces of at most `room` columns; hyphens do not break identifiers.

    rat-tail: keeps whitespace so code indentation survives, at the cost of a stray leading space on prose continuations.
    """
    return textwrap.wrap(text, max(1, room), break_long_words=True,
                         break_on_hyphens=False, drop_whitespace=False) or [""]


def _text(value, width: int, role: str) -> list[tuple[str, str]]:
    """A body block as indented rows, split on newlines before wrapping."""
    room = width - len(INDENT)
    return [(role, INDENT + piece)
            for line in str(value).split("\n")
            for piece in _wrap(line, room)]


def _field(name: str, value, width: int, role: str = FIELDS) -> list[tuple[str, str]]:
    """A `name  value` row, continuation lines aligned under the value."""
    label = INDENT + name.ljust(LABEL)
    pad = " " * len(label)
    room = width - len(label)
    out: list[tuple[str, str]] = []
    for line in str(value).split("\n"):
        for piece in _wrap(line, room):
            out.append((role, (label if not out else pad) + piece))
    return out


def _fields(at: str, kind: str, event: dict, width: int) -> list[tuple[str, str]]:
    """An unstyled event kind: its name, then its JSON."""
    rest = {key: value for key, value in event.items() if key != "kind"}
    return _line(_head(at, kind), width, HEAD) + _field("event", _json(rest), width)


def _tool(at: str, event: dict, width: int) -> list[tuple[str, str]]:
    """A tool call and its verdict. Fields are optional: a headless DENY has no `result` or `ms`."""
    ms = event.get("ms")
    out = _line(_head(at, "tool", event.get("name", "?"), event.get("decision", "?"),
                      f"{ms}ms" if ms is not None else ""), width, HEAD)
    for name in ("rule", "reason", "input", "result"):
        if (value := event.get(name)) not in (None, ""):
            out += _field(name, _json(value), width)
    if event.get("error"):
        out += _field("error", "the call failed", width)
    if (total := event.get("result_length")) is not None:
        # The record truncated the result; say so.
        out += _field("cut", f"{len(event.get('result') or '')} of {total} characters",
                      width)
    return out


def _event(at: str, event: dict, width: int) -> list[tuple[str, str]]:
    """One namespaced event row. Four kinds are styled; the rest print themselves."""
    kind = str(event.get("kind", "?"))
    if kind == "system":
        return (_line(_head(at, "system prompt"), width, HEAD)
                + _text(event.get("text", ""), width, QUIET))
    if kind == "hook":
        return _line(_head(at, "hook", event.get("event", "?"), event.get("name", "?"),
                           event.get("outcome", "?")), width, QUIET)
    if kind == "tool":
        return _tool(at, event, width)
    if kind == "error":
        return (_line(_head(at, "error", event.get("source", "?")), width, BAD)
                + _text(event.get("text", ""), width, BAD))
    return _fields(at, kind, event, width)


def _message(at: str, row: dict, width: int) -> list[tuple[str, str]]:
    """One message, as a stanza per content block."""
    role = str(row.get("role", "?"))
    body = BODY.get(role, "assistant")
    content = row.get("content")
    if not isinstance(content, list):
        return _line(_head(at, role), width, HEAD) + _text(content, width, body)
    out: list[tuple[str, str]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            out += (_line(_head(at, role, "text"), width, HEAD)
                    + _text(block.get("text", ""), width, body))
        elif kind == "thinking":
            out += (_line(_head(at, role, "thinking"), width, HEAD)
                    + _text(block.get("thinking", ""), width, QUIET))
        elif kind == "tool_use":
            out += _line(_head(at, role, "calls", block.get("name", "?")), width, HEAD)
            out += _field("input", _json(block.get("input")), width)
        else:
            out += _line(_head(at, role, kind or "block"), width, HEAD)
            out += _field("block", _json(block), width)
    return out or _line(_head(at, role, "(no content)"), width, HEAD)


def _usage(at: str, usage: dict, width: int) -> list[tuple[str, str]]:
    """One turn's token counts, on one line."""
    counts = " ".join(f"{label} {usage.get(key, 0)}" for label, key in COUNTS)
    return _line(_head(at, "usage", counts), width, QUIET)


def _stanza(row: dict, width: int) -> list[tuple[str, str]]:
    """One record row as rendered lines: a message, an event, usage, or raw JSON. Never empty."""
    at = _time(str(row.get(AT_KEY, "")))
    if "role" in row:
        return _message(at, row, width)
    if isinstance(event := row.get(EVENT_KEY), dict):
        return _event(at, event, width)
    if isinstance(usage := row.get(USAGE_KEY), dict):
        return _usage(at, usage, width)
    return _line(_head(at, "row"), width, HEAD) + _field("json", _json(row), width)


@service("view:transcript")
def transcript(path: Path, width: int) -> list[tuple[str, str]]:
    """The record at `path` as (theme role, line) pairs wrapped to `width`, rendering only rows new since the last call. Returns the cached list itself, not a copy."""
    width = max(1, int(width))
    key = (str(path), width)
    offset, lines = _CACHE.get(key, (0, []))
    offset, rows = _read(Path(path), offset)
    for row in rows:
        lines.append((FIELDS, ""))
        # Final cut to width: every line must occupy exactly one screen row.
        lines += [(role, line[:width]) for role, line in _stanza(row, width)]
    _CACHE[key] = (offset, lines)
    return lines
