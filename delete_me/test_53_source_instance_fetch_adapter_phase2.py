"""Phase 2 checkpoint of plan 53: the translate route and the translate worker fetch their instances through `data.source_fetch`.

Route (C1), `handle_internal_translate` and `handle_internal_translate_enqueue` called in process over test_internal_translate.py's server harness (a temporary whitelist.db and subtitles.db, the stdlib request handler stood in for, the wall clock pinned at the module's `now_ms`), each answer checked whole and beside the exact URLs the instance saw:

- An unknown id and a known uuid on another host answer `404 Video not found` with nothing opened; the same server then opens the caption list and the track for the video that resolves and answers `ready`.
- A host in the active denylist answers the same 404 with nothing opened; lifted, the request opens both URLs on `denied.example`, answers `ready` and stores the row; denied again, it answers 404 and opens nothing more. The enqueue route answers the same 404 for it, and `queued` for v-1 under a fresh beat, opening nothing.
- Each bad body answers its 400 exactly with nothing opened: invalid JSON or a JSON array `Invalid JSON body`; no id, a blank host or a numeric id `Missing id or host`; `not a host!` `Invalid host`; an `after` of true, -1, "1", 1.0 or null `Invalid after`. The same server then answers a well-formed body `ready` through the adapter.
- A running row of three stored cues answers, for `after` absent, 0, 1, 3 and 5, exactly the cues from that index on in stored order, with `total` 3, opening nothing; once the job has ended failed the same server opens both URLs and answers `ready`.
- The enqueue route opens nothing in each of its other answers. With no beat, a beat 15 001 ms old or one 1 ms ahead it answers `{"state": "none", "available": false}` and stores no row, and the same server's state route then opens both URLs. With a fresh beat, a key already queued, running, ready, failed or already_english answers exactly that state with `available` true and its row stays as it was; with `SUBTITLE_QUEUE_CAP` other keys queued it answers `busy` and stores nothing, and with one fewer it queues the key; a store error from the enqueue answers `503 {"error": "Translate store unavailable"}` and stores nothing, and the same request queues once the table is back.
- A miss for `u-1` requested as `PEER.Example.` answers `ready` with the parsed cues, opening both URLs on `peer.example`, and stores exactly one `v-1` row with the track text and those cues; a fresh connection to the file answers the same by uuid and by canonical id with nothing more opened.
- No en track, a track that fails to parse, an unserved caption list, an unserved track, a track over 2,000,000 bytes by its Content-Length and a track redirected off the host each answer exactly `{"state": "none", "available": false}`, open exactly the URLs listed (never the redirect target), store nothing, and log `[translate] instance fetch failed host=peer.example path=<path>: <reason>` once per failed fetch with the adapter's reason (`HTTP 404`, `Content-Length 2000001 over 2000000 bytes`, `redirect refused: https://evil.example/track.vtt`), and no such line when no fetch failed.
- One 15 s budget covers both fetches: a 7.5 s caption list leaves the 8 s track 7.5 s, so it answers `none` and logs `deadline passed` for the track; the same track after a caption list that takes no time answers `ready`.
- Each of ten stored states, with a fresh beat and with none, answers exactly its state, cues, `total` and `available`, and opens nothing for ready, queued and running rows and the caption list (then the track when there is one) for the rest.
- A caption entry pointing off the host, by `fileUrl` or a protocol-relative `captionPath`, or no en entry at all, answers `none` with only the caption list opened; the entry that differs only in pointing on the host answers `ready`.

Worker (C2), `run_job` on a claimed v-1 over test_translate_worker.py's whitelist.db and a temporary subtitles.db, with a runner that fails the job if any audio reaches it: an unserved video JSON stores `failed` with exactly `video JSON fetch failed: HTTP 404`, a Content-Length over the cap `video JSON fetch failed: Content-Length 2000001 over 2000000 bytes`, a redirect off the instance `video JSON fetch failed: redirect refused: https://cdn.example/api/v1/videos/u-1` with the target never opened, and a body that is a JSON array or not JSON the bare `video JSON fetch failed`; a served JSON whose duration is 6 s goes past the fetch to `duration 6s over 5s`. Each of those opened exactly the caption list and the video JSON on the instance, and nothing on the media host. A media download redirected off the media host stores exactly `media download failed: HTTP Error 302: Scripted`, with the same two instance URLs opened and only the media URL opened on the media host.

The network is severed at the adapter's single patch point, `data.source_fetch.build_opener`: the route's instance is test_internal_translate.py's `ScriptedInstance`, the worker's two hosts are test_translate_worker.py's `ScriptedHost`s behind one dispatching opener that hands each URL to the host serving it, so a followed cdn.example redirect would show in that host's opened list. `socket.getaddrinfo` raises as well, so a fetch that goes around the adapter fails instead of reaching a real host.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
from argparse import Namespace
from pathlib import Path
from types import ModuleType
from urllib.request import HTTPHandler, HTTPSHandler, Request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import AFTERS, BODY, CUES, DENIED_HOST, DENIED_VIDEO, EN_LISTING, FR_LISTING, HOST, INVALID_JSON, MISSING, NONE, NOW, PEER_VIDEO, PICK_REFUSED, QUEUED, QUEUED_ROW, READY, REFUSED_TARGETS, RUNNING, STORED_READY, TRACK, TRACK_PATH, TRACK_URL, UNAVAILABLE_BEATS, VIDEO_NOT_FOUND, Clock, ScriptedInstance, _beat, _claimed, _enqueue, _handle, _listing, _rows, _seed, _server, _set_denied, _socket_handler, _state, _stored, _subtitles_db, _whitelist, _write  # noqa: E402
from test_translate_worker import CAPTIONS_URL, JOB_VIDEOS, MAX_DURATION, MEDIA_URL, OFF_DOMAIN_VIDEO_URL, OFF_HOST_TARGET, QUEUED_AT, STARTED_AT, VIDEO_URL, WORKER, ScriptedHost, _video  # noqa: E402
from test_translate_worker import _whitelist as _job_whitelist  # noqa: E402

from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, finish_translate_failed, store_running_cues, write_translate_heartbeat  # noqa: E402
from server_config import SUBTITLE_QUEUE_CAP  # noqa: E402

DENIED_CAPTIONS_URL = f"https://{DENIED_HOST}/api/v1/videos/{DENIED_VIDEO[1]}/captions"
DENIED_TRACK_URL = f"https://{DENIED_HOST}{TRACK_PATH}"
INSTANCE_TRACK = [CAPTIONS_URL, TRACK_URL]
FAILED_FETCH = "[translate] instance fetch failed"
CAPTIONS_PATH = f"/api/v1/videos/{PEER_VIDEO[1]}/captions"
OFF_HOST_TRACK_URL = REFUSED_TARGETS["off-host"]
BAD_TRACK = b"WEBVTT\n\n00:01.00 --> 00:02.000\nTwo-digit milliseconds\n"


def _ok(body: bytes) -> dict:
    """ScriptedInstance.serve keywords for a 200 with this body."""
    return {"chunks": [body]}


# Each way the instance answers `none`: what it serves (URL to serve keywords), every URL opened, and every failed-fetch log line.
NONE_CASES = {
    "no en track": ({CAPTIONS_URL: _ok(FR_LISTING), TRACK_URL: _ok(TRACK.encode("utf-8"))}, [CAPTIONS_URL], []),
    "track fails to parse": ({CAPTIONS_URL: _ok(EN_LISTING), TRACK_URL: _ok(BAD_TRACK)}, INSTANCE_TRACK, []),
    "caption list unserved": ({TRACK_URL: _ok(TRACK.encode("utf-8"))}, [CAPTIONS_URL], [f"{FAILED_FETCH} host={HOST} path={CAPTIONS_PATH}: HTTP 404"]),
    "track unserved": ({CAPTIONS_URL: _ok(EN_LISTING)}, INSTANCE_TRACK, [f"{FAILED_FETCH} host={HOST} path={TRACK_PATH}: HTTP 404"]),
    "track over the cap by its Content-Length": ({CAPTIONS_URL: _ok(EN_LISTING), TRACK_URL: {"headers": {"Content-Length": "2000001"}, "chunks": [TRACK.encode("utf-8")]}}, INSTANCE_TRACK, [f"{FAILED_FETCH} host={HOST} path={TRACK_PATH}: Content-Length 2000001 over 2000000 bytes"]),
    # The target is served the good track, so a fetch that followed it would answer ready.
    "track redirected off the host": ({CAPTIONS_URL: _ok(EN_LISTING), TRACK_URL: {"status": 302, "headers": {"Location": OFF_HOST_TRACK_URL}}, OFF_HOST_TRACK_URL: _ok(TRACK.encode("utf-8"))}, INSTANCE_TRACK, [f"{FAILED_FETCH} host={HOST} path={TRACK_PATH}: redirect refused: {OFF_HOST_TRACK_URL}"]),
}

INVALID_AFTER = [[400, {"error": "Invalid after"}]]
# Each body the state route refuses before any store read or fetch, and its literal answer.
REFUSED_BODIES = {
    "invalid JSON": (b"{not json", INVALID_JSON),
    "a JSON array": (b"[1, 2]", INVALID_JSON),
    "no id": ({"host": HOST}, MISSING),
    "blank host": ({"id": PEER_VIDEO[1], "host": "  "}, MISSING),
    "numeric id": ({"id": 1, "host": HOST}, MISSING),
    "invalid host": ({"id": PEER_VIDEO[1], "host": "not a host!"}, [[400, {"error": "Invalid host"}]]),
    "after true": ({**BODY, "after": True}, INVALID_AFTER),
    "after -1": ({**BODY, "after": -1}, INVALID_AFTER),
    "after a string": ({**BODY, "after": "1"}, INVALID_AFTER),
    "after a float": ({**BODY, "after": 1.0}, INVALID_AFTER),
    "after null": ({**BODY, "after": None}, INVALID_AFTER),
}

# (stored row, instance holds a track, the answer without `available`, every URL opened).
BRANCHES = {
    "no row, no track": ("no row", False, {"state": "none"}, [CAPTIONS_URL]),
    "no row, instance track": ("no row", True, {"state": "ready", "cues": CUES}, INSTANCE_TRACK),
    "ready": ("ready", True, {"state": "ready", "cues": STORED_READY}, []),
    "queued": ("queued", True, {"state": "queued"}, []),
    "running": ("running", True, {"state": "running", "cues": RUNNING, "total": 3}, []),
    "failed, no track": ("failed", False, {"state": "failed"}, [CAPTIONS_URL]),
    "failed, instance track": ("failed", True, {"state": "ready", "cues": CUES}, INSTANCE_TRACK),
    "already_english, no track": ("already_english", False, {"state": "already_english"}, [CAPTIONS_URL]),
    "already_english, instance track": ("already_english", True, {"state": "ready", "cues": CUES}, INSTANCE_TRACK),
    "ready with cues that do not load, no track": ("corrupt ready", False, {"state": "none"}, [CAPTIONS_URL]),
}

# Worker: what the instance and the media host serve (URL to ScriptedHost.serve keywords), the stored error, and every URL each host opened.
INSTANCE_THEN_JSON = [CAPTIONS_URL, VIDEO_URL]
JOBS = {
    "video JSON unserved": ({}, {}, "video JSON fetch failed: HTTP 404", INSTANCE_THEN_JSON, []),
    "video JSON over the cap by its Content-Length": ({VIDEO_URL: {"headers": {"Content-Length": "2000001"}, "body": _video()}}, {}, "video JSON fetch failed: Content-Length 2000001 over 2000000 bytes", INSTANCE_THEN_JSON, []),
    # The target is served a valid JSON, so a fetch that followed it would go on to the media host.
    "video JSON redirected off the instance": ({VIDEO_URL: {"status": 302, "headers": {"Location": OFF_DOMAIN_VIDEO_URL}}, OFF_DOMAIN_VIDEO_URL: {"body": _video()}}, {}, f"video JSON fetch failed: redirect refused: {OFF_DOMAIN_VIDEO_URL}", INSTANCE_THEN_JSON, []),
    "video JSON a JSON array": ({VIDEO_URL: {"body": b"[]"}}, {}, "video JSON fetch failed", INSTANCE_THEN_JSON, []),
    "video JSON not JSON": ({VIDEO_URL: {"body": b"not json"}}, {}, "video JSON fetch failed", INSTANCE_THEN_JSON, []),
    "video JSON served, duration over the cap": ({VIDEO_URL: {"body": _video(duration=MAX_DURATION + 1)}}, {}, "duration 6s over 5s", INSTANCE_THEN_JSON, []),
    "media redirected off the media host": ({VIDEO_URL: {"body": _video()}}, {MEDIA_URL: {"status": 302, "headers": {"Location": OFF_HOST_TARGET}}, OFF_HOST_TARGET: {"body": b"RIFF"}}, "media download failed: HTTP Error 302: Scripted", INSTANCE_THEN_JSON, [MEDIA_URL]),
}


@pytest.fixture(autouse=True)
def severed_network(monkeypatch) -> None:
    """Name resolution fails, so a fetch that goes around the adapter's patch point fails here instead of reaching a real host."""

    def unreachable(*args: object, **kwargs: object) -> list:
        raise OSError("network severed by the checkpoint")

    monkeypatch.setattr(socket, "getaddrinfo", unreachable)


