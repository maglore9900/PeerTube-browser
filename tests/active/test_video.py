"""`/api/video` and `/api/video/refresh` (engine/server/api/handlers/video.py): the live instance values merged over the stored row, written back only when the instance's video detail call answered a non-empty JSON object, with stored category ids and language codes answered as PeerTube display labels.

Labels (in-process, instance fetch stubbed):

- With the instance fetch failing, so the answer comes from the DB: a stored "15" answers "Science & Technology", "18" answers "Food", and an unknown id ("99", "19") or a text category ("Music") answers as stored.
- A stored "en" answers "English", "zh-Hans" answers "Simplified Chinese", and an unknown code ("xx") answers "xx".
- A successful refresh whose source carries only a category id (15) and a language code ("en") writes the row, keeps "15" and "en" stored, and answers "Science & Technology" and "English".

Write guard and merge (in-process, the real `fetch_instance_json` and `data.source_fetch` adapter over a real urllib opener whose https open step is scripted):

- A failed detail fetch (the open step raising `URLError`, a non-200 status, a body that is not JSON, a body that is not UTF-8, a JSON list, an empty object `{}`) leaves the whole videos row, every channels row and `instances.last_error*` as they were, and answers 200 with the stored title, description, views, likes, dislikes, tags, category, language, nsfw, duration, thumbnail, channel name and subscriber count.
- `fetch_instance_json` answers None, having opened only the detail URL under a 4 s socket timeout, for a detail redirected off the instance (the target serves the full payload), a declared Content-Length of 2,000,001, and the payload padded to 2,000,001 bytes; served straight, by Content-Length 2,000,000 or padded to exactly 2,000,000 bytes, it answers the payload.
- A full source payload writes title, description, stats, tags, category, language code, nsfw, duration, absolute thumbnail URL and the channel, moves `last_checked_at` forward, clears `instances.last_error*`, leaves every other column as seeded, keeps the 18 original response keys and answers the same values (category and language as labels, tags as a list, nsfw as a bool).
- A payload that omits a field, or sends it null, blank or with a null language id, keeps the stored value in the row and in the response, and leaves the channels row as it was; `tags: []` stores "[]" and answers `[]`.
- A failed channel-detail fetch writes the source channel slug and display name and keeps the stored follower count, in the channels row and in the response.
- A non-empty JSON object body counts as a success, even one carrying only some fields.
- A source change between two requests is in the second response and in the row.

Refresh answer (Engine child over HTTP):

- With the instance answering the video detail and the channel, the refresh answers 200 with `/api/video`'s eighteen keys plus the taxonomy and media keys: the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar; the channel URL built from the instance's channel slug and the host, the original URL from the row's uuid and the host; and uuid, channel avatar, account name and URL, embed and published date from the row. It asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`. Requested by the row's video id rather than its uuid, it answers the same.
- With the detail omitting `description` and `views`, carrying `likes: 0`, and the channel call answering nothing, the refresh answers the row's description, views, channel display name and follower count beside the instance's title, dislikes and `likes` 0; with the detail omitting title, likes and dislikes instead, it answers the row's title, likes and dislikes beside the instance's description, views, channel display name and follower count.
- A refresh with no id answers 400 `Missing video id`, and one for an id not in the DB answers 404 `Video not found`, neither calling the instance.
- `/api/video` against the same answering instance still answers the instance's values.

Refresh persistence (Engine child over HTTP):

- With the detail and channel calls answering, the video row holds the instance's title, description, channel display name, counts, tags, category and nsfw, with `last_checked_at` inside the run's wall-clock window and a nonzero `popularity`; the channel row holds the instance's slug, display name and the channel call's follower count; the instance row's `last_error*` are NULL; every other column and the other video's row are unchanged. With the channel call answering nothing, the rows are written the same way, but the channel display name and follower count keep the DB's values.
- With `statement_timeout_seconds` at 0.2 and each instance call taking 0.5 s, so the request's own deadline has passed before the write, the same rows are written. The fixture DB carries an extra AFTER UPDATE trigger on `videos` that runs well past the progress handler's 10,000-instruction check; without it the real UPDATE never reaches that check, and an expired deadline would go unnoticed.
- With the detail call answering `None`, `{}`, a JSON list, or failing with `URLError` at the adapter's opener, the refresh answers 200 with the DB-only values, and every column of the `videos`, `channels` and `instances` rows is the same before and after.
- With the detail call blocking for 5 s, a `/videos/v1/similar` GET sent while the refresh is inside that call answers 200 with its ANN neighbour in under 1 s, and the instance stub has by then been called only for the refresh's `/api/v1/videos/{uuid}`.

The DBs are built by `sync-whitelist.py`'s own schema helpers. In-process cases replace `respond_json` and either `fetch_instance_json` on `handlers.video` or `build_opener` on `data.source_fetch`, so the instance is never contacted. Engine-child cases run under the Engine's interpreter: a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, with `handlers.video.fetch_instance_json` replaced by a stub that records each call and answers from the case's path map, or `data.source_fetch.build_opener` by one whose opener raises `URLError`; for the similars case the child also builds a flat faiss index over the DB's embeddings and the Engine's own recommendation strategy.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import threading
import time
from array import array
from http.client import HTTPMessage
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import HTTPSHandler, build_opener

import pytest
from conftest import ENGINE_PY, ROOT

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
# The Engine dirs go on sys.path after conftest's import: both trees hold a `server` module.
for _path in (SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from handlers import video  # noqa: E402
from data import source_fetch  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402

# In-process cases: one video v1 on PEER_HOST.
PEER_HOST = "peer.example"
PARAMS = {"id": ["v1"], "host": [PEER_HOST]}
OLD_CHECKED_AT = 1000
VIDEO_PATH = "/api/v1/videos/v1"
VIDEO_URL = f"https://{PEER_HOST}{VIDEO_PATH}"
NEWSLUG_PATH = "/api/v1/video-channels/newslug"
OLD_THUMBNAIL = "https://peer.example/old.jpg"
NEW_THUMBNAIL = "https://peer.example/static/thumbnails/new.jpg"
SOURCE = {"name": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": {"id": 15, "label": "Science & Technology"}, "language": {"id": "en", "label": "English"}, "nsfw": True, "duration": 321, "thumbnailPath": "/static/thumbnails/new.jpg", "channel": {"name": "newslug", "displayName": "New Chan"}}
# The 18 keys /api/video answered before the taxonomy and media keys were added.
ORIGINAL_KEYS = {"videoUuid", "title", "description", "channelName", "channelUrl", "channelAvatarUrl", "subscribersCount", "instanceName", "instanceUrl", "accountName", "accountUrl", "accountAvatarUrl", "embedUrl", "originalUrl", "views", "likes", "dislikes", "publishedAt"}
STORED_ANSWER = {"title": "Old title", "description": "Old desc", "views": 1, "likes": 1, "dislikes": 0, "tags": ["old"], "category": "Music", "language": "French", "duration": 10, "thumbnailUrl": OLD_THUMBNAIL, "channelName": "Old Chan", "subscribersCount": 3}

# Engine-child cases: video v1 (uuid-v1) on HOST, and its ANN neighbour v2.
HOST = "tube.example"
UUID = "uuid-v1"
REFRESH = f"/api/video/refresh?id={UUID}&host={HOST}"
SIMILAR = f"/videos/v1/similar?host={HOST}"
DETAIL_PATH = f"/api/v1/videos/{UUID}"
CHANNEL_PATH = "/api/v1/video-channels/live_slug"
# Every value differs from the row's, so an answer or row built from the seed cannot pass for the instance's.
DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
ANSWERING = {DETAIL_PATH: DETAIL, CHANNEL_PATH: {"displayName": "Live Chan Detail", "followersCount": 77}}
# No description or views, likes 0 (supplied, and falsy), a channel slug but no channel display name or followers; the channel call is not in the map, so it answers None.
PARTIAL = {DETAIL_PATH: {"name": "Live title B", "likes": 0, "dislikes": 3, "channel": {"name": "live_slug"}}}
# The complement of PARTIAL: no title, likes or dislikes, but its own description, views, channel display name and followers; the channel call again answers None.
OMITTING = {DETAIL_PATH: {"description": "Live description B", "views": 900, "channel": {"name": "live_slug", "displayName": "Live Chan B", "followersCount": 60}}}
# The row requested by its video_id "v1" rather than its uuid; the detail answers under either id, so the answer turns only on where uuid, embed and original URL come from.
BY_VIDEO_ID = {**ANSWERING, "/api/v1/videos/v1": DETAIL}
# The answer to a refresh over ANSWERING: accountName/accountUrl, channelAvatarUrl, embedUrl, publishedAt and videoUuid come from the row.
LIVE = {
    "videoUuid": UUID,
    "title": "Live title",
    "description": "Live description",
    "channelName": "Live Chan",
    "channelUrl": f"https://{HOST}/video-channels/live_slug",
    "channelAvatarUrl": f"https://{HOST}/lazy-static/avatars/db.png",
    "subscribersCount": 77,
    "instanceName": HOST,
    "instanceUrl": f"https://{HOST}",
    "accountName": "DB Account",
    "accountUrl": f"https://{HOST}/accounts/db",
    "accountAvatarUrl": f"https://{HOST}/lazy-static/avatars/live.png",
    "embedUrl": f"https://{HOST}/videos/embed/{UUID}",
    "originalUrl": f"https://{HOST}/videos/watch/{UUID}",
    "views": 1000,
    "likes": 50,
    "dislikes": 3,
    "publishedAt": 1_700_000_000_000,
    # The taxonomy and media keys: DETAIL's tags, category and nsfw; no language, duration or thumbnail in DETAIL or the row.
    "category": "Music",
    "language": "",
    "tags": ["live"],
    "nsfw": False,
    "duration": None,
    "thumbnailUrl": "",
}
# The taxonomy keys answered from the row, for a detail that omits tags and category.
ROW_TAXONOMY = {"category": "DB cat", "tags": ["db-tag"]}
# The detail names the channel slug but no display name or followers, and the channel call is not in the map, so it answers None.
CHANNEL_FAILED = {DETAIL_PATH: {**DETAIL, "channel": {"name": "live_slug"}}}
# The columns an answered refresh writes, over ANSWERING and over CHANNEL_FAILED.
LIVE_VIDEO = {"title": "Live title", "description": "Live description", "channel_name": "Live Chan", "views": 1000, "likes": 50, "dislikes": 3, "tags_json": '["live"]', "category": "Music", "nsfw": 0}
LIVE_CHANNEL = {"channel_name": "live_slug", "display_name": "Live Chan", "followers_count": 77}
DB_CHANNEL_VIDEO = {**LIVE_VIDEO, "channel_name": "DB Chan"}
DB_CHANNEL_CHANNEL = {"channel_name": "live_slug", "display_name": "DB Chan", "followers_count": 5}
CLEARED_INSTANCE = {"last_error": None, "last_error_at": None, "last_error_source": None}
# The refresh's answer when the instance supplied nothing: every field from the seeded row.
DB_ONLY = {
    "videoUuid": UUID,
    "title": "DB title",
    "description": "DB description",
    "channelName": "DB Chan",
    "channelUrl": f"https://{HOST}/video-channels/db_slug",
    "channelAvatarUrl": f"https://{HOST}/lazy-static/avatars/db.png",
    "subscribersCount": 5,
    "instanceName": HOST,
    "instanceUrl": f"https://{HOST}",
    "accountName": "DB Account",
    "accountUrl": f"https://{HOST}/accounts/db",
    "accountAvatarUrl": "",
    "embedUrl": f"https://{HOST}/videos/embed/{UUID}",
    "originalUrl": f"https://{HOST}/videos/watch/{UUID}",
    "views": 10,
    "likes": 2,
    "dislikes": 1,
    "publishedAt": 1_700_000_000_000,
    "category": "DB cat",
    "language": "",
    "tags": ["db-tag"],
    "nsfw": False,
    "duration": None,
    "thumbnailUrl": "",
}

# Starts each case's server on its own DB, runs one GET through the real handler with `fetch_instance_json` stubbed, and reports the status, the parsed body and every instance call.
ANSWER_CHILD = r'''
import http.client, inspect, json, sys, threading
from pathlib import Path
from unittest.mock import patch
import server
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler
reports = []
for db_path, path, answers in json.loads(sys.argv[1]):
    conn = connect_db(Path(db_path))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    calls = []
    def stub(host, api_path):
        calls.append([host, api_path])
        return answers.get(api_path)
    try:
        with patch.object(video, "fetch_instance_json", stub):
            client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            client.request("GET", path)
            resp = client.getresponse()
            body = json.loads(resp.read() or b"null")
            client.close()
        reports.append({"status": resp.status, "body": body, "calls": calls})
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''

# Starts each case's server on its own DB, sends the refresh (and, for a similars case, the similars GET while the refresh sits in the instance call), and reports statuses, bodies, timings and every instance call.
PERSIST_CHILD = r'''
import http.client, inspect, json, sys, threading, time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import faiss, numpy as np
import server
from data import source_fetch
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler

def get(port, path):
    started = time.monotonic()
    try:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        client.request("GET", path)
        resp = client.getresponse()
        raw = resp.read()
        client.close()
        return {"status": resp.status, "body": json.loads(raw or b"null"), "elapsed": time.monotonic() - started}
    except Exception as exc:
        return {"status": None, "body": repr(exc), "elapsed": time.monotonic() - started}

def similars_stack(conn):
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    rows = conn.execute("SELECT ann_id, embedding FROM video_embeddings").fetchall()
    index.add_with_ids(np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]), np.array([r["ann_id"] for r in rows], dtype=np.int64))
    deps = server.RecommendationBuilderDeps(fetch_recent_likes=server.fetch_recent_likes_request, fetch_seed_embedding=server.fetch_seed_embedding, fetch_seed_embeddings_for_likes=server.fetch_seed_embeddings_for_likes, get_similar_candidates=server.get_similar_candidates, like_key=server.like_key, fetch_embeddings_by_ids=server.fetch_embeddings_by_ids, fetch_random_rows=server.fetch_random_rows, fetch_random_rows_from_cache=server.fetch_random_rows_from_cache, fetch_recent_videos=server.fetch_recent_videos, fetch_popular_videos=server.fetch_popular_videos, fetch_dislike_centroids=server.fetch_request_dislike_centroids, fetch_excluded_keys=server.fetch_request_excluded_keys)
    settings = server.RecommendationBuilderSettings(max_likes=server.MAX_LIKES, max_likes_for_recs=server.MAX_LIKES_FOR_RECS, similar_per_like=server.SIMILAR_PER_LIKE, default_similar_from_likes_source=server.DEFAULT_USE_SIMILARITY_CACHE, video_error_threshold=server.VIDEO_ERROR_THRESHOLD, fresh_pool_size=server.DEFAULT_FRESH_POOL_SIZE, dislike_similarity_floor=server.DISLIKE_SIMILARITY_FLOOR)
    strategy = server.build_recommendation_strategy(server.RECOMMENDATION_PIPELINE, deps, settings)
    strategy.settings = settings
    return {"index": index, "embeddings_dim": 4, "embeddings_count": len(rows), "default_limit": 8, "normalize_queries": True, "similarity_search_limit": 0, "similarity_max_per_author": 0, "similarity_exclude_source_author": False, "similarity_require_full_cache": False, "recommendation_strategy": strategy}

reports = []
for case in json.loads(sys.argv[1]):
    conn = connect_db(Path(case["db"]))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    extra = similars_stack(conn) if case["similar"] else {}
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0, **extra})
    if case["timeout"] is not None:
        srv.statement_timeout_seconds = case["timeout"]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    calls = []
    entered = threading.Event()
    def stub(host, api_path):
        calls.append([host, api_path])
        entered.set()
        time.sleep(case["delay"])
        return case["answers"].get(api_path)
    class Refusing:
        def open(self, req, timeout=None):
            calls.append([req.host, req.selector])
            raise URLError("instance down")
    report = {}
    try:
        with patch.object(source_fetch, "build_opener", lambda *handlers: Refusing()) if case["refuse"] else patch.object(video, "fetch_instance_json", stub):
            if case["similar"]:
                holder = {}
                worker = threading.Thread(target=lambda: holder.update(get(port, case["path"])))
                worker.start()
                report["entered"] = entered.wait(10)
                report["similar"] = get(port, case["similar"])
                report["calls_at_similar"] = [list(call) for call in calls]
                worker.join(30)
                report["refresh"] = holder
            else:
                report["refresh"] = get(port, case["path"])
        report["calls"] = calls
        reports.append(report)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''


@pytest.fixture(scope="module")
def sync_job():
    spec = importlib.util.spec_from_file_location("sync_whitelist_for_test_video", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def data_db():
    spec = importlib.util.spec_from_file_location("data_db_for_test_video", SERVER_DIR / "data" / "db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- In-process: handle_video_request on a seeded whitelist DB ----


@pytest.fixture
def server(sync_job, tmp_path):
    conn = sqlite3.connect(tmp_path / "whitelist.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 5, 'video')", (PEER_HOST,))
    conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count) VALUES ('7', ?, 'oldslug', 'Old Chan', 3)", (PEER_HOST,))
    conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, title, description, tags_json, category, language, nsfw, duration, thumbnail_url, views, likes, dislikes, published_at, last_checked_at) VALUES ('v1', 'uuid-1', ?, '7', 'Old Chan', 'Old title', 'Old desc', '[\"old\"]', 'Music', 'fr', 0, 10, ?, 1, 1, 0, 1600000000000, ?)", (PEER_HOST, OLD_THUMBNAIL, OLD_CHECKED_AT))
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


class _FakeResponse(io.BytesIO):
    """One instance response as urllib's https open step hands it on: status, headers and a body read in chunks."""

    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.code = self.status = status
        self.msg = "Scripted"
        self.headers = HTTPMessage()
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def info(self) -> HTTPMessage:
        return self.headers


