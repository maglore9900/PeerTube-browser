"""Read-only: length distribution of stored tags after trim, to size the tag parameter's cap."""
import collections
import json
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
lengths = collections.Counter()
longest = []
for (tags_json,) in conn.execute("SELECT tags_json FROM videos WHERE json_valid(tags_json)"):
    tags = json.loads(tags_json)
    if not isinstance(tags, list):
        continue
    for tag in tags:
        text = str(tag).strip()
        lengths[len(text)] += 1
        longest.append((len(text), text))
longest.sort(reverse=True)
total = sum(lengths.values())
for cap in (30, 32, 50, 64, 100):
    over = sum(n for length, n in lengths.items() if length > cap)
    print(f"over {cap} chars: {over} of {total}")
print("longest:", longest[:5])
print("non-string tags:", sum(1 for (t,) in conn.execute(
    "SELECT j.type FROM videos v, json_each(v.tags_json) j WHERE json_valid(v.tags_json) AND j.type != 'text'")))
