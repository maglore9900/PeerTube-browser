"""Probe for plan 50 phase 2 checkpoint: observe, through the checkpoint's own helpers, the state route's answer to each refused body, the row the store's enqueue leaves at NOW, its answer at the cap, the freshness boundary under the pinned clock, and the seeded rows."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_50_translate_generation_in_page_phase2 as cp  # noqa: E402
from test_internal_translate import whitelist  # noqa: E402,F401


def test_probe(tmp_path, whitelist, monkeypatch):
    from data.subtitles import enqueue_translate_job, fetch_translate_heartbeat

    print("CAP", cp.SUBTITLE_QUEUE_CAP)
    module = cp._route(monkeypatch)
    for name, (body, answer) in cp.REFUSED.items():
        path = tmp_path / f"refused-{len(name)}-{abs(hash(name))}.db"
        cp._beat(path, 0)
        got = cp._state(module, cp._server(whitelist, path), body)
        print("state route", name, got, "matches literal" if got == answer else "DIFFERS from literal", "rows", cp._rows(path))
    path = tmp_path / "denied.db"
    cp._beat(path, 0)
    cp._set_denied(whitelist, True)
    print("state route denied", cp._state(module, cp._server(whitelist, path), {"id": cp.DENIED_VIDEO[1], "host": cp.DENIED_HOST}))
    cp._set_denied(whitelist, False)
    print("state route denied inactive", cp._state(module, cp._server(whitelist, path), {"id": cp.DENIED_VIDEO[1], "host": cp.DENIED_HOST}))
    for age in [None, 15_001, -1, 0, 15_000]:
        path = tmp_path / f"beat-{age}.db"
        cp._beat(path, age)
        server = cp._server(whitelist, path)
        print("beat age", age, "available", module._generation_available(server.subtitles_db), "state route", cp._state(module, server, cp.BODY))
    path = tmp_path / "row.db"
    store = cp._subtitles_db(path)
    print("enqueue new", enqueue_translate_job(store, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    print("enqueue again", enqueue_translate_job(store, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    store.close()
    print("row", cp._rows(path), "== QUEUED_ROW", cp._rows(path) == [cp.QUEUED_ROW])
    path = tmp_path / "cap.db"
    store = cp._subtitles_db(path)
    for index in range(cp.SUBTITLE_QUEUE_CAP):
        enqueue_translate_job(store, f"q-{index:03d}", cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW - 5000)
    print("enqueue at cap", enqueue_translate_job(store, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    store.close()
    cp._write(path, "DELETE FROM subtitles WHERE video_id = 'q-000'")
    store = cp._subtitles_db(path)
    print("enqueue one fewer", enqueue_translate_job(store, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    store.close()
    for state in ["queued", "running", "ready", "failed", "already_english"]:
        path = tmp_path / f"seed-{state}.db"
        cp._seed(path, state)
        cp._beat(path, 0)
        print("seeded", state, cp._rows(path), "state route", cp._state(module, cp._server(whitelist, path), cp.BODY))
    path = tmp_path / "rename.db"
    cp._beat(path, 0)
    server = cp._server(whitelist, path)
    cp._write(path, "ALTER TABLE subtitles RENAME TO subtitles_away")
    print("after rename available", module._generation_available(server.subtitles_db), "beat", fetch_translate_heartbeat(server.subtitles_db))
    try:
        print("enqueue after rename", enqueue_translate_job(server.subtitles_db, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    except sqlite3.Error as exc:
        print("enqueue after rename raised", type(exc).__name__, str(exc), "in_transaction", server.subtitles_db.in_transaction)
    cp._write(path, "ALTER TABLE subtitles_away RENAME TO subtitles")
    print("after restore rows", cp._rows(path), "enqueue", enqueue_translate_job(server.subtitles_db, cp.VIDEO_ID, cp.HOST, "en", cp.SUBTITLE_QUEUE_CAP, cp.NOW))
    raise AssertionError("probe: read the printed output")
