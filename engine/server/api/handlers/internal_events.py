"""Internal bridge ingest handler for normalized interaction events."""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from data.db import is_interrupted_error
from data.interaction_events import ingest_interaction_event, prune_interaction_raw_events
from data.time import now_ms
from http_utils import read_json_body, respond_json
from server_config import DEFAULT_INGEST_CHUNK_SIZE, DEFAULT_MAX_INGEST_EVENTS, INTERACTION_RAW_PRUNE_CHUNK_SIZE, INTERACTION_RAW_PRUNE_INTERVAL_SECONDS, INTERACTION_RAW_RETENTION_DAYS

DAY_MS = 86_400_000


def handle_internal_events_ingest(handler: Any, server: Any) -> bool:
    """Accept bridge events and ingest them idempotently into Engine DB.

    The batch is capped and committed in chunks, releasing the global DB lock between
    them: one commit per event fsyncs under that lock, so a large batch otherwise
    makes every other Engine endpoint wait for the whole ingest.

    After a successful ingest it also strips raw events older than the retention window, at most once per `INTERACTION_RAW_PRUNE_INTERVAL_SECONDS`; the strip never changes the response.
    """
    try:
        body = read_json_body(handler)
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True

    events: list[dict[str, Any]]
    if isinstance(body.get("events"), list):
        events = [item for item in body["events"] if isinstance(item, dict)]
    else:
        events = [body] if isinstance(body, dict) else []

    if not events:
        respond_json(handler, 400, {"error": "Missing events"})
        return True

    max_events = getattr(server, "max_ingest_events", DEFAULT_MAX_INGEST_EVENTS)
    if len(events) > max_events:
        respond_json(
            handler,
            400,
            {
                "error": "Too many events",
                "max_allowed": max_events,
                "received": len(events),
            },
        )
        return True

    chunk_size = max(int(getattr(server, "ingest_chunk_size", DEFAULT_INGEST_CHUNK_SIZE)), 1)
    ingested = 0
    duplicates = 0
    results: list[dict[str, Any]] = []
    try:
        for start in range(0, len(events), chunk_size):
            chunk = events[start : start + chunk_size]
            with server.db_lock:
                try:
                    for event in chunk:
                        result = ingest_interaction_event(server.db, event, commit=False)
                        results.append(result)
                        if result.get("duplicate"):
                            duplicates += 1
                        else:
                            ingested += 1
                    server.db.commit()
                except Exception:
                    server.db.rollback()
                    raise
    except ValueError as exc:
        respond_json(handler, 400, {"error": str(exc)})
        return True
    except Exception as exc:  # pragma: no cover
        respond_json(handler, 500, {"error": str(exc)})
        return True

    _prune_raw_events_if_due(server)
    respond_json(
        handler,
        200,
        {
            "ok": True,
            "count": len(results),
            "ingested": ingested,
            "duplicates": duplicates,
            "results": results,
        },
    )
    return True


def _prune_raw_events_if_due(server: Any) -> None:
    """Run the raw-event retention strip when the interval since the last one has passed.

    The slot is claimed before the strip runs and without a lock: two threads that read the timestamp together may both strip, which is harmless because the strip is idempotent. Failures are logged and never reach the ingest caller; the next slot retries.
    """
    now = time.monotonic()
    last_run = getattr(server, "last_raw_prune_at", None)
    if last_run is not None and now - last_run < INTERACTION_RAW_PRUNE_INTERVAL_SECONDS:
        return
    server.last_raw_prune_at = now
    days = int(getattr(server, "raw_retention_days", INTERACTION_RAW_RETENTION_DAYS))
    try:
        stripped = prune_interaction_raw_events(server.db, now_ms() - days * DAY_MS, INTERACTION_RAW_PRUNE_CHUNK_SIZE, lock=server.db_lock)
    except Exception as exc:
        if isinstance(exc, sqlite3.OperationalError) and is_interrupted_error(exc):
            # rat-tail: the strip shares the request's statement deadline, so a large backlog drains over several slots, and not at all while no ingests arrive; the upgrade is resetting last_raw_prune_at on an interrupt, or running the strip from the updater.
            logging.warning("[ingest] raw-event retention strip hit the request deadline; the next slot resumes it")
        else:
            logging.exception("[ingest] raw-event retention strip failed")
        return
    if stripped:
        logging.info("[ingest] stripped %d raw events older than %d days", stripped, days)
