"""Every unseeded feed mode reaches its feed: recommendations and random as their pre-build spellings, hot, popular and recent as the next rows of one global order.

Against the session `engine` fixture (the real Engine on the repo's dataset), `FEED_MODES`, `ORDERED_FEED_MODES` and `VIDEO_ERROR_THRESHOLD` read under the Engine interpreter:

- Each value of `FEED_MODES` outside `ORDERED_FEED_MODES` has a pre-build spelling (`recommendations` none, `random` `random=1`), and POST /recommendations with that `mode` answers the same `seed` as the pre-build spelling, with a full page: `{"user_id", "mode": "home"}` and no `random` key for `recommendations` (an empty `mode` too), `{"random": True}` for `random`.
- For each value of `ORDERED_FEED_MODES`: page 1 carrying five likes, page 1 carrying none, page 2 carrying page 1's rows as `exclude`, and page 3 carrying pages 1 and 2 plus the reference's last page (rows far past page 3) as `exclude` each answer a `seed` with neither a `random` nor a `mode` key. Page 1 is the same ordered rows with and without likes. Pages 1, 2 and 3 are full, share no `(video_id, instance_domain)`, and concatenate into the first rows of `fetch_ordered_page` for that order, read through the read-only `dataset` connection at the Engine's threshold, rows on an active denylisted host or a blocked channel skipped. That reference is read before and after the requests and is the same both times.

Against the `tests/active/test_server.py` stubbed-Engine harness (a real Client backend in front of a recording stand-in Engine):

- A keyed `mode=hot&limit=10` page, for a profile blocking one row's channel and disliking another row, omits both rows and keeps the rest in the Engine's order, and reaches the Engine with `mode=hot` and `limit=20`; the same request without a key reaches it with `limit=10` and returns every row.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import pytest

# tests/tmp has no conftest of its own, so the active suite's fixtures and helpers are imported from it; fixtures imported here are registered as this module's.
ACTIVE_DIR = Path(__file__).resolve().parents[1] / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
from conftest import ENGINE_PY, ROOT, ClientBackend, RateLimiter, client_server, dataset, engine  # noqa: E402,F401
from lib.blocks import add_block, block_target  # noqa: E402
from lib.dislikes import write_dislike  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
# test_server puts the Engine dirs on sys.path after conftest's import, as both trees hold a `server` module.
from test_server import _client_backend, _serving  # noqa: E402

from data.random_videos import fetch_ordered_page  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
PAGE = 12
# Rows of the order read for the reference: three pages and the far excluded page, plus room for moderated rows to be skipped.
REFERENCE_DEPTH = 200
LIKE_COUNT = 5
# How each non-ordered mode was spelled before the build; a mode outside the ordered set with no entry here reaches no known feed.
PRE_BUILD = {"recommendations": "", "random": "&random=1"}
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
UNORDERED_HEADERS = {"X-Client-IP": "192.0.2.173"}
ORDERED_HEADERS = {"X-Client-IP": "192.0.2.174"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# A missing ORDERED_FEED_MODES prints null rather than failing the import, so its absence reaches the tests instead of the collection.
_CONSTANTS_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    import server_config
    ordered = getattr(similar, "ORDERED_FEED_MODES", None)
    print(json.dumps({"feed": list(similar.FEED_MODES), "ordered": sorted(ordered) if ordered is not None else None, "threshold": server_config.VIDEO_ERROR_THRESHOLD}))
    """
)


def _constants() -> tuple[dict | None, str]:
    """The Engine's feed-mode constants and error threshold, or None with the reason they could not be read."""
    if not ENGINE_PY.exists():
        return None, f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _CONSTANTS_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        return None, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1]), ""


# Read once at collection, so both parametrizations follow the module as it is.
CONSTANTS, CONSTANTS_ERROR = _constants()
ORDERED = (CONSTANTS or {}).get("ordered")
UNORDERED = [mode for mode in (CONSTANTS or {}).get("feed", []) if mode not in (ORDERED or [])]


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _post(engine, path: str, headers: dict[str, str], body: dict) -> dict:
    status, payload = engine.request("POST", path, headers=headers, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path, status, payload)
    return payload


