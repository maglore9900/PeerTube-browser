"""The Engine's feed and search responses, against a real Engine on the repo's dataset.

- Every row of a home, random, up-next and search response carries the `channel_id` and
  `account_url` that `whitelist.db` holds for that video: the identity the Client's
  per-profile blocks match on.
- Home and random serve more than the default page when asked for twice it, which the
  Client's over-fetch for visitors with blocks relies on.
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

Up-next's sampled page, against the session Engine:

- Ten unseeded POST /recommendations?id=…&host=…&limit=8&debug=1 requests for the linux seed each return 8
  distinct rows, every row's debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE, and the mean
  pairwise Jaccard of their key sets is below 0.5.
- The same request with &seed=11, sent twice, returns 8 rows in the same order both times, and with &seed=12
  returns a different ordered page.
- For the linux and cooking seeds, a POST /recommendations?id=…&host=…&limit=8&debug=1&seed=7 page, then the same request excluding that whole page and excluding every other row of it, each return 8 distinct rows, none of them excluded, every one with debug similarity_score at or above SIMILAR_VIDEO_TAIL_MIN_SCORE (membership of the seed's pool). The same seeded request without exclude repeats the first page, so ignoring exclude would serve the excluded rows again.

Up-next draws with and without likes, and the upnext_pool log line, against the session Engine:

- For the linux seed, ten POST /videos/similar?id=…&host=…&limit=8&debug=1 requests carrying five "music"
  search rows as likes, then ten carrying none, each return 8 distinct rows, and each set's mean pairwise
  Jaccard is below 0.5. Every row drawn with likes has a debug similarity_score at or above
  SIMILAR_VIDEO_TAIL_MIN_SCORE. Each request writes exactly one `upnext_pool` line, under its own request id:
  likes_rerank=yes for each of the ten whose likes resolved, and likes_rerank=no for each of the ten without
  likes and for one whose likes name no known video.

Feed modes, against the session Engine, with `FEED_MODES`, `ORDERED_FEED_MODES` and `VIDEO_ERROR_THRESHOLD` read under the Engine interpreter:

- An unseeded POST /recommendations whose `mode` is `bogus`, `TRENDING`, `home` or the retired `hot` (none of them in `FEED_MODES`) is answered 400 with exactly `{"error": "Unknown mode", "allowed": list(FEED_MODES)}`.
- A seeded POST /recommendations (a real video's `id` and `host`, `seed=11`) with each of the five modes, `mode=bogus`, `mode=TRENDING`, the retired `mode=hot` or an empty `mode` is answered 200 with the same `seed` payload (`mode` "upnext") and the same ordered rows as that request without `mode`.
- Each value of `FEED_MODES` outside `ORDERED_FEED_MODES` has a pre-build spelling (`recommendations` none, `random` `random=1`), and POST /recommendations with that `mode` answers the same `seed` as that spelling, with a full page: `{"user_id", "mode": "home"}` and no `random` key for `recommendations` (an empty `mode` too), `{"random": True}` for `random`.
- For each value of `ORDERED_FEED_MODES`: page 1 carrying five likes, page 1 carrying none, page 2 carrying page 1's rows as `exclude`, and page 3 carrying pages 1 and 2 plus the reference's last page (rows far past page 3) as `exclude` each answer a `seed` with neither a `random` nor a `mode` key. Page 1 is the same ordered rows with and without likes. Pages 1, 2 and 3 are full, share no `(video_id, instance_domain)`, and concatenate into the first rows of `fetch_ordered_page` for that order, read through the read-only `dataset` connection at the Engine's threshold with NSFW-flagged rows left out, rows on an active denylisted host or a blocked channel skipped. That reference is read before and after the requests and is the same both times.

Trending's end of order, under the Engine interpreter in a child process, not against the `engine` fixture:

- The real `SimilarHandler._handle_similar`, on a stub server over a temp DB of the labelled rows in `RANKS`, serves `mode=trending` as the rank order under its error threshold and the default NSFW filter, with `nsfw=1` keeping the flagged row, and with `seed` `{}`. It continues the order past an excluded head, and answers an empty page with `seed` `{}` once every ranked row is excluded or the ranks table is empty, where `mode=random` on the emptied DB still serves rows.

The NSFW filter at the request edge, against the session Engine, with rows cross-checked against the non-empty set of keys whitelist.db flags nsfw = 1, read through the `dataset` connection:

- Nine listing paths are each sent with nsfw missing, empty, "0", "true" and " 1": POST /recommendations with mode recommendations (carrying five flagged likes), random and trending; up-next for one flagged seed on POST /recommendations, POST /videos/similar and GET /videos/{id}/similar; POST /recommendations?random=1; the raw-vector POST /recommendations for that seed's embedding; and GET /api/v1/search/videos?q=hentai. Every response is 200, holds rows, and holds no flagged key. The random feeds are drawn 24 times per value and the mixed feed 3 times.
- Before each of those requests, the same path with nsfw=1 returns at least one flagged key on the same Engine (within 24 draws for the random feeds, 3 for the mixed feed). For mode=recommendations this means the mixer honours the opt-in and then filters the next request, so its flag is read per request, not frozen at build time.
"""
from __future__ import annotations

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
from conftest import ENGINE_PY, ROOT, embedding_of, identity_of

# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
for _path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from data.ann_ids import compute_ann_id, create_video_embeddings_table  # noqa: E402
from data.moderation import ensure_moderation_schema  # noqa: E402
from data.random_videos import fetch_ordered_page  # noqa: E402
from data.trending import ensure_trending_schema  # noqa: E402

SEARCH_QUERY = "music"
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
LOG_WAIT_SECONDS = 5
REFRESHES = 10
MAX_MEAN_JACCARD = 0.5
LIKE_COUNT = 5
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
DRAW_HEADERS = {"X-Client-IP": "192.0.2.109"}
LIKES_HEADERS = {"X-Client-IP": "192.0.2.140"}
EXCLUDE_HEADERS = {"X-Client-IP": "192.0.2.151"}
# Seeds whose up-next pool runs to about 300 rows, far past a page plus its excluded rows.
UPNEXT_SEED_QUERIES = ("linux", "cooking")
EXCLUDE_DRAW_SEED = 7
SERVER_PREFIX = "[similar-server]"
# Logged once per seeded request before its pool is built, with likes=yes only when the request's likes resolved to videos.
PROFILE_PREFIX = "[recommendations] profile="
POOL_LINE = re.compile(r"\[similar-server\]\[(\w+)\] upnext_pool ")


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


@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    path = _upnext_path(engine, query) + f"&debug=1&seed={EXCLUDE_DRAW_SEED}"
    status, first = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _keys(first["rows"])
    assert len(set(previous)) == UPNEXT_PAGE, previous
    assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in first["rows"]), [r["debug"]["similarity_score"] for r in first["rows"]]
    # Control: the seeded draw repeats, so a request ignoring exclude would serve every excluded row again.
    status, again = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={})
    assert status == 200 and _keys(again["rows"]) == previous, (previous, _keys(again["rows"]))

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        status, page = engine.request("POST", path, headers=EXCLUDE_HEADERS, body={"exclude": _exclude(excluded)})
        assert status == 200, page
        rows = page["rows"]
        assert len(rows) == UPNEXT_PAGE and len(set(_keys(rows))) == UPNEXT_PAGE, (excluded, _keys(rows))
        assert not set(_keys(rows)) & set(excluded), sorted(set(_keys(rows)) & set(excluded))
        # Nothing under the tail floor is in a seed's pool; observed pages sat at or above 0.545 (cooking) and 0.747 (linux).
        assert all(r["debug"]["similarity_score"] >= floor - 1e-6 for r in rows), [r["debug"]["similarity_score"] for r in rows]


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


# The values the requirements name for `mode`, sent as inputs so a tuple that dropped one is refused on the wire, not compared against a copy of the spec.
REQUIRED_MODES = ["recommendations", "trending", "recent", "random", "popular"]
# Near misses: an unknown word, a known mode in the wrong case, and the Engine's internal profile name; and hot, the mode trending replaced.
UNKNOWN_MODES = ["bogus", "TRENDING", "home", "hot"]
SEEDED_MODES = [*REQUIRED_MODES, "bogus", "TRENDING", "hot", ""]
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
    # A handler that ignores mode answers 200 with a home page (observed for the near misses before validation); hot answered 200 while it was a feed mode.
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert FEED_MODES is not None and mode not in FEED_MODES, FEED_MODES  # control: FEED_MODES exists and the value sent is outside it
    assert body == {"error": "Unknown mode", "allowed": list(FEED_MODES)}


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
    # A mode left out of ORDERED_FEED_MODES by mistake, such as trending, lands here and has no pre-build feed to match.
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


