"""Retired from `tests/active/test_similar.py` in build 35-upnext-tests-retired-by-random-draw (plan 20), step 8, by the operator's decision; issue 41 tracks their rewrite.

Each test here rests on a control that the shared `engine/server/db/similarity-cache.db` holds a short entry for the linux and cooking seeds (at most 20 rows when they were written), so up-next runs the floored ANN fallback. Main's cache was rebuilt in one `--top-k 1000` run on 2026-10-01 at 17:00 (one `computed_at` for every source). The linux seed's entry now holds 542 rows and cooking's 260, both up-next routes are served from the cache with `steps=none`, and every test fails on its control before it reaches the code it checks. Build 35 changed no Engine code and none of these tests. Kept readable here, and skipped. They depend on conftest's `ROOT`, `ENGINE_PY`, `ENGINE_SERVER`, `ENGINE_START_LOCK`, `BRIDGE_TOKEN`, `ClientBackend`, `_free_port` and `embedding_of`, and on the active file's `SERVER_DIR`, `SERVER_CONFIG`, `UPNEXT_PAGE`, `LOG_WAIT_SECONDS`, `SERVER_PREFIX`, `POOL_LINE`, `_config`, `_search`, `_keys`, `_messages`, `_tokens` and `_requests`, so a bare `pytest` run skips it.

`test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page` was retired here later in the same step 8, also by the operator's decision, for the same cause. Its control needs two plain home pages carrying the same five likes to share a row, which rested on the like-seeded layers drawing "from the same shallow pool". On the rebuilt cache that overlap is chance: over 14 observed pairs per seed, music's shared nothing in 7 and linux's and cooking's in none, and the suite run still drew a linux pair sharing nothing. It was the Engine's only test of home `exclude`; the ordered modes keep theirs in the active file. Issue 41 covers its rewrite too.

The retired module docstring sections read:

- A home request carrying `exclude` with a previous home page's rows returns none of them,
  where the same request without `exclude` repeats some, and still at least 45 rows: the fewest
  any plain home page returned in 24 measured draws. Skipping the excluded rows after mixing,
  with no spare candidates gathered, leaves about 27-37. Every request sends the same five
  likes, so the like-seeded layers draw from the same shallow pool and repeat across pages.

Up-next's floored ANN fallback, against the session Engine and the shared similarity-cache.db:

- For the linux and cooking seeds, whose cache entry holds between 1 and 47 rows, POST /recommendations at
  limit=48 returns 48 rows, and at limit=30 returns 30. Each page's rows are distinct by (video_uuid,
  instance_domain) and by video_id::instance_domain, and every row's debug similarity_score is at or above
  SIMILAR_VIDEO_TAIL_MIN_SCORE. The seed's source row and cached neighbours, read through a
  read-only connection, are the same before and after both requests.
- A linux up-next request adds at least one `[similar-server] ann_fallback` line to the Engine log. Every such
  line reports restored_nprobe equal to DEFAULT_NPROBE, which is also the value in the startup
  ann_nprobe_configured lines, and reports searching at an nprobe on the fallback ladder (SIMILAR_VIDEO_NPROBE
  doubling up to SIMILAR_VIDEO_MAX_NPROBE), above it. A raw-vector POST /recommendations at limit=96 with nsfw=1 for the
  music seed's embedding returns the same ordered keys before and after that request; the same index searched
  in a child process reproduces that page at DEFAULT_NPROBE and serves a different one at 1 and at every nprobe
  on the ladder. The q=music&limit=20 search runs its vector half and returns 20 rows, with the same ordered
  keys before and after that request. A home POST /recommendations {} returns BATCH_SIZE rows with mode
  "home", not the random fallback, both before and after that request.

- One linux request on each up-next route, POST /recommendations and POST /videos/similar, writes one
  `upnext_pool` line after running the ann_fallback. Across the session log, every `upnext_pool` line records
  as its steps the nprobe/search_limit pairs of the ann_fallback searches its own request ran (those logged
  between that request's start line and its pool line), each nprobe on the fallback ladder and above
  DEFAULT_NPROBE. At least one line has steps other than `none`, and every such line reports the
  restored_nprobe the last of its request's searches read back, which equals DEFAULT_NPROBE, the value in the
  startup ann_nprobe_configured lines.
- An Engine whose startup nprobe is 16, with DEFAULT_NPROBE left at its shipped value in every module, logs
  ann_nprobe_configured=16 and ann_fallback searches that read back 16. There, one linux request on each
  up-next route writes one `upnext_pool` line whose steps are its own request's searches and whose
  restored_nprobe is 16, the value its last search read back, not DEFAULT_NPROBE.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import textwrap
import time
from urllib.parse import quote

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")

# Seeds whose cache entry is shorter than a page: without the fallback, up-next served them 18 and 17 rows at limit=30 and limit=48.
SHORT_SEED_QUERIES = ("linux", "cooking")
FILL_LIMIT = 48
# Deeper than the cached entry and short of 48, the value default_limit, BATCH_SIZE and the pool target share, so a page padded to 48 whatever the request reads 48 here.
SHORT_PAGE_LIMIT = 30
LIKE_QUERIES = ("linux", "cooking", "music")
PLAIN_FLOOR = 45
FALLBACK_SEARCH_PATH = "/api/v1/search/videos?q=music&limit=20"
FALLBACK_SEARCH_ROWS = 20
FALLBACK_PREFIX = "[similar-server] ann_fallback"
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
# The music seed's raw-vector page at limit=96 moved at nprobe 1, 16, 32, 64 and 128 against 24 (observed); the linux and cooking pages did not move at 16 and up.
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
# Its own rate-limit bucket: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
POOL_HEADERS = {"X-Client-IP": "192.0.2.141"}
START_LINE = re.compile(r"\[similar-server\]\[(\w+)\] start ")
STEPS = re.compile(r"\d+/\d+->\d+(?:,\d+/\d+->\d+)*")
# Neither DEFAULT_NPROBE (24) nor the IVF's unset value (1), and below the fallback ladder, so a restore to it is a value only the read-back carries.
OFF_DEFAULT_NPROBE = 16
# The Engine has no nprobe setting, so this runs the real server.py with the real set_nprobe handed OFF_DEFAULT_NPROBE at startup; nothing else is replaced, and DEFAULT_NPROBE stays shipped in every module.
LAUNCH = """
import runpy, sys
from pathlib import Path
server, nprobe = Path(sys.argv[1]).resolve(), int(sys.argv[2])
sys.path[:0] = [str(server.parents[1]), str(server.parent)]
import data.ann
set_nprobe = data.ann.set_nprobe
data.ann.set_nprobe = lambda index, _configured: set_nprobe(index, nprobe)
sys.argv = [str(server)] + sys.argv[3:]
runpy.run_path(str(server), run_name="__main__")
"""


@pytest.fixture
def off_default_engine(tmp_path):
    """A second real Engine on the repo's dataset, started at OFF_DEFAULT_NPROBE, logging to its own file."""
    log_path = tmp_path / "engine.log"
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN, "RECOMMENDATIONS_DEBUG": "1"}
    with open(log_path, "w") as log:
        port = _free_port()
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen(
                [str(ENGINE_PY), "-c", LAUNCH, str(ENGINE_SERVER), str(OFF_DEFAULT_NPROBE), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"],
                env=env, stdout=log, stderr=log,
            )
            http = ClientBackend(f"http://127.0.0.1:{port}", log_path)
            deadline = time.time() + 120
            while proc.poll() is None and time.time() < deadline:
                try:
                    if http.request("GET", "/api/health")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.25)
        try:
            assert proc.poll() is None and http.request("GET", "/api/health")[0] == 200, f"off-default Engine did not start; see {log_path}"
            yield http
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=30)


