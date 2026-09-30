"""The Engine's feed and search responses, against a real Engine on the repo's dataset.

- Every row of a home, random, up-next and search response carries the `channel_id` and
  `account_url` that `whitelist.db` holds for that video: the identity the Client's
  per-profile blocks match on.
- Home and random serve more than the default page when asked for twice it, which the
  Client's over-fetch for visitors with blocks relies on.
- A home request carrying `exclude` with a previous home page's rows returns none of them,
  where the same request without `exclude` repeats some, and still at least 45 rows: the fewest
  any plain home page returned in 24 measured draws. Skipping the excluded rows after mixing,
  with no spare candidates gathered, leaves about 27-37. Every request sends the same five
  likes, so the like-seeded layers draw from the same shallow pool and repeat across pages.
- `/recommendations` and `/videos/similar` answer 400 "Too many exclude entries in request body"
  to 501 `exclude` entries and 200 to 500, the entries being real videos from `whitelist.db`.
- `SimilarHandler._rate_limit_check`, with the client address resolved by the real
  `_get_client_ip` and bucketed in a real `RateLimiter` (one request per bucket): with
  `X-Forwarded-For` and `X-Real-IP` but no `X-Client-IP` the bucket is the TCP peer, so a second
  request from the same peer is refused whatever it forwards and another peer gets its own
  bucket; with `X-Client-IP` the bucket is its stripped value even when `X-Forwarded-For` is also
  sent. This one runs under the Engine interpreter in a child process, not against the `engine`
  fixture.
- POST `/videos/similar` validates likes as `/recommendations` does: `DEFAULT_CLIENT_LIKES_MAX + 1`
  likes, a blank uuid at index 0, a non-object entry at index 0 and a non-string host at index 2
  each get exactly one `respond_json(handler, 400, body)` with the body `/recommendations` gives,
  and the likes are never parsed, set on the request context or handled. `DEFAULT_CLIENT_LIKES_MAX`
  well-formed likes are parsed once, resolved, set on the request context and handled. These run
  `SimilarHandler._handle_similar_request` under the Engine interpreter in a child process, with
  the body reader, responder, request-context setters and DB lookup of likes patched.
- Under the Engine interpreter with `RECOMMENDATIONS_DEBUG` unset, the real
  `SimilarHandler._handle_similar`, on a stub server whose `recommendations_debug_enabled` is the
  imported flag, answers a debug request (with or without `random`) with one 403
  `{"error": "Debug mode is disabled"}` from the real `respond_json` and serves nothing, while a
  request not asking for debug is served. With `RECOMMENDATIONS_DEBUG=1` the same debug request is
  served with debug included.
- The `engine` fixture answers GET /api/health, OPTIONS /recommendations and /api/health,
  POST /recommendations, a malformed POST /recommendations (400) and an unknown route (404), each
  sent with an `Origin`, with no header starting `access-control-`.
- Under the Engine interpreter with `configure_engine_logging("verbose")`, `_handle_similar` on a
  `random=1` request whose random feed raises `RuntimeError`, `ValueError`, or a `ValueError` only
  containing a bad-request text sends exactly one 500 `{"error": "Recommendations request failed"}`
  through the real `respond_json`, and that case's stderr has an ERROR JSON line whose `traceback`
  runs through `_handle_similar` to the raised exception; a `ValueError` whose text is exactly
  `Invalid vector parameter`, `Vector dimension does not match embeddings` or `Vector norm is zero`
  sends exactly one 400 carrying that text.

Up-next's floored ANN fallback, against the session Engine and the shared similarity-cache.db:

- For the linux and cooking seeds, whose cache entry holds between 1 and 47 rows, POST /recommendations at
  limit=48 returns 48 rows, and at limit=30 returns 30. Each page's rows are distinct by (video_uuid,
  instance_domain) and by video_id::instance_domain, and every row's debug similarity_score is at or above
  SIMILAR_VIDEO_TAIL_MIN_SCORE. The seed's similarity_sources and similarity_items rows, read through a
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

Up-next's sampled page, against the session Engine:

- Ten unseeded POST /recommendations?id=…&host=…&limit=8&debug=1 requests for the linux seed each return 8
  distinct rows, every row's debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE, and the mean
  pairwise Jaccard of their key sets is below 0.5.
- The same request with &seed=11, sent twice, returns 8 rows in the same order both times, and with &seed=12
  returns a different ordered page.

Up-next draws with and without likes, and the upnext_pool log line, against the session Engine and one
started off DEFAULT_NPROBE:

- For the linux seed, ten POST /videos/similar?id=…&host=…&limit=8&debug=1 requests carrying five "music"
  search rows as likes, then ten carrying none, each return 8 distinct rows, and each set's mean pairwise
  Jaccard is below 0.5. Every row drawn with likes has a debug similarity_score at or above
  SIMILAR_VIDEO_TAIL_MIN_SCORE. Each request writes exactly one `upnext_pool` line, under its own request id:
  likes_rerank=yes for each of the ten whose likes resolved, and likes_rerank=no for each of the ten without
  likes and for one whose likes name no known video.
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

Feed modes, against the session Engine, with `FEED_MODES`, `ORDERED_FEED_MODES` and `VIDEO_ERROR_THRESHOLD` read under the Engine interpreter:

- An unseeded POST /recommendations whose `mode` is `bogus`, `HOT` or `home` (none of them in `FEED_MODES`) is answered 400 with exactly `{"error": "Unknown mode", "allowed": list(FEED_MODES)}`. `FEED_MODES` exists with no value repeated, and each of the five modes the requirements name, each value in `FEED_MODES`, an empty `mode` and no `mode` are answered 200.
- A seeded POST /recommendations (a real video's `id` and `host`, `seed=11`) with each of the five modes, `mode=bogus`, `mode=HOT` or an empty `mode` is answered 200 with the same `seed` payload (`mode` "upnext") and the same ordered rows as that request without `mode`.
- Each value of `FEED_MODES` outside `ORDERED_FEED_MODES` has a pre-build spelling (`recommendations` none, `random` `random=1`), and POST /recommendations with that `mode` answers the same `seed` as that spelling, with a full page: `{"user_id", "mode": "home"}` and no `random` key for `recommendations` (an empty `mode` too), `{"random": True}` for `random`.
- For each value of `ORDERED_FEED_MODES`: page 1 carrying five likes, page 1 carrying none, page 2 carrying page 1's rows as `exclude`, and page 3 carrying pages 1 and 2 plus the reference's last page (rows far past page 3) as `exclude` each answer a `seed` with neither a `random` nor a `mode` key. Page 1 is the same ordered rows with and without likes. Pages 1, 2 and 3 are full, share no `(video_id, instance_domain)`, and concatenate into the first rows of `fetch_ordered_page` for that order, read through the read-only `dataset` connection at the Engine's threshold with NSFW-flagged rows left out, rows on an active denylisted host or a blocked channel skipped. That reference is read before and after the requests and is the same both times.

The NSFW filter at the request edge, against the session Engine, with rows cross-checked against the non-empty set of keys whitelist.db flags nsfw = 1, read through the `dataset` connection:

- Ten listing paths are each sent with nsfw missing, empty, "0", "true" and " 1": POST /recommendations with mode recommendations (carrying five flagged likes), hot, recent and random; up-next for one flagged seed on POST /recommendations, POST /videos/similar and GET /videos/{id}/similar; POST /recommendations?random=1; the raw-vector POST /recommendations for that seed's embedding; and GET /api/v1/search/videos?q=hentai. Every response is 200, holds rows, and holds no flagged key. The random feeds are drawn 12 times per value and the mixed feed 3 times.
- Before each of those requests, the same path with nsfw=1 returns at least one flagged key on the same Engine (within 12 draws for the random feeds, 3 for the mixed feed). For mode=recommendations this means the mixer honours the opt-in and then filters the next request, so its flag is read per request, not frozen at build time.
"""
from __future__ import annotations