def _serve(monkeypatch, bodies: dict) -> list[tuple[str, object]]:
    """Replace the https open step under `data.source_fetch`'s real opener, keyed by URL path, and return (url, timeout) per call.

    An unlisted path raises `URLError`, an exception is raised, a `_FakeResponse` is returned as is, bytes are served raw and anything else is served as JSON.
    """
    calls = []

    class Scripted(HTTPSHandler):
        def https_open(self, req):
            calls.append((req.full_url, req.timeout))
            body = bodies.get(req.full_url.removeprefix(f"https://{PEER_HOST}"), URLError("no route"))
            if isinstance(body, Exception):
                raise body
            if isinstance(body, _FakeResponse):
                return body
            return _FakeResponse(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(source_fetch, "build_opener", lambda *handlers: build_opener(Scripted(), *handlers))
    return calls


def _video(conn) -> dict:
    return dict(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone())


def _instance_errors(conn) -> tuple:
    return tuple(conn.execute("SELECT last_error, last_error_at, last_error_source FROM instances WHERE host = ?", (PEER_HOST,)).fetchone())


def _snapshot(conn) -> tuple:
    return (tuple(conn.execute("SELECT * FROM videos WHERE video_id = 'v1'").fetchone()), tuple(tuple(row) for row in conn.execute("SELECT * FROM channels ORDER BY channel_id")), _instance_errors(conn))


def _only_body(responses) -> dict:
    assert len(responses) == 1
    status, body = responses[0]
    assert status == 200, body
    return body


def _answered(body: dict, expected: dict) -> dict:
    return {key: body.get(key, "MISSING") for key in expected}


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
def test_response_labels(server, monkeypatch, responses, category, language, expected_category, expected_language):
    server.db.execute("UPDATE videos SET category = ?, language = ? WHERE video_id = 'v1'", (category, language))
    server.db.commit()
    monkeypatch.setattr(video, "fetch_instance_json", lambda host, path: None)

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    assert body.get("category", "MISSING") == expected_category
    assert body.get("language", "MISSING") == expected_language


def test_refresh_stores_raw_codes(server, monkeypatch, responses):
    server.db.execute("UPDATE videos SET category = '15', language = 'en' WHERE video_id = 'v1'")
    server.db.commit()
    # An id-only category and a code-only language are what a source without labels sends; both must stay raw in the row.
    source = {"name": "New title", "category": {"id": 15}, "language": {"id": "en"}}
    monkeypatch.setattr(video, "fetch_instance_json", lambda host, path: source if path == VIDEO_PATH else None)

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    # Labels are a display concern only: the row keeps the id and code, which FTS and embeddings read.
    stored = server.db.execute("SELECT title, last_checked_at, category, language FROM videos WHERE video_id = 'v1'").fetchone()
    assert (stored["title"], stored["last_checked_at"] > OLD_CHECKED_AT) == ("New title", True), "the refresh did not write the row"
    assert (stored["category"], stored["language"]) == ("15", "en")
    assert body.get("category", "MISSING") == "Science & Technology"
    assert body.get("language", "MISSING") == "English"


# The 404 carries a `{}` body, which would be a success if the status were ignored.
@pytest.mark.parametrize("outcome", [URLError("down"), _FakeResponse(b"{}", status=404), b"<html>", b"\xff\xfe", b"[1, 2]", b"{}"], ids=["open-urlerror", "status-404", "not-json", "bad-utf8", "json-list", "empty-object"])
def test_fetch_failure_leaves_db_untouched(server, monkeypatch, responses, outcome):
    calls = _serve(monkeypatch, {VIDEO_PATH: outcome})
    before = _snapshot(server.db)
    assert before[2] == ("boom", 5, "video"), "the seeded instance error is what the comparison must preserve"

    video.handle_video_request(None, server, PARAMS)

    # The detail fetch was really attempted, so an untouched DB is not just a handler that never fetched.
    assert calls[:1] == [(VIDEO_URL, 4)]
    body = _only_body(responses)
    assert _snapshot(server.db) == before
    assert _answered(body, STORED_ANSWER) == STORED_ANSWER
    assert body.get("nsfw", "MISSING") is False


CDN_URL = "https://cdn.example/api/v1/videos/uuid-1"
SOURCE_BYTES = json.dumps(SOURCE).encode("utf-8")


def _padded(size: int) -> bytes:
    """The source payload followed by JSON whitespace up to exactly size bytes, so it still parses to SOURCE."""
    return SOURCE_BYTES + b" " * (size - len(SOURCE_BYTES))


# (what the instance serves, the control that differs in that one thing), as `_serve` maps.
REFUSED_DETAILS = {
    # The target is served the full payload, so a fetch that followed it would answer SOURCE.
    "redirect off the instance": ({VIDEO_PATH: _FakeResponse(b"", status=302, headers={"Location": CDN_URL}), CDN_URL: SOURCE_BYTES}, {VIDEO_PATH: SOURCE_BYTES}),
    # The body itself is small, so only the declared length can refuse it.
    "Content-Length 2,000,001": ({VIDEO_PATH: _FakeResponse(SOURCE_BYTES, headers={"Content-Length": "2000001"})}, {VIDEO_PATH: _FakeResponse(SOURCE_BYTES, headers={"Content-Length": "2000000"})}),
    "2,000,001 bytes streamed": ({VIDEO_PATH: _padded(2_000_001)}, {VIDEO_PATH: _padded(2_000_000)}),
}


@pytest.mark.parametrize("refused, control", REFUSED_DETAILS.values(), ids=REFUSED_DETAILS.keys())
def test_fetch_instance_json_answers_none_for_a_refused_detail_and_opens_only_the_detail_url(monkeypatch, refused, control):
    calls = _serve(monkeypatch, refused)
    assert video.fetch_instance_json(PEER_HOST, VIDEO_PATH) is None
    # Following the redirect adds the cdn.example URL.
    assert calls == [(VIDEO_URL, 4)]
    # Control: the answer that differs in that one thing comes back as the source payload.
    calls = _serve(monkeypatch, control)
    assert video.fetch_instance_json(PEER_HOST, VIDEO_PATH) == SOURCE
    assert calls == [(VIDEO_URL, 4)]


def test_success_refreshes_row_and_response(server, monkeypatch, responses):
    before = _video(server.db)
    _serve(monkeypatch, {VIDEO_PATH: SOURCE, NEWSLUG_PATH: {"followersCount": 9}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    after = _video(server.db)
    # tags_json is compared parsed: the JSON spacing and escaping are not part of the contract.
    assert json.loads(after.pop("tags_json")) == ["alpha", "beta"]
    before.pop("tags_json")
    assert after["last_checked_at"] > OLD_CHECKED_AT
    # popularity and last_checked_at are derived at write time; every other column is either a source value or the untouched seed.
    assert after == {**before, "title": "New title", "description": "New desc", "channel_name": "New Chan", "views": 50, "likes": 5, "dislikes": 1, "category": "Science & Technology", "language": "en", "nsfw": 1, "duration": 321, "thumbnail_url": NEW_THUMBNAIL, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}
    assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 9)
    assert _instance_errors(server.db) == (None, None, None)
    assert ORIGINAL_KEYS <= body.keys()
    expected = {"title": "New title", "description": "New desc", "views": 50, "likes": 5, "dislikes": 1, "tags": ["alpha", "beta"], "category": "Science & Technology", "language": "English", "duration": 321, "thumbnailUrl": NEW_THUMBNAIL, "channelName": "New Chan", "subscribersCount": 9}
    assert _answered(body, expected) == expected
    assert body.get("nsfw", "MISSING") is True


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
    assert after == {**before, "views": 77, "popularity": after["popularity"], "last_checked_at": after["last_checked_at"]}
    assert _snapshot(server.db)[1] == channels_before
    expected = {**STORED_ANSWER, "views": 77}
    assert _answered(body, expected) == expected
    assert body.get("nsfw", "MISSING") is False


def test_failed_channel_fetch_keeps_stored_followers(server, monkeypatch, responses):
    calls = _serve(monkeypatch, {VIDEO_PATH: SOURCE})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    # The channel-detail fetch was attempted and failed, so followers are absent while slug and display name are present.
    assert [url for url, _ in calls] == [VIDEO_URL, f"https://{PEER_HOST}{NEWSLUG_PATH}"]
    assert tuple(server.db.execute("SELECT channel_name, display_name, followers_count FROM channels WHERE channel_id = '7'").fetchone()) == ("newslug", "New Chan", 3)
    assert (body.get("channelName"), body.get("subscribersCount", "MISSING")) == ("New Chan", 3)


def test_empty_tag_list_propagates(server, monkeypatch, responses):
    _serve(monkeypatch, {VIDEO_PATH: {"tags": []}})

    video.handle_video_request(None, server, PARAMS)

    body = _only_body(responses)
    assert _video(server.db)["tags_json"] == "[]"
    assert body.get("tags", "MISSING") == []


def test_object_body_counts_as_success(server, monkeypatch, responses):
    title, duration = "Fresh title", 42
    calls = _serve(monkeypatch, {VIDEO_PATH: b'{"name": "Fresh title", "duration": 42}'})

    video.handle_video_request(None, server, PARAMS)

    reply = _only_body(responses)
    assert calls[:1] == [(VIDEO_URL, 4)]
    stored = _video(server.db)
    assert (stored["title"], stored["duration"], stored["last_checked_at"] > OLD_CHECKED_AT) == (title, duration, True)
    assert _instance_errors(server.db) == (None, None, None)
    assert (reply.get("title"), reply.get("duration", "MISSING")) == (title, duration)


def test_second_request_reflects_source_change(server, monkeypatch, responses):
    bodies = {VIDEO_PATH: SOURCE, NEWSLUG_PATH: {"followersCount": 9}}
    _serve(monkeypatch, bodies)

    video.handle_video_request(None, server, PARAMS)
    bodies[VIDEO_PATH] = {**SOURCE, "name": "Renamed", "tags": ["gamma"]}
    video.handle_video_request(None, server, PARAMS)

    assert [status for status, _ in responses] == [200, 200]
    assert [(body.get("title"), body.get("tags", "MISSING")) for _, body in responses] == [("New title", ["alpha", "beta"]), ("Renamed", ["gamma"])]
    stored = _video(server.db)
    assert (stored["title"], json.loads(stored["tags_json"])) == ("Renamed", ["gamma"])


# ---- Engine child: the routes over HTTP ----


def _seed(sync_job, path: Path, heavy: bool = False) -> None:
    conn = sqlite3.connect(path)
    try:
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 123, 'crawler')", (HOST,))
        conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
        # channel_url and video_url are NULL, so both URLs in the answer are built from slug/uuid + host.
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
            (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
        )
        # v1's ANN neighbour on another channel, the only row the similars GET can answer; it also shows a refresh of v1 leaves other rows alone.
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, embed_path, views, likes, dislikes, last_checked_at) VALUES ('v2', 'uuid-v2', ?, 'c2', 'Neighbour', 1700000000000, '/videos/embed/uuid-v2', 5, 1, 0, 1)", (HOST,))
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES ('v1', ?, ?, 4, 'm', 'now', ?)", (HOST, array("f", [1, 0, 0, 0]).tobytes(), compute_ann_id("v1", HOST)))
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES ('v2', ?, ?, 4, 'm', 'now', ?)", (HOST, array("f", [0.8, 0.6, 0, 0]).tobytes(), compute_ann_id("v2", HOST)))
        if heavy:
            # About 90,000 joined rows per videos UPDATE: past the progress handler's 10,000-instruction check, yet a few ms of work (observed persisting inside a 0.2 s budget).
            conn.execute("CREATE TABLE heavy (n INTEGER)")
            conn.executemany("INSERT INTO heavy VALUES (?)", [(n,) for n in range(300)])
            conn.execute("CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END")
        conn.commit()
    finally:
        conn.close()


