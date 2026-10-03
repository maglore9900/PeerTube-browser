"""Read-only: tags containing common adult keywords, with how many carriers are NSFW-flagged."""
import collections
import json
import sqlite3

KEYWORDS = ("porn", "sex", "nsfw", "hentai", "nude", "naked", "xxx", "18+", "erotic", "jav", "fetish", "boobs", "milf", "r18", "エロ", "色情", "成人")

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
total = collections.Counter()
flagged = collections.Counter()
for tags_json, nsfw in conn.execute(
    """
    SELECT v.tags_json, v.nsfw FROM videos v JOIN video_embeddings e
      ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
    WHERE v.tags_json IS NOT NULL AND v.tags_json != '[]'
    """
):
    try:
        tags = {str(t).strip().lower() for t in json.loads(tags_json)}
    except ValueError:
        continue
    for tag in tags:
        if any(k in tag for k in KEYWORDS):
            total[tag] += 1
            if nsfw:
                flagged[tag] += 1

print("matching distinct tags", len(total), "uses", sum(total.values()), "on flagged", sum(flagged.values()))
for tag, t in total.most_common(50):
    print(f"{tag}\t{flagged[tag]}/{t}")
