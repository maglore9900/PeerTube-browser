import importlib.util
import json
import math
import random
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def reference(ordered, sims, limit, alpha, weight):
    keyed, zero = [], []
    for vid in ordered:
        w = weight(sims[vid]) ** alpha
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


def test_probe():
    spec = importlib.util.spec_from_file_location("checkpoint16", HERE / "test_16_popular_weighted_random_phase1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    case = next(c for c in mod.CASES if c["name"] == "zero_unused")
    pool = case["pool"]
    print("pool", pool)
    run = subprocess.run([str(mod.ENGINE_PY), "-c", mod._CHILD, str(mod.SERVER_DIR), json.dumps([case])], capture_output=True, text=True, timeout=120)
    print("RC", run.returncode, run.stderr[-500:])
    flat = [v for d in json.loads(run.stdout)["zero_unused"]["draws"] for v in d]
    print("today non_p", sum(not v.startswith("p") for v in flat), "neg0", flat.count("neg0"), "none0", flat.count("none0"))
    ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)
    variants = {
        "correct": lambda s: max(s or 0.0, 0.0),
        "none_as_one": lambda s: 1.0 if s is None else max(s, 0.0),
        "neg_abs": lambda s: abs(s or 0.0),
    }
    for label, weight in variants.items():
        got = []
        for t in range(case["trials"]):
            random.seed(f"zero_unused:{t}")
            got.extend(reference(ordered, pool, 5, 1.0, weight))
        print(label, "non_p", sum(not v.startswith("p") for v in got), "neg0", got.count("neg0"), "none0", got.count("none0"))
