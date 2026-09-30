"""Throwaway: snapshot every random_videos listing read over the phase-1 fixture before the refactor, then compare after."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_36_nsfw_filter_phase1 import THRESHOLD, _statements  # noqa: E402
from data import random_videos  # noqa: E402

SNAPSHOT = Path(__file__).with_name("probe_36_refactor_snapshot.json")


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for sql, params in _statements():
        db.execute(sql, params)
    # A future-dated and an undated row, so the recent order's own condition is exercised beside the NSFW one.
    db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, published_at, nsfw, last_checked_at) VALUES ('F', 'u-F', 'h.example', 99999999999999, 0, 0)")
    db.execute("INSERT INTO video_embeddings VALUES ('F', 'h.example', x'00', 3, 'm')")
    db.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, published_at, nsfw, last_checked_at) VALUES ('N', 'u-N', 'h.example', NULL, 1, 0)")
    db.execute("INSERT INTO video_embeddings VALUES ('N', 'h.example', x'00', 3, 'm')")
    db.commit()
    return db


def test_snapshot():
    db = _db()
    out = {}
    for threshold in (None, THRESHOLD):
        for flag in (True, False):
            key = f"{threshold}-{flag}"
            out[f"random-{key}"] = sorted(r["video_id"] for r in random_videos.fetch_random_rows(db, 50, error_threshold=threshold, include_nsfw=flag))
            out[f"recent-{key}"] = [r["video_id"] for r in random_videos.fetch_recent_videos(db, 50, error_threshold=threshold, include_nsfw=flag)]
            out[f"popular-{key}"] = sorted(r["video_id"] for r in random_videos.fetch_popular_videos(db, 4, error_threshold=threshold, include_nsfw=flag))
            for order in ("hot", "popular", "recent"):
                out[f"{order}-page-{key}"] = [r["video_id"] for size, offset in ((3, 0), (3, 3), (50, 1)) for r in random_videos.fetch_ordered_page(db, order, size, offset, error_threshold=threshold, include_nsfw=flag)]
    print(json.dumps(out, indent=1))
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(out, sort_keys=True))
        assert False, "snapshot written"
    assert json.loads(SNAPSHOT.read_text()) == out
