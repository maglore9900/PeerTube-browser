"""Look a video up in whitelist.db by uuid (read-only)."""
import sqlite3
import sys

db = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
for row in db.execute(
    "select video_id, video_uuid, instance_domain, duration, language, title from videos where video_uuid = ? or video_id = ?",
    (sys.argv[1], sys.argv[1]),
):
    print(row)
