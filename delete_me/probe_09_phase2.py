import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ROOT, engine  # noqa: E402,F401

CACHE = ROOT / "engine" / "server" / "db" / "similarity-cache.db"


def _keys(rows):
    return [(r["video_id"], r["instance_domain"]) for r in rows]


def test_probe(engine):
    print("cache", CACHE, CACHE.is_symlink(), CACHE.resolve(), CACHE.exists())
    conn = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    seeds = {}
    for query in ("linux", "cooking"):
        status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
        seed = body["rows"][0]
        seeds[query] = seed
        items = conn.execute("SELECT similar_video_id, similar_instance_domain, score, rank FROM similarity_items WHERE source_video_id=? AND source_instance_domain=? ORDER BY rank", (seed["video_id"], seed["instance_domain"])).fetchall()
        sources = conn.execute("SELECT * FROM similarity_sources WHERE video_id=? AND instance_domain=?", (seed["video_id"], seed["instance_domain"])).fetchall()
        print(query, "seed", seed["video_id"], seed["video_uuid"], seed["instance_domain"], "items", len(items), "sources", sources, "minscore", min((i[2] for i in items), default=None))
    s1 = engine.request("GET", "/api/v1/search/videos?q=music&limit=20")
    s2 = engine.request("GET", "/api/v1/search/videos?q=music&limit=20")
    print("search status", s1[0], s2[0], "len", len(s1[1]["rows"]), "equal", _keys(s1[1]["rows"]) == _keys(s2[1]["rows"]))
    h1 = engine.request("POST", "/recommendations", body={})
    h2 = engine.request("POST", "/recommendations", body={})
    print("home status", h1[0], "len", len(h1[1]["rows"]), "seed", h1[1]["seed"], "equal", _keys(h1[1]["rows"]) == _keys(h2[1]["rows"]))
    for query, seed in seeds.items():
        count = conn.execute("SELECT COUNT(*) FROM similarity_items WHERE source_video_id=? AND source_instance_domain=?", (seed["video_id"], seed["instance_domain"])).fetchone()[0]
        if count == 0:
            print(query, "no entry; skipping up-next so the shared cache is not written")
            continue
        status, body = engine.request("POST", f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=48", body={})
        print(query, "upnext48 status", status, "rows", len(body["rows"]), "seed", body.get("seed", {}).get("mode"))
    for line in engine.db_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        message = str(payload.get("message", ""))
        if "nprobe" in message or "similar-cache" in message or "rate" in message.lower():
            print("LOG", message[:300], payload.get("context"))
    assert False, "probe"
