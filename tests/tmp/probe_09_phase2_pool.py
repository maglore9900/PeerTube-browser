"""Probe: what the phase-2 up-next pool build serves for the short cached seeds, and what the fallback logs."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def _messages(log_path, needle):
    out = []
    for line in Path(log_path).read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and needle in str(payload.get("message", "")):
            out.append(payload["message"])
    return out


def test_probe(engine):
    for query in ("linux", "cooking"):
        status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
        seed = body["rows"][0]
        for limit in (48, 30, 8):
            started = time.time()
            status, page = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}&debug=1", body={})
            elapsed = time.time() - started
            rows = page.get("rows", []) if isinstance(page, dict) else []
            scores = [r["debug"]["similarity_score"] for r in rows]
            print("PROBE", query, limit, status, len(rows), len({(r["video_uuid"], r["instance_domain"]) for r in rows}), len({f"{r['video_id']}::{r['instance_domain']}" for r in rows}), min(scores) if scores else None, round(elapsed, 2), page if status != 200 else "")
    time.sleep(1)
    for message in _messages(engine.db_path, "ann_fallback") + _messages(engine.db_path, "ann_nprobe_configured") + _messages(engine.db_path, "statement.timeout") + _messages(engine.db_path, "server error"):
        print("LOG", message)
    assert False, "probe"
