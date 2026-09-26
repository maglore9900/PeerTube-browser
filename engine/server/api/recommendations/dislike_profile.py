"""A visitor's dislikes as a few taste centroids, and the ranking penalty they give.

The Engine keeps no user state: the Client asks for centroids when a visitor's dislikes
change, stores them, and sends them back with each feed request. Clustering keeps the
penalty sharp when dislikes span several topics, where a single mean would sit between them
and match nothing.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from recommendations.keys import like_key

MAX_CENTROIDS = 4
KMEANS_ITERATIONS = 20


def compute_centroids(vectors: np.ndarray, k: int = MAX_CENTROIDS) -> np.ndarray:
    """Cluster disliked-video embeddings into at most `k` unit-length centroids.

    Initialisation is farthest-point from the first row, so the same input always gives the
    same centroids. With `n <= k` every vector is its own centroid.

    :param vectors: One embedding per row, shape (n, dim), n >= 1.
    :returns: Array of shape (min(k, n), dim).
    """
    points = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    k = min(k, len(points))
    chosen = [0]
    while len(chosen) < k:
        nearest = np.max(points @ points[chosen].T, axis=1)
        chosen.append(int(np.argmin(nearest)))
    centroids = points[chosen].copy()
    for _ in range(KMEANS_ITERATIONS):
        labels = np.argmax(points @ centroids.T, axis=1)
        for index in range(k):
            members = points[labels == index]
            if len(members):
                mean = members.mean(axis=0)
                centroids[index] = mean / np.linalg.norm(mean)
    return centroids


def apply_dislike_penalty(
    server: Any,
    candidates: list[dict[str, Any]],
    centroids: np.ndarray | None,
    weight: float,
    fetch_embeddings_by_ids: Callable[[Any, list[dict[str, Any]]], dict[str, np.ndarray]],
    floor: float,
) -> None:
    """Lower each candidate's `score` by `weight` × its best cosine to a centroid.

    Candidates below `floor` are untouched, as are all of them when there are no centroids.
    The penalty is recorded on the candidate as `dislike_penalty` so a later re-rank can
    keep it.
    """
    if centroids is None or not candidates:
        return
    with server.db_lock:
        embeddings = fetch_embeddings_by_ids(server.db, candidates)
    for candidate in candidates:
        vector = embeddings.get(like_key(candidate))
        if vector is None:
            continue
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            continue
        similarity = float(np.max(centroids @ (vector / norm)))
        if similarity < floor:
            continue
        penalty = weight * similarity
        candidate["dislike_penalty"] = penalty
        candidate["score"] = float(candidate.get("score") or 0.0) - penalty
