"""Phase 2 checkpoint (plan 19): `precompute-similar-ann.py` refreshes and extends a compact similarity cache, selecting through `video_keys`.

must_prove:
- P2C1: After `--refresh-existing`, each cached source still in `video_embeddings` reads back through `fetch_cached_similarities` with the job's fresh top-k neighbours, and each cached source no longer in `video_embeddings` reads back unchanged.
- P2C2: After `--incremental`, each embedding not cached before reads back with its fresh top-k neighbours, and each source cached before reads back unchanged.

The job runs as a child process under the Engine's pixi interpreter, `--cpu --top-k 2`, over eight unit vectors in a real FAISS inner-product index (adapted from tests/active/test_precompute_similar_ann.py). Expected neighbours and scores are the dot products worked out by hand from VECTORS; sources whose top two tie (v3: v2 and v4 both 0.6; v7: v6 and v8 both 0.8) are checked by neighbour set and ranks only. The seeded cache is written through `data.similarity_cache`.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
SERVER_DIR = ROOT / "engine" / "server"
for path in (ACTIVE, SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from conftest import ENGINE_PY  # noqa: E402
from data.db import connect_similarity_db  # noqa: E402
from data.similarity_cache import ensure_similarity_schema, fetch_cached_similarities, store_similarity_cache  # noqa: E402

SIMILAR_JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
DOMAIN = "live.example"
MODEL = "refresh-test-model"
DIM = 4
VECTORS = {1: (1.0, 0.0, 0.0, 0.0), 2: (0.8, 0.6, 0.0, 0.0), 3: (0.0, 1.0, 0.0, 0.0), 4: (0.0, 0.6, 0.8, 0.0), 5: (0.0, 0.0, 1.0, 0.0), 6: (0.0, 0.0, 0.6, 0.8), 7: (0.0, 0.0, 0.0, 1.0), 8: (0.6, 0.0, 0.0, 0.8)}
# Declares DIM but stores 3 floats: in video_embeddings, never in the index, dropped by the job's query batch.
SHORT_ROWID = 9
SENTINEL = [{"video_id": "sentinel-target", "instance_domain": "sentinel.example", "score": 0.5, "rank": 1}]
SENTINEL_AT = 1
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
# Top two by inner product, worked out from VECTORS: (neighbour, score) in rank order.
TOP2 = {
    1: [(2, 0.8), (8, 0.6)],
    2: [(1, 0.8), (3, 0.6)],
    4: [(5, 0.8), (3, 0.6)],
    5: [(4, 0.8), (6, 0.6)],
    6: [(7, 0.8), (8, 0.64)],
    8: [(7, 0.8), (6, 0.64)],
}
TIED_TOP2 = {3: ({2, 4}, 0.6), 7: ({6, 8}, 0.8)}


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A source DB with `video_embeddings` rowids 1..9 and an inner-product index over the 8 full-length vectors, with its model sidecar."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    import sqlite3

    root = tmp_path_factory.mktemp("similar_compact")
    conn = sqlite3.connect(root / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL)")
    rows = [(rowid, f"v{rowid}", DOMAIN, struct.pack(f"<{DIM}f", *vector), DIM, MODEL) for rowid, vector in VECTORS.items()]
    rows.append((SHORT_ROWID, f"v{SHORT_ROWID}", DOMAIN, struct.pack("<3f", 1.0, 1.0, 1.0), DIM, MODEL))
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    built = subprocess.run([str(ENGINE_PY), "-c", INDEX_BUILDER, str(root / "source.db"), str(root / "index.faiss"), str(DIM)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stderr
    (root / "index.faiss.json").write_text(json.dumps({"model_name": MODEL, "embedding_dim": DIM}), encoding="utf-8")
    return root


def _run_job(source: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(source / "source.db"), "--index", str(source / "index.faiss"), "--out", str(out_path), "--cpu", "--top-k", "2", *args], cwd=out_path.parent, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _seed(out_path: Path, keys: list[tuple[str, str]]) -> None:
    """A compact cache in which every key holds the one SENTINEL neighbour at SENTINEL_AT."""
    conn = connect_similarity_db(out_path)
    ensure_similarity_schema(conn)
    for video_id, domain in keys:
        store_similarity_cache(conn, {"video_id": video_id, "instance_domain": domain}, SENTINEL, SENTINEL_AT)
    conn.close()


def _read(out_path: Path, video_id: str, domain: str = DOMAIN) -> list[dict]:
    conn = connect_similarity_db(out_path)
    try:
        return fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": domain}, 1000)
    finally:
        conn.close()


def _expected(rowid: int) -> list[dict]:
    return [{"video_id": f"v{other}", "instance_domain": DOMAIN, "score": pytest.approx(score, abs=1e-6), "rank": rank} for rank, (other, score) in enumerate(TOP2[rowid], start=1)]


def test_refresh_existing_recomputes_cached_embedded_sources_and_keeps_the_rest(source: Path, tmp_path: Path) -> None:
    """Cached v1, v2, v4 read back with their hand-computed top two; cached gone1, ("v5", "") and the length-skipped v9 keep the sentinel; an uncached embedding gains nothing."""
    out_path = tmp_path / "similarity-cache.db"
    _seed(out_path, [("v1", DOMAIN), ("v2", DOMAIN), ("v4", DOMAIN), ("gone1", DOMAIN), ("v5", ""), (f"v{SHORT_ROWID}", DOMAIN)])

    result = _run_job(source, out_path, "--refresh-existing")

    assert result.returncode == 0, result.stderr
    for rowid in (1, 2, 4):
        assert _read(out_path, f"v{rowid}") == _expected(rowid), rowid  # C1
    assert _read(out_path, "gone1") == SENTINEL  # C1
    # ("v5", "") shares a video_id with the embedded (v5, DOMAIN): matching on video_id alone would refresh it.
    assert _read(out_path, "v5", "") == SENTINEL  # C1
    assert _read(out_path, f"v{SHORT_ROWID}") == SENTINEL
    assert _read(out_path, "v5") == []


def test_incremental_adds_uncached_embeddings_and_keeps_cached_sources(source: Path, tmp_path: Path) -> None:
    """With v1 and gone1 cached, v2-v8 read back with their top two (v3 and v7 by tied neighbour set) and v1 and gone1 keep the sentinel."""
    out_path = tmp_path / "similarity-cache.db"
    _seed(out_path, [("v1", DOMAIN), ("gone1", DOMAIN)])

    result = _run_job(source, out_path, "--incremental")

    assert result.returncode == 0, result.stderr
    for rowid in (2, 4, 5, 6, 8):
        assert _read(out_path, f"v{rowid}") == _expected(rowid), rowid  # C2
    for rowid, (neighbours, score) in TIED_TOP2.items():
        entries = _read(out_path, f"v{rowid}")
        assert {entry["video_id"] for entry in entries} == {f"v{other}" for other in neighbours}, (rowid, entries)  # C2
        assert [entry["rank"] for entry in entries] == [1, 2], (rowid, entries)  # C2
        assert [entry["score"] for entry in entries] == [pytest.approx(score, abs=1e-6)] * 2, (rowid, entries)  # C2
    assert _read(out_path, "v1") == SENTINEL  # C2
    assert _read(out_path, "gone1") == SENTINEL  # C2
