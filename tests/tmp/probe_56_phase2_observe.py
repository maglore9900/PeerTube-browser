"""Throwaway probe for the plan 56 phase 2 checkpoint: what the current store and worker actually do on the setups the checkpoint uses."""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import HOST, QUEUED_AT, STARTED_AT, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job, open_subtitles_db, store_ready_subtitles  # noqa: E402


def _rows(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {row["video_id"]: dict(row) for row in conn.execute("SELECT rowid, * FROM subtitles")}
    finally:
        conn.close()


def test_probe_store(tmp_path):
    path = tmp_path / "subtitles.db"
    conn = open_subtitles_db(path)
    for video_id, queued_at in [("v-expired", 1000), ("v-unleased", 2000), ("v-fresh", 3000), ("v-ready", 4000)]:
        print("enqueue", video_id, enqueue_translate_job(conn, video_id, HOST, "en", 50, queued_at))
    store_ready_subtitles(conn, "v-ready", HOST, "en", "instance", "WEBVTT\n", [{"start": 1.0, "end": 2.0, "text": "Hello"}], 5000)
    before = _rows(path)
    print("BEFORE", before)
    job = claim_translate_job(conn, "en", 1_000_000)
    print("JOB", job)
    conn.close()
    after = _rows(path)
    print("AFTER", after)
    print("DIFF", {k: {c: (before[k][c], after[k][c]) for c in before[k] if before[k][c] != after[k][c]} for k in before})
    assert False


def test_probe_run(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rig.worker, "now_ms", lambda: 10 ** 13)
    print("ENQ", enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT))
    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT)
    print("JOB", rig.job, rig.key)
    runner = StubRunner(rig)
    result = rig.run(runner)
    row = rig.row()
    print("RESULT", result, "TRANSCRIBES", runner.transcribes)
    print("ROW", {k: v for k, v in row.items() if k != "cues_json"})
    print("CUES", json.loads(row["cues_json"]))
    print("LOGS", [r.getMessage() for r in caplog.records])
    assert False
