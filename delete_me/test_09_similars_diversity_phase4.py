"""Up-next draws with and without likes, and the upnext_pool log line, checked against the session Engine and one started off DEFAULT_NPROBE.

- For the linux seed, ten POST /videos/similar?id=…&host=…&limit=8&debug=1 requests carrying five "music" search rows as likes, then ten carrying none, each return 8 distinct rows, and each set's mean pairwise Jaccard is below 0.5. Every row drawn with likes has a debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE. Each request writes exactly one `upnext_pool` line, under its own request id: likes_rerank=yes for each of the ten whose likes resolved, and likes_rerank=no for each of the ten without likes and for one whose likes name no known video.
- One linux request on each up-next route, POST /recommendations and POST /videos/similar, writes one `upnext_pool` line after running the ann_fallback. Across the session log, every `upnext_pool` line records as its steps the nprobe/search_limit pairs of the ann_fallback searches its own request ran (those logged between that request's start line and its pool line), each nprobe on R2's ladder and above DEFAULT_NPROBE. At least one line has steps other than `none`, and every such line reports the restored_nprobe the last of its request's searches read back, which equals DEFAULT_NPROBE, the value in the startup ann_nprobe_configured lines.
- An Engine whose startup nprobe is 16, with DEFAULT_NPROBE left at its shipped value in every module, logs ann_nprobe_configured=16 and ann_fallback searches that read back 16. There, one linux request on each up-next route writes one `upnext_pool` line whose steps are its own request's searches and whose restored_nprobe is 16, the value its last search read back, not DEFAULT_NPROBE.
"""
from __future__ import annotations

import fcntl
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, ClientBackend, _free_port, engine  # noqa: E402,F401

SERVER_CONFIG = ROOT / "engine" / "server" / "api" / "server_config.py"
PAGE_LIMIT = 8
REFRESHES = 10
MAX_MEAN_JACCARD = 0.5
LIKE_COUNT = 5
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
LIKES_HEADERS = {"X-Client-IP": "192.0.2.140"}
POOL_HEADERS = {"X-Client-IP": "192.0.2.141"}
SERVER_PREFIX = "[similar-server]"
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
FALLBACK_PREFIX = "[similar-server] ann_fallback"
# Logged once per seeded request before its pool is built, with likes=yes only when the request's likes resolved to videos.
PROFILE_PREFIX = "[recommendations] profile="
POOL_LINE = re.compile(r"\[similar-server\]\[(\w+)\] upnext_pool ")
START_LINE = re.compile(r"\[similar-server\]\[(\w+)\] start ")
STEPS = re.compile(r"\d+/\d+->\d+(?:,\d+/\d+->\d+)*")
LOG_WAIT_SECONDS = 5
# Neither DEFAULT_NPROBE (24) nor the IVF's unset value (1), and below R2's ladder, so a restore to it is a value only the read-back carries.
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


def _config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _search(engine, query: str, limit: int) -> list[dict]:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit={limit}")
    assert status == 200 and body["rows"], body
    return body["rows"]


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


def _mean_jaccard(sets: list[set]) -> float:
    pairs = list(itertools.combinations(sets, 2))
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


def _nprobe_steps(config) -> list[int]:
    """R2's fallback nprobes: SIMILAR_VIDEO_NPROBE, doubled each step and clamped to SIMILAR_VIDEO_MAX_NPROBE."""
    steps = [config.SIMILAR_VIDEO_NPROBE]
    while steps[-1] < config.SIMILAR_VIDEO_MAX_NPROBE:
        steps.append(min(steps[-1] * 2, config.SIMILAR_VIDEO_MAX_NPROBE))
    return steps


def _pool_lines(messages: list[str]) -> list[str]:
    return [message for message in messages if POOL_LINE.match(message)]


