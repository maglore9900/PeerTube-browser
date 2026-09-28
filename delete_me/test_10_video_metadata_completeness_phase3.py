"""`/api/video` writes the stored video only when the detail fetch returns a non-empty JSON object, and on success stores and answers one source-over-DB value set.

- A failed detail fetch (`urlopen` raising `URLError`, a non-200 status, a body that is not JSON, a body that is not UTF-8, a JSON list, an empty object `{}`) leaves the whole videos row, every channels row and `instances.last_error*` as they were, and answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count.
- A full source payload writes title, description, stats, tags, category, language code, nsfw, duration, absolute thumbnail URL and the channel, moves `last_checked_at` forward, clears `instances.last_error*`, leaves every other column as seeded, keeps the 18 original response keys and answers the same values (category and language as labels, tags as a list, nsfw as a bool).
- A payload that omits a field, or sends it null, blank or with a null language id, keeps the stored value in the row and in the response, and leaves the channels row as it was; `tags: []` stores "[]" and answers `[]`.
- A failed channel-detail fetch writes the source channel slug and display name and keeps the stored follower count, in the channels row and in the response.
- A non-empty JSON object body counts as a success, even one carrying only some fields.
- A source change between two requests is in the second response and in the row.

The DB is built by `sync-whitelist.py`'s own schema helpers; `respond_json` and `urlopen` are replaced on `handlers.video`, so the real `fetch_instance_json` parses every body and the instance is never contacted.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

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
OLD_CHECKED_AT = 1000
VIDEO_PATH = "/api/v1/videos/v1"
VIDEO_URL = f"https://{HOST}{VIDEO_PATH}"
CHANNEL_PATH = "/api/v1/video-channels/newslug"
OLD_THUMBNAIL = "https://peer.example/old.jpg"
NEW_THUMBNAIL = "https://peer.example/static/thumbnails/new.jpg"
SOURCE = {"name": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": {"id": 15, "label": "Science & Technology"}, "language": {"id": "en", "label": "English"}, "nsfw": True, "duration": 321, "thumbnailPath": "/static/thumbnails/new.jpg", "channel": {"name": "newslug", "displayName": "New Chan"}}
# The keys /api/video answered before this build; the probe printed exactly these 18.
ORIGINAL_KEYS = {"videoUuid", "title", "description", "channelName", "channelUrl", "channelAvatarUrl", "subscribersCount", "instanceName", "instanceUrl", "accountName", "accountUrl", "accountAvatarUrl", "embedUrl", "originalUrl", "views", "likes", "dislikes", "publishedAt"}
STORED_ANSWER = {"title": "Old title", "description": "Old desc", "views": 1, "likes": 1, "dislikes": 0, "tags": ["old"], "category": "Music", "language": "French", "duration": 10, "thumbnailUrl": OLD_THUMBNAIL, "channelName": "Old Chan", "subscribersCount": 3}


def _load_job(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, JOBS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path):
    sync_job = _load_job("sync_whitelist_video_refresh", "sync-whitelist.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 5, 'video')", (HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count) VALUES ('7', ?, 'oldslug', 'Old Chan', 3)", (HOST,))
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, title, description, tags_json, category, language, nsfw, duration, thumbnail_url, views, likes, dislikes, published_at, last_checked_at) VALUES ('v1', 'uuid-1', ?, '7', 'Old Chan', 'Old title', 'Old desc', '[\"old\"]', 'Music', 'fr', 0, 10, ?, 1, 1, 0, 1600000000000, ?)", (HOST, OLD_THUMBNAIL, OLD_CHECKED_AT))
    conn.commit()
    try:
        yield SimpleNamespace(db=conn, db_lock=threading.Lock(), video_error_threshold=0, popularity_like_weight=2.0)
    finally:
        conn.close()


@pytest.fixture
def responses(monkeypatch):
    captured = []
    monkeypatch.setattr(video, "respond_json", lambda handler, status, body: captured.append((status, body)))
    return captured


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._body


def _serve(monkeypatch, bodies: dict) -> list[tuple[str, object]]:
    """Replace `urlopen` one level below `fetch_instance_json`, keyed by URL path, and return (url, timeout) per call.

    An unlisted path raises `URLError`, an exception is raised, a `_FakeResponse` is returned as is, bytes are served raw and anything else is served as JSON.
    """
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append((req.full_url, timeout))
        body = bodies.get(req.full_url.removeprefix(f"https://{HOST}"), URLError("no route"))
        if isinstance(body, Exception):
            raise body
        if isinstance(body, _FakeResponse):
            return body
        return _FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(video, "urlopen", fake_urlopen)
    return calls


def _video(conn) -> dict:
    return dict(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone())


def _instance_errors(conn) -> tuple:
    return tuple(conn.execute("SELECT last_error, last_error_at, last_error_source FROM instances WHERE host = ?", (HOST,)).fetchone())


def _snapshot(conn) -> tuple:
    return (tuple(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone()), tuple(tuple(row) for row in conn.execute("SELECT * FROM channels ORDER BY channel_id")), _instance_errors(conn))


def _only_body(responses) -> dict:
    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    return body


def _answered(body: dict, expected: dict) -> dict:
    return {key: body.get(key, "MISSING") for key in expected}


# The 404 carries a `{}` body, which would be a success if the status were ignored.
@pytest.mark.parametrize("outcome", [URLError("down"), _FakeResponse(b"{}", status=404), b"<html>", b"\xff\xfe", b"[1, 2]", b"{}"], ids=["urlopen-urlerror", "status-404", "not-json", "bad-utf8", "json-list", "empty-object"])
def test_fetch_failure_leaves_db_untouched(server, monkeypatch, responses, outcome):
    calls = _serve(monkeypatch, {VIDEO_PATH: outcome})
    before = _snapshot(server.db)
    assert before[2] == ("boom", 5, "video"), "the seeded instance error is what the comparison must preserve"

    video.handle_video_request(None, server, PARAMS)

    # The detail fetch was really attempted, so an untouched DB is not just a handler that never fetched.
    assert calls[:1] == [(VIDEO_URL, 8)]
    body = _only_body(responses)
    assert _snapshot(server.db) == before  # C1
    assert _answered(body, STORED_ANSWER) == STORED_ANSWER  # C1
    assert body.get("nsfw", "MISSING") is False  # C1


def test_success_refreshes_row_and_response(server, monkeypatch, responses):
    before = _video(server.db)
    _serve(monkeypatch, {VIDEO_PATH: SOURCE, CHANNEL_PATH: {"followersCount": 9}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    after = _video(server.db)
    # tags_json is compared parsed: the JSON spacing and escaping are not part of the contract.
    assert json.loads(after.pop("tags_json")) == ["alpha", "beta"]  # C2
    before.pop("tags_json")
    assert after["last_checked_at"] > OLD_CHECKED_AT  # C2
    # popularity and last_checked_at are derived at write time; every other column is either a source value or the untouched seed.
    assert after == {**before, "title": "New title", "description": "New desc", "channel_name": "New Chan", "views": 50, "likes": 5, "dislikes": 1, "category": "Science & Technology", "language": "en", "nsfw": 1, "duration": 321, "thumbnail_url": NEW_THUMBNAIL, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}  # C2
    assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 9)  # C2
    assert _instance_errors(server.db) == (None, None, None)  # C2
    assert ORIGINAL_KEYS <= body.keys()  # C2
    expected = {"title": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": "Science & Technology", "language": "English", "duration": 321, "thumbnailUrl": NEW_THUMBNAIL, "channelName": "New Chan", "subscribersCount": 9}
    assert _answered(body, expected) == expected  # C2
    assert body.get("nsfw", "MISSING") is True  # C2


@pytest.mark.parametrize(
    "payload",
    [
        {"views": 77},
        # Null, blank and a null language id are all "absent" under the mapping rules, not values to store.
        {"views": 77, "name": "  ", "description": "", "tags": None, "category": None, "language": {"id": None, "label": "Unknown"}, "nsfw": None, "duration": None, "thumbnailPath": None},
    ],
    ids=["absent", "null-or-blank"],
)
def test_partial_payload_keeps_tags_and_category(server, monkeypatch, responses, payload):
    before = _video(server.db)
    channels_before = _snapshot(server.db)[1]
    _serve(monkeypatch, {VIDEO_PATH: payload})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    after = _video(server.db)
    assert after["last_checked_at"] > OLD_CHECKED_AT, "the refresh did not write the row"
    assert after == {**before, "views": 77, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}  # C2
    assert _snapshot(server.db)[1] == channels_before  # C2
    expected = {**STORED_ANSWER, "views": 77}
    assert _answered(body, expected) == expected  # C2
    assert body.get("nsfw", "MISSING") is False  # C2


def test_failed_channel_fetch_keeps_stored_followers(server, monkeypatch, responses):
    calls = _serve(monkeypatch, {VIDEO_PATH: SOURCE})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    # The channel-detail fetch was attempted and failed, so followers are absent while slug and display name are present.
    assert [url for url, _ in calls] == [VIDEO_URL, f"https://{HOST}{CHANNEL_PATH}"]
    assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 3)  # C2
    assert (body.get("channelName"), body.get("subscribersCount", "MISSING")) == ("New Chan", 3)  # C2


def test_empty_tag_list_propagates(server, monkeypatch, responses):
    _serve(monkeypatch, {VIDEO_PATH: {"tags": []}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    assert _video(server.db)["tags_json"] == "[]"  # C2
    assert body.get("tags", "MISSING") == []  # C2


def test_object_body_counts_as_success(server, monkeypatch, responses):
    title, duration = "Fresh title", 42
    calls = _serve(monkeypatch, {VIDEO_PATH: b'{"name": "Fresh title", "duration": 42}'})

    video.handle_video_request(None, server, PARAMS)

    reply = _only_body(responses)
    assert calls[:1] == [(VIDEO_URL, 8)]
    stored = _video(server.db)
    assert (stored["title"], stored["duration"], stored["last_checked_at"] > OLD_CHECKED_AT) == (title, duration, True)  # C2
    assert _instance_errors(server.db) == (None, None, None)  # C2
    assert (reply.get("title"), reply.get("duration", "MISSING")) == (title, duration)  # C2


def test_second_request_reflects_source_change(server, monkeypatch, responses):
    bodies = {VIDEO_PATH: SOURCE, CHANNEL_PATH: {"followersCount": 9}}
    _serve(monkeypatch, bodies)

    video.handle_video_request(None, server, PARAMS)
    bodies[VIDEO_PATH] = {**SOURCE, "name": "Renamed", "tags": ["gamma"]}
    video.handle_video_request(None, server, PARAMS)

    assert [status for status, _ in responses] == [200, 200]
    assert [(body.get("title"), body.get("tags", "MISSING")) for _, body in responses] == [("New title", ["alpha", "beta"]), ("Renamed", ["gamma"])]  # C2
    stored = _video(server.db)
    assert (stored["title"], json.loads(stored["tags_json"])) == ("Renamed", ["gamma"])  # C2
