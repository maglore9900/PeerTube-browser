import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import engine  # noqa: E402,F401


def test_probe_limits(engine):
    for query in ("linux", "cooking"):
        status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
        seed = body["rows"][0]
        for limit in (30, 48, 60, 96, 97):
            status, page = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={limit}&debug=1", body={})
            rows = page.get("rows") if isinstance(page, dict) else None
            print("PROBE", query, "limit", limit, "status", status, "rows", None if rows is None else len(rows), "seed", page.get("seed") if isinstance(page, dict) else page)
    assert False, "probe"
