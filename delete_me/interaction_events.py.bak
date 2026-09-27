"""Provide interaction events runtime helpers."""

from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager, nullcontext
from typing import Any

from data.time import now_ms

ALLOWED_EVENT_TYPES = {"Like", "UndoLike", "Comment"}
# Cap for the caller-supplied raw_payload blob stored per event (bytes).
MAX_RAW_PAYLOAD_BYTES = 4096
# A raw event still holding data the retention strip removes. The partial index and the prune query share this text because SQLite only uses a partial index whose predicate the query implies term for term.
_UNSTRIPPED_ROW = "raw_payload_json IS NOT NULL OR actor_id IS NOT NULL OR source_instance IS NOT NULL"


def ensure_interaction_event_schema(conn: sqlite3.Connection) -> None:
    """Create raw/aggregated interaction event tables if missing."""
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS interaction_raw_events (
          event_id TEXT PRIMARY KEY,
          event_type TEXT NOT NULL,
          actor_id TEXT,
          video_uuid TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          canonical_url TEXT,
          source_instance TEXT,
          published_at INTEGER NOT NULL,
          raw_payload_json TEXT,
          ingested_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS interaction_raw_events_video_idx
          ON interaction_raw_events (video_uuid, instance_domain, published_at DESC);
        -- Covers only rows the prune still has to strip, so each chunk skips the already-stripped history.
        CREATE INDEX IF NOT EXISTS interaction_raw_events_unstripped_idx
          ON interaction_raw_events (ingested_at)
          WHERE {_UNSTRIPPED_ROW};

        CREATE TABLE IF NOT EXISTS interaction_signals (
          video_uuid TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          likes_count INTEGER NOT NULL DEFAULT 0,
          undo_likes_count INTEGER NOT NULL DEFAULT 0,
          comments_count INTEGER NOT NULL DEFAULT 0,
          signal_score REAL NOT NULL DEFAULT 0,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (video_uuid, instance_domain)
        );
        """
    )
    conn.commit()


def ingest_interaction_event(
    conn: sqlite3.Connection, payload: dict[str, Any], *, commit: bool = True
) -> dict[str, Any]:
    """Insert one event idempotently and update aggregated interaction signals.

    :param conn: Engine database connection.
    :param payload: One normalized bridge event.
    :param commit: Commit this event on its own. Batch callers pass False and commit
        once per chunk instead: a commit per event fsyncs while the global DB lock is
        held, which stalls every other Engine endpoint for the length of the batch.
    :returns: Ingest result with the event id and whether it was a duplicate.
    """
    event = normalize_event_payload(payload)
    ingested_at = now_ms()
    cursor = conn.execute(
        """
        INSERT INTO interaction_raw_events (
          event_id,
          event_type,
          actor_id,
          video_uuid,
          instance_domain,
          canonical_url,
          source_instance,
          published_at,
          raw_payload_json,
          ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO NOTHING
        """,
        (
            event["event_id"],
            event["event_type"],
            event["actor_id"],
            event["video_uuid"],
            event["instance_domain"],
            event["canonical_url"],
            event["source_instance"],
            event["published_at"],
            json.dumps(event["raw_payload"], ensure_ascii=False),
            ingested_at,
        ),
    )
    inserted = int(cursor.rowcount or 0) > 0
    if not inserted:
        if commit:
            conn.commit()
        return {
            "ok": True,
            "duplicate": True,
            "event_id": event["event_id"],
            "event_type": event["event_type"],
        }

    deltas = _event_deltas(event["event_type"])
    conn.execute(
        """
        INSERT INTO interaction_signals (
          video_uuid,
          instance_domain,
          likes_count,
          undo_likes_count,
          comments_count,
          signal_score,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_uuid, instance_domain) DO UPDATE SET
          likes_count = MAX(0, interaction_signals.likes_count + excluded.likes_count),
          undo_likes_count = MAX(0, interaction_signals.undo_likes_count + excluded.undo_likes_count),
          comments_count = MAX(0, interaction_signals.comments_count + excluded.comments_count),
          signal_score = MAX(0.0, interaction_signals.signal_score + excluded.signal_score),
          updated_at = excluded.updated_at
        """,
        (
            event["video_uuid"],
            event["instance_domain"],
            deltas["likes_count"],
            deltas["undo_likes_count"],
            deltas["comments_count"],
            deltas["signal_score"],
            ingested_at,
        ),
    )
    if commit:
        conn.commit()
    return {
        "ok": True,
        "duplicate": False,
        "event_id": event["event_id"],
        "event_type": event["event_type"],
    }


def prune_interaction_raw_events(
    conn: sqlite3.Connection,
    cutoff: int,
    chunk_size: int,
    *,
    lock: AbstractContextManager[Any] | None = None,
) -> int:
    """Strip actor and payload data from raw events ingested before `cutoff`.

    The row itself stays, so a replayed event is still recognised as a duplicate.

    :param conn: Engine database connection.
    :param cutoff: Epoch milliseconds; rows with `ingested_at` below it are stripped.
    :param chunk_size: Most rows stripped per commit.
    :param lock: Held for each chunk and released between them, so other Engine
        endpoints sharing the global DB lock are not stalled for the whole prune.
    :returns: Number of rows stripped.
    """
    guard = lock if lock is not None else nullcontext()
    stripped = 0
    while True:
        with guard:
            cursor = conn.execute(
                f"""
                UPDATE interaction_raw_events
                SET raw_payload_json = NULL, actor_id = NULL, source_instance = NULL
                WHERE rowid IN (
                  SELECT rowid FROM interaction_raw_events
                  WHERE ({_UNSTRIPPED_ROW})
                    AND ingested_at < ?
                  LIMIT ?
                )
                """,
                (cutoff, chunk_size),
            )
            conn.commit()
        changed = int(cursor.rowcount or 0)
        if changed == 0:
            return stripped
        stripped += changed


def normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize bridge event payload."""
    event_id = _clean_text(payload.get("event_id"))
    event_type = _clean_text(payload.get("event_type"))
    actor_id = _clean_text(payload.get("actor_id"))
    if not event_id:
        raise ValueError("Missing event_id")
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("Unsupported event_type")

    obj = payload.get("object")
    if not isinstance(obj, dict):
        raise ValueError("Missing object")
    video_uuid = _clean_text(obj.get("video_uuid"))
    instance_domain = _clean_text(obj.get("instance_domain"))
    canonical_url = _clean_text(obj.get("canonical_url"))
    if not video_uuid:
        raise ValueError("Missing object.video_uuid")
    if not instance_domain:
        raise ValueError("Missing object.instance_domain")

    published_raw = payload.get("published_at")
    try:
        published_at = int(published_raw)
    except (TypeError, ValueError):
        published_at = now_ms()

    return {
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "video_uuid": video_uuid,
        "instance_domain": instance_domain,
        "canonical_url": canonical_url,
        "published_at": published_at,
        "source_instance": _clean_text(payload.get("source_instance")),
        "raw_payload": _bounded_raw_payload(payload.get("raw_payload")),
    }


def _bounded_raw_payload(value: Any) -> dict[str, Any]:
    """Return `value` as a stored payload, dropping it when oversized.

    `interaction_raw_events` keeps this blob until `prune_interaction_raw_events` strips it after the `INTERACTION_RAW_RETENTION_DAYS` window, so an unbounded caller-supplied object would still be a free way to grow the database inside that window.

    :param value: Caller-supplied `raw_payload` field.
    :returns: The payload when it is a dict within the size limit, else an empty dict.
    """
    if not isinstance(value, dict):
        return {}
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_RAW_PAYLOAD_BYTES:
        return {}
    return value


def _event_deltas(event_type: str) -> dict[str, float]:
    """Handle event deltas."""
    if event_type == "Like":
        return {
            "likes_count": 1,
            "undo_likes_count": 0,
            "comments_count": 0,
            "signal_score": 1.0,
        }
    if event_type == "UndoLike":
        return {
            "likes_count": -1,
            "undo_likes_count": 1,
            "comments_count": 0,
            "signal_score": -1.0,
        }
    return {
        "likes_count": 0,
        "undo_likes_count": 0,
        "comments_count": 1,
        "signal_score": 0.25,
    }


def _clean_text(value: Any) -> str | None:
    """Handle clean text."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None
