"""Harness: SQLite LIKE backtracking cost with realistic channel names.

Same query shape as engine/server/data/channels.py:fetch_channels, but the rows
use word-like display names instead of a 3-letter alphabet, to check that the
blow-up is not an artefact of the synthetic data.
"""

import random
import sqlite3
import time

WORDS = [
    "News", "Daily", "Tech", "Channel", "Review", "Music", "Live", "Show",
    "Podcast", "Stream", "Video", "Official", "Community", "Science", "Cinema",
    "Gaming", "Deutsch", "France", "Studio", "Media", "Network", "Archive",
]

conn = sqlite3.connect(":memory:")
conn.execute(
    "CREATE TABLE channels (display_name TEXT, channel_name TEXT,"
    " channel_id TEXT, instance_domain TEXT)"
)
random.seed(11)
rows = []
for i in range(20000):
    name = " ".join(random.choice(WORDS) for _ in range(random.randint(2, 5)))
    rows.append((name, name.lower().replace(" ", "_"), str(i), "peertube%d.example" % (i % 800)))
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


print("-- literal-char pattern: %e%e%...%zq")
for wildcards in (4, 8, 12, 16):
    pat = "%" + "%".join(["e"] * wildcards) + "%zq"
    elapsed, matched = bench(pat)
    print(f"wildcards={wildcards} seconds={elapsed:.3f} matched={matched}", flush=True)
    if elapsed > 30:
        break

# '_' matches any single character, so the number of backtracking paths depends
# on row LENGTH only, not on row content.
print("-- content-independent pattern: (%_)*zq")
for groups in (2, 4, 6, 8, 10):
    pat = "%_" * groups + "%zq"
    elapsed, matched = bench(pat)
    print(f"groups={groups} len={len(pat)} seconds={elapsed:.3f} matched={matched}", flush=True)
    if elapsed > 30:
        break
