"""Phase 1 checkpoint: the popular layer's likes path draws by similarity when `weighted_random_alpha` is positive.

- With likes and alpha 1.0 or 0.5, `limit` distinct candidates come back, the 0.9-similarity group outnumbers the 0.1 group (at least 3:1 at alpha 1.0, 2:1 at 0.5) while the 0.1 group still appears, and zero-weight candidates (0.0, negative, missing embedding) appear only to fill a shortfall, spread over every one of them.
- With alpha missing, None, 0, -1.0 or NaN, or with every weight zero, each draw equals `random.sample(ordered, limit)` under the same seed, `ordered` being the pool sorted by similarity rather than the pool's own (low-first) order.
- A pool of `limit` or fewer comes back whole.

`popular_videos` imports numpy, which only the Engine's environment has, so every case runs in one child on the Engine's interpreter, reseeded per trial, and reports back as JSON.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
LIMIT = 5

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
