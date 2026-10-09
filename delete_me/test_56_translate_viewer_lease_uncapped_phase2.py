"""Plan 56 phase 2 checkpoint: a page-queued translate job whose viewer lease has lapsed leaves subtitles.db, dropped at claim while queued or abandoned at its first chunk-loop wake while running; an unleased command-line job is never dropped.

Claim (the store functions against a tmp subtitles.db): six rows, a running row leased on the cutoff (queued and claimed before the rest), a queued row whose `wanted_at` sits exactly on the cutoff (queued first), a queued unleased row, a second queued row on the cutoff queued behind the unleased one, a queued row leased 1 ms past the cutoff, and a ready row carrying the cutoff `wanted_at` the instance-track store left behind. `claim_translate_job(conn, "en", T, expired_at=cutoff)` deletes both expired queued rows, claims the unleased row as the oldest survivor (running, started_at T, attempts 1, lease still NULL), and leaves the running, fresh and ready rows byte-identical.

Abandon (`run_job` through the `Rig` of tests/active/test_translate_worker.py, `worker.now_ms` patched): v-1 is enqueued on the rig's connection as the Engine route queues it (`wanted_at=` given) or as the CLI does (no keyword), then claimed with the store's own claim, so the checkpoint does not lean on a `Rig.claim` signature. A running job leased at 1000 with the clock at 10**13 leaves no row, logs exactly one `abandoned, no viewer` record, has fetched the video JSON and opened the media (so the abandon came in the chunk loop, not before it), transcribes nothing and returns False. An unleased job, and a job leased at the patched now, each run to ready/whisper with the clip's four cues and log no abandoned line.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import HOST, INSTANCE_THEN_JSON, MEDIA_URL, QUEUED_AT, STARTED_AT, Rig, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job, open_subtitles_db, store_ready_subtitles  # noqa: E402

# Claim: the caller's clock and cutoff; a lease at or before the cutoff has expired (wanted_at <= expired_at), so the boundary row is expired and the row 1 ms later is fresh.
CLAIM_AT = 1_000_000
CUTOFF = 820_000
EXPIRED = CUTOFF
FRESH = CUTOFF + 1
# (video_id, queued_at, wanted_at); queued in this order, so a claim that did not drop first would take the expired row (probed: today's claim takes v-expired), and one that dropped only the head row it reached would leave v-expired-late queued.
QUEUED = [("v-expired", 1000, EXPIRED), ("v-unleased", 2000, None), ("v-expired-late", 2500, EXPIRED), ("v-fresh", 3000, FRESH)]
READY_ID = "v-ready"
READY_QUEUED_AT = 4000
# A worker's live job, its lease on the cutoff: queued and claimed (no expired_at, at 600, before any cutoff could reach 820_000) while it is the only row, so the later claim finds it running (probed: a later claim leaves such a row byte-identical today).
RUNNING_ID = "v-running"
RUNNING_QUEUED_AT = 500
RUNNING_AT = 600

# Abandon: a lease stamped at 1000 has lapsed under any lease length at a clock of 10**13; a lease stamped at the clock itself has not.
OLD_LEASE = 1000
FAR_NOW = 10 ** 13
ABANDONED = "abandoned, no viewer"
# The stub runner's segments for the clip's two speech seconds, sorted at absolute ms (probed: an unleased run on this rig with now_ms patched to 10**13 ended ready with these).
CLIP_CUES = [{"start": 0.123, "end": 0.568, "text": "call 1 a"}, {"start": 0.6, "end": 0.9, "text": "call 1 b"}, {"start": 2.123, "end": 2.568, "text": "call 2 a"}, {"start": 2.6, "end": 2.9, "text": "call 2 b"}]
# run_job's line for a job that reached ready (probed on the same run).
READY_LINE = "[translate-worker] job ready video_id=v-1 host=peer.example"


def _rows(path: Path) -> dict[str, dict]:
    """Every subtitles row, rowid included, keyed by video_id, through a fresh plain connection."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {row["video_id"]: dict(row) for row in conn.execute("SELECT rowid, * FROM subtitles")}
    finally:
        conn.close()


def _enqueue(conn: sqlite3.Connection, video_id: str, queued_at: int, wanted_at: int | None) -> tuple[str, str | None]:
    """Queue as the Engine route does (a lease given) or as the CLI does (no wanted_at keyword at all)."""
    if wanted_at is None:
        return enqueue_translate_job(conn, video_id, HOST, "en", 50, queued_at)
    return enqueue_translate_job(conn, video_id, HOST, "en", 50, queued_at, wanted_at=wanted_at)


