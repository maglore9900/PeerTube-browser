import sqlite3

conn = sqlite3.connect("file:engine/crawler/data/crawl.db?mode=ro", uri=True)
conn.execute("ATTACH DATABASE 'file:engine/server/db/whitelist.db?mode=ro' AS w")
print("rows where whitelist has tags and crawl.db has NULL:", conn.execute(
    "SELECT COUNT(*) FROM w.videos s JOIN main.videos m ON m.video_id = s.video_id AND m.instance_domain = s.instance_domain "
    "WHERE m.tags_json IS NULL AND s.tags_json IS NOT NULL").fetchone()[0])
