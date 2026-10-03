"""Probe: what the served dataset and index sidecar look like, and what the Engine's startup gate says about them."""

import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
SERVER_DIR = ROOT / "engine" / "server"
DB = SERVER_DIR / "db" / "whitelist.db"
INDEX = SERVER_DIR / "db" / "whitelist-video-embeddings.faiss"

CHILD = """
import sys, json, sqlite3
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from data.embedding_space import resolve_embedding_space, assert_index_matches_embeddings
from data.ann_ids import assert_video_embeddings_has_ann_id
db = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
dim, model = resolve_embedding_space(db)
print("space", dim, model)
try:
    assert_video_embeddings_has_ann_id(db)
    print("has_ann_id ok")
except Exception as exc:
    print("has_ann_id raised", type(exc).__name__, exc)
try:
    assert_index_matches_embeddings(Path(sys.argv[3]), SimpleNamespace(d=dim), dim, model)
    print("gate ok")
except Exception as exc:
    print("gate raised", type(exc).__name__, exc)
"""


def test_probe() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    print("columns", [row[1] for row in conn.execute("PRAGMA table_info(video_embeddings)")])
    print("rows", conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone())
    meta_path = Path(f"{INDEX}.json")
    print("index exists", INDEX.exists(), "sidecar exists", meta_path.exists())
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        print("sidecar", {k: meta.get(k) for k in ("model_name", "embedding_dim", "id_source", "total", "built_at")})
    out = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR), str(DB), str(INDEX)], capture_output=True, text=True)
    print("child exit", out.returncode)
    print(out.stdout)
    print(out.stderr[-3000:])
    assert False, "probe"
