"""Retired from `tests/active/test_similar.py` in build 46-45-trending-from-source-instances (plan 46), step 8.

Retired whole: `test_every_feed_mode_and_a_missing_or_empty_mode_is_served_not_refused`.
Retired cases: `test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[mode=hot-*]` (the five nsfw values); the function stays active for its other nine listings.

Both conflict with that build's confirmed requirement A3: `trending` replaces `hot` in `FEED_MODES` and the Engine answers `mode=hot` with the unknown-mode 400, `trending` in `allowed`.

- The feed-mode test sends every value of `REQUIRED_MODES`, which names `hot`, and requires each to be served 200.
- The `mode=hot` listing cases require `mode=hot&nsfw=1` to be served 200 with a flagged row.

`REQUIRED_MODES` stays active: `SEEDED_MODES` reads it, and a seeded request ignores `mode`, `hot` included. Their Trending replacements are the build's gated phase-2 checkpoint, promoted at the same step to `tests/active/test_trending_feed.py`: `test_mode_hot_is_refused_400_with_trending_among_the_allowed_modes` and `test_trending_without_exactly_nsfw_1_serves_no_flagged_row_where_nsfw_1_serves_some`. The rest of what the feed-mode test carried stays active elsewhere: every `FEED_MODES` value is served by `test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did` or `test_an_ordered_mode_s_page_after_an_excluded_page_continues_its_order_with_no_row_repeated`, an empty `mode` by the former's `recommendations` case, and no `mode` by every home-page test.

The original code of the retired function and of the NSFW listing test follows unchanged, as excerpts: lines 694-777 and 853-921 of the file as it stood. The helpers they call (`_default_limit`, `_keys`, `embedding_of`, the `engine`, `dataset` fixtures) stay in the active file and in `tests/active/conftest.py`.

Retired later in the same step 8 (third suite comparison), by operator decision: `test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some[mode=recent-*]` (the five nsfw values). The function stays active for its other eight listings. This is not a requirement conflict. The build left the Recent order byte-identical. The case's `nsfw=1` control needs a flagged row among the 96 newest rows of the live dev `whitelist.db`, and after a crawl the first one sat at about position 614 (observed in step 8, attempt 2). The control then failed before any filter assertion ran, in three consecutive comparisons. The case cannot be pinned through `exclude` either, because the Engine caps `exclude` at 500 entries. What it carried stays active elsewhere. The Recent NSFW filter itself is `tests/active/test_random_videos.py::test_the_filter_drops_every_nsfw_row_and_keeps_the_null_and_0_rows[fetch_ordered_page:recent-*]` on a fixture DB. The request-edge flag through `_handle_ordered_feed`, the path every ordered mode shares, is `tests/active/test_trending_feed.py::test_trending_without_exactly_nsfw_1_serves_no_flagged_row_where_nsfw_1_serves_some` on seeded ranks. The `NSFW_LISTINGS` line as it stood before that retirement follows the excerpts.
"""
# --- excerpt: lines 694-777 ---

# The values the requirements name for `mode`, sent as inputs so a tuple that dropped one is refused on the wire, not compared against a copy of the spec.
REQUIRED_MODES = ["recommendations", "hot", "recent", "random", "popular"]
# Near misses: an unknown word, a known mode in the wrong case, and the Engine's internal profile name.
UNKNOWN_MODES = ["bogus", "HOT", "home"]
SEEDED_MODES = [*REQUIRED_MODES, "bogus", "HOT", ""]
FEED_PAGE = 12
# Rows of the order read for the reference: three pages and the far excluded page, plus room for moderated rows to be skipped.
REFERENCE_DEPTH = 200
# How each non-ordered mode was spelled before feed modes existed; a mode outside the ordered set with no entry here reaches no known feed.
PRE_BUILD = {"recommendations": "", "random": "&random=1"}
# Their own rate-limit buckets: the session Engine allows 60 requests a minute per client IP and path, and other tests share 127.0.0.1's.
MODE_HEADERS = {"X-Client-IP": "192.0.2.172"}
UNORDERED_HEADERS = {"X-Client-IP": "192.0.2.173"}
ORDERED_HEADERS = {"X-Client-IP": "192.0.2.174"}

# Runs under the Engine interpreter: importing handlers.similar needs numpy and faiss, which only its pixi env carries.
# A missing FEED_MODES or ORDERED_FEED_MODES prints null rather than failing the import, so its absence reaches the tests instead of the collection.
_FEED_CONSTANTS_CHILD = textwrap.dedent(
    """
    import json, sys
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    import handlers.similar as similar
    import server_config
    feed = getattr(similar, "FEED_MODES", None)
    ordered = getattr(similar, "ORDERED_FEED_MODES", None)
    print(json.dumps({"feed": list(feed) if feed is not None else None, "ordered": sorted(ordered) if ordered is not None else None, "threshold": server_config.VIDEO_ERROR_THRESHOLD}))
    """
)


