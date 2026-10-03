"""The session Engine, started by `tests/active/conftest.py`'s `engine` fixture, serves Trending and its popular layer from the session's private ranks, and the shared whitelist.db `trending_ranks` is left as it was:

- Controls: `shared_trending_before` shows a real fill in the shared table (rows with `fetched_at > 0`); `_feed_constants` reads the Engine's error threshold and its `DEFAULT_POPULAR_POOL_SIZE`; the private Trending order through `dataset` runs past three pages; on a fresh plain read-only connection the shared order's first three pages differ from it, and at least a quarter of the shared popular pool lies outside the private one.
- Three `mode=trending` pages, each excluding the rows served before it, are exactly the first three pages of `_reference(dataset, "trending", threshold)`.
- An unseeded `POST /recommendations?debug=1` serves at least one `debug.layer == "popular"` row, and every such row is in `fetch_popular_videos(dataset, POOL)` under the threshold and the default NSFW filter.
- After the Engine has served, `shared_trending_fingerprint()` (row count, `fetched_at` min and max, rows with `fetched_at > 0`) equals `shared_trending_before`, read before the seed was built.

The fixtures and `shared_trending_fingerprint` come from `tests/active/conftest.py` and `_reference`, `_post`, `_exclude`, `_keys` and `FEED_CONSTANTS` from `tests/active/test_similar.py`, loaded by path so its tests are not collected here.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_DIR = ROOT / "tests" / "active"
if str(ACTIVE_DIR) not in sys.path:
    sys.path.insert(0, str(ACTIVE_DIR))
import conftest  # noqa: E402
# Imported so pytest serves the session fixtures outside tests/active.
from conftest import WHITELIST_DB, dataset, engine, trending_seed  # noqa: E402, F401

# Bound only once the conftest defines it; until then the test stops on its lookup, before the old trending_seed can rewrite the shared table's real fill.
if hasattr(conftest, "shared_trending_before"):
    from conftest import shared_trending_before  # noqa: E402, F401

_HARNESS_SPEC = importlib.util.spec_from_file_location("similar_harness", ACTIVE_DIR / "test_similar.py")
harness = importlib.util.module_from_spec(_HARNESS_SPEC)
# The harness puts engine/server on sys.path, which the data import below needs.
_HARNESS_SPEC.loader.exec_module(harness)

from data.random_videos import fetch_popular_videos  # noqa: E402

# The key `_feed_constants` carries the Engine's DEFAULT_POPULAR_POOL_SIZE under.
POOL_KEY = "popular_pool_size"
# Their own rate-limit buckets, clear of every 192.0.2.x address tests/active uses.
TRENDING_HEADERS = {"X-Client-IP": "192.0.2.180"}
POPULAR_HEADERS = {"X-Client-IP": "192.0.2.181"}


def _shared(threshold: int, pool_size: int) -> tuple[list[tuple[str, str]], set[tuple[str, str]]]:
    """The shared table's Trending reference and popular pool, read on a fresh plain read-only connection that carries no private ranks."""
    plain = sqlite3.connect(f"file:{WHITELIST_DB}?mode=ro", uri=True)
    plain.row_factory = sqlite3.Row
    try:
        return harness._reference(plain, "trending", threshold), set(harness._keys(fetch_popular_videos(plain, pool_size, error_threshold=threshold, include_nsfw=False)))
    finally:
        plain.close()


def test_the_session_engine_serves_trending_from_its_private_ranks_and_leaves_the_shared_ranks_unchanged(request):
    # Requested first and by name, so the fingerprint is read before the seed is built and the Engine starts, and a conftest without it never reaches the Engine.
    before = request.getfixturevalue("shared_trending_before")
    engine = request.getfixturevalue("engine")  # noqa: F811
    dataset = request.getfixturevalue("dataset")  # noqa: F811
    # Observed read-only: (86826, 1791035941189, 1791035941189, 86826). A seed written into the table sets fetched_at = 0 throughout, so the last field drops to 0.
    assert before[3] > 0, f"control: the shared trending_ranks holds no rows with fetched_at > 0, so a seed written into it may leave the fingerprint unmoved: {before}"
    constants = harness.FEED_CONSTANTS
    assert constants is not None, harness.FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    pool_size = constants.get(POOL_KEY)
    assert isinstance(pool_size, int) and pool_size > 0, f"control: _feed_constants carries no {POOL_KEY!r} read from the Engine's DEFAULT_POPULAR_POOL_SIZE: {constants}"
    threshold = constants["threshold"]
    page = harness.FEED_PAGE
    reference = harness._reference(dataset, "trending", threshold)
    assert len(reference) >= 3 * page, len(reference)  # control: the private order holds three pages
    shared_reference, shared_pool = _shared(threshold, pool_size)
    # Observed with the real fill: 7 of the 36 head keys in common, and 3003 of the shared pool's 5000 outside the private pool.
    assert shared_reference[: 3 * page] != reference[: 3 * page], f"control: the shared trending_ranks gives the same first three pages as the private seed, so it has no real fill (or the seed was written into it) and this test cannot tell the two apart; shared fingerprint {before} -> {conftest.shared_trending_fingerprint()}"
    private_pool = set(harness._keys(fetch_popular_videos(dataset, pool_size, error_threshold=threshold, include_nsfw=False)))
    # Popular rows drawn from the shared pool then land outside the private one about once in four or more each, so an Engine reading the shared table fails below on its ~20 rows (observed 9 to 13 of 20 on an Engine started without --trending-db).
    assert 4 * len(shared_pool - private_pool) >= len(shared_pool), f"control: only {len(shared_pool - private_pool)} of the shared popular pool's {len(shared_pool)} rows are outside the private pool"

    path = f"/recommendations?mode=trending&limit={page}"
    first = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {})["rows"])
    second = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first)})["rows"])
    third = harness._keys(harness._post(engine, path, TRENDING_HEADERS, {"exclude": harness._exclude(first + second)})["rows"])
    # An Engine reading the shared table serves its head here, which the control above shows differs (observed: 1 of the first page's 12 keys in common on an Engine started without --trending-db).
    assert first + second + third == reference[: 3 * page], (first + second + third, reference[: 3 * page])  # C1

    # Twice the default page: 20 popular rows a request, all in the private pool and 4 to 10 in the shared one (observed over two probe runs on an Engine started with --trending-db on the seed).
    served = harness._post(engine, f"/recommendations?limit={2 * harness._default_limit()}&debug=1", POPULAR_HEADERS, {})
    popular = harness._keys([row for row in served["rows"] if row["debug"]["layer"] == "popular"])
    assert popular, f"control: no popular-layer row served, layers {sorted({str(row['debug']['layer']) for row in served['rows']})}"  # an Engine whose ranks table is empty serves none
    outside = [key for key in popular if key not in private_pool]
    assert not outside, f"{len(outside)} of {len(popular)} popular rows are outside the private pool, {sum(key in shared_pool for key in outside)} of them in the shared one: {outside[:5]}"  # C1

    after = conftest.shared_trending_fingerprint()
    assert after == before, f"the shared whitelist.db trending_ranks fingerprint moved {before} -> {after}: the suite wrote it, or the operator's updater ran its trending stage during this run"  # C2
