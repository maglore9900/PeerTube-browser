"""Measure TRENDING_PATH's uncompressed size on large catalogue hosts (urllib sends no Accept-Encoding, as curl without --compressed)."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "engine" / "server" / "db" / "whitelist.db"
PATH = "/api/v1/videos?sort=-trending&isLocal=true&count=100&nsfw=both"


def _size(host: str) -> str:
    try:
        with urlopen(Request(f"https://{host}{PATH}", headers={"User-Agent": "peertube-browser-trending/1.0"}), timeout=30) as resp:
            body = resp.read()
            return f"{host} status={resp.status} encoding={resp.headers.get('content-encoding')} bytes={len(body)}"
    except Exception as exc:  # noqa: BLE001
        return f"{host} FAILED {type(exc).__name__}: {exc}"


def test_measure():
    hosts = ["framatube.org", "tilvids.com"]
    print("db", DB, DB.is_file())
    if DB.is_file():
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        top = conn.execute("SELECT instance_domain, COUNT(*) AS n FROM video_embeddings GROUP BY instance_domain ORDER BY n DESC LIMIT 15").fetchall()
        conn.close()
        print("top by video_embeddings:", top)
        hosts += [host for host, _ in top if host not in hosts]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for line in pool.map(_size, hosts):
            print(line)
