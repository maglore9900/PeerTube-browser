import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
ENGINE_PY = ROOT / "engine" / ".pixi" / "envs" / "default" / "bin" / "python"

CHILD = textwrap.dedent(
    """
    import json, math, random, sys, threading
    from types import SimpleNamespace
    sys.path[:0] = [sys.argv[1], sys.argv[1] + "/api"]
    import numpy as np
    from recommendations.candidates import popular_videos
    from recommendations.candidates.popular_videos import PopularVideosDeps, PopularVideosGenerator
    print("has_weighted", hasattr(popular_videos, "_weighted_from_pool"))
    pool = {"hi0": 0.9, "hi1": 0.9, "lo0": 0.1, "z0": 0.0, "neg0": -0.5, "none0": None}
    def vector(sim):
        return np.array([sim, math.sqrt(max(0.0, 1.0 - sim * sim))], dtype=np.float32)
    table = {"like": np.array([1.0, 0.0], dtype=np.float32)}
    table.update({vid: vector(sim) for vid, sim in pool.items() if sim is not None})
    gen = PopularVideosGenerator(PopularVideosDeps(
        fetch_popular_videos=lambda db, count: [{"video_id": vid} for vid in pool],
        fetch_recent_likes=lambda user_id, count: [{"video_id": "like"}],
        fetch_embeddings_by_ids=lambda db, rows: {r["video_id"]: table[r["video_id"]] for r in rows if r["video_id"] in table},
        like_key=lambda row: row["video_id"],
        max_likes=10,
    ))
    server = SimpleNamespace(db=None, db_lock=threading.Lock())
    random.seed("probe:0")
    rows = gen.get_candidates(server, "user", 3, config={"max_per_author": 0, "max_per_instance": 0})
    print("draw", [(r["video_id"], r["similarity_score"]) for r in rows])
    ordered = sorted(pool, key=lambda vid: max(pool[vid] or 0.0, 0.0), reverse=True)
    random.seed("probe:0")
    print("expected", random.sample(ordered, 3), "ordered", ordered)
    random.seed("probe:0")
    print("same_seed_again", random.sample(ordered, 3))
    """
)


def test_probe_child():
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, str(SERVER_DIR)], capture_output=True, text=True, timeout=120)
    print("RC", run.returncode)
    print("STDOUT", run.stdout)
    print("STDERR", run.stderr[-3000:])
