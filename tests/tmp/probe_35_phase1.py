"""Probe: the drafted conftest helpers, inlined, run against the session Engine; prints what the checkpoint would read."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "tests" / "active"
if str(ACTIVE) not in sys.path:
    sys.path.insert(0, str(ACTIVE))

from conftest import engine  # noqa: E402,F401

H = {"X-Client-IP": "192.0.2.150"}
T = {"X-Client-IP": "192.0.2.152"}
X = {"X-Client-IP": "192.0.2.151"}


def _key(r):
    return (r["video_id"], r["instance_domain"])


def _ex(rows):
    return [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]


def _page(engine, route, seed, exclude):
    path = f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=96&seed=0&debug=1"
    status, body = engine.request("POST", path, headers=H, body={"exclude": exclude})
    assert status == 200, body
    return body["rows"]


def _seed(engine, q):
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(q)}&limit=1")
    return body["rows"][0]


@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_probe_pin(engine, route):
    seed = _seed(engine, "linux")
    listed = {}
    first_page = None
    pages = []
    for _ in range(7):
        page = _page(engine, route, seed, _ex(listed.values()))
        pages.append(len(page))
        if first_page is None:
            first_page = page
        if not page:
            break
        listed.update((_key(r), r) for r in page)
    listing_order = list(listed.values())
    lo_scores = [r["debug"]["similarity_score"] for r in listing_order]
    print(f"\n{route}: pages {pages}, pool {len(listed)}, listing order non-increasing: {lo_scores == sorted(lo_scores, reverse=True)}")
    pool = sorted(listed.values(), key=lambda r: (-r["debug"]["similarity_score"], _key(r)))
    base = f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}"
    s, b = engine.request("POST", base + "&limit=96", headers=T, body={"exclude": _ex(pool)})
    print(f"{route}: exclude whole pool, limit 96 -> status {s}, {len(b['rows'])} rows")
    # wrong: pool from the first page only
    s, b = engine.request("POST", base + "&limit=96", headers=T, body={"exclude": _ex(first_page)})
    print(f"{route}: exclude first page only, limit 96 -> {len(b['rows'])} rows")
    s, b = engine.request("POST", base + "&limit=16", headers=T, body={})
    print(f"{route}: unpinned limit 16 -> {len(b['rows'])} rows")
    head = pool[:8]
    pin = _ex(pool[8:])
    for limit in (8, 16):
        s, b = engine.request("POST", base + f"&limit={limit}", headers=T, body={"exclude": pin})
        print(f"{route}: pinned limit {limit} -> {len(b['rows'])} rows, equals head: {sorted(map(_key, b['rows'])) == sorted(map(_key, head))}")
    # wrong: pin built from the listing-order head of a single page
    pin_partial = _ex([r for r in first_page[8:]])
    s, b = engine.request("POST", base + "&limit=16", headers=T, body={"exclude": pin_partial})
    print(f"{route}: partial pin (first page minus its 8) limit 16 -> {len(b['rows'])} rows")
    # wrong: head by listing order
    lo_head = set(map(_key, listing_order[:8]))
    print(f"{route}: listing-order head == score head: {lo_head == set(map(_key, head))}")


@pytest.mark.parametrize("query", ["linux", "cooking"])
def test_probe_exclude(engine, query):
    seed = _seed(engine, query)
    path = f"/recommendations?id={seed['video_uuid']}&host={seed['instance_domain']}&limit=8&debug=1&seed=7"
    s, first = engine.request("POST", path, headers=X, body={})
    s2, again = engine.request("POST", path, headers=X, body={})
    prev = [_key(r) for r in first["rows"]]
    print(f"\n{query}: first {len(prev)} rows, seeded repeat equal: {[_key(r) for r in again['rows']] == prev}")
    for excluded in (prev, prev[0::2]):
        s, page = engine.request("POST", path, headers=X, body={"exclude": [{"id": a, "host": b} for a, b in excluded]})
        rows = page["rows"]
        keys = [_key(r) for r in rows]
        print(f"{query}: excluded {len(excluded)} -> {len(rows)} rows, distinct {len(set(keys))}, overlap {len(set(keys) & set(excluded))}, min score {min(r['debug']['similarity_score'] for r in rows):.3f}")
