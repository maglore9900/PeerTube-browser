"""`PopularVideosGenerator.get_candidates` ends its likes path in a similarity-weighted draw when `weighted_random_alpha` is positive, and in the unchanged uniform sample otherwise.

- With likes and alpha 1.0 or 0.5, `limit` distinct candidates come back, the 0.9-similarity group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5) while the 0.1 group still appears, and zero-weight candidates (0.0, negative, missing embedding) appear only to fill a shortfall, spread over every one of them.
- With alpha missing, None, 0, -1.0 or NaN, or with every weight zero, each draw equals `random.sample(ordered, limit)` under the same seed, `ordered` being the pool sorted by similarity rather than the pool's own (low-first) order.
- A pool of `limit` or fewer comes back whole.

`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.

The mix answers an empty popular layer without falling short for guests:

- The real `MixingRecommendationStrategy` on `RECOMMENDATION_PIPELINE`, with the real `PopularVideosGenerator` over the real `fetch_popular_videos` and stub other layers, serves no popular row once `trending_ranks` is emptied, though the catalogue holds rows. It gives `guest_home` a full 48-row batch and `home` with likes 43 rows, short by exactly popular's 5-row share. With ranks present, popular fills its 5 slots (control).

That runs in a child on the Engine's interpreter over a temp whitelist-shaped DB holding the labelled rows in `RANKS`, once with its ranks and once with `trending_ranks` emptied.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
LIMIT = 5
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for _path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data import random_videos  # noqa: E402
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

_CHILD = textwrap.dedent(
    """
    import json, math, random, sys, threading
    from types import SimpleNamespace
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    import numpy as np
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator

    SERVER = SimpleNamespace(db=None, db_lock=threading.Lock())

    def vector(sim):
        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)

    def generator(pool):
        table = {"like": np.array([1.0, 0.0], dtype=np.float32)}
        table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})
        return PopularVideosGenerator(PopularVideosDeps(
            fetch_popular_videos=lambda db, count: [{"video_id": vid} for vid in pool],
            fetch_recent_likes=lambda user_id, count: [{"video_id": "like"}],
            fetch_embeddings_by_ids=lambda db, rows: {r["video_id"]: table[r["video_id"]] for r in rows if r["video_id"] in table},
            like_key=lambda row: row["video_id"],
            max_likes=10,
        ))

    out = {}
    for case in json.loads(sys.argv[2]):
        pool, limit = case["pool"], case["limit"]
        config = {"pool_size": len(pool), "max_per_author": 0, "max_per_instance": 0}
        if "alpha" in case:
            config["weighted_random_alpha"] = float("nan") if case["alpha"] == "nan" else case["alpha"]
        # nominal similarity clamped at 0, stable descending, as the generator orders its scored pool
        ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)
        gen = generator(pool)
        draws, expected = [], []
        for trial in range(case["trials"]):
            random.seed(f"{case['name']}:{trial}")
            draws.append([row["video_id"] for row in gen.get_candidates(SERVER, "user", limit, config=config)])
            if case.get("uniform"):
                random.seed(f"{case['name']}:{trial}")
                expected.append(random.sample(ordered, limit))
        out[case["name"]] = {"draws": draws, "expected": expected}
    print(json.dumps(out))
    """
)


def _pool(**groups: tuple[int, float | None]) -> dict[str, float | None]:
    return {f"{prefix}{i}": sim for prefix, (count, sim) in groups.items() for i in range(count)}


# low group first, so the pool's own order differs from the similarity order the uniform draw must sample from
LO_HI = _pool(lo=(10, 0.1), hi=(10, 0.9))
ZERO_FILL = {**_pool(p=(3, 0.5), z=(5, 0.0)), "neg0": -0.5, "none0": None}
SKEW = {"skew": (1.0, 3), "skew_half": (0.5, 2)}
DISABLED = {"disabled_missing": {}, "disabled_none": {"alpha": None}, "disabled_zero": {"alpha": 0}, "disabled_negative": {"alpha": -1.0}, "disabled_nan": {"alpha": "nan"}}
SMALL = {"small_equal": {"a": 0.9, "b": 0.5, "c": 0.0, "d": None, "e": 0.2}, "small_under": {"a": 0.9, "b": 0.0, "c": 0.4}}

CASES = [
    *({"name": name, "pool": LO_HI, "alpha": alpha, "limit": LIMIT, "trials": 400} for name, (alpha, _) in SKEW.items()),
    {"name": "zero_fill", "pool": ZERO_FILL, "alpha": 1.0, "limit": LIMIT, "trials": 100},
    {"name": "zero_unused", "pool": {**_pool(p=(6, 0.5), z=(10, 0.0)), "neg0": -0.5, "none0": None}, "alpha": 1.0, "limit": LIMIT, "trials": 200},
    {"name": "all_zero", "pool": {**_pool(z=(10, 0.0)), "neg0": -0.3, "none0": None}, "alpha": 1.0, "limit": LIMIT, "trials": 50, "uniform": True},
    *({"name": name, "pool": LO_HI, **extra, "limit": LIMIT, "trials": 50, "uniform": True} for name, extra in DISABLED.items()),
    *({"name": name, "pool": pool, "alpha": 1.0, "limit": LIMIT, "trials": 3} for name, pool in SMALL.items()),
]


@pytest.fixture(scope="module")
def draws() -> dict[str, dict[str, list]]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(CASES)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _assert_full_and_distinct(results: list[list[str]]) -> None:
    assert results
    for draw in results:
        assert len(draw) == LIMIT and len(set(draw)) == LIMIT, draw


@pytest.mark.parametrize("name", list(SKEW))
def test_closer_candidates_are_drawn_clearly_more_often_and_never_twice(draws, name):
    results = draws[name]["draws"]
    _assert_full_and_distinct(results)  # C1
    hi = sum(vid.startswith("hi") for draw in results for vid in draw)
    lo = sum(vid.startswith("lo") for draw in results for vid in draw)
    # a reference Efraimidis-Spirakis draw under these seeds gave 1773:227 at alpha 1.0 and 1468:532 at 0.5; the uniform sample gave 974:1026 and 1042:958
    assert hi >= SKEW[name][1] * lo, (hi, lo)  # C1
    assert lo > 0, (hi, lo)  # C1: a draw, not a deterministic top-`limit` pick


def test_zero_weight_candidates_fill_only_a_shortfall_and_spread_over_all_of_them(draws):
    filled = draws["zero_fill"]["draws"]
    _assert_full_and_distinct(filled)  # C1
    positives = {"p0", "p1", "p2"}
    fill_ids: set[str] = set()
    for draw in filled:
        assert positives <= set(draw), draw  # C1: every positive-weight candidate is taken before any zero-weight one
        fill_ids |= set(draw) - positives
    assert fill_ids == set(ZERO_FILL) - positives  # C1: the fill is drawn over every zero-weight candidate, not in pool order
    unused = draws["zero_unused"]["draws"]
    _assert_full_and_distinct(unused)  # C1
    assert [vid for draw in unused for vid in draw if not vid.startswith("p")] == []  # C1: enough positives, so no zero-weight id (0.0, negative or missing embedding) ever appears


def test_all_zero_weights_draw_exactly_the_uniform_sample(draws):
    case = draws["all_zero"]
    _assert_full_and_distinct(case["draws"])  # C2
    assert case["draws"] == case["expected"]  # C2


@pytest.mark.parametrize("name", list(DISABLED))
def test_a_missing_none_zero_negative_or_nan_alpha_draws_exactly_the_uniform_sample(draws, name):
    case = draws[name]
    _assert_full_and_distinct(case["draws"])  # C2
    assert case["draws"] == case["expected"]  # C2


@pytest.mark.parametrize("name", list(SMALL))
def test_a_pool_of_limit_or_fewer_comes_back_whole(draws, name):
    results = draws[name]["draws"]
    assert results
    for draw in results:
        assert sorted(draw) == sorted(SMALL[name])


CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
# label: (video_id, instance_domain, rank or None, listed likes, listed views, nsfw, error_count, in videos, embedded).
RANKS = {
    "C1": ("c1", "c.example", 1, 70, 10, 0, 0, True, True),
    "X": ("x1", "d.example", 1, 60, 10, 1, 0, True, True),
    "B1": ("b1", "b.example", 1, 50, 900, None, 0, True, True),
    "A1": ("a1", "a.example", 1, 50, 100, 0, 0, True, True),
    "B2": ("v-z", "b.example", 2, 10, 10, 0, 0, True, True),
    "C2": ("v-m", "c.example", 2, 10, 10, 0, 0, True, True),
    "A2": ("v-m", "a.example", 2, 10, 10, 0, 0, True, True),
    "E": ("v-a", "d.example", 2, 10, 10, 0, 3, True, True),
    "A3": ("a3", "a.example", 3, 500, 5000, 0, 0, True, True),
    "B5": ("b5", "b.example", 5, 400, 4000, 0, 0, True, True),
    "GHOST": ("g1", "f.example", 1, 999, 999, 0, 0, False, False),
    "U": ("u1", "e.example", 1, 999, 999, 0, 0, True, False),
    "N": ("n1", "b.example", None, 0, 0, 0, 0, True, True),
}
# The Trending order of RANKS, derived by hand: the ten ranked catalogue rows. Crawled likes and popularity rise along it, so a likes or popularity order comes out reversed.
TRENDING_ORDER = ["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"]


def _ranks_db(path: Path) -> sqlite3.Connection:
    """A whitelist-shaped DB holding the RANKS rows: the crawler schema with the Engine's popularity column, the shared embeddings table, moderation and trending ranks."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    ensure_trending_schema(conn)
    for label in reversed(list(RANKS)):
        video_id, host, rank, likes, views, nsfw, errors, in_videos, embedded = RANKS[label]
        crawled = 100 if label == "N" else TRENDING_ORDER.index(label) + 1 if label in TRENDING_ORDER else 200
        if in_videos:
            conn.execute(
                "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, likes, views, nsfw, popularity, error_count, published_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (video_id, f"uuid-{label}", host, f"ch-{label}", crawled, 10 * crawled, nsfw, float(crawled), errors, 1_700_000_000_000),
            )
        if embedded:
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
        if rank is not None:
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, likes, views))
    conn.commit()
    return conn


