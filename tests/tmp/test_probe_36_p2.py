"""Probe: today's get_upnext_candidates ladder and fetch_random_rows_from_cache draws on the phase-2 fixtures."""
from __future__ import annotations

import sqlite3
import sys
import threading
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from data import random_cache, random_videos, similarity_candidates  # noqa: E402

HOST = "h.example"


def _db(videos):
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE videos (video_id TEXT NOT NULL, video_uuid TEXT, video_numeric_id INTEGER, instance_domain TEXT NOT NULL, channel_id TEXT, channel_name TEXT, channel_url TEXT, account_name TEXT, account_url TEXT, title TEXT, description TEXT, tags_json TEXT, category TEXT, published_at INTEGER, video_url TEXT, duration INTEGER, thumbnail_url TEXT, embed_path TEXT, views INTEGER, likes INTEGER, dislikes INTEGER, comments_count INTEGER, nsfw INTEGER, preview_path TEXT, popularity REAL NOT NULL DEFAULT 0, last_checked_at INTEGER NOT NULL, error_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE video_embeddings (video_id TEXT, instance_domain TEXT, embedding BLOB, embedding_dim INTEGER, model_name TEXT, PRIMARY KEY (video_id, instance_domain))")
    db.execute("CREATE TABLE channels (channel_id TEXT, instance_domain TEXT, display_name TEXT, avatar_url TEXT)")
    for label, nsfw, channel, errors in videos:
        db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, nsfw, last_checked_at, error_count) VALUES (?, ?, ?, ?, ?, 0, ?)", (label, f"u-{label}", HOST, channel, nsfw, errors))
        db.execute("INSERT INTO video_embeddings VALUES (?, ?, x'00', 3, 'm')", (label, HOST))
    db.commit()
    return db


def test_env():
    print("python", sys.executable, sys.version)
    try:
        import numpy  # noqa: F401
        print("numpy importable")
    except ImportError as exc:
        print("numpy missing", exc)
    try:
        import faiss  # noqa: F401
        print("faiss importable")
    except ImportError as exc:
        print("faiss missing", exc)


def _upnext(monkeypatch, script, author_limit, **policy):
    db = _db([(label, nsfw, channel, 0) for label, (score, nsfw, channel) in {k: v for step in script.values() for k, v in step.items()}.items()])
    calls = []

    def stub(server, seed, nprobe, search_limit, min_score):
        calls.append((nprobe, search_limit, min_score))
        return [{"video_id": label, "instance_domain": HOST, "score": score} for label, (score, _, _) in script[(nprobe, search_limit)].items()], 7

    monkeypatch.setitem(sys.modules, "data.ann", types.SimpleNamespace(search_similar_above=stub))
    server = SimpleNamespace(db=db, db_lock=threading.Lock(), similarity_max_per_author=author_limit, enable_instance_ignore=False, enable_channel_blocklist=False)
    seed = {"video_id": "S", "instance_domain": HOST, "channel_id": "ch-S", "embedding": [0.0]}
    base = dict(top_k=48, target_min_pool=5, nprobe=1, search_limit=10, max_nprobe=8, max_search_limit=80, min_score=0.5, tail_min_score=0.3, cache_limit=20)
    base.update(policy)
    rows, stats = similarity_candidates.get_upnext_candidates(server, seed, similarity_candidates.UpnextPoolPolicy(**base))
    return calls, [row["video_id"] for row in rows], stats


def test_upnext_ladder_today(monkeypatch):
    s1 = {"X1": (0.95, 1, "ch-X1"), "A": (0.9, 0, "ch-A")}
    s2 = {**s1, "X2": (0.85, 1, "ch-X2")}
    s3 = {**s2, "L": (0.4, None, "ch-L")}
    s4 = {**s3, "B": (0.8, None, "ch-B"), "C": (0.75, 0, "ch-C")}
    print("ladder", _upnext(monkeypatch, {(1, 10): s1, (2, 20): s2, (4, 40): s3, (8, 80): s4}, 0))
    y1 = {"X1": (0.95, 1, "ch-X"), "A": (0.9, 0, "ch-A")}
    y2 = {**y1, "X2": (0.85, 1, "ch-X2")}
    y3 = {**y2, "Y": (0.8, None, "ch-X")}
    y4 = {**y3, "B": (0.78, None, "ch-B"), "C": (0.76, 0, "ch-C")}
    print("ladder-y", _upnext(monkeypatch, {(1, 10): y1, (2, 20): y2, (4, 40): y3, (8, 80): y4}, 1))
    t1 = {"X1": (0.95, 1, "ch-X1"), "A": (0.9, 0, "ch-A")}
    t3 = {**t1, "B": (0.8, None, "ch-B"), "C": (0.75, 0, "ch-C")}
    print("stall", _upnext(monkeypatch, {(1, 10): t1, (2, 20): t1, (4, 40): t3, (8, 80): t3}, 0))
    cap = {"X1": (0.95, 1, "ch-A"), "X2": (0.92, 1, "ch-X2"), "A": (0.9, 0, "ch-A"), "B": (0.85, None, "ch-B"), "C": (0.8, 0, "ch-C"), "D": (0.75, None, "ch-D")}
    print("cap", _upnext(monkeypatch, {(1, 10): cap}, 1, top_k=3, target_min_pool=3))


def test_random_cache_today(monkeypatch):
    labels = ["X1", "X2", "A", "B", "C", "X3", "D", "E", "A2"]
    db = _db([(label, 1 if label.startswith("X") else 0, f"ch-{label}", 3 if label == "E" else 0) for label in labels])
    cache = sqlite3.connect(":memory:", check_same_thread=False)
    cache.row_factory = sqlite3.Row
    cache.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    # positions 1..8; rowid of A appears twice
    rowids = [3, 1, 3, 8, 4, 2, 5, 7]
    cache.executemany("INSERT INTO random_rowids VALUES (?, ?)", list(enumerate(rowids, start=1)))
    cache.commit()
    randints = []
    monkeypatch.setattr(random_cache, "random", SimpleNamespace(randint=lambda a, b: randints.append((a, b)) or 0))
    owner = SimpleNamespace(random_cache_db=cache, random_cache_lock=threading.Lock(), db=db, db_lock=threading.Lock())
    rows = random_videos.fetch_random_rows_from_cache(owner, 4, error_threshold=3)
    print("rowid map", [(row[0], row[1]) for row in db.execute("SELECT rowid, video_id FROM video_embeddings ORDER BY rowid")])
    print("today window", [row["video_id"] for row in rows], "randint", randints)
    small = sqlite3.connect(":memory:", check_same_thread=False)
    small.row_factory = sqlite3.Row
    small.execute("CREATE TABLE random_rowids (position INTEGER PRIMARY KEY, video_rowid INTEGER NOT NULL)")
    small.executemany("INSERT INTO random_rowids VALUES (?, ?)", [(1, 1), (2, 3), (3, 2)])
    small.commit()
    randints.clear()
    owner.random_cache_db = small
    print("small", [row["video_id"] for row in random_videos.fetch_random_rows_from_cache(owner, 5)], "randint", randints)
