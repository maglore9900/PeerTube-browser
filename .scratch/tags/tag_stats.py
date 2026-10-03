"""Read-only tag statistics over whitelist.db's embedded videos."""
import collections
import json
import sqlite3

conn = sqlite3.connect("file:engine/server/db/whitelist.db?mode=ro", uri=True)
rows = conn.execute(
    """
    SELECT v.tags_json, v.category, v.language
    FROM videos v JOIN video_embeddings e
      ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
    """
)
total = null_tags = empty_tags = 0
per_video = collections.Counter()
tag_counts = collections.Counter()
lower_counts = collections.Counter()
categories = collections.Counter()
languages = collections.Counter()
for tags_json, category, language in rows:
    total += 1
    categories[category is not None and category != ""] += 1
    languages[language is not None and language != ""] += 1
    if tags_json is None:
        null_tags += 1
        per_video["null"] += 1
        continue
    try:
        tags = json.loads(tags_json)
    except ValueError:
        per_video["bad"] += 1
        continue
    if not tags:
        empty_tags += 1
    per_video[len(tags)] += 1
    for tag in tags:
        tag_counts[tag] += 1
        lower_counts[str(tag).strip().lower()] += 1

print("embedded videos", total)
print("tags null", null_tags, "empty", empty_tags)
print("tags per video", sorted(per_video.items(), key=lambda kv: str(kv[0])))
print("distinct tags (raw)", len(tag_counts), "case-folded", len(lower_counts))
uses = sum(lower_counts.values())
for threshold in (1, 2, 5, 10, 50, 100, 1000):
    tags_at = [c for c in lower_counts.values() if c >= threshold]
    print(f"tags used >= {threshold}: {len(tags_at)} tags, {sum(tags_at)} uses ({sum(tags_at) / uses:.1%})")
print("category set", dict(categories))
print("language set", dict(languages))
print("top 60 tags (case-folded):")
print(", ".join(f"{t} {c}" for t, c in lower_counts.most_common(60)))
