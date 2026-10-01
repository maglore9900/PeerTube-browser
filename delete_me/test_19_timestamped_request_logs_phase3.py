"""After `configure_client_logging()` with `LOG_FORMAT` unset, every Client record leaves the root handler as one JSON line in the Client's key order, with a UTC `ts`.

- In-process, the zone pinned off UTC, the handler's stream swapped for a StringIO: `_emit_client_log(ERROR, "engine.call", "Engine metadata failed", {"error": "x\\ny"})`, a `logging.exception` for `ValueError("sentinel-client-log")`, `logging.info("bare")`, and `_emit_client_log` with an empty and with no context write exactly five lines, each a JSON object.
- The `engine.call` line's keys are exactly `ts, level, service, event, message, context`, with level ERROR, service `client-backend`, the message and `{"error": "x\\ny"}` unchanged; the empty- and no-context lines stop at `message`.
- Every line's `ts` matches `TS_RE` and reads back as UTC inside the wall-clock window of the calls; the installed formatter renders a record whose `created` is 1741091696.789 as `2025-03-04T12:34:56.789Z` and 1741091696.9999996 as `2025-03-04T12:34:57.000Z`.
- The bare and the exception records have event `client.log` and their own message; the bare line's keys are exactly `ts, level, service, event, message`, the exception line adds `traceback`, the formatted `ValueError: sentinel-client-log` traceback.
"""
from __future__ import annotations

import io
import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import client_server  # noqa: E402

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
EMIT_KEYS = ["ts", "level", "service", "event", "message", "context"]
BARE_KEYS = ["ts", "level", "service", "event", "message"]


@contextmanager
def _client_logging(monkeypatch, value):
    """Run configure_client_logging under LOG_FORMAT=value; yield the stream it writes to."""
    # Saved and restored in the test body, so pytest's own capture handlers come back for later tests.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    if value is None:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
    else:
        monkeypatch.setenv("LOG_FORMAT", value)
    try:
        client_server.configure_client_logging()
        stream = io.StringIO()
        root.handlers[0].setStream(stream)
        yield stream
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _epoch(ts: str) -> float:
    """Read a `TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def _fixed_record(created: float) -> logging.LogRecord:
    """A bare record whose creation time is `created`."""
    record = logging.LogRecord("probe", logging.INFO, "probe", 1, "fixed", None, None)
    record.created = created
    return record


def test_client_records_leave_as_json_lines_in_client_key_order_with_utc_ts_and_bare_ones_as_client_log(monkeypatch):
    monkeypatch.setenv("TZ", OFF_UTC_ZONE)
    time.tzset()
    try:
        with _client_logging(monkeypatch, None) as stream:
            before = time.time()
            client_server._emit_client_log(logging.ERROR, "engine.call", "Engine metadata failed", {"error": "x\ny"})
            try:
                raise ValueError("sentinel-client-log")
            except ValueError:
                logging.exception("client probe failed")
            logging.info("bare")
            client_server._emit_client_log(logging.INFO, "probe.empty", "empty context", {})
            client_server._emit_client_log(logging.INFO, "probe.none", "no context")
            after = time.time()
            handler = logging.getLogger().handlers[0]
            fixed = json.loads(handler.format(_fixed_record(1741091696.789)))
            rounded = json.loads(handler.format(_fixed_record(1741091696.9999996)))
    finally:
        monkeypatch.undo()
        time.tzset()

    # Today the exception record's traceback and the bare text add or replace lines; one record is one line.
    lines = stream.getvalue().splitlines()
    assert len(lines) == 5, lines  # C1 C2
    payloads = [json.loads(line) for line in lines]
    assert all(isinstance(payload, dict) for payload in payloads), lines  # C1 C2
    emitted, failed, bare, empty, none = payloads

    assert list(emitted) == EMIT_KEYS, emitted  # C1
    assert (emitted["level"], emitted["service"], emitted["event"], emitted["message"], emitted["context"]) == ("ERROR", "client-backend", "engine.call", "Engine metadata failed", {"error": "x\ny"}), emitted  # C1
    # An empty or missing context is omitted, not written as {} or null.
    assert (list(empty), empty["event"], empty["message"]) == (BARE_KEYS, "probe.empty", "empty context"), empty  # C1
    assert (list(none), none["event"], none["message"]) == (BARE_KEYS, "probe.none", "no context"), none  # C1

    stamps = [payload["ts"] for payload in payloads]
    # Today's ts is local time with an offset (observed `2026-10-02T04:17:22.827+05:45`), which TS_RE refuses.
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C1
    # A local-time rendering with a `Z` reads back 5h45m outside the window; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)  # C1
    # The record's `created` in UTC, not the formatting time; milliseconds truncated without rounding to the microsecond first give 56.999.
    assert (fixed["ts"], rounded["ts"]) == ("2025-03-04T12:34:56.789Z", "2025-03-04T12:34:57.000Z"), (fixed, rounded)  # C1

    assert list(bare) == BARE_KEYS, bare  # C2
    assert (bare["level"], bare["service"], bare["event"], bare["message"]) == ("INFO", "client-backend", "client.log", "bare"), bare  # C2
    assert list(failed) == BARE_KEYS + ["traceback"], failed  # C1
    assert (failed["level"], failed["service"], failed["event"], failed["message"]) == ("ERROR", "client-backend", "client.log", "client probe failed"), failed  # C2
    assert failed["traceback"].startswith("Traceback (most recent call last):") and failed["traceback"].endswith("ValueError: sentinel-client-log"), failed["traceback"]  # C1
