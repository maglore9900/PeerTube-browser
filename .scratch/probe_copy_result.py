import sqlite3

conn = sqlite3.connect("file:engine/crawler/data/crawl.db?mode=ro", uri=True)
conn.execute("ATTACH DATABASE 'file:engine/server/db/whitelist.db?mode=ro' AS w")
print("crawl videos:", conn.execute("SELECT COUNT(*) FROM main.videos").fetchone()[0])
print("crawl has language column:", "language" in [r[1] for r in conn.execute("PRAGMA main.table_info(videos)")])
print("whitelist videos missing from crawl:", conn.execute(
    "SELECT COUNT(*) FROM w.videos s WHERE NOT EXISTS (SELECT 1 FROM main.videos m WHERE m.video_id = s.video_id AND m.instance_domain = s.instance_domain)").fetchone()[0])
