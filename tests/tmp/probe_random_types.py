"""Probe: do random-feed rows carry non-string values in fields the card escapes as strings?"""
import collections
import json
from urllib.request import Request, urlopen

FIELDS = ("title", "channel_display_name", "channel_name", "channel_url", "thumbnail_url", "preview_path",
          "embed_path", "video_url", "video_uuid", "video_id", "instance_domain", "channel_avatar_url")


def test_probe():
    seen = collections.Counter()
    examples = {}
    for path in ["/recommendations?random=1"] * 6 + ["/recommendations"] * 3:
        req = Request("http://127.0.0.1:7072" + path, data=b"{}", method="POST",
                      headers={"content-type": "application/json"})
        with urlopen(req, timeout=60) as resp:
            rows = json.loads(resp.read())["rows"]
        for row in rows:
            for field in FIELDS:
                value = row.get(field)
                kind = type(value).__name__
                seen[(path, field, kind)] += 1
                if kind not in ("str", "NoneType"):
                    examples.setdefault((path, field, kind), (value, row.get("title")))
    for key, count in sorted(seen.items()):
        print(key, count)
    print("NON-STRING EXAMPLES", examples)
