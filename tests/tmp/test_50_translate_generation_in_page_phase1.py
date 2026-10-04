"""Plan 50 phase 1 checkpoint: `/internal/translate` answers a key's stored job state with `available`, and the store gains readers for a key's state and the translate heartbeat.

Store readers (`data/subtitles.py`, rung 1):

- `fetch_subtitle_state` gives None for a key with no row, and for the same video under another language or host; a queued key gives `("queued", None)`; a running key whose cues_json was hand-damaged gives `("running", "{not json")`, the text unparsed.
- `fetch_translate_heartbeat` gives None on a fresh schema, then the beat_at last written: 1234, then 5678.

State route (`handle_internal_translate` through the `test_internal_translate.py` harness: real whitelist.db and subtitles.db, the instance stood in for at `fetch_bounded`, the wall clock pinned at the module's `now_ms`):

- C1: for a key with no row, `available` is true for a beat 0 ms and 15 000 ms old, and false for no beat, a beat 15 001 ms old and a beat 1 ms ahead. Each of ten branches (no row, ready, queued, running, failed, already_english, a ready row whose cues do not load; failed, already_english and no row each with and without an instance track) answers exactly its state, its cues and `total` where it has them, and `available` true with a fresh beat and false with none. A closed store answers `none` with `available` false, where the same server answers true once its store is back.
- C2: a running key stored out of start order answers its stored cues from `after` on, in stored order, with `total` 3, for `after` absent, 0, 1, 3 and 5, and fetches nothing; once that job is failed the same server fetches the caption list. A running key whose cues_json is unset, `[]`, not JSON or not a list answers no cues and `total` 0 with no fetch; once that job is failed the same server fetches.
- Order around them: ready, queued and running rows answer from the store with no fetch even when the instance holds a track; failed and already_english rows answer their state after a fetch finds no track, and `ready` with the instance cues when it finds one; a ready row whose cues do not load answers `none` after the fetch. `after` given as true, false, -1, "1", null or 1.0 answers 400 with an error and no fetch for a running, a failed and an unrowed key, where `after` 1 answers 200 and the failed and unrowed keys then fetch the caption list; the same values for an unknown video answer exactly 404 `Video not found` with no fetch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import CUES, EN_LISTING, FR_LISTING, HOST, PEER_VIDEO, TRACK, TRACK_PATH, RecordingInstance, _handle, _handler_module, _server, _subtitles_db, whitelist  # noqa: E402,F401

VIDEO_ID, VIDEO_UUID, _ = PEER_VIDEO
BODY = {"id": VIDEO_UUID, "host": HOST}
CAPTIONS = (HOST, f"/api/v1/videos/{VIDEO_UUID}/captions")
TRACK_FETCHES = [CAPTIONS, (HOST, TRACK_PATH)]
# The wall clock is a system boundary: pinned, a beat's age is exact, so the 0 and 15 000 ms edges are tested without a race against the real clock.
NOW = 1_760_000_000_000
# Stored in chunk order, not start order, so an answer that re-sorts the running cues shows.
RUNNING = [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}]
# Differs from CUES (the instance track), so a stored ready answer that was fetched instead shows.
STORED_READY = [{"start": 7.0, "end": 8.0, "text": "Stored"}]
BAD_AFTER = {"true": True, "false": False, "negative": -1, "string": "1", "null": None, "float": 1.0}


def _instance(track: bool) -> RecordingInstance:
    """The video's instance: a caption list whose en track parses to CUES, or one with no en entry."""
    instance = RecordingInstance()
    instance.serve(PEER_VIDEO, EN_LISTING if track else FR_LISTING, TRACK.encode("utf-8") if track else None)
    return instance


def _route(instance: RecordingInstance, monkeypatch: pytest.MonkeyPatch):
    module = _handler_module(instance, monkeypatch)
    monkeypatch.setattr(module, "now_ms", lambda: NOW)
    return module


def _damage(store, cues_json: str) -> None:
    """Overwrite the key's cues_json by hand, as only a damaged file would hold it."""
    with store:
        store.execute("UPDATE subtitles SET cues_json = ? WHERE video_id = ?", (cues_json, VIDEO_ID))


def _claimed(store) -> int:
    """Queue and claim the key's job; its started_at."""
    from data.subtitles import claim_translate_job, enqueue_translate_job

    enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000)
    return claim_translate_job(store, "en", NOW - 1000)["started_at"]


