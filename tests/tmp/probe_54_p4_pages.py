"""Probe: what the video page's tag list and the up-next markup read today, with tags in the bodies and `?api=` in the URL."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_frontend_tag_chips import BASE, FRONTEND, SIMILARS_RUNNER, VIDEO_PAGE_RUNNER, _build, _classes, _elements, _node, _Tree  # noqa: E402


def test_probe(tmp_path):
    bundle = _build(tmp_path, "page.mjs", dev=False, entry=FRONTEND / "src" / "pages" / "video-page" / "index.ts")
    (tmp_path / "video.mjs").write_text(VIDEO_PAGE_RUNNER)
    (tmp_path / "similars.mjs").write_text(SIMILARS_RUNNER)
    search = "?id=v1&host=peer.example&api=http%3A%2F%2Fapi.example"
    body = {"videoUuid": "uuid-1", "title": "Tag fixture", "tags": ["alpha", "a b&c", "   ", "\U0001F600" * 65]}
    video = _node(tmp_path / "video.mjs", {"BASE": BASE, "BUNDLE": str(bundle), "SEARCH": search, "VIDEO_BODY": json.dumps(body)})
    rows = [{"video_id": "v0", "instance_domain": "videos.example", "title": "R0", "tags": ["lo-fi & chill", "beats"]},
            {"video_id": "v1", "instance_domain": "videos.example", "title": "R1", "tags": ["   ", "study"]}]
    similars = _node(tmp_path / "similars.mjs", {"BASE": BASE, "BUNDLE": str(bundle), "SEARCH": search, "RECOMMENDATIONS_BODY": json.dumps({"rows": rows, "seed": {"mode": "upnext"}})})
    tree = _Tree(similars["similar"])
    outline = [(n["tag"], _classes(n), n["attrs"].get("data-video-key")) for n in _elements(tree.root) if n["tag"] in ("a", "div")]
    assert False, json.dumps({"video": video, "similars_requests": similars["requests"], "rejections": similars["rejections"], "outline": outline}, indent=1)
