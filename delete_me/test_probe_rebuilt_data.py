"""Probe: what the rebuilt dataset holds for the data-pinned controls (cache entry sizes, nsfw rank in the ordered feeds)."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WL = ROOT / "engine/server/db/whitelist.db"
SC = ROOT / "engine/server/db/similarity-cache.db"


def test_probe_cache_sizes():
    conn = sqlite3.connect(f"file:{SC}?mode=ro", uri=True)
    rows = conn.execute("SELECT length(neighbours)/8 AS n, count(*) FROM similarity_sources GROUP BY n ORDER BY n").fetchall()
    total = sum(c for _, c in rows)
    short = [(n, c) for n, c in rows if n < 48]
    print(f"\nPROBE sources={total} short(<48)={sum(c for _, c in short)} dist_short={short[:60]}")
    print(f"PROBE min={rows[0]} max={rows[-1]}")
    for lo in (0, 1, 20, 48, 100, 200, 300, 500, 1000):
        print(f"PROBE n<={lo}: {sum(c for n, c in rows if n <= lo)}")


def test_probe_nsfw_rank():
    conn = sqlite3.connect(f"file:{WL}?mode=ro", uri=True)
    total = conn.execute("SELECT count(*), sum(nsfw=1) FROM videos").fetchone()
    print(f"\nPROBE videos={total}")
    orders = {
        "recent": "published_at DESC, video_id DESC, instance_domain DESC",
        "hot": "popularity DESC, likes DESC, views DESC, published_at DESC, video_id DESC, instance_domain DESC",
        "popular": "likes DESC, views DESC, video_id DESC, instance_domain DESC",
    }
    for name, order in orders.items():
        ranks = [i for i, (nsfw,) in enumerate(conn.execute(f"SELECT nsfw FROM videos WHERE error_count IS NULL OR error_count < 3 ORDER BY {order} LIMIT 500"), 1) if nsfw == 1]
        print(f"PROBE {name} flagged ranks in top 500: {ranks[:15]} count={len(ranks)}")
