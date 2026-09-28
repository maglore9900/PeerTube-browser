import math
import random


def weighted(candidates, limit, alpha):
    if len(candidates) <= limit:
        return candidates
    keyed, unweighted = [], []
    for entry in candidates:
        weight = float(entry.get("similarity_score") or 0.0) ** alpha
        if not weight > 0:
            unweighted.append(entry)
            continue
        keyed.append((math.log(1.0 - random.random()) / weight, entry))
    if not keyed:
        return random.sample(candidates, limit)
    keyed.sort(key=lambda item: item[0], reverse=True)
    chosen = [item[1] for item in keyed[:limit]]
    if len(chosen) < limit:
        chosen.extend(random.sample(unweighted, limit - len(chosen)))
    return chosen


def rows(pool):
    return [{"video_id": vid, "similarity_score": max(sim or 0.0, 0.0)} for vid, sim in pool.items()]


def test_probe_margin():
    skew = {**{f"hi{i}": 0.9 for i in range(10)}, **{f"lo{i}": 0.1 for i in range(10)}}
    hi = lo = 0
    for trial in range(400):
        random.seed(f"skew:{trial}")
        for row in weighted(rows(skew), 5, 1.0):
            hi += row["video_id"].startswith("hi")
            lo += row["video_id"].startswith("lo")
    print("skew hi", hi, "lo", lo, "ratio", hi / lo)
    uniform_hi = uniform_lo = 0
    for trial in range(400):
        random.seed(f"skew:{trial}")
        for vid in random.sample(list(skew), 5):
            uniform_hi += vid.startswith("hi")
            uniform_lo += vid.startswith("lo")
    print("uniform hi", uniform_hi, "lo", uniform_lo)
    fill = {"p0": 0.5, "p1": 0.5, "p2": 0.5, **{f"z{i}": 0.0 for i in range(5)}, "neg0": -0.5, "none0": None}
    seen = {}
    for trial in range(100):
        random.seed(f"zero_fill:{trial}")
        for row in weighted(rows(fill), 5, 1.0):
            seen[row["video_id"]] = seen.get(row["video_id"], 0) + 1
    print("zero_fill counts", seen)
