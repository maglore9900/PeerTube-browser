"""Read-only look at subtitles.db: heartbeat age, recent job rows, state counts."""
import sqlite3
import time

c = sqlite3.connect("file:engine/server/db/subtitles.db?mode=ro", uri=True)
now = int(time.time() * 1000)
for r in c.execute("select * from translate_worker_heartbeat"):
    print("beat", r, "age_ms", now - r[1])
print([d[1] for d in c.execute("pragma table_info(subtitles)")])
for r in c.execute(
    "select video_id, instance_domain, state, source, attempts, queued_at, started_at, finished_at, error "
    "from subtitles order by coalesce(finished_at, started_at, queued_at) desc limit 12"
):
    print(r)
print(c.execute("select state, count(*) from subtitles group by state").fetchall())
