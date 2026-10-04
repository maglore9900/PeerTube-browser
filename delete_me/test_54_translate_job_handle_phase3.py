"""Phase 3 checkpoint of plan 54: with subtitles.db closed, `/internal/translate` still answers an instance track ready and logs that the track was not stored.

The state route, `handle_internal_translate`, over test_internal_translate.py's harness: a temporary whitelist.db holding v-1/u-1 on peer.example, the adapter's patch point serving the instance (a caption list and an English track that parses to two cues), and the wall clock pinned at the module's `now_ms`.

- C1: with `subtitles_db` None, as server.py leaves it at shutdown, the answer is exactly `ready` with the instance's two cues and `available` false, after fetching the caption list and the track. Exactly one log record starts `[translate] cache closed, track not stored`, at INFO, naming `video_id=v-1 host=peer.example`.
- Control: the same request against an open store answers the same, stores one ready row, and logs no such line, so the line is the closed store's doing.
- With the store closed and no English track on the instance, the answer is `none` and no such line is logged: the line marks a found track that was not stored, not every closed-store request.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import BODY, CUES, HOST, NONE, TRACK_FETCHES, VIDEO_ID, _handle, _instance, _route, _server, _stored, _whitelist  # noqa: E402

CLOSED = "[translate] cache closed, track not stored"


@pytest.fixture
def whitelist(tmp_path):
    conn = _whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


def _closed_lines(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(record.levelno, record.getMessage()) for record in caplog.records if record.getMessage().startswith(CLOSED)]


def test_a_closed_store_still_answers_an_instance_track_ready_and_logs_once_that_it_was_not_stored(tmp_path, whitelist, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    open_store = server.subtitles_db
    server.subtitles_db = None  # as server.py leaves it at shutdown
    # The request's host differs from the row's `peer.example` in case and a trailing dot, so a line naming the request's host shows.
    body = {**BODY, "host": "PEER.Example."}

    assert _handle(internal_translate, server, body) == [[200, {"state": "ready", "cues": CUES, "available": False}]]  # C1
    assert instance.fetched == TRACK_FETCHES  # control: the answer came from the instance
    assert _closed_lines(caplog) == [(logging.INFO, f"{CLOSED} video_id={VIDEO_ID} host={HOST}")]  # C1
    assert _stored(tmp_path / "subtitles.db") == []  # control: nothing reached the file

    # Control: the same request against the open store answers the same, stores the row and logs no such line.
    caplog.clear()
    server.subtitles_db = open_store
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": False}]]
    assert [row[:4] for row in _stored(tmp_path / "subtitles.db")] == [(VIDEO_ID, HOST, "en", "ready")]
    assert _closed_lines(caplog) == []


def test_a_closed_store_with_no_instance_track_answers_none_and_logs_no_closed_line(tmp_path, whitelist, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    instance = _instance(False)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    server.subtitles_db = None

    assert _handle(internal_translate, server, BODY) == NONE
    assert instance.fetched == TRACK_FETCHES[:1]  # control: the caption list was read and held no English track
    assert _closed_lines(caplog) == []  # C1: the line marks a found track, not every closed-store request
