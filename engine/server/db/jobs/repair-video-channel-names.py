#!/usr/bin/env python3
"""Repair `videos.channel_name` from each video's own channel.

Every video is given the `display_name` of the channel keyed by its own `(channel_id, instance_domain)`. Channel ids are only unique per instance, so a name copied from the same id on another instance is corrected here. On a database with `videos_fts` the index is rebuilt afterwards.
"""
import argparse
import importlib.util
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parents[1]))

from scripts.cli_format import CompactHelpFormatter

REPAIR_CHANNEL_NAMES_SQL = """
UPDATE videos
SET channel_name = (
  SELECT c.display_name FROM channels c
  WHERE c.channel_id = videos.channel_id AND c.instance_domain = videos.instance_domain
)
WHERE EXISTS (
  SELECT 1 FROM channels c
  WHERE c.channel_id = videos.channel_id
    AND c.instance_domain = videos.instance_domain
    AND c.display_name IS NOT NULL
    AND c.display_name <> ''
    AND videos.channel_name IS NOT c.display_name
);
"""


def _load_sync_whitelist():
    """Load `sync-whitelist.py`, whose hyphenated name rules out a normal import, for its `videos_fts` helpers."""
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_repair", script_dir / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_videos_fts(conn: sqlite3.Connection) -> bool:
    """Return whether the database carries the `videos_fts` index (whitelist shape) or not (crawl shape)."""
    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'videos_fts';").fetchone()
    return bool(row)


def repair_channel_names(conn: sqlite3.Connection) -> int:
    """Set each video's `channel_name` to its own channel's non-empty `display_name`, commit, and return the rows changed.

    Rows whose channel is missing or has no display name keep their stored name: there is nothing better to put there. On the whitelist shape the update runs between `sync-whitelist.py`'s trigger drop and recreate, then `videos_fts` is rebuilt and its count checked on every run, even when nothing changed, because a per-row `'delete'` from the triggers cannot mend an index that already drifted.
    """
    if not has_videos_fts(conn):
        with conn:
            changed = conn.execute(REPAIR_CHANNEL_NAMES_SQL).rowcount
        return int(changed)
    # rat-tail: the helpers use executescript, which commits, so the update is committed before the rebuild and a failed rebuild is recovered by re-running, not by rollback; one transaction needs the helpers to run their SQL through conn.execute instead.
    sync = _load_sync_whitelist()
    sync.drop_videos_fts_triggers(conn)
    changed = conn.execute(REPAIR_CHANNEL_NAMES_SQL).rowcount
    sync.create_videos_fts_triggers(conn)
    fts_count = sync.rebuild_videos_fts(conn)
    videos_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    if fts_count != videos_count:
        raise RuntimeError(f"videos_fts holds {fts_count} rows but videos holds {videos_count}; the full-text index did not rebuild cleanly.")
    conn.commit()
    return int(changed)


def main() -> None:
    """Parse `--db`, repair that database and log the rows changed."""
    parser = argparse.ArgumentParser(description="Repair videos.channel_name from the channel on each video's own instance.", formatter_class=CompactHelpFormatter)
    # No default: every neighbour defaults to the shared whitelist.db, and a bare run of a migration must not hit it by accident.
    parser.add_argument("--db", required=True, metavar="PATH", help="Path to the crawl.db or whitelist.db to repair (required; there is no default).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db)
    # sqlite3.connect would create an empty file for a mistyped path and then fail on the missing tables.
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        changed = repair_channel_names(conn)
    finally:
        conn.close()
    logging.info("channel names repaired rows=%d", changed)


if __name__ == "__main__":
    main()
