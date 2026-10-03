"""The Engine's similar and vector-search readers, and the similarity precompute, turn a FAISS id into the video whose `ann_id` it is, so an index not rebuilt after the table changed can only miss a video, never name another one.

- One `IDMap2,IVF1,Flat` inner-product index is built on `ann_id` from 12 videos (8 on keep.example, 4 on purge.example) and never rebuilt. Its ids, mapped through `compute_ann_id`, rank the videos in the hand-sorted ORDER, each at its vector's cosine against the probe (control).
- Over that index, `ann.compute_similar_items` (seeded by `embeddings.resolve_seed` on v0) names ORDER without v0, each with the cosine its vector scores against the probe, and `search.vector_candidates` (an encoder returning v0's vector) names all of ORDER. This holds:
  - on the unchanged DB;
  - after every `video_embeddings` row is deleted and reinserted in reverse, which changes every rowid and keeps every row and `ann_id` (control);
  - after a new keep.example video equal to the probe is embedded but not indexed; it is in neither list.
- After `purge_host_data` on purge.example, whose videos are hits of the index (control) and whose rows are gone (control), similar names the keep.example videos of ORDER without v0 with their scores, search names all of them, and purge.example is in neither.
- `precompute-similar-ann.py --cpu --top-k 2` runs over an `ann_id`-keyed index with an `id_source: video_embeddings.ann_id` sidecar, in full, `--incremental` (over a reset cache) and `--refresh-existing` (over a cache of sentinel rows for v1-v8) mode. Each of v1-v8 gets exactly two neighbours ranked 1, 2, none of them itself. They are its hand-computed top two by video key, rank and score, and for the tied v3 and v7 by neighbour set, host and score.

The DBs are tmp files built on the system interpreter: the stale-index DB through `sync-whitelist.py`'s schema helpers, the precompute source through `ensure_video_embeddings_schema`. The readers run in one child on the Engine's interpreter against a stub server, and the job runs as a child process.
"""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import sqlite3
import struct
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema  # noqa: E402
from data.moderation import purge_host_data  # noqa: E402
from data.similarity_cache import fetch_cached_similarities, store_similarity_cache  # noqa: E402

# ---- C1: the Engine readers over an index not rebuilt after the table changed ----

KEEP = "keep.example"
PURGE = "purge.example"
HOSTS = {f"v{n}": KEEP if n < 8 else PURGE for n in range(12)}
# Each video's vector sits at 15 * rank degrees in one plane, so its inner product with the probe (v0's vector, rank 0) is cos(15 * rank deg), strictly falling with rank; ranks are scrambled against labels and insertion order.
RANK = {"v0": 0, "v1": 7, "v2": 3, "v3": 10, "v4": 1, "v5": 5, "v6": 8, "v7": 2, "v8": 4, "v9": 9, "v10": 6, "v11": 11}
# RANK sorted by hand: the order every read must name, the purge.example videos interleaved.
ORDER = ["v0", "v4", "v7", "v2", "v8", "v5", "v10", "v1", "v6", "v9", "v3", "v11"]
# ORDER without the purge.example videos v8, v10, v9, v11.
KEPT_ORDER = ["v0", "v4", "v7", "v2", "v5", "v1", "v6", "v3"]
NEW = ("new", KEEP)
# More than the 12 indexed ids, so a read returns every hit it can resolve.
LIMIT = 50
EMBEDDING_COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"

_CHILD = textwrap.dedent(
    """
    import json, sqlite3, sys, threading, types
    import faiss, numpy as np
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    from data import ann, embeddings, search

    limit = int(sys.argv[5])
    probe = np.array(json.loads(sys.argv[4]), dtype=np.float32)
    built_from = sqlite3.connect(sys.argv[2])
    rows = built_from.execute("SELECT ann_id, embedding FROM video_embeddings").fetchall()
    built_from.close()
    vectors = np.vstack([np.frombuffer(blob, dtype=np.float32) for _, blob in rows])
    index = faiss.index_factory(vectors.shape[1], "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)
    index.train(vectors)
    index.add_with_ids(vectors, np.array([ann_id for ann_id, _ in rows], dtype=np.int64))
    scores, ids = index.search(probe.reshape(1, -1), limit)
    out = {"index": [[int(ann_id), float(score)] for score, ann_id in zip(scores[0], ids[0]) if int(ann_id) != -1]}
    for case, path in json.loads(sys.argv[3]).items():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        seed = embeddings.resolve_seed(conn, vectors.shape[1], None, "v0", "keep.example", None)
        server = types.SimpleNamespace(index=index, index_lock=threading.Lock(), db=conn, db_lock=threading.Lock(), normalize_queries=False, similarity_search_limit=0, similarity_exclude_source_author=False, similarity_max_per_author=0, video_error_threshold=None, query_encoder=types.SimpleNamespace(enabled=True, encode=lambda text: probe))
        similar = ann.compute_similar_items(server, seed, limit)
        found = search.vector_candidates(server, "probe", limit)
        out[case] = {"similar": [[item["video_id"], item["instance_domain"], item["score"]] for item in similar], "search": [[row["video_id"], row["instance_domain"]] for row in found]}
        conn.close()
    print(json.dumps(out))
    """
)


