"""The Engine turns disliked videos into taste centroids.

- `/internal/dislikes/centroids` returns min(4, n) unit-length centroids, and for n <= 4 each
  disliked video's embedding is one of them.
- An up-next request carrying the centroid of a disliked video returns a page whose leading other rows are less similar to that video than the same request without it, both drawn with the same `seed`; home requests carrying it place the videos clearly similar to that video lower on the page, on average, for a pair chosen so that each has a clearly similar row on every plain home page.
- In both, a page carrying one of two dislikes leans away from it, relative to the other, more than a page carrying the other.
"""
from __future__ import annotations

from statistics import mean
from urllib.parse import quote

import pytest

from conftest import BRIDGE_HEADERS, closeness, cosine, embedding_of

SEED_QUERIES = ("cooking", "linux")
HOME_DRAWS = 5
UPNEXT_LEADING = 8
# Above the 99th percentile of cosine between random videos in this corpus (0.59, measured).
CLEARLY_SIMILAR = 0.6
# One fixed draw for every up-next request, so pages with and without a centroid are the same draw.
DRAW_SEED = 7
# Their own Engine rate bucket: these tests send about 40 requests to /recommendations.
DRAW_HEADERS = {"X-Client-IP": "192.0.2.157"}


def _distinct_videos(dataset, n: int) -> list[dict]:
    """n embedded videos from different channels, no two with the same embedding."""
    rows = dataset.execute(
        "SELECT v.video_id, v.instance_domain FROM videos v JOIN video_embeddings e "
        "ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "GROUP BY v.channel_id, v.instance_domain ORDER BY v.rowid LIMIT ?",
        (n,),
    ).fetchall()
    entries = [{"video_id": r["video_id"], "instance_domain": r["instance_domain"]} for r in rows]
    vecs = [embedding_of(dataset, e["video_id"], e["instance_domain"]) for e in entries]
    assert len(entries) == n
    assert all(cosine(vecs[i], vecs[j]) < 0.999 for i in range(n) for j in range(i + 1, n))
    return entries


def _centroids(engine, entries):
    return engine.request("POST", "/internal/dislikes/centroids", headers=BRIDGE_HEADERS,
                          body={"entries": entries})


@pytest.mark.parametrize("n", [1, 3, 4, 5, 6])
def test_centroids_are_min_4_n_unit_vectors_and_each_of_up_to_4_dislikes_is_one(engine, dataset, n):
    entries = _distinct_videos(dataset, n)
    status, body = _centroids(engine, entries)
    assert status == 200, body
    centroids = body["centroids"]
    assert len(centroids) == min(4, n)
    for c in centroids:
        assert abs(sum(x * x for x in c) ** 0.5 - 1.0) < 1e-4
    if n <= 4:
        for e in entries:
            vec = embedding_of(dataset, e["video_id"], e["instance_domain"])
            assert max(cosine(vec, c) for c in centroids) > 0.9999


# --- centroids on up-next and home pages ---------------------------------------------------


def _space(dataset) -> str:
    return dataset.execute("SELECT model_name FROM video_embeddings LIMIT 1").fetchone()[0]


