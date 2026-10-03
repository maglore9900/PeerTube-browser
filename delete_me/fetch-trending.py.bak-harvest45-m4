#!/usr/bin/env python3
"""Store each catalogue host's own PeerTube trending list in `trending_ranks`.

Hosts are the distinct `video_embeddings.instance_domain` values minus the active denylist. Every list is fetched before the write transaction opens. In one transaction, each answered host's rows are replaced by its new list, a failed host's rows are left alone, and any row fetched more than 10 days before the run is purged.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

script_dir = Path(__file__).resolve().parent
server_dir = script_dir.parents[1]
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

from data.moderation import list_active_denied_hosts
from data.time import now_ms
from data.trending import ensure_trending_schema
from scripts.cli_format import CompactHelpFormatter

# One page per host, ordered by PeerTube's own trending.videos.intervalDays window (ADR-0010).
TRENDING_PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
MAX_RANK = 100
# The updater runs weekly: a host failing one run keeps its list, a host failing two loses it (operator decision, issue 38).
AGE_OUT_MS = 10 * 24 * 60 * 60 * 1000
BUSY_TIMEOUT_S = 10
# Negative is KiB: room for a full write, so the page cache does not spill and take EXCLUSIVE before commit while the Engine reads.
CACHE_SIZE_KIB = -65536
INSERT_SQL = "INSERT INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at) VALUES (?, ?, ?, ?, ?, ?)"


def video_key(video: dict[str, Any]) -> str | None:
    """Return the crawler's video_id for a listed video, as videos-worker.ts toStringId(video.uuid ?? video.id): a non-empty string, or an integer as its decimal string."""
    raw = video.get("uuid")
    if raw is None:
        raw = video.get("id")
    if isinstance(raw, str):
        return raw or None
    # bool is an int subclass; JSON true is not an id.
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return None


def _count(value: Any) -> int:
    """Return a listed count as an int, 0 for anything that is not one."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def rank_rows(host: str, videos: list[Any], fetched_at: int) -> list[tuple[str, str, int, int, int, int]]:
    """Return the rank rows of one host's list: rank is the 1-based list position, an entry without a key leaves a gap, and a repeated key keeps its first rank."""
    rows = []
    seen: set[str] = set()
    for rank, video in enumerate(videos[:MAX_RANK], start=1):
        key = video_key(video) if isinstance(video, dict) else None
        if key is None or key in seen:
            continue
        seen.add(key)
        rows.append((host, key, rank, _count(video.get("likes")), _count(video.get("views")), fetched_at))
    return rows


def fetch_host_list(host: str, timeout_s: float, max_retries: int) -> list[Any] | None:
    """Return a host's trending list (possibly empty), or None when all max_retries + 1 attempts failed."""
    # rat-tail: every failure is retried, 4xx included, with no backoff; a status-code check here if dead hosts stretch the stage.
    request = Request(f"https://{host}{TRENDING_PATH}", headers={"User-Agent": "peertube-browser-trending/1.0"})
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read())
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise ValueError("body has no data list")
            return data
        # OSError covers HTTPError, URLError and timeouts; ValueError covers a non-JSON body.
        except (OSError, ValueError) as exc:
            logging.debug("trending fetch host=%s attempt=%d failed: %s", host, attempt + 1, exc)
    return None


def _fetch_safely(fetch_list: Callable[[str], list[Any] | None], host: str) -> list[Any] | None:
    """Run one host's fetch: any exception is that host failing, never the job."""
    try:
        return fetch_list(host)
    except Exception as exc:
        logging.warning("trending fetch host=%s raised: %s", host, exc)
        return None


def run(conn: sqlite3.Connection, fetch_list: Callable[[str], list[Any] | None], concurrency: int) -> dict[str, int]:
    """Fetch every undenied embedded host's list with no transaction open, then replace answered hosts' rows and purge aged rows in one transaction; return the run's counters."""
    ensure_trending_schema(conn)
    denied = list_active_denied_hosts(conn)
    # The denylist is lowercased, so a host stored mixed-case is compared lowercased.
    hosts = sorted(row[0] for row in conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings") if row[0] and row[0].lower() not in denied)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        lists = dict(zip(hosts, pool.map(partial(_fetch_safely, fetch_list), hosts)))
    run_ms = now_ms()
    answered = {host: rank_rows(host, videos, run_ms) for host, videos in lists.items() if videos is not None}
    failed = [host for host, videos in lists.items() if videos is None]
    if failed:
        logging.warning("trending hosts failed: %s", " ".join(failed))
    conn.execute("BEGIN IMMEDIATE")
    start = time.monotonic()
    try:
        for host, rows in answered.items():
            conn.execute("DELETE FROM trending_ranks WHERE instance_domain = ?", (host,))
            conn.executemany(INSERT_SQL, rows)
        purged = conn.execute("DELETE FROM trending_ranks WHERE fetched_at < ?", (run_ms - AGE_OUT_MS,)).rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    transaction_ms = int((time.monotonic() - start) * 1000)
    return {"asked": len(hosts), "answered": len(answered), "failed": len(failed), "written": sum(len(rows) for rows in answered.values()), "purged": purged, "transaction_ms": transaction_ms}


def main() -> None:
    """Parse the options, refresh `trending_ranks` in that database and log the run's counters."""
    parser = argparse.ArgumentParser(description="Store each catalogue host's own PeerTube trending list.", formatter_class=CompactHelpFormatter)
    repo_root = script_dir.parents[3]
    api_dir = repo_root / "engine" / "server" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from server_config import DEFAULT_DB_PATH

    parser.add_argument("--db", default=str((repo_root / DEFAULT_DB_PATH).resolve()), metavar="PATH", help=f"Path to database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--concurrency", type=int, default=4, metavar="N", help="Hosts fetched at once (default: 4).")
    parser.add_argument("--timeout-ms", type=int, default=5000, metavar="MS", help="HTTP timeout per attempt (default: 5000).")
    parser.add_argument("--max-retries", type=int, default=3, metavar="N", help="HTTP retries per host (default: 3).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db_path = Path(args.db)
    # sqlite3.connect would create an empty file for a mistyped path and then fail on the missing tables.
    if not db_path.is_file():
        parser.error(f"database not found: {db_path}")
    # The busy timeout waits out Engine reads holding SHARED while the write lock is taken.
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_S)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA cache_size = {CACHE_SIZE_KIB}")
        fetch_list = partial(fetch_host_list, timeout_s=args.timeout_ms / 1000, max_retries=args.max_retries)
        stats = run(conn, fetch_list, args.concurrency)
    finally:
        conn.close()
    logging.info("trending hosts asked=%d answered=%d failed=%d rows written=%d purged by age=%d transaction=%dms", stats["asked"], stats["answered"], stats["failed"], stats["written"], stats["purged"], stats["transaction_ms"])


if __name__ == "__main__":
    main()
