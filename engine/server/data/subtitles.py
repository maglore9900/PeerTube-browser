"""Translated caption tracks in engine/server/db/subtitles.db, one row per (video_id, instance_domain, target_language).

B1 writes only state 'ready' with source 'instance'. state and source are plain TEXT with no CHECK, so plan 49 adds its job states and the 'whisper' source to this table without a rebuild. cues_json is one compact JSON array per row; plan 49's per-chunk appends need a cue table or a blob rewrite.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# Longer than sqlite3's 5 s default: several Engines may create the table at once on a fresh file, and two blue/green Engines write it.
SUBTITLES_BUSY_TIMEOUT_SECONDS = 30.0


def connect_subtitles_db(path: Path) -> sqlite3.Connection:
    """Open or create the subtitles database; no deadline handler, so statement_deadline does not bound it."""
    conn = sqlite3.connect(path.as_posix(), check_same_thread=False, timeout=SUBTITLES_BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_subtitles_schema(conn: sqlite3.Connection) -> None:
    """Create the subtitles table if it is missing."""
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subtitles (
              video_id TEXT NOT NULL,
              instance_domain TEXT NOT NULL,
              target_language TEXT NOT NULL,
              state TEXT NOT NULL,
              source TEXT NOT NULL,
              fetched_at INTEGER NOT NULL,
              track_text TEXT,
              cues_json TEXT,
              PRIMARY KEY (video_id, instance_domain, target_language)
            )
            """
        )


def fetch_ready_subtitles(conn: sqlite3.Connection, video_id: str, instance_domain: str, target_language: str) -> list[dict[str, Any]] | None:
    """The stored cues of a ready row; None for no row, another state, or a cues_json that does not load as a non-empty list."""
    row = conn.execute(
        "SELECT cues_json FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = ? AND state = 'ready'",
        (video_id, instance_domain, target_language),
    ).fetchone()
    if row is None:
        return None
    try:
        cues = json.loads(row["cues_json"] or "")
    except (ValueError, RecursionError):
        return None
    return cues if isinstance(cues, list) and cues else None


def store_ready_subtitles(conn: sqlite3.Connection, video_id: str, instance_domain: str, target_language: str, source: str, track_text: str, cues: list[dict[str, Any]], fetched_at: int) -> None:
    """Upsert a ready row; a concurrent miss on the same key writes the same row twice, harmlessly."""
    with conn:
        conn.execute(
            """
            INSERT INTO subtitles (video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json)
            VALUES (?, ?, ?, 'ready', ?, ?, ?, ?)
            ON CONFLICT(video_id, instance_domain, target_language) DO UPDATE SET
              state = excluded.state, source = excluded.source, fetched_at = excluded.fetched_at, track_text = excluded.track_text, cues_json = excluded.cues_json
            """,
            (video_id, instance_domain, target_language, source, fetched_at, track_text, json.dumps(cues, ensure_ascii=False, separators=(",", ":"))),
        )
