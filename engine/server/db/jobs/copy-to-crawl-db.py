#!/usr/bin/env python3
"""Copy into crawl.db the instances, channels and videos a whitelist DB holds and crawl.db lacks.

The dataset build's sync stage (`sync-whitelist.py`) rebuilds `whitelist.db` from `crawl.db`, so a row only `whitelist.db` holds is lost on the next sync. The updater worker merges new videos straight into `whitelist.db`; this job carries them back. It inserts the rows crawl.db lacks, and on a video crawl.db holds it changes one thing: a NULL `tags_json` takes the whitelist's tags, so tags filled later by `backfill-null-tags.py` survive a sync. Nothing else crawl.db holds is changed. Columns are the ones both DBs share. A crawl.db older than the `videos.language` column gains it first, as the crawler's own `migrateVideosLanguage` would, so the copy keeps it.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from scripts.cli_format import CompactHelpFormatter

# Parents before children: channels and videos name an instance, videos a channel.
TABLE_KEYS = (
    ("instances", ("host",)),
    ("channels", ("channel_id", "instance_domain")),
    ("videos", ("video_id", "instance_domain")),
)
# Waits out a crawler writing crawl.db; the crawler commits row by row, so its locks are short.
BUSY_TIMEOUT_S = 30


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def copy_missing_rows(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert into main (crawl.db) every row of the attached `source` whose key main lacks, table by table, in one transaction; return the rows copied per table."""
    copied: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        if "language" not in _columns(conn, "main", "videos"):
            conn.execute("ALTER TABLE main.videos ADD COLUMN language TEXT")
        for table, keys in TABLE_KEYS:
            source_columns = set(_columns(conn, "source", table))
            columns = [column for column in _columns(conn, "main", table) if column in source_columns]
            if not set(keys) <= set(columns):
                raise RuntimeError(f"{table}: key {keys} is not in both DBs")
            names = ", ".join(columns)
            match = " AND ".join(f"m.{key} = s.{key}" for key in keys)
            copied[table] = conn.execute(
                f"INSERT INTO main.{table} ({names}) SELECT {', '.join('s.' + c for c in columns)} FROM source.{table} s "
                f"WHERE NOT EXISTS (SELECT 1 FROM main.{table} m WHERE {match})"
            ).rowcount
        # Tags fetched after a row was copied (backfill-null-tags.py) would otherwise be lost on the next sync. Only NULL is filled: crawl.db's own tags, and its '[]', stay.
        copied["tags"] = conn.execute(
            "UPDATE main.videos AS m SET tags_json = s.tags_json FROM source.videos AS s "
            "WHERE m.video_id = s.video_id AND m.instance_domain = s.instance_domain AND m.tags_json IS NULL AND s.tags_json IS NOT NULL"
        ).rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return copied


def main() -> None:
    """Parse the options, copy the missing rows and log how many each table gained."""
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(description="Copy into crawl.db the rows a whitelist DB holds and crawl.db lacks.", formatter_class=CompactHelpFormatter)
    parser.add_argument("--source-db", default=str((repo_root / DEFAULT_DB_PATH).resolve()), metavar="PATH", help=f"Whitelist DB to copy from (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--crawl-db", default=str((repo_root / "engine" / "crawler" / "data" / "crawl.db").resolve()), metavar="PATH", help="Crawl DB to copy into (default: engine/crawler/data/crawl.db)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    source_db, crawl_db = Path(args.source_db), Path(args.crawl_db)
    # sqlite3.connect would create an empty file for a mistyped path.
    for path in (source_db, crawl_db):
        if not path.is_file():
            parser.error(f"database not found: {path}")
    conn = sqlite3.connect(str(crawl_db), timeout=BUSY_TIMEOUT_S)
    try:
        conn.execute("ATTACH DATABASE ? AS source", (str(source_db),))
        copied = copy_missing_rows(conn)
    finally:
        conn.close()
    logging.info("copied to crawl.db instances=%d channels=%d videos=%d tags_filled=%d", copied["instances"], copied["channels"], copied["videos"], copied["tags"])


if __name__ == "__main__":
    main()
