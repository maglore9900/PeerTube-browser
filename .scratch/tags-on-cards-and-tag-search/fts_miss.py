"""Read-only: which exact-tag videos the FTS token prefilter misses, and tags with no FTS token."""
import json
import re
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
EXACT = "lower(trim(j.value)) = ?"
full = {r[0] for r in conn.execute(
    f"SELECT v.rowid FROM videos v, json_each(v.tags_json) j WHERE json_valid(v.tags_json) AND {EXACT}", ("linux",))}
fts = {r[0] for r in conn.execute(
    "SELECT rowid FROM videos_fts WHERE videos_fts MATCH ?", ('tags_json : "linux"',))}
for rowid in sorted(full - fts):
    print(conn.execute(
        "SELECT rowid, tags_json, (SELECT tags_json FROM videos_fts WHERE rowid = ?) FROM videos WHERE rowid = ?",
        (rowid, rowid)).fetchone())

no_token = 0
uses = 0
examples = []
for (tags_json,) in conn.execute("SELECT tags_json FROM videos WHERE json_valid(tags_json)"):
    tags = json.loads(tags_json)
    if not isinstance(tags, list):
        continue
    for tag in tags:
        text = str(tag).strip()
        if text and not re.search(r"\w", text):
            no_token += 1
            if len(examples) < 10:
                examples.append(text)
        uses += 1
print("tag uses", uses, "with no word character", no_token, examples)
