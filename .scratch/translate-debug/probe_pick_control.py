"""Read-only: short non-English candidates (likely speech) with no subtitles row yet."""
import sqlite3

wl = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
wl.execute("attach 'file:engine/server/db/subtitles.db?mode=ro' as s")
for row in wl.execute(
    "select v.video_id, v.instance_domain, v.title, v.duration, v.language from videos v "
    "left join s.subtitles t on t.video_id = v.video_id and t.instance_domain = v.instance_domain "
    "where t.video_id is null and v.language in ('fr', 'de', 'es') and v.duration between 90 and 300 "
    "and (lower(v.title) like '%interview%' or lower(v.title) like '%entretien%' or lower(v.title) like '%vortrag%' "
    "or lower(v.title) like '%conférence%' or lower(v.title) like '%charla%') limit 8"
):
    print(row)
