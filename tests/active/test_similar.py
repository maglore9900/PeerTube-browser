"""The Engine's feed and search responses, against a real Engine on the repo's dataset.

- Every row of a home, random, up-next and search response carries the `channel_id` and
  `account_url` that `whitelist.db` holds for that video: the identity the Client's
  per-profile blocks match on.
- Home and random serve more than the default page when asked for twice it, which the
  Client's over-fetch for visitors with blocks relies on.
- A home request carrying `exclude` with a previous home page's rows returns none of them,
  where the same request without `exclude` repeats some, and still at least 45 rows: the fewest
  any plain home page returned in 24 measured draws. Skipping the excluded rows after mixing,
  with no spare candidates gathered, leaves about 27-37. Every request sends the same five
  likes, so the like-seeded layers draw from the same shallow pool and repeat across pages.
- For a seed whose ranked pool fills two 8-row pages, an up-next request excluding the previous
  8-row page, or every other row of it, returns the next 8 rows of that ranked pool with the
  excluded rows removed, where the same request without `exclude` returns that page again.
- `/recommendations` and `/videos/similar` answer 400 "Too many exclude entries in request body"
  to 501 `exclude` entries and 200 to 500, the entries being real videos from `whitelist.db`.
"""
from __future__ import annotations

import importlib.util
from urllib.parse import quote

import pytest
from conftest import ROOT, identity_of

SEARCH_QUERY = "music"
LIKE_QUERIES = ("linux", "cooking", "music")
PLAIN_FLOOR = 45
# Seeds whose up-next pool was 19 and 17 deep when measured.
UPNEXT_SEED_QUERIES = ("linux", "cooking")
UPNEXT_PAGE = 8
EXCLUDE_CAP = 500


def _default_limit() -> int:
    spec = importlib.util.spec_from_file_location(
        "engine_server_config", ROOT / "engine" / "server" / "api" / "server_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(module.BATCH_SIZE)


def _rows(engine, route: str) -> list[dict]:
    if route == "search":
        status, body = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=20")
    elif route == "upnext":
        status, seed = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=1")
        assert status == 200, seed
        first = seed["rows"][0]
        status, body = engine.request(
            "POST", f"/recommendations?id={first['video_uuid']}&host={first['instance_domain']}&limit=8",
            body={})
    elif route == "random":
        status, body = engine.request("POST", "/recommendations?random=1", body={})
    else:
        status, body = engine.request("POST", "/recommendations", body={})
    assert status == 200, body
    return body["rows"]


@pytest.mark.parametrize("route", ["home", "random", "upnext", "search"])
def test_every_row_carries_the_channel_and_account_the_dataset_holds(engine, dataset, route):
    rows = _rows(engine, route)
    assert rows, f"{route} returned no rows to check"
    for row in rows:
        expected = identity_of(dataset, row["video_id"], row["instance_domain"])
        # A stored NULL would equal a missing key; the dataset holds none, and this keeps it so.
        assert expected["channel_id"] and expected["account_url"], row["video_id"]
        assert "channel_id" in row and "account_url" in row, (route, row["video_id"])
        assert row.get("channel_id") == expected["channel_id"], (route, row["video_id"])
        assert row.get("account_url") == expected["account_url"], (route, row["video_id"])


@pytest.mark.parametrize("path", ["/recommendations", "/recommendations?random=1"])
def test_home_and_random_return_more_than_the_default_page_when_asked_for_twice_it(engine, path):
    default = _default_limit()
    sep = "&" if "?" in path else "?"

    status, body = engine.request("POST", f"{path}{sep}limit={default}", body={})
    assert status == 200, body
    assert len(body["rows"]) == default  # control: the pool fills a default page

    status, body = engine.request("POST", f"{path}{sep}limit={default * 2}", body={})
    assert status == 200, body
    assert len(body["rows"]) > default, len(body["rows"])


def _likes(engine, query: str) -> list[dict]:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=5")
    assert status == 200 and len(body["rows"]) == 5, body
    return [{"uuid": r["video_uuid"], "host": r["instance_domain"]} for r in body["rows"]]


def _home(engine, body: dict) -> list[dict]:
    status, payload = engine.request("POST", "/recommendations", body=body)
    assert status == 200, payload
    # An empty mix falls back to a random draw marked `random`; that draw is not a home page.
    assert payload["seed"].get("mode") == "home" and not payload["seed"].get("random"), payload["seed"]
    return payload["rows"]


def _key_set(rows: list[dict]) -> set[tuple[str, str]]:
    return {(r["video_id"], r["instance_domain"]) for r in rows}


def _key_list(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["video_id"], r["instance_domain"]) for r in rows]


