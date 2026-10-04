from __future__ import annotations

import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, MAX_DURATION, QUEUED_AT, StubRunner, _recording, _until, clip, rig  # noqa: E402,F401

from data.subtitles import enqueue_translate_job  # noqa: E402


def _args(rig):
    return Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)


@pytest.mark.parametrize("backoff", [0.5, 1.0])
def test_gap(rig, monkeypatch, backoff):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", backoff)
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, _args(rig), StubRunner(rig), stop, {"at": time.monotonic()}), daemon=True)
    thread.start()
    _until(lambda: len(lookups.calls) >= 3, 10)
    stop.set()
    thread.join(5)
    print("PROBE gap", backoff, [round(b[0] - a[0], 4) for a, b in zip(lookups.calls, lookups.calls[1:])])


@pytest.mark.parametrize("slice_", [0.05, 0.2])
def test_ages(rig, monkeypatch, slice_):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", slice_)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", 2.5)
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, _args(rig), StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    _until(lambda: len(lookups.calls) >= 2, 10)
    _until(lambda: rig.row().get("state") == "queued", 1)
    ages = []
    end = time.monotonic() + 5 * slice_
    while time.monotonic() < end:
        ages.append(time.monotonic() - progress["at"])
        time.sleep(0.01)
    stop_at = time.monotonic()
    left = lookups.calls[1][0] + 2.5 - stop_at
    stop.set()
    thread.join(5)
    print("PROBE ages", slice_, "max", round(max(ages), 4), "n", len(ages), "left", round(left, 3), "stop", round(time.monotonic() - stop_at, 4), "calls", len(lookups.calls))


def test_kwargs(rig):
    errors = []

    def target():
        try:
            rig.worker.serve(rig.conn, _args(rig), StubRunner(rig), threading.Event(), {"at": time.monotonic()}, poll_seconds=0.05, backoff_seconds=0.5)
        except BaseException as exc:
            errors.append(repr(exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(1)
    print("PROBE kwargs", thread.is_alive(), errors)
