PROD = "engine/server/api/handlers/internal_translate.py"
TEST = "tests/tmp/test_54_translate_job_handle_phase4.py"

MUTATIONS = [
    ("host-check-after-lookup", "    if not host:\n        return None, \"missing host\"\n    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n",
     "    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n    if not host:\n        return None, \"missing host\"\n", "resolve or refused or answers"),
    ("deny-on-request-host-first", "    if not host:\n        return None, \"missing host\"\n",
     "    if not host:\n        return None, \"missing host\"\n    if normalize_host(host) in list_active_denied_hosts(conn):\n        return None, \"host denied\"\n", "resolve or refused or answers"),
    ("threshold-dropped", "fetch_video_row(conn, video_id, host, error_threshold=error_threshold)", "fetch_video_row(conn, video_id, host)", "resolve or refused or answers"),
    ("raw-domain-vs-denylist", "    if normalize_host(row[\"instance_domain\"]) in list_active_denied_hosts(conn):", "    if row[\"instance_domain\"].upper() in list_active_denied_hosts(conn):", "resolve or refused or answers"),
]
