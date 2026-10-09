"""Read-only: title, duration and language of every failed translate job's video."""
import sqlite3

subs = sqlite3.connect("file:engine/server/db/subtitles.db?mode=ro", uri=True)
wl = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
cols = [d[1] for d in wl.execute("pragma table_info(videos)")]
lang_col = next((c for c in ("language", "language_id", "lang") if c in cols), None)
for vid, host, state, err in subs.execute(
    "select video_id, instance_domain, state, error from subtitles where state != 'ready' order by queued_at"
):
    row = wl.execute(
        f"select title, duration{', ' + lang_col if lang_col else ''} from videos where video_id = ? and instance_domain = ?",
        (vid, host),
    ).fetchone()
    print(state, host, row, "|", err)
