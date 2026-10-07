import importlib.util
import sqlite3

spec = importlib.util.spec_from_file_location("backfill", "engine/server/db/jobs/backfill-null-tags.py")
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
pending = job.pending_by_host(conn, 2000)
print("hosts in first 2000 NULL rows:", len(pending))
for host, videos in list(pending.items())[:5]:
    print(host, videos[0][1], "->", job.fetch_video_tags(host, videos[0][1], 5))
