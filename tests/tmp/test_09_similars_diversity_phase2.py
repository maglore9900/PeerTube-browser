"""Up-next's floored ANN fallback, checked against the session Engine and the shared similarity-cache.db.

- For the linux and cooking seeds, whose cache entry holds between 1 and 47 rows, POST /recommendations at limit=48 returns 48 rows, and at limit=30 returns 30. Each page's rows are distinct by (video_uuid, instance_domain) and by video_id::instance_domain, and every row's debug similarity_score is at or above SIMILAR_VIDEO_TAIL_MIN_SCORE. The seed's similarity_sources and similarity_items rows, read through a read-only connection, are the same before and after both requests.
- A linux up-next request adds at least one `[similar-server] ann_fallback` line to the Engine log. Every such line reports restored_nprobe equal to DEFAULT_NPROBE, which is also the value in the startup ann_nprobe_configured lines, and reports searching at an nprobe on R2's ladder (SIMILAR_VIDEO_NPROBE doubling up to SIMILAR_VIDEO_MAX_NPROBE), above it. A raw-vector POST /recommendations at limit=96 for the music seed's embedding returns the same ordered keys before and after that request; the same index searched in a child process reproduces that page at DEFAULT_NPROBE and serves a different one at 1 and at every nprobe on the ladder. The q=music&limit=20 search runs its vector half and returns 20 rows, with the same ordered keys before and after that request. A home POST /recommendations {} returns BATCH_SIZE rows with mode "home", not the random fallback, both before and after that request.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, dataset, embedding_of, engine  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"
SERVER_CONFIG = SERVER_DIR / "api" / "server_config.py"
# Seeds whose cache entry is shorter than a page: up-next served them 18 and 17 rows at limit=30 and limit=48 before this phase.
SHORT_SEED_QUERIES = ("linux", "cooking")
FILL_LIMIT = 48
# Deeper than the cached entry and short of 48, the value default_limit, BATCH_SIZE and the pool target share, so a page padded to 48 whatever the request reads 48 here.
PAGE_LIMIT = 30
SEARCH_PATH = "/api/v1/search/videos?q=music&limit=20"
SEARCH_ROWS = 20
FALLBACK_PREFIX = "[similar-server] ann_fallback"
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
LOG_WAIT_SECONDS = 5
# The music seed's raw-vector page at limit=96 moved at nprobe 1, 16, 32, 64 and 128 against 24 (probe); the linux and cooking pages did not move at 16 and up.
VECTOR_QUERY = "music"
VECTOR_LIMIT = 96
# The nprobe the IVF holds when read from file, before startup's set_nprobe.
UNSET_NPROBE = 1
# Searches the Engine's index file the way the raw-vector route does, at each nprobe given, and prints the ordered keys per nprobe.
ANN_CHILD = textwrap.dedent(
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
    root, vector, nprobes, limit = sys.argv[3], np.array(json.loads(sys.argv[4]), dtype=np.float32), json.loads(sys.argv[5]), int(sys.argv[6])
    vector = (vector / np.linalg.norm(vector)).astype(np.float32)
    db = connect_readonly_db(Path(root) / c.DEFAULT_DB_PATH)
    index = faiss.read_index(root + "/" + c.DEFAULT_INDEX_PATH, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
    ivf = faiss.extract_index_ivf(index)
    pages = {}
    for nprobe in nprobes:
        ivf.nprobe = nprobe
        rowids, _ = search_index(index, vector, limit, None)
        meta = fetch_metadata(db, rowids, error_threshold=c.VIDEO_ERROR_THRESHOLD)
        pages[str(nprobe)] = [[meta[r]["video_id"], meta[r]["instance_domain"]] for r in rowids if r in meta]
    print(json.dumps(pages))
    """
)


def _config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(engine, query: str) -> dict:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    return body["rows"][0]


def _cache_entry(video_id: str, instance_domain: str) -> tuple[list[tuple], list[tuple]]:
    """The seed's similarity_sources and similarity_items rows, read through a read-only connection: the cache is shared with main."""
    path = ROOT / _config().DEFAULT_SIMILARITY_DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sources = conn.execute("SELECT video_id, instance_domain, computed_at FROM similarity_sources WHERE video_id = ? AND instance_domain = ?", (video_id, instance_domain)).fetchall()
        items = conn.execute("SELECT similar_video_id, similar_instance_domain, score, rank FROM similarity_items WHERE source_video_id = ? AND source_instance_domain = ? ORDER BY rank, similar_video_id, similar_instance_domain", (video_id, instance_domain)).fetchall()
    finally:
        conn.close()
    return sources, items


def _messages(log_path: Path, prefix: str) -> list[str]:
    messages = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("message"), str) and payload["message"].startswith(prefix):
            messages.append(payload["message"])
    return messages


def _tokens(message: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in message.split() if "=" in token)


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _nprobe_steps(config) -> list[int]:
    """R2's fallback nprobes: SIMILAR_VIDEO_NPROBE, doubled each step and clamped to SIMILAR_VIDEO_MAX_NPROBE."""
    steps = [config.SIMILAR_VIDEO_NPROBE]
    while steps[-1] < config.SIMILAR_VIDEO_MAX_NPROBE:
        steps.append(min(steps[-1] * 2, config.SIMILAR_VIDEO_MAX_NPROBE))
    return steps


