"""Probe: do short-cached seeds picked from similarity-cache.db fill a 48-row up-next page through the ANN fallback, and does the gateway's up-next for the flagged seed carry flagged rows at 48?"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import dataset, engine, engine_client  # noqa: E402,F401
from test_similar import FALLBACK_PREFIX, ROOT, _config, _messages  # noqa: E402
from data.similarity_cache import NEIGHBOUR  # noqa: E402


def _candidates(dataset, lo, hi, count):
    conn = sqlite3.connect(f"file:{ROOT / _config().DEFAULT_SIMILARITY_DB_PATH}?mode=ro", uri=True)
    out = []
    for vid, host, size in conn.execute(
            "SELECT k.video_id, k.instance_domain, length(s.neighbours) FROM similarity_sources s JOIN video_keys k ON k.key = s.source_key "
            "WHERE length(s.neighbours) BETWEEN ? AND ? ORDER BY s.source_key", (lo * NEIGHBOUR.size, hi * NEIGHBOUR.size)):
        row = dataset.execute("SELECT video_uuid, nsfw, error_count FROM videos WHERE video_id = ? AND instance_domain = ?", (vid, host)).fetchone()
        out.append((vid, host, size // NEIGHBOUR.size, None if row is None else (row["video_uuid"], row["nsfw"], row["error_count"])))
        if len(out) == count:
            break
    conn.close()
    return out


def test_probe_short_seeds(engine, dataset):
    floor = _config().SIMILAR_VIDEO_TAIL_MIN_SCORE
    t = time.time()
    cands = _candidates(dataset, 10, 30, 8)
    print(f"\nPROBE select took {time.time() - t:.2f}s")
    for vid, host, size, row in cands:
        if row is None or row[1]:
            print(f"PROBE {vid}@{host} n={size} row={row} SKIP")
            continue
        before = len(_messages(engine.db_path, FALLBACK_PREFIX))
        res = []
        for limit in (48, 30):
            status, body = engine.request("POST", f"/recommendations?id={row[0]}&host={host}&limit={limit}&debug=1", body={}, headers={"X-Client-IP": "192.0.2.250"})
            rows = body.get("rows", []) if isinstance(body, dict) else []
            low = sum(1 for r in rows if r.get("debug", {}).get("similarity_score", 0) < floor - 1e-6)
            res.append((status, len(rows), low))
        time.sleep(0.5)
        print(f"PROBE {vid}@{host} n={size} err={row[2]} pages={res} fallbacks={len(_messages(engine.db_path, FALLBACK_PREFIX)) - before}")


def test_probe_gateway_flagged_upnext(engine_client, dataset):
    flagged = {(r[0], r[1]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    for route in ("/recommendations", "/videos/similar"):
        counts = []
        for i in range(5):
            status, body = engine_client.request("POST", f"{route}?id=59b6239b-15c6-4bc4-b5e6-6ebac4ea9751&host=810video.com&nsfw=1",
                                                 headers={"X-Forwarded-For": f"198.19.200.{i + 1}"}, body={})
            counts.append((status, len(body.get("rows", [])), sum((r["video_id"], r["instance_domain"]) in flagged for r in body.get("rows", []))))
        status, body = engine_client.request("POST", f"{route}?id=59b6239b-15c6-4bc4-b5e6-6ebac4ea9751&host=810video.com",
                                             headers={"X-Forwarded-For": "198.19.201.1"}, body={})
        plain = (status, len(body.get("rows", [])), sum((r["video_id"], r["instance_domain"]) in flagged for r in body.get("rows", [])))
        print(f"\nPROBE gateway {route} nsfw=1 (status, rows, flagged)={counts} plain={plain}")
