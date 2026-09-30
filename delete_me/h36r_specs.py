"""The harvest-36 mutations, one per moved test, written out as JSON specs for h36r_mutate.py."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = "engine/server/data/metadata.py"
RV = "engine/server/data/random_videos.py"
SEARCH = "engine/server/data/search.py"
SC = "engine/server/data/similarity_candidates.py"
SPECS = [
    dict(tag="m01", file=META, test_file="tests/active/test_metadata.py", test="test_the_filter_drops_every_nsfw_row_and_keeps_the_null_and_0_rows",
         edits=[['NSFW_ALLOWED_SQL = "(v.nsfw IS NULL OR v.nsfw = 0)"', 'NSFW_ALLOWED_SQL = "(v.nsfw IS NULL OR v.nsfw = 0 OR v.nsfw = 1)"']]),
    dict(tag="m02", file=META, test_file="tests/active/test_metadata.py", test="test_the_uuid_lookup_still_returns_nsfw_videos",
         edits=[['_select_pairs(conn, "video_uuid", entries, error_threshold)', '_select_pairs(conn, "video_uuid", entries, error_threshold, False)']]),
    dict(tag="m03", file=RV, test_file="tests/active/test_random_videos.py", test="test_the_filter_drops_every_nsfw_row_and_keeps_the_null_and_0_rows",
         edits=[["    if not include_nsfw:\n        conditions.append(NSFW_ALLOWED_SQL)", "    if False:\n        conditions.append(NSFW_ALLOWED_SQL)"]]),
    dict(tag="m04", file=RV, test_file="tests/active/test_random_videos.py", test="test_limits_count_only_allowed_rows",
         scope_start="def fetch_popular_videos", scope_end="def fetch_ordered_page",
         edits=[["          {where_clause}\n          ORDER BY {POPULAR_ORDER_BY}", "          {('WHERE ' + ' AND '.join(c for c in conditions if c != NSFW_ALLOWED_SQL)) if [c for c in conditions if c != NSFW_ALLOWED_SQL] else ''}\n          ORDER BY {POPULAR_ORDER_BY}"],
                ["          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n        LIMIT ?", "          ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n        {'' if include_nsfw else 'WHERE ' + NSFW_ALLOWED_SQL}\n        LIMIT ?"]]),
    dict(tag="m05", file=RV, test_file="tests/active/test_random_videos.py", test="test_filtered_pages_concatenate_into_the_one_filtered_page",
         scope_start="def fetch_ordered_page", scope_end="def fetch_random_rows_from_cache",
         edits=[["conditions, params = _listing_conditions(error_threshold, include_nsfw)", "conditions, params = _listing_conditions(error_threshold, True)"],
                ["    return rows\n", "    return [row for row in rows if include_nsfw or row[\"nsfw\"] != 1]\n"]]),
    dict(tag="m06", file=RV, test_file="tests/active/test_random_videos.py", test="test_filter_on_redraws_past_nsfw_and_seen_rowids_until_the_page_is_full",
         edits=[["    draws = 1 if include_nsfw else RANDOM_CACHE_NSFW_MAX_DRAWS", "    draws = 1"]]),
    dict(tag="m07", file=RV, test_file="tests/active/test_random_videos.py", test="test_filter_on_stops_at_the_draw_cap_with_the_page_still_short",
         edits=[["    for _ in range(draws):", "    for _ in range(draws + 1):"]]),
    dict(tag="m08", file=RV, test_file="tests/active/test_random_videos.py", test="test_filter_on_stops_after_a_draw_adds_no_unseen_rowid",
         edits=[["        if not fresh:\n            break", "        if not fresh:\n            continue"]]),
    dict(tag="m09", file=RV, test_file="tests/active/test_random_videos.py", test="test_filter_on_returns_nothing_from_an_all_nsfw_cache",
         edits=[["fetch_metadata(server.db, fresh, error_threshold=error_threshold, include_nsfw=include_nsfw)", "fetch_metadata(server.db, fresh, error_threshold=error_threshold, include_nsfw=True)"]]),
    dict(tag="m10", file=RV, test_file="tests/active/test_random_videos.py", test="test_filter_off_makes_one_draw_and_returns_its_rows_duplicates_included",
         edits=[["    draws = 1 if include_nsfw else RANDOM_CACHE_NSFW_MAX_DRAWS", "    draws = 2 if include_nsfw else RANDOM_CACHE_NSFW_MAX_DRAWS"]]),
    dict(tag="m11", file=SEARCH, test_file="tests/active/test_search.py", test="test_lexical_candidates_drop_every_nsfw_match_and_keep_the_null_and_0_ones",
         edits=[['    nsfw_clause = "" if include_nsfw else f"AND {NSFW_ALLOWED_SQL}"', '    nsfw_clause = ""']]),
    dict(tag="m12", file=SEARCH, test_file="tests/active/test_search.py", test="test_lexical_limit_and_search_total_count_only_allowed_rows",
         edits=[['    nsfw_clause = "" if include_nsfw else f"AND {NSFW_ALLOWED_SQL}"', '    nsfw_clause = ""'],
                ["    return [dict(row) for row in query]\n", "    return [dict(row) for row in query if include_nsfw or row[\"nsfw\"] != 1]\n"]]),
    dict(tag="m13", file=SC, test_file="tests/active/test_similarity_candidates.py", test="test_upnext_ladder_widens_past_an_all_nsfw_step_to_the_caps_when_filtered",
         edits=[["            if len(rows) <= before and (policy.include_nsfw or len(hits) <= hits_before):", "            if len(rows) <= before:"]]),
    dict(tag="m14", file=SC, test_file="tests/active/test_similarity_candidates.py", test="test_upnext_ladder_stops_when_a_step_adds_no_hit",
         edits=[["            if len(rows) <= before and (policy.include_nsfw or len(hits) <= hits_before):", "            if len(rows) <= before and policy.include_nsfw:"]]),
    dict(tag="m15", file=SC, test_file="tests/active/test_similarity_candidates.py", test="test_upnext_nsfw_hits_take_no_author_slot_and_no_pool_place",
         scope_start="def _build_rows", scope_end="filter_ms = int(",
         edits=[["                include_nsfw=include_nsfw,\n", "                include_nsfw=True,\n"],
                ['        rows.append({**meta, "score": entry.get("score")})', '        if include_nsfw or meta.get("nsfw") != 1:\n            rows.append({**meta, "score": entry.get("score")})']]),
    dict(tag="m16", file="engine/server/api/handlers/similar.py", test_file="tests/active/test_similar.py", test="test_a_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some", timeout=3000, tail=60,
         edits=[['    return value == "1"\n', '    return value is not None and value.strip() == "1"\n']]),
    dict(tag="m17", file="client/backend/server.py", test_file="tests/active/test_server.py", test="test_a_gateway_listing_request_without_exactly_nsfw_1_gets_no_flagged_row_where_nsfw_1_gets_some", timeout=3000, tail=60,
         edits=[['PROXY_UNSTRIPPED_QUERY_PARAMS = frozenset(("nsfw",))', "PROXY_UNSTRIPPED_QUERY_PARAMS = frozenset()"]]),
    dict(tag="m18", file="client/backend/server.py", test_file="tests/active/test_server.py", test="test_the_gateway_still_refuses_nsfw_on_api_video", timeout=1500,
         edits=[['    "/api/video": {"id", "host", "refresh_cache", "user_id"},', '    "/api/video": {"id", "host", "refresh_cache", "user_id", "nsfw"},']]),
    dict(tag="m19", file="client/frontend/src/data/feed-params.ts", test_file="tests/active/test_frontend_feed_params.py", test="test_only_a_stored_off_puts_nsfw_1_on_up_next_feed_and_search_requests",
         edits=[['    return window.localStorage.getItem(NSFW_FILTER_KEY) !== "off";', '    return (window.localStorage.getItem(NSFW_FILTER_KEY) ?? "").trim().toLowerCase() !== "off";']]),
    dict(tag="m20", file="client/frontend/src/data/feed-params.ts", test_file="tests/active/test_frontend_feed_params.py", test="test_set_nsfw_filter_holds_on_the_page_when_set_item_throws",
         edits=[["  nsfwFilterInMemory = on;\n  try {\n    window.localStorage.setItem(NSFW_FILTER_KEY", "  try {\n    window.localStorage.setItem(NSFW_FILTER_KEY"],
                ["    // Ignore storage failures (quota/private mode): the in-memory value above still applies on this page.\n", "    // Ignore storage failures (quota/private mode): the in-memory value above still applies on this page.\n    return;\n  }\n  {\n    nsfwFilterInMemory = on;\n"]]),
    dict(tag="m21", file="client/frontend/src/data/feed-params.ts", test_file="tests/active/test_frontend_feed_params.py", test="test_set_nsfw_filter_is_read_back_by_the_next_page_view",
         edits=[['    window.localStorage.setItem(NSFW_FILTER_KEY, on ? "on" : "off");', '    void NSFW_FILTER_KEY;']]),
    dict(tag="m22", file="client/frontend/src/pages/videos/index.ts", test_file="tests/active/test_frontend_videos_page.py", test="test_the_checked_profile_checkbox_reloads_the_home_feed_under_each_new_setting_and_shows_that_page",
         edits=[["    const payload = await current.next();\n    // A newer load (an NSFW toggle, a likes reset) replaced this pager; its own result renders instead.\n    if (current !== pager) return;\n", "    const payload = await current.next();\n"]]),
]
for spec in SPECS:
    (HERE / f"h36r_{spec['tag']}.json").write_text(json.dumps(spec))
print(len(SPECS))
