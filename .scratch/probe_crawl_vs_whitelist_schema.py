import sqlite3

def cols(path, table):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()

crawl, white = "engine/crawler/data/crawl.db", "engine/server/db/whitelist.db"
for table in ("videos", "channels", "instances", "video_embeddings"):
    c, w = cols(crawl, table), cols(white, table)
    print(table, "crawl:", len(c), "whitelist:", len(w), "whitelist-only:", [x for x in w if x not in c], "crawl-only:", [x for x in c if x not in w])
