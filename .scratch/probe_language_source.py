import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
conn.execute("ATTACH DATABASE 'file:engine/crawler/data/crawl.db?mode=ro' AS crawl")
total = conn.execute("SELECT COUNT(*) FROM videos WHERE language IS NOT NULL").fetchone()[0]
in_crawl = conn.execute(
    "SELECT COUNT(*) FROM videos w WHERE language IS NOT NULL AND EXISTS "
    "(SELECT 1 FROM crawl.videos c WHERE c.video_id = w.video_id AND c.instance_domain = w.instance_domain)"
).fetchone()[0]
print("whitelist videos with language:", total, "of which also in crawl.db:", in_crawl)