def _cache_entry(video_id: str, instance_domain: str) -> tuple[list[tuple], list[tuple]]:
    """The seed's source row (with its computed_at) and its cached neighbours, read through a read-only connection: the cache is shared with main."""
    from data.similarity_cache import fetch_cached_similarities

    path = ROOT / _config().DEFAULT_SIMILARITY_DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sources = conn.execute("SELECT k.video_id, k.instance_domain, s.computed_at FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key WHERE k.video_id = ? AND k.instance_domain = ?", (video_id, instance_domain)).fetchall()
        items = [(entry["video_id"], entry["instance_domain"], entry["score"], entry["rank"]) for entry in fetch_cached_similarities(conn, {"video_id": video_id, "instance_domain": instance_domain}, 1000)]
    finally:
        conn.close()
    return sources, items


def _nprobe_steps(config) -> list[int]:
    """The fallback's nprobes: SIMILAR_VIDEO_NPROBE, doubled each step and clamped to SIMILAR_VIDEO_MAX_NPROBE."""
    steps = [config.SIMILAR_VIDEO_NPROBE]
    while steps[-1] < config.SIMILAR_VIDEO_MAX_NPROBE:
        steps.append(min(steps[-1] * 2, config.SIMILAR_VIDEO_MAX_NPROBE))
    return steps


