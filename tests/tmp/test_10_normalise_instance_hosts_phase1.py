"""Phase 1 checkpoint: `data.moderation.normalize_host_token`, the Engine's port of the crawler's `normalizeHostToken`.

- `tests/active/host_tokens.json` holds exactly the 15 input -> expected pairs pinned by the requirements (WHATWG `URL.hostname` values, null for None), so the fixture the port is checked against cannot drift to match the port.
- For every pinned pair, and so for every pair in that fixture, `normalize_host_token(input)` returns the expected value, and None where it is null.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# The module, not the name: the phase adds the function, so a missing one must fail each case rather than the whole file's collection.
import data.moderation as moderation  # noqa: E402

FIXTURE = ROOT / "tests" / "active" / "host_tokens.json"

# The pinned values from the requirements, written out independently of the fixture the phase creates.
PINNED = {
    " Tube.Example ": "tube.example",
    "tube.example.": "tube.example",
    "..tube.example..": "tube.example",
    "https://Tube.Example/": "tube.example",
    "http://tube.example:8080/path": "tube.example",
    "https://user@tube.example": "tube.example",
    "tube.example/videos": "tube.example",
    "tube.example:9000": "tube.example:9000",
    "https://[::1]:8080/": "[::1]",
    "https://bücher.example/": "xn--bcher-kva.example",
    "": None,
    "   ": None,
    ".": None,
    "https://": None,
    "https://tube.example./": "tube.example.",
}


def test_fixture_holds_exactly_the_pinned_pairs():
    # Read at run time: the phase creates the fixture, so reading it at import would stop collection instead of failing this test.
    pairs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(pairs) == len(PINNED)  # C1
    assert {pair["input"]: pair["expected"] for pair in pairs} == PINNED  # C1


@pytest.mark.parametrize("value,expected", PINNED.items(), ids=[repr(value) for value in PINNED])
def test_normalize_host_token_returns_pinned_value(value, expected):
    assert moderation.normalize_host_token(value) == expected  # C1
