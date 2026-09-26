"""Probe: the most recent interaction events' actor_id, read-only."""
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
for row in conn.execute(
    "SELECT actor_id, event_type, video_uuid, instance_domain "
    "FROM interaction_raw_events ORDER BY rowid DESC LIMIT 5"
):
    print(row)
