import sqlite3
import sys

f = sys.argv[1]
c = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
q = lambda s: c.execute(s).fetchall()
print("==", f, "pages", q("pragma page_count")[0][0], "free", q("pragma freelist_count")[0][0])
for (n,) in q("select name from sqlite_master where type='table'"):
    print("  table", n)
for r in q("select name, sum(pgsize) b from dbstat group by name order by b desc limit 10"):
    print("   size", r[0], round(r[1] / 1e6, 1), "MB")
for extra in sys.argv[2:]:
    print("  ", extra, "->", q(extra))
