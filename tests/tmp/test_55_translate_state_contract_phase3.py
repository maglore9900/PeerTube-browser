"""Phase 3 checkpoint of plan 55: the Engine's /internal/translate and /internal/translate/enqueue handlers, driven into each state by the `ENGINE_DRIVERS` table phase 3 adds to tests/active/test_internal_translate.py, answer with the keys and JSON types of tests/active/fixtures/translate_contract.json, and their not-found answer is the fixture's body.

The fixture is read inside each test. A driver is called as `ENGINE_DRIVERS[(route, state)](subtitles_path, whitelist, monkeypatch, case)` and returns the responses its route's handler wrote. Both real handlers are wrapped in a pass-through recorder (a spy; the real handler still runs and answers). While test_internal_translate.py has no `ENGINE_DRIVERS`, the table test and every shape test fail on its absence.

- Table (C1): the (route, state) set of the fixture's valid 200 cases that carry available has no member without a driver, and the table has no driver without such a case. As a control, that set equals the 13 (route, state) pairs written down here (six states on the state route, those plus busy on the enqueue route), which the shape test is parametrized over.
- Shape (C1), for every such case of the (route, state): the answer is exactly one 200 whose key-to-JSON-type map equals the case's (bool before number). Where the case has cues, the answer's cues are non-empty and each cue's key-to-type map is one of the case's cues'. Controls: the fixture carries the (route, state); that route's real handler was called once and the other route's not at all, and the driver returned exactly what the handler wrote; the request carried the case's `after` exactly when the case has one; the answer's state is the state under test.
- Not found (C2), on each route: an unknown video and the actively denylisted video (deny row stored as DENIED.EXAMPLE) each answer exactly `[[404, <the fixture's Video not found body for that route>]]` (that no instance is fetched is test_internal_translate.py's claim, not this one). As a control, the same denied video answers 200 once its deny row is inactive. This half drives the real handlers directly and holds before the phase lands, since the phase changes no runtime code.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_internal_translate as durable  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
# Every (route, state) the Engine answers, written down: the gateway's six states on the state route, and those plus busy on the enqueue route.
ROUTE_STATES = [("state", state) for state in ("none", "queued", "running", "ready", "already_english", "failed")] + [("enqueue", state) for state in ("none", "queued", "running", "ready", "already_english", "failed", "busy")]
HANDLERS = {"state": "handle_internal_translate", "enqueue": "handle_internal_translate_enqueue"}


def _contract_cases() -> list[dict]:
    return json.loads(CONTRACT.read_text())["cases"]


def _engine_cases() -> list[dict]:
    """The fixture's valid 200 cases that carry available, the shape this Engine always answers in."""
    return [case for case in _contract_cases() if case["gateway"] != "rejected" and case["engine"]["status"] == 200 and "available" in case["engine"]["body"]]


def _drivers() -> dict:
    drivers = getattr(durable, "ENGINE_DRIVERS", None)
    assert drivers is not None, "tests/active/test_internal_translate.py has no ENGINE_DRIVERS: the phase's driver table is not written yet"
    return drivers


def _json_type(value: object) -> str:
    """The JSON type a value is written as; bool first, since a bool is also an int."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def _types(body: dict) -> dict[str, str]:
    return {key: _json_type(value) for key, value in body.items()}


@pytest.fixture
def whitelist(tmp_path):
    conn = durable._whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


def _record_handlers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict, list]]:
    """Wrap both real route handlers so every call is recorded as (route, request body, responses written); the real handler still runs and writes the answer."""
    module = importlib.import_module("handlers.internal_translate")
    calls: list[tuple[str, dict, list]] = []
    for route, name in HANDLERS.items():
        def recording(handler, server, _route=route, _real=getattr(module, name)):
            body = json.loads(handler.rfile.getvalue())
            handled = _real(handler, server)
            calls.append((_route, body, [list(response) for response in handler.responses]))
            return handled
        monkeypatch.setattr(module, name, recording)
    return calls


def test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states():
    fixture = {(case["route"], case["engine"]["body"]["state"]) for case in _engine_cases()}
    drivers = set(_drivers())
    assert sorted(fixture - drivers) == []  # C1: no fixture (route, state) without a driver
    assert sorted(drivers - fixture) == []  # C1: no driver without a fixture (route, state)
    # Control: the list the shape test is parametrized over is the fixture's own set, so every fixture (route, state) is driven there.
    assert fixture == set(ROUTE_STATES)


@pytest.mark.parametrize("route, state", ROUTE_STATES, ids=[f"{route} {state}" for route, state in ROUTE_STATES])
def test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included(tmp_path, whitelist, monkeypatch, route, state):
    cases = [case for case in _engine_cases() if (case["route"], case["engine"]["body"]["state"]) == (route, state)]
    assert cases, (route, state)  # control: the fixture carries this (route, state)
    drive = _drivers()[(route, state)]
    calls = _record_handlers(monkeypatch)
    for index, case in enumerate(cases):
        expected = case["engine"]["body"]
        calls.clear()
        responses = drive(tmp_path / f"subtitles-{index}.db", whitelist, monkeypatch, case)
        # Control: this route's real handler answered once, the other route's not at all, and the driver returned what the handler wrote, so the answer below is the handler's and not one the driver made up.
        assert [(called, written) for called, _, written in calls] == [(route, responses)], case["name"]
        # Control: the request carried the case's after exactly when the case has one.
        assert {key: value for key, value in calls[0][1].items() if key == "after"} == ({"after": case["after"]} if "after" in case else {}), case["name"]
        ((status, answer),) = responses
        assert status == 200, (case["name"], answer)  # C1
        assert answer["state"] == state, (case["name"], answer)  # control: the driver reached the state under test
        assert _types(answer) == _types(expected), (case["name"], answer)  # C1: exactly the case's keys, each value of the case's JSON type
        if "cues" in expected:
            # Non-empty wherever the case's are, so the per-cue check below reads at least one cue.
            assert bool(answer["cues"]) == bool(expected["cues"]), (case["name"], answer)  # C1
            assert all(_types(cue) in [_types(want) for want in expected["cues"]] for cue in answer["cues"]), (case["name"], answer)  # C1: each cue's keys and JSON types are the case's cues'


@pytest.mark.parametrize("route", ["state", "enqueue"])
def test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route(tmp_path, whitelist, monkeypatch, route):
    (body,) = [case["engine"]["body"] for case in _contract_cases() if case["route"] == route and case["engine"]["status"] == 404 and case["gateway"] != "rejected"]
    answer = durable._state if route == "state" else durable._enqueue
    instance = durable._instance(True)
    internal_translate = durable._route(instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    server = durable._server(whitelist, subtitles_path)
    # A fresh beat, so the enqueue control below queues rather than answering none for want of a worker.
    durable._beat(subtitles_path, 0)
    durable._set_denied(whitelist, True)  # stored as DENIED.EXAMPLE
    denied = {"id": durable.DENIED_VIDEO[1], "host": durable.DENIED_HOST}
    assert answer(internal_translate, server, {"id": "no-such-video", "host": durable.HOST}) == [[404, body]]  # C2: unknown video
    assert answer(internal_translate, server, denied) == [[404, body]]  # C2: actively denylisted video
    # Control: with the deny inactive the same video is answered 200, so the 404 above is the denylist's doing.
    durable._set_denied(whitelist, False)
    assert answer(internal_translate, server, denied)[0][0] == 200
