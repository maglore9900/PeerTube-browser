"""Probe: the seed lookups in data.embeddings return the same seeds before and after the SELECT consolidation, run under the Engine interpreter."""
from __future__ import annotations

import json
import subprocess

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

CHILD = r'''
import json, sqlite3, sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from data import embeddings

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE videos (video_id TEXT, video_uuid TEXT, channel_id TEXT, instance_domain TEXT, title TEXT)")
conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, ann_id INTEGER)")
rows = [("v1", "u1", "c1", "a.example", "T1", 11), ("v1", "u1b", "c2", "b.example", "T1b", 12), ("v2", "u2", "c3", "a.example", "T2", 13)]
for video_id, uuid, channel, host, title, ann_id in rows:
    conn.execute("INSERT INTO videos VALUES (?, ?, ?, ?, ?)", (video_id, uuid, channel, host, title))
    conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?, 2, ?)", (video_id, host, np.array([ann_id, 1], dtype=np.float32).tobytes(), ann_id))
conn.execute("INSERT INTO videos VALUES ('v3', 'u3', 'c4', 'a.example', 'T3')")
conn.execute("INSERT INTO video_embeddings VALUES ('v3', 'a.example', ?, 2, 14)", (np.array([1], dtype=np.float32).tobytes(),))

def brief(seed):
    return None if seed is None else [seed["ann_id"], seed["video_id"], seed["video_uuid"], seed["channel_id"], seed["instance_domain"], seed["title"], seed["embedding"].tolist()]

single = {
    "uuid_host": brief(embeddings.fetch_seed_embedding(conn, None, "b.example", "u1b")),
    "uuid_wrong_host_falls_to_id": brief(embeddings.fetch_seed_embedding(conn, "v2", "a.example", "u1b")),
    "id_host": brief(embeddings.fetch_seed_embedding(conn, "v1", "b.example", None)),
    "id_no_host": brief(embeddings.fetch_seed_embedding(conn, "v2", None, None)),
    "short": brief(embeddings.fetch_seed_embedding(conn, "v3", "a.example", None)),
    "missing": brief(embeddings.fetch_seed_embedding(conn, "nope", None, None)),
    "none": brief(embeddings.fetch_seed_embedding(conn, None, None, None)),
}
likes = embeddings.fetch_seed_embeddings_for_likes(conn, [{"video_uuid": "u1", "instance_domain": "a.example"}, {"video_id": "v2", "instance_domain": "a.example"}, {"video_id": "v1", "instance_domain": "b.example", "video_uuid": "u1b"}, {"video_id": "v3", "instance_domain": "a.example"}])
print(json.dumps({"single": single, "likes": {key: brief(seed) for key, seed in likes.items()}, "empty": embeddings.fetch_seed_embeddings_for_likes(conn, [])}))
'''


def test_probe():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(ROOT / "engine" / "server")], capture_output=True, text=True, timeout=60)
    print(run.stdout, run.stderr)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out["single"] == {
        "uuid_host": [12, "v1", "u1b", "c2", "b.example", "T1b", [12.0, 1.0]],
        "uuid_wrong_host_falls_to_id": [13, "v2", "u2", "c3", "a.example", "T2", [13.0, 1.0]],
        "id_host": [12, "v1", "u1b", "c2", "b.example", "T1b", [12.0, 1.0]],
        "id_no_host": [13, "v2", "u2", "c3", "a.example", "T2", [13.0, 1.0]],
        "short": None,
        "missing": None,
        "none": None,
    }
    assert {key: seed[0] for key, seed in out["likes"].items()} == {"uuid::u1::a.example": 11, "uuid::u1b::b.example": 12, "uuid::u2::a.example": 13, "v1::a.example": 11, "v1::b.example": 12, "v2::a.example": 13}
    assert out["empty"] == {}
