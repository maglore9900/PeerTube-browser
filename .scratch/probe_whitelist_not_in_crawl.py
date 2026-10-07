import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
conn.execute("ATTACH DATABASE 'file:engine/crawler/data/crawl.db?mode=ro' AS crawl")
missing = conn.execute(
    "SELECT COUNT(*), MIN(published_at), MAX(published_at) FROM videos w "
    "WHERE NOT EXISTS (SELECT 1 FROM crawl.videos c WHERE c.video_id = w.video_id AND c.instance_domain = w.instance_domain)"
).fetchone()
embedded = conn.execute(
    "SELECT COUNT(*) FROM video_embeddings e "
    "WHERE NOT EXISTS (SELECT 1 FROM crawl.videos c WHERE c.video_id = e.video_id AND c.instance_domain = e.instance_domain)"
).fetchone()[0]
print("whitelist videos not in crawl.db:", missing, "with embeddings:", embedded)
