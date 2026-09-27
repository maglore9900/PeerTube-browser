import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "server"))

from data.moderation import normalize_host_token  # noqa: E402


def test_probe():
    pairs = json.loads((ROOT / "tests" / "active" / "host_tokens.json").read_text(encoding="utf-8"))
    bad = []
    for pair in pairs:
        got = normalize_host_token(pair["input"])
        print(repr(pair["input"]), "->", repr(got), "expected", repr(pair["expected"]))
        if got != pair["expected"]:
            bad.append((pair["input"], got, pair["expected"]))
    print("pairs", len(pairs), "mismatches", bad)
    assert not bad
