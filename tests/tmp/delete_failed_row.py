"""Delete one failed translate row so the video can be queued again: argv video_id, host."""
import sqlite3
import sys

conn = sqlite3.connect("engine/server/db/subtitles.db", timeout=30)
with conn:
    before = conn.execute("SELECT video_id, instance_domain, state, error FROM subtitles WHERE video_id = ? AND instance_domain = ?", sys.argv[1:3]).fetchall()
    deleted = conn.execute("DELETE FROM subtitles WHERE video_id = ? AND instance_domain = ? AND target_language = 'en' AND state = 'failed'", sys.argv[1:3]).rowcount
print("before:", before)
print("deleted:", deleted)
print("after:", conn.execute("SELECT COUNT(*) FROM subtitles WHERE video_id = ? AND instance_domain = ?", sys.argv[1:3]).fetchone()[0])
conn.close()
