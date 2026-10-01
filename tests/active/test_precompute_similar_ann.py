"""`precompute-similar-ann.py --refresh-existing` refuses a destructive flag before it touches `--out`, and rewrites exactly the cached sources still in `video_embeddings` while leaving every other cache row as it was; `--incremental` adds exactly the uncached embeddings; a legacy-layout `--out` is refused untouched.

- Run with `--refresh-existing --cpu` and one of `--incremental`, `--reset`, `--reset-only`, `--recreate-out-db`, the job exits 2 on one argparse error line naming `--refresh-existing` and that flag and no other of the four, over a seeded cache or none; a seeded `--out` keeps its bytes and mtime, and an absent one is still absent.
- Over a cache holding v1-v3 (live), gone1, gone2, (v5, "") and the length-skipped v9, the job logs `mode=refresh-existing`, 4 total sources and 3/4 processed; v1-v3 carry one `computed_at` stamped during the run and exactly three fresh items ranked 1..3 on other live keys, the rest keep their snapshot rows and items, the uncached v4-v8 gain no rows, and 7 sources remain.
- Over a missing or schema-only cache the job exits 0 with 0 total and 0/0 processed, leaves both cache tables (`video_keys`, `similarity_sources`) in place, and writes no rows.
- With v1 and gone1 cached, `--incremental --top-k 2` gives v2-v8 their top two by inner product (worked out by hand from the unit vectors; v3 and v7, whose top two tie, by neighbour set, ranks and score) and leaves v1 and gone1 as they were.
- Over a legacy-layout `--out` (one with `similarity_items`) `--refresh-existing` exits non-zero with stderr naming `migrate-similarity-cache.py` and leaves the file's bytes unchanged, while the same run over a compact `--out` exits 0.

The job runs as a child process under the engine's pixi interpreter on temporary sqlite files and a real FAISS index built by that interpreter.
"""
from __future__ import annotations

import json
import re
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import ENGINE_PY, ROOT

if str(ROOT / "engine" / "server") not in sys.path:
    sys.path.insert(0, str(ROOT / "engine" / "server"))
from data.similarity_cache import fetch_cached_similarities, store_similarity_cache  # noqa: E402