import fcntl
import http.client
import importlib.util
import itertools
import json
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from conftest import BRIDGE_TOKEN, ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, ClientBackend, _free_port, embedding_of, identity_of

# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
for _path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data.random_videos import fetch_ordered_page  # noqa: E402

SEARCH_QUERY = "music"
LIKE_QUERIES = ("linux", "cooking", "music")
PLAIN_FLOOR = 45
UPNEXT_PAGE = 8
EXCLUDE_CAP = 500


def _default_limit() -> int:
    spec = importlib.util.spec_from_file_location(
        "engine_server_config", ROOT / "engine" / "server" / "api" / "server_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.BATCH_SIZE)


def _rows(engine, route: str) -> list[dict]:
    if route == "search":
        status, body = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=20")
    elif route == "upnext":
        status, seed = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=1")
        assert status == 200, seed
        first = seed["rows"][0]
        status, body = engine.request(
            "POST", f"/recommendations?id={first['video_uuid']}&host={first['instance_domain']}&limit=8",
            body={})
    elif route == "random":
        status, body = engine.request("POST", "/recommendations?random=1", body={})
    else:
        status, body = engine.request("POST", "/recommendations", body={})
    assert status == 200, body
    return body["rows"]


@pytest.mark.parametrize("route", ["home", "random", "upnext", "search"])
def test_every_row_carries_the_channel_and_account_the_dataset_holds(engine, dataset, route):
    rows = _rows(engine, route)
    assert rows, f"{route} returned no rows to check"
    for row in rows:
        expected = identity_of(dataset, row["video_id"], row["instance_domain"])
        # A stored NULL would equal a missing key; the dataset holds none, and this keeps it so.
        assert expected["channel_id"] and expected["account_url"], row["video_id"]
        assert "channel_id" in row and "account_url" in row, (route, row["video_id"])
        assert row.get("channel_id") == expected["channel_id"], (route, row["video_id"])
        assert row.get("account_url") == expected["account_url"], (route, row["video_id"])


@pytest.mark.parametrize("path", ["/recommendations", "/recommendations?random=1"])
def test_home_and_random_return_more_than_the_default_page_when_asked_for_twice_it(engine, path):
    default = _default_limit()
    sep = "&" if "?" in path else "?"

    status, body = engine.request("POST", f"{path}{sep}limit={default}", body={})
    assert status == 200, body
    assert len(body["rows"]) == default  # control: the pool fills a default page

    status, body = engine.request("POST", f"{path}{sep}limit={default * 2}", body={})
    assert status == 200, body
    assert len(body["rows"]) > default, len(body["rows"])


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


def _upnext_path(engine, query: str, route: str = "/recommendations") -> str:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    seed = body["rows"][0]
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_PAGE}"


@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_a_feed_request_with_more_than_500_exclude_entries_is_refused_and_500_is_served(engine, dataset, route):
    path = _upnext_path(engine, "linux", route)
    rows = dataset.execute("SELECT video_id, instance_domain FROM videos LIMIT ?", (EXCLUDE_CAP + 1,)).fetchall()
    assert len(rows) == EXCLUDE_CAP + 1
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]

    status, body = engine.request("POST", path, body={"exclude": entries[:EXCLUDE_CAP]})
    assert status == 200 and body["rows"], body

    status, body = engine.request("POST", path, body={"exclude": entries})
    assert (status, body.get("error")) == (400, "Too many exclude entries in request body"), body


SERVER_DIR = ROOT / "engine" / "server"

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
_RATE_LIMIT_CHILD = textwrap.dedent(
    """
    import http.client, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers.similar import SimilarHandler
    from http_utils import RateLimiter

    out = []
    for sequence in json.loads(sys.argv[3]):
        limiter = RateLimiter(1, 3600)
        allowed = []
        for peer, headers in sequence:
            message = http.client.HTTPMessage()
            for name, value in headers.items():
                message[name] = value
            stub = types.SimpleNamespace(headers=message, client_address=(peer, 50000), server=types.SimpleNamespace(rate_limiter=limiter))
            stub._get_client_ip = types.MethodType(SimilarHandler._get_client_ip, stub)
            allowed.append(SimilarHandler._rate_limit_check(stub, "/recommendations"))
        out.append({"allowed": allowed, "buckets": sorted(limiter.requests)})
    print(json.dumps(out), flush=True)
    """
)


