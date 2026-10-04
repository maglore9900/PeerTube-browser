PROD = "engine/server/api/router.py"
TEST = "tests/active/test_router.py"

MUTATIONS = [
    ("R1-gate-after-lookup", '    if url.path.startswith("/internal/") and not bridge_authorized(handler):\n        return\n    route = POST_ROUTES.get(url.path)\n',
     '    route = POST_ROUTES.get(url.path)\n    if route is not None and url.path.startswith("/internal/") and not bridge_authorized(handler):\n        return\n',
     "bridge_gate"),
    ("R2-empty-token-accepted", "    if not configured:", "    if configured is None:",
     "bridge_gate"),
    ("R3-prefix-token-compare", "not hmac.compare_digest(presented, configured)", "not configured.startswith(presented)",
     "bridge_gate"),
    ("R4-get-table-frozen", "    route = GET_ROUTES.get(url.path)", '    route = globals().setdefault("_FROZEN_GET", dict(GET_ROUTES)).get(url.path)',
     "get_routes_entry"),
    ("R5-get-prefix-match", "    route = GET_ROUTES.get(url.path)", "    route = next((r for p, r in GET_ROUTES.items() if url.path.startswith(p)), None)",
     "get_routes_entry"),
]
