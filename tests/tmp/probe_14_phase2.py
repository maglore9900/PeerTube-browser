"""Throwaway probe for the phase 2 checkpoint; deleted once the real test carries what it shows."""
from __future__ import annotations

import json
import sqlite3
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "active"))
from conftest import ENGINE_PY  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
HOST = "h.example"
VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")

CHILD = r'''
import json, sqlite3, sys, threading
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from handlers import internal_client_reads as reads

class CountingLock:
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

HANDLERS = {"metadata": reads.handle_internal_videos_metadata, "centroids": reads.handle_internal_dislike_centroids}
conn = sqlite3.connect(sys.argv[3])
conn.row_factory = sqlite3.Row
reports = []
for route, body, threshold in json.loads(sys.argv[4]):
    lock = CountingLock()
    statements = []
    conn.set_trace_callback(lambda sql: statements.append(lock.locked()))
    server = SimpleNamespace(db=conn, db_lock=lock, video_error_threshold=threshold)
    with patch.object(reads, "read_json_body", return_value=body), patch.object(reads, "respond_json") as respond, patch.object(reads, "fetch_embeddings_by_ids", wraps=reads.fetch_embeddings_by_ids) as embeddings:
        HANDLERS[route](object(), server)
    reports.append({"responses": [list(c.args[1:]) for c in respond.call_args_list], "enters": lock.enters, "held_after": lock.locked(), "statements_locked": statements, "embedding_entries": [c.args[1] for c in embeddings.call_args_list]})
print(json.dumps(reports))
'''


def _add(conn, video_id, uuid, n, error_count=0):
    values = {c: f"{c}:{video_id}@{HOST}" for c in VIDEO_TEXT}
    values.update({c: n * 10 + i for i, c in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=HOST, error_count=error_count)
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, 3, 'm')", (video_id, HOST, struct.pack("<3f", float(n), 1.0, 0.0)))


def test_probe(tmp_path):
    print("ENGINE_PY", ENGINE_PY, ENGINE_PY.exists())
    db = sqlite3.connect(tmp_path / "p.db")
    cols = ", ".join([f"{c} TEXT" for c in VIDEO_TEXT] + [f"{c} INTEGER" for c in VIDEO_INT] + ["error_count INTEGER"])
    db.execute(f"CREATE TABLE videos ({cols}, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    _add(db, "a1", "u-a", 1)
    _add(db, "b1", "u-b", 2)
    _add(db, "e1", "u-e", 6, error_count=5)
    db.commit()
    db.close()
    mixed = [{"video_uuid": "u-b", "instance_domain": HOST}, {"video_id": "a1", "instance_domain": HOST}, {"video_id": "b1", "instance_domain": HOST}, {"video_uuid": "u-a", "instance_domain": HOST}, {"video_uuid": "u-x", "instance_domain": HOST}]
    cases = [
        ["metadata", {"entries": mixed}, 3],
        ["metadata", {"entries": [{"video_id": "a1", "instance_domain": HOST}, {"video_id": "b1", "instance_domain": HOST}, {"video_id": "a1", "instance_domain": HOST}]}, 3],
        ["metadata", {"entries": "x"}, 3],
        ["metadata", {}, 3],
        ["metadata", {"entries": ["x", {"video_id": "a1", "instance_domain": "  "}, {"instance_domain": HOST}]}, 3],
        ["centroids", {"entries": [{"video_uuid": "u-a", "instance_domain": HOST}]}, 3],
        ["centroids", {"entries": [{"video_uuid": "u-b", "instance_domain": HOST}, {"video_id": "a1", "instance_domain": HOST}]}, 3],
    ]
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR), str(API_DIR), str(tmp_path / "p.db"), json.dumps(cases)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    print("rc", run.returncode)
    print("stderr", run.stderr[-2000:])
    for case, report in zip(cases, json.loads(run.stdout)):
        for response in report["responses"]:
            if isinstance(response[1], dict) and "rows" in response[1]:
                response[1]["rows"] = [(row["video_id"], len(row)) for row in response[1]["rows"]]
        print(case[0], json.dumps(case[1])[:80], "->", json.dumps(report))
