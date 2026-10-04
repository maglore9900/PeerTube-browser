"""Probe: the C2e test against the draft adapter narrowed to catch only HTTPError and ValueError, as the claim auditor's wrong implementation."""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import probe_53_checkpoint_vs_draft as harness  # noqa: E402
from test_53_source_instance_fetch_adapter_phase1 import MEDIA_OPEN_ERRORS, scripted_instance, test_stream_media_names_an_error_raised_at_open_in_todays_text  # noqa: E402,F401


@pytest.mark.parametrize("error, text", MEDIA_OPEN_ERRORS.values(), ids=MEDIA_OPEN_ERRORS.keys())
def test_narrowed(scripted_instance, monkeypatch, error, text):
    monkeypatch.setattr(harness.draft, "_FETCH_ERRORS", (urllib.error.HTTPError, ValueError))
    test_stream_media_names_an_error_raised_at_open_in_todays_text(scripted_instance, error, text)
