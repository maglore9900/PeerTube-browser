"""Read-only probe: how many raw ANN neighbours does a seed need before the Engine's filters yield its pool?

Mirrors precompute (nprobe 16, top-k 1000, self excluded) and _build_rows (one row per channel_id::instance_domain).
"""
import random
import sqlite3
import statistics
import sys

import faiss
import numpy as np

DB = "engine/server/db/whitelist.db"
INDEX = "engine/server/db/whitelist-video-embeddings.faiss"
SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 300
TOP_K = 1000
TARGETS = (16, 48, 100, 192, 300)

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
index = faiss.read_index(INDEX, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY)
faiss.extract_index_ivf(index).nprobe = 16
max_rowid = conn.execute("SELECT MAX(rowid) FROM video_embeddings").fetchone()[0]
random.seed(7)
rowids = random.sample(range(1, max_rowid + 1), SAMPLE)
seeds = conn.execute(
    f"SELECT rowid, embedding FROM video_embeddings WHERE rowid IN ({','.join('?' * len(rowids))})", rowids
).fetchall()
queries = np.stack([np.frombuffer(blob, dtype=np.float32) for _, blob in seeds]).copy()
faiss.normalize_L2(queries)
scores, ids = index.search(queries, TOP_K + 1)

wanted = sorted({int(i) for row in ids for i in row if i > 0})
author = {}
for start in range(0, len(wanted), 5000):
    chunk = wanted[start : start + 5000]
    for rid, ch, dom in conn.execute(
        f"""SELECT e.rowid, v.channel_id, v.instance_domain FROM video_embeddings e
            JOIN videos v ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain
            WHERE e.rowid IN ({','.join('?' * len(chunk))})""",
        chunk,
    ):
        author[rid] = f"{ch}::{dom}" if ch else f"rid{rid}"

for floor in (0.25, 0.35):
    depth = {t: [] for t in TARGETS}
    final = []
    for (seed_rid, _), srow, irow in zip(seeds, scores, ids):
        seen = set()
        raw = 0
        reached = {}
        for score, rid in zip(srow, irow):
            rid = int(rid)
            if rid <= 0 or rid == seed_rid:
                continue
            raw += 1
            if score < floor or rid not in author or author[rid] in seen:
                continue
            seen.add(author[rid])
            for t in TARGETS:
                if len(seen) == t and t not in reached:
                    reached[t] = raw
        final.append(len(seen))
        for t in TARGETS:
            depth[t].append(reached.get(t))
    print(f"== score floor {floor}, {len(seeds)} seeds, distinct-author pool from {TOP_K} raw")
    q = statistics.quantiles(final, n=10)
    print(f"   pool size at 1000 raw: median {statistics.median(final)}  p10 {q[0]}  p90 {q[-1]}  min {min(final)}")
    for t in TARGETS:
        hit = [d for d in depth[t] if d is not None]
        if not hit:
            print(f"   pool {t:>3}: reached by 0%")
            continue
        hq = statistics.quantiles(hit, n=10) if len(hit) > 1 else [hit[0]] * 9
        print(
            f"   pool {t:>3}: reached by {100 * len(hit) / len(seeds):5.1f}% of seeds;"
            f" raw needed median {statistics.median(hit):.0f}  p90 {hq[-1]:.0f}  max {max(hit)}"
        )
