"""Plan 50 phase 2 checkpoint: `/internal/translate/enqueue` queues a whisper job for a resolved video only while a translate worker is serving, and sits behind the bridge gate.

Enqueue route (`handle_internal_translate_enqueue` through the `test_internal_translate.py` harness: real whitelist.db and subtitles.db, the wall clock pinned at the module's `now_ms`; stored rows read back through a separate read-only connection):

- C1: with no beat, a beat 15 001 ms old, a beat 1 ms ahead, and a closed store under a fresh beat, the answer is exactly `{"state": "none", "available": false}` and subtitles.db holds no row; the same server then queues once a fresh beat is written or the store is back.
- C2: with a beat 0 ms or 15 000 ms old, uuid `u-1` requested as `PEER.Example.` answers exactly `{"state": "queued", "available": true}` and stores one row, under canonical `v-1` and `peer.example`: `en`, `queued`, source `whisper`, fetched_at and queued_at now, attempts 0, every other column unset. A key already `queued`, `running`, `ready`, `failed` or `already_english` answers exactly that state with `available` true and leaves its row byte for byte as it was, with no second row. With `SUBTITLE_QUEUE_CAP` other keys queued it answers exactly `{"state": "busy", "available": true}` and stores nothing; with one fewer the same server queues it.
- A store error from the enqueue itself (the subtitles table moved away under a fresh beat) answers 503 with an `error` and stores nothing; with the table back the same request queues.
- Invalid JSON, a JSON array, a missing id, a blank host, a numeric id, an invalid host, an unknown video and a known uuid on another host each answer the literal 400 or 404 the state route gives for the same body, with a fresh beat and no row stored; an actively denylisted host answers 404 `Video not found` from both routes and stores nothing, and queues once its denylist row is inactive.

Bridge gate: server.py run as the startup test there runs it answers `/internal/translate/enqueue` for an unknown video `404 Video not found` with the bridge token (an Engine without the route answers `404 Not found`), and `401 Unauthorized` without it.
"""
from __future__ import annotations

import fcntl
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from conftest import ENGINE_PY, ENGINE_START_LOCK  # noqa: E402
from test_internal_translate import BRIDGE_TOKEN, CUES, DENIED_HOST, DENIED_VIDEO, ENGINE_SERVER, HEALTHY_WITHIN_SECONDS, HOST, PEER_VIDEO, STOP_WITHIN_SECONDS, TRACK, VARIANT_RUNNER, VIDEO_NOT_FOUND, HandlerRequest, RecordingInstance, _free_port, _handler_module, _post, _server, _set_denied, _subtitles_db, whitelist  # noqa: E402,F401

from server_config import SUBTITLE_QUEUE_CAP  # noqa: E402

VIDEO_ID, VIDEO_UUID, _ = PEER_VIDEO
BODY = {"id": VIDEO_UUID, "host": HOST}
# The wall clock is a system boundary: pinned, a beat's age is exact, and so is the queued_at the route writes.
NOW = 1_760_000_000_000
NONE_UNAVAILABLE = [[200, {"state": "none", "available": False}]]
QUEUED = [[200, {"state": "queued", "available": True}]]
# Every subtitles column, in table order, of the row a new key leaves.
QUEUED_ROW = (VIDEO_ID, HOST, "en", "queued", "whisper", NOW, None, None, NOW, None, None, None, None, 0)


def _route(monkeypatch: pytest.MonkeyPatch):
    """The handler module with its clock pinned at NOW; its instance fetch reaches a stand-in that serves nothing."""
    module = _handler_module(RecordingInstance(), monkeypatch)
    monkeypatch.setattr(module, "now_ms", lambda: NOW)
    return module


def _request(body: dict | bytes) -> HandlerRequest:
    """A request carrying body as JSON, or as these raw bytes."""
    request = HandlerRequest(body if isinstance(body, dict) else {})
    if isinstance(body, bytes):
        request.rfile = io.BytesIO(body)
        request.headers = {"content-length": str(len(body))}
    return request


def _enqueue(module, server, body: dict | bytes) -> list[list]:
    request = _request(body)
    module.handle_internal_translate_enqueue(request, server)
    return request.responses


def _state(module, server, body: dict | bytes) -> list[list]:
    request = _request(body)
    module.handle_internal_translate(request, server)
    return request.responses


def _rows(subtitles_path: Path) -> list[tuple]:
    """Every subtitles row, every column, read through a separate read-only connection."""
    conn = sqlite3.connect(f"file:{subtitles_path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT * FROM subtitles ORDER BY video_id, instance_domain").fetchall()
    finally:
        conn.close()


def _write(subtitles_path: Path, sql: str) -> None:
    """One statement through a plain connection of its own, as another process would run it."""
    conn = sqlite3.connect(subtitles_path)
    try:
        with conn:
            conn.execute(sql)
    finally:
        conn.close()


