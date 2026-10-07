import sqlite3

c = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
print("total, null, empty:", c.execute("select count(*), sum(tags_json is null), sum(tags_json='[]') from videos").fetchone())
print("null among newest 2000:", c.execute("select count(*) from (select tags_json from videos order by published_at desc limit 2000) where tags_json is null").fetchone()[0])
print("top null hosts:", c.execute("select instance_domain, count(*) from videos where tags_json is null group by 1 order by 2 desc limit 10").fetchall())
