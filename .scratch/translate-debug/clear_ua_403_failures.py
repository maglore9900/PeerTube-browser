"""One-off: delete the two translate jobs that failed on HTTP 403 to Python-urllib's User-Agent, so they can be requested again."""
import sqlite3

KEYS = [("897a658e-c857-48a2-9781-e22b9b27c672", "makertube.net"), ("d8f61a3b-4490-4d6b-baef-8713aa2647ba", "video.toby3d.me")]
where = "video_id = ? AND instance_domain = ? AND state = 'failed' AND error = 'video JSON fetch failed: HTTP 403'"

conn = sqlite3.connect("engine/server/db/subtitles.db", timeout=30)
with conn:
    conn.execute("BEGIN IMMEDIATE")
    deleted = 0
    for key in KEYS:
        for row in conn.execute(f"SELECT video_id, instance_domain, state, error FROM subtitles WHERE {where}", key):
            print("delete", row)
        deleted += conn.execute(f"DELETE FROM subtitles WHERE {where}", key).rowcount
print("deleted", deleted)
print("remaining", conn.execute("SELECT state, count(*) FROM subtitles GROUP BY state").fetchall())