def _seed_and_pair(engine, dataset, query: str):
    """A seed, its seeded up-next path and plain page, and the least similar pair of rows on it."""
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1", headers=DRAW_HEADERS)
    assert status == 200 and body["rows"], body
    seed = body["rows"][0]
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=16&seed={DRAW_SEED}"
    status, plain = engine.request("POST", path, headers=DRAW_HEADERS, body={})
    assert status == 200 and len(plain["rows"]) == 16, plain
    rows = plain["rows"]
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    i, j = min(((i, j) for i in range(16) for j in range(i + 1, 16)),
               key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    assert cosine(vecs[i], vecs[j]) < 0.7
    return seed, path, rows, rows[i], rows[j]


def _centroid_body(dataset, disliked) -> dict:
    return {"space": _space(dataset),
            "vectors": [embedding_of(dataset, disliked["video_id"], disliked["instance_domain"])]}


def _others(rows, d1, d2, leading: int) -> list[dict]:
    """The first `leading` rows of a page other than the two disliked videos: what a visitor sees first is where "lower" shows."""
    return [r for r in rows if r["video_id"] not in (d1["video_id"], d2["video_id"])][:leading]


def _margin(dataset, rows, d1, d2, leading: int) -> float:
    """How much closer a page's leading other rows are to d1 than to d2."""
    others = _others(rows, d1, d2, leading)
    return closeness(dataset, others, d1) - closeness(dataset, others, d2)


@pytest.mark.parametrize("query", SEED_QUERIES)
def test_an_upnext_page_carrying_a_dislike_centroid_moves_away_from_that_disliked_video(
        engine, dataset, query):
    _, path, plain, d1, d2 = _seed_and_pair(engine, dataset, query)
    pages = {}
    for own in (d1, d2):
        status, body = engine.request("POST", path, headers=DRAW_HEADERS, body={"dislike_centroids": _centroid_body(dataset, own)})
        assert status == 200 and len(body["rows"]) == 16, body
        pages[own["video_id"]] = body["rows"]
        assert (closeness(dataset, _others(body["rows"], d1, d2, UPNEXT_LEADING), own)
                < closeness(dataset, _others(plain, d1, d2, UPNEXT_LEADING), own))
    assert (_margin(dataset, pages[d1["video_id"]], d1, d2, UPNEXT_LEADING)
            < _margin(dataset, pages[d2["video_id"]], d1, d2, UPNEXT_LEADING))


def _position(dataset, rows, d1, d2, own) -> float:
    """Mean page position of the rows, other than the two dislikes, clearly similar to `own`; a page holding none has pushed them all below itself, which counts as its length."""
    target = embedding_of(dataset, own["video_id"], own["instance_domain"])
    positions = [p for p, r in enumerate(rows)
                 if r["video_id"] not in (d1["video_id"], d2["video_id"])
                 and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR]
    return sum(positions) / len(positions) if positions else float(len(rows))


def _similar_ids(dataset, rows, video) -> set[str]:
    """The video_ids on a page, other than the video itself, clearly similar to it."""
    target = embedding_of(dataset, video["video_id"], video["instance_domain"])
    return {r["video_id"] for r in rows if r["video_id"] != video["video_id"]
            and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR}


def _covered_pair(dataset, rows, plain_pages) -> tuple[dict, dict]:
    """The least similar pair on the up-next page, under cosine 0.7, each with a row other than the pair clearly similar to it on every plain home page."""
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    near = [[_similar_ids(dataset, page, r) for page in plain_pages] for r in rows]
    pairs = sorted(((i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))),
                   key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    for i, j in pairs:
        if cosine(vecs[i], vecs[j]) >= 0.7:
            break
        pair = {rows[i]["video_id"], rows[j]["video_id"]}
        if all(ids - pair for k in (i, j) for ids in near[k]):
            return rows[i], rows[j]
    pytest.fail("control: no pair under cosine 0.7 on the seeded up-next page has a clearly similar row on every plain home page")


@pytest.mark.parametrize("query", SEED_QUERIES)
def test_home_pages_carrying_a_dislike_centroid_place_videos_similar_to_it_lower(
        engine, dataset, query):
    seed, _, upnext, _, _ = _seed_and_pair(engine, dataset, query)
    likes = [{"uuid": seed["video_uuid"], "host": seed["instance_domain"]}]

    def home(extra: dict) -> list[dict]:
        status, body = engine.request("POST", "/recommendations", headers=DRAW_HEADERS, body={"likes": likes, **extra})
        assert status == 200 and body["rows"], body
        return body["rows"]

    # Home takes no draw seed and its pages differ request to request, so the pair is chosen on the very plain pages compared below.
    plain = [home({}) for _ in range(HOME_DRAWS)]
    d1, d2 = _covered_pair(dataset, upnext, plain)
    before = {own["video_id"]: [_position(dataset, rows, d1, d2, own) for rows in plain] for own in (d1, d2)}
    for own in (d1, d2):
        # Control: every plain page holds a row clearly similar to it, so a shaped page has something to place lower.
        assert all(p < len(rows) for p, rows in zip(before[own["video_id"]], plain)), before[own["video_id"]]
    draws = {own["video_id"]: [home({"dislike_centroids": _centroid_body(dataset, own)}) for _ in range(HOME_DRAWS)]
             for own in (d1, d2)}
    for own in (d1, d2):
        shaped = [_position(dataset, rows, d1, d2, own) for rows in draws[own["video_id"]]]
        # Means, not extremes: single unseeded pages can overlap.
        assert mean(shaped) > mean(before[own["video_id"]]), (own["video_id"], shaped, before[own["video_id"]])
    lean_d1 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2)
               for rows in draws[d1["video_id"]]]
    lean_d2 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2)
               for rows in draws[d2["video_id"]]]
    assert mean(lean_d1) > mean(lean_d2), (lean_d1, lean_d2)
