"""`/internal/videos/metadata` answers a body of id-form and uuid-form entries under one `db_lock` hold, with each matched video once, at its first matching entry; `/internal/dislikes/centroids` still looks up only id-form entries.

- The mixed body `[uuid u-b, id a1, id b1, uuid u-a, uuid u-x]` gives exactly `[b1, a1]` with `count == 2`, and `[id a1, uuid u-x, uuid u-b, id b1]` gives `[a1, b1]`, each with one lock acquisition and every SQL statement run while that lock is held. The id-only body `[b1, a1, b1]` gives `[b1, a1]` with one acquisition.
- An item with a valid `video_id` and the `video_uuid` of another video gives the id's video; values are stripped; a blank `video_id` beside a valid `video_uuid` gives the uuid's video. Repeats within a form, and a video reached by both forms, give one row.
- The uuid entry of a video at `error_count` 5 is omitted at threshold 3, and returned in its first-match place with no threshold.
- `{"entries": "x"}` and `{}` give 400 `Missing entries`, and a body of only malformed items gives 200 with no rows, all three without taking the lock.
- On centroids, a uuid-only body hands the embedding lookup `[]` and gives no centroids; a mixed body hands it only the id entry and gives that video's unit vector.

The handlers import numpy, so they run under the Engine's interpreter in a child process, on a temporary database with the Engine's three joined tables, handed a stand-in for the stdlib request handler so the real body reader and responder run; the embedding lookup is spied on, not replaced, and the lock counts every acquisition.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests" / "active") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "active"))

from conftest import ENGINE_PY  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
HOST = "h.example"
THRESHOLD = 3
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")
# (video_id, video_uuid, instance_domain, n, channel display_name/avatar_url), as in the phase 1 fixture.
A1 = ("a1", "u-a", HOST, 1, ("Chan A", "ava-a"))
B1 = ("b1", "u-b", HOST, 2, ("Chan B", "ava-b"))
E1 = ("e1", "u-e", HOST, 6, (None, None))
MISSING_ENTRIES = [[400, {"error": "Missing entries"}]]
NO_ROWS = [[200, {"ok": True, "count": 0, "rows": []}]]
# Runs each (route, body, threshold) case through the real handler and reports its responses, the lock's acquisitions, whether each SQL statement ran under the lock, and what the embedding lookup was handed.
CHILD = r'''
import io, json, sqlite3, sys, threading
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from handlers import internal_client_reads as reads

class CountingLock:
    """A db_lock that counts every acquisition, through `with` or `acquire`."""
    def __init__(self):
        self._lock = threading.Lock()
        self.enters = 0
    def acquire(self, *args, **kwargs):
        self.enters += 1
        return self._lock.acquire(*args, **kwargs)
    def release(self):
        self._lock.release()
    def locked(self):
        return self._lock.locked()
    def __enter__(self):
        return self.acquire()
    def __exit__(self, *exc_info):
        self.release()

class Request:
    """The parts of a BaseHTTPRequestHandler that http_utils reads and writes: each send_response opens a [status, payload] response."""
    def __init__(self, body):
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"content-length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.responses = []
        self.wfile = SimpleNamespace(write=lambda data: self.responses[-1].append(json.loads(data)))
    def send_response(self, status):
        self.responses.append([status])
    def send_header(self, name, value):
        pass
    def end_headers(self):
        pass

HANDLERS = {"metadata": reads.handle_internal_videos_metadata, "centroids": reads.handle_internal_dislike_centroids}
conn = sqlite3.connect(sys.argv[3])
conn.row_factory = sqlite3.Row
reports = []
for route, body, threshold in json.loads(sys.argv[4]):
    lock = CountingLock()
    statements = []
    conn.set_trace_callback(lambda sql: statements.append(lock.locked()))
    server = SimpleNamespace(db=conn, db_lock=lock, video_error_threshold=threshold)
    request = Request(body)
    with patch.object(reads, "fetch_embeddings_by_ids", wraps=reads.fetch_embeddings_by_ids) as embeddings:
        HANDLERS[route](request, server)
    reports.append({"responses": request.responses, "enters": lock.enters, "held_after": lock.locked(), "statements_locked": statements, "embedding_entries": [c.args[1] for c in embeddings.call_args_list]})
print(json.dumps(reports))
'''


def _video(video_id: str, uuid: str, host: str, n: int) -> dict:
    """The `videos` values the fixture stores for one video: each text column names its video, each integer is distinct."""
    values = {column: f"{column}:{video_id}@{host}" for column in VIDEO_TEXT}
    values.update({column: n * 10 + i for i, column in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=host)
    return values


def _row(video_id: str, uuid: str, host: str, n: int, channel: tuple) -> dict:
    """The metadata row a fixture video should come back as."""
    return {**_video(video_id, uuid, host, n), "channel_display_name": channel[0], "channel_avatar_url": channel[1], "embedding_dim": 3, "model_name": "m"}


def _add(conn: sqlite3.Connection, video: tuple, error_count: int | None = 0) -> None:
    video_id, uuid, host, n, channel = video
    values = {**_video(video_id, uuid, host, n), "error_count": error_count}
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    # A real 3-float32 vector (n, 1, 0), not phase 1's one-byte blob: the centroids handler decodes it.
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, 3, 'm')", (video_id, host, struct.pack("<3f", float(n), 1.0, 0.0)))
    if channel[0] is not None:
        conn.execute("INSERT INTO channels VALUES (?, ?, ?, ?)", (values["channel_id"], host, *channel))


def _id(video_id: str) -> dict:
    return {"video_id": video_id, "instance_domain": HOST}


def _uuid(video_uuid: str) -> dict:
    return {"video_uuid": video_uuid, "instance_domain": HOST}


def _rows(*videos: tuple) -> list:
    return [[200, {"ok": True, "count": len(videos), "rows": [_row(*video) for video in videos]}]]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "metadata.db"
    db = sqlite3.connect(path)
    columns = ", ".join([f"{column} TEXT" for column in VIDEO_TEXT] + [f"{column} INTEGER" for column in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({columns}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    _add(db, A1)
    _add(db, B1, error_count=None)
    _add(db, E1, error_count=5)
    db.commit()
    db.close()
    return path


def _handle(db_path: Path, *cases: tuple[str, dict, int | None]) -> list[dict]:
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR), str(API_DIR), str(db_path), json.dumps(cases)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter imported the handlers and ran every case
    return json.loads(run.stdout)


def test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order(db_path):
    report, id_first = _handle(db_path, ("metadata", {"entries": [_uuid("u-b"), _id("a1"), _id("b1"), _uuid("u-a"), _uuid("u-x")]}, THRESHOLD), ("metadata", {"entries": [_id("a1"), _uuid("u-x"), _uuid("u-b"), _id("b1")]}, THRESHOLD))
    assert (report["enters"], [row["video_id"] for _, payload in report["responses"] for row in payload["rows"]]) == (1, ["b1", "a1"])  # C1: one acquisition served the uuid entry (b1) and the id entry (a1); a lookup per form reads (2, ...), today's id-only lookup (1, ["a1", "b1"])
    assert report["responses"] == _rows(B1, A1)  # C2: b1 at its uuid entry, a1 at its id entry, neither repeated by its other-form entry, u-x omitted; the id-only lookup gives [a1, b1]
    assert id_first["responses"] == _rows(A1, B1)  # C2: emitting every uuid row before the id rows gives [b1, a1] here
    assert set(report["statements_locked"]) == {True}  # at least one statement, and every one ran inside that hold
    assert report["held_after"] is False
    assert (id_first["enters"], set(id_first["statements_locked"])) == (1, {True})  # C1


def test_an_id_only_body_takes_the_lock_once_and_gives_its_rows_in_entry_order(db_path):
    (report,) = _handle(db_path, ("metadata", {"entries": [_id("b1"), _id("a1"), _id("b1")]}, THRESHOLD))
    assert report["responses"] == _rows(B1, A1)  # C2: b1 first against the fixture's insertion, rowid and alphabetical order, so rows in table order give [a1, b1]
    assert report["enters"] == 1  # C1


def test_a_valid_video_id_wins_over_a_video_uuid_and_a_blank_one_falls_back_to_it(db_path):
    both, padded, blank_id = _handle(
        db_path,
        ("metadata", {"entries": [{"video_id": "a1", "video_uuid": "u-b", "instance_domain": HOST}]}, THRESHOLD),
        ("metadata", {"entries": [{"video_id": " a1 ", "video_uuid": "   ", "instance_domain": f" {HOST} "}]}, THRESHOLD),
        ("metadata", {"entries": [{"video_id": "   ", "video_uuid": " u-b ", "instance_domain": HOST}]}, THRESHOLD),
    )
    assert both["responses"] == _rows(A1)  # C2: the id's video, not u-b's and not both
    assert padded["responses"] == _rows(A1)  # C2: values are stripped
    assert blank_id["responses"] == _rows(B1)  # C2: a blank id is no id, so the uuid decides


def test_repeats_within_and_across_forms_give_one_row_per_video(db_path):
    (report,) = _handle(db_path, ("metadata", {"entries": [_uuid("u-a"), _uuid("u-a"), _id("b1"), _id("b1"), _uuid("u-b"), _id("a1")]}, THRESHOLD))
    assert report["responses"] == _rows(A1, B1)  # C2


def test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold(db_path):
    by_id, under, unset = _handle(db_path, ("metadata", {"entries": [_id("e1"), _id("a1")]}, None), ("metadata", {"entries": [_uuid("u-e"), _uuid("u-a")]}, THRESHOLD), ("metadata", {"entries": [_uuid("u-e"), _uuid("u-a")]}, None))
    assert by_id["responses"] == _rows(E1, A1)  # control: the fixture's e1 comes back by id when no threshold is set
    assert unset["responses"] == _rows(E1, A1)  # C2: u-e resolves in its first-match place with no threshold
    assert under["responses"] == _rows(A1)  # C2: e1 (error_count 5) is not a match at threshold 3


def test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock(db_path):
    malformed = ["x", {"video_id": "a1", "instance_domain": "  "}, {"instance_domain": HOST}, {"video_uuid": "u-a"}, {"video_id": "a1", "instance_domain": 7}]
    not_a_list, no_entries, all_malformed = _handle(db_path, ("metadata", {"entries": "x"}, THRESHOLD), ("metadata", {}, THRESHOLD), ("metadata", {"entries": malformed}, THRESHOLD))
    assert (not_a_list["responses"], not_a_list["enters"]) == (MISSING_ENTRIES, 0)
    assert (no_entries["responses"], no_entries["enters"]) == (MISSING_ENTRIES, 0)
    assert (all_malformed["responses"], all_malformed["enters"]) == (NO_ROWS, 0)


def test_centroids_looks_up_only_the_id_entries(db_path):
    uuid_only, mixed = _handle(db_path, ("centroids", {"entries": [_uuid("u-a")]}, THRESHOLD), ("centroids", {"entries": [_uuid("u-b"), _id("a1")]}, THRESHOLD))
    assert uuid_only["embedding_entries"] == [[]]
    assert uuid_only["responses"] == [[200, {"ok": True, "space": None, "centroids": []}]]
    assert mixed["embedding_entries"] == [[_id("a1")]]
    assert mixed["responses"] == [[200, {"ok": True, "space": None, "centroids": [[0.707107, 0.707107, 0.0]]}]]  # a1's (1, 1, 0) at unit length alone (observed); b1's (2, 1, 0) would add a second centroid
