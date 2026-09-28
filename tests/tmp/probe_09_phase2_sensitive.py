import json
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, engine  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"
QUERIES = ["music", "linux", "cooking", "news", "game", "travel", "science", "art", "history", "football"]
NPROBES = [24, 1, 16, 32, 64, 128, 24]

CHILD = textwrap.dedent(
    """
    import json, sys, threading, types
    from pathlib import Path
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import faiss
    import server_config as c
    from data.db import connect_readonly_db
    from data.query_encoder import QueryEncoder
    from data.search import search_videos
    root = sys.argv[3]
    queries = json.loads(sys.argv[4])
    nprobes = json.loads(sys.argv[5])
    db = connect_readonly_db(Path(root) / c.DEFAULT_DB_PATH)
    index = faiss.read_index(root + "/" + c.DEFAULT_INDEX_PATH, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    ivf = faiss.extract_index_ivf(index)
    encoder = QueryEncoder(c.QUERY_ENCODER_MODEL, device=c.QUERY_ENCODER_DEVICE, idle_seconds=0)
    server = types.SimpleNamespace(db=db, db_lock=threading.Lock(), search_db=db, search_db_lock=threading.Lock(), index=index, index_lock=threading.Lock(), query_encoder=encoder, statement_timeout_seconds=0, video_error_threshold=c.VIDEO_ERROR_THRESHOLD)
    out = {}
    for q in queries:
        for nprobe in nprobes:
            ivf.nprobe = nprobe
            rows, total = search_videos(server, q, page=1, limit=20, sort="relevance", max_tokens=c.SEARCH_MAX_QUERY_TOKENS, max_token_length=c.SEARCH_MAX_TOKEN_LENGTH, candidate_pool=c.SEARCH_CANDIDATE_POOL, rrf_k=c.SEARCH_RRF_K, lexical_weight=c.SEARCH_WEIGHT_LEXICAL, vector_weight=c.SEARCH_WEIGHT_VECTOR)
            out.setdefault(q, {}).setdefault(str(nprobe), []).append([[r["video_id"], r["instance_domain"]] for r in rows])
    print(json.dumps(out))
    """
)


def test_sensitivity(engine):
    live = {}
    for q in QUERIES:
        status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(q)}&limit=20")
        live[q] = (status, body.get("vectorSearch"), [[r["video_id"], r["instance_domain"]] for r in body.get("rows", [])])
    import time
    t0 = time.time()
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), str(ROOT), json.dumps(QUERIES), json.dumps(NPROBES)], capture_output=True, text=True, timeout=900)
    print("rc", run.returncode, "secs", round(time.time() - t0, 1), run.stderr[-1500:])
    out = json.loads(run.stdout.strip().splitlines()[-1])
    for q in QUERIES:
        base = out[q]["24"][0]
        status, vec, live_rows = live[q]
        print(q, "live", status, vec, len(live_rows), "child24==live", base == live_rows, "24 repeat", out[q]["24"][0] == out[q]["24"][1], "rows", len(base), {n: out[q][n][0] != base for n in ("1", "16", "32", "64", "128")})
    assert False, "probe"