def test_engine_limiter_buckets_on_x_client_ip_else_the_tcp_peer():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    forwarded_sequence = [["127.0.0.1", {"X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Real-IP": "7.7.7.7"}], ["127.0.0.1", {"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "9.9.9.9"}], ["192.0.2.10", {"X-Forwarded-For": "6.6.6.6", "X-Real-IP": "7.7.7.7"}]]
    client_ip_sequence = [["127.0.0.1", {"X-Client-IP": " 203.0.113.9 ", "X-Forwarded-For": "6.6.6.6"}], ["127.0.0.1", {"X-Client-IP": "198.51.100.4", "X-Forwarded-For": "6.6.6.6"}]]
    run = subprocess.run([str(ENGINE_PY), "-c", _RATE_LIMIT_CHILD, str(SERVER_DIR / "api"), str(SERVER_DIR), json.dumps([forwarded_sequence, client_ip_sequence])], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    forwarded, client_ip = json.loads(run.stdout)

    # Control: X-Client-IP still wins over X-Forwarded-For and the peer, so a limiter bucketing every request on the peer cannot pass.
    assert client_ip == {"allowed": [True, True], "buckets": ["198.51.100.4:/recommendations", "203.0.113.9:/recommendations"]}
    # Bucketing on the first X-Forwarded-For hop reads [True, True, False]; on X-Real-IP the same; hardcoding loopback refuses the third.
    assert forwarded == {"allowed": [True, False, True], "buckets": ["127.0.0.1:/recommendations", "192.0.2.10:/recommendations"]}


# What the patched `_resolve_client_likes` returns: non-empty and unlike the handler's default `[]`, so only the resolved value reaching `set_request_client_likes` matches it.
RESOLVED_LIKES = [{"video_uuid": "resolved-sentinel", "instance_domain": "resolved.example"}]
# Runs each (path, body) case through the real `_handle_similar_request` and reports every call it made at the patched boundaries.
_LIKES_CHILD = textwrap.dedent(
    """
    import json, sys, types
    from unittest.mock import patch
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar

    class Handler:
        def __init__(self, path):
            self.path = path
            self.headers = {"content-length": "128"}
            self.server = types.SimpleNamespace(use_client_likes=True)
            self.handled = False

        def _rate_limit_check(self, _path):
            return True

        def _handle_similar(self, _params):
            self.handled = True

    resolved = json.loads(sys.argv[4])
    reports = []
    for path, body in json.loads(sys.argv[3]):
        handler = Handler(path)
        with (
            patch.object(similar, "read_json_body", return_value=body),
            patch.object(similar, "respond_json") as respond,
            patch.object(similar, "_parse_client_likes", wraps=similar._parse_client_likes) as parse,
            patch.object(similar, "_resolve_client_likes", return_value=resolved) as resolve,
            patch.object(similar, "set_request_client_likes") as set_likes,
            patch.object(similar, "clear_request_context") as clear,
        ):
            similar.SimilarHandler._handle_similar_request(handler, method="POST")
        reports.append({
            "likes_max": similar.DEFAULT_CLIENT_LIKES_MAX,
            "respond": [[c.args[0] is handler, *c.args[1:]] for c in respond.call_args_list],
            "parse": [c.args[0] for c in parse.call_args_list],
            "resolve": [[c.args[0] is handler.server, c.args[1]] for c in resolve.call_args_list],
            "set_likes": [list(c.args) for c in set_likes.call_args_list],
            "clear": clear.call_count,
            "handled": handler.handled,
        })
    print(json.dumps(reports))
    """
)


def _likes_max() -> int:
    spec = importlib.util.spec_from_file_location(
        "engine_server_config", ROOT / "engine" / "server" / "api" / "server_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.DEFAULT_CLIENT_LIKES_MAX)


def _handle_likes(*cases: tuple[str, dict]) -> list[dict]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _LIKES_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases), json.dumps(RESOLVED_LIKES)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout)


def _like_list(count: int) -> list[dict]:
    return [{"uuid": f"video-{idx}", "host": "example.com"} for idx in range(count)]


def _rejected(likes_max: int, body: dict) -> dict:
    # A request the likes check stops: one 400 to this handler, and nothing past it runs.
    return {"likes_max": likes_max, "respond": [[True, 400, body]], "parse": [], "resolve": [], "set_likes": [], "clear": 0, "handled": False}


def test_videos_similar_rejects_more_likes_than_allowed_with_the_recommendations_400_body():
    likes_max = _likes_max()
    body = {"likes": _like_list(likes_max + 1)}
    similar_report, recommendations_report = _handle_likes(("/videos/similar", body), ("/recommendations", body))

    expected = _rejected(likes_max, {"error": "Too many likes in request body", "max_allowed": likes_max, "received": likes_max + 1})
    assert recommendations_report == expected  # control: the body `/recommendations` gives (observed)
    assert similar_report == expected  # one 400 with that exact body, likes never parsed or set, request not handled
    assert similar_report == recommendations_report


@pytest.mark.parametrize("likes, reason, index", [
    ([{"uuid": "   ", "host": "example.com"}], "likes.uuid must be a non-empty string", 0),
    (["video-0"], "likes entry must be an object", 0),
    ([{"uuid": "video-0", "host": "example.com"}, {"uuid": "video-1", "host": "example.com"}, {"uuid": "video-2", "host": 7}], "likes.host must be a non-empty string", 2),
], ids=["blank-uuid", "non-object-entry", "non-string-host-after-two-valid"])
def test_videos_similar_rejects_a_malformed_likes_entry_with_the_recommendations_400_body(likes, reason, index):
    likes_max = _likes_max()
    similar_report, recommendations_report = _handle_likes(("/videos/similar", {"likes": likes}), ("/recommendations", {"likes": likes}))

    expected = _rejected(likes_max, {"error": "Invalid likes payload", "reason": reason, "index": index})
    assert recommendations_report == expected  # control: the body `/recommendations` gives (observed)
    assert similar_report == expected  # one 400 with that exact body, likes never parsed or set, request not handled
    assert similar_report == recommendations_report


def test_videos_similar_parses_resolves_and_handles_likes_at_the_limit():
    likes_max = _likes_max()
    body = {"likes": _like_list(likes_max)}
    (report,) = _handle_likes(("/videos/similar", body))

    assert report["likes_max"] == likes_max  # control: the handler checks against the same max this test sends
    assert report["respond"] == []  # no 400, nor any other response from the likes check
    assert report["parse"] == [body]  # `_parse_client_likes` runs once, on the body
    assert report["resolve"] == [[True, [{"video_uuid": f"video-{idx}", "instance_domain": "example.com"} for idx in range(likes_max)]]]  # every like reaches resolution
    assert report["set_likes"] == [[RESOLVED_LIKES, True]]  # what resolution returned, not the default `[]`, is set on the request context
    assert report["clear"] == 1
    assert report["handled"] is True


DEBUG_VAR = "RECOMMENDATIONS_DEBUG"
DEBUG_DISABLED = [403, {"error": "Debug mode is disabled"}]


def _debug_env(value: str | None) -> dict[str, str]:
    # The value goes only into a copy for the child, so a shell that exports the variable cannot flip the unset case.
    env = {key: val for key, val in os.environ.items() if key != DEBUG_VAR}
    if value is not None:
        env[DEBUG_VAR] = value
    return env


# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
_DEBUG_CHILD = textwrap.dedent(
    """
    import io, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import server_config
    from handlers import similar

    # The real respond_json writes through these transport methods, so a response is read as the status line and body it sends.
    class Handler:
        def __init__(self):
            self.server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=server_config.RECOMMENDATIONS_DEBUG_ENABLED)
            self.wfile = io.BytesIO()
            self.statuses = []
            self.served = []

        def send_response(self, status):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

        # Stands in for the random feed, which reads the random cache and whitelist.db.
        def _handle_random(self, limit, include_debug, request_id, started_at):
            self.served.append([limit, include_debug])

    out = {"flag": server_config.RECOMMENDATIONS_DEBUG_ENABLED, "cases": []}
    for params in json.loads(sys.argv[3]):
        handler = Handler()
        similar.SimilarHandler._handle_similar(handler, params)
        body = handler.wfile.getvalue()
        out["cases"].append({"respond": [[*handler.statuses, json.loads(body)]] if handler.statuses else [], "served": handler.served})
    print(json.dumps(out))
    """
)


def _handle_debug(value: str | None, cases: list[dict]) -> dict:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _DEBUG_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases)], cwd=SERVER_DIR / "api", env=_debug_env(value), capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout)


