"""Probe: observe the hash values, normalize_host on the test inputs, and the planned DDL's behaviour on the checkpoint's fixture."""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host  # noqa: E402

HOST = "peertube.example"
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
TABLE = """CREATE TABLE IF NOT EXISTS video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, ann_id INTEGER NOT NULL{check}, PRIMARY KEY (video_id, instance_domain), FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain))"""
INDEX = "CREATE UNIQUE INDEX IF NOT EXISTS idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
TRIGGER = """CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision BEFORE INSERT ON video_embeddings WHEN EXISTS (SELECT 1 FROM video_embeddings WHERE ann_id = NEW.ann_id AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)) BEGIN SELECT RAISE(ABORT, 'collision'); END"""
TRIGGER_ANY = """CREATE TRIGGER IF NOT EXISTS video_embeddings_ann_id_collision BEFORE INSERT ON video_embeddings WHEN EXISTS (SELECT 1 FROM video_embeddings WHERE ann_id = NEW.ann_id) BEGIN SELECT RAISE(ABORT, 'collision'); END"""


def blake63(key: bytes, order: str = "big", mask: bool = True) -> int:
    value = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), order)
    return value & ((1 << 63) - 1) if mask else value


def test_values():
    print("\nPIN abc big masked", blake63(b"abc::peertube.example"))
    print("PIN abc big unmasked", blake63(b"abc::peertube.example", mask=False))
    print("PIN abc little masked", blake63(b"abc::peertube.example", "little"))
    print("PIN abc colon-sep", blake63(b"abc:peertube.example"))
    for raw in ("Peertube.Example.", "https://peertube.example/w/abc", "  PEERTUBE.EXAMPLE  ", "...", "bad host", "  Bad Host  ", "peertube.example:8080"):
        print("NORM", repr(raw), "->", repr(normalize_host(raw)))
    for key in (b"v::...", b"v::bad host", b"v::  bad host  ", b"v::  Bad Host  "):
        print("FALLBACK", key, blake63(key))


def scenario(label, table_check, guards):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE videos (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, PRIMARY KEY (video_id, instance_domain))")
    conn.executemany("INSERT INTO videos (video_id, instance_domain) VALUES (?, ?)", [(v, HOST) for v in ("v1", "v2", "v3")])
    conn.execute(TABLE.format(check=table_check))
    for g in guards:
        conn.execute(g)

    def write(verb, vid, ann, emb=b"\x01", model="m"):
        conn.execute(f"{verb} INTO video_embeddings ({COLUMNS}) VALUES (?, ?, ?, 1, ?, 't', ?)", (vid, HOST, emb, model, ann))

    def rows():
        return conn.execute(f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id").fetchall()

    write("INSERT", "v1", 111)
    conn.commit()
    out = {}
    for name, action in (
        ("zero", lambda: write("INSERT", "v2", 0)),
        ("insert_collide", lambda: write("INSERT", "v2", 111)),
        ("replace_collide", lambda: write("INSERT OR REPLACE", "v2", 111)),
        ("same_key_replace", lambda: write("INSERT OR REPLACE", "v1", 111, b"\x02", "m2")),
    ):
        before = rows()
        try:
            action()
            out[name] = ("ok", rows())
        except sqlite3.Error as exc:
            out[name] = (type(exc).__name__, str(exc), rows() == before)
        conn.rollback()
    write("INSERT", "v2", 222)
    conn.commit()
    before = rows()
    try:
        conn.execute("UPDATE video_embeddings SET ann_id = 111 WHERE video_id = 'v2'")
        out["update_collide"] = ("ok", rows())
    except sqlite3.Error as exc:
        out["update_collide"] = (type(exc).__name__, str(exc), rows() == before)
    conn.execute("UPDATE video_embeddings SET ann_id = 333 WHERE video_id = 'v2'")
    out["update_free"] = [r[-1] for r in rows()]
    print(f"\nSCENARIO {label}")
    for k, v in out.items():
        print("  ", k, v)


def test_scenarios():
    print("\nsqlite", sqlite3.sqlite_version)
    scenario("planned", " CHECK (ann_id > 0)", [INDEX, TRIGGER])
    scenario("unique-only", " CHECK (ann_id > 0)", [INDEX])
    scenario("trigger-only", " CHECK (ann_id > 0)", [TRIGGER])
    scenario("no-check", "", [INDEX, TRIGGER])
    scenario("trigger-blocks-same-key", " CHECK (ann_id > 0)", [INDEX, TRIGGER_ANY])
