"""The Engine's similar and vector-search readers turn a FAISS id into the video whose `ann_id` it is, so an index not rebuilt after the table changed can only miss a video, never name another one.

- One `IDMap2,IVF1,Flat` inner-product index is built on `ann_id` from 12 videos (8 on keep.example, 4 on purge.example) and never rebuilt. Its ids, mapped through `compute_ann_id`, rank the videos in the hand-sorted ORDER, each at its vector's cosine against the probe (control).
- Over that index, `ann.compute_similar_items` (seeded by `embeddings.resolve_seed` on v0) names ORDER without v0, each with the cosine its vector scores against the probe, and `search.vector_candidates` (an encoder returning v0's vector) names all of ORDER. This holds:
  - on the unchanged DB;
  - after every `video_embeddings` row is deleted and reinserted in reverse, which changes every rowid and keeps every row and `ann_id` (control);
  - after a new keep.example video equal to the probe is embedded but not indexed; it is in neither list.
- After `purge_host_data` on purge.example, whose videos are hits of the index (control) and whose rows are gone (control), similar names the keep.example videos of ORDER without v0 with their scores, search names all of them, and purge.example is in neither.

The DBs are tmp files built on the system interpreter through `sync-whitelist.py`'s schema helpers. The readers run in one child on the Engine's interpreter against a stub server.
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
from conftest import ENGINE_PY, ROOT

SERVER_DIR = ROOT / "engine" / "server"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
from data.ann_ids import compute_ann_id  # noqa: E402
from data.moderation import purge_host_data  # noqa: E402

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
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_test_ann", JOBS_DIR / "sync-whitelist.py")
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
    """Over the DB the index was built from, similar names ORDER without the seed and search names ORDER, each similar item at its vector's cosine."""
    # control: the index the stale cases reuse names ORDER through the recorded ann_ids, each at its vector's cosine, so a wrong list below is the readers', not the index's.
    assert stale["index"] == _keys(ORDER)
    assert stale["index_scores"] == _scores(ORDER)
    base = stale["reads"]["base"]

    assert _similar_keys(base) == _keys(ORDER[1:])
    assert [score for *_, score in base["similar"]] == _scores(ORDER[1:])
    assert _search_keys(base) == _keys(ORDER)


def test_after_a_reverse_reinsert_both_readers_name_the_video_each_ann_id_was_built_from(stale):
    """After every row's rowid changes under an unrebuilt index, both readers still name the video each hit's ann_id was built from."""
    base_rowids, moved_rowids = _rowids(stale["dbs"]["base"]), _rowids(stale["dbs"]["A"])
    # control: every video's rowid changed while its row, ann_id included, did not, so a read keyed on rowid would name other videos.
    assert set(moved_rowids) == set(RANK)
    assert all(moved_rowids[label] != base_rowids[label] for label in RANK), (base_rowids, moved_rowids)
    assert _embedding_rows(stale["dbs"]["A"]) == _embedding_rows(stale["dbs"]["base"])
    read = stale["reads"]["A"]

    assert _similar_keys(read) == _keys(ORDER[1:])
    assert [score for *_, score in read["similar"]] == _scores(ORDER[1:])  # each named video carries the vector its hit scored
    assert _search_keys(read) == _keys(ORDER)


def test_after_a_host_purge_both_readers_drop_its_videos_and_name_the_rest_by_ann_id(stale):
    """Hits whose rows a host purge removed are dropped, not substituted, and the rest are named by their ann_id."""
    # control: purge.example videos are hits of the index both readers consult, and the purge removed their rows.
    assert {host for _, host in stale["index"]} == {KEEP, PURGE}
    assert _embedding_rows(stale["dbs"]["B"], "instance_domain = ?", (PURGE,)) == []
    read = stale["reads"]["B"]

    assert _similar_keys(read) == _keys(KEPT_ORDER[1:])
    assert [score for *_, score in read["similar"]] == _scores(KEPT_ORDER[1:])
    assert _search_keys(read) == _keys(KEPT_ORDER)
    assert PURGE not in {host for _, host in _similar_keys(read) + _search_keys(read)}


def test_a_new_unindexed_video_is_absent_from_both_reads_not_substituted(stale):
    """A video embedded after the index was built appears in neither read, even with the probe's own vector."""
    # control: the new video is embedded in C with the probe's own vector, so only its absence from the index keeps it out.
    assert [row[:4] + row[6:] for row in _embedding_rows(stale["dbs"]["C"], "video_id = ?", (NEW[0],))] == [(*NEW, struct.pack("<4f", *_vector("v0")), 4, compute_ann_id(*NEW))]
    read = stale["reads"]["C"]

    assert _similar_keys(read) == _keys(ORDER[1:])
    assert [score for *_, score in read["similar"]] == _scores(ORDER[1:])
    assert _search_keys(read) == _keys(ORDER)
    assert NEW not in _similar_keys(read)
    assert NEW not in _search_keys(read)
