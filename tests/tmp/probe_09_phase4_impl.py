"""Probe: the upnext_pool line a liked, a plain and an unknown-likes request write on the implemented phase 4."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def _search(engine, query, limit):
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit={limit}")
    return body["rows"]


def test_probe(engine):
    seed = _search(engine, "linux", 1)[0]
    likes = [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in _search(engine, "music", 5)]
    path = f"/videos/similar?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8&debug=1"
    headers = {"X-Client-IP": "192.0.2.150"}
    for body in ({"likes": likes}, {}, {"likes": [{"uuid": like["uuid"] + "-absent", "host": like["host"]} for like in likes]}):
        status, response = engine.request("POST", path, headers=headers, body=body)
        print("status", status, "rows", len(response["rows"]), [round(r["debug"]["similarity_score"], 3) for r in response["rows"]])
    status, response = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8", headers=headers, body={})
    print("recommendations status", status, len(response["rows"]))
    time.sleep(1)
    for line in engine.db_path.read_text(errors="replace").splitlines():
        try:
            message = json.loads(line).get("message", "")
        except ValueError:
            continue
        if "upnext_pool" in message or "ann_fallback" in message or "] start " in message or "profile=" in message or "server error" in message:
            print(message)
