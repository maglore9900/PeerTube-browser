import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import ENGINE_PY  # noqa: E402

JOB = ROOT / "engine" / "server" / "db" / "jobs" / "precompute-similar-ann.py"
VECTORS = {1: (1.0, 0.0, 0.0, 0.0), 2: (0.8, 0.6, 0.0, 0.0), 3: (0.0, 1.0, 0.0, 0.0), 4: (0.0, 0.6, 0.8, 0.0), 5: (0.0, 0.0, 1.0, 0.0), 6: (0.0, 0.0, 0.6, 0.8), 7: (0.0, 0.0, 0.0, 1.0), 8: (0.6, 0.0, 0.0, 0.8)}
BUILDER = """
import sqlite3, sys
import faiss, numpy as np
db, index_path, dim = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = sqlite3.connect(db).execute("SELECT rowid, embedding FROM video_embeddings WHERE length(embedding) = ?", (dim * 4,)).fetchall()
vectors = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
index = faiss.index_factory(dim, "IDMap2,IVF1,Flat", faiss.METRIC_INNER_PRODUCT)
index.train(vectors)
index.add_with_ids(vectors, np.array([r[0] for r in rows], dtype=np.int64))
faiss.write_index(index, index_path)
print("ntotal", index.ntotal)
"""


def _run(tmp_path, out, *args):
    return subprocess.run([str(ENGINE_PY), str(JOB), "--db", str(tmp_path / "source.db"), "--index", str(tmp_path / "index.faiss"), "--out", str(out), *args], cwd=tmp_path, capture_output=True, text=True, timeout=120)


def test_probe(tmp_path):
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL)")
    rows = [(r, f"v{r}", "live.example", struct.pack("<4f", *v), 4, "probe-model") for r, v in VECTORS.items()]
    rows.append((9, "v9", "live.example", struct.pack("<3f", 1.0, 1.0, 1.0), 4, "probe-model"))
    conn.executemany("INSERT INTO video_embeddings (rowid, video_id, instance_domain, embedding, embedding_dim, model_name) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    built = subprocess.run([str(ENGINE_PY), "-c", BUILDER, str(tmp_path / "source.db"), str(tmp_path / "index.faiss"), "4"], capture_output=True, text=True, timeout=120)
    print("BUILD rc", built.returncode, "stdout", repr(built.stdout), "stderr", repr(built.stderr))
    (tmp_path / "index.faiss.json").write_text(json.dumps({"model_name": "probe-model", "embedding_dim": 4}))
    out = tmp_path / "cache.db"
    seed = _run(tmp_path, out, "--reset-only")
    print("SEED rc", seed.returncode, repr(seed.stderr))
    c = sqlite3.connect(out)
    for vid, dom in [("v1", "live.example"), ("v2", "live.example"), ("v3", "live.example"), ("gone1", "live.example"), ("gone2", "live.example"), ("v5", ""), ("v9", "live.example")]:
        c.execute("INSERT INTO similarity_sources VALUES (?, ?, 1)", (vid, dom))
        c.execute("INSERT INTO similarity_items VALUES (?, ?, 'sentinel-target', 'sentinel.example', 0.5, 1)", (vid, dom))
    c.commit()
    c.close()
    run = _run(tmp_path, out, "--refresh-existing", "--cpu", "--top-k", "3")
    print("RUN rc", run.returncode, "stderr", repr(run.stderr))
    c = sqlite3.connect(out)
    print("SOURCES", c.execute("SELECT * FROM similarity_sources ORDER BY video_id, instance_domain").fetchall())
    print("ITEMS", c.execute("SELECT * FROM similarity_items ORDER BY source_video_id, source_instance_domain, rank").fetchall())
    missing = tmp_path / "missing.db"
    run = _run(tmp_path, missing, "--refresh-existing", "--cpu", "--top-k", "3")
    print("MISSING rc", run.returncode, "stderr", repr(run.stderr), "exists", missing.exists())
