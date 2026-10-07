#!/usr/bin/env python3
"""Fill `videos.tags_json` where it is NULL, from each video's own instance.

Only NULL rows are asked: `'[]'` means the instance answered with no tags, and re-asking those is why the dataset build's tags stage never converges. Active-denylisted hosts are skipped. Each host is worked through one video at a time with a delay between requests, several hosts at once; a host that fails `--host-give-up` videos in a row is left for a later run. Rows are written through `videos`, so the `videos_fts` triggers keep tag search current, one transaction per host. A failed fetch leaves the row NULL, so re-running the job resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.parse import quote

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
for _path in (server_dir, server_dir / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from data.moderation import list_active_denied_hosts
from data.source_fetch import SourceFetchFailed, fetch_bounded
from handlers.video import to_tags_json
from scripts.cli_format import CompactHelpFormatter

BUSY_TIMEOUT_S = 10
UPDATE_SQL = "UPDATE videos SET tags_json = ? WHERE video_id = ? AND instance_domain = ? AND tags_json IS NULL"


def fetch_video_tags(host: str, uuid: str, timeout_s: float) -> str | None:
    """Return the video's tags as stored tags_json ("[]" when it has none), or None when the fetch failed or the answer carries no tag list."""
    try:
        detail = json.loads(fetch_bounded(host, f"/api/v1/videos/{quote(uuid)}", deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"accept": "application/json", "User-Agent": "peertube-browser-tags/1.0"}))
    except (SourceFetchFailed, ValueError) as exc:
        logging.debug("tags fetch host=%s uuid=%s failed: %s", host, uuid, exc)
        return None
    return to_tags_json(detail.get("tags")) if isinstance(detail, dict) else None


def pending_by_host(conn: sqlite3.Connection, limit: int) -> dict[str, list[tuple[str, str]]]:
    """Return the NULL-tag videos with a uuid on undenied hosts, as host -> [(video_id, uuid)]; at most `limit` videos when limit > 0."""
    denied = list_active_denied_hosts(conn)
    sql = "SELECT video_id, video_uuid, instance_domain FROM videos WHERE tags_json IS NULL AND video_uuid IS NOT NULL ORDER BY instance_domain, published_at DESC"
    grouped: dict[str, list[tuple[str, str]]] = {}
    taken = 0
    for video_id, uuid, host in conn.execute(sql):
        if not host or host.lower() in denied:
            continue
        grouped.setdefault(host, []).append((video_id, uuid))
        taken += 1
        if limit and taken >= limit:
            break
    return grouped


def fetch_host(host: str, videos: list[tuple[str, str]], fetch_tags: Callable[[str, str], str | None], host_delay_s: float, give_up_after: int) -> tuple[list[tuple[str, str, str]], int]:
    """Fetch one host's videos in turn; return the (tags_json, video_id, host) updates and how many fetches failed. Stops after `give_up_after` failures in a row."""
    updates: list[tuple[str, str, str]] = []
    failed = streak = 0
    for index, (video_id, uuid) in enumerate(videos):
        if index and host_delay_s > 0:
            time.sleep(host_delay_s)
        try:
            tags_json = fetch_tags(host, uuid)
        except Exception as exc:
            logging.warning("tags fetch host=%s uuid=%s raised: %s", host, uuid, exc)
            tags_json = None
        if tags_json is None:
            failed += 1
            streak += 1
            if give_up_after and streak >= give_up_after:
                logging.info("tags host=%s given up after %d failures in a row; %d videos left for a later run", host, streak, len(videos) - index - 1)
                break
            continue
        streak = 0
        updates.append((tags_json, video_id, host))
    return updates, failed


def run(conn: sqlite3.Connection, fetch_tags: Callable[[str, str], str | None], concurrency: int, host_delay_s: float = 0.2, give_up_after: int = 5, limit: int = 0) -> dict[str, int]:
    """Fetch the NULL-tag videos host by host and write each host's answers in its own transaction as it finishes; return the run's counters."""
    grouped = pending_by_host(conn, limit)
    stats = {"hosts": len(grouped), "asked": sum(len(videos) for videos in grouped.values()), "written": 0, "failed": 0}
    logging.info("tags backfill hosts=%d videos=%d", stats["hosts"], stats["asked"])
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(fetch_host, host, videos, fetch_tags, host_delay_s, give_up_after): host for host, videos in grouped.items()}
        # Writes stay on this thread: one connection, one writer.
        for future in as_completed(futures):
            updates, failed = future.result()
            stats["failed"] += failed
            if not updates:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                stats["written"] += conn.executemany(UPDATE_SQL, updates).rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            logging.info("tags host=%s written=%d failed=%d", futures[future], len(updates), failed)
    return stats


def main() -> None:
    """Parse the options, fill NULL tags in that database and log the run's counters."""
    repo_root = script_dir.parents[3]
    from server_config import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(description="Fill videos.tags_json where it is NULL, from each video's own instance.", formatter_class=CompactHelpFormatter)
    parser.add_argument("--db", default=str((repo_root / DEFAULT_DB_PATH).resolve()), metavar="PATH", help=f"Path to database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--concurrency", type=int, default=4, metavar="N", help="Hosts fetched at once (default: 4).")
    parser.add_argument("--timeout-ms", type=int, default=5000, metavar="MS", help="HTTP timeout per video (default: 5000).")
    parser.add_argument("--host-delay-ms", type=int, default=200, metavar="MS", help="Pause between requests to one host (default: 200).")
    parser.add_argument("--host-give-up", type=int, default=5, metavar="N", help="Leave a host after N failures in a row; 0 never (default: 5).")
    parser.add_argument("--limit", type=int, default=0, metavar="N", help="Ask at most N videos; 0 is all (default: 0).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db)
    # sqlite3.connect would create an empty file for a mistyped path and then fail on the missing tables.
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    # The busy timeout waits out Engine reads holding SHARED while the write lock is taken.
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_S)
    try:
        # list_active_denied_hosts reads its rows by column name.
        conn.row_factory = sqlite3.Row
        fetch_tags = partial(fetch_video_tags, timeout_s=args.timeout_ms / 1000)
        stats = run(conn, fetch_tags, args.concurrency, args.host_delay_ms / 1000, args.host_give_up, args.limit)
    finally:
        conn.close()
    logging.info("tags backfill hosts=%d asked=%d written=%d failed=%d", stats["hosts"], stats["asked"], stats["written"], stats["failed"])


if __name__ == "__main__":
    main()
