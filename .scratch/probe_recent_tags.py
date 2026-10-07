import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
rows = conn.execute("SELECT tags_json FROM videos ORDER BY published_at DESC, video_id DESC LIMIT 2000").fetchall()
first_tagged = next((i for i, (t,) in enumerate(rows) if t and t.startswith('["')), None)
print("recent: rows before the first tagged one:", first_tagged, "NULL in newest 100:", sum(1 for (t,) in rows[:100] if t is None))
channel = ("play.cotv.org.br", "7")
rows = conn.execute("SELECT tags_json FROM videos WHERE instance_domain=? AND channel_id=? ORDER BY published_at DESC LIMIT 200", channel).fetchall()
print("followed channel newest 30:", sorted({repr(t)[:20] for (t,) in rows[:30]}), "first tagged at", next((i for i, (t,) in enumerate(rows) if t and t.startswith('["')), None))
