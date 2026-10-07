"""Probe: per route, how many served rows hold tags out of sorted order or with duplicates, and whether tags_from_json matches a plain json.loads on every stored value."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import dataset, engine, shared_trending_before, trending_seed  # noqa: E402,F401
import test_similar  # noqa: E402
from handlers.video import tags_from_json  # noqa: E402


def _followed_channel(dataset):
    row = dataset.execute(
        """
        SELECT v.instance_domain, v.channel_id FROM videos v
        JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        WHERE v.tags_json LIKE '["%' AND v.published_at = (
          SELECT MAX(w.published_at) FROM videos w
          JOIN video_embeddings f ON f.video_id = w.video_id AND f.instance_domain = w.instance_domain
          WHERE w.instance_domain = v.instance_domain AND w.channel_id = v.channel_id)
        ORDER BY v.published_at DESC LIMIT 1
        """
    ).fetchone()
    return [row["instance_domain"], row["channel_id"]]


def test_probe_order(engine, dataset):
    headers = {"X-Client-IP": "192.0.2.196"}
    routes = ["upnext", "search", *(f"mode={m}" for m in test_similar.FEED_MODES)]
    for route in routes:
        if route == "search":
            status, body = engine.request("GET", "/api/v1/search/videos?q=music&limit=20", headers=headers)
        elif route == "upnext":
            status, seed = engine.request("GET", "/api/v1/search/videos?q=music&limit=1", headers=headers)
            first = seed["rows"][0]
            status, body = engine.request("POST", f"/recommendations?id={first['video_uuid']}&host={first['instance_domain']}&limit=8", headers=headers, body={})
        elif route == "mode=following":
            status, body = engine.request("POST", "/recommendations?mode=following", headers=headers, body={"follows": {"channels": [_followed_channel(dataset)], "accounts": []}})
        else:
            status, body = engine.request("POST", f"/recommendations?{route}", headers=headers, body={})
        unsorted = dups = oracle_off = 0
        for r in body["rows"]:
            stored = dataset.execute("SELECT tags_json FROM videos WHERE video_id = ? AND instance_domain = ?", (r["video_id"], r["instance_domain"])).fetchone()["tags_json"]
            plain = [] if stored is None else json.loads(stored)
            oracle_off += tags_from_json(stored) != plain
            unsorted += plain != sorted(plain)
            dups += len(plain) != len(set(plain))
        print("ROUTE", route, status, "rows", len(body["rows"]), "unsorted", unsorted, "dups", dups, "oracle_off", oracle_off)
