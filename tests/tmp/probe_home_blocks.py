"""Probe: do the operator's blocked channels/accounts survive the Client's home-feed filter?"""
import json
import random
import sqlite3
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client/backend"))

import server  # noqa: E402
from lib.blocks import load_block_keys  # noqa: E402
from lib.users_store import fetch_recent_likes  # noqa: E402

PROFILE = "AT6FAkLsBFxvU6sV"


def test_probe():
    conn = sqlite3.connect(f"file:{ROOT}/client/backend/db/users.db?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    keys = load_block_keys(conn, PROFILE)
    liked = server.load_liked_keys(conn, PROFILE)
    disliked = server.load_disliked_keys(conn, PROFILE)
    centroids = server.load_centroids(conn, PROFILE)
    stored = fetch_recent_likes(conn, PROFILE, server.MAX_LIKES)
    print("blocks", keys)
    print("likes stored", len(stored), "centroids", centroids is not None)

    def blocked(row):
        return ((str(row.get("instance_domain") or ""), str(row.get("channel_id") or "")) in keys[0]
                or str(row.get("account_url") or "") in keys[1])

    for i in range(8):
        sample = random.sample(stored, min(server.ENGINE_FEED_LIKES_MAX, len(stored)))
        body = {"likes": [{"uuid": l["video_uuid"], "host": l["instance_domain"]} for l in sample]}
        if centroids is not None:
            body["dislike_centroids"] = centroids
        req = Request("http://127.0.0.1:7070/recommendations?limit=96", data=json.dumps(body).encode(),
                      method="POST", headers={"content-type": "application/json", "x-client-ip": "10.9.9.9"})
        with urlopen(req, timeout=30) as resp:
            payload = resp.read()
        rows = json.loads(payload)["rows"]
        raw_blocked = [(r["instance_domain"], r["channel_id"], r["account_url"], r["title"]) for r in rows if blocked(r)]
        out = json.loads(server._filter_payload(payload, (keys, disliked, liked, disliked), 48))["rows"]
        out_blocked = [r["title"] for r in out if blocked(r)]
        print(f"run {i}: raw {len(rows)} blocked_raw {len(raw_blocked)} out {len(out)} blocked_out {len(out_blocked)}")
        for b in raw_blocked[:5]:
            print("   ", b)
        hosts = {"810video.com", "video.hikamers.net", "tube.sasek.tv", "tube.webcontact.de"}
        for r in out:
            if r["instance_domain"] in hosts:
                print("    KEPT same-host:", r["instance_domain"], r["channel_id"], r["account_url"],
                      r["channel_display_name"], "|", r["title"][:50])
