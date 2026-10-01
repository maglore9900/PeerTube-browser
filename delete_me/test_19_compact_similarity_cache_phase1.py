"""Phase 1 checkpoint (plan 19): the compact similarity cache round-trips through `data.similarity_cache`, and `migrate-similarity-cache.py` converts a legacy-layout file into it.

must_prove:
- P1C1: Entries stored with `store_similarity_cache` for several sources are returned by `fetch_cached_similarities` with the stored `video_id`, `instance_domain` and `score`, in rank order, cut at `limit`, each `rank` numbering its position (1..n), from a file whose only tables are `video_keys` and `similarity_sources`.
- P1C2: For every source in a legacy-layout file, including one with no neighbours, `fetch_cached_similarities` on the file `migrate-similarity-cache.py` writes returns the neighbours the legacy `similarity_items` rows held for it, in rank order.

The store and read run in-process on temporary files; the job runs as a child process under the Engine's pixi interpreter. Scores are dyadic fractions, exact in float32.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
SERVER_DIR = ROOT / "engine" / "server"
for path in (ACTIVE, SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from conftest import ENGINE_PY  # noqa: E402
from data.db import connect_similarity_db  # noqa: E402
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402

MIGRATE_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "migrate-similarity-cache.py"
A = "a.example"
B = "b.example"
# The layout every cache had before plan 19, as precompute-similar-ann.py and data/similarity_cache.py created it.
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


def _fetch(path: Path, video_id: str, domain: str, limit: int = 1000) -> list[dict]:
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

    assert _fetch(path, "s1", A, 10) == [_entry("n1", A, 0.75, 1), _entry("n2", B, 0.5, 2), _entry("n3", A, 0.25, 3)]  # C1
    assert _fetch(path, "s1", A, 2) == [_entry("n1", A, 0.75, 1), _entry("n2", B, 0.5, 2)]  # C1
    # Handed over n2 first: cutting before ordering would answer n2 here.
    assert _fetch(path, "s1", A, 1) == [_entry("n1", A, 0.75, 1)]  # C1
    assert _fetch(path, "s1", B, 10) == [_entry("n1", B, 0.875, 1), _entry("n2", B, 0.625, 2)]  # C1
    assert _fetch(path, "never", A, 10) == []

    conn = connect_similarity_db(path)
    store_similarity_cache(conn, source_a, [_entry("n3", A, 0.375, 4)], 300)
    conn.close()
    assert _fetch(path, "s1", A, 10) == [_entry("n3", A, 0.375, 1)]  # C1
    assert _fetch(path, "s1", B, 10) == [_entry("n1", B, 0.875, 1), _entry("n2", B, 0.625, 2)]

    assert _tables(path) == {"video_keys", "similarity_sources"}  # C1


def _legacy_cache(path: Path) -> None:
    """s1@a (three items, inserted out of rank order), s1@b (one), s2@a (two, one pointing back at s1@a) and s3@a with no items."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_DDL)
    conn.executemany("INSERT INTO similarity_sources VALUES (?, ?, ?)", [("s1", A, 100), ("s1", B, 200), ("s2", A, 300), ("s3", A, 400)])
    conn.executemany(
        "INSERT INTO similarity_items VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("s1", A, "n3", A, 0.25, 3),
            ("s1", A, "n1", A, 0.75, 1),
            ("s1", A, "n2", B, 0.5, 2),
            ("s1", B, "n1", B, 0.875, 1),
            ("s2", A, "n2", B, 0.125, 2),
            ("s2", A, "s1", A, 0.625, 1),
        ],
    )
    conn.commit()
    conn.close()


def _migrate(in_path: Path, out_path: Path) -> subprocess.CompletedProcess:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    return subprocess.run([str(ENGINE_PY), str(MIGRATE_JOB), "--in", str(in_path), "--out", str(out_path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_migration_serves_every_legacy_source_its_legacy_neighbours_and_refuses_an_existing_output(tmp_path: Path) -> None:
    """A legacy file migrated by the job serves s1@a, s1@b and s2@a their legacy items in rank order and keeps s3@a with none; the input keeps its bytes, and a second run onto the existing output fails and leaves it as it was."""
    legacy = tmp_path / "legacy.db"
    out = tmp_path / "compact.db"
    _legacy_cache(legacy)
    legacy_bytes = legacy.read_bytes()

    result = _migrate(legacy, out)
    assert result.returncode == 0, result.stderr

    assert _fetch(out, "s1", A) == [_entry("n1", A, 0.75, 1), _entry("n2", B, 0.5, 2), _entry("n3", A, 0.25, 3)]  # C2
    assert _fetch(out, "s1", B) == [_entry("n1", B, 0.875, 1)]  # C2
    assert _fetch(out, "s2", A) == [_entry("s1", A, 0.625, 1), _entry("n2", B, 0.125, 2)]  # C2
    # rung 3: fetch_cached_similarities answers [] for an empty source and for a missing one alike, so only the stored rows show s3@a was kept.
    conn = sqlite3.connect(out)
    try:
        sources = sorted(conn.execute("SELECT k.video_id, k.instance_domain FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key").fetchall())
    finally:
        conn.close()
    assert sources == [("s1", A), ("s1", B), ("s2", A), ("s3", A)]  # C2
    assert _fetch(out, "s3", A) == []  # C2

    assert legacy.read_bytes() == legacy_bytes
    out_bytes = out.read_bytes()
    again = _migrate(legacy, out)
    assert again.returncode != 0, again.stdout
    assert out.read_bytes() == out_bytes
