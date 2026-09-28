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
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import subprocess
import textwrap
from urllib.parse import quote

import pytest
from conftest import ENGINE_PY, ROOT, identity_of

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
