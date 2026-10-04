"""Probe for plan 53 C2e: the text today's AudioPipe._feed records for an error raised at open on a media URL, through the scripted harness."""
from __future__ import annotations

import importlib.util
import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "active"))

from test_53_source_instance_fetch_adapter_phase1 import HOST, MEDIA_URL, OPEN_ERRORS, scripted_instance  # noqa: E402,F401
import pytest  # noqa: E402


def _worker():
    root = Path(__file__).resolve().parents[2]
    for p in (root / "engine" / "server", root / "engine" / "server" / "api"):
        sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location("probe_worker_c2e", root / "engine" / "server" / "db" / "jobs" / "translate-worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


@pytest.mark.parametrize("error, reason", OPEN_ERRORS.values(), ids=OPEN_ERRORS.keys())
def test_probe(scripted_instance, error, reason):
    worker = _worker()
    scripted_instance.monkeypatch.setattr(worker, "build_opener", scripted_instance.build_opener)
    scripted_instance.fail(MEDIA_URL, error)
    failed = []
    pipe = SimpleNamespace(url=MEDIA_URL, host=HOST, max_bytes=200_000, stop=threading.Event(), proc=SimpleNamespace(stdin=io.BytesIO()), _fail=failed.append)
    worker.AudioPipe._feed(pipe)
    print("C2E", repr(type(error).__name__), repr(failed), "opened", scripted_instance.opened, "timeouts", scripted_instance.socket_timeouts, "reason", repr(reason))
    assert False, "probe"
