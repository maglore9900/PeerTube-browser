"""The Client backend carries a browser's `exclude` to the Engine, keyed profiles included, and
caps it at 500 entries.

- A keyed home request, for a profile holding five likes and four dislikes (so the Client rewrites
  the body with the profile's likes and taste vectors), carrying 500 `exclude` entries - a
  previous keyed page's rows, topped up with the dataset's longest-host videos to over 50 KB of
  `exclude` alone - is answered 200 with a home page holding none of them, where the same
  request without `exclude` repeats rows of that page.
- The Client answers 400 `Invalid exclude payload` to 501 entries, and passes 500 on to the
  Engine (a closed port here, so 502).

The keyed Client is the `unpublished_client` fixture.
"""
from __future__ import annotations

import json
from urllib.parse import quote

EXCLUDE_CAP = 500


def _mint(client) -> dict[str, str]:
    status, body = client.request("POST", "/api/profile")
    assert status == 201, body
    return {"X-Profile-Key": body["key"]}


def _search(client, query: str, n: int) -> list[dict]:
    status, body = client.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit={n}")
    assert status == 200 and len(body["rows"]) == n, body
    return body["rows"]


def _home(client, headers, body: dict) -> list[dict]:
    status, payload = client.request("POST", "/recommendations", headers=headers, body=body)
    assert status == 200, payload
    assert payload["seed"].get("mode") == "home" and not payload["seed"].get("random"), payload["seed"]
    return payload["rows"]


def _keys(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _longest_host_entries(dataset, n: int, skip: set[tuple[str, str]]) -> list[dict]:
    rows = dataset.execute(
        "SELECT video_id, instance_domain FROM videos ORDER BY length(instance_domain) DESC LIMIT ?",
        (n + len(skip),),
    ).fetchall()
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows
               if (r["video_id"], r["instance_domain"]) not in skip]
    return entries[:n]


def test_a_keyed_request_s_500_entry_exclude_reaches_the_engine_and_none_of_it_is_returned(
        unpublished_client, dataset):
    client = unpublished_client
    key = _mint(client)
    liked = {(row["video_uuid"], row["instance_domain"]) for row in _search(client, "linux", 5)}
    for uuid, host in liked:
        # 502: the like is stored, then its Like event cannot be published in this mode.
        client.request("POST", "/api/user-action", headers=key, body={"action": "like", "uuid": uuid, "host": host})
    status, body = client.request("GET", "/api/user-profile/likes", headers=key)
    assert status == 200, body
    assert {(r["video_uuid"], r["instance_domain"]) for r in body["likes"]} == liked  # the profile holds the likes
    # Four dislikes give the four taste vectors (min(4, n)) that make the Engine's body largest.
    for disliked in _search(client, "cooking", 4):
        status, body = client.request("POST", "/api/user-action", headers=key,
                                      body={"action": "dislike", "uuid": disliked["video_uuid"],
                                            "host": disliked["instance_domain"]})
        assert status == 200, body  # control: the dislike and its taste vectors are stored

    previous = _home(client, key, {})
    plain = _home(client, key, {})
    assert _keys(previous) & _keys(plain), "control: a plain keyed page repeats none of the previous one"

    exclude = [{"id": v, "host": h} for v, h in _keys(previous)]
    exclude += _longest_host_entries(dataset, EXCLUDE_CAP - len(exclude), _keys(previous))
    assert len(exclude) == EXCLUDE_CAP
    # control: with the ~16 KB of four taste vectors the Client adds, the Engine's body passes 64 KB
    assert len(json.dumps({"exclude": exclude})) > 50_000

    page = _home(client, key, {"exclude": exclude})  # C1: 200, a home page

    excluded = {(e["id"], e["host"]) for e in exclude}
    assert page, "the page is empty"  # C1
    assert not _keys(page) & excluded, sorted(_keys(page) & excluded)  # C1


def test_the_client_refuses_501_exclude_entries_and_passes_500_on_to_the_engine(client_backend, dataset):
    rows = dataset.execute("SELECT video_id, instance_domain FROM videos LIMIT ?", (EXCLUDE_CAP + 1,)).fetchall()
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]

    status, body = client_backend.request("POST", "/recommendations", body={"exclude": entries[:EXCLUDE_CAP]})
    assert status == 502, body  # C2: past validation, to the (closed) Engine

    status, body = client_backend.request("POST", "/recommendations", body={"exclude": entries})
    assert (status, body.get("error")) == (400, "Invalid exclude payload"), body  # C2