def test_debug_request_is_refused_403_unless_the_flag_is_set():
    # Control: with the flag set, the same debug request reaches the (stubbed) random feed with debug included, and nothing is refused.
    enabled = _handle_debug("1", [{"debug": ["1"], "random": ["1"]}, {"random": ["1"]}])
    assert enabled == {"flag": True, "cases": [{"respond": [], "served": [[20, True]]}, {"respond": [], "served": [[20, False]]}]}

    disabled = _handle_debug(None, [{"debug": ["1"]}, {"debug": ["1"], "random": ["1"]}, {"random": ["1"]}])

    assert disabled["flag"] is False
    assert disabled["cases"][0] == {"respond": [DEBUG_DISABLED], "served": []}
    assert disabled["cases"][1] == {"respond": [DEBUG_DISABLED], "served": []}
    # The refusal is tied to asking for debug: the same handler with the flag off still serves a plain request.
    assert disabled["cases"][2] == {"respond": [], "served": [[20, False]]}


def _wire(engine, method: str, path: str, body: bytes | None = None) -> tuple[int, dict[str, list[str]], bytes]:
    """Send one request with an `Origin` to the Engine; return the status, every header as lower-cased name -> list of values, and the body."""
    port = int(engine.base.rsplit(":", 1)[1])
    headers = {"Origin": "http://127.0.0.1:5173"}
    if body is not None:
        headers["content-type"] = "application/json"
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        seen: dict[str, list[str]] = {}
        for name, value in resp.getheaders():
            seen.setdefault(name.lower(), []).append(value)
        return resp.status, seen, data
    finally:
        conn.close()


@pytest.mark.parametrize("method, path, body, status", [
    ("GET", "/api/health", None, 200),
    ("OPTIONS", "/recommendations", None, 204),
    ("OPTIONS", "/api/health", None, 204),
    ("POST", "/recommendations?limit=1", b"{}", 200),
    ("POST", "/recommendations", b"{not json", 400),
    ("GET", "/no-such-route", None, 404),
], ids=["health", "options-recommendations", "options-health", "recommendations", "malformed-json", "not-found"])
def test_no_engine_response_carries_a_cors_header(engine, method, path, body, status):
    got = _wire(engine, method, path, body)

    assert got[0] == status, got[2][:300]  # control: the request reached the route this case names
    # Control: headers are read off the wire; every Engine response carries Server and Date, and JSON ones carry content-type.
    assert "server" in got[1] and "date" in got[1], got[1]
    if status != 204:
        assert got[1].get("content-type") == ["application/json; charset=utf-8"], got[1]
    assert {name: values for name, values in got[1].items() if name.startswith("access-control-")} == {}, got[1]


TRACEBACK_HEAD = "Traceback (most recent call last):"
SIMILAR_FAILED = ([500], {"error": "Recommendations request failed"})
BOOM = "sentinel-boom-4e2b"
VALUE = "sentinel-value-8a1c"
# Contains a bad-request text but is not one, so only an exact match may answer 400.
NEAR = "Invalid vector parameter: sentinel-near-3f9a"
BAD_REQUEST = ("Invalid vector parameter", "Vector dimension does not match embeddings", "Vector norm is zero")
SIMILAR_CASES = [("RuntimeError", BOOM), ("ValueError", VALUE), ("ValueError", NEAR), *(("ValueError", text) for text in BAD_REQUEST)]