def _exclude(keys: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": video_id, "host": host} for video_id, host in keys]


def _reference(dataset, order: str, threshold: int) -> list[tuple[str, str]]:
    """The order's first rows as `fetch_ordered_page` reads them from whitelist.db, less those the Engine's moderation removes."""
    denied = {row["host"].lower() for row in dataset.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(row["channel_id"], row["instance_domain"].lower()) for row in dataset.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    rows = fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, error_threshold=threshold)
    kept = [r for r in rows if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked]
    return _keys(kept)


@pytest.mark.parametrize("mode", UNORDERED or ["FEED_MODES unreadable"])
def test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did(engine, mode):
    assert CONSTANTS is not None, CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    # A mode left out of ORDERED_FEED_MODES by mistake, such as hot, lands here and has no pre-build feed to match.
    assert mode in PRE_BUILD, (mode, ORDERED)  # C1
    before = _post(engine, f"/recommendations?limit={PAGE}{PRE_BUILD[mode]}", UNORDERED_HEADERS, {})
    # Control: the pre-build spellings serve a home page, not the random fallback, and the random feed (observed).
    if mode == "recommendations":
        assert before["seed"].get("mode") == "home" and "random" not in before["seed"], before["seed"]
    else:
        assert before["seed"] == {"random": True}, before["seed"]
    after = _post(engine, f"/recommendations?limit={PAGE}&mode={mode}", UNORDERED_HEADERS, {})
    # Before dispatch, mode=random served a home page: {"user_id": "local-user", "mode": "home"} (observed).
    assert after["seed"] == before["seed"], (mode, after["seed"])  # C1
    assert len(after["rows"]) == len(before["rows"]) == PAGE, (len(after["rows"]), len(before["rows"]))  # C1
    if mode == "recommendations":
        empty = _post(engine, f"/recommendations?limit={PAGE}&mode=", UNORDERED_HEADERS, {})
        assert empty["seed"] == before["seed"] and len(empty["rows"]) == PAGE, empty["seed"]  # C1


@pytest.mark.parametrize("order", ORDERED or ["ORDERED_FEED_MODES missing"])
def test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated(engine, dataset, order):
    assert CONSTANTS is not None, CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert ORDERED is not None, "handlers.similar has no ORDERED_FEED_MODES"  # C2
    assert order in CONSTANTS["feed"], (order, CONSTANTS["feed"])  # control: a mode the Engine accepts rather than refuses 400
    reference = _reference(dataset, order, CONSTANTS["threshold"])
    assert len(reference) >= 4 * PAGE, len(reference)  # control: the order holds three pages and a last page beyond them
    status, found = engine.request("GET", f"/api/v1/search/videos?q=linux&limit={LIKE_COUNT}", headers=ORDERED_HEADERS)
    assert status == 200 and len(found["rows"]) == LIKE_COUNT, found
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in found["rows"]]
    path = f"/recommendations?mode={quote(order)}&limit={PAGE}"

    liked = _post(engine, path, ORDERED_HEADERS, {"likes": likes})
    plain = _post(engine, path, ORDERED_HEADERS, {})
    second = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]))})
    # Page 3 excludes every row shown so far, as the pager sends it, plus the reference's last page: those rows lie past page 3, so a walk continuing after the shown rows is untouched by them, while one jumping len(exclude) rows ahead starts page 3 at index 3 * PAGE instead of 2 * PAGE.
    third = _post(engine, path, ORDERED_HEADERS, {"exclude": _exclude(_keys(plain["rows"]) + _keys(second["rows"]) + reference[-PAGE:])})
    # Control: signals and publish dates did not move the order while the requests ran, so the reference is the order they were served from.
    assert _reference(dataset, order, CONSTANTS["threshold"]) == reference

    # Before dispatch every mode served a home page, seed {"user_id": "local-user", "mode": "home"} (observed); the random feed's seed is {"random": True}.
    for payload in (liked, plain, second, third):
        assert "random" not in payload["seed"] and "mode" not in payload["seed"], payload["seed"]  # C2
    # A feed ranked by likes, or drawn afresh per request, differs here.
    assert _keys(liked["rows"]) == _keys(plain["rows"])  # C2
    first, following, last = _keys(plain["rows"]), _keys(second["rows"]), _keys(third["rows"])
    assert len(first) == len(following) == len(last) == PAGE, (len(first), len(following), len(last))  # C2
    # A walk ignoring `exclude` serves page 1 again; one honouring only the first page's keys serves page 2 again at page 3.
    assert not set(first) & set(following), sorted(set(first) & set(following))  # C2
    assert not set(first + following) & set(last), sorted(set(first + following) & set(last))  # C2
    # Another order's head, a shuffled page, a page that skips or restarts the order, or a count-offset walk (page 3 from index 3 * PAGE) differs from the reference prefix.
    assert first + following + last == reference[: 3 * PAGE], (first + following + last, reference[: 3 * PAGE])  # C2


