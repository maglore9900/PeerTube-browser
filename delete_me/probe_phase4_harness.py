from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("feed_params_harness_probe", ROOT / "tests" / "active" / "test_frontend_feed_params.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def test_probe():
    print("ENGINE", h.ENGINE_FEED_MODES)
    print("VIDEOS", h.VIDEOS, h.VIDEOS_ERROR[:200])
    print("FEED_PARAMS", h.FEED_PARAMS, h.FEED_PARAMS_ERROR[:200])
    report = h._run([])
    print("CLIENT", report["feedModes"])
    cases = [
        {"search": "?mode=hot"},
        {"search": "?mode=hot", "stored": h._stored("recent")},
        {"search": "", "stored": h._stored("hot")},
        {"search": "?host=peer.example", "stored": h._stored("hot")},
        {"search": "?mode=bogus"},
        {"search": "", "stored": h._stored("bogus")},
        {"search": "", "stored": json.dumps("hot")},
        {"search": "", "stored": json.dumps("trending")},
        {"search": "?mode=trending"},
        {"search": "", "persist": "?mode=hot"},
    ] + [{"search": f"?mode={m}"} for m in h.ENGINE_FEED_MODES]
    for c, got in zip(cases, h._modes(cases)):
        print("CASE", c, "->", got)
    assert False, "probe"
