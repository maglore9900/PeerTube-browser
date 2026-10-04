"""Probe: the phase 1 checkpoint against wrong variants of the draft adapter, one parametrized run per variant."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_53_checkpoint_vs_draft as base  # noqa: E402
from probe_53_checkpoint_vs_draft import *  # noqa: E402,F401,F403

MUTATIONS = ["ignore stop", "shared handler", "read past cap", "consume before check", "wrap broken pipe", "constant media cap"]


@pytest.fixture(autouse=True, params=MUTATIONS)
def mutation(request, monkeypatch):
    monkeypatch.setattr(base.draft, "MUTATION", request.param)
    return request.param
