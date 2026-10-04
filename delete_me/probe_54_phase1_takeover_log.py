"""Probe for plan 54 phase 1: the exact worker log lines today's JobTakenOver path renders, reached through a mid-job takeover."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import HOST, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import connect_subtitles_db, store_ready_subtitles  # noqa: E402


def test_probe_takeover_log_text(rig, caplog):
    caplog.set_level(logging.INFO)
    taken: dict = {}

    def engine_stores(runner: StubRunner) -> None:
        if taken:
            return
        engine = connect_subtitles_db(rig.subtitles)
        store_ready_subtitles(engine, "v-1", HOST, "en", "instance", "WEBVTT e", [{"start": 5.0, "end": 6.0, "text": "Engine"}], 1_700_000_000_000)
        engine.close()
        taken.update(rig.row())

    rig.run(StubRunner(rig, on_transcribe=engine_stores))
    print("records", [(record.levelname, record.getMessage()) for record in caplog.records])
