"""Throwaway (issue 41 triage): similarity-cache entry sizes, read-only."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "engine" / "server" / "db" / "similarity-cache.db"
NEIGHBOUR_BYTES = 8  # struct "<if" in data/similarity_cache.py

conn = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
rows = f"length(neighbours) / {NEIGHBOUR_BYTES}"

total, smallest, largest, avg = conn.execute(f"SELECT count(*), min({rows}), max({rows}), avg({rows}) FROM similarity_sources").fetchone()
print(f"sources={total} min={smallest} max={largest} avg={avg:.1f}")

buckets = [(0, 0), (1, 9), (10, 29), (30, 47), (48, 99), (100, 299), (300, 999), (1000, 10**9)]
for low, high in buckets:
    n = conn.execute(f"SELECT count(*) FROM similarity_sources WHERE {rows} BETWEEN ? AND ?", (low, high)).fetchone()[0]
    print(f"  {low:>5}-{high if high < 10**9 else 'max':<5} rows: {n}")

print("computed_at values:", conn.execute("SELECT count(DISTINCT computed_at), min(computed_at), max(computed_at) FROM similarity_sources").fetchone())

print("sample sources with 10-29 rows (ordered by key):")
for key, video_id, domain, n in conn.execute(
    f"SELECT s.source_key, k.video_id, k.instance_domain, {rows} FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key WHERE {rows} BETWEEN 10 AND 29 ORDER BY s.source_key LIMIT 5"
):
    print(f"  key={key} {video_id}@{domain} rows={n}")
sys.exit(0)
