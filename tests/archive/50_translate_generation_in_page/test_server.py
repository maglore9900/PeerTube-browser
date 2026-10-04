"""Retired from `tests/active/test_server.py` in the harvest of build 50-translate-generation-in-page.

`test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502` was merged (COMBINE) with that build's phase 3 checkpoint test of the GET gateway's Engine answers. Its five rows live on in `test_the_engine_answer_reaches_the_visitor_as_none_not_available_or_a_fixed_502`, whose `TRANSLATE_ENGINE_ANSWERS` table also holds the ten rows the checkpoint owned: 404 `Video not found` → 200 `{"state": "none", "available": false}`, an `available` that is a string, 1 or null, a running `total` that is missing, -1, true, a string or 1.5, and the state `bogus`, each → 502. "route missing" was in both tables and is kept once. Kept readable; the names it uses come from the active module and are not imported here, and the whole module is skipped.

The table it ran over read:

    TRANSLATE_ENGINE_ANSWERS = {
        "route missing": ((404, {"error": "Not found"}), TRANSLATE_FAILED),
        "engine 500": ((500, {"error": "translate-engine-sentinel"}), TRANSLATE_FAILED),
        "cues not a list": ((200, {"state": "ready", "cues": {"start": 1.0, "end": 2.5, "text": "Hello"}}), TRANSLATE_FAILED),
        "start true": ((200, {"state": "ready", "cues": [{"start": True, "end": 2.5, "text": "Hello"}]}), TRANSLATE_FAILED),
        "text not a string": ((200, {"state": "ready", "cues": [{"start": 1.0, "end": 2.5, "text": 7}]}), TRANSLATE_FAILED),
    }
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


def test_the_engine_answer_reaches_the_visitor_as_none_or_a_fixed_502(tmp_path, translate_bridge_token, engine_reply, expected):
    with _translate_engine(engine_reply) as (engine_base, seen), _keyed_client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as (base, key):  # noqa: F821
        answered = _translate_get(base, TRANSLATE_VALID, key)  # noqa: F821
    assert answered == expected
    # Control: the answer under test is the Engine's, from one bridge call.
    assert [entry[:2] for entry in seen] == [("POST", "/internal/translate")]
