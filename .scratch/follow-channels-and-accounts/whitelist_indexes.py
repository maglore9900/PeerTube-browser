"""Read-only: indexes on whitelist.db videos, and how accounts relate to channels."""
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='videos'"):
    print(name, "|", sql)
print("videos with account_url:", conn.execute(
    "SELECT count(*), sum(account_url IS NULL OR account_url = '') FROM videos").fetchone())
print("distinct channels, accounts:", conn.execute(
    "SELECT count(DISTINCT instance_domain || ' ' || channel_id), count(DISTINCT account_url) FROM videos").fetchone())
print("accounts with >1 channel:", conn.execute(
    "SELECT count(*) FROM (SELECT account_url FROM videos WHERE account_url != '' "
    "GROUP BY account_url HAVING count(DISTINCT channel_id) > 1)").fetchone())
