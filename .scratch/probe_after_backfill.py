import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
print("NULL tags:", conn.execute("SELECT COUNT(*) FROM videos WHERE tags_json IS NULL").fetchone()[0])
newest = conn.execute("SELECT tags_json FROM videos ORDER BY published_at DESC, video_id DESC LIMIT 50").fetchall()
print("newest 50 with non-empty tags:", sum(1 for (t,) in newest if t and t != "[]"))
print("fts hits for linux:", conn.execute("SELECT COUNT(*) FROM videos_fts WHERE videos_fts MATCH 'tags_json : \"linux\"'").fetchone()[0])
