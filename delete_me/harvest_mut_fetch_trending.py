PROD = "engine/server/db/jobs/fetch-trending.py"
TEST = "tests/active/test_fetch_trending.py"

CALL = 'body = json.loads(fetch_bounded(host, TRENDING_PATH, max_bytes=TRENDING_MAX_BYTES, deadline_seconds=timeout_s, socket_timeout=timeout_s, headers={"User-Agent": "peertube-browser-trending/1.0"}))'

MUTATIONS = [
    ("FT1-default-cap", "max_bytes=TRENDING_MAX_BYTES, deadline_seconds", "deadline_seconds",
     "trending_max_bytes"),
    ("FT2-default-deadline", "deadline_seconds=timeout_s, socket_timeout", "socket_timeout",
     "clock_passes_timeout_s"),
    ("FT3-redirects-followed", CALL,
     'body = json.loads(__import__("data.source_fetch", fromlist=["build_opener"]).build_opener().open(__import__("urllib.request", fromlist=["Request"]).Request(f"https://{host}{TRENDING_PATH}", headers={"User-Agent": "peertube-browser-trending/1.0"}), timeout=timeout_s).read())',
     "off_host_redirect"),
]