def _vector(label: str) -> tuple[float, float, float, float]:
    angle = math.radians(15 * RANK[label])
    return (math.cos(angle), math.sin(angle), 0.0, 0.0)


def _keys(labels: list[str]) -> list[tuple[str, str]]:
    return [(label, HOSTS[label]) for label in labels]


def _scores(labels: list[str]) -> list:
    return [pytest.approx(math.cos(math.radians(15 * RANK[label])), abs=1e-6) for label in labels]


def _similar_keys(read: dict) -> list[tuple[str, str]]:
    return [(video_id, host) for video_id, host, _ in read["similar"]]


def _search_keys(read: dict) -> list[tuple[str, str]]:
    return [(video_id, host) for video_id, host in read["search"]]


def _rowids(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {video_id: rowid for rowid, video_id in conn.execute("SELECT rowid, video_id FROM video_embeddings")}
    finally:
        conn.close()


def _embedding_rows(path: Path, where: str = "1", params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT {EMBEDDING_COLUMNS} FROM video_embeddings WHERE {where} ORDER BY video_id", params).fetchall()
    finally:
        conn.close()


def _insert_video(conn: sqlite3.Connection, label: str, host: str, vector: tuple[float, ...]) -> None:
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, nsfw, last_checked_at) VALUES (?, ?, ?, ?, ?, 0, 1)", (label, f"u-{label}", host, f"ch-{label}", f"title {label}"))
    conn.execute(f"INSERT INTO video_embeddings ({EMBEDDING_COLUMNS}) VALUES (?, ?, ?, 4, 'm', 'now', ?)", (label, host, struct.pack("<4f", *vector), compute_ann_id(label, host)))


@pytest.fixture(scope="module")
def stale(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One index built from `base`, then both readers over `base` and over copies changed after the build: A reverse-reinserted, B with purge.example purged, C with an unindexed `new` equal to the probe."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    root = tmp_path_factory.mktemp("stale_ann_index")
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_test_42_phase1", JOBS_DIR / "sync-whitelist.py")
    sync_job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_job)
    dbs = {"base": root / "base.db"}
    conn = sqlite3.connect(dbs["base"])
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    for label in RANK:
        _insert_video(conn, label, HOSTS[label], _vector(label))
    conn.commit()
    conn.close()
    for case in ("A", "B", "C"):
        dbs[case] = root / f"{case}.db"
        shutil.copy(dbs["base"], dbs[case])

    conn = sqlite3.connect(dbs["A"])
    rows = conn.execute(f"SELECT {EMBEDDING_COLUMNS} FROM video_embeddings ORDER BY rowid").fetchall()
    # Deleted first: the collision trigger and the UNIQUE index refuse a second row holding one ann_id.
    conn.execute("DELETE FROM video_embeddings")
    conn.executemany(f"INSERT INTO video_embeddings ({EMBEDDING_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", list(reversed(rows)))
    conn.commit()
    conn.close()
    conn = sqlite3.connect(dbs["B"])
    purge_host_data(conn, PURGE)
    conn.close()
    conn = sqlite3.connect(dbs["C"])
    _insert_video(conn, *NEW, _vector("v0"))
    conn.commit()
    conn.close()

    proc = subprocess.run([str(ENGINE_PY), "-c", _CHILD, str(SERVER_DIR), str(dbs["base"]), json.dumps({case: str(path) for case, path in dbs.items()}), json.dumps(list(_vector("v0"))), str(LIMIT)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    reads = json.loads(proc.stdout)
    # The ann_id each video's vector was indexed under, computed here rather than read back.
    recorded = {compute_ann_id(label, host): (label, host) for label, host in [*_keys(list(RANK)), NEW]}
    hits = reads.pop("index")
    return {"dbs": dbs, "reads": reads, "index": [recorded[ann_id] for ann_id, _ in hits], "index_scores": [score for _, score in hits]}


def test_on_the_unchanged_db_both_readers_name_the_video_each_ann_id_was_built_from(stale):
    # control: the index the stale cases reuse names ORDER through the recorded ann_ids, each at its vector's cosine, so a wrong list below is the readers', not the index's.
    assert stale["index"] == _keys(ORDER)
    assert stale["index_scores"] == _scores(ORDER)
    base = stale["reads"]["base"]

    assert _similar_keys(base) == _keys(ORDER[1:])
    assert [score for *_, score in base["similar"]] == _scores(ORDER[1:])
    assert _search_keys(base) == _keys(ORDER)


def test_after_a_reverse_reinsert_both_readers_name_the_video_each_ann_id_was_built_from(stale):
    base_rowids, moved_rowids = _rowids(stale["dbs"]["base"]), _rowids(stale["dbs"]["A"])
    # control: every video's rowid changed while its row, ann_id included, did not, so a read keyed on rowid would name other videos.
    assert set(moved_rowids) == set(RANK)
    assert all(moved_rowids[label] != base_rowids[label] for label in RANK), (base_rowids, moved_rowids)
    assert _embedding_rows(stale["dbs"]["A"]) == _embedding_rows(stale["dbs"]["base"])
    read = stale["reads"]["A"]

    assert _similar_keys(read) == _keys(ORDER[1:])  # C1
    assert [score for *_, score in read["similar"]] == _scores(ORDER[1:])  # C1: each named video carries the vector its hit scored
    assert _search_keys(read) == _keys(ORDER)  # C1


def test_after_a_host_purge_both_readers_drop_its_videos_and_name_the_rest_by_ann_id(stale):
    # control: purge.example videos are hits of the index both readers consult, and the purge removed their rows.
    assert {host for _, host in stale["index"]} == {KEEP, PURGE}
    assert _embedding_rows(stale["dbs"]["B"], "instance_domain = ?", (PURGE,)) == []
    read = stale["reads"]["B"]

    assert _similar_keys(read) == _keys(KEPT_ORDER[1:])  # C1
    assert [score for *_, score in read["similar"]] == _scores(KEPT_ORDER[1:])  # C1
    assert _search_keys(read) == _keys(KEPT_ORDER)  # C1
    assert PURGE not in {host for _, host in _similar_keys(read) + _search_keys(read)}  # C1


def test_a_new_unindexed_video_is_absent_from_both_reads_not_substituted(stale):
    # control: the new video is embedded in C with the probe's own vector, so only its absence from the index keeps it out.
    assert [row[:4] + row[6:] for row in _embedding_rows(stale["dbs"]["C"], "video_id = ?", (NEW[0],))] == [(*NEW, struct.pack("<4f", *_vector("v0")), 4, compute_ann_id(*NEW))]
    read = stale["reads"]["C"]

    assert _similar_keys(read) == _keys(ORDER[1:])  # C1
    assert [score for *_, score in read["similar"]] == _scores(ORDER[1:])  # C1
    assert _search_keys(read) == _keys(ORDER)  # C1
    assert NEW not in _similar_keys(read)  # C1
    assert NEW not in _search_keys(read)  # C1


# ---- C2: precompute-similar-ann.py over an index keyed by ann_id ----

SIMILAR_JOB = JOBS_DIR / "precompute-similar-ann.py"
DOMAIN = "live.example"
MODEL = "phase1-model"
DIM = 4
# Unit vectors: each is its own nearest neighbour, so a source that is not excluded heads its own list at score 1.
VECTORS = {1: (1.0, 0.0, 0.0, 0.0), 2: (0.8, 0.6, 0.0, 0.0), 3: (0.0, 1.0, 0.0, 0.0), 4: (0.0, 0.6, 0.8, 0.0), 5: (0.0, 0.0, 1.0, 0.0), 6: (0.0, 0.0, 0.6, 0.8), 7: (0.0, 0.0, 0.0, 1.0), 8: (0.6, 0.0, 0.0, 0.8)}
# Top two by inner product, worked out by hand from VECTORS: (neighbour, score) in rank order.
TOP2 = {
    1: [(2, 0.8), (8, 0.6)],
    2: [(1, 0.8), (3, 0.6)],
    4: [(5, 0.8), (3, 0.6)],
    5: [(4, 0.8), (6, 0.6)],
    6: [(7, 0.8), (8, 0.64)],
    8: [(7, 0.8), (6, 0.64)],
}
# v3's top two tie at 0.6 (v2, v4) and v7's at 0.8 (v6, v8), so only the set, the ranks and the scores are fixed.
TIED_TOP2 = {3: ({2, 4}, 0.6), 7: ({6, 8}, 0.8)}
SENTINEL = [{"video_id": "sentinel", "instance_domain": "sentinel.example", "score": 0.5, "rank": 1}]
INDEX_BUILDER = """
import sqlite3, sys
import faiss, numpy as np
db, index_path, dim = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = sqlite3.connect(db).execute("SELECT ann_id, embedding FROM video_embeddings").fetchall()
vectors = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
index = faiss.index_factory(dim, "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)
index.train(vectors)
index.add_with_ids(vectors, np.array([row[0] for row in rows], dtype=np.int64))
faiss.write_index(index, index_path)
"""


@pytest.fixture(scope="module")
def source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A source DB from the shared `video_embeddings` definition holding v1..v8 with their ann_ids, and an inner-product index over them keyed by ann_id, with its sidecar."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    root = tmp_path_factory.mktemp("similar_ann_ids")
    conn = sqlite3.connect(root / "source.db")
    ensure_video_embeddings_schema(conn)
    conn.executemany(f"INSERT INTO video_embeddings ({EMBEDDING_COLUMNS}) VALUES (?, ?, ?, ?, ?, 'now', ?)", [(f"v{n}", DOMAIN, struct.pack(f"<{DIM}f", *vector), DIM, MODEL, compute_ann_id(f"v{n}", DOMAIN)) for n, vector in VECTORS.items()])
    conn.commit()
    conn.close()
    built = subprocess.run([str(ENGINE_PY), "-c", INDEX_BUILDER, str(root / "source.db"), str(root / "index.faiss"), str(DIM)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stderr
    (root / "index.faiss.json").write_text(json.dumps({"model_name": MODEL, "embedding_dim": DIM, "id_source": "video_embeddings.ann_id"}), encoding="utf-8")
    return root


def _run_job(source: Path, out_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(ENGINE_PY), str(SIMILAR_JOB), "--db", str(source / "source.db"), "--index", str(source / "index.faiss"), "--out", str(out_path), *args], cwd=out_path.parent, capture_output=True, text=True, encoding="utf-8", timeout=120)


def _read(out_path: Path, video_id: str) -> list[dict]:
    conn = sqlite3.connect(out_path)
    try:
        return fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": DOMAIN}, 1000)
    finally:
        conn.close()


# Each mode reaches the index through its own source selection: the full-table scan, the uncached join and the cached join.
@pytest.mark.parametrize(("mode", "flags"), [("full", []), ("incremental", ["--incremental"]), ("refresh-existing", ["--refresh-existing"])])
def test_precompute_lists_each_sources_neighbours_by_ann_id_and_never_the_source(source, tmp_path, mode, flags):
    out_path = tmp_path / "similarity-cache.db"
    if mode != "full":
        reset = _run_job(source, out_path, "--reset-only")
        assert reset.returncode == 0, reset.stderr
    if mode == "refresh-existing":
        conn = sqlite3.connect(out_path)
        for n in VECTORS:
            store_similarity_cache(conn, {"video_id": f"v{n}", "instance_domain": DOMAIN}, SENTINEL, 1)
        conn.close()

    result = _run_job(source, out_path, *flags, "--cpu", "--top-k", "2")

    assert result.returncode == 0, result.stderr
    assert f"mode={mode}" in result.stderr, result.stderr
    for n in VECTORS:
        entries = _read(out_path, f"v{n}")
        assert len(entries) == 2, (n, entries)  # C2: two resolved neighbours, so the self check below is not vacuous
        assert (f"v{n}", DOMAIN) not in {(entry["video_id"], entry["instance_domain"]) for entry in entries}, (n, entries)  # C2
        assert [entry["rank"] for entry in entries] == [1, 2], (n, entries)  # C2
    for n, neighbours in TOP2.items():
        expected = [{"video_id": f"v{other}", "instance_domain": DOMAIN, "score": pytest.approx(score, abs=1e-6), "rank": rank} for rank, (other, score) in enumerate(neighbours, start=1)]
        assert _read(out_path, f"v{n}") == expected, n  # C2
    for n, (neighbours, score) in TIED_TOP2.items():
        entries = _read(out_path, f"v{n}")
        assert {entry["video_id"] for entry in entries} == {f"v{other}" for other in neighbours}, (n, entries)  # C2
        assert {entry["instance_domain"] for entry in entries} == {DOMAIN}, (n, entries)  # C2
        assert [entry["score"] for entry in entries] == [pytest.approx(score, abs=1e-6)] * 2, (n, entries)  # C2
