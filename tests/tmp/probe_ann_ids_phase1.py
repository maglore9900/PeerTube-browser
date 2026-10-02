import hashlib
import sqlite3
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2] / "engine" / "server"
sys.path.insert(0, str(SERVER_DIR))

from data.moderation import normalize_host  # noqa: E402

TABLE = """CREATE TABLE video_embeddings (video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, embedding BLOB NOT NULL, embedding_dim INTEGER NOT NULL, model_name TEXT NOT NULL, created_at TEXT NOT NULL, ann_id INTEGER NOT NULL{check}, PRIMARY KEY (video_id, instance_domain), FOREIGN KEY (video_id, instance_domain) REFERENCES videos (video_id, instance_domain))"""
INDEX = "CREATE UNIQUE INDEX idx_video_embeddings_ann_id ON video_embeddings (ann_id)"
TRIGGER = """CREATE TRIGGER video_embeddings_ann_id_collision BEFORE INSERT ON video_embeddings WHEN EXISTS (SELECT 1 FROM video_embeddings WHERE ann_id = NEW.ann_id AND (video_id <> NEW.video_id OR instance_domain <> NEW.instance_domain)) BEGIN SELECT RAISE(ABORT, 'collision'); END"""
COLUMNS = "video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id"
HOST = "peertube.example"


def h(text, endian="big", mask=True):
    v = int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), endian)
    return v & ((1 << 63) - 1) if mask else v


def test_values():
    print("abc", h("abc::peertube.example"), h("abc::peertube.example", mask=False), h("abc::peertube.example", "little"), h("abc:peertube.example"))
    for s in ["Peertube.Example.", "https://peertube.example/w/abc", "  PEERTUBE.EXAMPLE  ", "...", "bad host", "  Bad Host  "]:
        print(repr(s), repr(normalize_host(s)))
    print("fallback", h("v::..."), h("v::bad host"), h("v::  bad host  "), h("v::  Bad Host  "))


def scenario(tmp_path, check, index, trigger):
    conn = sqlite3.connect(tmp_path / f"{check}{index}{trigger}.db")
    conn.execute(TABLE.format(check=" CHECK (ann_id > 0)" if check else ""))
    if index:
        conn.execute(INDEX)
    if trigger:
        conn.execute(TRIGGER)
    conn.execute(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES ('v1', ?, x'01', 1, 'm', 't', 111)", (HOST,))
    conn.commit()
    out = {}
    for name, sql in [("zero", f"INSERT INTO video_embeddings ({COLUMNS}) VALUES ('v2', '{HOST}', x'01', 1, 'm', 't', 0)"), ("insert", f"INSERT INTO video_embeddings ({COLUMNS}) VALUES ('v2', '{HOST}', x'01', 1, 'm', 't', 111)"), ("replace", f"INSERT OR REPLACE INTO video_embeddings ({COLUMNS}) VALUES ('v2', '{HOST}', x'01', 1, 'm', 't', 111)"), ("same", f"INSERT OR REPLACE INTO video_embeddings ({COLUMNS}) VALUES ('v1', '{HOST}', x'02', 1, 'm2', 't', 111)")]:
        try:
            conn.execute(sql)
            out[name] = "ok"
        except sqlite3.Error as e:
            out[name] = f"{type(e).__name__}: {e}"
        out[name + "_rows"] = conn.execute(f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id").fetchall()
        conn.rollback()
    conn.execute(f"INSERT INTO video_embeddings ({COLUMNS}) VALUES ('v2', '{HOST}', x'01', 1, 'm', 't', 222)")
    try:
        conn.execute("UPDATE video_embeddings SET ann_id = 111 WHERE video_id = 'v2'")
        out["update"] = "ok"
    except sqlite3.Error as e:
        out["update"] = f"{type(e).__name__}: {e}"
    out["update_rows"] = conn.execute(f"SELECT {COLUMNS} FROM video_embeddings ORDER BY video_id").fetchall()
    return out


def test_guards(tmp_path):
    for flags in [(1, 1, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]:
        print("check,index,trigger", flags)
        for k, v in scenario(tmp_path, *flags).items():
            print("  ", k, v)
