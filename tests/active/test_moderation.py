"""`purge_similarity_for_host` on the compact similarity cache: a host leaves as a source and as a neighbour, the rest keeps its rank order, and the counts are the ones the row-per-neighbour purge reported for the same content.

- Purging bad.example deletes b1 and b2 (one with neighbours, one without), removes its videos from s1 (ranks 1 and 3), s3 (last) and s4 (its only neighbour), renumbers the survivors in rank order, leaves s2 untouched, deletes bad.example's `video_keys` rows, adds no index, and returns {similarity_items: 6, similarity_sources: 2}.
- On the same content `collect_similarity_host_stats` reports as_source 2, as_similar 5, total mentions 7; a host with no keys purges to zeros and changes nothing; an empty host raises `ValueError`.

The expected counts are those the legacy purge returned for the same content in the old row-per-neighbour layout (observed when the compact layout was introduced). Runs in-process on temporary files.

`purge_host_data` removes a host's trending ranks with its other rows:

- On a DB holding a.example's two `trending_ranks` rows and one embedding, and b.example's one of each, `purge_host_data(conn, "a.example")` deletes a.example's rank rows, reports them as `trending_ranks: 2`, and leaves b.example's. a.example's `video_embeddings` row goes too, counted as `video_embeddings: 1`, while b.example's stays. The rows are seeded directly through `data.trending.ensure_trending_schema` and `data.ann_ids.create_video_embeddings_table`.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.ann_ids import create_video_embeddings_table  # noqa: E402
from data.db import connect_similarity_db  # noqa: E402
from data.moderation import collect_similarity_host_stats, purge_host_data, purge_similarity_for_host  # noqa: E402
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

A = "a.example"
BAD = "bad.example"


def _e(video_id: str, domain: str, score: float, rank: int) -> dict:
    return {"video_id": video_id, "instance_domain": domain, "score": score, "rank": rank}


def _cache(path: Path) -> None:
    """s1@a holds bad videos at ranks 1 and 3 between a.example ones; s2@a holds none; s3@a holds one last; s4@a holds only a bad one; b1@bad holds one of each; b2@bad holds nothing."""
    conn = connect_similarity_db(path)
    ensure_similarity_schema(conn)
    store_similarity_cache(conn, {"video_id": "s1", "instance_domain": A}, [_e("x1", BAD, 0.875, 1), _e("n1", A, 0.75, 2), _e("x2", BAD, 0.625, 3), _e("n2", A, 0.5, 4)], 1)
    store_similarity_cache(conn, {"video_id": "s2", "instance_domain": A}, [_e("n1", A, 0.5, 1)], 1)
    store_similarity_cache(conn, {"video_id": "s3", "instance_domain": A}, [_e("n1", A, 0.75, 1), _e("x1", BAD, 0.5, 2)], 1)
    store_similarity_cache(conn, {"video_id": "s4", "instance_domain": A}, [_e("x2", BAD, 0.5, 1)], 1)
    store_similarity_cache(conn, {"video_id": "b1", "instance_domain": BAD}, [_e("n1", A, 0.75, 1), _e("x1", BAD, 0.5, 2)], 1)
    store_similarity_cache(conn, {"video_id": "b2", "instance_domain": BAD}, [], 1)
    conn.close()


def _read(conn: sqlite3.Connection, video_id: str, domain: str) -> list[dict]:
    return fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, 1000)


def _source_keys(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    # rung 3: fetch_cached_similarities answers [] for an empty source and a missing one alike, so only the stored rows show b2@bad is gone.
    # connect_similarity_db sets sqlite3.Row, which neither sorts nor equals a tuple.
    return sorted(tuple(row) for row in conn.execute("SELECT k.video_id, k.instance_domain FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key"))


def test_purge_removes_a_host_as_source_and_as_neighbour_with_legacy_counts(tmp_path: Path) -> None:
    """Purging bad.example drops b1 and b2, leaves s1 and s3 their a.example neighbours in rank order, s4 with none and s2 untouched, leaves no bad.example key and no per-domain index, and returns the legacy counts; on the same content the stats match the legacy stats, a host with no keys returns zeros and changes nothing, and an empty host is refused."""
    path = tmp_path / "cache.db"
    _cache(path)
    conn = connect_similarity_db(path)
    assert purge_similarity_for_host(conn, BAD) == {"similarity_items": 6, "similarity_sources": 2}
    assert _read(conn, "s1", A) == [_e("n1", A, 0.75, 1), _e("n2", A, 0.5, 2)]
    assert _read(conn, "s3", A) == [_e("n1", A, 0.75, 1)]
    assert _read(conn, "s4", A) == []
    assert _read(conn, "s2", A) == [_e("n1", A, 0.5, 1)]
    assert _source_keys(conn) == [("s1", A), ("s2", A), ("s3", A), ("s4", A)]
    # rung 3: no production read lists keys by host; the purge must leave none for bad.example.
    assert conn.execute("SELECT COUNT(*) FROM video_keys WHERE instance_domain = ?", (BAD,)).fetchone()[0] == 0
    # rung 3: the claim is about what the file holds — no per-domain index beyond the schema's own.
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex%'")} == {"video_keys_instance_domain_idx"}
    conn.close()

    # On a fresh copy of the same content: the stats the CLI logs, and a host with no keys.
    other = tmp_path / "other.db"
    _cache(other)
    conn = connect_similarity_db(other)
    assert collect_similarity_host_stats(conn, BAD) == {"similarity_items": 6, "similarity_sources": 2, "similarity_items_as_source": 2, "similarity_items_as_similar": 5, "similarity_items_total_mentions": 7}
    assert purge_similarity_for_host(conn, "nokeys.example") == {"similarity_items": 0, "similarity_sources": 0}
    assert _read(conn, "s1", A) == [_e("x1", BAD, 0.875, 1), _e("n1", A, 0.75, 2), _e("x2", BAD, 0.625, 3), _e("n2", A, 0.5, 4)]
    assert _read(conn, "s2", A) == [_e("n1", A, 0.5, 1)]
    assert _read(conn, "b1", BAD) == [_e("n1", A, 0.75, 1), _e("x1", BAD, 0.5, 2)]
    assert _source_keys(conn) == [("b1", BAD), ("b2", BAD), ("s1", A), ("s2", A), ("s3", A), ("s4", A)]
    with pytest.raises(ValueError):
        purge_similarity_for_host(conn, "")
    conn.close()


T0 = 1_760_000_000_000


def _trending_rows(conn: sqlite3.Connection, host: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute("SELECT video_id, rank, likes, views, fetched_at FROM trending_ranks WHERE instance_domain = ? ORDER BY rank", (host,))]


def _ranks_and_embeddings(path: Path) -> sqlite3.Connection:
    """a.example ranks a-1 and a-2 and embeds a-v1; b.example ranks b-1 and embeds b-v1."""
    conn = sqlite3.connect(path)
    create_video_embeddings_table(conn)
    ensure_trending_schema(conn)
    conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, x'00', 1, 'm', 't', ?)", [("a-v1", "a.example", 1), ("b-v1", "b.example", 2)])
    conn.executemany("INSERT INTO trending_ranks (instance_domain, video_id, rank, likes, views, fetched_at) VALUES (?, ?, ?, 0, 0, ?)", [("a.example", "a-1", 1, T0), ("a.example", "a-2", 2, T0), ("b.example", "b-1", 1, T0)])
    conn.commit()
    return conn


def test_purge_host_data_deletes_and_counts_the_host_s_trending_rows(tmp_path: Path) -> None:
    """`purge_host_data` deletes the purged host's rank rows, counts them under `trending_ranks`, and leaves another host's; its `video_embeddings` row still goes with them."""
    conn = _ranks_and_embeddings(tmp_path / "whitelist.db")
    # Control: a.example has rows for the purge to remove.
    assert len(_trending_rows(conn, "a.example")) == 2

    counts = purge_host_data(conn, "a.example")

    assert counts["trending_ranks"] == 2
    assert _trending_rows(conn, "a.example") == []
    assert _trending_rows(conn, "b.example") == [("b-1", 1, 0, 0, T0)]
    # The rank delete joins the existing ones rather than replacing them: a.example's embedding goes and is counted, b.example's stays.
    assert counts["video_embeddings"] == 1
    assert [row[0] for row in conn.execute("SELECT video_id FROM video_embeddings ORDER BY video_id")] == ["b-v1"]
