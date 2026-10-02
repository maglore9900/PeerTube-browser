"""A profile's dislikes on the Client backend: the actions, the key rule and its up-next pages.

- The profile's reaction to a video reads back like, dislike, undo_dislike, and a like that
  replaces a dislike; another video's reaction is its own.
- A dislike with no key or an unknown key is refused with 401, where the profile's key is
  accepted.
- A disliked video is absent from the profile's up-next page on `/recommendations` and `/videos/similar`, which stays the requested size, while the keyless page and another profile's page for the same request contain it.
- The profile's up-next page leans away from its disliked video: its leading other rows are less similar to it than the keyless page's, and lean away from it more than the page of a profile that dislikes a different video.

Each up-next page is pinned with `exclude` to a fixed set of the seed's pool (conftest `pin_upnext`), so it is served whole in penalised order, not drawn.

Every test runs the Client in `unpublished_client` mode, so no Like/UndoLike reaches the
repo's live whitelist.db.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

import pytest

from conftest import closeness, cosine, embedding_of, pin_upnext, upnext_pool

UNKNOWN_KEY = "A" * 43  # the shape a minted key has, issued to nobody
# Seeds whose up-next pool is deeper than one page plus one, which the absent/present test checks.
SEEDS = ("linux", "football")
ROUTES = ("/recommendations", "/videos/similar")
PAGE = 16
LEADING = 8


def _videos(dataset, n: int) -> list[dict]:
    """n embedded, error-free videos from different channels, which the Engine resolves."""
    rows = dataset.execute(
        "SELECT v.video_uuid, v.instance_domain FROM videos v JOIN video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 GROUP BY v.channel_id, v.instance_domain ORDER BY v.rowid LIMIT ?",
        (n,),
    ).fetchall()
    assert len(rows) == n
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in rows]


def _mint(client) -> dict[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return {"X-Profile-Key": body["key"]}


def _act(client, headers, action: str, video: dict) -> int:
    status, _ = client.request("POST", "/api/user-action", headers=headers,
                               body={"action": action, **video})
    return status


def _reaction(client, headers, video: dict) -> tuple[int, bool | None, bool | None]:
    status, body = client.request("GET", f"/api/profile/reaction?{urlencode(video)}", headers=headers)
    if status != 200:
        return status, None, None
    return status, body["liked"], body["disliked"]


# --- actions ------------------------------------------------------------------------------


def test_a_video_s_reaction_follows_like_dislike_undo_dislike_and_a_like_replacing_a_dislike(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    video, other = _videos(dataset, 2)

    _act(client, key, "like", video)
    assert _reaction(client, key, video) == (200, True, False)
    # 502: this dislike removes a like, so it publishes UndoLike, which this Client cannot send.
    assert _act(client, key, "dislike", video) in (200, 502)
    assert _reaction(client, key, video) == (200, False, True)
    _act(client, key, "like", other)
    assert _reaction(client, key, other) == (200, True, False)
    assert _reaction(client, key, video) == (200, False, True)
    assert _act(client, key, "undo_dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, False)
    assert _act(client, key, "dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, True)
    _act(client, key, "like", video)
    assert _reaction(client, key, video) == (200, True, False)


def test_a_dislike_without_a_valid_key_is_refused_where_the_profile_s_key_is_accepted(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    (video,) = _videos(dataset, 1)
    assert _act(client, {}, "dislike", video) == 401
    assert _act(client, {"X-Profile-Key": UNKNOWN_KEY}, "dislike", video) == 401
    assert _act(client, key, "dislike", video) == 200
    assert _reaction(client, key, video) == (200, False, True)


# --- up-next ------------------------------------------------------------------------------


def _seed(client, query: str) -> dict:
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _upnext(client, route: str, seed: dict, headers: dict | None = None, body: dict | None = None) -> list[dict]:
    status, payload = client.request(
        "POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE}",
        headers=headers, body=body or {})
    assert status == 200, payload
    return payload["rows"]


def _pin(engine, route: str, seed: dict, rows: list[dict]) -> dict:
    """The up-next body pinning a page to these rows of the seed's pool."""
    return {"exclude": pin_upnext(engine, route, seed, rows)}


def _keys(rows) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _profile_disliking(client, video: dict) -> dict[str, str]:
    key = _mint(client)
    status, body = client.request("POST", "/api/user-action", headers=key, body={
        "action": "dislike", "uuid": video["video_uuid"], "host": video["instance_domain"]})
    assert status == 200, body
    return key


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("query", SEEDS)
def test_a_disliked_video_is_absent_from_the_profile_s_full_upnext_page_and_present_for_others(
        unpublished_client, engine, route, query):
    client = unpublished_client
    seed = _seed(client, query)
    pool = upnext_pool(engine, route, seed)
    assert len(pool) > PAGE + 1, f"control: {query}'s {route} pool holds {len(pool)} rows"
    pin16 = _pin(engine, route, seed, pool[:PAGE])
    pin17 = _pin(engine, route, seed, pool[:PAGE + 1])
    keyless = _upnext(client, route, seed, body=pin16)
    assert _keys(keyless) == _keys(pool[:PAGE])  # control: the pinned keyless page is the pool's first 16
    disliked = keyless[PAGE // 2]
    key = _profile_disliking(client, disliked)
    bystander = _profile_disliking(client, keyless[0])
    # The Client asks for 32, the Engine serves the 17 pinned rows whole, and the Client drops the disliked one.
    page = _upnext(client, route, seed, key, pin17)
    assert _keys(page) == _keys(pool[:PAGE + 1]) - _keys([disliked])
    assert len(page) == PAGE
    # Under the 16-row pin no row is cut to fit the page, so the absence is the Client's filter, not the centroid ranking the row 17th.
    assert _keys(_upnext(client, route, seed, key, pin16)) == _keys(keyless) - _keys([disliked])
    assert _keys([disliked]) <= _keys(_upnext(client, route, seed, body=pin16))
    assert _keys([disliked]) <= _keys(_upnext(client, route, seed, bystander, pin16))


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
def test_a_profile_s_upnext_page_leans_away_from_its_disliked_video(unpublished_client, engine, dataset, route, query):
    client = unpublished_client
    seed = _seed(client, query)
    pool = upnext_pool(engine, route, seed)
    # One pinned set on all three pages, so they differ only in the order the dislike penalty gives it.
    pin16 = _pin(engine, route, seed, pool[:PAGE])
    keyless = _upnext(client, route, seed, body=pin16)
    assert _keys(keyless) == _keys(pool[:PAGE])  # control: the pinned keyless page is the pool's first 16
    d1, d2 = _pair(dataset, keyless)
    page_d1 = _upnext(client, route, seed, _profile_disliking(client, d1), pin16)
    page_d2 = _upnext(client, route, seed, _profile_disliking(client, d2), pin16)
    assert (closeness(dataset, _leading_others(page_d1, d1, d2), d1)
            < closeness(dataset, _leading_others(keyless, d1, d2), d1))
    assert (closeness(dataset, _leading_others(page_d2, d1, d2), d2)
            < closeness(dataset, _leading_others(keyless, d1, d2), d2))
    assert _margin(dataset, page_d1, d1, d2) < _margin(dataset, page_d2, d1, d2)
