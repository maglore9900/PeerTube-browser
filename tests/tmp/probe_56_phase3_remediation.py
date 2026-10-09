"""Probe for the phase 3 remediation: the unchanged state route on leased failed/already_english rows with other keys present, and router.route_post driving the translate handlers."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_internal_translate import BODY, HOST, NOW, VIDEO_ID, HandlerRequest, _beat, _claimed, _instance, _route, _server, _state, _subtitles_db, whitelist  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job  # noqa: E402

LEASE = NOW - 60_000


def _dump(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT rowid, * FROM subtitles")]
    finally:
        conn.close()


def _seed(path, end):
    store = _subtitles_db(path)
    print("enqueue v-1", enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000, wanted_at=LEASE))
    job = claim_translate_job(store, "en", NOW - 1000)
    print("claimed", job)
    if end == "failed":
        print("end", job.end_failed("boom", NOW - 500))
    else:
        print("end", job.end_already_english("en", NOW - 500))
    for key in ((VIDEO_ID, "other.example", "en"), ("v-2", HOST, "en"), (VIDEO_ID, HOST, "fr")):
        print("other", key, enqueue_translate_job(store, key[0], key[1], key[2], 50, NOW - 1500, wanted_at=LEASE))
    store.close()
    _beat(path, 0)


def test_failed_and_already_english(tmp_path, whitelist, monkeypatch):
    for end in ("failed", "already_english"):
        path = tmp_path / f"{end}.db"
        _seed(path, end)
        before = _dump(path)
        instance = _instance(False)
        answered = _state(_route(instance, monkeypatch), _server(whitelist, path), BODY)
        after = _dump(path)
        print(end, "ANSWER", answered)
        print(end, "FETCHED", instance.fetched)
        print(end, "BEFORE", before)
        print(end, "SAME", before == after)


def test_router(tmp_path, whitelist, monkeypatch):
    import router

    print("POST_ROUTES translate", sorted(p for p in router.POST_ROUTES if "translate" in p))
    path = tmp_path / "r.db"
    store = _subtitles_db(path)
    enqueue_translate_job(store, VIDEO_ID, HOST, "en", 50, NOW - 2000, wanted_at=LEASE)
    store.close()
    _beat(path, 0)
    for headers in ({"X-Bridge-Token": "tok"}, {}):
        request = HandlerRequest(BODY)
        request.path = "/internal/translate"
        request.headers.update(headers)
        request._get_client_ip = lambda: "127.0.0.1"
        server = _server(whitelist, path)
        server.bridge_token = "tok"
        request.server = server
        module = _route(_instance(False), monkeypatch)
        router.route_post(request)
        print("ROUTE", headers, request.responses, _dump(path)[0]["wanted_at"])
    request = HandlerRequest(BODY)
    request.path = "/internal/translate/cancel"
    request.headers.update({"X-Bridge-Token": "tok"})
    request._get_client_ip = lambda: "127.0.0.1"
    request.server = _server(whitelist, path)
    request.server.bridge_token = "tok"
    router.route_post(request)
    print("CANCEL ROUTE TODAY", request.responses)
