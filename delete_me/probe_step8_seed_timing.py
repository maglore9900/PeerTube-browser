"""Probe: how long the conftest trending seed holds whitelist.db's write lock, and how long the home popular pool read takes."""

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
sys.path.insert(0, str(ROOT / "engine" / "server"))
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))

import conftest  # noqa: E402
from data.random_videos import fetch_popular_videos  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402


def test_probe_timings():
    conn = sqlite3.connect(conftest.WHITELIST_DB, timeout=30)
    print("journal_mode", conn.execute("PRAGMA journal_mode").fetchone())
    ensure_trending_schema(conn)
    t0 = time.monotonic()
    with conn:
        conn.execute("DELETE FROM trending_ranks")
        t1 = time.monotonic()
        conn.execute(conftest.TRENDING_SEED_SQL)
        t2 = time.monotonic()
    t3 = time.monotonic()
    print(f"seed delete={t1 - t0:.2f}s insert={t2 - t1:.2f}s commit={t3 - t2:.2f}s total={t3 - t0:.2f}s")
    conn.row_factory = sqlite3.Row
    for _ in range(3):
        t0 = time.monotonic()
        rows = fetch_popular_videos(conn, 5000, error_threshold=3, include_nsfw=False)
        print(f"pool rows={len(rows)} {time.monotonic() - t0:.2f}s")
    conn.close()
    assert False, "probe: read stdout"
