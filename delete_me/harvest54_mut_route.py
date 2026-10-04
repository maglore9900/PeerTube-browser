PROD = "engine/server/api/handlers/internal_translate.py"
TEST = "tests/active/test_internal_translate.py"

MUTATIONS = [
    ("R1-closed-line-dropped", "                logging.info(\"[translate] cache closed, track not stored video_id=%s host=%s\", video_id, instance_domain)\n", "", "logs_once_that_it_was_not_stored"),
    ("R2-host-check-after-lookup", "    if not host:\n        return None, \"missing host\"\n    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n",
     "    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n    if not host:\n        return None, \"missing host\"\n", "missing_host_is_refused"),
    ("R3-threshold-dropped", "fetch_video_row(conn, video_id, host, error_threshold=error_threshold)", "fetch_video_row(conn, video_id, host)", "video_not_in_the_whitelist"),
    ("R4-deny-on-request-host-first", "    if not host:\n        return None, \"missing host\"\n",
     "    if not host:\n        return None, \"missing host\"\n    if normalize_host(host) in list_active_denied_hosts(conn):\n        return None, \"host denied\"\n", "actively_denied_host"),
    ("R5-row-keyed-on-request", "        return None, \"host denied\"\n    return row, None", "        return None, \"host denied\"\n    return {**row, \"video_id\": video_id}, None", "whitelisted_video_answers"),
]