# Runs under the Engine interpreter, which the mixer's imports need. The popular layer is the real generator over the real fetch_popular_videos on a temp DB; the other layers stand in for generators whose output size is the mixer's input, each returning `limit` distinct rows on h.example.
_MIX_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import server_config
    from data.random_videos import fetch_popular_videos
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator
    from recommendations.keys import like_key
    from recommendations.mixer import MixerDeps, MixingRecommendationStrategy

    class Layer:
        def __init__(self, name):
            self.name = name

        def get_candidates(self, server, user_id, limit, refresh_cache=False, config=None):
            return [{"video_id": f"{self.name}-{i}", "instance_domain": "h.example", "channel_id": f"{self.name}-ch-{i}", "views": 10, "likes": 1, "published_at": 1700000000000, "similarity_score": 0.5} for i in range(limit)]

    likes = [{"video_id": "liked-1", "instance_domain": "h.example"}]
    out = {}
    for case, (with_likes, db_path) in json.loads(sys.argv[3]).items():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        server = types.SimpleNamespace(db=db, db_lock=threading.Lock())
        recent_likes = lambda user_id, limit, w=with_likes: list(likes) if w else []
        popular = PopularVideosGenerator(PopularVideosDeps(fetch_popular_videos=fetch_popular_videos, fetch_recent_likes=recent_likes, fetch_embeddings_by_ids=lambda conn, rows: {}, like_key=like_key, max_likes=50))
        layers = {name: Layer(name) for name in ("random", "explore", "exploit", "fresh")}
        layers["popular"] = popular
        deps = MixerDeps(like_key=like_key, fetch_recent_likes=recent_likes, max_likes=50, fetch_embeddings_by_ids=lambda server, rows: {}, fetch_dislike_centroids=lambda: None, fetch_excluded_keys=set, dislike_similarity_floor=0.0)
        rows = MixingRecommendationStrategy(layers, server_config.RECOMMENDATION_PIPELINE, deps).generate_recommendations(server, "u", 0, mode="home")
        out[case] = {"count": len(rows), "distinct": len({like_key(r) for r in rows}), "popular_served": sum(1 for r in rows if r["instance_domain"] != "h.example")}
        db.close()
    print(json.dumps(out))
    """
)


def test_the_mix_answers_with_an_empty_popular_layer_full_for_guests_and_short_by_popular_s_share_with_likes(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    ranked = str(tmp_path / "ranks.db")
    _ranks_db(Path(ranked)).close()
    empty = str(tmp_path / "empty.db")
    emptied = _ranks_db(Path(empty))
    emptied.execute("DELETE FROM trending_ranks")
    emptied.commit()
    # Control: the emptied DB still serves its catalogue, so a popular layer with nothing to serve is the empty ranks and not an empty DB.
    assert len(random_videos.fetch_ordered_page(emptied, "popular", 100, 0)) == 11
    emptied.close()
    cases = {"guest_empty": [False, empty], "home_empty": [True, empty], "home_full": [True, ranked]}
    run = subprocess.run([str(ENGINE_PY), "-c", _MIX_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    # Control: with likes and ranked rows the home batch is full and the real popular layer fills its 5 gathered slots.
    assert out["home_full"] == {"count": 48, "distinct": 48, "popular_served": 5}, out["home_full"]
    assert out["home_empty"]["popular_served"] == 0, out["home_empty"]  # an empty ranks table gives the popular layer an empty pool, though the catalogue holds rows
    assert out["home_empty"]["count"] == out["home_empty"]["distinct"] == 48 - 5, out["home_empty"]  # non-empty, short by exactly popular's share
    assert out["guest_empty"] == {"count": 48, "distinct": 48, "popular_served": 0}, out["guest_empty"]  # an empty pool still gives guests a full batch
