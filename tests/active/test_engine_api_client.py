"""`client/backend/lib/engine_api_client.py` agrees with the translate contract (`tests/active/fixtures/translate_contract.json`) case by case, and the contract's valid states are exactly the gateway's.

Replay, `fetch_translate` / `request_translate` / `cancel_translate` called directly against a stub Engine answering the case's Engine status and body:

- A state case through `fetch_translate` (with the case's `after`), an enqueue case through `request_translate` and a cancel case through `cancel_translate` returns exactly the case's `gateway` answer; a case whose `gateway` is "rejected" raises `EngineApiError` with the gateway's own "Engine translate ..." text, never a transport error's.
- Either way the stub saw exactly one POST, to /internal/translate for a state case, /internal/translate/enqueue for an enqueue case and /internal/translate/cancel for a cancel case, with the body exactly id, host and the case's `after` when it has one.

Coverage, the fixture read as JSON: every case name is unique; the routes are exactly state, enqueue and cancel, each with at least one rejected case; `after` appears only on state cases; the states of the valid 200 cases carrying `available` and of those without it each equal TRANSLATE_STATES on the state and cancel routes and TRANSLATE_REQUEST_STATES on the enqueue route; each route has exactly one 404 `{"error": "Video not found"}` case.

The fixture is read at collection because the replay is parametrized over its cases; while it is missing, both tests fail on its absence. The stub Engine (`_TranslateEngine`, `_serving`, `_translate_engine`) is this file's own copy of test_server.py's, so the two groups stay independent.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from lib.engine_api_client import TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, EngineApiError, cancel_translate, fetch_translate, request_translate

CONTRACT = Path(__file__).resolve().parent / "fixtures" / "translate_contract.json"
# Read at collection because the replay is parametrized over the cases; a missing fixture collects one named stand-in that fails on the missing file, so the red is per test rather than a collection error.
CASES = json.loads(CONTRACT.read_text())["cases"] if CONTRACT.exists() else [{"name": "fixture missing"}]
ROUTES = {"state": "/internal/translate", "enqueue": "/internal/translate/enqueue", "cancel": "/internal/translate/cancel"}
VIDEO_ID = "uuid-1"
HOST = "peer.example"


@contextmanager
def _serving(srv):
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


class _TranslateEngine(BaseHTTPRequestHandler):
    """Records each request as (method, path, X-Bridge-Token, X-Request-ID, JSON body) and answers `server.reply`, a (status, payload) pair."""

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        self.server.seen.append((self.command, self.path, self.headers.get("X-Bridge-Token"), self.headers.get("X-Request-ID"), json.loads(raw) if raw else None))
        status, payload = self.server.reply
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # A route that proxied by GET instead of the bridge POST would be recorded too.
    do_GET = do_POST

    def log_message(self, *args):
        pass


@contextmanager
def _translate_engine(reply):
    """A _TranslateEngine on 127.0.0.1:0 answering `reply`; yields its base URL and its request log."""
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _TranslateEngine)
    stub.seen = []
    stub.reply = reply
    with _serving(stub) as base:
        yield base, stub.seen


def _gateway_call(case: dict, engine_base: str) -> dict:
    """The case's route through its gateway function: fetch_translate with the case's after, request_translate or cancel_translate."""
    if case["route"] == "state":
        return fetch_translate(engine_base, VIDEO_ID, HOST, after=case.get("after"))
    return (cancel_translate if case["route"] == "cancel" else request_translate)(engine_base, VIDEO_ID, HOST)


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route(case):
    """Each contract case parses through the gateway's real fetch_translate, request_translate or cancel_translate to exactly its stated answer, or to EngineApiError where it says rejected, from one request to its route."""
    assert CONTRACT.exists(), CONTRACT
    with _translate_engine((case["engine"]["status"], case["engine"]["body"])) as (engine_base, seen):
        if case["gateway"] == "rejected":
            # The gateway's own refusals all read "Engine translate ..."; a dropped or refused connection would carry the transport's text instead.
            with pytest.raises(EngineApiError, match=r"^Engine translate"):
                _gateway_call(case, engine_base)
        else:
            assert _gateway_call(case, engine_base) == case["gateway"]  # exactly the stated answer
    sent = {"id": VIDEO_ID, "host": HOST, **({"after": case["after"]} if "after" in case else {})}
    # Control: one request reached the case's route, so the answer or refusal above is the parse of that route's reply.
    assert [(entry[0], entry[1], entry[4]) for entry in seen] == [("POST", ROUTES[case["route"]], sent)]


def test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names():
    """The contract's valid 200 states equal TRANSLATE_STATES on the state and cancel routes and TRANSLATE_REQUEST_STATES on the enqueue route, with and without available, under unique case names."""
    assert CONTRACT.exists(), CONTRACT
    names = [case["name"] for case in CASES]
    assert sorted(name for name in set(names) if names.count(name) > 1) == []  # every case name unique
    assert {case["route"] for case in CASES} == set(ROUTES)
    assert [case["name"] for case in CASES if "after" in case and case["route"] != "state"] == []
    for route, states in (("state", TRANSLATE_STATES), ("enqueue", TRANSLATE_REQUEST_STATES), ("cancel", TRANSLATE_STATES)):
        bodies = [case["engine"]["body"] for case in CASES if case["route"] == route and case["engine"]["status"] == 200 and case["gateway"] != "rejected"]
        assert {body["state"] for body in bodies if "available" in body} == states, route  # with available
        assert {body["state"] for body in bodies if "available" not in body} == states, route  # without available
        assert len([case for case in CASES if case["route"] == route and case["engine"] == {"status": 404, "body": {"error": "Video not found"}}]) == 1, route
        # Control: each route replays at least one refusal, so the replay's rejected half is exercised on both parsers.
        assert any(case["gateway"] == "rejected" for case in CASES if case["route"] == route), route
