"""Throwaway probe: whether the phase-2 checkpoint's live premises hold on today's dev whitelist.db, read with the conftest seed's own SELECT on an in-memory copy of trending_ranks."""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ACTIVE_DIR = ROOT / "tests" / "active"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from data import random_videos  # noqa: E402

WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"


def _seed_sql() -> str:
    tree = ast.parse((ACTIVE_DIR / "conftest.py").read_text(encoding="utf-8"))
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "TRENDING_SEED_SQL")


def test_probe_trending_premises():
    seed_sql = _seed_sql()
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    stored = conn.execute("SELECT COUNT(*), MIN(fetched_at), MAX(fetched_at) FROM trending_ranks").fetchone()
    print("STORED RANKS", tuple(stored))
    # The seed's rows, as the fixture would write them now, in a temp schema so the dev DB is not written.
    conn.execute("ATTACH DATABASE ':memory:' AS scratch")
    conn.execute("CREATE TABLE scratch.seed AS SELECT" + seed_sql.split("\nSELECT", 1)[1])
    seeded = {(r[0], r[1], r[2], r[3], r[4]) for r in conn.execute("SELECT instance_domain, video_id, rank, likes, views FROM scratch.seed")}
    current = {(r[0], r[1], r[2], r[3], r[4]) for r in conn.execute("SELECT instance_domain, video_id, rank, likes, views FROM trending_ranks")}
    print("SEED ROWS", len(seeded), "STORED == SEED", seeded == current)
    flagged = {(r[0], r[1]) for r in conn.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    threshold = 3
    head = random_videos.fetch_ordered_page(conn, "trending", 96, 0, error_threshold=threshold, include_nsfw=True)
    print("TRENDING HEAD 96 FLAGGED", sum(1 for r in head if (r["video_id"], r["instance_domain"]) in flagged), "LEN", len(head))
    denied = {r["host"].lower() for r in conn.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(r["channel_id"], r["instance_domain"].lower()) for r in conn.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    filtered = random_videos.fetch_ordered_page(conn, "trending", 200, 0, error_threshold=threshold, include_nsfw=False)
    kept = [r for r in filtered if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked]
    print("TRENDING REFERENCE KEPT OF 200", len(kept))
