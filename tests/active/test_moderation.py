"""`purge_similarity_for_host` on the compact similarity cache: a host leaves as a source and as a neighbour, the rest keeps its rank order, and the counts are the ones the row-per-neighbour purge reported for the same content.

- Purging bad.example deletes b1 and b2 (one with neighbours, one without), removes its videos from s1 (ranks 1 and 3), s3 (last) and s4 (its only neighbour), renumbers the survivors in rank order, leaves s2 untouched, deletes bad.example's `video_keys` rows, adds no index, and returns {similarity_items: 6, similarity_sources: 2}.
- On the same content `collect_similarity_host_stats` reports as_source 2, as_similar 5, total mentions 7; a host with no keys purges to zeros and changes nothing; an empty host raises `ValueError`.

The expected counts are those the legacy purge returned for the same content in the old row-per-neighbour layout (observed when the compact layout was introduced). Runs in-process on temporary files.
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

from data.db import connect_similarity_db  # noqa: E402
from data.moderation import collect_similarity_host_stats, purge_similarity_for_host  # noqa: E402
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402

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
