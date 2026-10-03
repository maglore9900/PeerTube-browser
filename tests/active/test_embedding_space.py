"""`assert_index_matches_embeddings` accepts the sidecar `build-ann-index.py` writes, whose `id_source` is `video_embeddings.ann_id`, and refuses one whose `id_source` is anything else or missing with a RuntimeError naming the source it found and `build-ann-index.py`; a model mismatch is still refused by the model check first.

- The sidecar a real `--cpu` build over a 64-row `ann_id` source writes passes for its own model and dimension, against a stub index of `d=8`.
- The same sidecar with `id_source` `video_embeddings.rowid` raises RuntimeError naming `video_embeddings.rowid` and `build-ann-index.py`.
- The same sidecar with `id_source` `video_embeddings.ann_ids`, a near miss no legacy sidecar carries, raises RuntimeError naming `video_embeddings.ann_ids` and `build-ann-index.py`.
- The same sidecar with `id_source` removed raises RuntimeError naming `<unset>` and `build-ann-index.py`.
- The rowid sidecar checked against another model raises the model refusal, which names that model and not `video_embeddings.rowid`.

The source DB is a tmp file built on the system interpreter through `ensure_video_embeddings_schema`, and the job runs as a child on the Engine's interpreter (setup, not asserted). The index is a `SimpleNamespace(d=8)` stub: the function reads only `index.d`, and loading faiss would tie this test to the Engine interpreter for one attribute.
"""
from __future__ import annotations

import json
import random
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ENGINE_PY, ROOT

SERVER_DIR = ROOT / "engine" / "server"
BUILD_JOB = SERVER_DIR / "db" / "jobs" / "build-ann-index.py"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
from data.ann_ids import compute_ann_id, ensure_video_embeddings_schema  # noqa: E402
from data.embedding_space import assert_index_matches_embeddings  # noqa: E402

DOMAIN = "build.example"
MODEL = "space-test-model"
DIM = 8
ROWS = 64
LABELS = [f"v{n}" for n in range(1, ROWS + 1)]
INDEX = SimpleNamespace(d=DIM)


def _source_db(path: Path) -> None:
    """64 embedded videos on one host, through the shared definition with their ann_ids."""
    rng = random.Random(42)
    conn = sqlite3.connect(path)
    ensure_video_embeddings_schema(conn)
    conn.executemany("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, ?, ?, ?, 'now', ?)", [(label, DOMAIN, struct.pack(f"<{DIM}f", *[rng.uniform(-1.0, 1.0) for _ in range(DIM)]), DIM, MODEL, compute_ann_id(label, DOMAIN)) for label in LABELS])
    conn.commit()
    conn.close()


@pytest.fixture
def built(tmp_path: Path) -> Path:
    """Run the real index build and return its index path; the sidecar sits at `<index>.json`."""
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    _source_db(tmp_path / "source.db")
    result = subprocess.run([str(ENGINE_PY), str(BUILD_JOB), "--cpu", "--db-path", str(tmp_path / "source.db"), "--index-path", str(tmp_path / "index.faiss"), "--meta-path", str(tmp_path / "index.faiss.json"), "--nlist", "2", "--m", "2", "--nbits", "4", "--train-sample", str(ROWS)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return tmp_path / "index.faiss"


def _meta(index_path: Path) -> dict:
    return json.loads(Path(f"{index_path}.json").read_text(encoding="utf-8"))


def _rewrite(index_path: Path, meta: dict) -> None:
    Path(f"{index_path}.json").write_text(json.dumps(meta), encoding="utf-8")


def test_accepts_the_sidecar_build_ann_index_writes(built: Path) -> None:
    """The sidecar a real build writes passes the check for its own model and dimension."""
    meta = _meta(built)
    # control: the written sidecar carries the ann_id source and this space, so only a check refusing the right source could fail here.
    assert meta["id_source"] == "video_embeddings.ann_id"
    assert (meta["model_name"], meta["embedding_dim"]) == (MODEL, DIM)

    assert assert_index_matches_embeddings(built, INDEX, DIM, MODEL) is None


def test_refuses_a_rowid_sidecar_naming_the_rowid_source_and_build_ann_index(built: Path) -> None:
    """A legacy rowid-keyed sidecar is refused with a message naming the rowid source and the rebuild."""
    _rewrite(built, {**_meta(built), "id_source": "video_embeddings.rowid"})

    with pytest.raises(RuntimeError) as refused:
        assert_index_matches_embeddings(built, INDEX, DIM, MODEL)

    assert "video_embeddings.rowid" in str(refused.value), str(refused.value)
    assert "build-ann-index.py" in str(refused.value), str(refused.value)


def test_refuses_a_near_miss_sidecar_no_legacy_value_uses_naming_it_and_build_ann_index(built: Path) -> None:
    """The check is exact equality on `ANN_ID_SOURCE`: a near-miss value is refused, naming it and the rebuild."""
    # Neither the legacy rowid nor missing: only an allowlist on ANN_ID_SOURCE refuses it, and a prefix match on ann_id would let it through.
    _rewrite(built, {**_meta(built), "id_source": "video_embeddings.ann_ids"})

    with pytest.raises(RuntimeError) as refused:
        assert_index_matches_embeddings(built, INDEX, DIM, MODEL)

    assert "video_embeddings.ann_ids" in str(refused.value), str(refused.value)
    assert "build-ann-index.py" in str(refused.value), str(refused.value)


def test_refuses_a_sidecar_without_id_source_as_unset_naming_build_ann_index(built: Path) -> None:
    """A sidecar with no `id_source` is refused as `<unset>`, not defaulted."""
    meta = _meta(built)
    del meta["id_source"]
    _rewrite(built, meta)

    with pytest.raises(RuntimeError) as refused:
        assert_index_matches_embeddings(built, INDEX, DIM, MODEL)

    assert "<unset>" in str(refused.value), str(refused.value)
    assert "build-ann-index.py" in str(refused.value), str(refused.value)


def test_a_model_mismatch_is_refused_by_the_model_check_before_id_source(built: Path) -> None:
    """A model mismatch is refused by the model check, which runs ahead of the id-source check."""
    _rewrite(built, {**_meta(built), "id_source": "video_embeddings.rowid"})

    with pytest.raises(RuntimeError) as refused:
        assert_index_matches_embeddings(built, INDEX, DIM, "other-model")

    # Probed against the function before the id-source check: this message names other-model and build-ann-index.py, never the id source.
    assert "other-model" in str(refused.value), str(refused.value)
    assert "video_embeddings.rowid" not in str(refused.value), str(refused.value)
