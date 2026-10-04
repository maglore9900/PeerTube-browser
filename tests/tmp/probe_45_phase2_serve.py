"""Probe for issue 45 phase 2: the checkpoint's C1 body against today's serve, with the missing constant supplied, to see which assertion it fails."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_translate_worker import clip, rig  # noqa: E402,F401
from test_45_translate_worker_whitelist_locked_at_phase2 import test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job as c1  # noqa: E402


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_probe_c1_against_todays_serve(rig, monkeypatch, injected):
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", 99.0, raising=False)
    c1(rig, monkeypatch, injected)
