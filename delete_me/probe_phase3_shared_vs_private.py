"""Throwaway probe: shared vs private Trending head and popular pool, read-only on the shared whitelist.db."""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data import random_videos, trending  # noqa: E402

WHITELIST_DB = ROOT / "engine" / "server" / "db" / "whitelist.db"
FP = "SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at), COUNT(CASE WHEN fetched_at > 0 THEN 1 END) FROM main.trending_ranks"
SEED_SQL = """
INSERT INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at)
SELECT instance_domain, video_id, rank, likes, views, 0
FROM (
  SELECT
    v.instance_domain,
    v.video_id,
    COALESCE(v.likes, 0) AS likes,
    COALESCE(v.views, 0) AS views,
    ROW_NUMBER() OVER (PARTITION BY v.instance_domain ORDER BY v.views DESC, v.likes DESC, v.video_id DESC) AS rank
  FROM videos v
  JOIN video_embeddings e
    ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
)
WHERE rank <= 100
"""


def _keys(rows):
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def test_probe(tmp_path):
    spec = importlib.util.spec_from_file_location("cfg", ROOT / "engine" / "server" / "api" / "server_config.py")
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    threshold, pool = cfg.VIDEO_ERROR_THRESHOLD, cfg.DEFAULT_POPULAR_POOL_SIZE
    print("threshold", threshold, "pool", pool, "has attach", hasattr(trending, "attach_trending_override"))

    shared = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    shared.row_factory = sqlite3.Row
    print("shared fp before", tuple(shared.execute(FP).fetchone()))

    private = tmp_path / "trending.db"
    conn = sqlite3.connect(f"file:{private}", uri=True)
    trending.ensure_trending_schema(conn)
    conn.execute("ATTACH DATABASE ? AS shared", (f"file:{WHITELIST_DB}?mode=ro",))
    with conn:
        conn.execute(SEED_SQL)
    print("private rows", conn.execute("SELECT COUNT(*) FROM main.trending_ranks").fetchone())
    conn.close()

    ds = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    ds.row_factory = sqlite3.Row
    trending.attach_trending_override(ds, str(private))
    print("ds main fp", tuple(ds.execute(FP).fetchone()))

    s_head = _keys(random_videos.fetch_ordered_page(shared, "trending", 36, 0, error_threshold=threshold, include_nsfw=False))
    p_head = _keys(random_videos.fetch_ordered_page(ds, "trending", 36, 0, error_threshold=threshold, include_nsfw=False))
    print("head lens", len(s_head), len(p_head), "equal", s_head == p_head, "common", len(set(s_head) & set(p_head)))
    print("shared head[:3]", s_head[:3], "private head[:3]", p_head[:3])

    s_pool = set(_keys(random_videos.fetch_popular_videos(shared, pool, error_threshold=threshold, include_nsfw=False)))
    p_pool = set(_keys(random_videos.fetch_popular_videos(ds, pool, error_threshold=threshold, include_nsfw=False)))
    p_pool_unf = set(_keys(random_videos.fetch_popular_videos(ds, pool)))
    print("pools", len(s_pool), len(p_pool), "shared outside private", len(s_pool - p_pool), "filtered private outside unfiltered", len(p_pool - p_pool_unf))
    print("shared fp after", tuple(shared.execute(FP).fetchone()))
    assert False, "probe"