def _requests(engine, path: str, headers: dict[str, str], body: dict, count: int) -> tuple[list[list[dict]], list[str], list[str]]:
    """Send `count` requests one after another; return their pages, the upnext_pool lines and the profile lines they logged."""
    pool_before = len(_pool_lines(_messages(engine.db_path, SERVER_PREFIX)))
    profiles_before = len(_messages(engine.db_path, PROFILE_PREFIX))
    pages = []
    for _ in range(count):
        status, response = engine.request("POST", path, headers=headers, body=body)
        assert status == 200, response
        pages.append(response["rows"])
    deadline = time.time() + LOG_WAIT_SECONDS
    lines = _pool_lines(_messages(engine.db_path, SERVER_PREFIX))[pool_before:]
    while len(lines) < count and time.time() < deadline:
        time.sleep(0.1)
        lines = _pool_lines(_messages(engine.db_path, SERVER_PREFIX))[pool_before:]
    return pages, lines, _messages(engine.db_path, PROFILE_PREFIX)[profiles_before:]


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


def test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor(engine):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    seed = _search(engine, "linux", 1)[0]
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in _search(engine, "music", LIKE_COUNT)]
    # Control: five distinct likes, none of them the seed.
    assert len({(like["uuid"], like["host"]) for like in likes}) == LIKE_COUNT and (seed["video_uuid"], seed["instance_domain"]) not in {(like["uuid"], like["host"]) for like in likes}, likes
    path = f"/videos/similar?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE_LIMIT}&debug=1"

    # Liked draws go first, so a personalized_score stamp that outlived its request would show on the plain draws' lines.
    liked, liked_lines, liked_profiles = _requests(engine, path, LIKES_HEADERS, {"likes": likes}, REFRESHES)
    plain, plain_lines, plain_profiles = _requests(engine, path, LIKES_HEADERS, {}, REFRESHES)
    # Control: every liked request resolved its likes, and no plain request had any.
    assert liked_profiles == [liked_profiles[0]] * REFRESHES and liked_profiles[0].endswith(" likes=yes"), liked_profiles
    assert plain_profiles == [plain_profiles[0]] * REFRESHES and plain_profiles[0].endswith(" likes=no"), plain_profiles

    for rows in liked + plain:
        assert len(rows) == PAGE_LIMIT and len(set(_keys(rows))) == PAGE_LIMIT, _keys(rows)  # C1
    # The likes' pull must not reach outside the seed's pool, which holds nothing under the tail floor; observed at or above 0.725 today.
    assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for rows in liked for r in rows), [r["debug"]["similarity_score"] for rows in liked for r in rows]  # C1
    # Observed about 0.16 with likes and 0.14 without, drawing before the rerank; a window reranked by likes and cut to its top 8 repeats one page and scores 1.0.
    liked_mean = _mean_jaccard([set(_keys(rows)) for rows in liked])
    assert liked_mean < MAX_MEAN_JACCARD, (liked_mean, [_keys(rows) for rows in liked])  # C1
    plain_mean = _mean_jaccard([set(_keys(rows)) for rows in plain])
    assert plain_mean < MAX_MEAN_JACCARD, (plain_mean, [_keys(rows) for rows in plain])  # C1

    # Ten lines under ten distinct request ids tie each line to one request, so the liked ones are exactly the first ten.
    assert len(liked_lines) == REFRESHES, liked_lines  # C1
    assert [_tokens(line).get("likes_rerank") for line in liked_lines] == ["yes"] * REFRESHES, liked_lines  # C1
    assert len(plain_lines) == REFRESHES, plain_lines  # C1
    assert [_tokens(line).get("likes_rerank") for line in plain_lines] == ["no"] * REFRESHES, plain_lines  # C1
    assert len({POOL_LINE.match(line).group(1) for line in liked_lines + plain_lines}) == 2 * REFRESHES, liked_lines + plain_lines

    # Likes that name no known video leave nothing to rerank by, so a line keyed on the body carrying likes, rather than on a rerank, reads yes here.
    unknown = [{"uuid": like["uuid"] + "-absent", "host": like["host"]} for like in likes]
    _, unknown_lines, unknown_profiles = _requests(engine, path, LIKES_HEADERS, {"likes": unknown}, 1)
    assert len(unknown_profiles) == 1 and unknown_profiles[0].endswith(" likes=no"), unknown_profiles
    assert [_tokens(line).get("likes_rerank") for line in unknown_lines] == ["no"], unknown_lines  # C1


