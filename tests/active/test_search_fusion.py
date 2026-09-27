"""Weighted reciprocal-rank fusion in hybrid search.

- Each half's rank term is multiplied by its weight: with the default 0.3 keyword / 0.7
  vector, a video only the vector half ranks first outranks one only the keyword half ranks
  first, and keyword rank 1 is worth about vector rank 82.
- Weights of 1.0 each give the plain unweighted fusion.
- `SEARCH_WEIGHT_LEXICAL` / `SEARCH_WEIGHT_VECTOR` override the defaults; a negative, non-
  numeric or non-finite value stops the Engine instead of being used.

`data.search` imports numpy, which only the Engine's environment has, so each check runs in
a child on the Engine's interpreter and reports back as JSON.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
K = 60

_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    from data.search import fuse_by_rank
    import server_config

    def rows(ids):
        return [{"video_id": i, "instance_domain": "example.org"} for i in ids]

    case = json.loads(sys.argv[2])
    if case["op"] == "fuse":
        args = [rows(case["lexical"]), rows(case["vector"]), case["k"], *case.get("weights", [])]
        fused = fuse_by_rank(*args)
        out = [[r["video_id"], r["search_score"], r["search_sources"]] for r in fused]
    elif case["op"] == "defaults":
        out = [server_config.SEARCH_WEIGHT_LEXICAL, server_config.SEARCH_WEIGHT_VECTOR]
    print(json.dumps(out))
    """
)


def _child(case: dict, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("SEARCH_WEIGHT_")}
    child_env.update(env or {})
    return subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), json.dumps(case)],
                          capture_output=True, text=True, timeout=120, env=child_env)


def _run(case: dict, env: dict[str, str] | None = None):
    proc = _child(case, env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _fuse(lexical: list[str], vector: list[str], *weights: float) -> list[list]:
    return _run({"op": "fuse", "lexical": lexical, "vector": vector, "k": K, "weights": list(weights)})


def _scores(fused: list[list]) -> dict[str, float]:
    return {video_id: score for video_id, score, _sources in fused}


def test_the_default_weights_are_0_3_keyword_and_0_7_vector():
    assert _run({"op": "defaults"}) == [0.3, 0.7]


def test_weight_env_values_override_the_defaults_and_blank_keeps_them():
    assert _run({"op": "defaults"}, {"SEARCH_WEIGHT_LEXICAL": "0.5", "SEARCH_WEIGHT_VECTOR": "1"}) == [0.5, 1.0]
    assert _run({"op": "defaults"}, {"SEARCH_WEIGHT_LEXICAL": "0"}) == [0.0, 0.7]  # a half can be switched off
    assert _run({"op": "defaults"}, {"SEARCH_WEIGHT_LEXICAL": " "}) == [0.3, 0.7]


@pytest.mark.parametrize("raw", ["-0.1", "abc", "inf", "nan"])
def test_a_negative_non_numeric_or_non_finite_weight_stops_the_engine(raw):
    proc = _child({"op": "defaults"}, {"SEARCH_WEIGHT_VECTOR": raw})
    assert proc.returncode != 0
    assert "SEARCH_WEIGHT_VECTOR must be a non-negative number" in proc.stderr
    assert proc.stdout == ""  # nothing was served with the bad value


def test_with_default_weights_a_vector_only_first_outranks_a_keyword_only_first():
    fused = _fuse(["kw"], ["vec"], 0.3, 0.7)

    assert [video_id for video_id, _s, _src in fused] == ["vec", "kw"]
    assert _scores(fused) == pytest.approx({"kw": 0.3 / 61, "vec": 0.7 / 61})


def test_keyword_rank_1_is_worth_about_vector_rank_82_at_default_weights():
    scores = _scores(_fuse(["kw"], [f"v{rank}" for rank in range(1, 101)], 0.3, 0.7))

    assert scores["v81"] > scores["kw"] > scores["v83"]


def test_a_video_in_both_halves_scores_the_sum_of_its_weighted_terms():
    fused = _fuse(["a", "both"], ["both"], 0.3, 0.7)

    assert _scores(fused)["both"] == pytest.approx(0.3 / 62 + 0.7 / 61)
    assert fused[0][0] == "both" and fused[0][2] == ["lexical", "vector"]


def test_weights_of_one_give_the_unweighted_fusion():
    lexical, vector = ["a", "b", "c"], ["c", "d", "a"]

    weighted = _scores(_fuse(lexical, vector, 1.0, 1.0))
    assert weighted == pytest.approx({"a": 1 / 61 + 1 / 63, "b": 1 / 62, "c": 1 / 63 + 1 / 61, "d": 1 / 62})
    assert weighted == pytest.approx(_scores(_fuse(lexical, vector)))  # the parameters' defaults
