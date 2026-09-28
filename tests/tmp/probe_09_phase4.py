"""Probe: /videos/similar with and without likes on the live Engine, and the log lines one up-next request writes."""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401

HEADERS = {"X-Client-IP": "192.0.2.150"}


def _messages(log_path: Path) -> list[str]:
    out = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            out.append(payload["message"])
    return out


def _keys(rows):
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def _mean_jaccard(sets):
    pairs = list(itertools.combinations(sets, 2))
    return sum(len(a & b) / len(a | b) for a, b in pairs) / len(pairs)


def test_probe(engine):
    status, body = engine.request("GET", "/api/v1/search/videos?q=music&limit=5")
    print("music status", status, "rows", len(body["rows"]))
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in body["rows"]]
    print("likes", likes)
    status, body = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    seed = body["rows"][0]
    print("seed", seed["video_uuid"], seed["instance_domain"], seed["video_id"])
    path = f"/videos/similar?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8&debug=1"

    before = len(_messages(engine.db_path))
    status, one = engine.request("POST", path, headers=HEADERS, body={"likes": likes})
    time.sleep(1.0)
    new = _messages(engine.db_path)[before:]
    print("ONE REQUEST status", status, "rows", len(one["rows"]))
    for m in new:
        print("  LOG", m[:260])
    print("  scores", [(round(r["debug"]["score"], 4), round(r["debug"]["similarity_score"], 4)) for r in one["rows"]])

    liked = []
    plain = []
    for _ in range(9):
        status, b = engine.request("POST", path, headers=HEADERS, body={"likes": likes})
        assert status == 200, b
        liked.append(b["rows"])
    liked.append(one["rows"])
    for _ in range(10):
        status, b = engine.request("POST", path, headers=HEADERS, body={})
        assert status == 200, b
        plain.append(b["rows"])
    print("liked lens", [len(r) for r in liked], "jaccard", _mean_jaccard([set(_keys(r)) for r in liked]))
    print("liked min sim", min(r["debug"]["similarity_score"] for rows in liked for r in rows))
    print("plain lens", [len(r) for r in plain], "jaccard", _mean_jaccard([set(_keys(r)) for r in plain]))
    print("plain min sim", min(r["debug"]["similarity_score"] for rows in plain for r in rows))

    missing = [{"uuid": like["uuid"] + "-absent", "host": like["host"]} for like in likes]
    before = len(_messages(engine.db_path))
    status, b = engine.request("POST", path, headers=HEADERS, body={"likes": missing})
    time.sleep(1.0)
    print("MISSING status", status, "rows", len(b["rows"]) if b else b)
    for m in _messages(engine.db_path)[before:]:
        if "profile=" in m or "upnext" in m or "personalize" in m:
            print("  LOG", m[:260])
    profiles = [m for m in _messages(engine.db_path) if m.startswith("[recommendations] profile=")]
    print("profile lines tail", profiles[-4:])
    assert False, "probe"
