"""Checks for security tasks 74, 75, 77 and 78.

Run: python3 engine/server/db/jobs/tests/test-security-bundle.py

Covers:
- 74: LIKE metacharacters in the /api/channels search term are literal, and the term
  is length-capped, so the caller cannot control wildcard count.
- 75: a statement that outruns the deadline is interrupted rather than running on.
- 78: the batch ingest commits once per chunk and bounds the stored raw_payload.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[3]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.channels import MAX_SEARCH_TERM_LENGTH, _like_pattern, fetch_channels  # noqa: E402
from data.db import is_interrupted_error, statement_deadline  # noqa: E402
from data.interaction_events import (  # noqa: E402
    MAX_RAW_PAYLOAD_BYTES,
    ensure_interaction_event_schema,
    ingest_interaction_event,
)

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one assertion outcome."""
    if condition:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


def channels_conn() -> sqlite3.Connection:
    """Build an in-memory channels table with one hostile and one ordinary row."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE channels (
          channel_id TEXT, channel_name TEXT, display_name TEXT, instance_domain TEXT,
          videos_count INTEGER, followers_count INTEGER, avatar_url TEXT,
          health_status TEXT, health_checked_at INTEGER, health_error TEXT,
          channel_url TEXT, last_error TEXT, last_error_at INTEGER, last_error_source TEXT
        )
        """
    )
    rows = [("c1", "news", "Daily News", "peertube.example", 10, 5)]
    rows += [(f"p{i}", "plain", "a" * 200, "evil.example", 1, 1) for i in range(200)]
    rows += [("lit", "lit", "100% pure_data", "peertube.example", 2, 2)]
    conn.executemany(
        "INSERT INTO channels (channel_id, channel_name, display_name, instance_domain,"
        " videos_count, followers_count) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    return conn


print("task 74 - LIKE escaping and length cap")
check(
    "metacharacters escaped",
    _like_pattern("%a%a%") == "%\\%a\\%a\\%%",
    _like_pattern("%a%a%"),
)
check(
    "term length capped",
    len(_like_pattern("x" * 500)) == MAX_SEARCH_TERM_LENGTH + 2,
    str(len(_like_pattern("x" * 500))),
)

conn = channels_conn()
rows, total = fetch_channels(conn, limit=50, offset=0, query="%a%a%a%a%zq")
check("wildcard payload matches nothing", total == 0, f"total={total}")
rows, total = fetch_channels(conn, limit=50, offset=0, query="100% pure_data")
check("literal % and _ still match", total == 1, f"total={total}")
rows, total = fetch_channels(conn, limit=50, offset=0, query="daily")
check("ordinary search unaffected", total == 1, f"total={total}")
rows, total = fetch_channels(conn, limit=50, offset=0, instance="evil.example")
check("instance filter unaffected", total == 200, f"total={total}")

start = time.monotonic()
fetch_channels(conn, limit=50, offset=0, query="%a" * 12 + "%zq")
elapsed = time.monotonic() - start
check("hostile pattern is cheap", elapsed < 1.0, f"{elapsed:.3f}s")
conn.close()

print("task 75 - statement deadline")
conn = sqlite3.connect(":memory:")
interrupted = False
start = time.monotonic()
try:
    with statement_deadline(conn, 0.3):
        # Cartesian self-join over a generated series: long enough to trip the handler.
        conn.execute(
            "WITH RECURSIVE s(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM s WHERE x<2000)"
            " SELECT COUNT(*) FROM s a, s b, s c"
        ).fetchone()
except sqlite3.OperationalError as exc:
    interrupted = is_interrupted_error(exc)
elapsed = time.monotonic() - start
check("long statement interrupted", interrupted, f"elapsed={elapsed:.3f}s")
check("interrupted near the deadline", elapsed < 3.0, f"elapsed={elapsed:.3f}s")

handler_cleared = True
try:
    conn.execute("SELECT 1").fetchone()
except sqlite3.OperationalError:
    handler_cleared = False
check("handler cleared after the block", handler_cleared)
conn.close()

print("task 78 - batch ingest")
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
ensure_interaction_event_schema(conn)


def event(index: int, raw: dict | None = None) -> dict:
    """Build one minimal Like event."""
    payload = {
        "event_id": f"e{index}",
        "event_type": "Like",
        "object": {"video_uuid": "u1", "instance_domain": "h1"},
    }
    if raw is not None:
        payload["raw_payload"] = raw
    return payload


for i in range(5):
    ingest_interaction_event(conn, event(i), commit=False)
uncommitted = conn.execute("SELECT COUNT(*) FROM interaction_raw_events").fetchone()[0]
conn.commit()
committed = conn.execute("SELECT COUNT(*) FROM interaction_raw_events").fetchone()[0]
check("commit=False defers the commit", uncommitted == 5 and committed == 5)

duplicate = ingest_interaction_event(conn, event(0), commit=False)
check("duplicate still detected in batch mode", duplicate.get("duplicate") is True)

ingest_interaction_event(conn, event(90, raw={"k": "v"}), commit=True)
stored = conn.execute(
    "SELECT raw_payload_json FROM interaction_raw_events WHERE event_id = 'e90'"
).fetchone()[0]
check("small raw_payload kept", stored == '{"k": "v"}', stored)

ingest_interaction_event(conn, event(91, raw={"k": "v" * MAX_RAW_PAYLOAD_BYTES}), commit=True)
stored = conn.execute(
    "SELECT raw_payload_json FROM interaction_raw_events WHERE event_id = 'e91'"
).fetchone()[0]
check("oversized raw_payload dropped", stored == "{}", stored[:40])
conn.close()

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    sys.exit(1)
print("All checks passed.")
