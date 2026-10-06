"""Probe: can a tests/tmp file use the tests/active `engine` fixture by importing it, and what does the session Engine answer for mode=following today."""
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine, shared_trending_before, trending_seed  # noqa: E402,F401

HEADERS = {"X-Client-IP": "203.0.113.50"}


def test_engine_fixture_and_following_today(engine):
    status, body = engine.request("POST", "/recommendations?mode=following&limit=4", headers=HEADERS, body={})
    print("unseeded following", status, body)
    status, random_body = engine.request("POST", "/recommendations?mode=random&limit=4", headers=HEADERS, body={})
    print("random", status, random_body.get("seed"), len(random_body.get("rows", [])), "cursor" in random_body)
    status, found = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1", headers=HEADERS)
    seed = found["rows"][0]
    path = f"/recommendations?id={quote(seed['video_uuid'])}&host={quote(seed['instance_domain'])}&limit=8&seed=11"
    status, plain = engine.request("POST", path, headers=HEADERS, body={})
    print("seeded plain", status, plain.get("seed"), [r["video_id"] for r in plain["rows"]], "cursor" in plain)
    status, follow = engine.request("POST", f"{path}&mode=following", headers=HEADERS, body={"follows": {"channels": [["follow-probe.invalid", "ch-none"]], "accounts": []}})
    print("seeded following", status, follow.get("seed"), [r["video_id"] for r in follow["rows"]])
    status, big = engine.request("POST", "/recommendations?mode=following&limit=4", headers=HEADERS, body={"follows": {"channels": [[f"q{n}.invalid", f"ch-q{n}"] for n in range(600)], "accounts": [f"https://q{n}.invalid/accounts/q{n}" for n in range(401)]}})
    print("1001 today", status, {k: v for k, v in big.items() if k != "rows"} if isinstance(big, dict) else big)