# Runs under the Engine interpreter with the production logging installed; only the transport (statuses and bytes written) and the random feed are doubled.
_FAILING_SIMILAR_CHILD = textwrap.dedent(
    """
    import io, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from logging_profiles import configure_engine_logging
    configure_engine_logging("verbose")
    from handlers import similar

    ERRORS = {"RuntimeError": RuntimeError, "ValueError": ValueError}

    class Handler:
        def __init__(self, exc):
            self.statuses = []
            self.wfile = io.BytesIO()
            self.server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False)
            self.exc = exc

        def send_response(self, status):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

        # Stands in for the random feed, which reads the DB and FAISS; raising here puts the failure inside _handle_similar's try.
        def _handle_random(self, limit, include_debug, request_id, started_at):
            raise self.exc

    reports = []
    for index, (kind, text) in enumerate(json.loads(sys.argv[3])):
        # Marks where this case's log lines begin on stderr, which the formatter's handler writes to and flushes per record.
        print(json.dumps({"case": index}), file=sys.stderr, flush=True)
        handler = Handler(ERRORS[kind](text))
        similar.SimilarHandler._handle_similar(handler, {"random": ["1"]})
        reports.append({"statuses": handler.statuses, "body": handler.wfile.getvalue().decode("utf-8")})
    print(json.dumps(reports))
    """
)


def _json_lines(stderr: str) -> list[dict]:
    # Every line must be a JSON object: plain-text lines would mean logging.lastResort wrote them, not the production formatter.
    lines = [json.loads(line) for line in stderr.splitlines()]
    assert all(isinstance(line, dict) for line in lines), stderr[-2000:]
    return lines


def test_recommendations_failure_answers_a_fixed_500_and_logs_its_traceback():
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FAILING_SIMILAR_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(SIMILAR_CASES)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    reports = json.loads(run.stdout)
    lines = _json_lines(run.stderr)
    starts = [index for index, line in enumerate(lines) if set(line) == {"case"}]
    assert [lines[index]["case"] for index in starts] == list(range(len(SIMILAR_CASES)))
    segments = [lines[start + 1:end] for start, end in zip(starts, [*starts[1:], len(lines)])]
    # Control: each case entered _handle_similar, whose start line reached stderr within that case's segment.
    for segment in segments:
        assert any("] start limit=20" in line.get("message", "") for line in segment), segment

    answers = [(report["statuses"], json.loads(report["body"])) for report in reports]
    boom, value, near, *bad = answers
    assert boom == SIMILAR_FAILED
    assert value == SIMILAR_FAILED
    assert near == SIMILAR_FAILED
    assert bad == [([400], {"error": text}) for text in BAD_REQUEST]

    for segment, raised in zip(segments, (f"RuntimeError: {BOOM}", f"ValueError: {VALUE}", f"ValueError: {NEAR}")):
        tracebacks = [line["traceback"] for line in segment if line.get("level") == "ERROR" and "traceback" in line]
        # The ERROR line of this case holds a real traceback through the handler down to the raised exception.
        assert any(tb.startswith(TRACEBACK_HEAD) and "_handle_similar" in tb and tb.rstrip().endswith(raised) for tb in tracebacks), segment


SERVER_CONFIG = SERVER_DIR / "api" / "server_config.py"
# Seeds whose cache entry is shorter than a page: without the fallback, up-next served them 18 and 17 rows at limit=30 and limit=48.
SHORT_SEED_QUERIES = ("linux", "cooking")
FILL_LIMIT = 48
# Deeper than the cached entry and short of 48, the value default_limit, BATCH_SIZE and the pool target share, so a page padded to 48 whatever the request reads 48 here.
SHORT_PAGE_LIMIT = 30
FALLBACK_SEARCH_PATH = "/api/v1/search/videos?q=music&limit=20"
FALLBACK_SEARCH_ROWS = 20
FALLBACK_PREFIX = "[similar-server] ann_fallback"
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
LOG_WAIT_SECONDS = 5
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
REFRESHES = 10
MAX_MEAN_JACCARD = 0.5
LIKE_COUNT = 5
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
DRAW_HEADERS = {"X-Client-IP": "192.0.2.109"}
LIKES_HEADERS = {"X-Client-IP": "192.0.2.140"}
POOL_HEADERS = {"X-Client-IP": "192.0.2.141"}
SERVER_PREFIX = "[similar-server]"
# Logged once per seeded request before its pool is built, with likes=yes only when the request's likes resolved to videos.
PROFILE_PREFIX = "[recommendations] profile="
POOL_LINE = re.compile(r"\[similar-server\]\[(\w+)\] upnext_pool ")
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


def _config():
    spec = importlib.util.spec_from_file_location("engine_server_config", SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _search(engine, query: str, limit: int) -> list[dict]:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit={limit}")
    assert status == 200 and body["rows"], body
    return body["rows"]


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


def _mean_jaccard(sets: list[set]) -> float:
    pairs = list(itertools.combinations(sets, 2))
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


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


def _page(engine, path: str) -> list[dict]:
    status, body = engine.request("POST", path, headers=DRAW_HEADERS, body={})
    assert status == 200, body
    return body["rows"]


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


def test_ten_refreshes_of_one_seed_draw_different_pages_above_the_tail_floor(engine):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    path = _upnext_path(engine, "linux") + "&debug=1"

    pages = [_page(engine, path) for _ in range(REFRESHES)]
    for rows in pages:
        assert len(rows) == UPNEXT_PAGE, _keys(rows)
        assert len(set(_keys(rows))) == UPNEXT_PAGE, _keys(rows)
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]
    # A fixed top-8 scores 1.0 here (observed before sampling); an ES draw of 8 from the observed top-32 scores, simulated offline, scored about 0.14.
    mean = _mean_jaccard([set(_keys(rows)) for rows in pages])
    assert mean < MAX_MEAN_JACCARD, (mean, [_keys(rows) for rows in pages])

    first = _page(engine, path + "&seed=11")
    second = _page(engine, path + "&seed=11")
    assert len(first) == UPNEXT_PAGE, _keys(first)
    assert _keys(first) == _keys(second)
    # A seed that fixed the page without steering the draw, such as one falling back to the ranked top-8, gives every seed the same page.
    other = _page(engine, path + "&seed=12")
    assert len(other) == UPNEXT_PAGE, _keys(other)
    assert _keys(other) != _keys(first)


