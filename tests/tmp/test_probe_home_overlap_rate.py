"""Probe: how often do two plain home draws for the same 5 likes share no row (the control at test_similar.py:213)?"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401
from test_similar import _home, _key_set, _likes  # noqa: E402

PAIRS = 10


@pytest.mark.parametrize("query", ["linux", "cooking", "music"])
def test_probe_overlap(engine, query):
    likes = _likes(engine, query)
    overlaps = []
    for _ in range(PAIRS):
        time.sleep(1.1)
        a = _home(engine, {"likes": likes})
        time.sleep(1.1)
        b = _home(engine, {"likes": likes})
        overlaps.append(len(_key_set(a) & _key_set(b)))
    print(f"\nPROBE {query} overlaps={overlaps} zero={overlaps.count(0)}/{PAIRS}")
