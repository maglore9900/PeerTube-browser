"""Probe: how account identity is populated in whitelist.db (read-only)."""
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
q = lambda s: conn.execute(s).fetchall()
print("videos:", q("SELECT COUNT(*) FROM videos"))
print("null channel_id:", q("SELECT COUNT(*) FROM videos WHERE channel_id IS NULL OR channel_id = ''"))
print("null account_url:", q("SELECT COUNT(*) FROM videos WHERE account_url IS NULL OR account_url = ''"))
print("null account_name:", q("SELECT COUNT(*) FROM videos WHERE account_name IS NULL OR account_name = ''"))
print("channels:", q("SELECT COUNT(DISTINCT instance_domain || '|' || channel_id) FROM videos"))
print("accounts by url:", q("SELECT COUNT(DISTINCT account_url) FROM videos"))
print("accounts with >1 channel:", q(
    "SELECT COUNT(*) FROM (SELECT account_url FROM videos WHERE account_url <> '' "
    "GROUP BY account_url HAVING COUNT(DISTINCT channel_id) > 1)"))
print("sample:", q("SELECT instance_domain, channel_id, channel_name, account_name, account_url FROM videos LIMIT 3"))