def test_upnext_with_and_without_likes_both_diversify_and_liked_rows_stay_above_the_floor(engine):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    seed = _search(engine, "linux", 1)[0]
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in _search(engine, "music", LIKE_COUNT)]
    # Control: five distinct likes, none of them the seed.
    assert len({(like["uuid"], like["host"]) for like in likes}) == LIKE_COUNT and (seed["video_uuid"], seed["instance_domain"]) not in {(like["uuid"], like["host"]) for like in likes}, likes
    path = f"/videos/similar?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_PAGE}&debug=1"

    # Liked draws go first, so a personalized_score stamp that outlived its request would show on the plain draws' lines.
    liked, liked_lines, liked_profiles = _requests(engine, path, LIKES_HEADERS, {"likes": likes}, REFRESHES)
    plain, plain_lines, plain_profiles = _requests(engine, path, LIKES_HEADERS, {}, REFRESHES)
    # Control: every liked request resolved its likes, and no plain request had any.
    assert liked_profiles == [liked_profiles[0]] * REFRESHES and liked_profiles[0].endswith(" likes=yes"), liked_profiles
    assert plain_profiles == [plain_profiles[0]] * REFRESHES and plain_profiles[0].endswith(" likes=no"), plain_profiles

    for rows in liked + plain:
        assert len(rows) == UPNEXT_PAGE and len(set(_keys(rows))) == UPNEXT_PAGE, _keys(rows)
    # The likes' pull must not reach outside the seed's pool, which holds nothing under the tail floor; observed at or above 0.725.
    assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for rows in liked for r in rows), [r["debug"]["similarity_score"] for rows in liked for r in rows]
    # Observed about 0.16 with likes and 0.14 without, drawing before the rerank; a window reranked by likes and cut to its top 8 repeats one page and scores 1.0.
    liked_mean = _mean_jaccard([set(_keys(rows)) for rows in liked])
    assert liked_mean < MAX_MEAN_JACCARD, (liked_mean, [_keys(rows) for rows in liked])
    plain_mean = _mean_jaccard([set(_keys(rows)) for rows in plain])
    assert plain_mean < MAX_MEAN_JACCARD, (plain_mean, [_keys(rows) for rows in plain])

    # Ten lines under ten distinct request ids tie each line to one request, so the liked ones are exactly the first ten.
    assert len(liked_lines) == REFRESHES, liked_lines
    assert [_tokens(line).get("likes_rerank") for line in liked_lines] == ["yes"] * REFRESHES, liked_lines
    assert len(plain_lines) == REFRESHES, plain_lines
    assert [_tokens(line).get("likes_rerank") for line in plain_lines] == ["no"] * REFRESHES, plain_lines
    assert len({POOL_LINE.match(line).group(1) for line in liked_lines + plain_lines}) == 2 * REFRESHES, liked_lines + plain_lines

    # Likes that name no known video leave nothing to rerank by, so a line keyed on the body carrying likes, rather than on a rerank, reads yes here.
    unknown = [{"uuid": like["uuid"] + "-absent", "host": like["host"]} for like in likes]
    _, unknown_lines, unknown_profiles = _requests(engine, path, LIKES_HEADERS, {"likes": unknown}, 1)
    assert len(unknown_profiles) == 1 and unknown_profiles[0].endswith(" likes=no"), unknown_profiles
    assert [_tokens(line).get("likes_rerank") for line in unknown_lines] == ["no"], unknown_lines


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


# The values the requirements name for `mode`, sent as inputs so a tuple that dropped one is refused on the wire, not compared against a copy of the spec.
REQUIRED_MODES = ["recommendations", "hot", "recent", "random", "popular"]
# Near misses: an unknown word, a known mode in the wrong case, and the Engine's internal profile name.
UNKNOWN_MODES = ["bogus", "HOT", "home"]
SEEDED_MODES = [*REQUIRED_MODES, "bogus", "HOT", ""]
FEED_PAGE = 12
# Rows of the order read for the reference: three pages and the far excluded page, plus room for moderated rows to be skipped.
REFERENCE_DEPTH = 200
# How each non-ordered mode was spelled before feed modes existed; a mode outside the ordered set with no entry here reaches no known feed.
PRE_BUILD = {"recommendations": "", "random": "&random=1"}
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
MODE_HEADERS = {"X-Client-IP": "192.0.2.172"}
UNORDERED_HEADERS = {"X-Client-IP": "192.0.2.173"}
ORDERED_HEADERS = {"X-Client-IP": "192.0.2.174"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# A missing FEED_MODES or ORDERED_FEED_MODES prints null rather than failing the import, so its absence reaches the tests instead of the collection.
_FEED_CONSTANTS_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    import server_config
    feed = getattr(similar, "FEED_MODES", None)
    ordered = getattr(similar, "ORDERED_FEED_MODES", None)
    print(json.dumps({"feed": list(feed) if feed is not None else None, "ordered": sorted(ordered) if ordered is not None else None, "threshold": server_config.VIDEO_ERROR_THRESHOLD}))
    """
)


def _feed_constants() -> tuple[dict | None, str]:
    """The Engine's feed-mode constants and error threshold, or None with the reason they could not be read."""
    if not ENGINE_PY.exists():
        return None, f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FEED_CONSTANTS_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        return None, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1]), ""


# Read once at collection, so the parametrizations follow the module as it is.
FEED_CONSTANTS, FEED_CONSTANTS_ERROR = _feed_constants()
FEED_MODES = (FEED_CONSTANTS or {}).get("feed")
ORDERED = (FEED_CONSTANTS or {}).get("ordered")
UNORDERED = [mode for mode in (FEED_MODES or []) if mode not in (ORDERED or [])]


def _post(engine, path: str, headers: dict[str, str], body: dict) -> dict:
    status, payload = engine.request("POST", path, headers=headers, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path, status, payload)
    return payload


