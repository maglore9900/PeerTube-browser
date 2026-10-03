"""Probe: observe today's behaviour behind the phase-2 checkpoint's expectations."""
from __future__ import annotations

import importlib.util
import logging
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import data.db as db  # noqa: E402
import data.random_cache as random_cache  # noqa: E402
from data.ann_ids import compute_ann_id  # noqa: E402
from data.metadata import fetch_metadata  # noqa: E402

HOST = "a.example"


def test_probe_fetch_metadata_on_sync_schema(tmp_path):
    spec = importlib.util.spec_from_file_location("sw_probe", SERVER_DIR / "db" / "jobs" / "sync-whitelist.py")
    sync_job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_job)
    conn = sqlite3.connect(tmp_path / "e.db")
    conn.row_factory = sqlite3.Row
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    for label in ["D", "C", "B", "A"]:
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, nsfw, last_checked_at) VALUES (?, ?, ?, ?, ?, 0, 1)", (label, f"u-{label}", HOST, f"ch-{label}", f"title {label}"))
        conn.execute("INSERT INTO video_embeddings (video_id, instance_domain, embedding, embedding_dim, model_name, created_at, ann_id) VALUES (?, ?, x'00', 1, 'm', 'now', ?)", (label, HOST, compute_ann_id(label, HOST)))
    conn.commit()
    ids = [compute_ann_id("C", HOST), 1, compute_ann_id("A", HOST), compute_ann_id("gone", HOST)]
    out = fetch_metadata(conn, ids)
    print("METADATA", {k: (v["video_id"], v["instance_domain"], v["title"]) for k, v in out.items()})
    print("ROWID1", [tuple(r) for r in conn.execute("SELECT rowid, video_id FROM video_embeddings ORDER BY rowid")])


def test_probe_filtered_cap_today(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE videos (video_id TEXT, instance_domain TEXT, channel_id TEXT)")
    conn.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, ann_id INTEGER NOT NULL)")
    for i in range(1, 21):
        conn.execute("INSERT INTO videos VALUES (?, ?, ?)", (f"v{i}", HOST, f"c{i % 3}"))
        conn.execute("INSERT INTO video_embeddings VALUES (?, ?, ?)", (f"v{i}", HOST, compute_ann_id(f"v{i}", HOST)))
    conn.commit()
    conn.close()
    src = db.connect_readonly_db(path)
    cache = random_cache.connect_random_cache_db(tmp_path / "c.db")
    built = random_cache.populate_random_cache(src, cache, 100, True, True, 0, 2)
    rows = [r[0] for r in cache.execute("SELECT video_rowid FROM random_rowids")]
    print("CAP", built, Counter(f"c{r % 3}" for r in rows))
    calls = []
    real = random_cache.random

    def randint(low, high):
        calls.append((low, high))
        return high

    random_cache.random = SimpleNamespace(randint=randint, shuffle=random.shuffle)
    try:
        cache2 = random_cache.connect_random_cache_db(tmp_path / "c2.db")
        built2 = random_cache.populate_random_cache(src, cache2, 5, True, False, 0, 0)
        print("WRAP", built2, calls, sorted(r[0] for r in cache2.execute("SELECT video_rowid FROM random_rowids")))
    finally:
        random_cache.random = real


def test_probe_log_message(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    path = tmp_path / "e" / "random-cache.db"
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    conn.commit()
    conn.close()
    other = tmp_path / "o" / "random-cache.db"
    other.parent.mkdir()
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE random_ann_ids (position INTEGER PRIMARY KEY, ann_id INTEGER NOT NULL)")
    conn.commit()
    conn.close()
    random_cache.open_random_cache_if_usable(path)
    random_cache.open_random_cache_if_usable(other)
    print("MESSAGES", caplog.messages, "PATH", path)
    assert False, "probe: show output"
