"""The session record: one JSONL file per session under the project's `.un/sessions/` (ADR-0019), appended and never rewritten.

JSONL, so a killed process leaves a file valid up to its last complete line. Rows are messages (bare, so `restore` filters on `"role"`), usage rows and namespaced events (system prompt, tool calls, failures). The tool-result user message is not written; `restore` rebuilds it from the tool events. Every row is stamped with a sidecar `un_at` and redacted in `_write` alone. Other plugins reach this through `session:*` services, so disabling it makes them report the capability missing.
"""

from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None

from un import RecordUnavailable, Session, hook, service, session_file, tool
from un.core import redact

USAGE_KEY = "un_usage"
EVENT_KEY = "un_event"
AT_KEY = "un_at"

# Whether this record's system row is settled, in `Session.state`.
STAMPED_KEY = "transcript.stamped"

# rat-tail: a constant (about 8k tokens); `log_debug` lifts it. Promote to a Session field if needed.
RESULT_CAP = 32768

# Serialises this process's threads; `_locked` covers other processes (and `fcntl` is absent on Windows).
_WRITING = threading.Lock()


@contextmanager
def _locked(fh):
    """Hold an exclusive cross-process lock on `fh`. Appends under a lock keep every writer's row."""
    if fcntl is None:
        yield
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _rows(path: Path):
    """Every parseable JSON object row, in order; a torn last line is skipped."""
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def _now() -> str:
    """Local time with its offset, matching the local session id."""
    return datetime.now().astimezone().isoformat()


def _write(fh, row: dict) -> None:
    """One row, stamped and redacted. The only place either happens."""
    fh.write(json.dumps(redact({AT_KEY: _now(), **row}), ensure_ascii=False) + "\n")


def _stamped(session: Session, path: Path) -> bool:
    """Whether the system row is settled: already written, or the record already holds messages (a resume). Read from disk once, then memoised."""
    if STAMPED_KEY in session.state:
        return session.state[STAMPED_KEY]
    settled = any("role" in row
                  or (isinstance(event := row.get(EVENT_KEY), dict)
                      and event.get("kind") == "system")
                  for row in _rows(path))
    session.state[STAMPED_KEY] = settled
    return settled