def _exclude(keys: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": video_id, "host": host} for video_id, host in keys]


def _reference(dataset, order: str, threshold: int) -> list[tuple[str, str]]:
    """The order's first rows as `fetch_ordered_page` reads them from whitelist.db for a request without nsfw, less those the Engine's moderation removes."""
    denied = {row["host"].lower() for row in dataset.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(row["channel_id"], row["instance_domain"].lower()) for row in dataset.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    # The pages compared with this carry no nsfw, so the Engine filters them.
    rows = fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, error_threshold=threshold, include_nsfw=False)
    kept = [r for r in rows if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked]
    return _keys(kept)


@pytest.mark.parametrize("mode", UNKNOWN_MODES)
def test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them(engine, mode):
    status, body = engine.request("POST", f"/recommendations?mode={mode}&limit={UPNEXT_PAGE}", headers=MODE_HEADERS, body={})
    # A handler that ignores mode answers 200 with a home page (observed for all three before validation).
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert FEED_MODES is not None and mode not in FEED_MODES, FEED_MODES  # control: FEED_MODES exists and the value sent is outside it
    assert body == {"error": "Unknown mode", "allowed": list(FEED_MODES)}


def test_every_feed_mode_and_a_missing_or_empty_mode_is_served_not_refused(engine):
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert FEED_MODES is not None and len(FEED_MODES) == len(set(FEED_MODES)), FEED_MODES  # FEED_MODES exists with no value repeated
    # A validator refusing every mode passes the 400 test, and a tuple missing a required mode refuses it; both fail here.
    for suffix in [f"&mode={mode}" for mode in dict.fromkeys([*REQUIRED_MODES, *FEED_MODES])] + ["", "&mode="]:
        status, body = engine.request("POST", f"/recommendations?limit={UPNEXT_PAGE}{suffix}", headers=MODE_HEADERS, body={})
        assert status == 200 and "error" not in body and "rows" in body, (suffix, status, body.get("error"))


def test_a_seeded_request_is_served_the_same_upnext_whatever_its_mode(engine):
    status, found = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1", headers=MODE_HEADERS)
    assert status == 200 and found["rows"], found
    seed = found["rows"][0]
    # seed=11 fixes the up-next draw, so a page is a function of the request and pages can be compared row for row.
    path = f"/recommendations?id={quote(seed['video_uuid'])}&host={quote(seed['instance_domain'])}&limit={UPNEXT_PAGE}&seed=11"
    status, plain = engine.request("POST", path, headers=MODE_HEADERS, body={})
    assert status == 200 and plain["seed"].get("mode") == "upnext" and len(plain["rows"]) == UPNEXT_PAGE, (status, plain.get("seed"))
    status, again = engine.request("POST", path, headers=MODE_HEADERS, body={})
    assert status == 200 and _keys(again["rows"]) == _keys(plain["rows"]), "control: the seeded draw repeats without mode"

    for mode in SEEDED_MODES:
        status, body = engine.request("POST", f"{path}&mode={mode}", headers=MODE_HEADERS, body={})
        # Validating seeded requests answers bogus 400; dispatching on mode serves another feed, whose seed is not this video's.
        assert status == 200, (mode, status, body)
        assert body["seed"] == plain["seed"], (mode, body["seed"])
        assert _keys(body["rows"]) == _keys(plain["rows"]), mode


@pytest.mark.parametrize("mode", UNORDERED or ["FEED_MODES unreadable"])
def test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did(engine, mode):
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    # A mode left out of ORDERED_FEED_MODES by mistake, such as hot, lands here and has no pre-build feed to match.
    assert mode in PRE_BUILD, (mode, ORDERED)
    before = _post(engine, f"/recommendations?limit={FEED_PAGE}{PRE_BUILD[mode]}", UNORDERED_HEADERS, {})
    # Control: the pre-build spellings serve a home page, not the random fallback, and the random feed (observed).
    if mode == "recommendations":
        assert before["seed"].get("mode") == "home" and "random" not in before["seed"], before["seed"]
    else:
        assert before["seed"] == {"random": True}, before["seed"]
    after = _post(engine, f"/recommendations?limit={FEED_PAGE}&mode={mode}", UNORDERED_HEADERS, {})
    # Without dispatch, mode=random serves a home page: {"user_id": "local-user", "mode": "home"} (observed).
    assert after["seed"] == before["seed"], (mode, after["seed"])
    assert len(after["rows"]) == len(before["rows"]) == FEED_PAGE, (len(after["rows"]), len(before["rows"]))
    if mode == "recommendations":
        empty = _post(engine, f"/recommendations?limit={FEED_PAGE}&mode=", UNORDERED_HEADERS, {})
        assert empty["seed"] == before["seed"] and len(empty["rows"]) == FEED_PAGE, empty["seed"]


@pytest.mark.parametrize("order", ORDERED or ["ORDERED_FEED_MODES missing"])
def test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated(engine, dataset, order):
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert ORDERED is not None, "handlers.similar has no ORDERED_FEED_MODES"
    assert order in (FEED_MODES or []), (order, FEED_MODES)  # control: a mode the Engine accepts rather than refuses 400
    reference = _reference(dataset, order, FEED_CONSTANTS["threshold"])
    assert len(reference) >= 4 * FEED_PAGE, len(reference)  # control: the order holds three pages and a last page beyond them
    status, found = engine.request("GET", f"/api/v1/search/videos?q=linux&limit={LIKE_COUNT}", headers=ORDERED_HEADERS)
    assert status == 200 and len(found["rows"]) == LIKE_COUNT, found
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in found["rows"]]
    path = f"/recommendations?mode={quote(order)}&limit={FEED_PAGE}"

    liked = _post(engine, path, ORDERED_HEADERS, {"likes": likes})
    plain = _post(engine, path, ORDERED_HEADERS, {})
    second = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]))})
    # Page 3 excludes every row shown so far, as the pager sends it, plus the reference's last page: those rows lie past page 3, so a walk continuing after the shown rows is untouched by them, while one jumping len(exclude) rows ahead starts page 3 at index 3 * FEED_PAGE instead of 2 * FEED_PAGE.
    third = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]) + _keys(second["rows"]) + reference[-FEED_PAGE:])})
    # Control: signals and publish dates did not move the order while the requests ran, so the reference is the order they were served from.
    assert _reference(dataset, order, FEED_CONSTANTS["threshold"]) == reference

    # A home page's seed is {"user_id": "local-user", "mode": "home"} (observed); the random feed's seed is {"random": True}.
    for payload in (liked, plain, second, third):
        assert "random" not in payload["seed"] and "mode" not in payload["seed"], payload["seed"]
    # A feed ranked by likes, or drawn afresh per request, differs here.
    assert _keys(liked["rows"]) == _keys(plain["rows"])
    first, following, last = _keys(plain["rows"]), _keys(second["rows"]), _keys(third["rows"])
    assert len(first) == len(following) == len(last) == FEED_PAGE, (len(first), len(following), len(last))
    # A walk ignoring `exclude` serves page 1 again; one honouring only the first page's keys serves page 2 again at page 3.
    assert not set(first) & set(following), sorted(set(first) & set(following))
    assert not set(first + following) & set(last), sorted(set(first + following) & set(last))
    # Another order's head, a shuffled page, a page that skips or restarts the order, or a count-offset walk (page 3 from index 3 * FEED_PAGE) differs from the reference prefix.
    assert first + following + last == reference[: 3 * FEED_PAGE], (first + following + last, reference[: 3 * FEED_PAGE])


