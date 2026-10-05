"""Does SQLite lower() fold non-ASCII case here, and does the FTS prefilter catch accented tags?"""
import sqlite3

mem = sqlite3.connect(":memory:")
print("sqlite lower('MÚSICA') =", mem.execute("SELECT lower('MÚSICA')").fetchone()[0])
print("python 'MÚSICA'.lower() =", "MÚSICA".lower())

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
for tag in ("música", "éducation", "политика"):
    fts = conn.execute(
        "SELECT count(*) FROM videos_fts WHERE videos_fts MATCH ?", (f'tags_json : "{tag}"',)
    ).fetchone()[0]
    print(tag, "fts token rows", fts)
