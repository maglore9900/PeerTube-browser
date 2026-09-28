from __future__ import annotations

import importlib.util
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("phase2", Path(__file__).with_name("test_12_similars_on_scroll_phase2.py"))
phase2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase2)
bundle = phase2.bundle


def test_probe(bundle):
    page = phase2._page(bundle)
    markup = page["similar"] or ""
    cards = re.findall(r'<a\b[^>]*\bclass="[^"]*\bsimilar-card-item\b[^"]*"[^>]*>', markup)
    ids = [m.group(1) if (m := re.search(r'data-video-key="videos\.example::(v\d+)"', c)) else None for c in cards]
    print("COUNT", len(cards), "IDS", ids[:10], ids[-2:], "OBSERVED", page["observed"])
    assert False
