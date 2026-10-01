"""The compact similarity cache in `engine/server/data/similarity_cache.py`: what is stored reads back in rank order from a two-table file, and a legacy-layout file is refused untouched.

- Entries stored with `store_similarity_cache` for two sources sharing a `video_id` on different hosts, handed over out of rank order with gapped ranks, are returned by `fetch_cached_similarities` with the stored ids and scores in rank order, ranks renumbered 1..n, cut at `limit` after ordering, and replaced by a later store; the file holds only `video_keys` and `similarity_sources`.
- `ensure_similarity_schema` gives an empty file the compact tables, and on a legacy-layout file (one with `similarity_items`) raises `RuntimeError` naming the file and `migrate-similarity-cache.py`, leaving the file's bytes unchanged. The Engine's start calls it on the cache it opens.

Runs in-process on temporary files. Scores are dyadic fractions, exact in the float32 the cache stores.
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
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402

A = "a.example"
B = "b.example"
MIGRATE_JOB_NAME = "migrate-similarity-cache.py"
# The layout every cache had before the compact one, as the precompute job and the Engine created it.
LEGACY_DDL = """
CREATE TABLE similarity_sources (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, computed_at INTEGER NOT NULL, PRIMARY KEY (video_id, instance_domain));
CREATE TABLE similarity_items (source_video_id TEXT NOT NULL, source_instance_domain TEXT NOT NULL, similar_video_id TEXT NOT NULL, similar_instance_domain TEXT NOT NULL, score REAL, rank INTEGER NOT NULL, PRIMARY KEY (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain));
CREATE INDEX similarity_source_rank_idx ON similarity_items (source_video_id, source_instance_domain, rank);
"""


def _entry(video_id: str, domain: str, score: float, rank: int) -> dict:
    return {"video_id": video_id, "instance_domain": domain, "score": score, "rank": rank}


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def _fetch(path: Path, video_id: str, domain: str, limit: int) -> list[dict]:
    conn = connect_similarity_db(path)
    try:
        return fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, limit)
    finally:
        conn.close()


def test_stored_entries_read_back_in_rank_order_from_a_two_table_file(tmp_path: Path) -> None:
    """Two sources sharing a video_id on different hosts, items handed over out of rank order with gapped ranks, read back in rank order and renumbered 1..n, cut at limit, replaced by a later store, from a file holding only video_keys and similarity_sources."""
    path = tmp_path / "cache.db"
    conn = connect_similarity_db(path)
    ensure_similarity_schema(conn)
    source_a = {"video_id": "s1", "instance_domain": A}
    source_b = {"video_id": "s1", "instance_domain": B}
    # Gapped ranks: echoing the stored rank would answer 2/5/9, keeping the handed-over order would put n2 first.
    store_similarity_cache(conn, source_a, [_entry("n2", B, 0.5, 5), _entry("n1", A, 0.75, 2), _entry("n3", A, 0.25, 9)], 100)
    store_similarity_cache(conn, source_b, [_entry("n1", B, 0.875, 1), _entry("n2", B, 0.625, 2)], 200)
    conn.close()

    assert _fetch(path, "s1", A, 10) == [_entry("n1", A, 0.75, 1), _entry("n2", B, 0.5, 2), _entry("n3", A, 0.25, 3)]
    assert _fetch(path, "s1", A, 2) == [_entry("n1", A, 0.75, 1), _entry("n2", B, 0.5, 2)]
    # Handed over n2 first: cutting before ordering would answer n2 here.
    assert _fetch(path, "s1", A, 1) == [_entry("n1", A, 0.75, 1)]
    assert _fetch(path, "s1", B, 10) == [_entry("n1", B, 0.875, 1), _entry("n2", B, 0.625, 2)]
    assert _fetch(path, "never", A, 10) == []

    conn = connect_similarity_db(path)
    store_similarity_cache(conn, source_a, [_entry("n3", A, 0.375, 4)], 300)
    conn.close()
    assert _fetch(path, "s1", A, 10) == [_entry("n3", A, 0.375, 1)]
    assert _fetch(path, "s1", B, 10) == [_entry("n1", B, 0.875, 1), _entry("n2", B, 0.625, 2)]

    assert _tables(path) == {"video_keys", "similarity_sources"}


def _legacy_cache(path: Path) -> None:
    """A legacy-layout cache holding v1@live.example with one neighbour."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_DDL)
    conn.execute("INSERT INTO similarity_sources VALUES ('v1', 'live.example', 1)")
    conn.execute("INSERT INTO similarity_items VALUES ('v1', 'live.example', 'v2', 'live.example', 0.5, 1)")
    conn.commit()
    conn.close()


def test_ensure_schema_refuses_a_legacy_file_naming_it_and_the_migration_job(tmp_path: Path) -> None:
    """An empty file gains the compact tables; a legacy file raises RuntimeError naming its path and migrate-similarity-cache.py and keeps its bytes."""
    empty = tmp_path / "empty.db"
    conn = connect_similarity_db(empty)
    ensure_similarity_schema(conn)
    conn.close()
    assert _tables(empty) == {"video_keys", "similarity_sources"}

    legacy = tmp_path / "legacy.db"
    _legacy_cache(legacy)
    before = legacy.read_bytes()
    conn = connect_similarity_db(legacy)
    with pytest.raises(RuntimeError) as raised:
        ensure_similarity_schema(conn)
    conn.close()
    assert MIGRATE_JOB_NAME in str(raised.value), raised.value
    assert str(legacy) in str(raised.value), raised.value
    # Bytes, not the object list: a schema change or a row write before the raise also fails here.
    assert legacy.read_bytes() == before
