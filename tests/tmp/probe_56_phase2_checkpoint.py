"""Probe for the plan 56 phase 2 checkpoint: what the current store and the Rig do on the premises the checkpoint rests on."""
import inspect
import json
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import HOST, Rig, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, store_ready_subtitles  # noqa: E402


def test_probe_store(tmp_path):
    conn = connect_subtitles_db(tmp_path / "s.db")
    ensure_subtitles_schema(conn)
    print("enqueue sig", inspect.signature(enqueue_translate_job))
    print("claim sig", inspect.signature(claim_translate_job))
    print("Rig.claim sig", inspect.signature(Rig.claim))
    for vid, qa in (("a", 1000), ("b", 2000), ("c", 3000), ("d", 4000)):
        print(vid, enqueue_translate_job(conn, vid, HOST, "en", 50, qa))
    store_ready_subtitles(conn, "d", HOST, "en", "instance", "WEBVTT\n", [{"start": 1.0, "end": 2.0, "text": "x"}], 5000)
    plain = sqlite3.connect(tmp_path / "s.db")
    plain.row_factory = sqlite3.Row
    print("d after store_ready", dict(plain.execute("SELECT * FROM subtitles WHERE video_id = 'd'").fetchone()))
    job = claim_translate_job(conn, "en", 9000)
    print("claimed", job)
    print("rows", [dict(r) for r in plain.execute("SELECT rowid, * FROM subtitles ORDER BY rowid")])
    print("null cmp", plain.execute("SELECT NULL <= 5, (NULL IS NOT NULL AND NULL <= 5)").fetchone()[:])
    plain.close()
    conn.close()


def test_probe_rig_far_now(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(rig.worker, "now_ms", lambda: 10 ** 13)
    rig.claim()
    print("before", rig.row())
    runner = StubRunner(rig)
    result = rig.run(runner)
    row = rig.row()
    print("result", result, "state", row["state"], row["source"], row["finished_at"], "transcribes", runner.transcribes)
    print("cues", json.loads(row["cues_json"]))
    print("records", [(r.levelname, r.getMessage()) for r in caplog.records])
