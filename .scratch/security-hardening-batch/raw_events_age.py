"""Read-only: how many interaction_raw_events rows a 30-day strip would touch."""
import sqlite3
import time

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
cutoff_ms = int((time.time() - 30 * 86400) * 1000)
total, stale, oldest, newest, actors = conn.execute(
    """
    SELECT COUNT(*), SUM(ingested_at < ?), MIN(ingested_at), MAX(ingested_at),
           COUNT(DISTINCT actor_id)
    FROM interaction_raw_events
    """,
    (cutoff_ms,),
).fetchone()
fmt = lambda ms: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ms / 1000)) if ms else None
print(f"rows={total} older_than_30d={stale or 0} oldest={fmt(oldest)} newest={fmt(newest)} actors={actors}")
for row in conn.execute(
    "SELECT actor_id, COUNT(*) FROM interaction_raw_events GROUP BY actor_id ORDER BY 2 DESC LIMIT 8"
):
    print(row)