@pytest.fixture
def instance(monkeypatch) -> ScriptedInstance:
    clock = Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    scripted = ScriptedInstance(clock, monkeypatch)
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", scripted.build_opener)
    return scripted


@pytest.fixture
def whitelist(tmp_path) -> sqlite3.Connection:
    conn = _whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


def _route(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The route module, imported inside each test so that an import failure fails each test on its own, with its wall clock pinned at NOW."""
    module = importlib.import_module("handlers.internal_translate")
    monkeypatch.setattr(module, "now_ms", lambda: NOW)
    return module


def _serve(instance: ScriptedInstance, video: tuple[str, str, str], listing: bytes, track: bytes) -> None:
    _, uuid, host = video
    instance.serve(f"https://{host}/api/v1/videos/{uuid}/captions", chunks=[listing])
    instance.serve(f"https://{host}{TRACK_PATH}", chunks=[track])


def _failed_fetches(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith(FAILED_FETCH)]


def _split(data: bytes, parts: int) -> list[bytes]:
    size = -(-len(data) // parts)
    return [data[i * size:(i + 1) * size] for i in range(parts)]


def test_an_unknown_video_opens_nothing_and_a_resolved_one_is_fetched_through_the_adapter(tmp_path, whitelist, instance, monkeypatch):
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, {"id": "no-such-video", "host": HOST}) == VIDEO_NOT_FOUND  # C1
    assert _handle(internal_translate, server, {"id": PEER_VIDEO[1], "host": "other.example"}) == VIDEO_NOT_FOUND  # C1
    assert instance.opened == []  # C1
    # Control: the same server reaches the scripted instance through the adapter for the video that resolves.
    assert _handle(internal_translate, server, BODY) == READY  # C1
    assert instance.opened == INSTANCE_TRACK  # C1


def test_a_denylisted_host_answers_404_before_any_fetch_even_with_a_stored_track(tmp_path, whitelist, instance, monkeypatch):
    _serve(instance, DENIED_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = {"id": DENIED_VIDEO[1], "host": DENIED_HOST}
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND  # C1
    assert instance.opened == []  # C1
    _set_denied(whitelist, False)
    assert _handle(internal_translate, server, body) == READY  # C1: control, lifted it fetches
    assert instance.opened == [DENIED_CAPTIONS_URL, DENIED_TRACK_URL]  # C1
    assert [row[:2] for row in _stored(tmp_path / "subtitles.db")] == [DENIED_VIDEO[::2]]  # C1
    _set_denied(whitelist, True)
    assert _handle(internal_translate, server, body) == VIDEO_NOT_FOUND  # C1: the stored track is not served either
    assert instance.opened == [DENIED_CAPTIONS_URL, DENIED_TRACK_URL]  # C1


@pytest.mark.parametrize("body, answer", REFUSED_BODIES.values(), ids=REFUSED_BODIES.keys())
def test_each_bad_body_answers_its_400_with_nothing_opened(tmp_path, whitelist, instance, monkeypatch, body, answer):
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _state(internal_translate, server, body) == answer  # C1
    assert instance.opened == []  # C1
    # Control: the same server answers a well-formed body through the adapter, so the empty list above is the refusal's doing.
    assert _handle(internal_translate, server, BODY) == READY  # C1
    assert instance.opened == INSTANCE_TRACK  # C1


@pytest.mark.parametrize("after, cues", AFTERS.values(), ids=AFTERS.keys())
def test_a_running_row_answers_its_cues_from_after_with_the_stored_total_and_opens_nothing(tmp_path, whitelist, instance, monkeypatch, after, cues):
    store = _subtitles_db(tmp_path / "subtitles.db")
    started_at = _claimed(store)
    assert store_running_cues(store, PEER_VIDEO[0], HOST, "en", started_at, RUNNING, "fr")
    write_translate_heartbeat(store, NOW, 1)
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = BODY if after is None else {**BODY, "after": after}
    assert _handle(internal_translate, server, body) == [[200, {"state": "running", "cues": cues, "total": 3, "available": True}]]  # C1
    assert instance.opened == []  # C1
    # Control: once the job has ended failed the same server fetches through the adapter, so the empty list above is the running branch's doing.
    assert finish_translate_failed(store, PEER_VIDEO[0], HOST, "en", started_at, "boom", NOW)
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": True}]]  # C1
    assert instance.opened == INSTANCE_TRACK  # C1


def test_enqueue_answers_404_for_a_denied_host_and_queued_under_a_fresh_beat_opening_nothing(tmp_path, whitelist, instance, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    write_translate_heartbeat(store, NOW, 1)
    store.close()
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    _serve(instance, DENIED_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    _set_denied(whitelist, True)
    assert _enqueue(internal_translate, server, {"id": DENIED_VIDEO[1], "host": DENIED_HOST}) == VIDEO_NOT_FOUND  # C1
    assert _enqueue(internal_translate, server, BODY) == QUEUED  # C1
    assert instance.opened == []  # C1


@pytest.mark.parametrize("age", UNAVAILABLE_BEATS.values(), ids=UNAVAILABLE_BEATS.keys())
def test_enqueue_without_a_serving_worker_answers_none_not_available_and_queues_and_opens_nothing(tmp_path, whitelist, instance, monkeypatch, age):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, age)
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == NONE  # C1
    assert _rows(subtitles_path) == []  # C1
    assert instance.opened == []  # C1
    # Control: the same server's state route reaches the instance through the adapter, so the empty list above is the enqueue route's doing.
    assert _handle(internal_translate, server, BODY) == READY  # C1
    assert instance.opened == INSTANCE_TRACK  # C1


@pytest.mark.parametrize("state", ["queued", "running", "ready", "failed", "already_english"])
def test_enqueue_with_a_serving_worker_answers_a_stored_key_its_state_and_leaves_its_row_opening_nothing(tmp_path, whitelist, instance, monkeypatch, state):
    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    _seed(store, state)
    store.close()
    _beat(subtitles_path, 0)
    before = _rows(subtitles_path)
    assert [row[:4] for row in before] == [(PEER_VIDEO[0], HOST, "en", state)]  # control: the seeded row is the key in that state
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    assert _enqueue(internal_translate, _server(whitelist, subtitles_path), BODY) == [[200, {"state": state, "available": True}]]  # C1
    assert _rows(subtitles_path) == before  # C1: never overwritten, no second row
    assert instance.opened == []  # C1


def test_enqueue_at_the_queue_cap_answers_busy_and_one_below_it_queues_opening_nothing(tmp_path, whitelist, instance, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    store = _subtitles_db(subtitles_path)
    # Other videos' jobs fill the queue; the store counts every queued row against the cap.
    for index in range(SUBTITLE_QUEUE_CAP):
        assert tuple(enqueue_translate_job(store, f"q-{index:03d}", HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 5000)) == ("queued", "queued")
    store.close()
    _beat(subtitles_path, 0)
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    assert _enqueue(internal_translate, server, BODY) == [[200, {"state": "busy", "available": True}]]  # C1
    assert [row for row in _rows(subtitles_path) if row[0] == PEER_VIDEO[0]] == []  # C1: busy stores nothing
    # Control: with one fewer queued job the same server queues the key, so busy above came at exactly the cap.
    _write(subtitles_path, "DELETE FROM subtitles WHERE video_id = 'q-000'")
    assert _enqueue(internal_translate, server, BODY) == QUEUED  # C1
    assert [row for row in _rows(subtitles_path) if row[0] == PEER_VIDEO[0]] == [QUEUED_ROW]  # C1
    assert instance.opened == []  # C1


def test_a_store_error_from_the_enqueue_answers_503_and_queues_and_opens_nothing(tmp_path, whitelist, instance, monkeypatch):
    subtitles_path = tmp_path / "subtitles.db"
    _beat(subtitles_path, 0)
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, subtitles_path)
    # The heartbeat table stays, so the gate reads a fresh beat and the enqueue itself raises `no such table: subtitles`.
    _write(subtitles_path, "ALTER TABLE subtitles RENAME TO subtitles_away")
    assert _enqueue(internal_translate, server, BODY) == [[503, {"error": "Translate store unavailable"}]]  # C1
    _write(subtitles_path, "ALTER TABLE subtitles_away RENAME TO subtitles")
    assert _rows(subtitles_path) == []  # C1
    # Control: with the table back the same request queues.
    assert _enqueue(internal_translate, server, BODY) == QUEUED  # C1
    assert _rows(subtitles_path) == [QUEUED_ROW]  # C1
    assert instance.opened == []  # C1


def test_a_ready_track_is_fetched_from_the_row_host_stored_and_then_served_without_a_fetch(tmp_path, whitelist, instance, monkeypatch):
    _serve(instance, PEER_VIDEO, EN_LISTING, TRACK.encode("utf-8"))
    internal_translate = _route(monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    # The request host differs from the row's `peer.example` in case and a trailing dot, so fetching the request host would show.
    body = {"id": PEER_VIDEO[1], "host": "PEER.Example."}
    assert _handle(internal_translate, _server(whitelist, subtitles_path), body) == READY  # C1
    assert instance.opened == INSTANCE_TRACK  # C1
    (row,) = _stored(subtitles_path)
    assert row[:6] == (PEER_VIDEO[0], HOST, "en", "ready", "instance", TRACK)  # C1
    assert json.loads(row[6]) == CUES  # C1
    reopened = _server(whitelist, subtitles_path)
    assert _handle(internal_translate, reopened, body) == READY  # C1
    assert _handle(internal_translate, reopened, {"id": PEER_VIDEO[0], "host": HOST}) == READY  # C1
    assert instance.opened == INSTANCE_TRACK  # C1: served from subtitles.db, nothing more opened


@pytest.mark.parametrize("served, opened, failures", NONE_CASES.values(), ids=NONE_CASES.keys())
def test_each_none_path_answers_none_stores_nothing_and_logs_each_failed_fetch_with_its_reason(tmp_path, whitelist, instance, monkeypatch, caplog, served, opened, failures):
    caplog.set_level(logging.INFO)
    for url, keywords in served.items():
        instance.serve(url, **keywords)
    internal_translate = _route(monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    assert _handle(internal_translate, _server(whitelist, subtitles_path), BODY) == NONE  # C1
    assert instance.opened == opened  # C1: a refused redirect target is never opened
    assert _stored(subtitles_path) == []  # C1
    assert _failed_fetches(caplog) == failures  # C1


def test_one_15_second_budget_covers_both_fetches(tmp_path, whitelist, instance, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    # 7.5 s of caption list leaves 7.5 s of the 15 s budget; the track takes 8 s, which its own 8 s deadline allows.
    instance.serve(CAPTIONS_URL, chunks=_split(EN_LISTING, 3), seconds_per_chunk=2.5)
    instance.serve(TRACK_URL, chunks=_split(TRACK.encode("utf-8"), 4), seconds_per_chunk=2.0)
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, BODY) == NONE  # C1
    assert instance.opened == INSTANCE_TRACK  # C1
    assert _failed_fetches(caplog) == [f"{FAILED_FETCH} host={HOST} path={TRACK_PATH}: deadline passed"]  # C1
    # Control: after a caption list that takes no time, the same track arrives inside the budget.
    instance.serve(CAPTIONS_URL, chunks=[EN_LISTING])
    assert _handle(internal_translate, server, BODY) == READY  # C1
    assert instance.opened == INSTANCE_TRACK * 2  # C1


@pytest.mark.parametrize("available", [True, False], ids=["fresh beat", "no beat"])
@pytest.mark.parametrize("row, track, answer, opened", BRANCHES.values(), ids=BRANCHES.keys())
def test_each_stored_state_answers_its_state_and_fetches_only_past_queued_and_running(tmp_path, whitelist, instance, monkeypatch, row, track, answer, opened, available):
    store = _subtitles_db(tmp_path / "subtitles.db")
    _seed(store, row)
    if available:
        write_translate_heartbeat(store, NOW, 1)
    instance.serve(CAPTIONS_URL, chunks=[EN_LISTING if track else FR_LISTING])
    if track:
        instance.serve(TRACK_URL, chunks=[TRACK.encode("utf-8")])
    internal_translate = _route(monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), BODY) == [[200, {**answer, "available": available}]]  # C1
    assert instance.opened == opened  # C1


@pytest.mark.parametrize("entry, on_host", PICK_REFUSED.values(), ids=PICK_REFUSED.keys())
def test_a_caption_entry_off_the_host_answers_none_with_only_the_caption_list_opened(tmp_path, whitelist, instance, monkeypatch, entry, on_host):
    # Every refused target is served the good track, so a pick that accepted one would open it and answer ready.
    for url in (TRACK_URL, *REFUSED_TARGETS.values()):
        instance.serve(url, chunks=[TRACK.encode("utf-8")])
    instance.serve(CAPTIONS_URL, chunks=[_listing(entry)])
    internal_translate = _route(monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, BODY) == NONE  # C1
    assert instance.opened == [CAPTIONS_URL]  # C1
    # Control: the entry that differs only in pointing on the host as `en` is fetched.
    instance.serve(CAPTIONS_URL, chunks=[_listing(on_host)])
    assert _handle(internal_translate, server, BODY) == READY  # C1
    assert instance.opened == [CAPTIONS_URL, *INSTANCE_TRACK]  # C1


def _dispatching_opener(instance: ScriptedHost, media: ScriptedHost):  # noqa: ANN202
    """One build_opener for both scripted hosts, as the adapter's patch point takes it: a URL goes to the host that serves it, else by request host (peer.example to the instance, any other to the media host); the adapter's own handlers go into a real urllib opener."""

    def build_opener(*handlers: object) -> urllib.request.OpenerDirector:
        def owner(req: Request) -> ScriptedHost:
            return next((host for host in (instance, media) if req.full_url in host.routes), instance if req.host == HOST else media)

        class DispatchHTTPS(HTTPSHandler):
            def https_open(self, req: Request):  # noqa: ANN202
                return owner(req).open(req)

        class DispatchHTTP(HTTPHandler):
            def http_open(self, req: Request):  # noqa: ANN202
                return owner(req).open(req)

        return urllib.request.build_opener(DispatchHTTPS(), DispatchHTTP(), *[handler for handler in handlers if not _socket_handler(handler)])

    return build_opener


def _load_worker() -> ModuleType:
    """The worker script as a module; its hyphenated name rules out a plain import."""
    spec = importlib.util.spec_from_file_location("translate_worker", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UnreachedRunner:
    """Stands in for WhisperRunner on jobs that must end before any audio is decoded: reaching it fails the job with its own text."""

    model = None

    def speech(self, pcm: bytes) -> list:
        raise AssertionError("speech reached")

    def transcribe(self, pcm: bytes, language: str | None = None) -> tuple:
        raise AssertionError("transcribe reached")

    def unload(self) -> None:
        pass


@pytest.mark.parametrize("instance_serves, media_serves, error, instance_opened, media_opened", JOBS.values(), ids=JOBS.keys())
def test_a_job_stores_a_failed_video_json_fetch_with_the_adapters_reason(tmp_path, monkeypatch, instance_serves, media_serves, error, instance_opened, media_opened):
    whitelist_path = tmp_path / "whitelist.db"
    _job_whitelist(whitelist_path, JOB_VIDEOS, deny=True)
    subtitles_path = tmp_path / "subtitles.db"
    conn = connect_subtitles_db(subtitles_path)
    ensure_subtitles_schema(conn)
    instance, media = ScriptedHost(), ScriptedHost()
    for url, keywords in instance_serves.items():
        instance.serve(url, **keywords)
    for url, keywords in media_serves.items():
        media.serve(url, **keywords)
    worker = _load_worker()
    monkeypatch.setattr(importlib.import_module("data.source_fetch"), "build_opener", _dispatching_opener(instance, media))
    assert tuple(enqueue_translate_job(conn, PEER_VIDEO[0], HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    job = claim_translate_job(conn, "en", STARTED_AT)
    args = Namespace(whitelist_db=whitelist_path, max_duration=MAX_DURATION, max_bytes=4096, max_chunk_seconds=1)
    try:
        worker.run_job(conn, job, args, UnreachedRunner(), threading.Event(), {"at": time.monotonic()})
    finally:
        conn.close()
    reader = sqlite3.connect(subtitles_path)
    try:
        stored = reader.execute("SELECT state, error FROM subtitles WHERE video_id = ? AND instance_domain = ?", (PEER_VIDEO[0], HOST)).fetchone()
    finally:
        reader.close()
    assert stored == ("failed", error)  # C2
    assert instance.opened == instance_opened  # C2: the caption list and the video JSON, never a redirect target
    assert media.opened == media_opened  # C2
