"""Derive and guard the ANN id of an embedded video (ADR-0006)."""

from __future__ import annotations

import hashlib
import sqlite3

from data.moderation import normalize_host

# The sidecar id_source an index keyed by ann_id records.
ANN_ID_SOURCE = "video_embeddings.ann_id"
ANN_ID_MASK = (1 << 63) - 1


def compute_ann_id(video_id: str, instance_domain: str) -> int:
    """Return the 63-bit blake2b id of `video_id::normalized host`; the same key gives the same id in any process and DB."""
    # A domain normalize_host rejects hashes as its trimmed, lowercased text, so the id never raises inside a bulk SQL write.
    host = normalize_host(instance_domain) or str(instance_domain).strip().lower()
    digest = hashlib.blake2b(f"{video_id}::{host}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ANN_ID_MASK


def create_video_embeddings_table(conn: sqlite3.Connection) -> None:
    """Create video_embeddings from the shared definition unless it exists; an id of 0 fails its CHECK."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_embeddings (
          video_id TEXT NOT NULL,
          instance_domain TEXT NOT NULL,
          embedding BLOB NOT NULL,
          embedding_dim INTEGER NOT NULL,
          model_name TEXT NOT NULL,
          created_at TEXT NOT NULL,
          ann_id INTEGER NOT NULL CHECK (ann_id > 0),
          PRIMARY KEY (video_id, instance_domain),
          FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain)
        )
        """
    )


def create_ann_id_guards(conn: sqlite3.Connection) -> None:
    """Create the UNIQUE ann_id index and the collision trigger; video_embeddings must already carry ann_id."""
    # The UNIQUE index refuses a colliding UPDATE; the name differs from idx_video_embeddings_id_instance, which data/videos.py drops at every Engine start.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)")
    # Plain SQL so any connection can insert; BEFORE INSERT fires ahead of OR REPLACE conflict resolution, so a foreign id aborts instead of deleting the row that holds it.
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision
        BEFORE INSERT ON video_embeddings
        WHEN EXISTS (
          SELECT 1 FROM video_embeddings
          WHERE ann_id = NEW.ann_id
            AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)
        )
        BEGIN
          SELECT RAISE(ABORT, 'video_embeddings ann_id collision: another (video_id, instance_domain) holds this ann_id');
        END
        """
    )


def assert_video_embeddings_has_ann_id(conn: sqlite3.Connection, schema: str = "main") -> None:
    """Raise RuntimeError unless {schema}.video_embeddings carries ann_id; a missing table passes."""
    # Positional row[1]: merge and sync read through sqlite3.Row.
    columns = [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(video_embeddings)")]
    if columns and "ann_id" not in columns:
        raise RuntimeError(
            f"{schema}.video_embeddings has no ann_id column; it predates the stable ANN ids. "
            "Run engine/server/db/jobs/migrate-whitelist.py on this database; a staging DB reused "
            "with --resume-staging must instead be recreated by running the updater without it."
        )


def ensure_video_embeddings_schema(conn: sqlite3.Connection) -> None:
    """Create video_embeddings from the shared definition, refuse an old-shape table, then create the guards; never commits."""
    create_video_embeddings_table(conn)
    # Checked before the guards, so an old table gets the migrate pointer instead of a raw "no such column: ann_id".
    assert_video_embeddings_has_ann_id(conn)
    create_ann_id_guards(conn)
