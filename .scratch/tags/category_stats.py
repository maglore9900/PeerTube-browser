"""Read-only category distribution over whitelist.db's embedded videos."""
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
for category, count in conn.execute(
    """
    SELECT v.category, COUNT(*) FROM videos v JOIN video_embeddings e
      ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
    GROUP BY v.category ORDER BY 2 DESC
    """
):
    print(repr(category), count)
