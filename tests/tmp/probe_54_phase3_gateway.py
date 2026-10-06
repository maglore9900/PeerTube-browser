"""Probe: what the gateway forwards today for /recommendations?mode=following, and what the real Engine's Following page looks like."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ClientBackend, RateLimiter, client_server, dataset, engine, engine_client, ensure_user_schema, shared_trending_before, trending_seed  # noqa: E402,F401
from lib.blocks import add_block  # noqa: E402
from lib.dislikes import write_dislike  # noqa: E402
from lib.follows import add_follow  # noqa: E402
from lib.profiles import resolve_profile  # noqa: E402
from lib.users_store import record_like  # noqa: E402

ROWS = [{"video_id": f"v{i}", "video_uuid": f"u{i}", "instance_domain": "g.example", "channel_id": "ch-a", "account_url": "https://g.example/a/one", "title": str(i)} for i in range(6)]


def _stub(received):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            received.append((self.path, body))
            data = json.dumps({"seed": {}, "count": len(ROWS), "rows": ROWS, "cursor": "WzE3MDAwMDAwMDAwMDAsInYiLCJnIl0"}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    return ThreadingHTTPServer(("127.0.0.1", 0), H)


def test_probe_gateway_today(tmp_path):
    received = []
    eng = _stub(received)
    threading.Thread(target=eng.serve_forever, daemon=True).start()
    conn = client_server.connect_db(tmp_path / "users.db")
    ensure_user_schema(conn)
    srv = client_server.ClientBackendServer(("127.0.0.1", 0), client_server.ClientBackendHandler, conn, f"http://127.0.0.1:{eng.server_address[1]}", "bridge", RateLimiter(1000, 60))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = ClientBackend(f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "users.db")
    status, minted = client.request("POST", "/api/profile")
    c2 = client_server.connect_db(tmp_path / "users.db")
    pid = resolve_profile(c2, minted["key"])
    add_follow(c2, pid, {"kind": "channel", "instance_domain": "f.example", "channel_id": "fc", "account_url": "", "label": "F"})
    record_like(c2, pid, "like", {"video_id": "lv", "instance_domain": "l.example", "video_uuid": "lu"}, 50)
    add_block(c2, pid, {"kind": "channel", "instance_domain": "b.example", "channel_id": "bc", "account_url": "", "label": "B"})
    with c2:
        write_dislike(c2, pid, ROWS[1], {"space": "s", "vectors": [[1.0, 0.0]]})
    c2.close()
    hdr = {"X-Profile-Key": minted["key"]}
    browser = {"likes": [{"uuid": "bu", "host": "bh.example"}], "exclude": [{"id": "x", "host": "xh.example"}], "mode": "following"}
    for label, path, headers, body in [
        ("keyed following", "/recommendations?mode=following&limit=3", hdr, browser),
        ("keyed hot", "/recommendations?mode=hot&limit=3", hdr, browser),
        ("keyed seeded following", "/recommendations?mode=following&id=u9&host=g.example&limit=3", hdr, browser),
        ("keyless following", "/recommendations?mode=following&limit=3", {}, browser),
        ("cursor", "/recommendations?mode=following&limit=3", hdr, {"cursor": "abc"}),
        ("follows", "/recommendations?mode=following&limit=3", hdr, {"follows": {"channels": [], "accounts": []}}),
    ]:
        before = len(received)
        status, payload = client.request("POST", path, headers=headers, body=body)
        print(label, status, {k: v for k, v in (payload or {}).items() if k != "rows"}, [r["video_id"] for r in (payload or {}).get("rows", [])])
        for p, b in received[before:]:
            print("   engine got", urlparse(p).path, parse_qs(urlparse(p).query), json.dumps(b)[:300])
    srv.shutdown()
    eng.shutdown()


def test_probe_real_engine(engine, dataset):
    rows = dataset.execute(
        "SELECT v.instance_domain, v.channel_id, COUNT(*) n FROM videos v JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain "
        "WHERE v.error_count = 0 AND (v.nsfw IS NULL OR v.nsfw = 0) AND v.published_at IS NOT NULL GROUP BY 1, 2 HAVING n >= 12 ORDER BY n LIMIT 3"
    ).fetchall()
    print("channels", [tuple(r) for r in rows])
    host, cid = rows[0]["instance_domain"], rows[0]["channel_id"]
    status, p1 = engine.request("POST", "/recommendations?mode=following&limit=5", body={"follows": {"channels": [[host, cid]], "accounts": []}})
    print("p1", status, {k: v for k, v in p1.items() if k != "rows"})
    print("p1 rows", [(r.get("published_at"), r["video_id"], r["instance_domain"]) for r in p1["rows"]])
    print("row keys", sorted(p1["rows"][0].keys()))
    status, p2 = engine.request("POST", "/recommendations?mode=following&limit=5", body={"follows": {"channels": [[host, cid]], "accounts": []}, "cursor": p1["cursor"]})
    print("p2", status, {k: v for k, v in p2.items() if k != "rows"})
    print("p2 rows", [(r.get("published_at"), r["video_id"], r["instance_domain"]) for r in p2["rows"]])
    print("channel row", dict(dataset.execute("SELECT * FROM channels WHERE instance_domain = ? AND channel_id = ?", (host, cid)).fetchone() or {}))