def _seed(store, row: str) -> None:
    """Leave the key in one stored state, written by the store's own writers."""
    from data.subtitles import enqueue_translate_job, finish_translate_already_english, finish_translate_failed, store_ready_subtitles, store_running_cues

    if row == "ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", "WEBVTT stored", STORED_READY, NOW - 1000)
    elif row == "corrupt ready":
        store_ready_subtitles(store, VIDEO_ID, HOST, "en", "instance", "WEBVTT stored", STORED_READY, NOW - 1000)
        _damage(store, "{not json")
    elif row == "queued":
        enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000)
    elif row == "running":
        assert store_running_cues(store, VIDEO_ID, HOST, "en", _claimed(store), RUNNING, "fr")
    elif row == "failed":
        assert finish_translate_failed(store, VIDEO_ID, HOST, "en", _claimed(store), "boom", NOW - 500)
    elif row == "already_english":
        assert finish_translate_already_english(store, VIDEO_ID, HOST, "en", _claimed(store), "en", NOW - 500)
    else:
        assert row == "no row", row


def test_fetch_subtitle_state_gives_a_keys_state_and_raw_cues_json_or_none(tmp_path):
    from data.subtitles import fetch_subtitle_state

    store = _subtitles_db(tmp_path / "subtitles.db")
    assert fetch_subtitle_state(store, VIDEO_ID, HOST, "en") is None
    _seed(store, "queued")
    assert tuple(fetch_subtitle_state(store, VIDEO_ID, HOST, "en")) == ("queued", None)
    store.execute("DELETE FROM subtitles")
    store.commit()
    _seed(store, "running")
    _damage(store, "{not json")
    assert tuple(fetch_subtitle_state(store, VIDEO_ID, HOST, "en")) == ("running", "{not json")  # unparsed
    assert fetch_subtitle_state(store, VIDEO_ID, HOST, "fr") is None  # keyed on the language
    assert fetch_subtitle_state(store, VIDEO_ID, "other.example", "en") is None  # keyed on the host


def test_fetch_translate_heartbeat_gives_none_on_a_fresh_schema_then_the_last_beat(tmp_path):
    from data.subtitles import fetch_translate_heartbeat, write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    assert fetch_translate_heartbeat(store) is None
    write_translate_heartbeat(store, 1234, 7)
    assert fetch_translate_heartbeat(store) == 1234
    write_translate_heartbeat(store, 5678, 7)
    assert fetch_translate_heartbeat(store) == 5678


# Age in ms of the beat at answer time; negative is a beat dated ahead of now.
BEATS = {"no beat": (None, False), "0 ms old": (0, True), "15 000 ms old": (15_000, True), "15 001 ms old": (15_001, False), "1 ms ahead": (-1, False)}


@pytest.mark.parametrize("age, available", BEATS.values(), ids=BEATS.keys())
def test_available_is_true_only_for_a_heartbeat_0_to_15000_ms_old(tmp_path, whitelist, monkeypatch, age, available):
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    if age is not None:
        write_translate_heartbeat(store, NOW - age, 1)
    internal_translate = _route(_instance(False), monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), BODY) == [[200, {"state": "none", "available": available}]]  # C1


def test_a_closed_store_answers_none_and_not_available(tmp_path, whitelist, monkeypatch):
    from data.subtitles import write_translate_heartbeat

    write_translate_heartbeat(_subtitles_db(tmp_path / "subtitles.db"), NOW, 1)
    internal_translate = _route(_instance(False), monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    open_store = server.subtitles_db
    server.subtitles_db = None  # as server.py leaves it at shutdown
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "none", "available": False}]]  # C1
    # Control: the same server reads the fresh beat once its store is back, so the false above is the closed store's doing.
    server.subtitles_db = open_store
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "none", "available": True}]]


