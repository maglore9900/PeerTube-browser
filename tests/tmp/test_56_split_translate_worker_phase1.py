"""Phase 1 checkpoint for `engine/server/db/jobs/translate-worker.py`: `serve`, run in-process on a daemon thread over the rig's connection with a `StubRunner`, on a deleted whitelist.db and with the real `resolve_video` wrapped by a recorder of each lookup's time and key, takes its timings as keyword arguments (`poll_seconds`, `backoff_seconds`) and waits out a whitelist.db requeue on those values, not on the module's 2 s and 30 s defaults, which no test here touches. Each timing is read at two values, so a serve that hard-codes either one misses the other.

- After a requeue, the next lookup of v-1 comes no sooner than the `backoff_seconds` given (0.5 s or 1.0 s) and less than a quarter second past it, far under the 30 s default; it is again v-1, never d-1 queued behind it, and the row stays queued with attempts 0 and queued_at 1000.
- Through the second back-off, `progress["at"]` read for five given `poll_seconds` slices (0.05 s or 0.2 s) is never more than two slices old, against the 2 s default slice, and at its oldest more than half a slice old, so the wait is slept in the given slices rather than some finer fixed one; a stop set during it ends `serve` within 0.5 s without another lookup.
"""
from __future__ import annotations

import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import DENIED_HOST, HOST, MAX_DURATION, QUEUED_AT, StubRunner, _recording, _until, clip, rig  # noqa: E402,F401

from data.subtitles import enqueue_translate_job  # noqa: E402

# Passed to serve as poll_seconds for the gap test, so a stop is seen every slice.
GAP_SLICE_SECONDS = 0.05
# The gap was probed at 0.5003 s and 1.0003 s for these back-offs; a serve hard-coding either one waits the other, which the slack below excludes in both directions.
GAP_BACKOFF_SECONDS = (0.5, 1.0)
GAP_SLACK_SECONDS = 0.25
# Probed at 0.0447 s and 0.199 s for these slices: the oldest read sits just under one slice, so more than half a slice and less than two hold, and a serve hard-coding either slice, or the 2 s default, breaks one bound at the other.
LIVE_SLICE_SECONDS = (0.05, 0.2)
# Long enough that the requeue landing, five slices of sampling and the stop bound fit inside the second back-off; probed leaving 1.49 s after sampling five 0.2 s slices.
LIVE_BACKOFF_SECONDS = 2.5
# Several of the longest back-off and still under the 30 s default, so a serve waiting the default rather than the value it was given misses it.
LOOKUP_WAIT_SECONDS = 15.0
SAMPLE_SLICES = 5
SAMPLE_EVERY_SECONDS = 0.01
# Probed at 0.045 s and 0.19 s for the two slices; a wait that ignored the stop would run out the remaining ~1.5 s.
STOP_WITHIN_SECONDS = 0.5


def _serving(rig, stop: threading.Event, progress: dict, **timings: float) -> tuple[threading.Thread, list]:
    """`serve` on a started daemon thread with `timings` as its keyword arguments, and the list any exception it raised lands in."""
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    errors: list = []

    def target() -> None:
        try:
            rig.worker.serve(rig.conn, args, StubRunner(rig), stop, progress, **timings)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, errors


