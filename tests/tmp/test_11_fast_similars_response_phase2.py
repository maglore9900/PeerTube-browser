"""GET `/api/video/refresh` writes the `videos`, `channels` and `instances` rows only when the instance's video detail call answered, and a refresh blocked on the instance does not hold up the id-based similars GET.

- With the detail and channel calls answering, the video row holds the instance's title, description, channel display name, counts, tags, category and nsfw, with `last_checked_at` inside the run's wall-clock window and a nonzero `popularity`; the channel row holds the instance's slug, display name and the channel call's follower count; the instance row's `last_error`, `last_error_at` and `last_error_source` are NULL; every other column and the other video's row are unchanged. With the channel call answering nothing, the rows are written the same way, but the channel display name and follower count keep the DB's values.
- With `statement_timeout_seconds` at 0.2 and each instance call taking 0.5 s, so the request's own deadline has passed before the write, the same rows are written. The fixture DB carries an extra AFTER UPDATE trigger on `videos` that runs well past the progress handler's 10,000-instruction check; without it the real UPDATE never reaches that check, and an expired deadline would go unnoticed.
- With the detail call answering `None`, `{}`, a JSON list, or failing with `URLError` at `urlopen`, the refresh answers 200 with the DB-only values, and every column of the `videos`, `channels` and `instances` rows, `last_checked_at` and `last_error` included, is the same before and after.
- With the detail call blocking for 5 s, a `/videos/v1/similar` GET sent while the refresh is inside that call answers 200 with its ANN neighbour in under 1 s, and the instance stub has by then been called only for the refresh's `/api/v1/videos/{uuid}`.

Each case runs under the Engine's interpreter in a child process: a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, over its own whitelist-shaped temporary DB (schema from `sync-whitelist.py`). `handlers.video.fetch_instance_json` is replaced by a stub that records each call and answers from the case's path map, or `handlers.video.urlopen` by one that raises `URLError`. For the similars case the child also builds a flat faiss index over the DB's embeddings and the Engine's own recommendation strategy.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from array import array
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
SIMILAR = f"/videos/v1/similar?host={HOST}"
DETAIL_PATH = f"/api/v1/videos/{UUID}"
CHANNEL_PATH = "/api/v1/video-channels/live_slug"
# Every value differs from the row's, so a row left as seeded cannot pass for a written one.
DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
ANSWERING = {DETAIL_PATH: DETAIL, CHANNEL_PATH: {"displayName": "Live Chan Detail", "followersCount": 77}}
# The detail names the channel slug but no display name or followers, and the channel call is not in the map, so it answers None.
CHANNEL_FAILED = {DETAIL_PATH: {**DETAIL, "channel": {"name": "live_slug"}}}
# The columns an answered refresh writes, over ANSWERING and over CHANNEL_FAILED.
LIVE_VIDEO = {"title": "Live title", "description": "Live description", "channel_name": "Live Chan", "views": 1000, "likes": 50, "dislikes": 3, "tags_json": '["live"]', "category": "Music", "nsfw": 0}
LIVE_CHANNEL = {"channel_name": "live_slug", "display_name": "Live Chan", "followers_count": 77}
DB_CHANNEL_VIDEO = {**LIVE_VIDEO, "channel_name": "DB Chan"}
DB_CHANNEL_CHANNEL = {"channel_name": "live_slug", "display_name": "DB Chan", "followers_count": 5}
CLEARED_INSTANCE = {"last_error": None, "last_error_at": None, "last_error_source": None}
# The refresh's answer when the instance supplied nothing: every field from the seeded row (observed on today's refresh with the detail answering None).
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
}
# Starts each case's server on its own DB, sends the refresh (and, for a similars case, the similars GET while the refresh sits in the instance call), and reports statuses, bodies, timings and every instance call.
CHILD = r'''
import http.client, inspect, json, sys, threading, time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import faiss, numpy as np
import server
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
    rows = conn.execute("SELECT rowid, embedding FROM video_embeddings").fetchall()
    index.add_with_ids(np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]), np.array([r["rowid"] for r in rows], dtype=np.int64))
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
    def refusing(req, timeout=None):
        calls.append([req.host, req.selector])
        raise URLError("instance down")
    report = {}
    try:
        with patch.object(video, "urlopen", refusing) if case["refuse"] else patch.object(video, "fetch_instance_json", stub):
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
    spec = importlib.util.spec_from_file_location("sync_whitelist_video_metadata_phase2", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def data_db():
    spec = importlib.util.spec_from_file_location("data_db_video_metadata_phase2", SERVER_DIR / "data" / "db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(sync_job, path: Path, heavy: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 123, 'crawler')", (HOST,))
        conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
            (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
        )
        # v1's ANN neighbour on another channel, the only row the similars GET can answer; it also shows a refresh of v1 leaves other rows alone.
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, embed_path, views, likes, dislikes, last_checked_at) VALUES ('v2', 'uuid-v2', ?, 'c2', 'Neighbour', 1700000000000, '/videos/embed/uuid-v2', 5, 1, 0, 1)", (HOST,))
        conn.execute("INSERT INTO video_embeddings VALUES ('v1', ?, ?, 4, 'm', 'now')", (HOST, array("f", [1, 0, 0, 0]).tobytes()))
        conn.execute("INSERT INTO video_embeddings VALUES ('v2', ?, ?, 4, 'm', 'now')", (HOST, array("f", [0.8, 0.6, 0, 0]).tobytes()))
        if heavy:
            # About 90,000 joined rows per videos UPDATE: past the progress handler's 10,000-instruction check, yet a few ms of work (observed persisting inside a 0.2 s budget).
            conn.execute("CREATE TABLE heavy (n INTEGER)")
            conn.executemany("INSERT INTO heavy VALUES (?)", [(n,) for n in range(300)])
            conn.execute("CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END")
        conn.commit()
    finally:
        conn.close()


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
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, json.dumps([case])], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    finished_ms = time.time() * 1000
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built the server and ran every request
    (report,) = json.loads(run.stdout)
    return {**report, "before": before, "after": _rows(db_path), "window": (started_ms, finished_ms)}


def _assert_written(report: dict, video: dict, channel: dict) -> None:
    before, after = report["before"], report["after"]
    written = after["videos"]["v1"]
    # Left unwritten, last_checked_at stays 1 and popularity 0.0 as seeded.
    assert report["window"][0] <= written["last_checked_at"] <= report["window"][1]  # C1
    assert written["popularity"] > 0  # C1
    unstamped = {**written, "last_checked_at": None, "popularity": None}
    # Left unwritten, the video row still reads "DB title", views 10 and the rest of the seed; v2 is untouched either way.
    assert {**after["videos"], "v1": unstamped} == {**before["videos"], "v1": {**before["videos"]["v1"], **video, "last_checked_at": None, "popularity": None}}  # C1
    assert after["channels"] == {"c1": {**before["channels"]["c1"], **channel}}  # C1
    # Left unwritten, the instance row still reads 'boom', 123, 'crawler'.
    assert after["instances"] == {HOST: {**before["instances"][HOST], **CLEARED_INSTANCE}}  # C1


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
    # control: on this fixture an UPDATE of v1 reaches the progress handler's check, so an expired deadline interrupts it (observed); on the plain schema the same UPDATE finishes before the check, which is why the trigger is there
    assert _interrupted(data_db, sync_job, tmp_path / "heavy.db", True) is True
    assert _interrupted(data_db, sync_job, tmp_path / "plain.db", False) is False
    report = _run(sync_job, tmp_path, ANSWERING, delay=0.5, timeout=0.2, heavy=True)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["refresh"]["elapsed"] >= 1.0  # control: both instance calls took their 0.5 s, so the request's 0.2 s deadline had passed before the write
    # Writing under the request's expired deadline is interrupted: "[video] failed to persist ... interrupted" is logged and every row stays as seeded (observed on the pre-phase code).
    _assert_written(report, LIVE_VIDEO, LIVE_CHANNEL)


@pytest.mark.parametrize("answers, refuse", [
    ({}, False),
    ({DETAIL_PATH: {}}, False),
    ({DETAIL_PATH: [DETAIL]}, False),
    ({}, True),
], ids=["detail-none", "detail-empty-object", "detail-json-list", "urlopen-urlerror"])
def test_a_refresh_the_instance_did_not_answer_writes_nothing(sync_job, tmp_path, answers, refuse):
    report = _run(sync_job, tmp_path, answers, refuse=refuse)
    assert report["calls"] == [[HOST, DETAIL_PATH]]  # control: the refresh asked the instance for the detail, and only that
    # A JSON list reaching `detail.get` drops the connection unanswered (status None); the others answer these DB values today too.
    assert (report["refresh"]["status"], report["refresh"]["body"]) == (200, DB_ONLY)  # C1
    # Writing on a failed call bumps last_checked_at from 1, recomputes popularity from 0.0 and clears instances.last_error 'boom' (observed on the pre-phase code for None, {} and URLError).
    assert report["after"] == report["before"]  # C1


def test_similars_answer_while_a_refresh_is_blocked_on_the_instance(sync_job, tmp_path):
    # A detail naming no channel, so the refresh makes one 5 s instance call.
    report = _run(sync_job, tmp_path, {DETAIL_PATH: {**DETAIL, "channel": {}}}, delay=5, similar=SIMILAR)
    assert report["entered"] is True  # control: the similars GET went out while the refresh was inside the instance call
    assert report["refresh"]["status"] == 200 and report["refresh"]["elapsed"] >= 4.5, report["refresh"]  # control: the refresh really was held about 5 s
    similar = report["similar"]
    assert similar["status"] == 200, similar["body"]  # C2
    # The real ANN answer for v1 over this DB: its neighbour v2, and not the seed itself.
    assert (similar["body"]["seed"]["video_id"], [row["video_id"] for row in similar["body"]["rows"]]) == ("v1", ["v2"])  # C2
    # With the instance call made inside db_lock, the similars GET waits the refresh out (observed 4.0 s against a 2 s x 2 locked stub); unblocked it took about 2 ms.
    assert similar["elapsed"] < 1.0, similar["elapsed"]  # C2
    # The similars GET adds no instance call of its own; a locked refresh has already finished its calls by the time the similars answer.
    assert report["calls_at_similar"] == [[HOST, DETAIL_PATH]]  # C2
    assert report["calls"] == [[HOST, DETAIL_PATH]]  # C2
