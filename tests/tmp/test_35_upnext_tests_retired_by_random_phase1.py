"""Checkpoint for plan 20-35 phase 1: pinning an up-next page with conftest's helpers, and an up-next page that excludes earlier rows, against the session Engine.

- For the linux seed on POST /recommendations and POST /videos/similar, `upnext_pool` returns distinct rows in non-increasing debug similarity_score order, more than 16 of them, and an unseeded limit=96 request excluding all of them is served no row. Under the exclude `pin_upnext` returns for the pool's first 5 rows, and again for its first 12, unseeded requests at limit equal to the head's length and at limit=16 are each served exactly that head's keys, where the same limit=16 request without it is served 16 rows.
- For the linux and cooking seeds, a POST /recommendations?id=…&host=…&limit=8&debug=1&seed=7 page, then the same request excluding that whole page and excluding every other row of it, each return 8 distinct rows, none of them excluded, every one with debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE (membership of the seed's pool).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

# The helpers are read off the module at call time, so the exclude test runs whether or not they exist yet.
import conftest  # noqa: E402
from conftest import engine  # noqa: E402,F401

SERVER_CONFIG = ROOT / "engine" / "server" / "api" / "server_config.py"
UPNEXT_PAGE = 8
# The Engine's limit cap, default_limit * 2.
LIST_LIMIT = 96
PIN_QUERY = "linux"
# Heads either side of the page size, so a pin_upnext that ignores the head it is given (say, always excluding pool[8:]) is wrong for both; an exclude of every pool row past 5 or 12 served exactly that head at limit == size and limit=16 on both routes (observed).
PIN_HEAD_SIZES = (5, 12)
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and conftest's helpers use 192.0.2.150.
PIN_HEADERS = {"X-Client-IP": "192.0.2.152"}
EXCLUDE_HEADERS = {"X-Client-IP": "192.0.2.151"}
# Seeds whose up-next pool runs to about 300 rows, far past a page plus its excluded rows.
UPNEXT_SEED_QUERIES = ("linux", "cooking")
EXCLUDE_DRAW_SEED = 7


def _config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _exclude(keys: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": video_id, "host": instance_domain} for video_id, instance_domain in keys]


def _seed(engine, query: str) -> dict:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _upnext_path(seed: dict, route: str, limit: int) -> str:
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}"


def _served(engine, path: str, body: dict) -> list[dict]:
    status, payload = engine.request("POST", path, headers=PIN_HEADERS, body=body)
    assert status == 200, payload
    return payload["rows"]


@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_an_unseeded_upnext_request_under_a_pin_is_served_exactly_the_chosen_head_of_the_listed_pool(engine, route):
    seed = _seed(engine, PIN_QUERY)
    pool = conftest.upnext_pool(engine, route, seed)
    scores = [r["debug"]["similarity_score"] for r in pool]
    assert scores == sorted(scores, reverse=True), scores  # C1
    assert len(set(_keys(pool))) == len(pool), len(pool) - len(set(_keys(pool)))  # C1
    # Past two pages, so a 16-row request has rows beyond the longest chosen head to serve; the linux pool listed 317–319 rows on both routes (observed).
    assert len(pool) > 2 * UPNEXT_PAGE, len(pool)  # C1
    # Control: unpinned, the seed is served a full 16-row page on this route, so the empty page below and the pinned pages after it are the exclude's doing.
    assert len(_served(engine, _upnext_path(seed, route, 2 * UPNEXT_PAGE), {})) == 2 * UPNEXT_PAGE
    # A head taken from a partial listing is not the pool's head: with every listed row excluded, nothing is left to serve (observed: 0 rows; excluding only the first 96 listed still served 96).
    assert _served(engine, _upnext_path(seed, route, LIST_LIMIT), {"exclude": _exclude(_keys(pool))}) == []  # C1

    for size in PIN_HEAD_SIZES:
        head = pool[:size]
        exclude = conftest.pin_upnext(engine, route, seed, head)
        for limit in (size, 2 * UPNEXT_PAGE):
            rows = _served(engine, _upnext_path(seed, route, limit), {"exclude": exclude})
            # Sorted lists, not sets, so a repeated row is not hidden.
            assert sorted(_keys(rows)) == sorted(_keys(head)), (size, limit, _keys(rows), _keys(head))  # C1


@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    path = _upnext_path(_seed(engine, query), "/recommendations", UPNEXT_PAGE) + f"&debug=1&seed={EXCLUDE_DRAW_SEED}"
    status, first = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _keys(first["rows"])
    assert len(set(previous)) == UPNEXT_PAGE, previous  # C2
    # Observed reference pages scored 0.686–0.822 (linux) and 0.55–0.61 (cooking), all above the 0.25 floor.
    assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in first["rows"]), [r["debug"]["similarity_score"] for r in first["rows"]]  # C2
    # Control: the seeded draw repeats, so a request ignoring exclude would serve every excluded row again (observed equal for both seeds).
    status, again = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={})
    assert status == 200 and _keys(again["rows"]) == previous, (previous, _keys(again["rows"]))

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        status, page = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={"exclude": _exclude(excluded)})
        assert status == 200, page
        rows = page["rows"]
        assert len(rows) == UPNEXT_PAGE and len(set(_keys(rows))) == UPNEXT_PAGE, (excluded, _keys(rows))  # C2
        assert not set(_keys(rows)) & set(excluded), sorted(set(_keys(rows)) & set(excluded))  # C2
        # Nothing under the tail floor (0.25) is in a seed's pool; observed pages sat at or above 0.545 (cooking) and 0.747 (linux).
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]  # C2
