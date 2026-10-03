from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_42_ann_ids_b_readers_cutover_phase3 as p3  # noqa: E402
from data.embedding_space import assert_index_matches_embeddings  # noqa: E402


def _try(path, model):
    try:
        assert_index_matches_embeddings(path, SimpleNamespace(d=8), 8, model)
        return "OK"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def test_probe(tmp_path: Path) -> None:
    p3._source_db(tmp_path / "source.db", True)
    result = p3._run_job(tmp_path)
    print("RC", result.returncode)
    meta_path = tmp_path / "index.faiss.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    print("META", meta)
    index_path = tmp_path / "index.faiss"
    print("BUILT", _try(index_path, p3.MODEL))
    print("BUILT other model", _try(index_path, "other-model"))
    meta_path.write_text(json.dumps({**meta, "id_source": "video_embeddings.rowid"}), encoding="utf-8")
    print("ROWID", _try(index_path, p3.MODEL))
    print("ROWID other model", _try(index_path, "other-model"))
    meta_path.write_text(json.dumps({k: v for k, v in meta.items() if k != "id_source"}), encoding="utf-8")
    print("UNSET", _try(index_path, p3.MODEL))
    assert False
