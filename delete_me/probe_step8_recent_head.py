"""Throwaway probe: where the first nsfw-flagged row sits in today's dev whitelist.db Recent order, as the Engine reads it for mode=recent&nsfw=1."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
for path in (SERVER_DIR, SERVER_DIR / "api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from data import random_videos  # noqa: E402

WHITELIST_DB = SERVER_DIR / "db" / "whitelist.db"


def test_probe_recent_head():
    conn = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    flagged = {(r[0], r[1]) for r in conn.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    denied = {r["host"].lower() for r in conn.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(r["channel_id"], r["instance_domain"].lower()) for r in conn.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    print("FLAGGED TOTAL", len(flagged), "NOW MS", int(time.time() * 1000))
    for order in ("recent", "popular", "trending"):
        rows = random_videos.fetch_ordered_page(conn, order, 5000, 0, error_threshold=3, include_nsfw=True)
        kept = [r for r in rows if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked]
        positions = [i for i, r in enumerate(kept) if (r["video_id"], r["instance_domain"]) in flagged]
        print(order.upper(), "KEPT", len(kept), "FLAGGED IN FIRST 96", sum(1 for p in positions if p < 96), "FIRST FLAGGED POSITIONS", positions[:10])
        if order == "recent":
            for i in ([0, 95] + positions[:3]):
                if i < len(kept):
                    r = kept[i]
                    print("  RECENT", i, r["published_at"], r["instance_domain"], r["video_id"], r["nsfw"])
    newest = conn.execute("SELECT MAX(published_at), COUNT(*) FROM videos WHERE published_at > ?", (int(time.time() * 1000) - 7 * 86400000,)).fetchone()
    print("VIDEOS PUBLISHED LAST 7 DAYS (max, count)", tuple(newest))
    newest_flagged = conn.execute("SELECT MAX(v.published_at) FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain WHERE v.nsfw = 1 AND v.published_at <= ?", (int(time.time() * 1000),)).fetchone()
    print("NEWEST EMBEDDED FLAGGED published_at", tuple(newest_flagged))
    print("DB MTIME", WHITELIST_DB.stat().st_mtime)
