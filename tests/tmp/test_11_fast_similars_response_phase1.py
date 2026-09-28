"""GET `/api/video/refresh` answers the instance's live values in `/api/video`'s response shape, and answers a field the instance omitted from the row's value.

- With the instance answering the video detail and the channel, the refresh answers 200 with exactly `/api/video`'s eighteen keys: the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar; the channel URL built from the instance's channel slug and the host, the original URL from the row's uuid and the host; and the keys today's merge takes from the row (uuid, channel avatar, account name and URL, embed, published date) from the row. It asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`. Requested by the row's video id rather than its uuid, it answers the same, so uuid, embed and original URL come from the row and not from the query id.
- With the detail omitting `description` and `views`, carrying `likes: 0`, and the channel call answering nothing, the refresh answers the row's description, views, channel display name and follower count beside the instance's title, dislikes and `likes` 0; with the detail omitting title, likes and dislikes instead, it answers the row's title, likes and dislikes beside the instance's description, views, channel display name and follower count.
- A refresh with no id answers 400 `Missing video id`, and one for an id not in the DB answers 404 `Video not found`, neither calling the instance.
- `/api/video` against the same answering instance still answers the instance's values.

Each case runs under the Engine's interpreter in a child process: a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, over its own whitelist-shaped temporary DB (schema from `sync-whitelist.py`), with `handlers.video.fetch_instance_json` replaced by a stub that records each call and answers from the case's path map.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# The active suite's conftest, importable whether this file runs from tests/tmp or tests/active.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
HOST = "tube.example"
UUID = "uuid-v1"
REFRESH = f"/api/video/refresh?id={UUID}&host={HOST}"
DETAIL_PATH = f"/api/v1/videos/{UUID}"
CHANNEL_PATH = "/api/v1/video-channels/live_slug"
# Every value differs from the row's, so an answer built from the row cannot pass for the instance's.
DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
CHANNEL = {"displayName": "Live Chan Detail", "followersCount": 77}
ANSWERING = {DETAIL_PATH: DETAIL, CHANNEL_PATH: CHANNEL}
# No description or views, likes 0 (supplied, and falsy), a channel slug but no channel display name or followers; the channel call is not in the map, so it answers None.
PARTIAL = {DETAIL_PATH: {"name": "Live title B", "likes": 0, "dislikes": 3, "channel": {"name": "live_slug"}}}
# The complement of PARTIAL: no title, likes or dislikes, but its own description, views, channel display name and followers; the channel call again answers None.
OMITTING = {DETAIL_PATH: {"description": "Live description B", "views": 900, "channel": {"name": "live_slug", "displayName": "Live Chan B", "followersCount": 60}}}
# The row requested by its video_id "v1" rather than its uuid; the detail answers under either id, so the answer turns only on where uuid, embed and original URL come from.
BY_VIDEO_ID = {**ANSWERING, "/api/v1/videos/v1": DETAIL}
# The answer to a refresh over ANSWERING (observed from today's /api/video with the same stub): accountName/accountUrl, channelAvatarUrl, embedUrl, publishedAt and videoUuid come from the row in today's merge.
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
    # Issue 10's response keys: DETAIL's tags, category and nsfw; no language, duration or thumbnail in DETAIL or the row.
    "category": "Music",
    "language": "",
    "tags": ["live"],
    "nsfw": False,
    "duration": None,
    "thumbnailUrl": "",
}
# Issue 10's keys answered from the row, for a detail that omits tags and category.
ROW_TAXONOMY = {"category": "DB cat", "tags": ["db-tag"]}
# Starts each case's server on its own DB, runs one GET through the real handler with `fetch_instance_json` stubbed, and reports the status, the parsed body and every instance call.
CHILD = r'''
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


@pytest.fixture(scope="module")
def sync_job():
    spec = importlib.util.spec_from_file_location("sync_whitelist_video_metadata", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(sync_job, path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.execute("INSERT INTO instances (host, last_error) VALUES (?, 'boom')", (HOST,))
        conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
        # channel_url and video_url are NULL, so both URLs in the answer are built from slug/uuid + host.
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
            (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
        )
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
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, json.dumps(runs)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built each server and ran every request
    return json.loads(run.stdout)


def test_refresh_answers_the_instances_values_in_the_api_video_shape(sync_job, tmp_path):
    report, by_video_id = _get(sync_job, tmp_path, (REFRESH, ANSWERING), (f"/api/video/refresh?id=v1&host={HOST}", BY_VIDEO_ID))
    # Unrouted, the refresh reads 404 {"error": "Not found"}; merged with no live values it reads "DB title", views 10 and an empty accountAvatarUrl.
    assert (report["status"], report["body"]) == (200, LIVE)  # C1
    # The detail by the requested id, then the channel by the slug the detail named; 77 in LIVE is only reachable through the second call.
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # C1
    # Requested by "v1", uuid, embed and original URL built from the query id read "v1", ".../embed/v1" and ".../watch/v1"; from the row they are still LIVE's uuid-v1 values.
    assert (by_video_id["status"], by_video_id["body"]) == (200, LIVE)  # C1


def test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted(sync_job, tmp_path):
    report, omitting = _get(sync_job, tmp_path, (REFRESH, PARTIAL), (REFRESH, OMITTING))
    assert report["status"] == 200, report["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the channel call was made and answered nothing
    body = report["body"]
    # Taking only the instance's fields reads "", None, "" and None here.
    assert (body["description"], body["views"], body["channelName"], body["subscribersCount"]) == ("DB description", 10, "DB Chan", 5)  # C2
    # The instance's values still win where it supplied them; a truthiness fallback reads likes 2, the row's value.
    assert (body["title"], body["likes"], body["dislikes"]) == ("Live title B", 0, 3)  # C2
    assert body == {**LIVE, "title": "Live title B", "description": "DB description", "channelName": "DB Chan", "subscribersCount": 5, "accountAvatarUrl": "", "views": 10, "likes": 0, **ROW_TAXONOMY}  # C1 C2: the same eighteen keys, every other value unchanged
    assert omitting["status"] == 200, omitting["body"]
    assert omitting["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the detail answered without title, likes or dislikes
    # Taking only the instance's fields reads "", None and None here; the row's are "DB title", likes 2 and dislikes 1.
    assert (omitting["body"]["title"], omitting["body"]["likes"], omitting["body"]["dislikes"]) == ("DB title", 2, 1)  # C2
    assert omitting["body"] == {**LIVE, "title": "DB title", "description": "Live description B", "channelName": "Live Chan B", "subscribersCount": 60, "accountAvatarUrl": "", "views": 900, "likes": 2, "dislikes": 1, **ROW_TAXONOMY}  # C1 C2: the instance's values win for the four PARTIAL omitted


def test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance(sync_job, tmp_path):
    missing, unknown = _get(sync_job, tmp_path, (f"/api/video/refresh?host={HOST}", ANSWERING), (f"/api/video/refresh?id=nope&host={HOST}", ANSWERING))
    assert (missing["status"], missing["body"], missing["calls"]) == (400, {"error": "Missing video id"}, [])
    # The unrouted path reads 404 {"error": "Not found"}, which this body tells apart.
    assert (unknown["status"], unknown["body"], unknown["calls"]) == (404, {"error": "Video not found"}, [])


def test_api_video_still_answers_the_instances_values(sync_job, tmp_path):
    (report,) = _get(sync_job, tmp_path, (f"/api/video?id={UUID}&host={HOST}", ANSWERING))
    # Kept live until the follow-up plan; a DB-only /api/video reads "DB title" and makes no call.
    assert (report["status"], report["body"]) == (200, LIVE)
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]
