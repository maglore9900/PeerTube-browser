"""Retired from `tests/active/test_dislikes.py` in build 09-similars-diversity (plan 19), step 8.

Both conflict with that build's phase 3 C1: an up-next page is now a random score-weighted draw from the top 4 x limit rows of the pool.

- The absent/present test takes `disliked = keyless[8]` from one unseeded 16-row draw and asserts it is present on fresh keyless and bystander draws (old lines 144-145), which fails or flakes.
- The lean-away test compares closeness across independent unseeded draws, so it measures the draw, not the dislike.

The pinned rewrite in plan §7f was never written; issue 35 tracks a replacement. Kept readable here. It depends on `_mint` from the active file and `closeness`, `cosine` and `embedding_of` from conftest, so a bare `pytest` run skips it.

The retired module docstring bullets read:

- A disliked video is absent from the profile's up-next page on `/recommendations` and
  `/videos/similar`, which stays the requested size, while the keyless page and another
  profile's page for the same request contain it.
- The profile's up-next page leans away from its disliked video: its leading other rows are
  less similar to it than the keyless page's, and lean away from it more than the page of a
  profile that dislikes a different video.
"""
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

# Seeds whose up-next pool is deeper than one page (19 and 18 rows, measured), so a page
# can lose a disliked video and still be full.
SEEDS = ("linux", "football")
ROUTES = ("/recommendations", "/videos/similar")
PAGE = 16
LEADING = 8


def _seed(client, query: str) -> dict:
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _upnext(client, route: str, seed: dict, headers: dict | None = None) -> list[dict]:
    status, body = client.request(
        "POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}",
        headers=headers, body={})
    assert status == 200, body
    return body["rows"]


def _profile_disliking(client, video: dict) -> dict[str, str]:
    key = _mint(client)
    status, body = client.request("POST", "/api/user-action", headers=key, body={
        "action": "dislike", "uuid": video["video_uuid"], "host": video["instance_domain"]})
    assert status == 200, body
    return key


def _ids(rows) -> list[str]:
    return [r["video_id"] for r in rows]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", SEEDS)
def test_a_disliked_video_is_absent_from_the_profile_s_full_upnext_page_and_present_for_others(
        unpublished_client, route, query):
    client = unpublished_client
    seed = _seed(client, query)
    keyless = _upnext(client, route, seed)
    assert len(keyless) == PAGE
    disliked = keyless[PAGE // 2]
    key = _profile_disliking(client, disliked)
    bystander = _profile_disliking(client, keyless[0])
    page = _upnext(client, route, seed, key)
    assert disliked["video_id"] not in _ids(page)
    assert len(page) == PAGE
    assert disliked["video_id"] in _ids(_upnext(client, route, seed))
    assert disliked["video_id"] in _ids(_upnext(client, route, seed, bystander))


def _pair(dataset, rows) -> tuple[dict, dict]:
    """The least similar pair of rows on a page."""
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    i, j = min(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))),
               key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    assert cosine(vecs[i], vecs[j]) < 0.7
    return rows[i], rows[j]


def _leading_others(rows, d1, d2) -> list[dict]:
    return [r for r in rows if r["video_id"] not in (d1["video_id"], d2["video_id"])][:LEADING]


def _margin(dataset, rows, d1, d2) -> float:
    others = _leading_others(rows, d1, d2)
    return closeness(dataset, others, d1) - closeness(dataset, others, d2)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", SEEDS)
def test_a_profile_s_upnext_page_leans_away_from_its_disliked_video(unpublished_client, dataset, route, query):
    client = unpublished_client
    seed = _seed(client, query)
    keyless = _upnext(client, route, seed)
    d1, d2 = _pair(dataset, keyless)
    page_d1 = _upnext(client, route, seed, _profile_disliking(client, d1))
    page_d2 = _upnext(client, route, seed, _profile_disliking(client, d2))
    assert (closeness(dataset, _leading_others(page_d1, d1, d2), d1)
            < closeness(dataset, _leading_others(keyless, d1, d2), d1))
    assert (closeness(dataset, _leading_others(page_d2, d1, d2), d2)
            < closeness(dataset, _leading_others(keyless, d1, d2), d2))
    assert _margin(dataset, page_d1, d1, d2) < _margin(dataset, page_d2, d1, d2)