def _get(sync_job, tmp_path: Path, *cases: tuple[str, dict]) -> list[dict]:
    """Run each (path, instance answers) case on its own freshly seeded DB, so no case sees another's write."""
    runs = []
    for index, (path, answers) in enumerate(cases):
        db_path = tmp_path / f"case{index}.db"
        _seed(sync_job, db_path)
        runs.append([str(db_path), path, answers])
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", ANSWER_CHILD, json.dumps(runs)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built each server and ran every request
    return json.loads(run.stdout)


def _interrupted(data_db, sync_job, path: Path, heavy: bool) -> bool:
    """Seed a DB, then update v1 through the Engine's own connection after its statement deadline has passed; report whether the progress handler interrupted the UPDATE."""
    _seed(sync_job, path, heavy)
    conn = data_db.connect_db(path)
    try:
        with data_db.statement_deadline(0.05):
            time.sleep(0.1)
            try:
                conn.execute("UPDATE videos SET title = 'x' WHERE video_id = 'v1'")
            except sqlite3.OperationalError as exc:
                if not data_db.is_interrupted_error(exc):
                    raise
                return True
            return False
    finally:
        conn.close()


def _rows(path: Path) -> dict[str, dict[str, dict]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "videos": {row["video_id"]: dict(row) for row in conn.execute("SELECT * FROM videos")},
            "channels": {row["channel_id"]: dict(row) for row in conn.execute("SELECT * FROM channels")},
            "instances": {row["host"]: dict(row) for row in conn.execute("SELECT * FROM instances")},
        }
    finally:
        conn.close()