@pytest.mark.parametrize("backoff", GAP_BACKOFF_SECONDS, ids=lambda seconds: f"{seconds}s")
def test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job(rig, monkeypatch, backoff):
    """`serve`, given backoff_seconds 0.5 or 1.0, after a whitelist.db requeue looks up the same head job again no sooner than the given back-off and less than 0.25 s past it, far under the 30 s default; every lookup is for v-1 and never for d-1 queued behind it, and after a stop the row is queued with attempts 0 and queued_at kept."""
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    # Queued behind v-1, so a requeue that lost v-1's place at the head would show as a d-1 lookup.
    assert tuple(enqueue_translate_job(rig.conn, "d-1", DENIED_HOST, "en", 50, QUEUED_AT + 1)) == ("queued", "queued")
    stop = threading.Event()
    thread, errors = _serving(rig, stop, {"at": time.monotonic()}, poll_seconds=GAP_SLICE_SECONDS, backoff_seconds=backoff)
    try:
        assert _until(lambda: len(lookups.calls) >= 2 or not thread.is_alive(), LOOKUP_WAIT_SECONDS) and len(lookups.calls) >= 2, (errors, lookups.calls)  # C1: reclaimed within 15 s, so not after the 30 s default
        gap = lookups.calls[1][0] - lookups.calls[0][0]
        assert gap >= backoff, lookups.calls  # C1: no sooner than the given back-off after the first
        assert gap < backoff + GAP_SLACK_SECONDS, lookups.calls  # C1: and not some other fixed wait than the one given
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and errors == [], errors  # control: serve returned cleanly, so the row below is at rest
    assert {call[1:] for call in lookups.calls} == {("v-1", HOST)}, lookups.calls  # every lookup was the head job, never d-1
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # the same head job, requeued unspent at its place


@pytest.mark.parametrize("slice_seconds", LIVE_SLICE_SECONDS, ids=lambda seconds: f"{seconds}s")
def test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim(rig, monkeypatch, slice_seconds):
    """Inside `serve`'s second back-off on a deleted whitelist.db, given poll_seconds 0.05 or 0.2 and backoff_seconds 2.5, `progress["at"]` read every 0.01 s for five slices is never more than two given slices old, so the heartbeat never reads the wait as a stall, and at its oldest more than half a given slice old, so the slice is the one given; a stop set with more than 0.5 s of the back-off left ends `serve` within 0.5 s, with no lookup after the stop and the row queued with attempts 0."""
    lookups = _recording(rig.worker.resolve_video)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    stop = threading.Event()
    progress = {"at": time.monotonic()}
    thread, errors = _serving(rig, stop, progress, poll_seconds=slice_seconds, backoff_seconds=LIVE_BACKOFF_SECONDS)
    try:
        assert _until(lambda: len(lookups.calls) >= 2 or not thread.is_alive(), LOOKUP_WAIT_SECONDS) and len(lookups.calls) >= 2, (errors, lookups.calls)  # control: serve reached its second lookup on the given back-off
        assert _until(lambda: rig.row().get("state") == "queued", LIVE_BACKOFF_SECONDS / 2), rig.row()  # control: the second requeue landed, so serve is in the back-off

        ages = []
        end = time.monotonic() + SAMPLE_SLICES * slice_seconds
        while time.monotonic() < end:
            ages.append(time.monotonic() - progress["at"])
            time.sleep(SAMPLE_EVERY_SECONDS)

        assert max(ages) < 2 * slice_seconds, ages  # C2: no read through five slices of the wait found progress older than two given slices
        assert max(ages) > slice_seconds / 2, ages  # C2: and progress did age most of a given slice, so the wait is slept in that slice and not a finer fixed one
        assert len(lookups.calls) == 2, lookups.calls  # control: every read fell in the second back-off, not a fresh claim

        stop_at = time.monotonic()
        left = lookups.calls[1][0] + LIVE_BACKOFF_SECONDS - stop_at
        assert left > STOP_WITHIN_SECONDS, left  # control: a wait ignoring the stop would outlast the bound below
        stop.set()
        thread.join(5)
        elapsed = time.monotonic() - stop_at
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive() and elapsed < STOP_WITHIN_SECONDS, (thread.is_alive(), elapsed)  # serve returned within 0.5 s of the stop, well short of the back-off left
    assert errors == [], errors  # control: serve returned, not raised
    assert len(lookups.calls) == 2, lookups.calls  # no claim after the stop
    row = rig.row()
    assert (row["state"], row["attempts"]) == ("queued", 0), row  # the job is left requeued unspent
