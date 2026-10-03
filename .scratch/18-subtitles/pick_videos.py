"""List short non-English candidate videos from whitelist.db (read-only)."""
import sqlite3

db = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
print([r[1] for r in db.execute("pragma table_info(videos)")])
for row in db.execute(
    "select language, count(*) from videos where coalesce(language, '') != '' group by language order by 2 desc limit 12"
):
    print(row)
for lang in ("ru", "de", "ja", "fr", "es"):
    for row in db.execute(
        "select * from videos where language = ? and duration between 120 and 600 order by random() limit 2", (lang,)
    ):
        print(lang, row[:6])