SIMILAR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DESTRUCTIVE_FLAGS = ["--incremental", "--reset", "--reset-only", "--recreate-out-db"]
ERROR_PREFIX = f"{SIMILAR_JOB.name}: error: "
DOMAIN = "live.example"
MODEL = "refresh-test-model"
DIM = 4
# Unit vectors: under inner product each is its own nearest neighbour, so after the job drops self a --top-k 3 search over these 8 leaves exactly 3 others.
VECTORS = {1: (1.0, 0.0, 0.0, 0.0), 2: (0.8, 0.6, 0.0, 0.0), 3: (0.0, 1.0, 0.0, 0.0), 4: (0.0, 0.6, 0.8, 0.0), 5: (0.0, 0.0, 1.0, 0.0), 6: (0.0, 0.0, 0.6, 0.8), 7: (0.0, 0.0, 0.0, 1.0), 8: (0.6, 0.0, 0.0, 0.8)}
# Declares DIM but stores 3 floats, so it shares the table's one embedding space yet `build_query_batch` drops it.
SHORT_ROWID = 9
LIVE = {(f"v{rowid}", DOMAIN) for rowid in [*VECTORS, SHORT_ROWID]}
CACHED_LIVE = [("v1", DOMAIN), ("v2", DOMAIN), ("v3", DOMAIN)]
# gone1/gone2 left video_embeddings; ("v5", "") shares a video_id with a live key, so a join on video_id alone would wrongly pick up (v5, DOMAIN).
CACHED_UNTOUCHED = [("gone1", DOMAIN), ("gone2", DOMAIN), ("v5", ""), (f"v{SHORT_ROWID}", DOMAIN)]
UNCACHED = [("v4", DOMAIN), ("v5", DOMAIN), ("v6", DOMAIN), ("v7", DOMAIN), ("v8", DOMAIN)]
SENTINEL_AT = 1
SENTINEL_TARGET = ("sentinel-target", "sentinel.example")
INDEX_BUILDER = """
import sqlite3, sys
import faiss, numpy as np
db, index_path, dim = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = sqlite3.connect(db).execute("SELECT rowid, embedding FROM video_embeddings WHERE length(embedding) = ?", (dim * 4,)).fetchall()
vectors = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
index = faiss.index_factory(dim, "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)
index.train(vectors)
index.add_with_ids(vectors, np.array([row[0] for row in rows], dtype=np.int64))
faiss.write_index(index, index_path)
"""


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A source DB with `video_embeddings` rowids 1..9 and an inner-product index over the 8 full-length vectors, with its model sidecar."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    root = tmp_path_factory.mktemp("similar_refresh")
    conn = sqlite3.connect(root / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL)")
    rows = [(rowid, f"v{rowid}", DOMAIN, struct.pack(f"<{DIM}f", *vector), DIM, MODEL) for rowid, vector in VECTORS.items()]
    rows.append((SHORT_ROWID, f"v{SHORT_ROWID}", DOMAIN, struct.pack("<3f", 1.0, 1.0, 1.0), DIM, MODEL))
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    # A missing faiss or numpy fails here with the child's stderr rather than skipping.
    built = subprocess.run([str(ENGINE_PY), "-c", INDEX_BUILDER, str(root / "source.db"), str(root / "index.faiss"), str(DIM)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stderr
    (root / "index.faiss.json").write_text(json.dumps({"model_name": MODEL, "embedding_dim": DIM}), encoding="utf-8")
    return root


def _source_db(tmp_path: Path) -> None:
    """An empty source with no index beside it: a refusal must come before anything reads either."""
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER)")
    conn.commit()
    conn.close()


def _run_job(source: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(source / "source.db"), "--index", str(source / "index.faiss"), "--out", str(out_path), *args], cwd=out_path.parent, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _reset_cache(source: Path, out_path: Path) -> None:
    """A schema-only cache laid out by the job's own `--reset-only`."""
    seeded = _run_job(source, out_path, "--reset-only")
    assert seeded.returncode == 0, seeded.stderr


def _seed_cache(source: Path, out_path: Path) -> None:
    """Every key in CACHED_LIVE + CACHED_UNTOUCHED gets a source row at SENTINEL_AT and one item pointing at SENTINEL_TARGET."""
    _reset_cache(source, out_path)
    conn = sqlite3.connect(out_path)
    for video_id, domain in CACHED_LIVE + CACHED_UNTOUCHED:
        store_similarity_cache(conn, {"video_id": video_id, "instance_domain": domain}, [{"video_id": SENTINEL_TARGET[0], "instance_domain": SENTINEL_TARGET[1], "score": 0.5, "rank": 1}], SENTINEL_AT)
    conn.close()


def _snapshot(out_path: Path, keys: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[int | None, list[tuple]]]:
    """Per key: its `computed_at` (None without a source row) and its items as (similar_video_id, similar_instance_domain, score, rank) in rank order."""
    conn = sqlite3.connect(out_path)
    snapshot = {}
    for video_id, domain in keys:
        row = conn.execute("SELECT s.computed_at FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key WHERE k.video_id = ? AND k.instance_domain = ?", (video_id, domain)).fetchone()
        items = [(entry["video_id"], entry["instance_domain"], entry["score"], entry["rank"]) for entry in fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, 1000)]
        snapshot[(video_id, domain)] = (row[0] if row else None, items)
    conn.close()
    return snapshot


