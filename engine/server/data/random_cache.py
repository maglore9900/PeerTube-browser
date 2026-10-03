"""Provide random cache runtime helpers."""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from data.db import connect_readonly_db, swap_readonly_connection

# rat-tail: an unmeasured ceiling from the in-place rebuild; builds now write a per-pid temp file no other connection writes, so only a caller writing a shared cache file through connect_random_cache_db waits on it, and only the in-place tests in tests/active/test_random_cache.py still do. Upgrade by archiving those tests and dropping the timeout with `reuse_non_empty`.
RANDOM_CACHE_BUSY_TIMEOUT_SECONDS = 3600
# The swap's validation query: a finished cache must have the table and answer a count.
RANDOM_CACHE_CHECK_SQL = "SELECT COUNT(*) FROM random_ann_ids"


def connect_random_cache_db(path: Path) -> sqlite3.Connection:
    """Handle connect random cache db."""
    conn = sqlite3.connect(path.as_posix(), timeout=RANDOM_CACHE_BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Journal in memory, not in <path>-journal: the served handle keeps a build's temp name after the rename, and a later same-pid build's on-disk journal at that name would look hot to it and fail every read.
    conn.execute("PRAGMA journal_mode=MEMORY").fetchall()
    return conn


def ensure_random_cache_schema(conn: sqlite3.Connection) -> None:
    """Handle ensure random cache schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS random_ann_ids (
          position INTEGER PRIMARY KEY,
          ann_id INTEGER NOT NULL
        );
        """
    )


def random_ann_ids_count(conn: sqlite3.Connection) -> int | None:
    """Return the number of cached ANN ids, or None when the random_ann_ids table is missing (an old-format random_rowids file counts as missing)."""
    # rat-tail: an old cache is detected by table name, not shape; a future reshape under the same name needs a PRAGMA table_info check here.
    # fetchall, so no statement is left holding SHARED on the file.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'random_ann_ids' LIMIT 1").fetchall():
        return None
    return int(conn.execute("SELECT COUNT(*) FROM random_ann_ids").fetchall()[0][0])


