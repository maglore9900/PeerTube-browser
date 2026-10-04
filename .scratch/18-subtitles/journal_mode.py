"""Print the journal mode of the dev whitelist.db (read-only)."""
import sqlite3

db = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
print(db.execute("PRAGMA journal_mode").fetchone())
