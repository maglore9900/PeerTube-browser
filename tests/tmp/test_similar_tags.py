"""Every row the Engine serves carries its stored tags, and `/api/v1/search/videos` answers a lone tag and refuses every other tag request, against the session Engine and the read-only `dataset` connection.

- Up-next, search, and each mode in the production `FEED_MODES` (read under the Engine interpreter at collection; Following with a `follows` body naming a channel whose newest embedded video is tagged): every row's `tags` is `[]` where the stored `tags_json` is NULL, empty, malformed or not a list, the stored list itself (same strings, same order) where it is a JSON list of strings, and only its strings where it is a mixed list; and at least one row per route carries a non-empty list, except Recent, whose first page the dev dataset leaves untagged.
- `?tag=LINUX` and `?tag=MUSIC` answer 200 with at least 10 rows, every one carrying the tag after trimming and lowercasing. The matches are found independently in Python over `whitelist.db` (NSFW-flagged rows left out): the page is the 50 newest of them in order (less any moderation removed), `sort` is `published_at`, `vectorSearch` is false, and `total` is their count. The same word as a text search reports a total within two candidate pools, below the tag total. `sort=relevance` echoes `published_at` and returns the same rows; `sort=views` echoes `views` and returns the 50 most-viewed matches in order, which are not drawn from the newest page.
- Each refused request answers 400 with a JSON `error` string, while the request one defect away answers 200 with its rows (none only for the 64-character tag, which no video carries): `q` and `tag` together and two `tag`s (against one `tag`), a blank tag (against a padded one), a 65-character tag (against 64 characters padded with spaces), `sort=bogus` (against `sort=popularity`), a bare `tag=` and no parameter (against `tag=linux`).
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT, dataset, engine, shared_trending_before, trending_seed  # noqa: E402,F401

SERVER_DIR = ROOT / "engine" / "server"
SEARCH_QUERY = "music"
# Two stored tags with different match counts, requested upper-cased so the Engine must fold case.
TAGS = ("linux", "music")
TAG_LIMIT = 50
# Each test spends its own Engine rate bucket.
ROWS_HEADERS = {"X-Client-IP": "192.0.2.181"}
TAG_HEADERS = {"X-Client-IP": "192.0.2.182"}
REFUSAL_HEADERS = {"X-Client-IP": "192.0.2.183"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss.
_FEED_MODES_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    import server_config
    print(json.dumps({"modes": list(similar.FEED_MODES), "pool": server_config.SEARCH_CANDIDATE_POOL}))
    """
)


