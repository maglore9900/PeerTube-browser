import math
import random


def _pool(**groups):
    return {f"{prefix}{i}": sim for prefix, (count, sim) in groups.items() for i in range(count)}


def reference(ordered, sims, limit, alpha):
    keyed, zero = [], []
    for vid in ordered:
        w = max(sims[vid] or 0.0, 0.0) ** alpha
        if not w > 0:
            zero.append(vid)
            continue
        keyed.append((math.log(1.0 - random.random()) / w, vid))
    if not keyed:
        return random.sample(ordered, limit)
    keyed.sort(key=lambda item: item[0], reverse=True)
    chosen = [v for _, v in keyed[:limit]]
    if len(chosen) < limit:
        chosen.extend(random.sample(zero, limit - len(chosen)))
    return chosen


def order(pool):
    return sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)


def test_probe():
    mixed = _pool(lo=(10, 0.1), hi=(10, 0.9))
    ordered = order(mixed)
    for name, alpha, trials in [("skew", 1.0, 400), ("skew_half", 0.5, 400)]:
        hi = lo = 0
        for t in range(trials):
            random.seed(f"{name}:{t}")
            d = reference(ordered, mixed, 5, alpha)
            hi += sum(v.startswith("hi") for v in d)
            lo += sum(v.startswith("lo") for v in d)
        uhi = ulo = 0
        for t in range(trials):
            random.seed(f"{name}:{t}")
            d = random.sample(ordered, 5)
            uhi += sum(v.startswith("hi") for v in d)
            ulo += sum(v.startswith("lo") for v in d)
        print(name, "weighted", hi, lo, "uniform", uhi, ulo)
    zf = {**_pool(p=(3, 0.5), z=(5, 0.0)), "neg0": -0.5, "none0": None}
    fill = set()
    for t in range(100):
        random.seed(f"zero_fill:{t}")
        fill |= set(reference(order(zf), zf, 5, 1.0))
    print("zero_fill union", sorted(fill))
    differ = 0
    for t in range(50):
        random.seed(f"disabled_zero:{t}")
        a = random.sample(ordered, 5)
        random.seed(f"disabled_zero:{t}")
        b = random.sample(list(mixed), 5)
        differ += a != b
    print("ordered vs pool-order samples differ in", differ, "of 50", "ordered head", ordered[:3], "pool head", list(mixed)[:3])
