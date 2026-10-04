PROD = "engine/server/db/jobs/translate-worker.py"
TEST = "tests/active/test_translate_worker.py"

MUTATIONS = [
    ("TW1-json-reason-dropped", 'raise JobFailed(f"video JSON fetch failed: {exc}") from exc', 'raise JobFailed("video JSON fetch failed") from exc',
     "adapters_reason"),
    ("TW2-media-reason-dropped", "            self._fail(str(exc))", '            self._fail("media download failed")',
     "adapters_reason"),
]
