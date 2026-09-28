"""Up-next's sampled page, checked against the session Engine.

- Ten unseeded POST /recommendations?id=…&host=…&limit=8&debug=1 requests for the linux seed each return 8 distinct rows, every row's debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE, and the mean pairwise Jaccard of their key sets is below 0.5.
- The same request with &seed=11, sent twice, returns 8 rows in the same order both times, and with &seed=12 returns a different ordered page.
"""
from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ROOT, engine  # noqa: E402,F401

SERVER_CONFIG = ROOT / "engine" / "server" / "api" / "server_config.py"
PAGE_LIMIT = 8
REFRESHES = 10
MAX_MEAN_JACCARD = 0.5
# Its own rate-limit bucket: the session Engine allows 60 /recommendations requests a minute per client IP, and other tests share 127.0.0.1's.
HEADERS = {"X-Client-IP": "192.0.2.109"}


def _config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(engine, query: str) -> dict:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _page(engine, path: str) -> list[dict]:
    status, body = engine.request("POST", path, headers=HEADERS, body={})
    assert status == 200, body
    return body["rows"]


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _mean_jaccard(sets: list[set]) -> float:
    pairs = list(itertools.combinations(sets, 2))
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


def test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor(engine):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    seed = _seed(engine, "linux")
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE_LIMIT}&debug=1"

    pages = [_page(engine, path) for _ in range(REFRESHES)]
    for rows in pages:
        assert len(rows) == PAGE_LIMIT, _keys(rows)  # C1
        assert len(set(_keys(rows))) == PAGE_LIMIT, _keys(rows)  # C1
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]  # C1
    # A fixed top-8 scores 1.0 here (observed before sampling); an ES draw of 8 from the observed top-32 scores, simulated offline, scored about 0.14.
    mean = _mean_jaccard([set(_keys(rows)) for rows in pages])
    assert mean < MAX_MEAN_JACCARD, (mean, [_keys(rows) for rows in pages])  # C1

    first = _page(engine, path + "&seed=11")
    second = _page(engine, path + "&seed=11")
    assert len(first) == PAGE_LIMIT, _keys(first)  # C2
    assert _keys(first) == _keys(second)  # C2
    # A seed that fixed the page without steering the draw, such as one falling back to the ranked top-8, gives every seed the same page.
    other = _page(engine, path + "&seed=12")
    assert len(other) == PAGE_LIMIT, _keys(other)
    assert _keys(other) != _keys(first)  # C2
