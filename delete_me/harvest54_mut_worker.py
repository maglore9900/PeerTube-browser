PROD = "engine/server/db/jobs/translate-worker.py"
TEST = "tests/active/test_translate_worker.py"

MUTATIONS = [
    ("W1-lost-instance-end-ignored", "        if not job.end_ready_from_instance(fetched[0], fetched[1], now_ms()):\n            raise JobTakenOver()", "        job.end_ready_from_instance(fetched[0], fetched[1], now_ms())", "took_the_row_over"),
]
