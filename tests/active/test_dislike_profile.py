"""The Engine turns disliked videos into taste centroids and ranks feeds away from them.

- `/internal/dislikes/centroids` returns min(4, n) unit-length centroids, and for n <= 4 each
  disliked video's embedding is one of them.
- An up-next request carrying the centroid of a disliked video returns a page whose leading
  other rows are less similar to that video than the same request without it; a home request
  carrying it places the videos clearly similar to that video lower on the page.
- In both, a page carrying one of two dislikes leans away from it, relative to the other, more
  than a page carrying the other.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest

from conftest import BRIDGE_HEADERS, closeness, cosine, embedding_of

SEED_QUERIES = ("cooking", "linux")
HOME_DRAWS = 5
UPNEXT_LEADING = 8
# Above the 99th percentile of cosine between random videos in this corpus (0.59, measured).
CLEARLY_SIMILAR = 0.6


def _space(dataset) -> str:
    return dataset.execute("SELECT model_name FROM video_embeddings LIMIT 1").fetchone()[0]


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


def _seed_and_pair(engine, dataset, query: str):
    """A seed, its up-next path and plain page, and the least similar pair of rows on it."""
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    seed = body["rows"][0]
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=16"
    status, plain = engine.request("POST", path, body={})
    assert status == 200 and len(plain["rows"]) == 16, plain
    rows = plain["rows"]
    vecs = [embedding_of(dataset, r["video_id"], r["instance_domain"]) for r in rows]
    i, j = min(((i, j) for i in range(16) for j in range(i + 1, 16)),
               key=lambda p: cosine(vecs[p[0]], vecs[p[1]]))
    assert cosine(vecs[i], vecs[j]) < 0.7
    return seed, path, plain["rows"], rows[i], rows[j]


def _centroid_body(dataset, disliked) -> dict:
    return {"space": _space(dataset),
            "vectors": [embedding_of(dataset, disliked["video_id"], disliked["instance_domain"])]}


def _others(rows, d1, d2, leading: int) -> list[dict]:
    """The first `leading` rows of a page other than the two disliked videos.

    Candidate pools are shallow (one video per channel), so a penalty mostly reorders the
    same set; what a visitor sees first is where "lower" shows.
    """
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
        status, body = engine.request("POST", path, body={"dislike_centroids": _centroid_body(dataset, own)})
        assert status == 200 and len(body["rows"]) == 16, body
        pages[own["video_id"]] = body["rows"]
        assert (closeness(dataset, _others(body["rows"], d1, d2, UPNEXT_LEADING), own)
                < closeness(dataset, _others(plain, d1, d2, UPNEXT_LEADING), own))
    assert (_margin(dataset, pages[d1["video_id"]], d1, d2, UPNEXT_LEADING)
            < _margin(dataset, pages[d2["video_id"]], d1, d2, UPNEXT_LEADING))


def _position(dataset, rows, d1, d2, own) -> float:
    """Mean page position of the rows, other than the two dislikes, clearly similar to `own`.

    A page holding none of them has pushed them all below itself, which counts as the page's
    length.
    """
    target = embedding_of(dataset, own["video_id"], own["instance_domain"])
    positions = [p for p, r in enumerate(rows)
                 if r["video_id"] not in (d1["video_id"], d2["video_id"])
                 and cosine(embedding_of(dataset, r["video_id"], r["instance_domain"]), target) >= CLEARLY_SIMILAR]
    return sum(positions) / len(positions) if positions else float(len(rows))


@pytest.mark.parametrize("query", SEED_QUERIES)
def test_home_pages_carrying_a_dislike_centroid_place_videos_similar_to_it_lower(
        engine, dataset, query):
    seed, _, _, d1, d2 = _seed_and_pair(engine, dataset, query)
    likes = [{"uuid": seed["video_uuid"], "host": seed["instance_domain"]}]
    draws = {"plain": [], d1["video_id"]: [], d2["video_id"]: []}
    for _ in range(HOME_DRAWS):
        for name, extra in (("plain", {}),
                            (d1["video_id"], {"dislike_centroids": _centroid_body(dataset, d1)}),
                            (d2["video_id"], {"dislike_centroids": _centroid_body(dataset, d2)})):
            status, body = engine.request("POST", "/recommendations", body={"likes": likes, **extra})
            assert status == 200 and body["rows"], body
            draws[name].append(body["rows"])
    for own in (d1, d2):
        plain = [_position(dataset, rows, d1, d2, own) for rows in draws["plain"]]
        assert all(p < len(rows) for p, rows in zip(plain, draws["plain"]))
        shaped = [_position(dataset, rows, d1, d2, own) for rows in draws[own["video_id"]]]
        assert min(shaped) > max(plain)
    lean_d1 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2)
               for rows in draws[d1["video_id"]]]
    lean_d2 = [_position(dataset, rows, d1, d2, d1) - _position(dataset, rows, d1, d2, d2)
               for rows in draws[d2["video_id"]]]
    assert min(lean_d1) > max(lean_d2)