# (stored row, instance holds a track, the answer without `available`, the instance fetches).
BRANCHES = {
    "no row, no track": ("no row", False, {"state": "none"}, [CAPTIONS]),
    "no row, instance track": ("no row", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "ready": ("ready", True, {"state": "ready", "cues": STORED_READY}, []),
    "queued": ("queued", True, {"state": "queued"}, []),
    "running": ("running", True, {"state": "running", "cues": RUNNING, "total": 3}, []),
    "failed, no track": ("failed", False, {"state": "failed"}, [CAPTIONS]),
    "failed, instance track": ("failed", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "already_english, no track": ("already_english", False, {"state": "already_english"}, [CAPTIONS]),
    "already_english, instance track": ("already_english", True, {"state": "ready", "cues": CUES}, TRACK_FETCHES),
    "ready with cues that do not load, no track": ("corrupt ready", False, {"state": "none"}, [CAPTIONS]),
}


@pytest.mark.parametrize("available", [True, False], ids=["fresh beat", "no beat"])
@pytest.mark.parametrize("row, track, answer, fetches", BRANCHES.values(), ids=BRANCHES.keys())
def test_each_stored_state_answers_its_state_with_available_and_fetches_only_past_queued_and_running(tmp_path, whitelist, monkeypatch, row, track, answer, fetches, available):
    from data.subtitles import write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    _seed(store, row)
    if available:
        write_translate_heartbeat(store, NOW, 1)
    instance = _instance(track)
    internal_translate = _route(instance, monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), BODY) == [[200, {**answer, "available": available}]]  # C1, and C2 for running
    assert instance.fetched == fetches  # C2 for running: no fetch even with a track on the instance


# `after` (absent when None) and the running cues it answers, written out rather than sliced.
AFTERS = {
    "absent": (None, RUNNING),
    "0": (0, RUNNING),
    "1": (1, [{"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}]),
    "3, the total": (3, []),
    "5, past the total": (5, []),
}


@pytest.mark.parametrize("after, cues", AFTERS.values(), ids=AFTERS.keys())
def test_a_running_key_answers_its_cues_from_after_with_the_stored_total_and_no_fetch(tmp_path, whitelist, monkeypatch, after, cues):
    from data.subtitles import finish_translate_failed, store_running_cues, write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    started_at = _claimed(store)
    assert store_running_cues(store, VIDEO_ID, HOST, "en", started_at, RUNNING, "fr")
    write_translate_heartbeat(store, NOW, 1)
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    body = BODY if after is None else {**BODY, "after": after}
    assert _handle(internal_translate, server, body) == [[200, {"state": "running", "cues": cues, "total": 3, "available": True}]]  # C2
    assert instance.fetched == []  # C2
    # Control: the same server and instance fetch once the job has ended failed, so the empty list above is the running branch's doing.
    assert finish_translate_failed(store, VIDEO_ID, HOST, "en", started_at, "boom", NOW)
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": True}]]
    assert instance.fetched == TRACK_FETCHES


# What the running row's cues_json holds: never written (None), or written as this text.
ZERO_CUES = {"unset": None, "empty": "[]", "not JSON": "{not json", "not a list": '{"start": 1.0, "end": 2.0, "text": "x"}'}


@pytest.mark.parametrize("cues_json", ZERO_CUES.values(), ids=ZERO_CUES.keys())
def test_a_running_key_with_unset_empty_or_damaged_cues_answers_no_cues_and_total_0(tmp_path, whitelist, monkeypatch, cues_json):
    from data.subtitles import finish_translate_failed, write_translate_heartbeat

    store = _subtitles_db(tmp_path / "subtitles.db")
    started_at = _claimed(store)
    if cues_json is not None:
        _damage(store, cues_json)
    write_translate_heartbeat(store, NOW, 1)
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "running", "cues": [], "total": 0, "available": True}]]  # C2
    assert instance.fetched == []  # C2
    # Control: the same server and instance fetch once the job has ended failed, so the empty list above is the running branch's doing.
    assert finish_translate_failed(store, VIDEO_ID, HOST, "en", started_at, "boom", NOW)
    assert _handle(internal_translate, server, BODY) == [[200, {"state": "ready", "cues": CUES, "available": True}]]
    assert instance.fetched == TRACK_FETCHES


# Stored row, and what the instance fetches for it once `after` is valid: failed and no row would fetch, so a refusal checked only on the running branch shows.
REFUSED_ROWS = {"running": ("running", []), "failed": ("failed", [CAPTIONS]), "no row": ("no row", [CAPTIONS])}


@pytest.mark.parametrize("row, fetches", REFUSED_ROWS.values(), ids=REFUSED_ROWS.keys())
@pytest.mark.parametrize("after", BAD_AFTER.values(), ids=BAD_AFTER.keys())
def test_after_that_is_not_a_non_negative_json_int_answers_400(tmp_path, whitelist, monkeypatch, after, row, fetches):
    store = _subtitles_db(tmp_path / "subtitles.db")
    _seed(store, row)
    instance = _instance(False)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    (response,) = _handle(internal_translate, server, {**BODY, "after": after})
    assert response[0] == 400, response
    assert set(response[1]) == {"error"}, response
    assert instance.fetched == []
    # Control: the same request with a valid `after` is answered, and for failed and no row the same instance is fetched, so the empty list above is the refusal's doing.
    assert _handle(internal_translate, server, {**BODY, "after": 1})[0][0] == 200
    assert instance.fetched == fetches


@pytest.mark.parametrize("after", BAD_AFTER.values(), ids=BAD_AFTER.keys())
def test_an_unknown_video_with_a_bad_after_answers_404_video_not_found(tmp_path, whitelist, monkeypatch, after):
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    assert _handle(internal_translate, _server(whitelist, tmp_path / "subtitles.db"), {"id": "no-such-video", "host": HOST, "after": after}) == [[404, {"error": "Video not found"}]]
    assert instance.fetched == []
