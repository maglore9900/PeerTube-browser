import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def test_probe(engine):
    status, home = engine.request("POST", "/recommendations", body={})
    print("home status", status, "rows", len(home["rows"]), "seed", home.get("seed"))
    for query in ("linux", "cooking"):
        status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
        seed = body["rows"][0]
        status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=48&debug=1", body={})
        print(query, "status", status, "rows", len(body["rows"]), "seed", body.get("seed"))
        print(query, "scores", [r.get("debug", {}).get("similarity_score") for r in body["rows"]])
    status, body = engine.request("GET", "/api/v1/search/videos?q=music&limit=20")
    print("search keys", sorted(body.keys()), "vectorSearch", body.get("vectorSearch"))
    assert False, "probe"
