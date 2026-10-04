import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import AFTERS, BODY, NOW, PEER_VIDEO, HOST, RUNNING, _beat, _claimed, _enqueue, _rows, _seed, _server, _state, _subtitles_db, _whitelist, _write  # noqa: E402
from server_config import SUBTITLE_QUEUE_CAP  # noqa: E402
from data.subtitles import enqueue_translate_job, store_running_cues, write_translate_heartbeat  # noqa: E402


def _mod(monkeypatch):
    module = importlib.import_module("handlers.internal_translate")
    monkeypatch.setattr(module, "now_ms", lambda: NOW)
    return module


def test_probe(tmp_path, monkeypatch):
    m = _mod(monkeypatch)
    wl = _whitelist(tmp_path / "w.db")
    server = _server(wl, tmp_path / "s.db")
    for body in (b"{not json", b"[1, 2]", {"host": HOST}, {"id": "u-1", "host": "  "}, {"id": 1, "host": HOST}, {"id": "u-1", "host": "not a host!"}, {**BODY, "after": True}, {**BODY, "after": -1}, {**BODY, "after": "1"}, {**BODY, "after": 1.0}, {**BODY, "after": None}):
        print("STATE", body, _state(m, server, body), "ENQ", _enqueue(m, server, body))
    print("SAFTER", AFTERS)
    sp = tmp_path / "r.db"
    store = _subtitles_db(sp)
    started = _claimed(store)
    print("RUNNING stored", store_running_cues(store, "v-1", HOST, "en", started, RUNNING, "fr"))
    write_translate_heartbeat(store, NOW, 1)
    rs = _server(wl, sp)
    for after in (1, 3, 5):
        print("AFTER", after, _state(m, rs, {**BODY, "after": after}))
    print("ENQ existing running", _enqueue(m, rs, BODY))
    for age in (None, 15_001, -1):
        p = tmp_path / f"n{age}.db"
        _beat(p, age)
        print("ENQ none", age, _enqueue(m, _server(wl, p), BODY), _rows(p))
    p = tmp_path / "busy.db"
    st = _subtitles_db(p)
    for i in range(SUBTITLE_QUEUE_CAP):
        enqueue_translate_job(st, f"q-{i:03d}", HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 5000)
    st.close()
    _beat(p, 0)
    bs = _server(wl, p)
    print("ENQ busy", SUBTITLE_QUEUE_CAP, _enqueue(m, bs, BODY))
    _write(p, "DELETE FROM subtitles WHERE video_id = 'q-000'")
    print("ENQ cap-1", _enqueue(m, bs, BODY))
    p = tmp_path / "e.db"
    _beat(p, 0)
    es = _server(wl, p)
    _write(p, "ALTER TABLE subtitles RENAME TO subtitles_away")
    print("ENQ 503", _enqueue(m, es, BODY))
    for state in ("queued", "running", "ready", "failed", "already_english"):
        p = tmp_path / f"x{state}.db"
        st = _subtitles_db(p)
        _seed(st, state)
        st.close()
        _beat(p, 0)
        print("ENQ state", state, _enqueue(m, _server(wl, p), BODY))
    assert False
