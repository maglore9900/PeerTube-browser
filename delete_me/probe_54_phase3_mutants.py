PROD = "engine/server/api/handlers/internal_translate.py"
TEST = "tests/tmp/test_54_translate_job_handle_phase3.py"

MUTATIONS = [
    ("warning-level", 'logging.info("[translate] cache closed, track not stored', 'logging.warning("[translate] cache closed, track not stored', "closed"),
    ("logged-on-read-too", "            if conn is None:\n                return None, False", '            if conn is None:\n                logging.info("[translate] cache closed, track not stored video_id=%s host=%s", video_id, instance_domain)\n                return None, False', "closed"),
    ("request-host-not-row-host", '        _store_cues(server, canonical_id, instance, track_text, cues)', '        _store_cues(server, canonical_id, body["host"], track_text, cues)', "closed"),
]