def _vector_page(engine, vector: list[float]) -> list[list[str]]:
    """The live raw-vector route's ordered keys: a pure ANN search on the shared index at whatever nprobe it holds."""
    # nsfw=1 keeps the page a pure ANN search: filtered, the music seed's page drops a flagged hit and comes back 95 rows (observed).
    status, body = engine.request("POST", f"/recommendations?vector={quote(json.dumps(vector))}&limit={VECTOR_LIMIT}&nsfw=1", body={})
    assert status == 200 and body["seed"] == {"vector": True}, body.get("seed")
    return [[r["video_id"], r["instance_domain"]] for r in body["rows"]]


def _ann_pages(vector: list[float], nprobes: list[int]) -> dict[str, list[list[str]]]:
    """The same search run in a child process on the Engine's index file, at each nprobe, keyed by str(nprobe)."""
    run = subprocess.run([str(ENGINE_PY), "-c", ANN_CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), str(ROOT), json.dumps(vector), json.dumps(nprobes), str(VECTOR_LIMIT)], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def _pools_with_fallbacks(messages: list[str]) -> list[tuple[str, list[str]]]:
    """Each upnext_pool line, with the ann_fallback lines logged between its request's start line and it; the ann_fallback lines carry no id, and requests here run one at a time, so those are its own."""
    starts: dict[str, int] = {}
    pools = []
    for index, message in enumerate(messages):
        if START_LINE.match(message):
            starts[START_LINE.match(message).group(1)] = index
        elif POOL_LINE.match(message):
            request_id = POOL_LINE.match(message).group(1)
            assert request_id in starts, message
            pools.append((message, [m for m in messages[starts[request_id]:index] if m.startswith(FALLBACK_PREFIX)]))
    return pools


def _steps(message: str) -> list[tuple[int, int]]:
    """The (nprobe, search_limit) pairs an upnext_pool line records as its steps; `none` records no pairs."""
    steps = _tokens(message).get("steps", "")
    assert steps == "none" or STEPS.fullmatch(steps), message
    return [(int(nprobe), int(search_limit)) for nprobe, search_limit, _ in re.findall(r"(\d+)/(\d+)->(\d+)", steps)]


def _searched(fallbacks: list[str]) -> list[tuple[int, int]]:
    return [(int(_tokens(message)["nprobe"]), int(_tokens(message)["search_limit"])) for message in fallbacks]


@pytest.mark.parametrize("query", SHORT_SEED_QUERIES)
def test_a_short_cached_seed_fills_a_48_row_page_and_leaves_its_cache_entry_unchanged(engine, query):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    seed = _search(engine, query, 1)[0]
    before = _cache_entry(seed["video_id"], seed["instance_domain"])
    # Control: the seed has a cache entry, and it is too short to fill the page on its own.
    assert 0 < len(before[1]) < FILL_LIMIT, (query, len(before[1]))

    for limit in (FILL_LIMIT, SHORT_PAGE_LIMIT):
        status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}&debug=1", body={})
        assert status == 200, body
        rows = body["rows"]
        assert len(rows) == limit, (query, limit, len(rows))
        assert len({(r["video_uuid"], r["instance_domain"]) for r in rows}) == limit, _keys(rows)
        assert len({f"{r['video_id']}::{r['instance_domain']}" for r in rows}) == limit, _keys(rows)
        # The fallback adds nothing below the tail floor, so a row under it was padded from outside the seed's pool.
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]

    assert _cache_entry(seed["video_id"], seed["instance_domain"]) == before


