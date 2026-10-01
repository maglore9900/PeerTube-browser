"""Phase 3 checkpoint (plan 19): a legacy-layout similarity cache is refused, with a message naming migrate-similarity-cache.py, and left as it was.

must_prove:
- P3C1: `ensure_similarity_schema` on a legacy-layout file raises `RuntimeError` naming the file and `migrate-similarity-cache.py`, and the file's tables are unchanged.
- P3C2: `precompute-similar-ann.py --refresh-existing` with a legacy-layout `--out` exits non-zero with stderr naming `migrate-similarity-cache.py`, and the `--out` bytes are unchanged.

`ensure_similarity_schema` stands for the Engine's start (engine/server/api/server.py calls it on the cache it opens): the Engine's cache path is fixed under the repo root, so a test Engine cannot be pointed at a legacy file without overwriting the shared cache.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (Path(__file__).resolve().parent, SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.db import connect_similarity_db  # noqa: E402
from data.similarity_cache import ensure_similarity_schema  # noqa: E402
# The phase 2 source DB and FAISS index, so the positive control below runs the job to completion.
from test_19_compact_similarity_cache_phase2 import _run_job, source  # noqa: E402,F401

MIGRATE_JOB_NAME = "migrate-similarity-cache.py"
LEGACY_DDL = """
CREATE TABLE similarity_sources (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, computed_at INTEGER NOT NULL, PRIMARY KEY (video_id, instance_domain));
CREATE TABLE similarity_items (source_video_id TEXT NOT NULL, source_instance_domain TEXT NOT NULL, similar_video_id TEXT NOT NULL, similar_instance_domain TEXT NOT NULL, score REAL, rank INTEGER NOT NULL, PRIMARY KEY (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain));
CREATE INDEX similarity_source_rank_idx ON similarity_items (source_video_id, source_instance_domain, rank);
"""


def _legacy_cache(path: Path) -> None:
    """A legacy-layout cache holding v1@live.example with one neighbour."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_DDL)
    conn.execute("INSERT INTO similarity_sources VALUES ('v1', 'live.example', 1)")
    conn.execute("INSERT INTO similarity_items VALUES ('v1', 'live.example', 'v2', 'live.example', 0.5, 1)")
    conn.commit()
    conn.close()


def _schema(path: Path) -> set[tuple[str, str]]:
    conn = sqlite3.connect(path)
    try:
        return {(row[0], row[1]) for row in conn.execute("SELECT type, name FROM sqlite_master")}
    finally:
        conn.close()


def test_ensure_schema_refuses_a_legacy_file_naming_it_and_the_migration_job(tmp_path: Path) -> None:
    """An empty file gains the compact tables; a legacy file raises RuntimeError naming its path and migrate-similarity-cache.py and keeps its bytes."""
    empty = tmp_path / "empty.db"
    conn = connect_similarity_db(empty)
    ensure_similarity_schema(conn)
    conn.close()
    assert {name for kind, name in _schema(empty) if kind == "table"} == {"video_keys", "similarity_sources"}

    legacy = tmp_path / "legacy.db"
    _legacy_cache(legacy)
    before = legacy.read_bytes()
    conn = connect_similarity_db(legacy)
    with pytest.raises(RuntimeError) as raised:
        ensure_similarity_schema(conn)
    conn.close()
    assert MIGRATE_JOB_NAME in str(raised.value), raised.value  # C1
    assert str(legacy) in str(raised.value), raised.value  # C1
    # Bytes, not the object list: a schema change or a row write before the raise also fails here.
    assert legacy.read_bytes() == before  # C1


def test_precompute_refuses_a_legacy_out_naming_the_migration_job(source: Path, tmp_path: Path) -> None:
    """Over a compact --out the job exits 0; over a legacy --out it exits non-zero, its stderr names migrate-similarity-cache.py, and the file keeps its bytes."""
    compact = tmp_path / "compact.db"
    conn = connect_similarity_db(compact)
    ensure_similarity_schema(conn)
    conn.close()
    control = _run_job(source, compact, "--refresh-existing")
    assert control.returncode == 0, control.stderr

    legacy = tmp_path / "legacy.db"
    _legacy_cache(legacy)
    before = legacy.read_bytes()
    result = _run_job(source, legacy, "--refresh-existing")
    assert result.returncode != 0, result.stderr  # C2
    assert MIGRATE_JOB_NAME in result.stderr, result.stderr  # C2
    assert legacy.read_bytes() == before  # C2