def _beat(subtitles_path: Path, age: int | None) -> None:
    """Write the worker's heartbeat age ms before NOW (negative is ahead of it); None writes none."""
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(subtitles_path)
    if age is not None:
        write_translate_heartbeat(store, NOW - age, 1)
    store.close()


def _seed(subtitles_path: Path, state: str) -> None:
    """Leave the key in one stored state, written by the store's own writers."""
    from data.subtitles import claim_translate_job, enqueue_translate_job, finish_translate_already_english, finish_translate_failed, store_ready_subtitles, store_running_cues

    store = _subtitles_db(subtitles_path)
    if state == "ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", TRACK, CUES, NOW - 1000)
    else:
        assert enqueue_translate_job(store, VIDEO_ID, HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 2000) == ("queued", "queued")
        if state != "queued":
            started_at = claim_translate_job(store, "en", NOW - 1000)["started_at"]
            if state == "running":
                assert store_running_cues(store, VIDEO_ID, HOST, "en", started_at, CUES, "fr")
            elif state == "failed":
                assert finish_translate_failed(store, VIDEO_ID, HOST, "en", started_at, "boom", NOW - 500)
            else:
                assert state == "already_english", state
                assert finish_translate_already_english(store, VIDEO_ID, HOST, "en", started_at, "en", NOW - 500)
    store.close()


# Age in ms of the beat at request time; None is no beat, negative a beat dated ahead of now.
UNAVAILABLE_BEATS = {"no beat": None, "15 001 ms old": 15_001, "1 ms ahead": -1}


@pytest.mark.parametrize("age", UNAVAILABLE_BEATS.values(), ids=UNAVAILABLE_BEATS.keys())
def test_without_a_serving_worker_enqueue_answers_none_not_available_and_writes_no_row(tmp_path, whitelist, monkeypatch, age):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, age)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == NONE_UNAVAILABLE  # C1
    assert _rows(subtitles_path) == []  # C1
    # Control: the same server queues once a fresh beat is written, so the answer and the empty table above are the gate's doing.
    _beat(subtitles_path, 0)
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


def test_a_closed_store_enqueue_answers_none_not_available_and_writes_no_row(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    open_store = server.subtitles_db
    server.subtitles_db = None  # as server.py leaves it at shutdown
    assert _enqueue(internal_translate, server, BODY) == NONE_UNAVAILABLE  # C1
    assert _rows(subtitles_path) == []  # C1
    # Control: the same server, its store back, reads the fresh beat and queues.
    server.subtitles_db = open_store
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


FRESH_BEATS = {"0 ms old": 0, "15 000 ms old": 15_000}


@pytest.mark.parametrize("age", FRESH_BEATS.values(), ids=FRESH_BEATS.keys())
def test_with_a_serving_worker_a_new_key_is_queued_under_its_canonical_key(tmp_path, whitelist, monkeypatch, age):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, age)
    internal_translate = _route(monkeypatch)
    # The request host differs from the row's `peer.example` in case and a trailing dot, and the id is the uuid, so a row keyed on the request shows.
    assert _enqueue(internal_translate, _server(whitelist, subtitles_path), {"id": VIDEO_UUID, "host": "PEER.Example."}) == QUEUED  # C2
    assert _rows(subtitles_path) == [QUEUED_ROW]  # C2


@pytest.mark.parametrize("state", ["queued", "running", "ready", "failed", "already_english"])
def test_with_a_serving_worker_a_stored_key_answers_its_state_and_its_row_is_unchanged(tmp_path, whitelist, monkeypatch, state):
    subtitles_path = tmp_path / "subtitles.db"
    _seed(subtitles_path, state)
    _beat(subtitles_path, 0)
    before = _rows(subtitles_path)
    assert [row[:4] for row in before] == [(VIDEO_ID, HOST, "en", state)]  # control: the seeded row is the key in that state
    internal_translate = _route(monkeypatch)
    assert _enqueue(internal_translate, _server(whitelist, subtitles_path), BODY) == [[200, {"state": state, "available": True}]]  # C2
    assert _rows(subtitles_path) == before  # C2: never overwritten, no second row


