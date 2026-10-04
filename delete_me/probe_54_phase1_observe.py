"""Probe for plan 54 phase 1: today's per-claim writes after a store_ready_subtitles takeover, the instance encoding, and today's worker path when the Engine takes the row over before the instance-track store."""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import HOST, _snapshot, _subtitles  # noqa: E402
from test_translate_worker import CAPTIONS_URL, EN_LISTING, TRACK, TRACK_URL, Rig, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, finish_translate_already_english, finish_translate_failed, finish_translate_ready, mark_translate_finished, requeue_translate_job, store_ready_subtitles, store_running_cues  # noqa: E402

CUES = [{"start": 1.0, "end": 2.0, "text": "Hello"}]


def test_probe_old_writes_after_takeover(tmp_path):
    path = tmp_path / "s.db"
    conn = _subtitles(path)
    print("enqueue", tuple(enqueue_translate_job(conn, "v-1", HOST, "en", 50, 1000)))
    job = claim_translate_job(conn, "en", 2000)
    print("claim", tuple(job))
    engine = connect_subtitles_db(path)
    store_ready_subtitles(engine, "v-1", HOST, "en", "instance", "WEBVTT e", [{"start": 5.0, "end": 6.0, "text": "Engine"}], 8000)
    engine.close()
    before = _snapshot(path)
    print("snapshot after takeover", before)
    key = ("v-1", HOST, "en", 2000)
    print("running cues", store_running_cues(conn, *key, CUES, "fr"), _snapshot(path) == before)
    print("ready", finish_translate_ready(conn, *key, CUES, 9000), _snapshot(path) == before)
    print("already_english", finish_translate_already_english(conn, *key, "en", 9000), _snapshot(path) == before)
    print("failed", finish_translate_failed(conn, *key, "boom", 9000), _snapshot(path) == before)
    print("requeue", requeue_translate_job(conn, *key), _snapshot(path) == before)
    mark_translate_finished(conn, *key, 9000)
    print("mark_translate_finished changes it", _snapshot(path) != before, _snapshot(path))
    conn.close()


def test_probe_encoding_and_held_claim(tmp_path):
    path = tmp_path / "s.db"
    conn = _subtitles(path)
    enqueue_translate_job(conn, "v-1", HOST, "en", 50, 1000)
    claim_translate_job(conn, "en", 2000)
    print("running cues held", store_running_cues(conn, "v-1", HOST, "en", 2000, CUES, "fr"))
    store_ready_subtitles(conn, "v-1", HOST, "en", "instance", "WEBVTT t", CUES, 9000)
    conn.row_factory = sqlite3.Row
    print("row", dict(conn.execute("SELECT * FROM subtitles").fetchone()))
    conn.close()


def test_probe_worker_takeover_today(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    rig.instance.serve(CAPTIONS_URL, body=EN_LISTING)
    rig.instance.serve(TRACK_URL, body=TRACK.encode("utf-8"))
    real = rig.worker.fetch_instance_track
    seen = {}

    def engine_first(instance, video_key):
        fetched = real(instance, video_key)
        engine = connect_subtitles_db(rig.subtitles)
        store_ready_subtitles(engine, "v-1", HOST, "en", "instance", "WEBVTT engine", [{"start": 5.0, "end": 6.0, "text": "Engine"}], 1_700_000_000_000)
        engine.close()
        seen["fetched"] = fetched
        seen["taken"] = _snapshot(rig.subtitles)
        seen["writes"] = rig.cues_writes()
        return fetched

    monkeypatch.setattr(rig.worker, "fetch_instance_track", engine_first)
    runner = StubRunner(rig)
    print("run_job returned", rig.run(runner))
    print("fetched", seen["fetched"])
    print("taken", seen["taken"])
    print("after", _snapshot(rig.subtitles))
    print("equal", _snapshot(rig.subtitles) == seen["taken"])
    print("writes at takeover", seen["writes"], "after", rig.cues_writes())
    print("records", [(r.levelname, r.getMessage()) for r in caplog.records])
    print("transcribes", runner.transcribes, "instance opened", rig.instance.opened, "media opened", rig.media.opened)
