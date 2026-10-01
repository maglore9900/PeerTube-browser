"""Probe: 500 random legacy sources read back identically from the migrated live cache."""
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))
from data.similarity_cache import fetch_cached_similarities  # noqa: E402

legacy = sqlite3.connect(f"file:{ROOT / 'delete_me/similarity-cache.legacy.db'}?mode=ro", uri=True)
compact = sqlite3.connect(f"file:{ROOT / 'engine/server/db/similarity-cache.db'}?mode=ro", uri=True)
count = legacy.execute("SELECT MAX(rowid) FROM similarity_sources").fetchone()[0]
random.seed(19)
checked = mismatched = 0
for rowid in random.sample(range(1, count + 1), 500):
    row = legacy.execute("SELECT video_id, instance_domain FROM similarity_sources WHERE rowid = ?", (rowid,)).fetchone()
    if row is None:
        continue
    source = {"video_id": row[0], "instance_domain": row[1]}
    want = [
        {"video_id": a, "instance_domain": b, "score": c, "rank": d}
        for a, b, c, d in legacy.execute(
            "SELECT similar_video_id, similar_instance_domain, score, rank FROM similarity_items WHERE source_video_id = ? AND source_instance_domain = ? ORDER BY rank",
            (row[0], row[1]),
        )
    ]
    got = fetch_cached_similarities(compact, source, 1000)
    checked += 1
    if got != want:
        mismatched += 1
        print("MISMATCH", source, want[:2], got[:2])
print(f"checked={checked} mismatched={mismatched}")
