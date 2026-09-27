"""Harvest 14 Step 6: run every mutation through mutate.py, one at a time, in order."""
import subprocess
import sys

MD = "engine/server/data/metadata.py"
HD = "engine/server/api/handlers/internal_client_reads.py"
SV = "client/backend/server.py"
EC = "client/backend/lib/engine_api_client.py"
TM = "tests/active/test_metadata.py"
TH = "tests/active/test_internal_client_reads.py"
TS = "tests/active/test_server.py"

UUID_DOC = '"""Fetch video metadata for exact (video_uuid, instance_domain) pairs, keeping the lowest video_id per pair."""\n    if not entries:\n        return {}'
UUID_LOOP = 'for batch in _chunk(entries, 450):\n        conditions = " OR ".join(\n            ["(v.video_uuid = ? AND'
PAGE = 'likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {"error": f"Engine metadata failed'
IMPORT = 'likes = _parse_client_likes(body, MAX_CLIENT_LIKES)\n        try:\n            rows = fetch_metadata_for_entries(self.server.engine_ingest_base, likes)\n        except EngineApiError as exc:\n            respond_json(self, 502, {"error": f"Engine resolve failed'
METADATA_TAIL = '    respond_json(handler, 200, {"ok": True, "count": len(rows), "rows": rows})\n    return True'

