import importlib.util
import sqlite3
import time

spec = importlib.util.spec_from_file_location("copy_job", "engine/server/db/jobs/copy-to-crawl-db.py")
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
conn = sqlite3.connect("file:.scratch/crawl-copy.db", uri=True, timeout=30)
conn.execute("ATTACH DATABASE 'file:engine/server/db/whitelist.db?mode=ro' AS source")
start = time.monotonic()
print("copied:", job.copy_missing_rows(conn), f"in {time.monotonic() - start:.1f}s")
missing = conn.execute("SELECT COUNT(*) FROM source.videos s WHERE NOT EXISTS (SELECT 1 FROM main.videos m WHERE m.video_id = s.video_id AND m.instance_domain = s.instance_domain)").fetchone()[0]
orphans = conn.execute("SELECT COUNT(*) FROM main.videos v WHERE NOT EXISTS (SELECT 1 FROM main.channels c WHERE c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain)").fetchone()[0]
tagged = conn.execute("SELECT COUNT(*) FROM main.videos WHERE language IS NOT NULL").fetchone()[0]
print("whitelist videos still missing from crawl copy:", missing, "| crawl videos with no channel row:", orphans, "| with language:", tagged)
start = time.monotonic()
print("second run:", job.copy_missing_rows(conn), f"in {time.monotonic() - start:.1f}s")
