"""Every row an Engine listing route serves carries the tags whitelist.db stores for it, against the session Engine and the read-only `dataset` connection.

- Up-next, search, and each mode in the production `FEED_MODES` (read under the Engine interpreter by `test_similar._feed_constants`; Following with a `follows` body naming a channel whose newest embedded video is tagged): every row has a `tags` key whose value is a list of strings equal to `tags_from_json` of the `tags_json` that this file's `tags_json_of` reads from the `videos` table for that `(video_id, instance_domain)`, and at least one row of the route's page has a non-empty `tags`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import dataset, engine, shared_trending_before, trending_seed  # noqa: E402,F401
# Importing test_similar runs its `_feed_constants` child and puts the Engine dirs on sys.path.
from test_similar import FEED_CONSTANTS_ERROR, FEED_MODES  # noqa: E402
from handlers.video import tags_from_json  # noqa: E402

SEARCH_QUERY = "music"
# This test's own Engine rate bucket, clear of every other address tests/ uses.
TAGS_HEADERS = {"X-Client-IP": "192.0.2.197"}
# Read at collection, so the parametrisation follows the production mode list.
ROUTES = ["upnext", "search", *(f"mode={mode}" for mode in FEED_MODES)] if FEED_MODES is not None else ["FEED_MODES unreadable"]


def tags_json_of(dataset, video_id: str, instance_domain: str) -> str | None:
    """The tags_json whitelist.db holds for one video."""
    row = dataset.execute(
        "SELECT tags_json FROM videos WHERE video_id = ? AND instance_domain = ?",
        (video_id, instance_domain),
    ).fetchone()
    assert row is not None, f"{video_id}@{instance_domain} not in whitelist.db"
    return row["tags_json"]


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
    assert row is not None, "control: whitelist.db holds no channel whose newest embedded video is tagged"
    return [row["instance_domain"], row["channel_id"]]


def _rows(engine, dataset, route: str) -> list[dict]:
    if route == "search":
        status, body = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=20", headers=TAGS_HEADERS)
    elif route == "upnext":
        status, seed = engine.request("GET", f"/api/v1/search/videos?q={SEARCH_QUERY}&limit=1", headers=TAGS_HEADERS)
        assert status == 200 and seed["rows"], seed
        first = seed["rows"][0]
        status, body = engine.request("POST", f"/recommendations?id={first['video_uuid']}&host={first['instance_domain']}&limit=8", headers=TAGS_HEADERS, body={})
    elif route == "mode=following":
        follows = {"channels": [_followed_channel(dataset)], "accounts": []}
        status, body = engine.request("POST", "/recommendations?mode=following", headers=TAGS_HEADERS, body={"follows": follows})
    else:
        status, body = engine.request("POST", f"/recommendations?{route}", headers=TAGS_HEADERS, body={})
    assert status == 200, (route, status, body)
    return body["rows"]


@pytest.mark.parametrize("route", ROUTES)
def test_every_row_a_listing_route_serves_carries_the_tags_whitelist_db_stores_for_it(engine, dataset, route):
    assert FEED_MODES is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter read FEED_MODES
    rows = _rows(engine, dataset, route)
    assert rows, f"{route} returned no rows to check"  # control: an empty page checks nothing
    for row in rows:
        stored = tags_json_of(dataset, row["video_id"], row["instance_domain"])
        expected = tags_from_json(stored)
        # Control: the oracle agrees with a plain stdlib reading of the stored value; whitelist.db holds only NULL, '[]' and string lists (observed).
        assert expected == ([] if stored is None else json.loads(stored)), (row["video_id"], stored)
        # The previous projection had no `tags` key at all.
        assert "tags" in row, (route, row["video_id"])  # C1
        # A projection passing tags_json through serves a str; one serving NULL storage as None serves None.
        assert isinstance(row["tags"], list), (route, row["video_id"], row["tags"])  # C1
        assert all(isinstance(tag, str) for tag in row["tags"]), (route, row["video_id"], row["tags"])  # C1
        # Another video's tags, a sorted or deduplicated list differ here; search, recommendations, trending and random pages each held 1 to 3 rows stored out of sorted order (observed).
        assert row["tags"] == expected, (route, row["video_id"], stored, row["tags"])  # C1
    # Observed 2 to 46 tagged rows per route (Recent 10 of 48), so a projection that always serves [] fails here.
    assert any(row["tags"] for row in rows), f"{route}: no row carried a non-empty tags list"  # C1
