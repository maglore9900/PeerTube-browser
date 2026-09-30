"""`precompute-random-rowids.py` either keeps `--out` unwritten or replaces it by rename, at a new inode, leaving no temp file.

- Run on a 20-row source with a fresh `--out`, the job exits 0 and writes positions 1..20 over source rowids 1..20. Run again without `--reset`/`--refresh` at `--size 20` or `--size 5`, it leaves `--out` at the same inode with the same bytes.
- Run with `--reset`, with `--refresh`, or without either over a 3-row `--out` at `--size 20`, the job leaves `--out` at a new inode holding positions 1..20 over source rowids 1..20.
- After every job run the output directory holds only `--out`.

The job runs as a child process through `sys.executable` on temporary sqlite files.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRECOMPUTE_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-random-rowids.py"
SOURCE_ROWS = 20
STALE_ROWID = 999
# Fewer rows than the requested size, so the job cannot keep this cache.
SHORT_ROWS = [(1, 7), (2, 3), (3, 11)]


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


def _seed_cache(path: Path, rows: list[tuple[int, int]]) -> None:
    """Write a random cache file holding exactly `rows`, through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _cache_rows(path: Path) -> list[tuple[int, int]]:
    """A cache file's rows in position order, read through a read-only handle so a missing file is never created."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT position, video_rowid FROM random_rowids ORDER BY position").fetchall()
    finally:
        conn.close()


def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PRECOMPUTE_JOB), "--db", str(tmp_path / "source.db"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


@pytest.mark.parametrize("second_size", [SOURCE_ROWS, 5])
def test_job_builds_a_fresh_out_and_keeps_one_at_size(tmp_path: Path, second_size: int) -> None:
    """The job fills a fresh `--out` with positions 1..20 over source rowids 1..20, and a second run at or below that size leaves the same inode and bytes."""
    _source_db(tmp_path).close()
    out_path = tmp_path / "out" / "random-cache.db"

    fresh = _run_job(tmp_path, out_path, "--size", str(SOURCE_ROWS))
    assert fresh.returncode == 0, fresh.stderr
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]
    built_inode = out_path.stat().st_ino
    built_bytes = out_path.read_bytes()

    kept = _run_job(tmp_path, out_path, "--size", str(second_size))
    assert kept.returncode == 0, kept.stderr
    assert out_path.stat().st_ino == built_inode
    assert out_path.read_bytes() == built_bytes
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]


@pytest.mark.parametrize("case", ["reset", "refresh", "short"])
def test_job_replaces_out_by_rename(tmp_path: Path, case: str) -> None:
    """With `--reset`, with `--refresh`, or over a 3-row `--out` at `--size 20`, the job leaves a new inode at `--out` holding positions 1..20 over source rowids 1..20, and no other file."""
    _source_db(tmp_path).close()
    out_path = tmp_path / "out" / "random-cache.db"
    if case == "short":
        _seed_cache(out_path, SHORT_ROWS)
        flags: list[str] = []
    else:
        # At size, so only the flag stands between this cache and being kept.
        _seed_cache(out_path, [(position, STALE_ROWID) for position in range(1, SOURCE_ROWS + 1)])
        flags = [f"--{case}"]
    seeded_inode = out_path.stat().st_ino

    result = _run_job(tmp_path, out_path, "--size", str(SOURCE_ROWS), *flags)

    assert result.returncode == 0, result.stderr
    # The seeded file still exists when a replacing file is created beside it, so the two cannot share an inode; an in-place write keeps it.
    assert out_path.stat().st_ino != seeded_inode
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]
