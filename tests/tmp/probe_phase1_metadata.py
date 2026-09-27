"""Throwaway probe for the phase 1 checkpoint; deleted once the real test carries what it shows."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "engine" / "server", ROOT / "engine" / "server" / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import metadata  # noqa: E402

VIDEO_TEXT = ("video_id", "video_uuid", "instance_domain", "channel_id", "channel_name", "channel_url", "account_name", "account_url", "title", "description", "tags_json", "category", "published_at", "video_url", "thumbnail_url", "embed_path", "preview_path", "last_checked_at")
VIDEO_INT = ("video_numeric_id", "duration", "views", "likes", "dislikes", "comments_count", "nsfw")


def _db(tmp_path):
    conn = sqlite3.connect(tmp_path / "p.db")
    conn.row_factory = sqlite3.Row
    cols = ", ".join([f"{c} TEXT" for c in VIDEO_TEXT] + [f"{c} INTEGER" for c in VIDEO_INT] + ["error_count INTEGER"])
    conn.execute(f"CREATE TABLE videos ({cols}, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    conn.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    return conn


def _add(conn, video_id, uuid, host, error_count, n, embedded=True):
    values = {c: f"{c}:{video_id}@{host}" for c in VIDEO_TEXT}
    values.update({c: n * 10 + i for i, c in enumerate(VIDEO_INT)})
    values.update(video_id=video_id, video_uuid=uuid, instance_domain=host, error_count=error_count)
    conn.execute(f"INSERT INTO videos ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", list(values.values()))
    if embedded:
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (video_id, host))


def test_probe(tmp_path):
    print("sqlite", sqlite3.sqlite_version, sys.executable)
    print("has uuids fn", hasattr(metadata, "fetch_metadata_by_uuids"))
    conn = _db(tmp_path)
    _add(conn, "s2", "u-s", "h.example", 0, 1)
    _add(conn, "s1", "u-s", "h.example", 0, 2)
    _add(conn, "s3", "u-s", "h.example", 0, 3)
    _add(conn, "a1", "u-a", "h.example", 0, 4)
    _add(conn, "a1", "u-a", "other.example", 0, 5)
    _add(conn, "n1", "u-n", "h.example", 0, 6, embedded=False)
    _add(conn, "e1", "u-e", "h.example", 5, 7)
    conn.execute("INSERT INTO channels VALUES ('channel_id:a1@h.example', 'h.example', 'Chan A', 'ava')")
    conn.commit()
    where = "(v.video_uuid, v.instance_domain) IN ((?, ?))"
    base = "SELECT v.video_id FROM video_embeddings e JOIN videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain LEFT JOIN channels c ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain WHERE "
    print("order u-s", [r[0] for r in conn.execute(base + where, ("u-s", "h.example"))])
    print("order u-s thr", [r[0] for r in conn.execute(base + where + " AND (v.error_count IS NULL OR v.error_count < ?)", ("u-s", "h.example", 3))])
    print("plan", [tuple(r) for r in conn.execute("EXPLAIN QUERY PLAN " + base + where, ("u-s", "h.example"))])
    print("U-A", [r[0] for r in conn.execute(base + where, ("U-A", "h.example"))])
    print("H.EXAMPLE", [r[0] for r in conn.execute(base + where, ("u-a", "H.EXAMPLE"))])
    statements = []
    conn.set_trace_callback(statements.append)
    ids = metadata.fetch_metadata_by_ids(conn, [{"video_id": "a1", "instance_domain": "h.example"}, {"video_id": "n1", "instance_domain": "h.example"}])
    print("traced after 1 call", len(statements))
    statements.clear()
    print("empty", metadata.fetch_metadata_by_ids(conn, []), len(statements))
    conn.set_trace_callback(None)
    print("ids", {k: dict(v) for k, v in ids.items()})
    print("nkeys", [len(v) for v in ids.values()])
    bulk = [{"video_id": f"c{i:03d}", "instance_domain": "bulk.example"} for i in range(460)]
    for i in range(460):
        _add(conn, f"c{i:03d}", f"uc{i:03d}", "bulk.example", 5 if i == 455 else 0, 100 + i)
    conn.commit()
    got = metadata.fetch_metadata_by_ids(conn, bulk, error_threshold=3)
    print("bulk ids", len(got), "c455 in", "c455::bulk.example" in got)
    uuid_where = "(v.video_uuid, v.instance_domain) IN (" + ", ".join(["(?, ?)"] * 450) + ")"
    params = [v for i in range(450) for v in (f"uc{i:03d}", "bulk.example")] + [3]
    print("450 pairs + threshold rows", len(conn.execute(base + uuid_where + " AND (v.error_count IS NULL OR v.error_count < ?)", params).fetchall()))
