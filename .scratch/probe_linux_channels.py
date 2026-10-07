import json
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
rows = conn.execute("SELECT instance_domain, channel_id, tags_json, nsfw FROM videos WHERE tags_json LIKE '%linux%' ORDER BY published_at DESC, video_id DESC").fetchall()
page = []
for host, channel, tags, nsfw in rows:
    try:
        parsed = json.loads(tags)
    except ValueError:
        continue
    if nsfw != 1 and isinstance(parsed, list) and any(isinstance(t, str) and t.strip().lower() == "linux" for t in parsed):
        page.append((host, channel))
    if len(page) == 50:
        break
print(len(page), "rows,", len(set(page)), "channels; first channel holds", page.count(page[0]))