def _engine_constants() -> dict:
    run = subprocess.run([str(ENGINE_PY), "-c", _FEED_MODES_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


# Read once at collection, so the parametrisation follows the production mode list.
ENGINE_CONSTANTS = _engine_constants()
ROUTES = ["upnext", "search", *(f"mode={mode}" for mode in ENGINE_CONSTANTS["modes"])]
# Text search fuses two pooled halves, so its total is at most two pools.
TEXT_TOTAL_MAX = 2 * ENGINE_CONSTANTS["pool"]


def _followed_channel(dataset) -> list[str]:
    """A channel whose newest embedded video has a non-empty tag list, so page 1 of Following has tags to check."""
    row = dataset.execute(
        """
        SELECT v.instance_domain, v.channel_id FROM videos v
        JOIN video_embeddings e ON e.video_id = v.video_id AND e.instance_domain = v.instance_domain
        WHERE v.tags_json LIKE '["%' AND v.published_at = (
          SELECT MAX(w.published_at) FROM videos w
          JOIN video_embeddings f ON f.video_id = w.video_id AND f.instance_domain = w.instance_domain
          WHERE w.instance_domain = v.instance_domain AND w.channel_id = v.channel_id)
        ORDER BY v.published_at DESC LIMIT 1
        """
    ).fetchone()
    return [row["instance_domain"], row["channel_id"]]


# The dev dataset's newest 2000+ videos have NULL tags_json (the dataset build's tags stage lags),
# so page 1 of Recent serves no tagged row. Its rows are still checked one by one above;
# the non-empty floor that rules out an always-empty `tags` is armed on every other route.
# Operator-approved 2026-10-06 after the checkpoint gated.
NO_TAGGED_ROW_ROUTES = {"mode=recent"}


def _route_rows(engine, dataset, route: str) -> list[dict]:
    if route == "search":
        status, body = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=20", headers=ROWS_HEADERS)
    elif route == "upnext":
        status, seed = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=1", headers=ROWS_HEADERS)
        assert status == 200, seed
        first = seed["rows"][0]
        status, body = engine.request("POST", f"/recommendations?id={first['video_uuid']}&host={first['instance_domain']}&limit=8", headers=ROWS_HEADERS, body={})
    elif route == "mode=following":
        follows = {"channels": [_followed_channel(dataset)], "accounts": []}
        status, body = engine.request("POST", "/recommendations?mode=following", headers=ROWS_HEADERS, body={"follows": follows})
    else:
        status, body = engine.request("POST", f"/recommendations?{route}", headers=ROWS_HEADERS, body={})
    assert status == 200, (route, status, body)
    return body["rows"]


def _stored_tags_json(dataset, row: dict):
    found = dataset.execute(
        "SELECT tags_json FROM videos WHERE video_id = ? AND instance_domain = ?", (row["video_id"], row["instance_domain"])
    ).fetchone()
    assert found is not None, row["video_id"]
    return found["tags_json"]


@pytest.mark.parametrize("route", ROUTES)
def test_every_row_a_route_serves_carries_its_stored_tags_in_order(engine, dataset, route):
    rows = _route_rows(engine, dataset, route)
    assert rows, f"{route} returned no rows to check"
    tagged = 0
    for row in rows:
        stored = _stored_tags_json(dataset, row)
        try:
            parsed = json.loads(stored) if stored else None
        except ValueError:
            parsed = None
        if stored is None:
            assert row.get("tags") == [], (route, row["video_id"])  # C1: NULL stored tags give an empty list
        elif isinstance(parsed, list) and all(isinstance(tag, str) for tag in parsed):
            # The stored list read by the stdlib parser, independent of the Engine's: same strings, same order, no dedup.
            assert row.get("tags") == parsed, (route, row["video_id"], stored)  # C1
            tagged += bool(parsed)
        else:
            # Empty, malformed or non-list storage gives [], and a mixed list keeps only its strings.
            expected = [tag for tag in parsed if isinstance(tag, str)] if isinstance(parsed, list) else []
            assert row.get("tags") == expected, (route, row["video_id"], stored)  # C1
    if route not in NO_TAGGED_ROW_ROUTES:
        assert tagged, f"{route}: no row carried a non-empty stored tag list"  # C1: an always-empty `tags` cannot pass


def _direct_matches(dataset, tag: str) -> list[dict]:
    """Videos whose stored tags hold `tag` after trimming and lowercasing, NSFW-flagged ones left out, found in Python rather than in the Engine's SQL."""
    matches = []
    for row in dataset.execute("SELECT video_id, instance_domain, tags_json, nsfw, published_at, views FROM videos WHERE tags_json LIKE ?", (f"%{tag}%",)):
        if row["nsfw"] == 1:
            continue
        try:
            parsed = json.loads(row["tags_json"])
        except ValueError:
            continue
        if isinstance(parsed, list) and any(isinstance(t, str) and t.strip(" \t\r\n").lower() == tag for t in parsed):
            matches.append(dict(row))
    return matches


def _leading(matches: list[dict], field: str) -> list[tuple[str, str]]:
    """The first page of matches by `field` descending, then video_id descending; SQLite sorts NULL last in DESC."""
    ordered = sorted(matches, key=lambda m: (m[field] is not None, m[field] or 0, m["video_id"]), reverse=True)
    return [(m["video_id"], m["instance_domain"]) for m in ordered[:TAG_LIMIT]]


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    return [(row["video_id"], row["instance_domain"]) for row in rows]


def _is_ordered_subset(page: list[tuple[str, str]], leading: list[tuple[str, str]]) -> bool:
    """True when the page is the leading matches in their order, less any rows moderation removed."""
    kept = set(page)
    return set(page) <= set(leading) and page == [key for key in leading if key in kept]


def _carries(row: dict, tag: str) -> bool:
    return any(t.strip(" \t\r\n").lower() == tag for t in row.get("tags") or [])


def _search(engine, query: str) -> tuple[int, dict]:
    return engine.request("GET", f"/api/v1/search/videos?{query}", headers=TAG_HEADERS)


@pytest.mark.parametrize("tag", TAGS)
def test_a_lone_tag_is_answered_with_every_video_carrying_it_newest_first_or_in_the_asked_sort(engine, dataset, tag):
    upper = quote(tag.upper())
    status, newest = _search(engine, f"tag={upper}&limit={TAG_LIMIT}")
    assert status == 200, newest  # C2
    rows = newest["rows"]
    assert len(rows) >= 10, len(rows)  # control: enough rows for an order to mean something
    assert all(_carries(row, tag) for row in rows), [row["tags"] for row in rows if not _carries(row, tag)]  # C2
    matches = _direct_matches(dataset, tag)
    # The newest matches of all, in order, not some other subset sorted by date.
    assert _is_ordered_subset(_keys(rows), _leading(matches, "published_at")), _keys(rows)[:5]  # C2
    assert newest["sort"] == "published_at"  # C2
    assert newest["vectorSearch"] is False  # C2
    assert newest["total"] == len(matches)  # C2: every match, not one page or a pool
    status, text = _search(engine, f"q={quote(tag)}&limit=20")
    assert status == 200 and text["total"] <= TEXT_TOTAL_MAX < newest["total"], (text.get("total"), newest["total"])  # the same word as text stays pooled

    status, relevance = _search(engine, f"tag={upper}&limit={TAG_LIMIT}&sort=relevance")
    assert status == 200 and relevance["sort"] == "published_at", relevance  # C2: relevance resolves to newest
    assert [r["video_id"] for r in relevance["rows"]] == [r["video_id"] for r in rows]  # C2

    status, by_views = _search(engine, f"tag={upper}&limit={TAG_LIMIT}&sort=views")
    assert status == 200 and by_views["sort"] == "views", by_views  # C2
    assert len(by_views["rows"]) >= 10, len(by_views["rows"])  # control
    assert all(_carries(row, tag) for row in by_views["rows"])  # C2
    # The most-viewed matches of all, in order, not the newest page re-sorted.
    assert _is_ordered_subset(_keys(by_views["rows"]), _leading(matches, "views")), _keys(by_views["rows"])[:5]  # C2
    assert not set(_keys(by_views["rows"])) <= set(_keys(rows))  # control: the most-viewed page is not drawn from the newest one


@pytest.mark.parametrize("refused, accepted, has_matches", [
    ("q=music&tag=linux", "tag=linux", True),  # both q and tag
    ("tag=linux&tag=music", "tag=linux", True),  # two tags
    ("tag=%20", "tag=%20linux%20", True),  # blank after trimming
    ("tag=" + "a" * 65, "tag=%20" + "a" * 64 + "%20", False),  # over 64 characters after trimming; no stored tag is that long
    ("tag=linux&sort=bogus", "tag=linux&sort=popularity", True),  # unsupported sort
    ("tag=", "tag=linux", True),  # a bare tag carries none
    ("limit=5", "tag=linux&limit=5", True),  # neither q nor tag
])
def test_a_tag_request_is_refused_400_unless_it_is_a_lone_non_blank_tag_of_at_most_64_characters(engine, refused, accepted, has_matches):
    status, body = engine.request("GET", f"/api/v1/search/videos?{accepted}", headers=REFUSAL_HEADERS)
    assert status == 200 and isinstance(body.get("rows"), list), (accepted, status, body)  # C2: the request one defect away is answered
    assert bool(body["rows"]) is has_matches, (accepted, len(body["rows"]))  # C2: with its matches, so a padded tag is trimmed rather than missed
    status, body = engine.request("GET", f"/api/v1/search/videos?{refused}", headers=REFUSAL_HEADERS)
    assert status == 400, (refused, status, body)  # C2
    assert isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"], body  # C2
