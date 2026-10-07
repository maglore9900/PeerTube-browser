import sqlite3

print("scratch copy videos:", sqlite3.connect("file:.scratch/crawl-copy.db?mode=ro", uri=True).execute("SELECT COUNT(*) FROM videos").fetchone()[0])
