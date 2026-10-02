from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host  # noqa: E402

TRIGGER = """
CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision
BEFORE INSERT ON video_embeddings
WHEN EXISTS (
  SELECT 1 FROM video_embeddings
  WHERE ann_id = NEW.ann_id
    AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)
)
BEGIN
  SELECT RAISE(ABORT, 'collision');
END
"""


def test_probe(tmp_path):
    print("LITERAL", int.from_bytes(hashlib.blake2b(b"abc::peertube.example", digest_size=8).digest(), "big") & ((1 << 63) - 1))
    print("UNMASKED", int.from_bytes(hashlib.blake2b(b"abc::peertube.example", digest_size=8).digest(), "big"))
    print("LITTLE", int.from_bytes(hashlib.blake2b(b"abc::peertube.example", digest_size=8).digest(), "little") & ((1 << 63) - 1))
    for value in ("Peertube.Example.", "peertube.example", "...", "bad host", "  Bad Host  "):
        print("NORM", repr(value), repr(normalize_host(value)))
    for raw in (b"v::...", b"v::bad host"):
        print("FALLBACK", raw, int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big") & ((1 << 63) - 1))
    print("SQLITE", sqlite3.sqlite_version)
    conn = sqlite3.connect(tmp_path / "p.db")
    conn.execute("CREATE TABLE videos (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, ann_id INTEGER NOT NULL CHECK (ann_id > 0), PRIMARY KEY (video_id, instance_domain), FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain))")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)")
    conn.execute(TRIGGER)
    ins = "INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, 'h', x'01', 1, 'm', 't', ?)"
    conn.execute(ins, ("v1", 111))
    conn.commit()
    for label, sql, params in (("zero", ins, ("v2", 0)), ("plain", ins, ("v2", 111)), ("replace", ins.replace("INSERT", "INSERT OR REPLACE"), ("v2", 111))):
        try:
            conn.execute(sql, params)
            print("OUTCOME", label, "no raise")
        except Exception as exc:
            print("OUTCOME", label, type(exc).__name__, exc)
        print("ROWS", label, conn.execute("SELECT video_id, ann_id FROM video_embeddings ORDER BY video_id").fetchall(), conn.in_transaction)
    conn.execute(ins, ("v2", 222))
    try:
        conn.execute("UPDATE video_embeddings SET ann_id = 111 WHERE video_id = 'v2'")
        print("OUTCOME update no raise")
    except Exception as exc:
        print("OUTCOME update", type(exc).__name__, exc)
    conn.execute("INSERT OR REPLACE INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES ('v1', 'h', x'02', 1, 'm2', 't', 111)")
    print("SAMEKEY", conn.execute("SELECT video_id, embedding, model_name, ann_id FROM video_embeddings ORDER BY video_id").fetchall())
    # UNIQUE-only control: the wrong implementation the OR REPLACE case must exclude
    conn.execute("DROP TRIGGER video_embeddings_ann_id_collision")
    conn.execute(ins.replace("INSERT", "INSERT OR REPLACE"), ("v3", 111))
    print("UNIQUE_ONLY", conn.execute("SELECT video_id, ann_id FROM video_embeddings ORDER BY video_id").fetchall())
