"""`precompute-similar-ann.py` refuses `--refresh-existing` beside a destructive flag before it touches `--out`.

- Run with `--refresh-existing --cpu` and one of `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db`, the job exits 2 on one argparse error line naming `--refresh-existing` and that flag and no other of the four, over a seeded cache or none.
- After that refusal a seeded `--out` keeps its bytes and mtime, and an absent one is still absent.
- Run with `--refresh-existing --cpu` alone, the job prints no argparse error and goes on to create `--out`.

The job runs as a child process under the engine's pixi interpreter on temporary sqlite files.
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY  # noqa: E402

SIMILAR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DESTRUCTIVE_FLAGS = ["--incremental", "--reset", "--reset-only", "--recreate-out-db"]
ERROR_PREFIX = f"{SIMILAR_JOB.name}: error: "


def _source_db(tmp_path: Path) -> None:
    """An empty source: the refusal must come before anything reads it."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER)")
    conn.commit()
    conn.close()


def _run_job(tmp_path: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(tmp_path / "source.db"), "--index", str(tmp_path / "missing.faiss"), "--out", str(out_path), *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _seed_cache(tmp_path: Path, out_path: Path) -> None:
    """A cache laid out by the job's own `--reset-only`, then holding one sentinel source and item."""
    seeded = _run_job(tmp_path, out_path, "--reset-only")
    assert seeded.returncode == 0, seeded.stderr
    conn = sqlite3.connect(out_path)
    conn.execute("INSERT INTO similarity_sources VALUES ('sentinel-video', 'sentinel.example', 1)")
    conn.execute("INSERT INTO similarity_items VALUES ('sentinel-video', 'sentinel.example', 'other-video', 'sentinel.example', 0.5, 1)")
    conn.commit()
    conn.close()


def _error_lines(stderr: str) -> list[str]:
    # The usage block argparse prints above its `prog: error:` line lists every flag, so only that line can name one.
    return [line for line in stderr.splitlines() if line.startswith(ERROR_PREFIX)]


@pytest.mark.parametrize("cache", ["seeded", "absent"])
@pytest.mark.parametrize("flag", DESTRUCTIVE_FLAGS)
def test_refresh_rejects_each_destructive_flag(tmp_path: Path, flag: str, cache: str) -> None:
    """`--refresh-existing` beside `flag` exits 2 on an error line naming `flag` alone of the four, and leaves a seeded `--out` at the same bytes and mtime, or an absent one absent."""
    _source_db(tmp_path)
    out_path = tmp_path / "similarity-cache.db"
    if cache == "seeded":
        _seed_cache(tmp_path, out_path)
        before = (out_path.read_bytes(), out_path.stat().st_mtime_ns)
    else:
        assert not out_path.exists()

    result = _run_job(tmp_path, out_path, "--refresh-existing", flag, "--cpu")

    assert result.returncode == 2, result.stderr  # C1
    errors = _error_lines(result.stderr)
    assert len(errors) == 1, result.stderr  # C1
    # Whole tokens, so `--reset` is not found inside `--reset-only`.
    named = set(re.findall(r"--[\w-]+", errors[0]))
    assert "--refresh-existing" in named, errors[0]
    assert named & set(DESTRUCTIVE_FLAGS) == {flag}, errors[0]  # C1
    if cache == "seeded":
        assert out_path.exists()  # C2
        assert (out_path.read_bytes(), out_path.stat().st_mtime_ns) == before  # C2
    else:
        assert not out_path.exists()  # C2


def test_refresh_alone_is_not_refused(tmp_path: Path) -> None:
    """`--refresh-existing --cpu` with no destructive flag prints no argparse error and goes on to create `--out`."""
    _source_db(tmp_path)
    out_path = tmp_path / "similarity-cache.db"

    result = _run_job(tmp_path, out_path, "--refresh-existing", "--cpu")

    assert _error_lines(result.stderr) == [], result.stderr  # C1
    # The job opens `--out` only after its argument checks, so the file shows the run got past them rather than dying before them.
    assert out_path.exists(), result.stderr