MUTATIONS = [
    # test_metadata.py -> data/metadata.py
    ("H14-N1", MD, TM, "test_a_uuid_pair_gets_the_row_the_id_lookup_gives_its_video",
     "            if kept is None or row[\"video_id\"] < kept[\"video_id\"]:\n                result[key] = row",
     "            if kept is None or row[\"video_id\"] < kept[\"video_id\"]:\n                result[key] = {**row, \"title\": None}"),
    ("H14-N2", MD, TM, "test_a_uuid_pair_matches_only_its_exact_uuid_and_host",
     '["(v.video_uuid = ? AND v.instance_domain = ?)"]', '["(v.video_uuid = ? COLLATE NOCASE AND v.instance_domain = ?)"]'),
    ("H14-N3", MD, TM, "test_an_empty_uuid_list_gives_nothing_and_runs_no_statement",
     UUID_DOC, UUID_DOC.replace("        return {}", "        conn.execute(\"SELECT 1\")\n        return {}")),
    ("H14-N4", MD, TM, "test_a_shared_uuid_pair_keeps_the_lowest_video_id_under_the_threshold",
     'row["video_id"] < kept["video_id"]', 'row["video_id"] > kept["video_id"]'),
    ("H14-N5", MD, TM, "test_an_errored_video_s_uuid_pair_is_dropped_only_while_a_threshold_is_set",
     '_select_metadata(conn, f"({conditions})", params, error_threshold)', '_select_metadata(conn, f"({conditions})", params, None)'),
    ("H14-N6", MD, TM, "test_the_id_lookup_returns_the_joined_row_and_skips_an_unembedded_video",
     "FROM video_embeddings e\n            JOIN videos v\n              ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain\n            LEFT JOIN channels c\n              ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n            WHERE {conditions}",
     "FROM videos v\n            LEFT JOIN video_embeddings e\n              ON v.video_id = e.video_id AND v.instance_domain = e.instance_domain\n            LEFT JOIN channels c\n              ON c.channel_id = v.channel_id AND c.instance_domain = v.instance_domain\n            WHERE {conditions}"),
    ("H14-N7", MD, TM, "test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary",
     UUID_LOOP, UUID_LOOP.replace("_chunk(entries, 450):", "_chunk(entries, 450)[:1]:")),
    # test_internal_client_reads.py -> handlers/internal_client_reads.py
    ("H14-H1", HD, TH, "test_a_mixed_body_takes_the_lock_once_and_gives_each_video_once_in_first_match_order",
     "        if uuid_entries:\n            by_uuid = fetch_metadata_by_uuids(",
     "    with server.db_lock:\n        if uuid_entries:\n            by_uuid = fetch_metadata_by_uuids("),
    ("H14-H2", HD, TH, "test_an_id_only_body_takes_the_lock_once_and_gives_its_rows_in_entry_order",
     METADATA_TAIL, '    rows.sort(key=lambda r: r["video_id"])\n' + METADATA_TAIL),
    ("H14-H3", HD, TH, "test_a_valid_video_id_wins_over_a_video_uuid_and_a_blank_one_falls_back_to_it",
     '        if video_id is not None:\n            form, entry = "id"', '        if video_id is not None and video_uuid is None:\n            form, entry = "id"'),
    ("H14-H4", HD, TH, "test_repeats_within_and_across_forms_give_one_row_per_video",
     "if not isinstance(row, dict) or _like_key(row) in emitted:", "if not isinstance(row, dict):"),
    ("H14-H5", HD, TH, "test_an_errored_video_s_uuid_entry_is_omitted_only_under_the_threshold",
     "fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=error_threshold)", "fetch_metadata_by_uuids(server.db, uuid_entries, error_threshold=None)"),
    ("H14-H6", HD, TH, "test_a_body_with_no_entries_list_or_no_valid_entry_is_answered_without_the_lock",
     '    if not entries:\n        respond_json(handler, 200, {"ok": True, "count": 0, "rows": []})',
     '    if not entries:\n        with server.db_lock:\n            pass\n        respond_json(handler, 200, {"ok": True, "count": 0, "rows": []})'),
    ("H14-H7", HD, TH, "test_centroids_looks_up_only_the_id_entries",
     '        video_id = _stripped(raw.get("video_id"))\n        instance = _stripped(raw.get("instance_domain"))\n        if video_id is None or instance is None:',
     '        video_id = _stripped(raw.get("video_id")) or _stripped(raw.get("video_uuid"))\n        instance = _stripped(raw.get("instance_domain"))\n        if video_id is None or instance is None:'),
    # test_server.py -> client/backend
    ("H14-C1", SV, TS, "test_a_likes_page_is_one_metadata_call_answered_with_the_known_rows_in_submitted_order",
     'respond_json(self, 200, {"likes": rows, "updatedAt": now_ms()})\n\n\ndef _publish_to_engine_bridge',
     'respond_json(self, 200, {"likes": sorted(rows, key=lambda r: r["video_id"]), "updatedAt": now_ms()})\n\n\ndef _publish_to_engine_bridge'),
    ("H14-C2", EC, TS, "test_a_likes_page_with_no_well_formed_like_is_answered_empty_without_the_engine",
     "    if not entries:\n        return []\n    status, body = _post_json(\n        f\"{engine_base_url.rstrip('/')}/internal/videos/metadata\"",
     "    status, body = _post_json(\n        f\"{engine_base_url.rstrip('/')}/internal/videos/metadata\""),
    ("H14-C3", SV, TS, "test_an_import_is_one_metadata_call_and_likes_each_returned_video_the_profile_has_not_disliked",
     'if is_disliked(conn, profile_id, row["video_id"], row["instance_domain"]):', "if False:"),
    ("H14-C4", SV, TS, "test_a_60_like_likes_page_reaches_the_engine_as_its_first_50_and_is_answered_with_their_rows",
     PAGE, PAGE.replace("_parse_client_likes(body, MAX_CLIENT_LIKES)", "_parse_client_likes(body, 200)")),
    ("H14-C5", SV, TS, "test_a_60_like_import_reaches_the_engine_as_its_first_50_and_likes_exactly_those",
     IMPORT, IMPORT.replace("_parse_client_likes(body, MAX_CLIENT_LIKES)", "_parse_client_likes(body, 200)")),
    ("H14-C6", SV, TS, "test_a_keyless_60_like_recommendations_request_forwards_its_first_50_likes",
     "for entry in likes[:MAX_CLIENT_LIKES]:", "for entry in likes:"),
]

only = set(sys.argv[1:])
for label, prod, test_file, test_name, old, new in MUTATIONS:
    if only and label not in only:
        continue
    proc = subprocess.run([sys.executable, ".scratch/security-hardening-batch/mutate.py", label, prod, test_file, test_name, old, new], capture_output=True, text=True)
    print(proc.stdout.strip())
    if proc.returncode:
        print(f"[{label}] DRIVER ERROR: {proc.stderr.strip()}")
    print()
