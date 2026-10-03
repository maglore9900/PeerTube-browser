"""`precompute-random-rowids.py` either keeps `--out` unwritten or replaces it by rename, at a new inode, leaving no temp file.

- Run on a 20-row source with a fresh `--out`, the job exits 0 and writes positions 1..20 over the source's 20 ann_ids. Run again without `--reset`/`--refresh` at `--size 20` or `--size 5`, it leaves `--out` at the same inode with the same bytes.
- Run with `--reset`, with `--refresh`, or without either over a 3-row `--out` at `--size 20`, the job leaves `--out` at a new inode holding positions 1..20 over the source's 20 ann_ids.
- Run without flags at `--size 20` over a 20-row `--out` holding only the old `random_rowids` table, the job leaves `--out` at a new inode holding positions 1..20 over the source's 20 ann_ids and only `random_ann_ids`; the same run over a 20-id `random_ann_ids` `--out` keeps it at the same inode with the same bytes (control).
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
if str(ROOT / "engine" / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.ann_ids import compute_ann_id  # noqa: E402

SOURCE_ROWS = 20
SOURCE_IDS = sorted(compute_ann_id(f"v{index}", "a.example") for index in range(1, SOURCE_ROWS + 1))
STALE_ROWID = 999
# Fewer rows than the requested size, so the job cannot keep this cache.
SHORT_ROWS = [(1, 7), (2, 3), (3, 11)]


def _source_db(tmp_path: Path) -> sqlite3.Connection:
    """A source of 20 embedded videos, one instance, three channels, each stored with its computed ann_id."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, ann_id INTEGER NOT NULL)")
    for index in range(1, SOURCE_ROWS + 1):
        conn.execute("INSERT INTO videos VALUES (?, 'a.example', ?)", (f"v{index}", f"c{index % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, 'a.example', ?)", (f"v{index}", compute_ann_id(f"v{index}", "a.example")))
    conn.commit()
    return conn


def _seed_cache(path: Path, rows: list[tuple[int, int]]) -> None:
    """Write a random cache file holding exactly `rows`, through plain sqlite3."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_ann_ids (position, ann_id) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _seed_old_cache(path: Path) -> None:
    """Write a cache in the pre-cutover shape: 20 `random_rowids` rows and no `random_ann_ids`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.executemany("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", [(position, STALE_ROWID) for position in range(1, SOURCE_ROWS + 1)])
    conn.commit()
    conn.close()


def _tables(path: Path) -> set[str]:
    """A cache file's table names, read through a read-only handle."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def _cache_rows(path: Path) -> list[tuple[int, int]]:
    """A cache file's rows in position order, read through a read-only handle so a missing file is never created."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT position, ann_id FROM random_ann_ids ORDER BY position").fetchall()
    finally:
        conn.close()


def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PRECOMPUTE_JOB), "--db", str(tmp_path / "source.db"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)


@pytest.mark.parametrize("second_size", [SOURCE_ROWS, 5])
def test_job_builds_a_fresh_out_and_keeps_one_at_size(tmp_path: Path, second_size: int) -> None:
    """The job fills a fresh `--out` with positions 1..20 over the source's 20 ann_ids, and a second run at or below that size leaves the same inode and bytes."""
    _source_db(tmp_path).close()
    out_path = tmp_path / "out" / "random-cache.db"

    fresh = _run_job(tmp_path, out_path, "--size", str(SOURCE_ROWS))
    assert fresh.returncode == 0, fresh.stderr
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert sorted(row[1] for row in rows) == SOURCE_IDS
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
    """With `--reset`, with `--refresh`, or over a 3-row `--out` at `--size 20`, the job leaves a new inode at `--out` holding positions 1..20 over the source's 20 ann_ids, and no other file."""
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
    assert sorted(row[1] for row in rows) == SOURCE_IDS
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]


def test_job_rebuilds_an_out_holding_only_random_rowids_and_keeps_one_holding_random_ann_ids(tmp_path: Path) -> None:
    """Without flags at `--size 20`, the job replaces a 20-row `random_rowids` `--out` with one at a new inode holding positions 1..20 over the source's 20 ann_ids and only `random_ann_ids`, and keeps a 20-id `random_ann_ids` `--out` unwritten."""
    _source_db(tmp_path).close()
    current = tmp_path / "current" / "random-cache.db"
    _seed_cache(current, list(enumerate(SOURCE_IDS, start=1)))
    old = tmp_path / "old" / "random-cache.db"
    _seed_old_cache(old)
    current_inode, current_bytes = current.stat().st_ino, current.read_bytes()
    old_inode = old.stat().st_ino

    kept = _run_job(tmp_path, current, "--size", str(SOURCE_ROWS))
    rebuilt = _run_job(tmp_path, old, "--size", str(SOURCE_ROWS))

    assert rebuilt.returncode == 0, rebuilt.stderr
    # The seeded file still exists when the replacing file is created beside it, so the two cannot share an inode; an in-place write keeps it.
    assert old.stat().st_ino != old_inode
    rows = _cache_rows(old)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))
    assert sorted(row[1] for row in rows) == SOURCE_IDS
    assert _tables(old) == {"random_ann_ids"}
    assert [path.name for path in old.parent.iterdir()] == [old.name]
    # control: at the same size and without flags, a random_ann_ids `--out` is kept unwritten, so the rebuild above is the old table's doing.
    assert kept.returncode == 0, kept.stderr
    assert current.stat().st_ino == current_inode
    assert current.read_bytes() == current_bytes
