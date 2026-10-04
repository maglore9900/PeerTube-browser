PROD = "engine/server/api/handlers/internal_translate.py"
TEST = "tests/active/test_internal_translate.py"

MUTATIONS = [
    ("IT1-reason-not-logged", 'logging.info("[translate] instance fetch failed host=%s path=%s: %s", host, path, exc)', 'logging.info("[translate] instance fetch failed host=%s path=%s", host, path)',
     "none_path_answers_none_stores_nothing_and_logs"),
    ("IT2-cap-lifted-at-route", "        return fetch_bounded(host, path, budget_at=budget_at)", "        return fetch_bounded(host, path, budget_at=budget_at, max_bytes=10**9)",
     "none_path_answers_none_stores_nothing_and_logs"),
    ("IT3-fresh-budget-per-fetch", "    raw = _fetch(host, path, budget_at) if path", "    raw = _fetch(host, path, time.monotonic() + REQUEST_BUDGET_SECONDS) if path",
     "15_second_budget"),
    ("IT4-503-text", '{"error": "Translate store unavailable"}', '{"error": "Store unavailable"}',
     "store_error_from_the_enqueue"),
]
