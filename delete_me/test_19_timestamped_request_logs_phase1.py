"""The Engine's `ts` is the record's creation time in UTC `YYYY-MM-DDTHH:MM:SS.mmmZ`, and within one live request it never decreases.

- `configure_engine_logging("verbose")` in a child with `LOG_FORMAT` unset and the zone pinned off UTC: every stderr line is JSON whose `ts` matches `TS_RE` and reads back within a minute of the child's clock. For a `LogRecord` whose `created` is set after construction, `_format_ts` and `EngineJsonFormatter().format`'s `ts` both give `2025-03-04T12:34:56.789Z` for 1741091696.789 and `2025-03-04T12:34:57.000Z` for 1741091696.9999996; for a `created` one hour back both read back to that `created` within a millisecond, an hour before the formatting.
- The session Engine, sent `POST /recommendations?limit=5&user_id=log-order-<hex>`: in its log, from the one `access.start` whose url carries the marker to the one `access` that does, the `access.start`, the `access` and at least one `recommendations.*` record carry a `ts` matching `TS_RE`, within the request's wall-clock window, never decreasing.
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

ACTIVE = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ROOT, engine  # noqa: E402,F401

API_DIR = ROOT / "engine" / "server" / "api"
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
HOUR = 3600
# +05:45: a ts rendered in local time, with or without a `Z`, is off by hours and minutes here, whatever zone the host runs in.
OFF_UTC_ZONE = "Asia/Kathmandu"
LOG_WAIT_SECONDS = 5

# Logs three records through the production setup, then reports what `_format_ts` and the formatter give for records whose `created` comes from argv.
_ENGINE_CHILD = textwrap.dedent(
    """
    import json, logging, sys, time
    import logging_profiles
    from logging_profiles import EngineJsonFormatter, configure_engine_logging
    configure_engine_logging("verbose")
    logging.info("[probe] plain")
    logging.info("[access.start] ip=127.0.0.1 method=GET url=http://x/a")
    logging.error("[probe] failed without exception")
    # A missing helper prints null, so the formatter's own ts still reaches the test.
    format_ts = getattr(logging_profiles, "_format_ts", None)
    cases = []
    for created in json.loads(sys.argv[1]):
        # msecs is taken from the clock at construction and not updated, so a ts built from it shows the wrong milliseconds.
        record = logging.LogRecord("probe", logging.INFO, "probe", 1, "[probe] fixed", None, None)
        record.created = created
        cases.append({"format_ts": format_ts(record) if format_ts else None, "formatted": json.loads(EngineJsonFormatter().format(record))["ts"]})
    print(json.dumps({"now": time.time(), "cases": cases}))
    """
)


def _epoch(ts: str) -> float:
    """Read a `TS_RE` timestamp back as UTC epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def test_engine_ts_is_record_created_in_utc_with_milliseconds():
    env = {key: value for key, value in os.environ.items() if key != "LOG_FORMAT"}
    env["TZ"] = OFF_UTC_ZONE
    past = time.time() - HOUR
    run = subprocess.run([sys.executable, "-c", _ENGINE_CHILD, json.dumps([1741091696.789, 1741091696.9999996, past])], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    report = json.loads(run.stdout)
    lines = [json.loads(line) for line in run.stderr.splitlines()]
    assert all(isinstance(line, dict) for line in lines), run.stderr[-2000:]
    # Control: the three records reached stderr through the production formatter, in order.
    assert [line["message"] for line in lines] == ["[probe] plain", "request started", "[probe] failed without exception"], lines

    assert all(TS_RE.fullmatch(line["ts"]) for line in lines), [line["ts"] for line in lines]  # C1
    # A local-time rendering reads back 5h45m off the child's clock here.
    assert all(abs(report["now"] - _epoch(line["ts"])) < 60 for line in lines), (report["now"], [line["ts"] for line in lines])  # C1

    fixed, rounded, hour_back = report["cases"]
    # The formatting time, or a `created` read through record.msecs (the clock at construction), gives another value.
    assert fixed == {"format_ts": "2025-03-04T12:34:56.789Z", "formatted": "2025-03-04T12:34:56.789Z"}, fixed  # C1
    # Milliseconds truncated from `created` without rounding to the microsecond first give 56.999.
    assert rounded == {"format_ts": "2025-03-04T12:34:57.000Z", "formatted": "2025-03-04T12:34:57.000Z"}, rounded  # C1
    assert all(TS_RE.fullmatch(hour_back[key]) for key in ("format_ts", "formatted")), hour_back  # C1
    assert all(abs(_epoch(hour_back[key]) - past) < 0.001 for key in ("format_ts", "formatted")), (hour_back, past)  # C1
    # Not the formatting time: the child formatted it an hour after the time it renders.
    assert all(report["now"] - _epoch(hour_back[key]) > HOUR - 60 for key in ("format_ts", "formatted")), (report["now"], hour_back)  # C1


def _request_records(log_path: Path, marker: str) -> tuple[list[int], list[int], list[dict]]:
    """Every JSON record of the log, with the indexes of the access.start and access records whose url carries the marker."""
    records = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
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
    assert any(event.startswith("recommendations.") for event in events[1:-1]), events  # C2

    stamps = [record["ts"] for record in kept]
    assert all(TS_RE.fullmatch(ts) for ts in stamps), stamps  # C2
    # A constant or local-time ts falls outside the window the request ran in; one second covers the millisecond truncation.
    assert all(before - 1 <= _epoch(ts) <= after + 1 for ts in stamps), (before, after, stamps)  # C2
    assert [_epoch(ts) for ts in stamps] == sorted(_epoch(ts) for ts in stamps), list(zip(events, stamps))  # C2