def populate_random_cache(
    src_db: sqlite3.Connection,
    cache_db: sqlite3.Connection,
    size: int,
    refresh: bool = False,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
    reuse_non_empty: bool = False,
) -> int:
    """Handle populate random cache."""
    if size <= 0:
        return 0
    # Checked before ensure_random_cache_schema so the reuse path sends no DDL, whose lock needs vary by sqlite version.
    # rat-tail: any non-empty cache is reused, so a short or stale one is kept until a refresh; no production caller passes it since the Engine opens its cache read-only, only the in-place tests do, so the upgrade is removing it when they are archived.
    if not refresh and reuse_non_empty:
        reusable = random_ann_ids_count(cache_db)
        if reusable:
            return reusable
    ensure_random_cache_schema(cache_db)
    existing = cache_db.execute("SELECT COUNT(*) FROM random_ann_ids").fetchone()
    if not refresh and existing and int(existing[0]) >= size:
        return int(existing[0])
    cache_db.execute("DELETE FROM random_ann_ids")
    total_row = src_db.execute(
        "SELECT COUNT(*) AS total, MIN(ann_id) AS min_id, MAX(ann_id) AS max_id "
        "FROM video_embeddings"
    ).fetchone()
    if not total_row:
        cache_db.commit()
        return 0
    total = int(total_row["total"] or 0)
    if total == 0:
        cache_db.commit()
        return 0
    min_id = int(total_row["min_id"])
    max_id = int(total_row["max_id"])
    target = min(size, total)
    # Hashed ids are uniform over [min_id, max_id], so a window from a random start is a uniform sample, not a block of insertion order.
    start_id = random.randint(min_id, max_id)
    if not filtered_mode or (max_per_instance <= 0 and max_per_author <= 0):
        rows = src_db.execute(
            "SELECT ann_id FROM video_embeddings WHERE ann_id >= ? ORDER BY ann_id LIMIT ?",
            (start_id, target),
        ).fetchall()
        if len(rows) < target:
            rows += src_db.execute(
                "SELECT ann_id FROM video_embeddings WHERE ann_id < ? ORDER BY ann_id LIMIT ?",
                (start_id, target - len(rows)),
            ).fetchall()
        random.shuffle(rows)
        cache_db.executemany(
            "INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)",
            [(index, int(row["ann_id"])) for index, row in enumerate(rows, start=1)],
        )
        cache_db.commit()
        return len(rows)

    ann_ids: list[int] = []
    instance_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    seen: set[int] = set()
    scanned = 0
    chunk_size = 10000

    def try_add(entry: sqlite3.Row) -> bool:
        """Handle try add."""
        ann_id = int(entry["ann_id"])
        if ann_id in seen:
            return False
        instance = entry["instance_domain"] or ""
        if max_per_instance > 0 and instance:
            if instance_counts.get(instance, 0) >= max_per_instance:
                return False
        author: str | None = None
        channel_id = entry["channel_id"]
        if channel_id:
            author = f"{channel_id}::{instance}"
            if max_per_author > 0 and author_counts.get(author, 0) >= max_per_author:
                return False
        ann_ids.append(ann_id)
        seen.add(ann_id)
        if instance:
            instance_counts[instance] = instance_counts.get(instance, 0) + 1
        if author:
            author_counts[author] = author_counts.get(author, 0) + 1
        return True

    def scan_range(range_start: int, range_end: int) -> None:
        """Handle scan range."""
        nonlocal scanned
        if range_end < range_start:
            return
        current = range_start
        while current <= range_end and len(ann_ids) < target:
            rows = src_db.execute(
                """
                SELECT
                  e.ann_id AS ann_id,
                  v.instance_domain AS instance_domain,
                  v.channel_id AS channel_id
                FROM video_embeddings e
                JOIN videos v
                  ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
                WHERE e.ann_id >= ? AND e.ann_id <= ?
                ORDER BY e.ann_id
                LIMIT ?
                """,
                (current, range_end, chunk_size),
            ).fetchall()
            if not rows:
                break
            scanned += len(rows)
            current = int(rows[-1]["ann_id"]) + 1
            for entry in rows:
                if len(ann_ids) >= target:
                    break
                try_add(entry)

    scan_range(start_id, max_id)
    if len(ann_ids) < target:
        scan_range(min_id, start_id - 1)

    if len(ann_ids) < target:
        logging.info(
            "random cache filtered fill short: target=%d got=%d scanned=%d",
            target,
            len(ann_ids),
            scanned,
        )
    logging.info(
        "random cache filtered=%s size=%d scanned=%d max_per_instance=%d max_per_author=%d",
        filtered_mode,
        len(ann_ids),
        scanned,
        max_per_instance,
        max_per_author,
    )
    random.shuffle(ann_ids)
    cache_db.executemany(
        "INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)",
        [(index, ann_id) for index, ann_id in enumerate(ann_ids, start=1)],
    )
    cache_db.commit()
    return len(ann_ids)


def random_cache_temp_path(active_path: Path) -> Path:
    """Return this process's build file beside `active_path`: <stem>.tmp.<pid><suffix>, so Engines sharing a checkout never write the same one."""
    return active_path.with_name(f"{active_path.stem}.tmp.{os.getpid()}{active_path.suffix}")


def remove_random_cache_temp(temp_path: Path) -> None:
    """Delete a build file and its rollback-journal sidecar, whichever exist."""
    for path in (temp_path, temp_path.with_name(f"{temp_path.name}-journal")):
        path.unlink(missing_ok=True)


def build_random_cache(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool = False,
    max_per_instance: int = 0,
    max_per_author: int = 0,
) -> tuple[Path, int, float]:
    """Build a complete random cache into this process's temp file beside `active_path` and close it.

    The source is read through its own read-only connection. The active file is not touched: the caller renames the returned temp file into place. On any exception the temp file is removed and the exception re-raised.

    :returns: (temp path, ANN ids written, elapsed seconds).
    """
    started = time.monotonic()
    temp_path = random_cache_temp_path(active_path)
    # A file of this name can only be left by an earlier process with the same pid.
    remove_random_cache_temp(temp_path)
    src_db: sqlite3.Connection | None = None
    cache_db: sqlite3.Connection | None = None
    try:
        try:
            src_db = connect_readonly_db(source_path)
            cache_db = connect_random_cache_db(temp_path)
            # Created here because populate_random_cache returns before its own schema step when size <= 0, and a table-less file must never be installed.
            ensure_random_cache_schema(cache_db)
            count = populate_random_cache(src_db, cache_db, size, True, filtered_mode, max_per_instance, max_per_author)
            cache_db.commit()
        finally:
            # Closed before any removal: closing rolls back an open write and deletes its journal.
            if cache_db is not None:
                cache_db.close()
            if src_db is not None:
                src_db.close()
    except BaseException:
        remove_random_cache_temp(temp_path)
        raise
    return temp_path, count, time.monotonic() - started


