"""Probe: the flagged share of the random cache the Engine serves random=1 from."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
conn = sqlite3.connect(f"file:{ROOT / 'engine/server/db/random-cache.db'}?mode=ro", uri=True)
print("tables", conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall())
conn.execute("ATTACH DATABASE ? AS w", (f"file:{ROOT / 'engine/server/db/whitelist.db'}?mode=ro",))
total = conn.execute("SELECT COUNT(*) FROM random_rowids").fetchone()[0]
flagged = conn.execute(
    """
    SELECT COUNT(*) FROM random_rowids r
    JOIN w.video_embeddings e ON e.rowid = r.video_rowid
    JOIN w.videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
    WHERE v.nsfw = 1
    """
).fetchone()[0]
print(f"random_rowids={total} flagged={flagged} share={flagged / total:.4%}")
print("mtime", (ROOT / "engine/server/db/random-cache.db").stat().st_mtime)
