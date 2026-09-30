"""Retired from `tests/active/test_random_cache.py` by harvest 22 (random cache background refresh).

These two tests drove `populate_random_cache(..., reuse_non_empty=True)`, the in-place reuse branch the Engine used at a refresh-off start before it opened its cache read-only. No production caller uses that branch any more. Their rules live on in the active file:

- `test_refresh_off_reuses_a_short_cache_without_writing` is replaced by `test_a_non_empty_cache_opens_read_only_even_under_a_held_write_lock`, which serves a non-empty cache under a held write lock through the `mode=ro` open in `open_random_cache_if_usable`.
- `test_refresh_off_builds_a_missing_or_empty_cache` is replaced by `test_a_missing_tableless_or_empty_cache_is_not_usable`, which drives the Engine's "missing or empty means build" decision in `open_random_cache_if_usable`.

Kept readable here, and skipped.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

ROOT = Path(__file__).resolve().parents[3]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data.random_cache import connect_random_cache_db, ensure_random_cache_schema, populate_random_cache  # noqa: E402

SOURCE_ROWS = 20
# Fewer rows than the requested size, so a start that does not reuse rebuilds this cache.
SEEDED_ROWS = [(1, 7), (2, 3), (3, 11)]


def _source_db(tmp_path: Path) -> sqlite3.Connection:
    """A source of 20 embedded videos, rowids 1..20, one instance, three channels."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT)")
    for index in range(1, SOURCE_ROWS + 1):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example')", (f"v{index}",))
    conn.commit()
    return conn


def test_refresh_off_reuses_a_short_cache_without_writing(tmp_path: Path) -> None:
    """Refresh off with `reuse_non_empty=True` returns a 3-row cache's count under a held write lock, opens no transaction, and leaves the rows as seeded."""
    source = _source_db(tmp_path)
    cache_path = tmp_path / "cache.db"
    seed = connect_random_cache_db(cache_path)
    ensure_random_cache_schema(seed)
    seed.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", SEEDED_ROWS)
    seed.commit()
    seed.close()

    holder = sqlite3.connect(cache_path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        # Control: the lock is armed and a short cache is otherwise rebuilt, so the default call's write fails on it.
        control = sqlite3.connect(cache_path, timeout=0)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            populate_random_cache(source, control, 100, False, True, 0, 100)
        control.close()

        # timeout=0: any write this call sent would fail "locked" at once instead of waiting.
        cache = sqlite3.connect(cache_path, timeout=0)
        reused = populate_random_cache(source, cache, 100, False, True, 0, 100, reuse_non_empty=True)
        in_transaction = cache.in_transaction
        rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
        cache.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert reused == len(SEEDED_ROWS)
    # A write attempt, even a failed one, leaves Python's implicit BEGIN open on the connection.
    assert in_transaction is False
    assert rows == SEEDED_ROWS


@pytest.mark.parametrize("table", ["missing", "empty"])
def test_refresh_off_builds_a_missing_or_empty_cache(tmp_path: Path, table: str) -> None:
    """Refresh off with `reuse_non_empty=True` builds a cache whose table is missing or empty: 20 rows, positions 1..20 over source rowids 1..20."""
    source = _source_db(tmp_path)
    cache = connect_random_cache_db(tmp_path / "cache.db")
    if table == "empty":
        ensure_random_cache_schema(cache)
        cache.commit()

    built = populate_random_cache(source, cache, 100, False, True, 0, 100, reuse_non_empty=True)

    assert built == SOURCE_ROWS
    rows = cache.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    assert [row["position"] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert {row["video_rowid"] for row in rows} == set(range(1, SOURCE_ROWS + 1))
    cache.close()