def test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues(tmp_path, whitelist, monkeypatch):
    from data.subtitles import enqueue_translate_job

    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    # Other videos' jobs fill the queue; the store counts every queued row against the cap.
    for index in range(SUBTITLE_QUEUE_CAP):
        assert enqueue_translate_job(store, f"q-{index:03d}", HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 5000) == ("queued", "queued")
    store.close()
    _beat(subtitles_path, 0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == [[200, {"state": "busy", "available": True}]]  # C2
    rows = _rows(subtitles_path)
    assert [row for row in rows if row[0] == VIDEO_ID] == []  # C2: busy stores nothing
    assert len(rows) == SUBTITLE_QUEUE_CAP
    # One fewer queued job: the same server queues the key, so busy above came at exactly the cap.
    _write(subtitles_path, "DELETE FROM subtitles WHERE video_id = 'q-000'")
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert [row for row in _rows(subtitles_path) if row[0] == VIDEO_ID] == [QUEUED_ROW]


def test_a_store_error_from_the_enqueue_answers_503_and_writes_no_row(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    # The heartbeat table stays, so the gate reads a fresh beat and the enqueue itself raises `no such table: subtitles`.
    _write(subtitles_path, "ALTER TABLE subtitles RENAME TO subtitles_away")
    (response,) = _enqueue(internal_translate, server, BODY)
    assert response[0] == 503, response
    assert set(response[1]) == {"error"}, response
    _write(subtitles_path, "ALTER TABLE subtitles_away RENAME TO subtitles")
    assert _rows(subtitles_path) == []
    # Control: with the table back the same request queues.
    assert _enqueue(internal_translate, server, BODY) == QUEUED
    assert _rows(subtitles_path) == [QUEUED_ROW]


MISSING = [[400, {"error": "Missing id or host"}]]
INVALID_JSON = [[400, {"error": "Invalid JSON body"}]]
# Each body both routes refuse, and the literal answer.
REFUSED = {
    "invalid JSON": (b"{not json", INVALID_JSON),
    "a JSON array": (b"[1, 2]", INVALID_JSON),
    "no id": ({"host": HOST}, MISSING),
    "blank host": ({"id": VIDEO_UUID, "host": "  "}, MISSING),
    "numeric id": ({"id": 1, "host": HOST}, MISSING),
    "invalid host": ({"id": VIDEO_UUID, "host": "not a host!"}, [[400, {"error": "Invalid host"}]]),
    "unknown video": ({"id": "no-such-video", "host": HOST}, VIDEO_NOT_FOUND),
    "known uuid on another host": ({"id": VIDEO_UUID, "host": "other.example"}, VIDEO_NOT_FOUND),
}


@pytest.mark.parametrize("body, answer", REFUSED.values(), ids=REFUSED.keys())
def test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does(tmp_path, whitelist, monkeypatch, body, answer):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, body) == answer
    assert _state(internal_translate, server, body) == answer  # the same answer the state route gives
    assert _rows(subtitles_path) == []
    # Control: the gate is open, so the same server queues a body that resolves.
    assert _enqueue(internal_translate, server, BODY) == QUEUED


def test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does(tmp_path, whitelist, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    body = {"id": DENIED_VIDEO[1], "host": DENIED_HOST}
    _set_denied(whitelist, True)  # stored as DENIED.EXAMPLE
    assert _enqueue(internal_translate, server, body) == VIDEO_NOT_FOUND
    assert _state(internal_translate, server, body) == VIDEO_NOT_FOUND
    assert _rows(subtitles_path) == []
    # Control: with the denylist row inactive the same request queues the video under its own key.
    _set_denied(whitelist, False)
    assert _enqueue(internal_translate, server, body) == QUEUED
    assert [row[:4] for row in _rows(subtitles_path)] == [(DENIED_VIDEO[0], DENIED_HOST, "en", "queued")]


def test_an_engine_routes_internal_translate_enqueue_behind_the_bridge_gate(tmp_path):
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    env = {**os.environ, "ENGINE_INGEST_MODE": "bridge", "ENGINE_BRIDGE_TOKEN": BRIDGE_TOKEN}
    log_path = tmp_path / "engine.log"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with open(log_path, "w") as log:
        with open(ENGINE_START_LOCK, "w") as start_lock:
            fcntl.flock(start_lock, fcntl.LOCK_EX)
            proc = subprocess.Popen([str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps({"DEFAULT_SUBTITLES_DB_PATH": str(tmp_path / "subtitles.db")}), "--host", "127.0.0.1", "--port", str(port), "--no-random-cache-refresh"], env=env, stdout=log, stderr=log)
            healthy = False
            deadline = time.time() + HEALTHY_WITHIN_SECONDS
            while proc.poll() is None and time.time() < deadline and not healthy:
                try:
                    with urllib.request.urlopen(base + "/api/health", timeout=5) as resp:
                        healthy = resp.status == 200
                except OSError:
                    time.sleep(0.1)
    try:
        assert healthy, f"the variant Engine did not answer /api/health 200 within {HEALTHY_WITHIN_SECONDS}s (exit {proc.poll()}); see {log_path}"
        # An Engine without the route falls through to 404 {"error": "Not found"}; this video and host resolve to no row, so the handler answers before the store.
        assert _post(base, "/internal/translate/enqueue", {"id": "no-such-video", "host": "no-such-host.invalid"}, {"X-Bridge-Token": BRIDGE_TOKEN}) == (404, {"error": "Video not found"})
        assert _post(base, "/internal/translate/enqueue", {"id": "no-such-video", "host": "no-such-host.invalid"}, {}) == (401, {"error": "Unauthorized"})  # behind the bridge gate
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=STOP_WITHIN_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