def _feed_constants() -> tuple[dict | None, str]:
    """The Engine's feed-mode constants and error threshold, or None with the reason they could not be read."""
    if not ENGINE_PY.exists():
        return None, f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", _FEED_CONSTANTS_CHILD, str(SERVER_DIR), str(SERVER_DIR / "api")], cwd=SERVER_DIR / "api", capture_output=True, text=True, timeout=120)
    if run.returncode != 0:
        return None, run.stderr[-2000:]
    return json.loads(run.stdout.strip().splitlines()[-1]), ""


# Read once at collection, so the parametrizations follow the module as it is.
FEED_CONSTANTS, FEED_CONSTANTS_ERROR = _feed_constants()
FEED_MODES = (FEED_CONSTANTS or {}).get("feed")
ORDERED = (FEED_CONSTANTS or {}).get("ordered")
UNORDERED = [mode for mode in (FEED_MODES or []) if mode not in (ORDERED or [])]


def _post(engine, path: str, headers: dict[str, str], body: dict) -> dict:
    status, payload = engine.request("POST", path, headers=headers, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path, status, payload)
    return payload


def _exclude(keys: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": video_id, "host": host} for video_id, host in keys]


def _reference(dataset, order: str, threshold: int) -> list[tuple[str, str]]:
    """The order's first rows as `fetch_ordered_page` reads them from whitelist.db for a request without nsfw, less those the Engine's moderation removes."""
    denied = {row["host"].lower() for row in dataset.execute("SELECT host FROM instance_denylist WHERE is_active = 1")}
    blocked = {(row["channel_id"], row["instance_domain"].lower()) for row in dataset.execute("SELECT channel_id, instance_domain FROM channel_moderation WHERE status = 'blocked'")}
    # The pages compared with this carry no nsfw, so the Engine filters them.
    rows = fetch_ordered_page(dataset, order, REFERENCE_DEPTH, 0, error_threshold=threshold, include_nsfw=False)
    kept = [r for r in rows if r["instance_domain"].lower() not in denied and (r["channel_id"], r["instance_domain"].lower()) not in blocked]
    return _keys(kept)


@pytest.mark.parametrize("mode", UNKNOWN_MODES)
def test_an_unseeded_request_with_a_mode_outside_feed_modes_is_answered_400_naming_them(engine, mode):
    status, body = engine.request("POST", f"/recommendations?mode={mode}&limit={UPNEXT_PAGE}", headers=MODE_HEADERS, body={})
    # A handler that ignores mode answers 200 with a home page (observed for all three before validation).
    assert (status, body.get("error")) == (400, "Unknown mode"), (status, body.get("seed"))
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert FEED_MODES is not None and mode not in FEED_MODES, FEED_MODES  # control: FEED_MODES exists and the value sent is outside it
    assert body == {"error": "Unknown mode", "allowed": list(FEED_MODES)}


def test_every_feed_mode_and_a_missing_or_empty_mode_is_served_not_refused(engine):
    assert FEED_CONSTANTS is not None, FEED_CONSTANTS_ERROR  # control: the Engine's interpreter imported handlers.similar
    assert FEED_MODES is not None and len(FEED_MODES) == len(set(FEED_MODES)), FEED_MODES  # FEED_MODES exists with no value repeated
    # A validator refusing every mode passes the 400 test, and a tuple missing a required mode refuses it; both fail here.
    for suffix in [f"&mode={mode}" for mode in dict.fromkeys([*REQUIRED_MODES, *FEED_MODES])] + ["", "&mode="]:
        status, body = engine.request("POST", f"/recommendations?limit={UPNEXT_PAGE}{suffix}", headers=MODE_HEADERS, body={})
        assert status == 200 and "error" not in body and "rows" in body, (suffix, status, body.get("error"))

# --- excerpt: lines 853-921 ---

# The NSFW filter at the request edge, against the session Engine: a listing request is served no row whitelist.db flags nsfw = 1 unless it carries exactly nsfw=1.
# One fresh address per request from the benchmark range, clear of the 192.0.2.x buckets the rest of tests/active uses.
NSFW_CLIENT_IPS = (f"198.18.{n // 250}.{n % 250 + 1}" for n in itertools.count())
# Up-next caps a page at one row per channel; this flagged seed's neighbourhood spans ten flagged channels, so its seed=11 page at limit 96 carries 10 flagged rows, and its raw-vector page 37 of 96 (observed).
NSFW_SEED_ID, NSFW_SEED_HOST = "59b6239b-15c6-4bc4-b5e6-6ebac4ea9751", "810video.com"
NSFW_DRAW_SEED = 11
# 84 of the top 100 matches are flagged (observed), and 244 match in all.
NSFW_SEARCH_QUERY = "hentai"
NSFW_SEARCH_LIMIT = 100
# Flagged videos from the NSFW_SEARCH_QUERY results: liked, they pull the like layer into a flagged neighbourhood, and a mixed page carried 4 or 5 flagged rows in each of 6 draws (observed).
NSFW_LIKES = [{"uuid": uuid, "host": "video02.videohost.top"} for uuid in ("f4e114a2-e70e-4a3c-af92-3efe3071abbc", "0e9ab678-8f3c-4305-97c9-ba9586536999", "4577ad2f-8462-4c78-8212-c4470a4f6db5", "0b385f12-aaeb-435b-9282-7e466cbaf282", "b9ff92e2-6b40-4396-9ed9-1c7f30031dcb")]
NSFW_LISTINGS = ["mode=recommendations", "mode=hot", "mode=recent", "mode=random", "upnext POST /recommendations", "upnext POST /videos/similar", "upnext GET /videos/{id}/similar", "random=1", "vector", "search"]
# The random cache is 0.6% flagged (2966 of 490348 rows), so a 96-row window holds none with p=0.554 (observed): 24 draws hold none about once in 1.4 million cases, and the ten random-feed cases about once in 140,000 runs; 12 draws failed about one run in 120.
NSFW_DRAWS = {"mode=random": 24, "random=1": 24, "mode=recommendations": 3}
# Every value but exactly "1"; parse_qs drops the empty one, so it arrives as missing.
NSFW_VALUES = {"missing": "", "empty": "&nsfw=", "0": "&nsfw=0", "true": "&nsfw=true", "space-1": f"&nsfw={quote(' 1')}"}
# The largest page the Engine serves: twice its default.
NSFW_LIMIT = 2 * _default_limit()


@pytest.fixture(scope="module")
def nsfw_flagged(dataset) -> set[tuple[str, str]]:
    keys = {(r["video_id"], r["instance_domain"]) for r in dataset.execute("SELECT video_id, instance_domain FROM videos WHERE nsfw = 1")}
    assert keys, "control: whitelist.db flags no video nsfw = 1"
    return keys


def _nsfw_listing(dataset, listing: str) -> tuple[str, str, dict | None]:
    """The method, path and body of one listing request, without nsfw."""
    upnext = f"id={NSFW_SEED_ID}&host={NSFW_SEED_HOST}&limit={NSFW_LIMIT}&seed={NSFW_DRAW_SEED}"
    if listing == "mode=recommendations":
        return "POST", f"/recommendations?mode=recommendations&limit={NSFW_LIMIT}", {"likes": NSFW_LIKES}
    if listing.startswith("mode="):
        return "POST", f"/recommendations?{listing}&limit={NSFW_LIMIT}", {}
    if listing == "upnext POST /recommendations":
        return "POST", f"/recommendations?{upnext}", {}
    if listing == "upnext POST /videos/similar":
        return "POST", f"/videos/similar?{upnext}", {}
    if listing == "upnext GET /videos/{id}/similar":
        return "GET", f"/videos/{NSFW_SEED_ID}/similar?host={NSFW_SEED_HOST}&limit={NSFW_LIMIT}&seed={NSFW_DRAW_SEED}", None
    if listing == "random=1":
        return "POST", f"/recommendations?random=1&limit={NSFW_LIMIT}", {}
    if listing == "vector":
        return "POST", f"/recommendations?vector={quote(json.dumps(embedding_of(dataset, NSFW_SEED_ID, NSFW_SEED_HOST)))}&limit={NSFW_LIMIT}", {}
    return "GET", f"/api/v1/search/videos?q={NSFW_SEARCH_QUERY}&limit={NSFW_SEARCH_LIMIT}", None


def _nsfw_keys(engine, method: str, path: str, body: dict | None) -> list[tuple[str, str]]:
    status, payload = engine.request(method, path, headers={"X-Client-IP": next(NSFW_CLIENT_IPS)}, body=body)
    assert status == 200 and isinstance(payload, dict) and "rows" in payload, (path[:160], status, payload)
    return [(r["video_id"], r["instance_domain"]) for r in payload["rows"]]


@pytest.mark.parametrize("nsfw", NSFW_VALUES)
@pytest.mark.parametrize("listing", NSFW_LISTINGS)
def test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some(engine, dataset, nsfw_flagged, listing, nsfw):
    method, path, body = _nsfw_listing(dataset, listing)
    draws = NSFW_DRAWS.get(listing, 1)
    # Sent first on the same Engine: a mixer whose flag froze at build time serves no flagged row here.
    shown: set[tuple[str, str]] = set()
    for _ in range(draws):
        shown = set(_nsfw_keys(engine, method, f"{path}&nsfw=1", body)) & nsfw_flagged
        if shown:
            break
    assert shown, f"control: {listing} with nsfw=1 served no flagged row in {draws} draws"
    for _ in range(draws):
        keys = _nsfw_keys(engine, method, f"{path}{NSFW_VALUES[nsfw]}", body)
        assert keys, f"{listing} served an empty page"  # a handler answering every filtered request with no rows is no filter
        assert not set(keys) & nsfw_flagged, sorted(set(keys) & nsfw_flagged)[:5]  # no flagged row without exactly nsfw=1

# --- excerpt: NSFW_LISTINGS before the mode=recent retirement (line 855) ---

NSFW_LISTINGS = ["mode=recommendations", "mode=recent", "mode=random", "upnext POST /recommendations", "upnext POST /videos/similar", "upnext GET /videos/{id}/similar", "random=1", "vector", "search"]
