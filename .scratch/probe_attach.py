import sqlite3

cases = [
    (":memory:", False, "ATTACH DATABASE 'file:engine/server/db/whitelist.db?mode=ro' AS source"),
    (":memory:", False, "ATTACH DATABASE 'engine/server/db/whitelist.db' AS source"),
    ("file::memory:", True, "ATTACH DATABASE 'file:engine/server/db/whitelist.db?mode=ro' AS source"),
    ("file:.scratch/crawl-copy.db", True, "ATTACH DATABASE 'engine/server/db/whitelist.db' AS source"),
    ("file:.scratch/crawl-copy.db", True, "ATTACH DATABASE 'engine/server/db/whitelist.db' AS wl"),
]
for main, uri, sql in cases:
    try:
        conn = sqlite3.connect(main, uri=uri)
        conn.execute(sql)
        name = sql.rsplit(" ", 1)[-1]
        print("ok", main, sql[-60:], conn.execute(f"SELECT COUNT(*) FROM {name}.videos").fetchone()[0])
    except Exception as exc:
        print("FAIL", main, sql[-60:], repr(exc))
