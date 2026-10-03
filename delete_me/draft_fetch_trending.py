"""Probe stand-in: the plan's draft fetch-trending.py, with ensure_trending_schema inlined, to check the checkpoint's harness against a plausible implementation. Deleted after the probe."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from data.moderation import list_active_denied_hosts
from data.time import now_ms

TRENDING_PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"
MAX_RANK = 100
AGE_OUT_MS = 10 * 24 * 60 * 60 * 1000
INSERT_SQL = "INSERT INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at) VALUES (?, ?, ?, ?, ?, ?)"


def ensure_trending_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS trending_ranks (
          instance_domain TEXT NOT NULL,
          video_id TEXT NOT NULL,
          rank INTEGER NOT NULL,
          likes INTEGER NOT NULL,
          views INTEGER NOT NULL,
          fetched_at INTEGER NOT NULL,
          PRIMARY KEY (instance_domain, video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trending_ranks_order
          ON trending_ranks (rank ASC, likes DESC, views DESC, video_id DESC, instance_domain DESC);
        """
    )


def video_key(video):
    raw = video.get("uuid")
    if raw is None:
        raw = video.get("id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    return None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def rank_rows(host, videos, fetched_at):
    rows = []
    seen = set()
    for rank, video in enumerate(videos[:MAX_RANK], start=1):
        key = video_key(video) if isinstance(video, dict) else None
        if key is None or key in seen:
            continue
        seen.add(key)
        rows.append((host, key, rank, _count(video.get("likes")), _count(video.get("views")), fetched_at))
    return rows


def fetch_host_list(host, timeout_s, max_retries):
    request = Request(f"https://{host}{TRENDING_PATH}", headers={"Accept": "application/json"})
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read())
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise ValueError("no data list")
            return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            logging.debug("trending fetch host=%s attempt=%d failed: %s", host, attempt + 1, exc)
    return None


def _fetch_safely(fetch_list, host):
    try:
        return fetch_list(host)
    except Exception:
        return None


def run(conn, fetch_list, concurrency):
    ensure_trending_schema(conn)
    denied = list_active_denied_hosts(conn)
    hosts = sorted(row[0] for row in conn.execute("SELECT DISTINCT instance_domain FROM video_embeddings") if row[0] and row[0].lower() not in denied)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        lists = dict(zip(hosts, pool.map(partial(_fetch_safely, fetch_list), hosts)))
    run_ms = now_ms()
    answered = {host: rank_rows(host, videos, run_ms) for host, videos in lists.items() if videos is not None}
    failed = sorted(host for host, videos in lists.items() if videos is None)
    start = time.monotonic()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for host, rows in answered.items():
            conn.execute("DELETE FROM trending_ranks WHERE instance_domain = ?", (host,))
            conn.executemany(INSERT_SQL, rows)
        purged = conn.execute("DELETE FROM trending_ranks WHERE fetched_at < ?", (run_ms - AGE_OUT_MS,)).rowcount
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"asked": len(hosts), "answered": len(answered), "failed": len(failed), "written": sum(len(rows) for rows in answered.values()), "purged": purged, "transaction_ms": int((time.monotonic() - start) * 1000)}
