"""Probe: what the live Client answers for the random feed, with a throwaway profile holding a block."""
import json
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:7072"


def call(method, path, body=None, key=None):
    headers = {"content-type": "application/json"}
    if key:
        headers["X-Profile-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(BASE + path, data=data, method=method, headers=headers), timeout=60) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def test_probe():
    _, minted = call("POST", "/api/profile", {})
    key = minted["key"]
    try:
        _, page = call("POST", "/recommendations?random=1", {}, key)
        print("keyed random, no blocks:", len(page["rows"]), page.get("seed"))
        row = page["rows"][0]
        status, _ = call("POST", "/api/profile/blocks", {"kind": "channel", "uuid": row["video_uuid"],
                                                         "host": row["instance_domain"]}, key)
        print("block status", status)
        for i in range(3):
            _, page = call("POST", "/recommendations?random=1", {}, key)
            print("keyed random with block:", len(page["rows"]), page.get("seed"), page.get("count"))
    finally:
        print("delete", call("POST", "/api/profile/delete", {}, key)[0])
