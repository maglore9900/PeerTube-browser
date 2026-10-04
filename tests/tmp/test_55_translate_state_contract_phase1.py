"""Phase 1 checkpoint of plan 55: tests/active/fixtures/translate_contract.json states the translate contract, and the Client gateway's real parsers agree with it case by case.

Replay (C1), `fetch_translate` / `request_translate` in client/backend/lib/engine_api_client.py called directly against test_server.py's `_translate_engine` stub answering the case's Engine status and body:

- A state case through `fetch_translate` (with the case's `after`) and an enqueue case through `request_translate` returns exactly the case's `gateway` answer; a case whose `gateway` is "rejected" raises `EngineApiError` with the gateway's own "Engine translate ..." text, never a transport error's.
- Either way the stub saw exactly one POST, to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case, with the body exactly id, host and the case's `after` when it has one.

Coverage (C2), the fixture read as JSON: every case name is unique; the routes are exactly state and enqueue, each with at least one rejected case; `after` appears only on state cases; the states of the valid 200 cases carrying `available` and of those without it each equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route; each route has exactly one 404 `{"error": "Video not found"}` case.

The fixture is read at collection because the replay is parametrized over its cases; while it is missing, both tests fail on its absence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_server import _translate_engine  # noqa: E402

from lib.engine_api_client import TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, EngineApiError, fetch_translate, request_translate  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
# Read at collection because the replay is parametrized over the cases; a missing fixture collects one named stand-in that fails on the missing file, so the red is per test rather than a collection error.
CASES = json.loads(CONTRACT.read_text())["cases"] if CONTRACT.exists() else [{"name": "fixture missing"}]
ROUTES = {"state": "/internal/translate", "enqueue": "/internal/translate/enqueue"}
VIDEO_ID = "uuid-1"
HOST = "peer.example"


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route(case):
    assert CONTRACT.exists(), CONTRACT
    state_route = case["route"] == "state"
    with _translate_engine((case["engine"]["status"], case["engine"]["body"])) as (engine_base, seen):
        if case["gateway"] == "rejected":
            # The gateway's own refusals all read "Engine translate ..." (probed); a dropped or refused connection would carry the transport's text instead.
            with pytest.raises(EngineApiError, match=r"^Engine translate"):  # C1: rejected
                fetch_translate(engine_base, VIDEO_ID, HOST, after=case.get("after")) if state_route else request_translate(engine_base, VIDEO_ID, HOST)
        else:
            answered = fetch_translate(engine_base, VIDEO_ID, HOST, after=case.get("after")) if state_route else request_translate(engine_base, VIDEO_ID, HOST)
            assert answered == case["gateway"]  # C1: exactly the stated answer
    sent = {"id": VIDEO_ID, "host": HOST, **({"after": case["after"]} if "after" in case else {})}
    # Control: one request reached the case's route, so the answer or refusal above is the parse of that route's reply.
    assert [(entry[0], entry[1], entry[4]) for entry in seen] == [("POST", ROUTES[case["route"]], sent)]  # C1: exactly one request to that route


def test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names():
    assert CONTRACT.exists(), CONTRACT
    names = [case["name"] for case in CASES]
    assert sorted(name for name in set(names) if names.count(name) > 1) == []  # C2: every case name unique
    assert {case["route"] for case in CASES} == set(ROUTES)
    assert [case["name"] for case in CASES if "after" in case and case["route"] != "state"] == []
    for route, states in (("state", TRANSLATE_STATES), ("enqueue", TRANSLATE_REQUEST_STATES)):
        bodies = [case["engine"]["body"] for case in CASES if case["route"] == route and case["engine"]["status"] == 200 and case["gateway"] != "rejected"]
        assert {body["state"] for body in bodies if "available" in body} == states, route  # C2: with available
        assert {body["state"] for body in bodies if "available" not in body} == states, route  # C2: without available
        assert len([case for case in CASES if case["route"] == route and case["engine"] == {"status": 404, "body": {"error": "Video not found"}}]) == 1, route
        # Control: each route replays at least one refusal, so the replay's rejected half is exercised on both parsers.
        assert any(case["gateway"] == "rejected" for case in CASES if case["route"] == route), route
