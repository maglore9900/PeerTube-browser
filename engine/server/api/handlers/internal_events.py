"""Internal bridge ingest handler for normalized interaction events."""
from __future__ import annotations

from typing import Any

from data.interaction_events import ingest_interaction_event
from http_utils import read_json_body, respond_json
from server_config import DEFAULT_INGEST_CHUNK_SIZE, DEFAULT_MAX_INGEST_EVENTS


def handle_internal_events_ingest(handler: Any, server: Any) -> bool:
    """Accept bridge events and ingest them idempotently into Engine DB.

    The batch is capped and committed in chunks, releasing the global DB lock between
    them: one commit per event fsyncs under that lock, so a large batch otherwise
    makes every other Engine endpoint wait for the whole ingest.
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
