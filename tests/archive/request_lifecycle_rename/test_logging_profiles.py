"""Retired from `tests/active/test_logging_profiles.py` in build 20-request-lifecycle-logs (plan 21), step 8.

All four conflict with that build's R9: the Engine's request lines are now `[request.start]` / `[request.end]` logged with a `structured_context` extra, with events `request.start` / `request.end`. The `[access.start]` and `[access]` rules are gone, so an `[access.start]` record now falls to `access.start.info`, verbose only, with its raw message, and the session Engine logs no `access.start` / `access` record at all.

- The ts test's control (old line 152) expects the `[access.start]` record of `_TS_CHILD` to render "request started".
- The issue-19 durable test slices the session Engine log from a marked `access.start` to a marked `access` and finds neither (`([], [])`).
- The two LOG_FORMAT tests pin `JSON_PAYLOADS[3]` and the text line to `access.start` / "request started"; the other four records still match exactly (observed at step 8).

Plan 21's Tests section drafted the R9 rewrites (request.start probes with a spaced user agent, the durable test paired by request_id); no phase wrote them. Issue 39 tracks the replacement. A step-8 probe against the session Engine observed the rewritten property holding: request.start, ten `recommendations.*` records and request.end under one 32-hex id, ts non-decreasing inside the request's window. Kept readable here; the `engine` fixture is not available from this directory, and the whole module is skipped.

The retired module docstring bullets read:

- In a child with `LOG_FORMAT` unset and the zone pinned off UTC, every stderr line is JSON whose `ts` matches `TS_RE` and reads back within a minute of the child's clock. For a `LogRecord` whose `created` is set after construction, `_format_ts` and `EngineJsonFormatter().format`'s `ts` both give `2025-03-04T12:34:56.789Z` for 1741091696.789 and `2025-03-04T12:34:57.000Z` for 1741091696.9999996; for a `created` one hour back both read back to that `created` within a millisecond, an hour before the formatting.
- The session Engine, sent `POST /recommendations?limit=5&user_id=log-order-<hex>`: in its log, from the one `access.start` whose url carries the marker to the one `access` that does, the `access.start`, the `access` and at least one `recommendations.*` record carry a `ts` matching `TS_RE`, within the request's wall-clock window, never decreasing.
- A child logs five records: `[probe] plain`, `[probe] two\\r\\nlines`, a `logging.exception("[probe] failed")` for `ValueError("sentinel-log-format")` with request_id `rid-p2`, an `[access.start]` record with request_id `rid-a` and a `[service] lifecycle` record. With `LOG_FORMAT` unset, `json`, `JSON`, `bogus` or empty, stderr is five JSON objects, each with a `ts` matching `TS_RE`, a traceback on the exception record ending `ValueError: sentinel-log-format`, and otherwise exactly the keys, order and values of `JSON_PAYLOADS`.
- With `text`, `TEXT`, ` Text ` or tab-`text`-newline, stderr is exactly five lines. None parses as a JSON object or starts with `<`. Each line is `<TS_RE> LEVEL event`, then the message if there is one, the context as `k=v`, `request_id=…` and the traceback, with CR and LF written as the two characters `\\r` and `\\n`. The exception line puts `request_id=rid-p2` before the traceback and ends `ValueError: sentinel-log-format`. The access.start line reads `request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a`, context before request_id. The lifecycle line has no message token.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

ROOT = Path(__file__).resolve().parents[3]
API_DIR = ROOT / "engine" / "server" / "api"
TRACEBACK_HEAD = "Traceback (most recent call last):"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
TEXT_HEAD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z (INFO|ERROR) ")
HOUR = 3600
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
LOG_WAIT_SECONDS = 5

# Logs three records through the production setup, then reports what `_format_ts` and the formatter give for records whose `created` comes from argv.
_TS_CHILD = textwrap.dedent(
    """
    import json, logging, sys, time
    from logging_profiles import EngineJsonFormatter, _format_ts, configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a")
    logging.error("[probe] failed without exception")
    cases = []
    for created in json.loads(sys.argv[1]):
        # msecs is taken from the clock at construction and not updated, so a ts built from it shows the wrong milliseconds.
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "[probe] fixed", None, None)
        record.created = created
        cases.append({"format_ts": _format_ts(record), "formatted": json.loads(EngineJsonFormatter().format(record))["ts"]})
    print(json.dumps({"now": time.time(), "cases": cases}))
    """
)

# Logs five records through the production setup; LOG_FORMAT comes only from the env the test gives the child.
_LOG_FORMAT_CHILD = textwrap.dedent(
    """
    import logging
    from logging_profiles import configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.info("[probe] two\\r\\nlines")
    try:
        raise ValueError("sentinel-log-format")
    except ValueError:
        logging.exception("[probe] failed", extra={"request_id": "rid-p2"})
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a", extra={"request_id": "rid-a"})
    logging.info("[service] lifecycle state=start component=engine run_id=r pid=1")
    """
)

# The JSON payloads of the five records, less `ts` and `traceback` (observed before LOG_FORMAT existed; the CR/LF message falls back to engine.log).
JSON_PAYLOADS = [
    {"level": "INFO", "event": "probe.info", "message": "[probe] plain", "modes": ["verbose"]},
    {"level": "INFO", "event": "engine.log", "message": "[probe] two\r\nlines", "modes": ["verbose"]},
    {"level": "ERROR", "event": "probe.info", "message": "[probe] failed", "modes": ["focused", "verbose"], "request_id": "rid-p2"},
    {"level": "INFO", "event": "access.start", "message": "request started", "modes": ["focused", "verbose"], "request_id": "rid-a", "context": {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a"}},
    {"level": "INFO", "event": "service.lifecycle", "modes": ["focused", "verbose"], "context": {"state": "start", "component": "engine", "run_id": "r", "pid": "1"}},
]

# The traceback's `\n` are the two characters backslash and n, not a line break.
EXCEPTION_TEXT_RE = re.compile(r'ERROR probe\.info \[probe\] failed request_id=rid-p2 Traceback \(most recent call last\):\\n  File "<string>", line \d+, in <module>\\n    raise ValueError\("sentinel-log-format"\)\\nValueError: sentinel-log-format')


def _epoch(ts: str) -> float:
    """Read a `TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _run_log_format_child(value: str | None) -> subprocess.CompletedProcess:
    """Run the five-record child with LOG_FORMAT removed from the env, then set to value when it is not None."""
    env = {key: item for key, item in os.environ.items() if key != "LOG_FORMAT"}
    if value is not None:
        env["LOG_FORMAT"] = value
    return subprocess.run([sys.executable, "-c", _LOG_FORMAT_CHILD], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)


def _json_object(line: str) -> dict | None:
    """The line parsed as a JSON object, or None."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def test_engine_ts_is_record_created_in_utc_with_milliseconds():
    env = {key: value for key, value in os.environ.items() if key != "LOG_FORMAT"}
    env["TZ"] = OFF_UTC_ZONE
    past = time.time() - HOUR
    run = subprocess.run([sys.executable, "-c", _TS_CHILD, json.dumps([1741091696.789, 1741091696.9999996, past])], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    report = json.loads(run.stdout)
    lines = [json.loads(line) for line in run.stderr.splitlines()]
    assert all(isinstance(line, dict) for line in lines), run.stderr[-2000:]
    # Control: the three records reached stderr through the production formatter, in order.
    assert [line["message"] for line in lines] == ["[probe] plain", "request started", "[probe] failed without exception"], lines

    assert all(TS_RE.fullmatch(line["ts"]) for line in lines), [line["ts"] for line in lines]
    # A local-time rendering reads back 5h45m off the child's clock here.
    assert all(abs(report["now"] - _epoch(line["ts"])) < 60 for line in lines), (report["now"], [line["ts"] for line in lines])

    fixed, rounded, hour_back = report["cases"]
    # The formatting time, or a `created` read through record.msecs (the clock at construction), gives another value.
    assert fixed == {"format_ts": "2025-03-04T12:34:56.789Z", "formatted": "2025-03-04T12:34:56.789Z"}, fixed
    # Milliseconds truncated from `created` without rounding to the microsecond first give 56.999.
    assert rounded == {"format_ts": "2025-03-04T12:34:57.000Z", "formatted": "2025-03-04T12:34:57.000Z"}, rounded
    assert all(TS_RE.fullmatch(hour_back[key]) for key in ("format_ts", "formatted")), hour_back
    assert all(abs(_epoch(hour_back[key]) - past) < 0.001 for key in ("format_ts", "formatted")), (hour_back, past)
    # Not the formatting time: the child formatted it an hour after the time it renders.
    assert all(report["now"] - _epoch(hour_back[key]) > HOUR - 60 for key in ("format_ts", "formatted")), (report["now"], hour_back)


def _request_records(log_path: Path, marker: str) -> tuple[list[int], list[int], list[dict]]:
    """Every JSON record of the log, with the indexes of the access.start and access records whose url carries the marker."""
    records = []
    for line in log_path.read_text(errors="replace").splitlines():
        payload = _json_object(line)
        if payload is not None:
            records.append(payload)
    marked = [marker in str((record.get("context") or {}).get("url", "")) for record in records]
    starts = [index for index, record in enumerate(records) if marked[index] and record.get("event") == "access.start"]
    ends = [index for index, record in enumerate(records) if marked[index] and record.get("event") == "access"]
    return starts, ends, records


def test_engine_request_ts_never_decreases_from_access_start_to_access(engine):
    marker = f"log-order-{uuid.uuid4().hex}"
    before = time.time()
    status, body = engine.request("POST", f"/recommendations?limit=5&user_id={marker}", body={})
    after = time.time()
    # Control: the route took user_id, so the marker is in the url of both access lines (observed: seed {"user_id": marker, "mode": "home"}).
    assert status == 200 and body["seed"].get("user_id") == marker, (status, body)
    deadline = time.time() + LOG_WAIT_SECONDS
    starts, ends, records = _request_records(engine.db_path, marker)
    while not ends and time.time() < deadline:
        time.sleep(0.1)
        starts, ends, records = _request_records(engine.db_path, marker)
    # Control: one request, started before it finished.
    assert len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0], (starts, ends)
    kept = [record for record in records[starts[0]:ends[0] + 1] if record["event"] in ("access.start", "access") or record["event"].startswith("recommendations.")]
    events = [record["event"] for record in kept]
    assert events[0] == "access.start" and events[-1] == "access", events
    assert any(event.startswith("recommendations.") for event in events[1:-1]), events

    stamps = [record["ts"] for record in kept]
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps
    # A constant or local-time ts falls outside the window the request ran in; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)
    assert [_epoch(ts) for ts in stamps] == sorted(_epoch(ts) for ts in stamps), list(zip(events, stamps))


@pytest.mark.parametrize("value", [None, "json", "JSON", "bogus", ""])
def test_engine_log_format_unset_empty_json_or_unknown_writes_json_lines(value):
    run = _run_log_format_child(value)
    assert run.returncode == 0, run.stderr[-2000:]
    lines = run.stderr.splitlines()
    payloads = [_json_object(line) for line in lines]
    assert len(lines) == 5 and all(payload is not None for payload in payloads), run.stderr[-2000:]

    assert all(TS_RE.fullmatch(payload.pop("ts")) for payload in payloads), run.stderr[-2000:]
    traceback = payloads[2].pop("traceback")
    assert traceback.startswith(TRACEBACK_HEAD) and traceback.endswith("ValueError: sentinel-log-format"), traceback
    # Key order included: the watcher and the runbooks read this payload.
    assert [list(payload.items()) for payload in payloads] == [list(payload.items()) for payload in JSON_PAYLOADS], payloads


@pytest.mark.parametrize("value", ["text", "TEXT", " Text ", "\ttext\n"])
def test_engine_log_format_text_writes_one_escaped_text_line_per_record(value):
    run = _run_log_format_child(value)
    assert run.returncode == 0, run.stderr[-2000:]
    # splitlines breaks on CR as well as LF, so an unescaped CR or LF adds a line here.
    lines = run.stderr.splitlines()
    assert len(lines) == 5, lines

    assert all(TEXT_HEAD_RE.match(line) for line in lines), lines
    assert all(_json_object(line) is None for line in lines), lines
    assert not any(line.startswith("<") for line in lines), lines

    stamps, rests = zip(*(line.split(" ", 1) for line in lines))
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps
    plain, multiline, failed, access_start, lifecycle = rests
    assert plain == "INFO probe.info [probe] plain", plain
    assert multiline == "INFO engine.log [probe] two\\r\\nlines", multiline
    # request_id follows the message and precedes the traceback, which ends the line.
    assert EXCEPTION_TEXT_RE.fullmatch(failed), failed
    # The context tokens precede request_id.
    assert access_start == "INFO access.start request started ip=127.0.0.1 method=GET url=http://x/a request_id=rid-a", access_start
    # service.lifecycle carries no message, so its context follows the event directly.
    assert lifecycle == "INFO service.lifecycle state=start component=engine run_id=r pid=1", lifecycle
