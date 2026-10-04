"""Issue 45, phase 3 checkpoint: `serve`'s back-off after a whitelist.db requeue keeps `progress["at"]` advancing at least once per slice, and a stop set during it ends `serve` within about one slice without another claim.

`serve` runs in-process on a daemon thread over the rig's connection with `POLL_SECONDS` 0.05 and `TRANSIENT_BACKOFF_SECONDS` 1.5 on the loaded module, v-1 queued at 1000, and the `progress` dict handed to it held by the test. whitelist.db is deleted, so every lookup fails with the real `unable to open database file` and the job is requeued; a pass-through spy on `resolve_video` notes the time of each lookup. Once the second lookup has happened and its requeue has landed, the worker is inside the second back-off:

- C1: `progress["at"]` read every 0.01 s for 0.25 s (five slices) is never more than 0.1 s (two slices) old, with still only two lookups, so every read came from the wait and not a fresh claim. Probed: today's wait leaves it untouched (one distinct value, oldest read 0.25 s); a thread refreshing once per 0.05 s slice read the same way peaked at 0.050 s over 20 runs.
- C2: a stop set from the test thread with more than 0.5 s of the back-off left ends `serve` within 0.5 s, with still only two lookups, and the row queued with attempts 0. Phase 2's sliced wait already does this (probed: 0.041 s, two lookups, queued 0), so C2 is green before phase 3 and guards the new wait against ignoring the stop or claiming once more; the red is C1's.
"""
from __future__ import annotations

import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, MAX_DURATION, QUEUED_AT, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import enqueue_translate_job  # noqa: E402

BACKOFF_SECONDS = 1.5
SLICE_SECONDS = 0.05
SAMPLE_SECONDS = 0.25
SAMPLE_EVERY_SECONDS = 0.01
# Two slices: a once-per-slice refresh was probed peaking at 0.050 s; one refreshing every other slice or less would exceed it.
FRESH_SECONDS = 2 * SLICE_SECONDS
# Probed at 0.041 s with a 0.05 s slice; a wait that ignored the stop would run out the remaining ~1.2 s.
STOP_WITHIN_SECONDS = 0.5
LOOKUP_WAIT_SECONDS = 10 * BACKOFF_SECONDS


def _recording(resolve):
    """A pass-through spy on resolve_video noting the monotonic time of each call."""
    calls: list[float] = []

    def recorded(whitelist_path, video_id, host, max_duration):
        calls.append(time.monotonic())
        return resolve(whitelist_path, video_id, host, max_duration)

    recorded.calls = calls
    return recorded


def _until(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_serve_refreshes_progress_every_slice_of_the_back_off_and_a_stop_during_it_returns_within_a_slice_without_another_claim(rig, monkeypatch):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", BACKOFF_SECONDS)
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, progress), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reached its second lookup
        assert _until(lambda: rig.row().get("state") == "queued", BACKOFF_SECONDS / 2), rig.row()  # control: the second requeue landed, so serve is in the back-off

        ages = []
        end = time.monotonic() + SAMPLE_SECONDS
        while time.monotonic() < end:
            ages.append(time.monotonic() - progress["at"])
            time.sleep(SAMPLE_EVERY_SECONDS)

        assert max(ages) < FRESH_SECONDS, ages  # C1: no read through five slices of the wait found progress older than two slices
        assert len(lookups.calls) == 2, lookups.calls  # control: every read fell in the second back-off, not a fresh claim

        stop_at = time.monotonic()
        left = lookups.calls[1] + BACKOFF_SECONDS - stop_at
        assert left > STOP_WITHIN_SECONDS, left  # control: a wait ignoring the stop would outlast the bound below
        stop.set()
        thread.join(5)
        elapsed = time.monotonic() - stop_at
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and elapsed < STOP_WITHIN_SECONDS, (thread.is_alive(), elapsed)  # C2: serve returned within about one slice of the stop
    assert len(lookups.calls) == 2, lookups.calls  # C2: no claim after the stop
    row = rig.row()
    assert (row["state"], row["attempts"]) == ("queued", 0), row  # C2: the job is left requeued unspent
