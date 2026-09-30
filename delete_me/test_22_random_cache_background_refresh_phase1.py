"""A random cache is built complete in a per-pid temp file beside its target, and the precompute job either keeps `--out` unwritten or replaces it by rename, at a new inode, leaving no temp file.

- `build_random_cache(source, <dir>/random-cache.db, 100, True, 0, 100)` returns `<dir>/random-cache.tmp.<pid>.db` and 20, and that file holds positions 1..20 over source rowids 1..20. The directory then holds only that file and the active file's prior state: no `-journal` or other sidecar, a seeded active file byte-identical and a missing one still missing. A non-sqlite leftover at the temp name does not stop the build.
- With `populate_random_cache` patched to write into the temp file and then raise, `build_random_cache` re-raises, and the directory holds only the seeded active file, byte-identical, with no temp file or `-journal`.
- `precompute-random-rowids.py` run on a 20-row source with a fresh `--out` exits 0 and writes positions 1..20 over source rowids 1..20. Run again without `--reset`/`--refresh` at `--size 20` or `--size 5`, it leaves `--out` at the same inode with the same bytes.
- Run with `--reset`, with `--refresh`, or without either over a 3-row `--out` at `--size 20`, the job leaves `--out` at a new inode holding positions 1..20 over source rowids 1..20.
- After every job run the output directory holds only `--out`.

The in-process tests use temporary sqlite files. The job runs as a child process through `sys.executable`.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
# `data` imports `recommendations`, which lives under `api`, as the Engine's server.py runs it.
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.random_cache as random_cache  # noqa: E402

PRECOMPUTE_JOB = SERVER_DIR / "db" / "jobs" / "precompute-random-rowids.py"
SOURCE_ROWS = 20
STALE_ROWID = 999
# Fewer rows than the requested size, so the job cannot keep this cache.
SHORT_ROWS = [(1, 7), (2, 3), (3, 11)]
FAILURE_MESSAGE = "populate failed after writing"


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


@pytest.mark.parametrize("active", ["seeded", "missing", "leftover"])
def test_build_writes_a_complete_cache_into_the_pid_temp_file_only(tmp_path: Path, active: str) -> None:
    """`build_random_cache` returns `<stem>.tmp.<pid><suffix>` beside the active file holding positions 1..20 over source rowids 1..20, leaves no sidecar, and leaves the active file as it was."""
    source = _source_db(tmp_path)
    active_path = tmp_path / "db" / "random-cache.db"
    expected_temp = tmp_path / "db" / f"random-cache.tmp.{os.getpid()}.db"
    active_path.parent.mkdir()
    if active != "missing":
        _seed_cache(active_path, [(position, STALE_ROWID) for position in range(1, 6)])
    if active == "leftover":
        # Left by an earlier process with this pid; sqlite refuses it as "file is not a database", so only a build that clears it first gets through.
        expected_temp.write_bytes(b"not a sqlite database" * 10)
    active_bytes = active_path.read_bytes() if active_path.exists() else None

    temp_path, count, _ = random_cache.build_random_cache(tmp_path / "source.db", active_path, 100, True, 0, 100)
    source.close()

    assert temp_path == expected_temp  # C1
    assert count == SOURCE_ROWS  # C1
    # Listed before any read, so no sidecar a reader could create is counted; a left-open write or a persisted journal shows here as `-journal`.
    expected_names = {expected_temp.name} if active == "missing" else {expected_temp.name, active_path.name}
    assert {path.name for path in active_path.parent.iterdir()} == expected_names  # C1
    assert (active_path.read_bytes() if active_path.exists() else None) == active_bytes  # C1
    rows = _cache_rows(expected_temp)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C1
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))  # C1


def test_build_failure_removes_the_temp_file_and_leaves_the_active_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `populate_random_cache` that writes into the temp file and then raises: `build_random_cache` re-raises and the directory holds only the unchanged active file."""
    source = _source_db(tmp_path)
    active_path = tmp_path / "db" / "random-cache.db"
    _seed_cache(active_path, [(position, STALE_ROWID) for position in range(1, 6)])
    active_bytes = active_path.read_bytes()
    real_populate = random_cache.populate_random_cache
    temp_existed: list[bool] = []

    def populate_then_raise(src_db: sqlite3.Connection, cache_db: sqlite3.Connection, *args, **kwargs) -> int:
        real_populate(src_db, cache_db, *args, **kwargs)
        # Uncommitted, so the connection is mid-write when the exception leaves it.
        cache_db.execute("INSERT INTO random_rowids (position, video_rowid) VALUES (?, ?)", (SOURCE_ROWS + 1, STALE_ROWID))
        temp_existed.append((tmp_path / "db" / f"random-cache.tmp.{os.getpid()}.db").exists())
        raise RuntimeError(FAILURE_MESSAGE)

    monkeypatch.setattr(random_cache, "populate_random_cache", populate_then_raise)
    with pytest.raises(RuntimeError, match=FAILURE_MESSAGE):
        random_cache.build_random_cache(tmp_path / "source.db", active_path, 100, True, 0, 100)
    source.close()

    # Control: the build reached the patched step with its temp file on disk, so its absence below is the cleanup's doing.
    assert temp_existed == [True]
    assert {path.name for path in active_path.parent.iterdir()} == {active_path.name}  # C1
    assert active_path.read_bytes() == active_bytes  # C1


@pytest.mark.parametrize("second_size", [SOURCE_ROWS, 5])
def test_job_builds_a_fresh_out_and_keeps_one_at_size(tmp_path: Path, second_size: int) -> None:
    """The job fills a fresh `--out` with positions 1..20 over source rowids 1..20, and a second run at or below that size leaves the same inode and bytes."""
    _source_db(tmp_path).close()
    out_path = tmp_path / "out" / "random-cache.db"

    fresh = _run_job(tmp_path, out_path, "--size", str(SOURCE_ROWS))
    assert fresh.returncode == 0, fresh.stderr
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C2
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))  # C2
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]  # C2
    built_inode = out_path.stat().st_ino
    built_bytes = out_path.read_bytes()

    kept = _run_job(tmp_path, out_path, "--size", str(second_size))
    assert kept.returncode == 0, kept.stderr
    assert out_path.stat().st_ino == built_inode  # C2
    assert out_path.read_bytes() == built_bytes  # C2
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]  # C2


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
    assert out_path.stat().st_ino != seeded_inode  # C2
    rows = _cache_rows(out_path)
    assert [row[0] for row in rows] == list(range(1, SOURCE_ROWS + 1))  # C2
    assert sorted(row[1] for row in rows) == list(range(1, SOURCE_ROWS + 1))  # C2
    assert [path.name for path in out_path.parent.iterdir()] == [out_path.name]  # C2
