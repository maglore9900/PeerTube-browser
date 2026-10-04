"""Probe: the phase 1 checkpoint's tests run against the plan's draft adapter (MUTATION env picks a wrong variant); the checkpoint records socket timeouts itself, so the harness is not patched."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "active"))

import test_internal_translate  # noqa: E402,F401  (puts engine/server on sys.path)
import data  # noqa: E402

spec = importlib.util.spec_from_file_location("data.source_fetch", HERE / "probe_53_draft_source_fetch.py")
draft = importlib.util.module_from_spec(spec)
sys.modules["data.source_fetch"] = draft
spec.loader.exec_module(draft)
data.source_fetch = draft
draft.MUTATION = os.environ.get("MUTATION") or None

from test_53_source_instance_fetch_adapter_phase1 import *  # noqa: E402,F401,F403
