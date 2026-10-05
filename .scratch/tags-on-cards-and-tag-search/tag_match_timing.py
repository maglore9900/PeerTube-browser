"""Read-only: time exact-tag matching against whitelist.db without new storage."""
import sqlite3
import time

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)


def timed(label, sql, *args):
    start = time.time()
    rows = conn.execute(sql, args).fetchall()
    print(f"{label}: {time.time() - start:.2f}s -> {rows[:3]}")


EXACT = "lower(trim(j.value)) = ?"
timed(
    "full scan json_each 'linux'",
    f"SELECT count(*) FROM videos v, json_each(v.tags_json) j WHERE json_valid(v.tags_json) AND {EXACT}",
    "linux",
)
for tag, match in (("linux", '"linux"'), ("music", '"music"'), ("pco", '"pco"'),
                   ("partido da causa operária", '"partido da causa operária"')):
    timed(
        f"fts token {tag!r}",
        "SELECT count(*) FROM videos_fts WHERE videos_fts MATCH ?",
        "tags_json : " + match,
    )
    timed(
        f"fts + exact {tag!r}",
        "SELECT count(DISTINCT v.rowid) FROM videos_fts f JOIN videos v ON v.rowid = f.rowid, "
        f"json_each(v.tags_json) j WHERE videos_fts MATCH ? AND json_valid(v.tags_json) AND {EXACT}",
        "tags_json : " + match,
        tag,
    )
    timed(
        f"fts + exact newest 24 {tag!r}",
        "SELECT v.rowid FROM videos_fts f JOIN videos v ON v.rowid = f.rowid, "
        f"json_each(v.tags_json) j WHERE videos_fts MATCH ? AND json_valid(v.tags_json) AND {EXACT} "
        "GROUP BY v.rowid ORDER BY v.published_at DESC LIMIT 24",
        "tags_json : " + match,
        tag,
    )
print("videos", conn.execute("SELECT count(*) FROM videos").fetchone())
