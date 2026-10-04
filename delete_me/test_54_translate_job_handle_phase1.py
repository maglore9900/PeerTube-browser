"""Phase 1 checkpoint of plan 54: once the Engine's instance-track store has replaced a running row, no write through the claim's `TranslateJob` handle changes it.

Store (C1), `engine/server/data/subtitles.py` called directly on tmp subtitles.db files opened as test_subtitles.py's `_subtitles` opens them, v-1 on peer.example queued at 1000 and claimed at 2000:

- Each of the six handle methods (running cues, ready, already_english, failed, requeue, ready from the instance track), run after `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the running row, returns False, and every column of every row, rowid included, reads the same afterwards. The same method on a fresh claim with no takeover returns True and changes the row, so the unchanged row is the takeover's doing.
- With the claim held, ending ready from the instance track returns True and leaves exactly: ready, instance, the track text, the cues as compact JSON, fetched_at and finished_at both the one given time, and detected_language, error, attempts, queued_at and started_at as the running job had them; the ready reader then returns those cues.

Worker (C2), `run_job` through test_translate_worker.py's `Rig` with the English caption listing and track served: `fetch_instance_track` is wrapped so that, after the real fetch has found the track, the Engine stores its own different track ready/instance over the running row. Afterwards every column of every row reads as the Engine left it and no further cues_json write was made; the only worker log line is `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`; nothing was transcribed and nothing past the caption list and the track was fetched.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import HOST, _snapshot, _subtitles  # noqa: E402
from test_translate_worker import CAPTIONS_URL, EN_LISTING, TRACK, TRACK_URL, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, fetch_ready_subtitles, store_ready_subtitles  # noqa: E402

QUEUED_AT = 1000
STARTED_AT = 2000
TAKEOVER_AT = 8000
FINISHED_AT = 9000
# The Engine's track differs from the one the worker fetches, so a worker write over the Engine's row shows in track_text and cues_json.
ENGINE_TRACK = "WEBVTT\n\n00:05.000 --> 00:06.000\nEngine\n"
ENGINE_CUES = [{"start": 5.0, "end": 6.0, "text": "Engine"}]
# ENGINE_CUES as store_ready_subtitles encodes them, probed.
ENGINE_CUES_JSON = '[{"start":5.0,"end":6.0,"text":"Engine"}]'
WORKER_CUES = [{"start": 1.0, "end": 2.0, "text": "Hello"}]
TAKEN_OVER = f"[translate-worker] taken over by the instance track video_id=v-1 host={HOST}"

# Every claim-conditional write the handle offers, each with values that change the row when the claim holds.
CLAIM_WRITES = {
    "running cues": lambda job: job.write_running_cues(WORKER_CUES, "fr"),
    "ready": lambda job: job.end_ready(WORKER_CUES, FINISHED_AT),
    "already_english": lambda job: job.end_already_english("en", FINISHED_AT),
    "failed": lambda job: job.end_failed("boom", FINISHED_AT),
    "requeue": lambda job: job.requeue(),
    "ready from instance": lambda job: job.end_ready_from_instance("WEBVTT x", WORKER_CUES, FINISHED_AT),
}


def _claimed(path: Path):  # noqa: ANN202
    """A store at `path` with v-1 queued at QUEUED_AT and claimed at STARTED_AT; the worker's connection and its handle."""
    conn = _subtitles(path)
    assert tuple(enqueue_translate_job(conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    return conn, claim_translate_job(conn, "en", STARTED_AT)


def _engine_stores(path: Path, track: str, cues: list[dict], fetched_at: int) -> None:
    """The Engine state route's instance-track store, on a connection of its own as the Engine holds one."""
    engine = connect_subtitles_db(path)
    try:
        store_ready_subtitles(engine, "v-1", HOST, "en", "instance", track, cues, fetched_at)
    finally:
        engine.close()


@pytest.mark.parametrize("write", CLAIM_WRITES.values(), ids=CLAIM_WRITES.keys())
def test_every_claim_write_after_an_instance_track_takeover_reports_the_claim_lost_and_leaves_the_row_byte_identical(tmp_path, write):
    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        _engine_stores(path, ENGINE_TRACK, ENGINE_CUES, TAKEOVER_AT)
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == ENGINE_CUES  # control: the Engine's ready/instance row replaced the running one
        taken = _snapshot(path)
        assert write(job) is False  # C1
    finally:
        conn.close()
    assert _snapshot(path) == taken  # C1

    held_path = tmp_path / "held.db"
    conn, job = _claimed(held_path)
    held_before = _snapshot(held_path)
    try:
        assert write(job) is True  # control: the claim held, so the write matched
    finally:
        conn.close()
    assert _snapshot(held_path) != held_before  # control: with the claim held this write changes the row, so the unchanged row above is the takeover's doing


def test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp_and_the_job_columns_kept(tmp_path):
    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        # A running job with partial cues and a detected language, set directly so the only handle call is the one under test.
        with conn:
            conn.execute("UPDATE subtitles SET cues_json = ?, detected_language = ? WHERE video_id = 'v-1' AND state = 'running'", ('[{"start":0.5,"end":0.9,"text":"partial"}]', "fr"))
        assert job.end_ready_from_instance("WEBVTT t", WORKER_CUES, FINISHED_AT) is True  # held claim: the end matched
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == WORKER_CUES  # held claim: the ready reader returns the instance cues
    finally:
        conn.close()
    reader = sqlite3.connect(path)
    reader.row_factory = sqlite3.Row
    try:
        row = dict(reader.execute("SELECT * FROM subtitles").fetchone())
    finally:
        reader.close()
    assert row == {
        "video_id": "v-1",
        "instance_domain": HOST,
        "target_language": "en",
        "state": "ready",
        "source": "instance",
        "fetched_at": FINISHED_AT,
        "track_text": "WEBVTT t",
        "cues_json": '[{"start":1.0,"end":2.0,"text":"Hello"}]',
        "queued_at": QUEUED_AT,
        "started_at": STARTED_AT,
        "finished_at": FINISHED_AT,
        "error": None,
        "detected_language": "fr",
        "attempts": 1,
    }  # held claim: one timestamp for fetched_at and finished_at, compact cues, every other job column as the running job had it


def test_an_instance_track_found_after_the_engine_took_the_row_over_writes_nothing_and_logs_the_takeover(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    rig.instance.serve(CAPTIONS_URL, body=EN_LISTING)
    rig.instance.serve(TRACK_URL, body=TRACK.encode("utf-8"))
    real_fetch = rig.worker.fetch_instance_track
    seen: dict = {}

    def engine_takes_over_after_the_fetch(instance: str, video_key: str):  # noqa: ANN202
        fetched = real_fetch(instance, video_key)
        _engine_stores(rig.subtitles, ENGINE_TRACK, ENGINE_CUES, 1_700_000_000_000)
        seen.update(fetched=fetched, row=rig.row(), taken=_snapshot(rig.subtitles), writes=rig.cues_writes())
        return fetched

    monkeypatch.setattr(rig.worker, "fetch_instance_track", engine_takes_over_after_the_fetch)
    runner = StubRunner(rig)
    rig.run(runner)

    assert seen["fetched"] is not None and seen["fetched"][0] == TRACK  # control: the worker found the instance's English track
    assert (seen["row"]["state"], seen["row"]["source"], seen["row"]["track_text"]) == ("ready", "instance", ENGINE_TRACK)  # control: the Engine's store landed on the running row
    assert seen["writes"] == [ENGINE_CUES_JSON]  # control: the trigger records the Engine's upsert, so it would record a worker write too
    assert _snapshot(rig.subtitles) == seen["taken"]  # C2: every column of every row as the Engine left it
    assert rig.cues_writes() == seen["writes"]  # C2: no cues_json write after the takeover
    assert [record.getMessage() for record in caplog.records if record.getMessage().startswith("[translate-worker]")] == [TAKEN_OVER]  # C2: the takeover logged, and no ready, failed or error line
    assert runner.transcribes == 0  # C2
    assert rig.instance.opened == [CAPTIONS_URL, TRACK_URL] and rig.media.opened == []  # C2: nothing fetched past the track
