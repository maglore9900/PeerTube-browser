"""Probe: where the rows in the dev whitelist.db's trending_ranks came from, and the published dates of the Trending head."""

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))
sys.path.insert(0, str(ROOT / "engine" / "server" / "api"))

from data.random_videos import fetch_ordered_page  # noqa: E402


def test_probe():
    conn = sqlite3.connect(f"file:{ROOT / 'engine/server/db/whitelist.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    print("fetched_at groups", [tuple(r) for r in conn.execute("SELECT fetched_at, COUNT(*) FROM trending_ranks GROUP BY fetched_at ORDER BY 2 DESC LIMIT 5")])
    rows = fetch_ordered_page(conn, "trending", 24, 0, error_threshold=3, include_nsfw=False)
    now = time.time() * 1000
    for r in rows:
        rank = conn.execute("SELECT rank, views FROM trending_ranks WHERE instance_domain=? AND video_id=?", (r["instance_domain"], r["video_id"])).fetchone()
        age = (now - r["published_at"]) / 86400000 / 365 if r["published_at"] else None
        print(f"rank={rank[0]} listed_views={rank[1]} age_years={age and round(age, 1)} host={r['instance_domain']} title={r['title'][:50]!r}")
    conn.close()
    assert False, "probe"
