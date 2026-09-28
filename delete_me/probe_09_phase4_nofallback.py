"""Probe: does a plain linux request on each up-next route log ann_fallback lines between its start and done lines?"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401

HEADERS = {"X-Client-IP": "192.0.2.152"}


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


def test_probe(engine):
    status, body = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    seed = body["rows"][0]
    for route in ("/recommendations", "/videos/similar"):
        before = len(_messages(engine.db_path))
        status, body = engine.request("POST", f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8", headers=HEADERS, body={})
        time.sleep(1.0)
        print("ROUTE", route, status, len(body["rows"]))
        for m in _messages(engine.db_path)[before:]:
            if m.startswith("[similar-server]"):
                print("  LOG", m[:200])
    assert False, "probe"
