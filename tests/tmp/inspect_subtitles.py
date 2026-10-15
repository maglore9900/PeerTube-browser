import sqlite3

c = sqlite3.connect("file:engine/server/db/subtitles.db?mode=ro", uri=True)
for r in c.execute("select video_id, instance_domain, state, error, detected_language, attempts, queued_at, finished_at from subtitles where state in ('failed', 'already_english') order by coalesce(finished_at, queued_at) desc"):
    print(r)