GATEWAY_HOST = "g.example"
CLEAN_A = {"video_id": "vid-a", "video_uuid": "u-a", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "A"}
BLOCKED = {"video_id": "vid-b", "video_uuid": "u-b", "instance_domain": GATEWAY_HOST, "channel_id": "ch-blocked", "account_url": "https://g.example/a/two", "title": "B"}
CLEAN_C = {"video_id": "vid-c", "video_uuid": "u-c", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "C"}
# Same channel and account as the clean rows, so only the dislike can remove it.
DISLIKED = {"video_id": "vid-d", "video_uuid": "u-d", "instance_domain": GATEWAY_HOST, "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": "D"}
GATEWAY_ROWS = [CLEAN_A, BLOCKED, CLEAN_C, DISLIKED]
GATEWAY_PAGE = 10


def _hot_engine(received: list):
    """A stand-in Engine answering every POST with GATEWAY_ROWS, in order, recording each request's path."""

    class EngineStub(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("content-length") or 0))
            received.append(self.path)
            data = json.dumps({"seed": {}, "count": len(GATEWAY_ROWS), "rows": GATEWAY_ROWS}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), EngineStub)


def test_a_keyed_hot_page_drops_the_blocked_channel_and_disliked_video_and_asks_the_engine_for_twice_the_page(tmp_path):
    received: list[str] = []
    path = f"/recommendations?mode=hot&limit={GATEWAY_PAGE}"
    with _serving(_hot_engine(received)) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        client = ClientBackend(base, tmp_path / "users.db")
        status, unkeyed = client.request("POST", path, body={})
        assert status == 200, unkeyed
        status, minted = client.request("POST", "/api/profile")
        assert status == 201, minted
        conn = client_server.connect_db(client.db_path)
        try:
            profile_id = resolve_profile(conn, minted["key"])
            assert profile_id == minted["profile_id"]  # control: the second connection sees the minted profile
            add_block(conn, profile_id, block_target("channel", BLOCKED))
            with conn:
                write_dislike(conn, profile_id, DISLIKED, None)
        finally:
            conn.close()
        status, keyed = client.request("POST", path, headers={"X-Profile-Key": minted["key"]}, body={})
        assert status == 200, keyed

    assert len(received) == 2, received  # control: one Engine request per page
    # Control: with no profile nothing is filtered, so the page is the Engine's four rows under the limit sent.
    assert (urlparse(received[0]).path, parse_qs(urlparse(received[0]).query)) == ("/recommendations", {"mode": ["hot"], "limit": [str(GATEWAY_PAGE)]}), received[0]
    assert _keys(unkeyed["rows"]) == _keys(GATEWAY_ROWS), unkeyed["rows"]
    assert _keys(keyed["rows"]) == _keys([CLEAN_A, CLEAN_C]), keyed["rows"]  # regression pin: blocked channel and disliked video absent, Engine order kept
    assert (urlparse(received[1]).path, parse_qs(urlparse(received[1]).query)) == ("/recommendations", {"mode": ["hot"], "limit": [str(2 * GATEWAY_PAGE)]}), received[1]  # regression pin: mode forwarded, limit doubled