def refresh_random_cache(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool,
    max_per_instance: int,
    max_per_author: int,
    owner: Any,
    stop_event: threading.Event,
) -> bool:
    """Build a new random cache and swap it in as `owner.random_cache_db` under `owner.random_cache_lock`.

    Never raises: a failure anywhere in the build, check or rename is logged, the temp file is removed, and the active file and serving connection are left as they were. A build finishing after `stop_event` is set is discarded.

    :returns: True when a new cache was swapped in.
    """
    started = time.monotonic()
    temp_path = random_cache_temp_path(active_path)
    # Logged here rather than in build_random_cache, so the line marks the build's start even while the build itself is held or slow to begin.
    logging.info("random cache build start target=%d filtered=%s max_per_instance=%d max_per_author=%d temp=%s", size, filtered_mode, max_per_instance, max_per_author, temp_path)
    try:
        _, count, _ = build_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author)
        if stop_event.is_set():
            remove_random_cache_temp(temp_path)
            logging.info("random cache build skipped duration=%.2fs reason=stopping", time.monotonic() - started)
            return False
        swap_readonly_connection(temp_path, active_path, owner.random_cache_lock, owner, "random_cache_db", RANDOM_CACHE_CHECK_SQL)
    except Exception as exc:
        remove_random_cache_temp(temp_path)
        logging.info("random cache build failed duration=%.2fs reason=%s: %s", time.monotonic() - started, type(exc).__name__, exc)
        return False
    logging.info("random cache build ok duration=%.2fs size=%d target=%d path=%s", time.monotonic() - started, count, size, active_path)
    return True


def open_random_cache_if_usable(path: Path) -> sqlite3.Connection | None:
    """Open the random cache read-only if it holds at least one ANN id; otherwise log why and return None, which serves the random feed from the DB."""
    # Checked first so a missing file is reported as such rather than as sqlite's open error.
    if not path.exists():
        logging.info("random cache unusable path=%s reason=missing", path)
        return None
    conn: sqlite3.Connection | None = None
    try:
        conn = connect_readonly_db(path)
        count = random_ann_ids_count(conn)
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        logging.info("random cache unusable path=%s reason=%s: %s", path, type(exc).__name__, exc)
        return None
    if not count:
        conn.close()
        logging.info("random cache unusable path=%s reason=%s", path, "no_table" if count is None else "empty")
        return None
    return conn


def run_random_cache_worker(
    source_path: Path,
    active_path: Path,
    size: int,
    filtered_mode: bool,
    max_per_instance: int,
    max_per_author: int,
    owner: Any,
    stop_event: threading.Event,
    startup_build: bool,
    interval_seconds: float,
) -> None:
    """Run every random cache build of one Engine, one at a time: the startup build if asked, then one per interval until `stop_event` is set.

    Meant as a daemon thread's target, so an in-progress build never delays shutdown. A failed build is retried at the next tick; with `interval_seconds` 0 it is not retried.
    """
    if startup_build:
        refresh_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event)
    while interval_seconds > 0:
        if stop_event.wait(interval_seconds):
            return
        refresh_random_cache(source_path, active_path, size, filtered_mode, max_per_instance, max_per_author, owner, stop_event)


def fetch_random_ann_ids(cache_db: sqlite3.Connection, limit: int) -> list[int]:
    """Return up to `limit` cached ANN ids in position order, from a random offset when the cache holds more."""
    if limit <= 0:
        return []
    count_row = cache_db.execute("SELECT COUNT(*) FROM random_ann_ids").fetchone()
    if not count_row:
        return []
    total = int(count_row[0])
    if total <= 0:
        return []
    start = 0 if total <= limit else random.randint(0, total - limit)
    rows = cache_db.execute(
        "SELECT ann_id FROM random_ann_ids ORDER BY position LIMIT ? OFFSET ?",
        (limit, start),
    ).fetchall()
    return [int(row["ann_id"]) for row in rows]
