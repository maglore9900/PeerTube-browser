import sqlite3

wl = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
print("whitelist NULL tags:", wl.execute("SELECT COUNT(*) FROM videos WHERE tags_json IS NULL").fetchone()[0],
      "of", wl.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
newest = wl.execute("SELECT video_id, instance_domain, published_at, last_checked_at FROM videos ORDER BY published_at DESC LIMIT 5").fetchall()
print("whitelist newest:", newest)
oldest_null = wl.execute("SELECT MIN(published_at), MAX(published_at) FROM videos WHERE tags_json IS NULL").fetchone()
print("NULL published_at range:", oldest_null)
try:
    cr = sqlite3.connect("file:engine/crawler/data/crawl.db?mode=ro", uri=True)
    print("crawl NULL tags:", cr.execute("SELECT COUNT(*) FROM videos WHERE tags_json IS NULL").fetchone()[0],
          "of", cr.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
    for vid, host, *_ in newest:
        row = cr.execute("SELECT tags_json FROM videos WHERE video_id=? AND instance_domain=?", (vid, host)).fetchone()
        print("crawl row for", vid[:8], host, "->", row)
except Exception as exc:
    print("crawl.db:", exc)