def _run(sync_job, tmp_path: Path, answers: dict, *, delay: float = 0, timeout: float | None = None, refuse: bool = False, heavy: bool = False, similar: str | None = None) -> dict:
    """Run one refresh case on a freshly seeded DB; return the child's report with the rows before and after and the run's wall-clock window in ms."""
    db_path = tmp_path / "case.db"
    _seed(sync_job, db_path, heavy)
    before = _rows(db_path)
    case = {"db": str(db_path), "path": REFRESH, "answers": answers, "delay": delay, "timeout": timeout, "refuse": refuse, "similar": similar}
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    started_ms = time.time() * 1000
    run = subprocess.run([str(ENGINE_PY), "-c", PERSIST_CHILD, json.dumps([case])], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    finished_ms = time.time() * 1000
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built the server and ran every request
    (report,) = json.loads(run.stdout)
    return {**report, "before": before, "after": _rows(db_path), "window": (started_ms, finished_ms)}


def _assert_written(report: dict, video: dict, channel: dict) -> None:
    before, after = report["before"], report["after"]
    written = after["videos"]["v1"]
    # Left unwritten, last_checked_at stays 1 and popularity 0.0 as seeded.
    assert report["window"][0] <= written["last_checked_at"] <= report["window"][1]
    assert written["popularity"] > 0
    unstamped = {**written, "last_checked_at": None, "popularity": None}
    # Left unwritten, the video row still reads "DB title", views 10 and the rest of the seed; v2 is untouched either way.
    assert {**after["videos"], "v1": unstamped} == {**before["videos"], "v1": {**before["videos"]["v1"], **video, "last_checked_at": None, "popularity": None}}
    assert after["channels"] == {"c1": {**before["channels"]["c1"], **channel}}
    # Left unwritten, the instance row still reads 'boom', 123, 'crawler'.
    assert after["instances"] == {HOST: {**before["instances"][HOST], **CLEARED_INSTANCE}}


def test_refresh_answers_the_instances_values_in_the_api_video_shape(sync_job, tmp_path):
    report, by_video_id = _get(sync_job, tmp_path, (REFRESH, ANSWERING), (f"/api/video/refresh?id=v1&host={HOST}", BY_VIDEO_ID))
    # Unrouted, the refresh reads 404 {"error": "Not found"}; merged with no live values it reads "DB title", views 10 and an empty accountAvatarUrl.
    assert (report["status"], report["body"]) == (200, LIVE)
    # The detail by the requested id, then the channel by the slug the detail named; 77 in LIVE is only reachable through the second call.
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]
    # Requested by "v1", uuid, embed and original URL built from the query id read "v1", ".../embed/v1" and ".../watch/v1"; from the row they are still LIVE's uuid-v1 values.
    assert (by_video_id["status"], by_video_id["body"]) == (200, LIVE)