def test_the_claim_drops_every_queued_row_whose_lease_expired_at_the_cutoff_and_claims_the_oldest_survivor_leaving_unleased_fresh_running_and_ready_rows(tmp_path):
    path = tmp_path / "subtitles.db"
    conn = open_subtitles_db(path)
    try:
        assert _enqueue(conn, RUNNING_ID, RUNNING_QUEUED_AT, EXPIRED) == ("queued", "queued")
        running = claim_translate_job(conn, "en", RUNNING_AT)
        assert (running.video_id, running.started_at, running.attempts) == (RUNNING_ID, RUNNING_AT, 1)  # control: the live job is claimed before the rest are queued
        for video_id, queued_at, wanted_at in QUEUED:
            assert _enqueue(conn, video_id, queued_at, wanted_at) == ("queued", "queued")
        assert _enqueue(conn, READY_ID, READY_QUEUED_AT, EXPIRED) == ("queued", "queued")
        store_ready_subtitles(conn, READY_ID, HOST, "en", "instance", "WEBVTT\n", [{"start": 1.0, "end": 2.0, "text": "Hello"}], 5000)
        before = _rows(path)
        assert {video_id: (row["state"], row["wanted_at"]) for video_id, row in before.items()} == {RUNNING_ID: ("running", EXPIRED), "v-expired": ("queued", EXPIRED), "v-unleased": ("queued", None), "v-expired-late": ("queued", EXPIRED), "v-fresh": ("queued", FRESH), READY_ID: ("ready", EXPIRED)}  # control: each lease stored as given, the running and ready rows keeping their expired ones

        job = claim_translate_job(conn, "en", CLAIM_AT, expired_at=CUTOFF)
    finally:
        conn.close()

    after = _rows(path)
    assert "v-expired" not in after, after.get("v-expired")  # C1: the queued row whose lease expired at the cutoff is deleted
    assert "v-expired-late" not in after, after.get("v-expired-late")  # C1: so is the expired row queued behind the claimed one, not only the head
    assert job is not None and (job.video_id, job.instance_domain, job.started_at, job.attempts) == ("v-unleased", HOST, CLAIM_AT, 1), job  # C1: the claim took the oldest surviving queued row, not the dropped one
    assert after["v-unleased"] == {**before["v-unleased"], "state": "running", "started_at": CLAIM_AT, "attempts": 1}  # C1: the unleased row survived, claimed with its NULL lease and every other column kept
    assert after["v-fresh"] == before["v-fresh"]  # C1: a lease 1 ms past the cutoff is not expired, so the row is untouched
    assert after[READY_ID] == before[READY_ID]  # C1: a ready row is untouched whatever its stale lease
    assert after[RUNNING_ID] == before[RUNNING_ID]  # C1: a running row whose lease expired is left to its worker's chunk loop, not swept at claim
    assert set(after) == {RUNNING_ID, "v-unleased", "v-fresh", READY_ID}, sorted(after)  # C1: nothing else dropped or added


def _claim(rig: Rig, lease: int | None) -> None:
    """v-1 queued with lease at the rig's QUEUED_AT and claimed at its STARTED_AT on the rig's connection, as Rig.claim does; rig.key is already v-1's."""
    assert _enqueue(rig.conn, "v-1", QUEUED_AT, lease) == ("queued", "queued")
    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT)
    assert (rig.job.video_id, rig.job.instance_domain, rig.job.started_at, rig.job.attempts) == ("v-1", HOST, STARTED_AT, 1)  # control: a running job, claimed once
    assert (rig.row()["state"], rig.row()["wanted_at"]) == ("running", lease)  # control: the lease as queued


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_a_running_job_whose_lease_has_lapsed_is_deleted_at_its_first_wake_with_one_abandoned_line(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rig.worker, "now_ms", lambda: FAR_NOW)
    _claim(rig, OLD_LEASE)
    runner = StubRunner(rig)

    result = rig.run(runner)

    assert rig.row() == {}  # C2: the row is deleted, partial cues with it
    assert len([message for message in _messages(caplog) if ABANDONED in message]) == 1, _messages(caplog)  # C2: exactly one abandoned line
    assert rig.instance.opened == INSTANCE_THEN_JSON and rig.media.opened == [MEDIA_URL]  # C2: the job reached the chunk loop (video JSON read, media opened), so the abandon is not at the start of run_job or before the fetches
    assert runner.transcribes == 0  # C2: abandoned at the first chunk-loop wake, before any chunk is transcribed
    assert result is False  # C2: not the whitelist requeue, so serve does not back off


@pytest.mark.parametrize("lease", [None, FAR_NOW], ids=["unleased", "lease stamped now"])
def test_an_unleased_job_or_one_whose_lease_is_current_runs_to_ready_however_late_the_clock(rig, monkeypatch, caplog, lease):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rig.worker, "now_ms", lambda: FAR_NOW)
    _claim(rig, lease)

    result = rig.run(StubRunner(rig))

    row = rig.row()
    assert (row["state"], row["source"]) == ("ready", "whisper"), row  # C2: a NULL lease is never abandoned, and a current one is not lapsed
    assert json.loads(row["cues_json"]) == CLIP_CUES  # C2: it ran through every chunk
    assert READY_LINE in _messages(caplog), _messages(caplog)  # control: the worker's info lines reach caplog, so the empty list below is not blindness
    assert [message for message in _messages(caplog) if ABANDONED in message] == []  # C2: no abandoned line
    assert result is False  # control: an ordinary end, not the whitelist requeue
