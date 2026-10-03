"""`build-ann-index.py` keys its FAISS index by `video_embeddings.ann_id` and records `ANN_ID_SOURCE` (`video_embeddings.ann_id`) as the sidecar's `id_source`, and refuses a table without `ann_id` before it writes anything.

- Over a 64-row source whose 64 distinct `ann_id`s share nothing with its rowids 1..64 (control), `--cpu --nlist 2 --m 2 --nbits 4 --train-sample 64` exits 0, the written index's stored ids are exactly the DB's `ann_id`s, and the sidecar records `id_source` `video_embeddings.ann_id` and `total` 64.
- Over the same 64 vectors in a six-column `video_embeddings` with no `ann_id` (control), the same run exits non-zero, its stderr names `migrate-whitelist.py`, and neither `--index-path` nor `--meta-path` exists afterwards.

The source DBs are tmp files built on the system interpreter, the `ann_id` one through `ensure_video_embeddings_schema`. The job and the index reader run as children on the Engine's interpreter, and the job is passed explicit tmp `--db-path`, `--index-path` and `--meta-path` arguments (setup, not asserted).
"""
from __future__ import annotations

import json
import random
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
BUILD_JOB = SERVER_DIR / "db" / "jobs" / "build-ann-index.py"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
from data import ann_ids  # noqa: E402
from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema  # noqa: E402

DOMAIN = "build.example"
MODEL = "phase3-model"
DIM = 8
ROWS = 64
LABELS = [f"v{n}" for n in range(1, ROWS + 1)]
SIX_COLUMNS = ["video_id", "instance_domain", "embedding", "embedding_dim", "model_name", "created_at"]
# The index is held in a name: id_map read off a temporary `read_index(...)` came back as freed memory (0, 3..64, a stray large id) when probed.
READ_IDS = "import json, sys, faiss; index = faiss.read_index(sys.argv[1]); print(json.dumps(sorted(int(i) for i in faiss.vector_to_array(index.id_map))))"


def _vectors() -> list[bytes]:
    rng = random.Random(42)
    return [struct.pack(f"<{DIM}f", *[rng.uniform(-1.0, 1.0) for _ in range(DIM)]) for _ in LABELS]


def _source_db(path: Path, with_ann_id: bool) -> None:
    """64 embedded videos on one host: through the shared definition with their ann_ids, or in the six-column shape that predates it."""
    conn = sqlite3.connect(path)
    if with_ann_id:
        ensure_video_embeddings_schema(conn)
        conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, ?, ?, ?, 'now', ?)", [(label, DOMAIN, blob, DIM, MODEL, compute_ann_id(label, DOMAIN)) for label, blob in zip(LABELS, _vectors())])
    else:
        conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain))")
        conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at) VALUES (?, ?, ?, ?, ?, 'now')", [(label, DOMAIN, blob, DIM, MODEL) for label, blob in zip(LABELS, _vectors())])
    conn.commit()
    conn.close()


def _run_job(tmp_path: Path) -> subprocess.CompletedProcess:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    return subprocess.run([str(ENGINE_PY), str(BUILD_JOB), "--cpu", "--db-path", str(tmp_path / "source.db"), "--index-path", str(tmp_path / "index.faiss"), "--meta-path", str(tmp_path / "index.faiss.json"), "--nlist", "2", "--m", "2", "--nbits", "4", "--train-sample", str(ROWS)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)


# ---- C1: the index's ids are the DB's ann_ids, and the sidecar says so ----


def test_build_indexes_exactly_the_db_ann_ids_and_records_the_ann_id_source(tmp_path: Path) -> None:
    _source_db(tmp_path / "source.db", True)
    conn = sqlite3.connect(tmp_path / "source.db")
    db_ids = sorted(row[0] for row in conn.execute("SELECT ann_id FROM video_embeddings"))
    rowids = sorted(row[0] for row in conn.execute("SELECT rowid FROM video_embeddings"))
    conn.close()
    # control: 64 distinct ann_ids, none of them a rowid, so an index keyed by rowid or missing a row cannot match.
    assert len(set(db_ids)) == ROWS
    assert rowids == list(range(1, ROWS + 1))
    assert set(db_ids).isdisjoint(rowids)

    result = _run_job(tmp_path)

    assert result.returncode == 0, result.stderr  # C1
    read = subprocess.run([str(ENGINE_PY), "-c", READ_IDS, str(tmp_path / "index.faiss")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert read.returncode == 0, read.stderr
    assert json.loads(read.stdout) == db_ids  # C1
    meta = json.loads((tmp_path / "index.faiss.json").read_text(encoding="utf-8"))
    assert meta["id_source"] == "video_embeddings.ann_id"  # C1: the sidecar value readers resolve (ADR-0006), so a constant left at the rowid value cannot pass
    # Read off the module rather than imported by name: the constant is this phase's own, and a missing name must not stop collection.
    assert meta["id_source"] == ann_ids.ANN_ID_SOURCE  # C1
    assert meta["total"] == ROWS  # C1


# ---- C2: a table without ann_id is refused before anything is written ----


def test_build_refuses_a_table_without_ann_id_naming_migrate_whitelist_and_writes_no_index(tmp_path: Path) -> None:
    _source_db(tmp_path / "source.db", False)
    conn = sqlite3.connect(tmp_path / "source.db")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")]
    count = conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone()[0]
    conn.close()
    # control: the C1 vectors in the shape that predates ann_id, so the missing column is the only reason to refuse.
    assert columns == SIX_COLUMNS
    assert count == ROWS

    result = _run_job(tmp_path)

    assert result.returncode != 0, result.stderr  # C2
    assert "migrate-whitelist.py" in result.stderr, result.stderr  # C2
    # These are the paths the job writes: probed against the unguarded job, this same DB exited 0 and left both files here.
    assert not (tmp_path / "index.faiss").exists()  # C2
    assert not (tmp_path / "index.faiss.json").exists()  # C2
