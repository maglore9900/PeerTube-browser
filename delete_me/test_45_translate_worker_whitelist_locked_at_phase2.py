"""Issue 45, phase 2 checkpoint: `serve` backs off after a whitelist.db requeue, and the requeued job runs once whitelist.db is usable.

- Back-off: `serve` runs in-process on a daemon thread over the rig's connection with `POLL_SECONDS` 0.05 and `TRANSIENT_BACKOFF_SECONDS` 1.0 on the loaded module, v-1 queued at 1000 and d-1 queued behind it. Its whitelist lookup fails every time, either from an injected `database is locked` or from a deleted file (the real `unable to open database file`), and a recorder notes when each lookup happens and its key. The second lookup comes at least 1.0 s after the first, and both are for v-1. After a stop the row is back to queued with attempts 0 and queued_at 1000.
- Recovery: a job requeued by `run_job` is first seen queued with attempts 0. When the lock is released (one injected `database is locked`, then the real lookup) or the deleted file is rewritten, `claim_translate_job` hands back v-1 with attempts 1. That run ends ready/whisper with queued_at 1000, the reclaim's started_at and attempts 1, the four transcribed cues, and the instance and media URLs each requested once. Phase 1 already delivered this, so it is green before phase 2 (C2 exempted from the red by the operator). It drives `run_job` and `claim_translate_job` directly and never runs `serve`, so it checks recovery at those seams only, not past a back-off in `serve`'s loop.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import CHUNK_1, CHUNK_3, DENIED_HOST, HOST, INSTANCE_THEN_JSON, JOB_VIDEOS, MAX_DURATION, MEDIA_URL, QUEUED_AT, STARTED_AT, StubRunner, _whitelist, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job  # noqa: E402

LOCKED = "database is locked"
# Shortened on the loaded module; without a back-off serve was probed reclaiming about 0.1 ms after each requeue.
BACKOFF_SECONDS = 1.0
SLICE_SECONDS = 0.05
# Ten back-offs: a serve still waiting the 30 s default, not the module's value, misses it.
LOOKUP_WAIT_SECONDS = 10 * BACKOFF_SECONDS


def _recording(resolve, locked_calls: int | None):
    """A resolve_video stand-in noting (monotonic time, video_id, host) per call; it raises `database is locked` for the first `locked_calls` calls (None: every call) and otherwise calls `resolve`."""
    calls: list[tuple[float, str, str]] = []

    def recorded(whitelist_path, video_id, host, max_duration):
        calls.append((time.monotonic(), video_id, host))
        if locked_calls is None or len(calls) <= locked_calls:
            raise sqlite3.OperationalError(LOCKED)
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


@pytest.mark.parametrize("injected", [True, False], ids=["injected lock", "missing file"])
def test_serve_waits_the_back_off_before_its_next_lookup_of_the_same_head_job(rig, monkeypatch, injected):
    monkeypatch.setattr(rig.worker, "POLL_SECONDS", SLICE_SECONDS)
    # raising=False: until the phase adds the constant the test must still reach serve, so the red is the timing below and not this setup.
    monkeypatch.setattr(rig.worker, "TRANSIENT_BACKOFF_SECONDS", BACKOFF_SECONDS, raising=False)
    lookups = _recording(rig.worker.resolve_video, locked_calls=None if injected else 0)
    monkeypatch.setattr(rig.worker, "resolve_video", lookups)
    if not injected:
        rig.whitelist.unlink()
    assert tuple(enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    # Queued behind v-1, so a requeue that lost v-1's place at the head would show as a d-1 lookup.
    assert tuple(enqueue_translate_job(rig.conn, "d-1", DENIED_HOST, "en", 50, QUEUED_AT + 1)) == ("queued", "queued")
    args = Namespace(whitelist_db=rig.whitelist, max_duration=MAX_DURATION, max_bytes=len(rig.clip), max_chunk_seconds=1)
    stop = threading.Event()
    thread = threading.Thread(target=rig.worker.serve, args=(rig.conn, args, StubRunner(rig), stop, {"at": time.monotonic()}), daemon=True)
    thread.start()
    try:
        assert _until(lambda: len(lookups.calls) >= 2, LOOKUP_WAIT_SECONDS), lookups.calls  # control: serve reclaimed within ten back-offs
        assert lookups.calls[1][0] - lookups.calls[0][0] >= BACKOFF_SECONDS, lookups.calls  # C1: no sooner than the back-off after the first
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()  # control: serve returned, so the row below is at rest
    assert {call[1:] for call in lookups.calls} == {("v-1", HOST)}, lookups.calls  # C1: every lookup was the head job, never d-1
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # C1: the same head job, requeued unspent at its place


@pytest.mark.parametrize("case", ["lock released", "file restored"])
def test_a_job_requeued_on_whitelist_db_claimed_again_once_it_is_usable_runs_to_ready_with_its_queued_at_kept(rig, monkeypatch, case):
    if case == "lock released":
        monkeypatch.setattr(rig.worker, "resolve_video", _recording(rig.worker.resolve_video, locked_calls=1))
    else:
        rig.whitelist.unlink()
    rig.run(StubRunner(rig))
    row = rig.row()
    assert (row["state"], row["attempts"], row["queued_at"]) == ("queued", 0, QUEUED_AT), row  # control: requeued unspent, so what follows is a reclaim
    if case == "file restored":
        _whitelist(rig.whitelist, JOB_VIDEOS, deny=True)

    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT + 1)

    assert rig.job is not None and (rig.job["video_id"], rig.job["instance_domain"], rig.job["started_at"], rig.job["attempts"]) == ("v-1", HOST, STARTED_AT + 1, 1), rig.job and dict(rig.job)  # C2: the requeued row is claimable again
    rig.run(StubRunner(rig))
    row = rig.row()
    assert (row["state"], row["source"], row["queued_at"], row["started_at"], row["attempts"], row["error"]) == ("ready", "whisper", QUEUED_AT, STARTED_AT + 1, 1, None), row  # C2: the reclaim ran to ready, queued_at kept
    assert json.loads(row["cues_json"]) == CHUNK_1 + CHUNK_3  # C2: transcribed like any other job
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # C2: the whole pipeline once, on the reclaim only
