import sqlite3

for label, uri in (("crawl copy", "file:.scratch/crawl-copy.db"), ("crawl original ro", "file:engine/crawler/data/crawl.db?mode=ro"), ("whitelist ro", "file:engine/server/db/whitelist.db?mode=ro")):
    try:
        conn = sqlite3.connect(uri, uri=True)
        print(label, "tables:", conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0], "videos:", conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
    except Exception as exc:
        print(label, "->", repr(exc))