def _vector_page(engine, vector: list[float]) -> list[list[str]]:
    """The live raw-vector route's ordered keys: a pure ANN search on the shared index at whatever nprobe it holds."""
    status, body = engine.request("POST", f"/recommendations?vector={quote(json.dumps(vector))}&limit={VECTOR_LIMIT}", body={})
    assert status == 200 and body["seed"] == {"vector": True}, body.get("seed")
    return [[r["video_id"], r["instance_domain"]] for r in body["rows"]]


def _ann_pages(vector: list[float], nprobes: list[int]) -> dict[str, list[list[str]]]:
    """The same search run in a child process on the Engine's index file, at each nprobe, keyed by str(nprobe)."""
    run = subprocess.run([str(ENGINE_PY), "-c", ANN_CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), str(ROOT), json.dumps(vector), json.dumps(nprobes), str(VECTOR_LIMIT)], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("query", SHORT_SEED_QUERIES)
def test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged(engine, query):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    seed = _seed(engine, query)
    before = _cache_entry(seed["video_id"], seed["instance_domain"])
    # Control: the seed has a cache entry, and it is too short to fill the page on its own.
    assert 0 < len(before[1]) < FILL_LIMIT, (query, len(before[1]))

    for limit in (FILL_LIMIT, PAGE_LIMIT):
        status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}&debug=1", body={})
        assert status == 200, body
        rows = body["rows"]
        assert len(rows) == limit, (query, limit, len(rows))  # C1
        assert len({(r["video_uuid"], r["instance_domain"]) for r in rows}) == limit, _keys(rows)  # C1
        assert len({f"{r['video_id']}::{r['instance_domain']}" for r in rows}) == limit, _keys(rows)  # C1
        # The fallback adds nothing below the tail floor, so a row under it was padded from outside the seed's pool.
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]  # C1

    assert _cache_entry(seed["video_id"], seed["instance_domain"]) == before  # C1


def test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored(engine, dataset):
    config = _config()
    default_nprobe = str(config.DEFAULT_NPROBE)
    steps = _nprobe_steps(config)
    # Control: the shared index was started at DEFAULT_NPROBE, so it is the value a restore must return to.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(engine.db_path, NPROBE_PREFIX)]
    assert started and set(started) == {default_nprobe}, started

    probe_seed = _seed(engine, VECTOR_QUERY)
    vector = [round(value, 7) for value in embedding_of(dataset, probe_seed["video_id"], probe_seed["instance_domain"])]
    vector_before = _vector_page(engine, vector)
    pages = _ann_pages(vector, [config.DEFAULT_NPROBE, UNSET_NPROBE, *steps])
    # Control: the child reproduces the live page at DEFAULT_NPROBE, so it searches what the Engine searches.
    assert len(vector_before) == VECTOR_LIMIT and pages[default_nprobe] == vector_before, (len(vector_before), pages[default_nprobe][:3], vector_before[:3])
    # Control: an index left at any nprobe the fallback can search at, or at the unset one, serves a different page, so the after-page reads the index's nprobe.
    assert all(pages[str(nprobe)] != vector_before for nprobe in (UNSET_NPROBE, *steps)), [nprobe for nprobe in (UNSET_NPROBE, *steps) if pages[str(nprobe)] == vector_before]

    status, first = engine.request("GET", SEARCH_PATH)
    # Control: search runs its vector half on the shared index, which a leaked nprobe of 64 or more reorders.
    assert status == 200 and first["vectorSearch"] is True and len(first["rows"]) == SEARCH_ROWS, first
    # Control: before any fallback in this test, home is a full page in home mode, the shape it must keep.
    status, home = engine.request("POST", "/recommendations", body={})
    assert status == 200 and len(home["rows"]) == config.BATCH_SIZE and home["seed"].get("mode") == "home" and not home["seed"].get("random"), home.get("seed")

    fallbacks_before = len(_messages(engine.db_path, FALLBACK_PREFIX))
    seed = _seed(engine, "linux")
    status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8", body={})
    assert status == 200 and body["rows"], body
    deadline = time.time() + LOG_WAIT_SECONDS
    fallbacks = _messages(engine.db_path, FALLBACK_PREFIX)
    while len(fallbacks) <= fallbacks_before and time.time() < deadline:
        time.sleep(0.1)
        fallbacks = _messages(engine.db_path, FALLBACK_PREFIX)
    assert len(fallbacks) > fallbacks_before, f"the linux up-next request logged no {FALLBACK_PREFIX!r} line within {LOG_WAIT_SECONDS}s"  # C2
    assert all(_tokens(message).get("restored_nprobe") == default_nprobe for message in fallbacks), fallbacks  # C2
    # Each fallback searched above DEFAULT_NPROBE at a value the control above covers, so there was a raise to undo.
    assert all(int(_tokens(message).get("nprobe", 0)) in steps and int(_tokens(message)["nprobe"]) > config.DEFAULT_NPROBE for message in fallbacks), fallbacks  # C2
    # Read from the index itself, not from the fallback's report: a leaked raise reorders this page.
    assert _vector_page(engine, vector) == vector_before  # C2

    status, second = engine.request("GET", SEARCH_PATH)
    assert status == 200 and len(second["rows"]) == SEARCH_ROWS, second  # C2
    assert _keys(second["rows"]) == _keys(first["rows"])  # C2

    # Home draws afresh on every request, so its page is compared by shape, not by rows.
    status, home = engine.request("POST", "/recommendations", body={})
    assert status == 200, home
    assert len(home["rows"]) == config.BATCH_SIZE, len(home["rows"])  # C2
    assert home["seed"].get("mode") == "home" and not home["seed"].get("random"), home["seed"]  # C2
