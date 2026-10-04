"""Probe: the phase 2 checkpoint against wrong variants of the drafted route and worker, one parametrized run per variant."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_53_phase2_vs_draft as base  # noqa: E402
from probe_53_phase2_vs_draft import *  # noqa: E402,F401,F403

MUTATIONS = ["fresh budget", "no reason logged", "bare", "reason on a non-object"]
WORKERS = {mutation: base.draft_worker(mutation) for mutation in MUTATIONS}


@pytest.fixture(autouse=True, params=MUTATIONS)
def mutation(request, monkeypatch):
    monkeypatch.setattr(base, "MUTATION", request.param)
    monkeypatch.setattr(base.checkpoint, "WORKER", WORKERS[request.param])
    return request.param
