"""Read-only: tags ranked by how often they sit on NSFW-flagged embedded videos."""
import collections
import json
import sqlite3

MIN_USES = 50
MIN_SHARE = 0.8

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
total = collections.Counter()
flagged = collections.Counter()
flagged_videos = flagged_untagged = 0
for tags_json, nsfw in conn.execute(
    """
    SELECT v.tags_json, v.nsfw FROM videos v JOIN video_embeddings e
      ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
    """
):
    tags = []
    if tags_json:
        try:
            tags = {str(t).strip().lower() for t in json.loads(tags_json)}
        except ValueError:
            tags = []
    if nsfw:
        flagged_videos += 1
        if not tags:
            flagged_untagged += 1
    for tag in tags:
        total[tag] += 1
        if nsfw:
            flagged[tag] += 1

print("nsfw-flagged embedded videos", flagged_videos, "of which untagged", flagged_untagged)
rows = [
    (tag, flagged[tag], total[tag])
    for tag in flagged
    if total[tag] >= MIN_USES and flagged[tag] / total[tag] >= MIN_SHARE
]
rows.sort(key=lambda r: r[1], reverse=True)
print(f"tags with >= {MIN_USES} uses and >= {MIN_SHARE:.0%} on flagged videos: {len(rows)}")
for tag, f, t in rows[:120]:
    print(f"{tag}\t{f}/{t}")
print("--- frequent tags that are mostly on flagged videos but also on unflagged ones (60-80%):")
mixed = [
    (tag, flagged[tag], total[tag])
    for tag in flagged
    if total[tag] >= MIN_USES and 0.6 <= flagged[tag] / total[tag] < MIN_SHARE
]
mixed.sort(key=lambda r: r[1], reverse=True)
for tag, f, t in mixed[:30]:
    print(f"{tag}\t{f}/{t}")