# Trending's end of order, on a temp DB the handler reads in a child under the Engine interpreter.
CRAWL_SCHEMA = ROOT / "engine" / "crawler" / "schema.sql"
TRENDING_THRESHOLD = 3
# label: (video_id, instance_domain, rank or None, listed likes, listed views, nsfw, error_count, in videos, embedded).
RANKS = {
    "C1": ("c1", "c.example", 1, 70, 10, 0, 0, True, True),
    "X": ("x1", "d.example", 1, 60, 10, 1, 0, True, True),
    "B1": ("b1", "b.example", 1, 50, 900, None, 0, True, True),
    "A1": ("a1", "a.example", 1, 50, 100, 0, 0, True, True),
    "B2": ("v-z", "b.example", 2, 10, 10, 0, 0, True, True),
    "C2": ("v-m", "c.example", 2, 10, 10, 0, 0, True, True),
    "A2": ("v-m", "a.example", 2, 10, 10, 0, 0, True, True),
    "E": ("v-a", "d.example", 2, 10, 10, 0, TRENDING_THRESHOLD, True, True),
    "A3": ("a3", "a.example", 3, 500, 5000, 0, 0, True, True),
    "B5": ("b5", "b.example", 5, 400, 4000, 0, 0, True, True),
    "GHOST": ("g1", "f.example", 1, 999, 999, 0, 0, False, False),
    "U": ("u1", "e.example", 1, 999, 999, 0, 0, True, False),
    "N": ("n1", "b.example", None, 0, 0, 0, 0, True, True),
}
# Derived by hand from RANKS: rank, then listed likes, listed views, video_id and domain, all descending but rank. GHOST is not in videos, U has no embedding and N no rank, so none is served.
TRENDING_EXPECTED = ["C1", "X", "B1", "A1", "B2", "C2", "A2", "E", "A3", "B5"]
# Keyed by include_nsfw, under the threshold: the threshold drops E, the filter drops X.
TRENDING_SERVED = {
    True: ["C1", "X", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
    False: ["C1", "B1", "A1", "B2", "C2", "A2", "A3", "B5"],
}
TRENDING_LABEL_OF = {(spec[0], spec[1]): label for label, spec in RANKS.items()}


def _ranks_db(path: Path) -> sqlite3.Connection:
    """A whitelist-shaped DB holding the RANKS rows, stored last expected first, with crawled likes, views and popularity rising along TRENDING_EXPECTED and highest on the unranked N."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CRAWL_SCHEMA.read_text(encoding="utf-8"))
    conn.execute("ALTER TABLE videos ADD COLUMN popularity REAL NOT NULL DEFAULT 0")
    create_video_embeddings_table(conn)
    ensure_moderation_schema(conn)
    ensure_trending_schema(conn)
    for label in reversed(list(RANKS)):
        video_id, host, rank, likes, views, nsfw, errors, in_videos, embedded = RANKS[label]
        crawled = 100 if label == "N" else TRENDING_EXPECTED.index(label) + 1 if label in TRENDING_EXPECTED else 200
        if in_videos:
            conn.execute(
                "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, likes, views, nsfw, popularity, error_count, published_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (video_id, f"uuid-{label}", host, f"ch-{label}", crawled, 10 * crawled, nsfw, float(crawled), errors, 1_700_000_000_000),
            )
        if embedded:
            conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 1, 'm', 't', ?)", (video_id, host, compute_ann_id(video_id, host)))
        if rank is not None:
            conn.execute("INSERT INTO trending_ranks VALUES (?, ?, ?, ?, ?, 0)", (host, video_id, rank, likes, views))
    conn.commit()
    return conn


def _trending_labels(rows: list[dict]) -> list[str]:
    return [TRENDING_LABEL_OF.get((row["video_id"], row["instance_domain"]), row["video_id"]) for row in rows]


def _rank_key(label: str) -> str:
    return f"{RANKS[label][0]}::{RANKS[label][1]}"


# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# The stub server holds what the ordered-feed path reads; the HTTP transport is replaced so a response is read as the status and body it sends.
_TRENDING_HANDLER_CHILD = textwrap.dedent(
    """
    import io, json, sqlite3, sys, threading, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    from handlers import similar
    from request_context import set_request_excluded_keys

    class Handler(similar.SimilarHandler):
        def __init__(self, server):
            self.server = server
            self.wfile = io.BytesIO()
            self.statuses = []

        def send_response(self, status, message=None):
            self.statuses.append(status)

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

    out = []
    for db_path, params, excluded in json.loads(sys.argv[3]):
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        # No random cache, so the random feed reads whitelist rows: a fallback would fill the page.
        server = types.SimpleNamespace(default_limit=20, refresh_similarity_cache=False, recommendations_debug_enabled=False, db=db, db_lock=threading.Lock(), video_error_threshold=int(sys.argv[4]), embeddings_count=0, random_cache_db=None, random_cache_lock=threading.Lock())
        handler = Handler(server)
        set_request_excluded_keys(set(excluded))
        similar.SimilarHandler._handle_similar(handler, params)
        out.append({"statuses": handler.statuses, "body": json.loads(handler.wfile.getvalue() or b"null")})
        db.close()
    print(json.dumps(out))
    """
)


def _handle_trending(cases: list[list]) -> list[dict]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _TRENDING_HANDLER_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api"), json.dumps(cases), str(TRENDING_THRESHOLD)], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handler and ran every case
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_the_handler_serves_trending_until_the_ranked_rows_run_out_then_an_empty_page_not_a_fallback(tmp_path):
    ranked = str(tmp_path / "ranks.db")
    _ranks_db(Path(ranked)).close()
    empty = str(tmp_path / "empty.db")
    _ranks_db(Path(empty)).execute("DELETE FROM trending_ranks").connection.commit()
    served = TRENDING_SERVED[False]
    trending = {"mode": ["trending"], "limit": ["20"]}
    random_case, plain, flagged, past_head, run_out, emptied = _handle_trending([
        [empty, {"mode": ["random"], "limit": ["20"]}, []],
        [ranked, trending, []],
        [ranked, {**trending, "nsfw": ["1"]}, []],
        [ranked, trending, [_rank_key(label) for label in served[:3]]],
        [ranked, trending, [_rank_key(label) for label in served]],
        [empty, trending, []],
    ])
    # Control: on the emptied DB the random feed still serves rows, so a fallback would show as a non-empty page.
    assert random_case["statuses"] == [200] and random_case["body"]["seed"] == {"random": True} and random_case["body"]["rows"], random_case
    for case in (plain, flagged, past_head, run_out, emptied):
        assert case["statuses"] == [200] and case["body"]["seed"] == {}, case  # the ordered feed answered, not the random fallback
    assert _trending_labels(plain["body"]["rows"]) == served  # the Engine's threshold and the default NSFW filter applied to the rank order
    assert _trending_labels(flagged["body"]["rows"]) == TRENDING_SERVED[True]
    assert _trending_labels(past_head["body"]["rows"]) == served[3:]  # the walk continues past the excluded head
    assert run_out["body"]["rows"] == []  # every ranked row excluded: an empty page
    assert emptied["body"]["rows"] == []  # no ranked rows: an empty page


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
# mode=trending's nsfw=1 control was rehearsed with exactly one flagged row in the first 96 seeded Trending rows; the seed is derived from the live whitelist.db, so a crawl can starve it, as happened to mode=recent.
NSFW_LISTINGS = ["mode=recommendations", "mode=random", "mode=trending", "upnext POST /recommendations", "upnext POST /videos/similar", "upnext GET /videos/{id}/similar", "random=1", "vector", "search"]
# The random cache is 0.6% flagged (2966 of 490348 rows), so a 96-row window holds none with p=0.554 (observed): 24 draws hold none about once in 1.4 million cases, and the ten random-feed cases about once in 140,000 runs; 12 draws failed about one run in 120.
NSFW_DRAWS = {"mode=random": 24, "random=1": 24, "mode=recommendations": 3}
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
