"""`/api/video` answers the stored category and language as PeerTube default display labels, and leaves the stored id and code as they were.

- With the instance fetch failing, so the answer comes from the DB: a stored "15" answers "Science & Technology", "18" answers "Food", and an unknown id ("99", "19") or a text category ("Music") answers as stored.
- A stored "en" answers "English", "zh-Hans" answers "Simplified Chinese", and an unknown code ("xx") answers "xx".
- A successful refresh whose source carries only a category id (15) and a language code ("en") writes the row, keeps "15" and "en" stored, and answers "Science & Technology" and "English".

The DB is built by `sync-whitelist.py`'s own schema helpers; `respond_json` and `fetch_instance_json` are replaced on `handlers.video`, and the instance is never contacted.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
for path in (SERVER_DIR, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from handlers import video  # noqa: E402

HOST = "peer.example"
PARAMS = {"id": ["v1"], "host": [HOST]}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path):
    sync_job = _load_job("sync_whitelist_video_labels", "sync-whitelist.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 5, 'video')", (HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count) VALUES ('7', ?, 'oldslug', 'Old Chan', 3)", (HOST,))
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, title, category, language, published_at, last_checked_at) VALUES ('v1', 'uuid-1', ?, '7', 'Old Chan', 'Old title', 'Music', 'fr', 1600000000000, 1000)", (HOST,))
    conn.commit()
    try:
        yield SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("category", "language", "expected_category", "expected_language"),
    [
        ("15", "en", "Science & Technology", "English"),
        ("99", "zh-Hans", "99", "Simplified Chinese"),
        ("Music", "xx", "Music", "xx"),
        # The ends of PeerTube's 1-18 default range: the last id resolves, the next one is unknown.
        ("18", "en", "Food", "English"),
        ("19", "xx", "19", "xx"),
    ],
    ids=["id-and-code", "unknown-id", "text-and-unknown-code", "last-id", "past-last-id"],
)
def test_response_labels(server, monkeypatch, category, language, expected_category, expected_language):
    server.db.execute("UPDATE videos SET category = ?, language = ? WHERE video_id = 'v1'", (category, language))
    server.db.commit()
    responses = []
    monkeypatch.setattr(video, "respond_json", lambda handler, status, body: responses.append((status, body)))
    monkeypatch.setattr(video, "fetch_instance_json", lambda host, path: None)

    video.handle_video_request(None, server, PARAMS)

    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    assert body.get("category", "MISSING") == expected_category  # C1
    assert body.get("language", "MISSING") == expected_language  # C2


def test_refresh_stores_raw_codes(server, monkeypatch):
    server.db.execute("UPDATE videos SET category = '15', language = 'en' WHERE video_id = 'v1'")
    server.db.commit()
    responses = []
    monkeypatch.setattr(video, "respond_json", lambda handler, status, body: responses.append((status, body)))
    # An id-only category and a code-only language are what a source without labels sends; both must stay raw in the row.
    source = {"name": "New title", "category": {"id": 15}, "language": {"id": "en"}}
    monkeypatch.setattr(video, "fetch_instance_json", lambda host, path: source if path == "/api/v1/videos/v1" else None)

    video.handle_video_request(None, server, PARAMS)

    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    # Labels are a display concern only: the row keeps the id and code, which FTS and embeddings read.
    stored = server.db.execute("SELECT title, last_checked_at, category, language FROM videos WHERE video_id = 'v1'").fetchone()
    assert (stored["title"], stored["last_checked_at"] > 1000) == ("New title", True), "the refresh did not write the row"
    assert (stored["category"], stored["language"]) == ("15", "en")  # C1 C2
    assert body.get("category", "MISSING") == "Science & Technology"  # C1
    assert body.get("language", "MISSING") == "English"  # C2