def test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted(sync_job, tmp_path):
    report, omitting = _get(sync_job, tmp_path, (REFRESH, PARTIAL), (REFRESH, OMITTING))
    assert report["status"] == 200, report["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the channel call was made and answered nothing
    body = report["body"]
    # Taking only the instance's fields reads "", None, "" and None here.
    assert (body["description"], body["views"], body["channelName"], body["subscribersCount"]) == ("DB description", 10, "DB Chan", 5)
    # The instance's values still win where it supplied them; a truthiness fallback reads likes 2, the row's value.
    assert (body["title"], body["likes"], body["dislikes"]) == ("Live title B", 0, 3)
    assert body == {**LIVE, "title": "Live title B", "description": "DB description", "channelName": "DB Chan", "subscribersCount": 5, "accountAvatarUrl": "", "views": 10, "likes": 0, **ROW_TAXONOMY}
    assert omitting["status"] == 200, omitting["body"]
    assert omitting["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the detail answered without title, likes or dislikes
    # Taking only the instance's fields reads "", None and None here; the row's are "DB title", likes 2 and dislikes 1.
    assert (omitting["body"]["title"], omitting["body"]["likes"], omitting["body"]["dislikes"]) == ("DB title", 2, 1)
    assert omitting["body"] == {**LIVE, "title": "DB title", "description": "Live description B", "channelName": "Live Chan B", "subscribersCount": 60, "accountAvatarUrl": "", "views": 900, "likes": 2, "dislikes": 1, **ROW_TAXONOMY}


def test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance(sync_job, tmp_path):
    missing, unknown = _get(sync_job, tmp_path, (f"/api/video/refresh?host={HOST}", ANSWERING), (f"/api/video/refresh?id=nope&host={HOST}", ANSWERING))
    assert (missing["status"], missing["body"], missing["calls"]) == (400, {"error": "Missing video id"}, [])
    # The unrouted path reads 404 {"error": "Not found"}, which this body tells apart.
    assert (unknown["status"], unknown["body"], unknown["calls"]) == (404, {"error": "Video not found"}, [])


def test_api_video_still_answers_the_instances_values(sync_job, tmp_path):
    (report,) = _get(sync_job, tmp_path, (f"/api/video?id={UUID}&host={HOST}", ANSWERING))
    # Kept live until a follow-up makes /api/video DB-only; a DB-only /api/video reads "DB title" and makes no call.
    assert (report["status"], report["body"]) == (200, LIVE)
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]


def test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows(sync_job, tmp_path):
    report = _run(sync_job, tmp_path, ANSWERING)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the detail and the channel call both answered
    _assert_written(report, LIVE_VIDEO, LIVE_CHANNEL)


def test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields(sync_job, tmp_path):
    report = _run(sync_job, tmp_path, CHANNEL_FAILED)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the channel call was made and answered nothing
    # Counting a failed channel call as a failed refresh leaves every row as seeded.
    _assert_written(report, DB_CHANNEL_VIDEO, DB_CHANNEL_CHANNEL)


def test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed(sync_job, data_db, tmp_path):
    # control: on this fixture an UPDATE of v1 reaches the progress handler's check, so an expired deadline interrupts it; on the plain schema the same UPDATE finishes before the check, which is why the trigger is there
    assert _interrupted(data_db, sync_job, tmp_path / "heavy.db", True) is True
    assert _interrupted(data_db, sync_job, tmp_path / "plain.db", False) is False
    report = _run(sync_job, tmp_path, ANSWERING, delay=0.5, timeout=0.2, heavy=True)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["refresh"]["elapsed"] >= 1.0  # control: both instance calls took their 0.5 s, so the request's 0.2 s deadline had passed before the write
    # Writing under the request's expired deadline is interrupted: "[video] failed to persist ... interrupted" is logged and every row stays as seeded.
    _assert_written(report, LIVE_VIDEO, LIVE_CHANNEL)


@pytest.mark.parametrize("answers, refuse", [
    ({}, False),
    ({DETAIL_PATH: {}}, False),
    ({DETAIL_PATH: [DETAIL]}, False),
    ({}, True),
], ids=["detail-none", "detail-empty-object", "detail-json-list", "open-urlerror"])
def test_a_refresh_the_instance_did_not_answer_writes_nothing(sync_job, tmp_path, answers, refuse):
    report = _run(sync_job, tmp_path, answers, refuse=refuse)
    assert report["calls"] == [[HOST, DETAIL_PATH]]  # control: the refresh asked the instance for the detail, and only that
    # A JSON list reaching `detail.get` drops the connection unanswered (status None); the others answer these DB values.
    assert (report["refresh"]["status"], report["refresh"]["body"]) == (200, DB_ONLY)
    # Writing on a failed call bumps last_checked_at from 1, recomputes popularity from 0.0 and clears instances.last_error 'boom'.
    assert report["after"] == report["before"]


def test_similars_answer_while_a_refresh_is_blocked_on_the_instance(sync_job, tmp_path):
    # A detail naming no channel, so the refresh makes one 5 s instance call.
    report = _run(sync_job, tmp_path, {DETAIL_PATH: {**DETAIL, "channel": {}}}, delay=5, similar=SIMILAR)
    assert report["entered"] is True  # control: the similars GET went out while the refresh was inside the instance call
    assert report["refresh"]["status"] == 200 and report["refresh"]["elapsed"] >= 4.5, report["refresh"]  # control: the refresh really was held about 5 s
    similar = report["similar"]
    assert similar["status"] == 200, similar["body"]
    # The real ANN answer for v1 over this DB: its neighbour v2, and not the seed itself.
    assert (similar["body"]["seed"]["video_id"], [row["video_id"] for row in similar["body"]["rows"]]) == ("v1", ["v2"])
    # With the instance call made inside db_lock, the similars GET waits the refresh out (observed 4.0 s against a 2 s x 2 locked stub); unblocked it took about 2 ms.
    assert similar["elapsed"] < 1.0, similar["elapsed"]
    # The similars GET adds no instance call of its own; a locked refresh has already finished its calls by the time the similars answer.
    assert report["calls_at_similar"] == [[HOST, DETAIL_PATH]]
    assert report["calls"] == [[HOST, DETAIL_PATH]]