@pytest.mark.parametrize("query", LIKE_QUERIES)
def test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page(engine, query):
    likes = _likes(engine, query)
    previous = _home(engine, {"likes": likes})
    plain = _home(engine, {"likes": likes})
    assert _key_set(previous) & _key_set(plain), "control: a plain page repeats none of the previous one"

    exclude = [{"id": r["video_id"], "host": r["instance_domain"]} for r in previous]
    page = _home(engine, {"likes": likes, "exclude": exclude})

    assert not _key_set(previous) & _key_set(page), sorted(_key_set(previous) & _key_set(page))
    assert len(page) >= PLAIN_FLOOR, len(page)


def _upnext_path(engine, query: str, route: str = "/recommendations") -> str:
    status, body = engine.request("GET", f"/api/v1/search/videos?q={quote(query)}&limit=1")
    assert status == 200 and body["rows"], body
    seed = body["rows"][0]
    return f"{route}?id={seed['video_uuid']}&host={seed['instance_domain']}&limit={UPNEXT_PAGE}"


@pytest.mark.parametrize("query", UPNEXT_SEED_QUERIES)
def test_upnext_excluding_the_previous_page_returns_a_full_page_of_other_videos(engine, query):
    path = _upnext_path(engine, query)
    status, first = engine.request("POST", path, body={})
    assert status == 200 and len(first["rows"]) == UPNEXT_PAGE, first
    previous = _key_list(first["rows"])
    status, plain = engine.request("POST", path, body={})
    assert status == 200 and _key_list(plain["rows"]) == previous, "control: the plain page does not repeat"
    # The seed's ranked pool two pages deep; the first page is its head.
    status, deep = engine.request(
        "POST", path.replace(f"limit={UPNEXT_PAGE}", f"limit={UPNEXT_PAGE * 2}"), body={})
    ranked = _key_list(deep["rows"])
    assert status == 200 and len(ranked) == UPNEXT_PAGE * 2 and ranked[:UPNEXT_PAGE] == previous, \
        "control: pool too shallow"

    # The whole previous page, and every other row of it, which offset paging would not reproduce.
    for excluded in (previous, previous[0::2]):
        exclude = [{"id": video_id, "host": host} for video_id, host in excluded]
        status, page = engine.request("POST", path, body={"exclude": exclude})
        assert status == 200, page

        expected = [key for key in ranked if key not in set(excluded)][:UPNEXT_PAGE]
        assert _key_list(page["rows"]) == expected, (excluded, _key_list(page["rows"]))


@pytest.mark.parametrize("route", ["/recommendations", "/videos/similar"])
def test_a_feed_request_with_more_than_500_exclude_entries_is_refused_and_500_is_served(engine, dataset, route):
    path = _upnext_path(engine, "linux", route)
    rows = dataset.execute("SELECT video_id, instance_domain FROM videos LIMIT ?", (EXCLUDE_CAP + 1,)).fetchall()
    assert len(rows) == EXCLUDE_CAP + 1
    entries = [{"id": r["video_id"], "host": r["instance_domain"]} for r in rows]

    status, body = engine.request("POST", path, body={"exclude": entries[:EXCLUDE_CAP]})
    assert status == 200 and body["rows"], body

    status, body = engine.request("POST", path, body={"exclude": entries})
    assert (status, body.get("error")) == (400, "Too many exclude entries in request body"), body