def _count(out_path: Path, table: str) -> int:
    conn = sqlite3.connect(out_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return count


def _logged(stderr: str, pattern: str) -> tuple[str, ...]:
    match = re.search(pattern, stderr)
    assert match, stderr
    return match.groups()


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

    assert result.returncode == 2, result.stderr
    errors = _error_lines(result.stderr)
    assert len(errors) == 1, result.stderr
    # Whole tokens, so `--reset` is not found inside `--reset-only`.
    named = set(re.findall(r"--[\w-]+", errors[0]))
    assert "--refresh-existing" in named, errors[0]
    assert named & set(DESTRUCTIVE_FLAGS) == {flag}, errors[0]
    if cache == "seeded":
        assert out_path.exists()
        assert (out_path.read_bytes(), out_path.stat().st_mtime_ns) == before
    else:
        assert not out_path.exists()


def test_refresh_rewrites_exactly_cached_live_sources(source: Path, tmp_path: Path) -> None:
    """v1-v3 get one run-time `computed_at` and exactly three fresh items ranked 1..3 on other live keys; gone1, gone2, (v5, "") and the length-skipped v9 keep their rows and items; v4-v8 gain nothing; 4 sources are selected and 3 processed."""
    out_path = tmp_path / "similarity-cache.db"
    _seed_cache(source, out_path)
    before = _snapshot(out_path, CACHED_UNTOUCHED)
    started_ms = int(time.time() * 1000)

    result = _run_job(source, out_path, "--refresh-existing", "--cpu", "--top-k", "3")

    finished_ms = int(time.time() * 1000)
    assert result.returncode == 0, result.stderr
    assert "mode=refresh-existing" in result.stderr, result.stderr
    # A full scan logs 9 and 8/9; an outer join from the incremental path would also count the uncached keys.
    assert _logged(result.stderr, r"total sources=(\d+)") == ("4",)
    assert _logged(result.stderr, r"done processed=(\d+)/(\d+)") == ("3", "4")
    rewritten = _snapshot(out_path, CACHED_LIVE)
    stamps = {computed_at for computed_at, _ in rewritten.values()}
    assert len(stamps) == 1, rewritten
    (stamp,) = stamps
    assert stamp is not None and stamp > SENTINEL_AT and started_ms <= stamp <= finished_ms, (stamp, started_ms, finished_ms)
    for key, (_, items) in rewritten.items():
        assert [rank for *_, rank in items] == [1, 2, 3], (key, items)
        targets = {(video_id, domain) for video_id, domain, _, _ in items}
        assert SENTINEL_TARGET not in targets, (key, items)
        assert targets <= LIVE - {key}, (key, items)
    assert _snapshot(out_path, CACHED_UNTOUCHED) == before
    assert all(computed_at == SENTINEL_AT for computed_at, _ in before.values()), before
    assert _snapshot(out_path, UNCACHED) == {key: (None, []) for key in UNCACHED}
    assert _count(out_path, "similarity_sources") == len(CACHED_LIVE + CACHED_UNTOUCHED) == 7


@pytest.mark.parametrize("cache", ["missing", "empty"])
def test_refresh_over_missing_or_empty_cache_is_a_no_op(source: Path, tmp_path: Path, cache: str) -> None:
    """Over a missing or schema-only cache, `--refresh-existing` exits 0 with 0 total and 0/0 processed, and leaves both cache tables present and empty."""
    out_path = tmp_path / "similarity-cache.db"
    if cache == "empty":
        _reset_cache(source, out_path)
    else:
        assert not out_path.exists()

    result = _run_job(source, out_path, "--refresh-existing", "--cpu", "--top-k", "3")

    assert result.returncode == 0, result.stderr
    # A full scan over this source logs 9 and 8/9.
    assert _logged(result.stderr, r"total sources=(\d+)") == ("0",)
    assert _logged(result.stderr, r"done processed=(\d+)/(\d+)") == ("0", "0")
    conn = sqlite3.connect(out_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert {"video_keys", "similarity_sources"} <= tables, tables
    assert _count(out_path, "similarity_sources") == 0
    assert _count(out_path, "video_keys") == 0


# Top two by inner product, worked out by hand from VECTORS: (neighbour rowid, score) in rank order.
TOP2 = {
    2: [(1, 0.8), (3, 0.6)],
    4: [(5, 0.8), (3, 0.6)],
    5: [(4, 0.8), (6, 0.6)],
    6: [(7, 0.8), (8, 0.64)],
    8: [(7, 0.8), (6, 0.64)],
}
# v3's top two tie at 0.6 (v2, v4) and v7's at 0.8 (v6, v8), so only the set, the ranks and the scores are fixed.
TIED_TOP2 = {3: ({2, 4}, 0.6), 7: ({6, 8}, 0.8)}
SENTINEL = [{"video_id": SENTINEL_TARGET[0], "instance_domain": SENTINEL_TARGET[1], "score": 0.5, "rank": 1}]


def _read(out_path: Path, video_id: str, domain: str = DOMAIN) -> list[dict]:
    conn = sqlite3.connect(out_path)
    try:
        return fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, 1000)
    finally:
        conn.close()


def test_incremental_adds_uncached_embeddings_and_keeps_cached_sources(source: Path, tmp_path: Path) -> None:
    """With v1 and gone1 cached, `--incremental --top-k 2` gives v2-v8 their hand-computed top two (v3 and v7 by tied neighbour set) and leaves v1 and gone1 their sentinel entry."""
    out_path = tmp_path / "similarity-cache.db"
    _reset_cache(source, out_path)
    conn = sqlite3.connect(out_path)
    for video_id in ("v1", "gone1"):
        store_similarity_cache(conn, {"video_id": video_id, "instance_domain": DOMAIN}, SENTINEL, SENTINEL_AT)
    conn.close()

    result = _run_job(source, out_path, "--incremental", "--cpu", "--top-k", "2")

    assert result.returncode == 0, result.stderr
    for rowid, neighbours in TOP2.items():
        expected = [{"video_id": f"v{other}", "instance_domain": DOMAIN, "score": pytest.approx(score, abs=1e-6), "rank": rank} for rank, (other, score) in enumerate(neighbours, start=1)]
        assert _read(out_path, f"v{rowid}") == expected, rowid
    for rowid, (neighbours, score) in TIED_TOP2.items():
        entries = _read(out_path, f"v{rowid}")
        assert {entry["video_id"] for entry in entries} == {f"v{other}" for other in neighbours}, (rowid, entries)
        assert [entry["rank"] for entry in entries] == [1, 2], (rowid, entries)
        assert [entry["score"] for entry in entries] == [pytest.approx(score, abs=1e-6)] * 2, (rowid, entries)
    assert _read(out_path, "v1") == SENTINEL
    assert _read(out_path, "gone1") == SENTINEL


LEGACY_DDL = """
CREATE TABLE similarity_sources (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, computed_at INTEGER NOT NULL, PRIMARY KEY (video_id, instance_domain));
CREATE TABLE similarity_items (source_video_id TEXT NOT NULL, source_instance_domain TEXT NOT NULL, similar_video_id TEXT NOT NULL, similar_instance_domain TEXT NOT NULL, score REAL, rank INTEGER NOT NULL, PRIMARY KEY (source_video_id, source_instance_domain, similar_video_id, similar_instance_domain));
CREATE INDEX similarity_source_rank_idx ON similarity_items (source_video_id, source_instance_domain, rank);
"""


def test_refresh_refuses_a_legacy_out_naming_the_migration_job(source: Path, tmp_path: Path) -> None:
    """Over a compact `--out` the job exits 0; over a legacy-layout `--out` it exits non-zero, its stderr names migrate-similarity-cache.py, and the file keeps its bytes."""
    compact = tmp_path / "compact.db"
    _reset_cache(source, compact)
    control = _run_job(source, compact, "--refresh-existing", "--cpu", "--top-k", "2")
    assert control.returncode == 0, control.stderr

    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.executescript(LEGACY_DDL)
    conn.execute("INSERT INTO similarity_sources VALUES ('v1', ?, 1)", (DOMAIN,))
    conn.execute("INSERT INTO similarity_items VALUES ('v1', ?, 'v2', ?, 0.5, 1)", (DOMAIN, DOMAIN))
    conn.commit()
    conn.close()
    before = legacy.read_bytes()
    result = _run_job(source, legacy, "--refresh-existing", "--cpu", "--top-k", "2")
    assert result.returncode != 0, result.stderr
    assert "migrate-similarity-cache.py" in result.stderr, result.stderr
    assert legacy.read_bytes() == before
