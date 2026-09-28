import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def test_probe(engine):
    status, body = engine.request("GET", "/api/v1/search/videos?q=linux&limit=1")
    seed = body["rows"][0]
    status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=48&debug=1", body={})
    print("status", status, "rows", len(body["rows"]), "keys", sorted(body["rows"][0].keys()))
    print("debug", body["rows"][0].get("debug"))
    print("scores", [r["debug"].get("similarity_score") for r in body["rows"]])
    print("seed in rows", any(r["video_uuid"] == seed["video_uuid"] for r in body["rows"]))
    assert False, "probe"