@contextmanager
def _writer(session: Session):
    """The session file, open for append and locked, with the system row written first if due.

    Due only once SessionStart has composed the prompt (`context_injected`), so the recorded prompt is the one actually used. Written even when empty.
    """
    path = session_file(session.root, session.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh, _locked(fh):
        # Checked under the lock, so two writers cannot both write it.
        if session.context_injected and not _stamped(session, path):
            _write(fh, {EVENT_KEY: {"kind": "system", "text": session.system}})
            session.state[STAMPED_KEY] = True
            fh.flush()
        yield fh


def _emit(session: Session, rows: list[dict]) -> bool:
    """Write `rows`; on failure report it and return False rather than raise (`check` already proved the file writable).

    Serialised: rows arrive from several worker threads, and a large row can tear across writes, which `_rows` would silently drop.

    rat-tail: one process-wide lock rather than one per path.
    """
    try:
        with _WRITING, _writer(session) as fh:
            for row in rows:
                _write(fh, row)
    except OSError as exc:
        session.report("transcript", f"could not write the session record: {exc}")
        return False
    return True


@service("session:event")
def event(session: Session, kind: str, **fields) -> None:
    """Append one namespaced event row. Never reports its own failure, since `Session.report` writes through here."""
    try:
        # No deadlock with `_emit`, which releases the lock before reporting.
        with _WRITING, _writer(session) as fh:
            _write(fh, {EVENT_KEY: {"kind": kind, **fields}})
    except OSError:
        # The one deliberate swallow; narrow, so bugs still raise.
        pass


@hook("SessionStart")
def check(*, session: Session) -> None:
    """Raise `RecordUnavailable` if the record cannot be opened for append, before anything is recorded.

    Opened rather than touched: `touch` succeeds on a read-only file its owner owns.
    """
    path = session_file(session.root, session.id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.open("a").close()
    except OSError as exc:
        raise RecordUnavailable(
            f"cannot write the session record at {path.parent}: {exc.strerror}"
        ) from exc


@hook("Turn")
def append(*, session: Session, reply) -> None:
    """Write messages added since `session.transcript_cursor`, plus a usage row."""
    written = session.transcript_cursor
    rows = [message for message in session.messages[written:]
            if not _is_tool_results(message)]
    if reply is not None:
        # Stamped with the model and profile name, so a subagent's record can be priced later.
        # rat-tail: older rows lack these and are skipped by readers.
        rows.append({USAGE_KEY: {**(reply.usage or {}), "model": session.model,
                                 "provider": session.provider}})
    # The cursor advances only on success, so a failed turn is retried with the next.
    if _emit(session, rows):
        session.transcript_cursor = len(session.messages)


@hook("ToolEnd")
def record(*, session: Session, call: dict) -> None:
    """Write one row per resolved tool call immediately, so a killed process keeps each outcome (A6).

    rat-tail: no cursor, so a failed write loses this row.
    """
    _emit(session, [{EVENT_KEY: _bound(call, session.log_debug)}])


def _bound(call: dict, full: bool) -> dict:
    """The call with its result cut to `RESULT_CAP`, adding `result_length` only when cut. A headless DENY has no `result`."""
    result = call.get("result")
    if full or not isinstance(result, str) or len(result) <= RESULT_CAP:
        return call
    return {**call, "result": result[:RESULT_CAP], "result_length": len(result)}


def _is_tool_results(message: dict) -> bool:
    """Whether `message` consists only of tool_result blocks."""
    content = message.get("content")
    return (isinstance(content, list) and bool(content)
            and all(isinstance(block, dict) and block.get("type") == "tool_result"
                    for block in content))


@service("session:restore")
def restore(session: Session) -> None:
    """Rebuild `messages` from the record and set the cursor to match."""
    messages: list[dict] = []
    pending: list[dict] = []
    for row in _rows(session_file(session.root, session.id)):
        if "role" in row:
            # Answer the previous assistant turn's calls before this message.
            _close(messages, pending)
            pending = []
            messages.append({k: v for k, v in row.items() if k != AT_KEY})
        elif isinstance(event := row.get(EVENT_KEY), dict) and event.get("kind") == "tool":
            pending.append(event)
    _close(messages, pending)

    session.messages = messages
    # Includes rebuilt tool-result messages, which are never written.
    session.transcript_cursor = len(messages)


def _close(messages: list[dict], pending: list[dict]) -> None:
    """Answer every tool_use in the last assistant message, since providers refuse unanswered ones."""
    if not messages:
        return
    calls = [block["id"] for block in messages[-1].get("content", [])
             if isinstance(block, dict) and block.get("type") == "tool_use"]
    if not calls:
        return
    events = {event["id"]: event for event in pending if "id" in event}
    messages.append({"role": "user",
                     "content": [_answer(call_id, events.get(call_id))
                                 for call_id in calls]})


def _answer(call_id: str, event: dict | None) -> dict:
    """One tool_result, replayed from `event`, or an error saying no outcome was recorded. An empty-string result is a real outcome."""
    text = (event or {}).get("result")
    if text is None:
        return {"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                "content": "un exited before this tool returned; its outcome was "
                           "never recorded. Re-run it if you still need the result."}
    if (total := event.get("result_length")) is not None:
        text += f"\n\n[truncated: {len(text)} of {total} characters recorded]"
    return {"type": "tool_result", "tool_use_id": call_id,
            "content": text, "is_error": bool(event.get("error"))}


def _usage_of(path: Path) -> list[dict]:
    """The usage rows in one record, oldest first."""
    return [row[USAGE_KEY] for row in _rows(path) if USAGE_KEY in row]


@service("session:usage")
def usage(cwd: Path, session_id: str, forks: bool = False) -> list[dict]:
    """Every usage row, oldest first; with `forks`, then each subagent record (`<id>-*.jsonl`) in id order.

    A missing main record raises; an unreadable fork record is skipped.
    """
    rows = _usage_of(session_file(cwd, session_id))
    if not forks:
        return rows
    for path in sorted(session_file(cwd, session_id).parent.glob(f"{session_id}-*.jsonl")):
        try:
            rows.extend(_usage_of(path))
        except OSError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Reading the record back
# ---------------------------------------------------------------------------

# A top-level session id (`new_id`'s shape); fork records carry an extra suffix and do not match. Not `SLUG`, which rejects the `T`.
RECORD_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{4}")

# Characters per `SessionRead`.
READ_LIMIT = 24000


@service("session:records")
def records(cwd: Path) -> list[str]:
    """Every readable session id, oldest first, excluding fork records."""
    folder = session_file(cwd, "_").parent
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.jsonl")
                  if RECORD_ID.fullmatch(path.stem))


@service("session:rows")
def rows(cwd: Path, session_id: str) -> list[dict]:
    """Every parseable row of one record, or []. Uses `_rows`, so indices match `restore` and `usage`.

    rat-tail: reads the whole file.
    """
    path = session_file(cwd, session_id)
    return list(_rows(path)) if path.is_file() else []


@tool(
    "SessionRead",
    "Read rows of a session record by index, oldest first. A row is the raw log line: a "
    "message, a tool call with the verdict that let it through, or a usage record. "
    "`start` and `end` are a half-open range, so 0 and 10 are the first ten rows.",
    {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        },
        "required": ["session_id", "start", "end"],
    },
)
def session_read(*, session: Session, session_id: str, start: int, end: int) -> str:
    """Rows `start` to `end`, each prefixed with its index, within `READ_LIMIT`. An out-of-range request is refused, not clamped; failures return text."""
    known = records(session.root)
    if session_id not in known:
        return (f"no session record named {session_id!r}; readable: "
                f"{', '.join(known) or 'none'}")
    record = rows(session.root, session_id)
    if not 0 <= start < end <= len(record):
        return (f"rows {start}-{end} are outside {session_id}, which has {len(record)}; "
                f"ask for a half-open range within 0-{len(record)}")

    kept: list[str] = []
    spent = 0
    for index in range(start, end):
        line = f"{index}: {json.dumps(record[index], ensure_ascii=False)}"
        spent += len(line) + 1
        if spent > READ_LIMIT:
            break
        kept.append(line)
    if not kept:
        # Said explicitly, or it would read as an empty record.
        return (f"row {start} of {session_id} alone exceeds the {READ_LIMIT}-character "
                f"bound for one read, so nothing was returned")
    if len(kept) < end - start:
        return "\n".join(kept) + (
            f"\n\n[{len(kept)} of {end - start} rows returned; the rest would exceed the "
            f"{READ_LIMIT}-character bound. Read from {start + len(kept)} next.]")
    return "\n".join(kept)