def test_home_and_search_are_unchanged_by_an_upnext_fallback_and_nprobe_is_restored(engine, dataset):
    config = _config()
    default_nprobe = str(config.DEFAULT_NPROBE)
    steps = _nprobe_steps(config)
    # Control: the shared index was started at DEFAULT_NPROBE, so it is the value a restore must return to.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(engine.db_path, NPROBE_PREFIX)]
    assert started and set(started) == {default_nprobe}, started

    probe_seed = _search(engine, VECTOR_QUERY, 1)[0]
    vector = [round(value, 7) for value in embedding_of(dataset, probe_seed["video_id"], probe_seed["instance_domain"])]
    vector_before = _vector_page(engine, vector)
    pages = _ann_pages(vector, [config.DEFAULT_NPROBE, UNSET_NPROBE, *steps])
    # Control: the child reproduces the live page at DEFAULT_NPROBE, so it searches what the Engine searches.
    assert len(vector_before) == VECTOR_LIMIT and pages[default_nprobe] == vector_before, (len(vector_before), pages[default_nprobe][:3], vector_before[:3])
    # Control: an index left at any nprobe the fallback can search at, or at the unset one, serves a different page, so the after-page reads the index's nprobe.
    assert all(pages[str(nprobe)] != vector_before for nprobe in (UNSET_NPROBE, *steps)), [nprobe for nprobe in (UNSET_NPROBE, *steps) if pages[str(nprobe)] == vector_before]

    status, first = engine.request("GET", FALLBACK_SEARCH_PATH)
    # Control: search runs its vector half on the shared index, which a leaked nprobe of 64 or more reorders.
    assert status == 200 and first["vectorSearch"] is True and len(first["rows"]) == FALLBACK_SEARCH_ROWS, first
    # Control: before any fallback in this test, home is a full page in home mode, the shape it must keep.
    status, home = engine.request("POST", "/recommendations", body={})
    assert status == 200 and len(home["rows"]) == config.BATCH_SIZE and home["seed"].get("mode") == "home" and not home["seed"].get("random"), home.get("seed")

    fallbacks_before = len(_messages(engine.db_path, FALLBACK_PREFIX))
    seed = _search(engine, "linux", 1)[0]
    status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8", body={})
    assert status == 200 and body["rows"], body
    deadline = time.time() + LOG_WAIT_SECONDS
    fallbacks = _messages(engine.db_path, FALLBACK_PREFIX)
    while len(fallbacks) <= fallbacks_before and time.time() < deadline:
        time.sleep(0.1)
        fallbacks = _messages(engine.db_path, FALLBACK_PREFIX)
    assert len(fallbacks) > fallbacks_before, f"the linux up-next request logged no {FALLBACK_PREFIX!r} line within {LOG_WAIT_SECONDS}s"
    assert all(_tokens(message).get("restored_nprobe") == default_nprobe for message in fallbacks), fallbacks
    # Each fallback searched above DEFAULT_NPROBE at a value the control above covers, so there was a raise to undo.
    assert all(int(_tokens(message).get("nprobe", 0)) in steps and int(_tokens(message)["nprobe"]) > config.DEFAULT_NPROBE for message in fallbacks), fallbacks
    # Read from the index itself, not from the fallback's report: a leaked raise reorders this page.
    assert _vector_page(engine, vector) == vector_before

    status, second = engine.request("GET", FALLBACK_SEARCH_PATH)
    assert status == 200 and len(second["rows"]) == FALLBACK_SEARCH_ROWS, second
    assert _keys(second["rows"]) == _keys(first["rows"])

    # Home draws afresh on every request, so its page is compared by shape, not by rows.
    status, home = engine.request("POST", "/recommendations", body={})
    assert status == 200, home
    assert len(home["rows"]) == config.BATCH_SIZE, len(home["rows"])
    assert home["seed"].get("mode") == "home" and not home["seed"].get("random"), home["seed"]


