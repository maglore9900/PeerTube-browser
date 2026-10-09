"""One-off (plan 56): delete translate jobs that failed only on the duration cap, so they can be requested again."""
import sqlite3

conn = sqlite3.connect("engine/server/db/subtitles.db", timeout=30)
where = "state = 'failed' AND (error LIKE 'duration %' OR error LIKE 'audio longer than %')"
with conn:
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute(f"SELECT video_id, instance_domain, error FROM subtitles WHERE {where}").fetchall()
    for row in rows:
        print("delete", row)
    deleted = conn.execute(f"DELETE FROM subtitles WHERE {where}").rowcount
print("deleted", deleted)
print("remaining", conn.execute("SELECT state, count(*) FROM subtitles GROUP BY state").fetchall())
