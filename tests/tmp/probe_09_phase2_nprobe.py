import json
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, engine  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"

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
    db = connect_readonly_db(Path(root) / c.DEFAULT_DB_PATH)
    index = faiss.read_index(root + "/" + c.DEFAULT_INDEX_PATH, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    ivf = faiss.extract_index_ivf(index)
    print("ivf", type(ivf).__name__, "nprobe0", ivf.nprobe, "hasattr wrapper nprobe", hasattr(index, "nprobe"), file=sys.stderr)
    encoder = QueryEncoder(c.QUERY_ENCODER_MODEL, device=c.QUERY_ENCODER_DEVICE, idle_seconds=0)
    server = types.SimpleNamespace(db=db, db_lock=threading.Lock(), search_db=db, search_db_lock=threading.Lock(), index=index, index_lock=threading.Lock(), query_encoder=encoder, statement_timeout_seconds=0, video_error_threshold=c.VIDEO_ERROR_THRESHOLD)
    out = {}
    for nprobe in (24, 32, 64, 128, 24):
        ivf.nprobe = nprobe
        rows, total = search_videos(server, "music", page=1, limit=20, sort="relevance", max_tokens=c.SEARCH_MAX_QUERY_TOKENS, max_token_length=c.SEARCH_MAX_TOKEN_LENGTH, candidate_pool=c.SEARCH_CANDIDATE_POOL, rrf_k=c.SEARCH_RRF_K, lexical_weight=c.SEARCH_WEIGHT_LEXICAL, vector_weight=c.SEARCH_WEIGHT_VECTOR)
        out.setdefault(str(nprobe), []).append([[r["video_id"], r["instance_domain"]] for r in rows])
    print(json.dumps(out))
    """
)


def _keys(rows):
    return [[r["video_id"], r["instance_domain"]] for r in rows]


def test_search_page_at_each_nprobe():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), str(ROOT)], capture_output=True, text=True, timeout=600)
    print("rc", run.returncode, run.stderr[-3000:])
    out = json.loads(run.stdout.strip().splitlines()[-1])
    base = out["24"][0]
    print("24 repeat equal", out["24"][0] == out["24"][1])
    for nprobe in ("32", "64", "128"):
        page = out[nprobe][0]
        print(nprobe, "equal to 24:", page == base, "same set:", sorted(map(tuple, page)) == sorted(map(tuple, base)), "first diff at", next((i for i, (a, b) in enumerate(zip(page, base)) if a != b), None))
    assert False, "probe"


def test_live_search_uses_vectors(engine):
    status, body = engine.request("GET", "/api/v1/search/videos?q=music&limit=20")
    print("status", status, "vectorSearch", body.get("vectorSearch"), "rows", len(body["rows"]))
    for line in engine.db_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        message = str(payload.get("message", ""))
        if message.startswith("[search]") or "query-encoder" in message:
            print("LOG", message)
    assert False, "probe"
