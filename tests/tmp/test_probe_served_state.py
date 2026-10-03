import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "engine" / "server" / "db"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"


def test_probe():
    meta_path = DB / "whitelist-video-embeddings.faiss.json"
    print("sidecar exists", meta_path.exists())
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        print("sidecar", {k: v for k, v in meta.items() if k != "nlist"})
    conn = sqlite3.connect(f"file:{DB / 'whitelist.db'}?mode=ro", uri=True)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(video_embeddings)")]
    print("video_embeddings cols", cols)
    if "ann_id" in cols:
        print("ann_id null count", conn.execute("SELECT COUNT(*) FROM video_embeddings WHERE ann_id IS NULL").fetchone())
        print("rows", conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone())
    for p in sorted(DB.glob("*.db")):
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            print(p.name, [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")][:12])
        except Exception as exc:
            print(p.name, "ERR", exc)
    code = (
        "import sys; sys.path.insert(0, 'engine/server');"
        "import faiss, sqlite3; from pathlib import Path;"
        "from data.embedding_space import assert_index_matches_embeddings, resolve_embedding_space;"
        "p = Path('engine/server/db/whitelist-video-embeddings.faiss');"
        "idx = faiss.read_index(str(p), faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY);"
        "db = sqlite3.connect('file:engine/server/db/whitelist.db?mode=ro', uri=True);"
        "d, m = resolve_embedding_space(db);"
        "ids = faiss.vector_to_array(faiss.extract_index_ivf(idx).invlists.get_ids(0) if False else idx.id_map) if hasattr(idx, 'id_map') else None;"
        "print('ntotal', idx.ntotal, 'type', type(idx).__name__);"
        "assert_index_matches_embeddings(p, idx, d, m); print('GATE OK')"
    )
    proc = subprocess.run([str(ENGINE_PY), "-c", code], cwd=ROOT, capture_output=True, text=True)
    print("rc", proc.returncode)
    print(proc.stdout[-2000:])
    print(proc.stderr[-2000:])
