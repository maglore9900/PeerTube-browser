import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, dataset, embedding_of, engine  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"
NPROBES = [24, 1, 16, 32, 64, 128, 24]

CHILD = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import faiss
    import numpy as np
    import server_config as c
    from data.ann import search_index
    from data.db import connect_readonly_db
    from data.metadata import fetch_metadata
    root = sys.argv[3]
    vectors = json.loads(sys.argv[4])
    nprobes = json.loads(sys.argv[5])
    limit = int(sys.argv[6])
    db = connect_readonly_db(Path(root) / c.DEFAULT_DB_PATH)
    index = faiss.read_index(root + "/" + c.DEFAULT_INDEX_PATH, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    ivf = faiss.extract_index_ivf(index)
    out = {}
    for name, values in vectors.items():
        vector = np.array(values, dtype=np.float32)
        vector = vector / np.linalg.norm(vector)
        for nprobe in nprobes:
            ivf.nprobe = nprobe
            rowids, scores = search_index(index, vector.astype(np.float32), limit, None)
            meta = fetch_metadata(db, rowids, error_threshold=c.VIDEO_ERROR_THRESHOLD)
            keys = [[meta[r]["video_id"], meta[r]["instance_domain"]] for r in rowids if r in meta]
            out.setdefault(name, {}).setdefault(str(nprobe), []).append(keys)
    print(json.dumps(out))
    """
)


def _seed(engine, query):
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    return body["rows"][0]


def test_rawvec(engine, dataset):
    vectors = {}
    live = {}
    for q in ("linux", "cooking", "music"):
        seed = _seed(engine, q)
        vec = embedding_of(dataset, seed["video_id"], seed["instance_domain"])
        vectors[q] = vec
        path = "/recommendations?vector=" + quote(json.dumps([round(v, 7) for v in vec])) + "&limit=96"
        print(q, "path len", len(path), "dim", len(vec))
        status, body = engine.request("POST", path, body={})
        print(q, "status", status, "keys", list(body)[:6], "seed", body.get("seed"), "rows", len(body.get("rows", [])))
        live[q] = [[r["video_id"], r["instance_domain"]] for r in body.get("rows", [])]
        status2, body2 = engine.request("POST", path, body={})
        print(q, "repeat equal", [[r["video_id"], r["instance_domain"]] for r in body2.get("rows", [])] == live[q])
    t0 = time.time()
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), str(ROOT), json.dumps(vectors), json.dumps(NPROBES), "96"], capture_output=True, text=True, timeout=600)
    print("rc", run.returncode, "secs", round(time.time() - t0, 1), run.stderr[-1500:])
    out = json.loads(run.stdout.strip().splitlines()[-1])
    for q in vectors:
        base = out[q]["24"][0]
        print(q, "child24==live", base == live[q], "child rows", len(base), "live rows", len(live[q]), "24 repeat", out[q]["24"][0] == out[q]["24"][1], {n: out[q][n][0] != base for n in ("1", "16", "32", "64", "128")}, {n: next((i for i, (a, b) in enumerate(zip(out[q][n][0], base)) if a != b), None) for n in ("1", "16", "32", "64", "128")})
        if base != live[q]:
            print(q, "first live diff", next((i for i, (a, b) in enumerate(zip(live[q], base)) if a != b), None))
    assert False, "probe"