# The NSFW filter at the request edge, against the session Engine: a listing request is served no row whitelist.db flags nsfw = 1 unless it carries exactly nsfw=1.
# One fresh address per request from the benchmark range, clear of the 192.0.2.x buckets the rest of tests/active uses.
NSFW_CLIENT_IPS = (f"198.18.{n // 250}.{n % 250 + 1}" for n in itertools.count())
# Up-next caps a page at one row per channel; this flagged seed's neighbourhood spans ten flagged channels, so its seed=11 page at limit 96 carries 10 flagged rows, and its raw-vector page 37 of 96 (observed).
NSFW_SEED_ID, NSFW_SEED_HOST = "59b6239b-15c6-4bc4-b5e6-6ebac4ea9751", "810video.com"
NSFW_DRAW_SEED = 11
# 84 of the top 100 matches are flagged (observed), and 244 match in all.
NSFW_SEARCH_QUERY = "hentai"
NSFW_SEARCH_LIMIT = 100
# Flagged videos from the NSFW_SEARCH_QUERY results: liked, they pull the like layer into a flagged neighbourhood, and a mixed page carried 4 or 5 flagged rows in each of 6 draws (observed).
NSFW_LIKES = [{"uuid": uuid, "host": "video02.videohost.top"} for uuid in ("f4e114a2-e70e-4a3c-af92-3efe3071abbc", "0e9ab678-8f3c-4305-97c9-ba9586536999", "4577ad2f-8462-4c78-8212-c4470a4f6db5", "0b385f12-aaeb-435b-9282-7e466cbaf282", "b9ff92e2-6b40-4396-9ed9-1c7f30031dcb")]
NSFW_LISTINGS = ["mode=recommendations", "mode=hot", "mode=recent", "mode=random", "upnext POST /recommendations", "upnext POST /videos/similar", "upnext GET /videos/{id}/similar", "random=1", "vector", "search"]
# The random cache is 0.6% flagged, so a 96-row draw held 0 to 2 flagged rows (observed): 12 draws hold none about once in a thousand runs.
NSFW_DRAWS = {"mode=random": 12, "random=1": 12, "mode=recommendations": 3}
# Every value but exactly "1"; parse_qs drops the empty one, so it arrives as missing.
NSFW_VALUES = {"missing": "", "empty": "&nsfw=", "0": "&nsfw=0", "true": "&nsfw=true", "space-1": f"&nsfw={quote(' 1')}"}
# The largest page the Engine serves: twice its default.
NSFW_LIMIT = 2 * _default_limit()


@pytest.fixture(scope="module")
def nsfw_flagged(dataset) -> set[tuple[str, str]]:
    keys = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    assert keys, "control: whitelist.db flags no video nsfw = 1"
    return keys


def _nsfw_listing(dataset, listing: str) -> tuple[str, str, dict | None]:
    """The method, path and body of one listing request, without nsfw."""
    upnext = f"id={NSFW_SEED_ID}&host={NSFW_SEED_HOST}&limit={NSFW_LIMIT}&seed={NSFW_DRAW_SEED}"
    if listing == "mode=recommendations":
        return "POST", f"/recommendations?mode=recommendations&limit={NSFW_LIMIT}", {"likes": NSFW_LIKES}
    if listing.startswith("mode="):
        return "POST", f"/recommendations?{listing}&limit={NSFW_LIMIT}", {}
    if listing == "upnext POST /recommendations":
        return "POST", f"/recommendations?{upnext}", {}
    if listing == "upnext POST /videos/similar":
        return "POST", f"/videos/similar?{upnext}", {}
    if listing == "upnext GET /videos/{id}/similar":
        return "GET", f"/videos/{NSFW_SEED_ID}/similar?host={NSFW_SEED_HOST}&limit={NSFW_LIMIT}&seed={NSFW_DRAW_SEED}", None
    if listing == "random=1":
        return "POST", f"/recommendations?random=1&limit={NSFW_LIMIT}", {}
    if listing == "vector":
        return "POST", f"/recommendations?vector={quote(json.dumps(embedding_of(dataset, NSFW_SEED_ID, NSFW_SEED_HOST)))}&limit={NSFW_LIMIT}", {}
    return "GET", f"/api/v1/search/videos?q={NSFW_SEARCH_QUERY}&limit={NSFW_SEARCH_LIMIT}", None


def _nsfw_keys(engine, method: str, path: str, body: dict | None) -> list[tuple[str, str]]:
    status, payload = engine.request(method, path, headers={"X-Client-IP": next(NSFW_CLIENT_IPS)}, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path[:160], status, payload)
    return [(r["video_id"], r["instance_domain"]) for r in payload["rows"]]


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
@pytest.mark.parametrize("listing", NSFW_LISTINGS)
def test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some(engine, dataset, nsfw_flagged, listing, nsfw):
    method, path, body = _nsfw_listing(dataset, listing)
    draws = NSFW_DRAWS.get(listing, 1)
    # Sent first on the same Engine: a mixer whose flag froze at build time serves no flagged row here.
    shown: set[tuple[str, str]] = set()
    for _ in range(draws):
        shown = set(_nsfw_keys(engine, method, f"{path}&nsfw=1", body)) & nsfw_flagged
        if shown:
            break
    assert shown, f"control: {listing} with nsfw=1 served no flagged row in {draws} draws"
    for _ in range(draws):
        keys = _nsfw_keys(engine, method, f"{path}{NSFW_VALUES[nsfw]}", body)
        assert keys, f"{listing} served an empty page"  # a handler answering every filtered request with no rows is no filter
        assert not set(keys) & nsfw_flagged, sorted(set(keys) & nsfw_flagged)[:5]  # no flagged row without exactly nsfw=1
