"""The Engine turns disliked videos into taste centroids.

- `/internal/dislikes/centroids` returns min(4, n) unit-length centroids, and for n <= 4 each
  disliked video's embedding is one of them.
"""
from __future__ import annotations

import pytest

from conftest import BRIDGE_HEADERS, cosine, embedding_of


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
