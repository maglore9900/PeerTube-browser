import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"
DB = ROOT / "engine" / "server" / "db" / "whitelist.db"
INDEX = ROOT / "engine" / "server" / "db" / "whitelist-video-embeddings.faiss"
RANDOM_CACHE = ROOT / "engine" / "server" / "db" / "random-cache.db"

CHILD = """
import sys, sqlite3, faiss
sys.path.insert(0, sys.argv[1])
from data.embedding_space import resolve_embedding_space, assert_index_matches_embeddings
from pathlib import Path
db = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
dim, model = resolve_embedding_space(db)
index = faiss.read_index(sys.argv[3], faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
print("ntotal", index.ntotal, "d", index.d, "dim", dim, "model", model)
try:
    assert_index_matches_embeddings(Path(sys.argv[3]), index, dim, model)
    print("GATE OK")
except RuntimeError as exc:
    print("GATE RAISED:", exc)
"""


def test_probe():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(video_embeddings)")]
    print("video_embeddings columns:", cols)
    print("video_embeddings indexes:", conn.execute("SELECT name, sql FROM sqlite_master WHERE tbl_name='video_embeddings' AND type='index'").fetchall())
    print("rows:", conn.execute("SELECT COUNT(*) FROM video_embeddings").fetchone())
    sidecar = Path(f"{INDEX}.json")
    print("index exists:", INDEX.exists(), "sidecar exists:", sidecar.exists())
    if sidecar.exists():
        meta = json.loads(sidecar.read_text())
        print("sidecar:", {k: v for k, v in meta.items()})
    if RANDOM_CACHE.exists():
        rc = sqlite3.connect(f"file:{RANDOM_CACHE}?mode=ro", uri=True)
        print("random-cache tables:", rc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
    else:
        print("random-cache absent")
    res = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(ROOT / "engine" / "server"), str(DB), str(INDEX)], capture_output=True, text=True)
    print("child exit", res.returncode)
    print(res.stdout)
    print(res.stderr[-3000:])
    assert False, "probe"
