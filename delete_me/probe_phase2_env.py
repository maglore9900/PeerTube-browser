from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))
import conftest as active  # noqa: E402

dataset = active.dataset
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = active.ENGINE_PY

SEED_HEAD = """
WITH ranked AS (
  SELECT v.instance_domain, v.video_id, COALESCE(v.likes, 0) AS likes, COALESCE(v.views, 0) AS views,
         ROW_NUMBER() OVER (PARTITION BY v.instance_domain ORDER BY v.views DESC, v.likes DESC, v.video_id DESC) AS rank
  FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
)
SELECT r.instance_domain, r.video_id, r.rank, r.likes, r.views, v.nsfw, v.error_count FROM ranked r JOIN videos v ON v.video_id = r.video_id AND v.instance_domain = r.instance_domain
WHERE r.rank <= 100
ORDER BY r.rank, r.likes DESC, r.views DESC, r.video_id DESC, r.instance_domain DESC
LIMIT ?
"""


def test_conftest_fixture_reuse(dataset):
    print("dataset fixture works", dataset.execute("SELECT COUNT(*) FROM videos").fetchone()[0])


def test_seed_head(dataset):
    start = time.monotonic()
    rows = dataset.execute(SEED_HEAD, (200,)).fetchall()
    print("seed head ms", int((time.monotonic() - start) * 1000))
    print("flagged in head 96", sum(1 for r in rows[:96] if r["nsfw"] == 1), "first flagged index", next((i for i, r in enumerate(rows) if r["nsfw"] == 1), None))
    print("head 5", [tuple(r) for r in rows[:5]])
    start = time.monotonic()
    total = dataset.execute("SELECT COUNT(*) FROM (" + SEED_HEAD.replace("LIMIT ?", "") + ")").fetchone()[0]
    print("ranked total", total, "ms", int((time.monotonic() - start) * 1000))
    print("denylist active", dataset.execute("SELECT COUNT(*) FROM instance_denylist WHERE is_active = 1").fetchone()[0])
    print("blocked channels", dataset.execute("SELECT COUNT(*) FROM channel_moderation WHERE status = 'blocked'").fetchone()[0])


MIX_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import server_config
    from recommendations.mixer import MixerDeps, MixingRecommendationStrategy
    from recommendations.keys import like_key

    class Layer:
        def __init__(self, name, empty):
            self.name = name
            self.empty = empty
            self.asked = []

        def get_candidates(self, server, user_id, limit, refresh_cache=False, config=None):
            self.asked.append(limit)
            if self.empty:
                return []
            return [{"video_id": f"{self.name}-{i}", "instance_domain": "h.example", "channel_id": f"{self.name}-ch-{i}", "views": 10, "likes": 1, "published_at": 1700000000000, "similarity_score": 0.5} for i in range(limit)]

    likes = [{"video_id": "liked-1", "instance_domain": "h.example"}]
    out = {}
    for case, (mode, with_likes, popular_empty) in {"guest_empty": ("home", False, True), "guest_full": ("home", False, False), "home_empty": ("home", True, True), "home_full": ("home", True, False)}.items():
        layers = {name: Layer(name, popular_empty and name == "popular") for name in ("random", "popular", "explore", "exploit", "fresh")}
        deps = MixerDeps(like_key=like_key, fetch_recent_likes=lambda user_id, limit, w=with_likes: list(likes) if w else [], max_likes=50, fetch_embeddings_by_ids=lambda server, rows: {}, fetch_dislike_centroids=lambda: None, fetch_excluded_keys=set, dislike_similarity_floor=0.0)
        strategy = MixingRecommendationStrategy(layers, server_config.RECOMMENDATION_PIPELINE, deps)
        rows = strategy.generate_recommendations(None, "u", 0, mode=mode)
        out[case] = {"count": len(rows), "distinct": len({like_key(r) for r in rows}), "asked": {n: l.asked for n, l in layers.items()}, "by_layer": {n: sum(1 for r in rows if r["video_id"].startswith(n + "-")) for n in layers}}
    print(json.dumps(out))
    """
)


def test_mix_child():
    run = subprocess.run([str(ENGINE_PY), "-c", MIX_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    print("rc", run.returncode, run.stdout[-4000:], run.stderr[-3000:])