def test_every_upnext_pool_line_records_the_fallback_steps_its_request_ran_and_nprobe_restored_to_default(engine):
    config = _config()
    default_nprobe = str(config.DEFAULT_NPROBE)
    ladder = _nprobe_steps(config)
    # Control: the shared index was started at DEFAULT_NPROBE, so it is the value a restore must return to.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(engine.db_path, NPROBE_PREFIX)]
    assert started and set(started) == {default_nprobe}, started

    seed = _search(engine, "linux", 1)[0]
    query = f"?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE_LIMIT}"
    # One request on each up-next route, so the session-wide checks below cover both routes even when this test runs alone.
    own = []
    for route in ("/recommendations", "/videos/similar"):
        _, lines, _ = _requests(engine, route + query, POOL_HEADERS, {}, 1)
        assert len(lines) == 1, (route, lines)  # C2
        own.append(lines[0])
    pools = _pools_with_fallbacks(_messages(engine.db_path, SERVER_PREFIX))
    # Control: both requests ran the fallback; every similarity-cache.db entry holds at most 20 rows, short of the 48-row pool target (probe).
    assert [bool(fallbacks) for line, fallbacks in pools if line in own] == [True, True], pools

    for line, fallbacks in pools:
        # A line's steps are the searches its own request ran: not a formatted plan, and not `none` when searches ran.
        assert _steps(line) == _searched(fallbacks), (line, fallbacks)  # C2
        # Each step searched above DEFAULT_NPROBE, so there was a raise for the restore to undo.
        assert all(nprobe in ladder and nprobe > config.DEFAULT_NPROBE for nprobe, _ in _steps(line)), line  # C2

    with_steps = [(line, fallbacks) for line, fallbacks in pools if _tokens(line).get("steps") != "none"]
    assert with_steps  # C2
    # On this Engine the read-back is always DEFAULT_NPROBE; the off-default test below is where a line typing DEFAULT_NPROBE instead of relaying the read-back fails.
    assert all(_tokens(line).get("restored_nprobe") == _tokens(fallbacks[-1]).get("restored_nprobe") == default_nprobe for line, fallbacks in with_steps), with_steps  # C2


def test_on_an_engine_started_off_default_nprobe_every_upnext_pool_line_reports_the_nprobe_its_fallback_restored(off_default_engine):
    config = _config()
    off_default = str(OFF_DEFAULT_NPROBE)
    # Control: this Engine started at OFF_DEFAULT_NPROBE while DEFAULT_NPROBE is the shipped value, and R2's ladder starts above it.
    started = [message[len(NPROBE_PREFIX):].split()[0] for message in _messages(off_default_engine.db_path, NPROBE_PREFIX)]
    assert started == [off_default] and config.DEFAULT_NPROBE != OFF_DEFAULT_NPROBE < config.SIMILAR_VIDEO_NPROBE, started

    seed = _search(off_default_engine, "linux", 1)[0]
    query = f"?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={PAGE_LIMIT}"
    lines = {route: _requests(off_default_engine, route + query, POOL_HEADERS, {}, 1)[1] for route in ("/recommendations", "/videos/similar")}
    fallbacks = _messages(off_default_engine.db_path, FALLBACK_PREFIX)
    # Control: the requests ran the fallback, and every search read back this Engine's startup nprobe, not DEFAULT_NPROBE (probe: restored_nprobe=16 on both routes).
    assert fallbacks and {_tokens(message).get("restored_nprobe") for message in fallbacks} == {off_default}, fallbacks

    for route, route_lines in lines.items():
        assert len(route_lines) == 1, (route, route_lines)  # C2
    pools = _pools_with_fallbacks(_messages(off_default_engine.db_path, SERVER_PREFIX))
    assert len(pools) == 2, pools
    for line, own in pools:
        assert own and _steps(line) == _searched(own), (line, own)  # C2
        # A line typing DEFAULT_NPROBE reads 24 here; only one relaying its own request's read-back reads OFF_DEFAULT_NPROBE.
        assert _tokens(line).get("restored_nprobe") == _tokens(own[-1]).get("restored_nprobe") == off_default, (line, own)  # C2
