import importlib.util
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_probe_harness():
    spec = importlib.util.spec_from_file_location("checkpoint16", HERE / "test_16_popular_weighted_random_phase1.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run = subprocess.run([str(mod.ENGINE_PY), "-c", mod._CHILD, str(mod.SERVER_DIR), json.dumps(mod.CASES)], capture_output=True, text=True, timeout=120)
    print("RC", run.returncode, "STDERR", run.stderr[-2000:])
    out = json.loads(run.stdout)
    for name, case in out.items():
        flat = [vid for draw in case["draws"] for vid in draw]
        print(name, "trials", len(case["draws"]), "first", case["draws"][0], "equal_expected", case["draws"] == case["expected"] if case["expected"] else "n/a",
              "hi", sum(v.startswith("hi") for v in flat), "lo", sum(v.startswith("lo") for v in flat), "non_p", sum(not v.startswith("p") for v in flat))
    zf = [set(d) for d in out["zero_fill"]["draws"]]
    print("zero_fill all positives every draw", all({"p0", "p1", "p2"} <= d for d in zf))
    # the refuse patch really fires when the helper is reached: simulate a wrong branch
    child = mod._CHILD.replace("WEIGHTED = vars(popular_videos).get(\"_weighted_from_pool\")", "WEIGHTED = vars(popular_videos).get(\"_weighted_from_pool\")\n_orig = popular_videos._random_from_pool\npopular_videos._random_from_pool = lambda c, l: popular_videos._weighted_from_pool(c, l, 1.0)")
    bad = subprocess.run([str(mod.ENGINE_PY), "-c", child, str(mod.SERVER_DIR), json.dumps([c for c in mod.CASES if c["name"] == "disabled_zero"])], capture_output=True, text=True, timeout=120)
    print("WRONG-BRANCH RC", bad.returncode, "STDERR tail", bad.stderr.strip().splitlines()[-1:])