def test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default(engine):
    config = _config()
    default_nprobe = str(config.DEFAULT_NPROBE)
    ladder = _nprobe_steps(config)
    # Control: the shared index was started at DEFAULT_NPROBE, so it is the value a restore must return to.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(engine.db_path, NPROBE_PREFIX)]
    assert started and set(started) == {default_nprobe}, started

    seed = _search(engine, "linux", 1)[0]
    query = f"?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_PAGE}"
    # One request on each up-next route, so the session-wide checks below cover both routes even when this test runs alone.
    own = []
    for route in ("/recommendations", "/videos/similar"):
        _, lines, _ = _requests(engine, route + query, POOL_HEADERS, {}, 1)
        assert len(lines) == 1, (route, lines)
        own.append(lines[0])
    pools = _pools_with_fallbacks(_messages(engine.db_path, SERVER_PREFIX))
    # Control: both requests ran the fallback; every similarity-cache.db entry holds at most 20 rows, short of the 48-row pool target (observed).
    assert [bool(fallbacks) for line, fallbacks in pools if line in own] == [True, True], pools

    for line, fallbacks in pools:
        # A line's steps are the searches its own request ran: not a formatted plan, and not `none` when searches ran.
        assert _steps(line) == _searched(fallbacks), (line, fallbacks)
        # Each step searched above DEFAULT_NPROBE, so there was a raise for the restore to undo.
        assert all(nprobe in ladder and nprobe > config.DEFAULT_NPROBE for nprobe, _ in _steps(line)), line

    with_steps = [(line, fallbacks) for line, fallbacks in pools if _tokens(line).get("steps") != "none"]
    assert with_steps
    # On this Engine the read-back is always DEFAULT_NPROBE; the off-default test below is where a line typing DEFAULT_NPROBE instead of relaying the read-back fails.
    assert all(_tokens(line).get("restored_nprobe") == _tokens(fallbacks[-1]).get("restored_nprobe") == default_nprobe for line, fallbacks in with_steps), with_steps


def test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored(off_default_engine):
    config = _config()
    off_default = str(OFF_DEFAULT_NPROBE)
    # Control: this Engine started at OFF_DEFAULT_NPROBE while DEFAULT_NPROBE is the shipped value, and the fallback ladder starts above it.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(off_default_engine.db_path, NPROBE_PREFIX)]
    assert started == [off_default] and config.DEFAULT_NPROBE != OFF_DEFAULT_NPROBE < config.SIMILAR_VIDEO_NPROBE, started

    seed = _search(off_default_engine, "linux", 1)[0]
    query = f"?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_PAGE}"
    lines = {route: _requests(off_default_engine, route + query, POOL_HEADERS, {}, 1)[1] for route in ("/recommendations", "/videos/similar")}
    fallbacks = _messages(off_default_engine.db_path, FALLBACK_PREFIX)
    # Control: the requests ran the fallback, and every search read back this Engine's startup nprobe, not DEFAULT_NPROBE (observed: restored_nprobe=16 on both routes).
    assert fallbacks and {_tokens(message).get("restored_nprobe") for message in fallbacks} == {off_default}, fallbacks

    for route, route_lines in lines.items():
        assert len(route_lines) == 1, (route, route_lines)
    pools = _pools_with_fallbacks(_messages(off_default_engine.db_path, SERVER_PREFIX))
    assert len(pools) == 2, pools
    for line, own in pools:
        assert own and _steps(line) == _searched(own), (line, own)
        # A line typing DEFAULT_NPROBE reads 24 here; only one relaying its own request's read-back reads OFF_DEFAULT_NPROBE.
        assert _tokens(line).get("restored_nprobe") == _tokens(own[-1]).get("restored_nprobe") == off_default, (line, own)


def _likes(engine, query: str) -> list[dict]:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=5")
    assert status == 200 and len(body["rows"]) == 5, body
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in body["rows"]]


def _home(engine, body: dict) -> list[dict]:
    status, payload = engine.request("POST", "/recommendations", body=body)
    assert status == 200, payload
    # An empty mix falls back to a random draw marked `random`; that draw is not a home page.
    assert payload["seed"].get("mode") == "home" and not payload["seed"].get("random"), payload["seed"]
    return payload["rows"]


def _key_set(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


@pytest.mark.parametrize("query", LIKE_QUERIES)
def test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page(engine, query):
    likes = _likes(engine, query)
    previous = _home(engine, {"likes": likes})
    plain = _home(engine, {"likes": likes})
    assert _key_set(previous) & _key_set(plain), "control: a plain page repeats none of the previous one"

    exclude = [{"id": r["video_id"], "host": r["instance_domain"]} for r in previous]
    page = _home(engine, {"likes": likes, "exclude": exclude})

    assert not _key_set(previous) & _key_set(page), sorted(_key_set(previous) & _key_set(page))
    assert len(page) >= PLAIN_FLOOR, len(page)
