"""Probe for plan 50 phase 1: whether finish_translate_failed ends a claimed job whose cues_json was left unset or overwritten by hand, and what today's handler then fetches."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import EN_LISTING, PEER_VIDEO, TRACK, RecordingInstance, _handle, _handler_module, _server, _subtitles_db, whitelist  # noqa: E402,F401


@pytest.mark.parametrize("cues_json", [None, "[]", "{not json", '{"start": 1.0}'])
def test_probe(tmp_path, whitelist, monkeypatch, cues_json):
    from data.subtitles import claim_translate_job, enqueue_translate_job, finish_translate_failed

    path = tmp_path / "subtitles.db"
    store = _subtitles_db(path)
    enqueue_translate_job(store, "v-1", "peer.example", "en", 50, 10)
    started_at = claim_translate_job(store, "en", 20)["started_at"]
    if cues_json is not None:
        with store:
            store.execute("UPDATE subtitles SET cues_json = ? WHERE video_id = ?", (cues_json, "v-1"))
    print("raw:", tuple(store.execute("SELECT state, cues_json FROM subtitles").fetchone()))
    print("finish failed:", finish_translate_failed(store, "v-1", "peer.example", "en", started_at, "boom", 30))
    print("raw after:", tuple(store.execute("SELECT state, cues_json FROM subtitles").fetchone()))
    instance = RecordingInstance()
    instance.serve(PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    module = _handler_module(instance, monkeypatch)
    server = _server(whitelist, path)
    print("answer:", _handle(module, server, {"id": "u-1", "host": "peer.example"}), instance.fetched)
    open_store = server.subtitles_db
    server.subtitles_db = None
    print("closed:", _handle(module, server, {"id": "u-1", "host": "peer.example"}))
    server.subtitles_db = open_store
    print("reopened:", _handle(module, server, {"id": "u-1", "host": "peer.example"}))
    assert False, "probe"
