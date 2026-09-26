"""Harness: one crawled channel row with a long repetitive display_name is enough
to make the /api/channels ?q= LIKE filter run effectively forever.

Table shape and WHERE clause copied from engine/server/data/channels.py:fetch_channels.
"""

import random
import sqlite3
import time

WORDS = [
    "News", "Daily", "Tech", "Channel", "Review", "Music", "Live", "Show",
    "Podcast", "Stream", "Video", "Official", "Community", "Science", "Cinema",
]

conn = sqlite3.connect(":memory:")
conn.execute(
    "CREATE TABLE channels (display_name TEXT, channel_name TEXT,"
    " channel_id TEXT, instance_domain TEXT)"
)
random.seed(3)
rows = []
for i in range(20000):
    name = " ".join(random.choice(WORDS) for _ in range(random.randint(2, 5)))
    rows.append((name, name.lower().replace(" ", "_"), str(i), "peertube%d.example" % (i % 800)))
# One channel planted by a hostile instance: 200-character repetitive display name.
rows.append(("a" * 200, "evil", "999999", "evil.example"))
conn.executemany("INSERT INTO channels VALUES (?,?,?,?)", rows)

SQL = (
    "SELECT COUNT(*) FROM channels WHERE "
    "LOWER(COALESCE(display_name, channel_name, channel_id, '')) LIKE ? "
    "OR LOWER(COALESCE(instance_domain, '')) LIKE ?"
)


def bench(pattern: str) -> tuple[float, int]:
    """Time one filtered count for the given LIKE pattern."""
    started = time.time()
    count = conn.execute(SQL, (pattern, pattern)).fetchone()[0]
    return time.time() - started, count


for wildcards in (3, 4, 5, 6, 7, 8):
    pat = "%" + "%".join(["a"] * wildcards) + "%zq"
    elapsed, matched = bench(pat)
    print(f"wildcards={wildcards} seconds={elapsed:.3f} matched={matched}", flush=True)
    if elapsed > 30:
        break
