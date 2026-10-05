"""Read-only: time a newest-first page over a set of followed sources with today's indexes.

Picks followed sets from the catalogue (small channels, big channels, multi-channel accounts)
and runs the query the Following mode would need, with and without a cursor. whitelist.db has
no index on channel_id or account_url, so this measures the no-new-index case only.
"""
import sqlite3
import time

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)


def pick(sql, n):
    return [tuple(r) for r in conn.execute(sql, (n,))]


small = pick("SELECT instance_domain, channel_id FROM videos GROUP BY 1, 2 HAVING count(*) < 20 "
             "ORDER BY random() LIMIT ?", 20)
big = pick("SELECT instance_domain, channel_id FROM videos GROUP BY 1, 2 HAVING count(*) > 500 "
           "ORDER BY random() LIMIT ?", 5)
accounts = [r[0] for r in conn.execute(
    "SELECT account_url FROM videos GROUP BY account_url HAVING count(DISTINCT channel_id) > 1 "
    "ORDER BY random() LIMIT 5")]
many = pick("SELECT instance_domain, channel_id FROM videos GROUP BY 1, 2 ORDER BY random() LIMIT ?", 1000)


def page(channels, accts, cursor=None, limit=48):
    conds, params = [], []
    if channels:
        conds.append("(" + " OR ".join(["(v.instance_domain = ? AND v.channel_id = ?)"] * len(channels)) + ")")
        for host, cid in channels:
            params += [host, cid]
    if accts:
        conds.append("v.account_url IN (" + ",".join("?" * len(accts)) + ")")
        params += accts
    where = "(" + " OR ".join(conds) + ")"
    if cursor:
        where += " AND (v.published_at, v.video_id) < (?, ?)"
        params += list(cursor)
    sql = (f"SELECT v.published_at, v.video_id FROM videos v WHERE {where} "
           "ORDER BY v.published_at DESC, v.video_id DESC LIMIT ?")
    start = time.time()
    rows = conn.execute(sql, params + [limit]).fetchall()
    plan = conn.execute("EXPLAIN QUERY PLAN " + sql, params + [limit]).fetchall()
    return time.time() - start, rows, plan


for label, chans, accts in (("20 small channels", small, []), ("5 big channels", big, []),
                            ("5 multi-channel accounts", [], accounts),
                            ("1000 random channels", many, []),
                            ("20 small + 5 accounts", small, accounts)):
    secs, rows, plan = page(chans, accts)
    print(f"{label}: first page {secs:.2f}s, {len(rows)} rows; plan {[p[3] for p in plan]}")
    if rows:
        secs2, rows2, _ = page(chans, accts, cursor=rows[-1])
        print(f"  next page {secs2:.2f}s, {len(rows2)} rows")
