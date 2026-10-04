"""Probe for plan 50 phase 2: what the body reader, normalize_host, the cap config and a store with its subtitles table moved away actually do."""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_internal_translate import HandlerRequest, _subtitles_db  # noqa: E402


def test_probe(tmp_path):
    from data.moderation import normalize_host
    from data.subtitles import enqueue_translate_job, fetch_translate_heartbeat, write_translate_heartbeat
    from http_utils import read_json_body
    import server_config

    print("CAP", server_config.SUBTITLE_QUEUE_CAP)
    for raw in ["not a host!", "a b", "-", "..", "http://x/", "*", "peer.example:443", "PEER.Example."]:
        print("normalize_host", repr(raw), "->", repr(normalize_host(raw)))
    for raw in [b"{not json", b"[1, 2]", b"", b"null", b'"x"']:
        request = HandlerRequest({})
        request.rfile = io.BytesIO(raw)
        request.headers = {"content-length": str(len(raw))}
        try:
            print("read_json_body", raw, "->", repr(read_json_body(request)))
        except Exception as exc:  # noqa: BLE001
            print("read_json_body", raw, "raised", type(exc).__name__, repr(str(exc)))
    path = tmp_path / "subtitles.db"
    server_conn = _subtitles_db(path)
    other = _subtitles_db(path)
    write_translate_heartbeat(other, 1000, 1)
    other.execute("ALTER TABLE subtitles RENAME TO subtitles_away")
    other.commit()
    print("heartbeat after rename", fetch_translate_heartbeat(server_conn))
    try:
        print("enqueue after rename ->", enqueue_translate_job(server_conn, "v", "h", "en", 50, 1))
    except sqlite3.Error as exc:
        print("enqueue after rename raised", type(exc).__name__, repr(str(exc)), "in_transaction", server_conn.in_transaction)
    other.execute("ALTER TABLE subtitles_away RENAME TO subtitles")
    other.commit()
    print("enqueue after restore ->", enqueue_translate_job(server_conn, "v", "h", "en", 50, 1))
    print("rows", [tuple(r) for r in other.execute("SELECT video_id, instance_domain, target_language, state, source, fetched_at, queued_at, attempts FROM subtitles")])
    print("columns", [r[1] for r in other.execute("PRAGMA table_info(subtitles)")])
