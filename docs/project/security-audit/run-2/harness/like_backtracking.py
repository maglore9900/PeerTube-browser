"""Harness: measure SQLite LIKE backtracking cost for /api/channels ?q= patterns.

Reproduces the WHERE clause built by engine/server/data/channels.py:fetch_channels
against a synthetic channels table, and times increasingly wildcard-heavy patterns.
"""

import random
import sqlite3
import time

conn = sqlite3.connect(":memory:")
conn.execute(
    "CREATE TABLE channels (display_name TEXT, channel_name TEXT,"
    " channel_id TEXT, instance_domain TEXT)"
)
rows = []
random.seed(7)
for i in range(20000):
    name = "".join(random.choice("aaaaabbbbcccc") for _ in range(40))
    rows.append((name, name, str(i), "host%d.example" % (i % 500)))
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


for wildcards in (1, 4, 8, 12, 16, 20, 24):
    pat = "%" + "%".join(["a"] * wildcards) + "%zz"
    elapsed, matched = bench(pat)
    print(f"wildcards={wildcards} seconds={elapsed:.3f} matched={matched}", flush=True)
    if elapsed > 30:
        break
