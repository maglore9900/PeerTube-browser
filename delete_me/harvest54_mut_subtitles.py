PROD = "engine/server/data/subtitles.py"
TEST = "tests/active/test_subtitles.py"

MUTATIONS = [
    ("S1-claim-condition-dropped", "WHERE {_KEY} AND state = 'running' AND started_at = ?\", (*values,", "WHERE {_KEY} AND started_at = ?\", (*values,", "every_claim_write"),
    ("S2-instance-end-keeps-source", "\"state = 'ready', source = ?, track_text = ?, cues_json = ?, fetched_at = ?, finished_at = ?\", (SOURCE_INSTANCE, track_text,", "\"state = 'ready', track_text = ?, cues_json = ?, fetched_at = ?, finished_at = ?\", (track_text,", "ending_ready_from_the_instance"),
    ("S3-opener-no-mkdir", "    path.parent.mkdir(parents=True, exist_ok=True)\n    conn = connect_subtitles_db(path)", "    conn = connect_subtitles_db(path)", "missing_nested"),
    ("S4-opener-no-migrate", "    try:\n        ensure_subtitles_schema(conn)\n    except BaseException:", "    try:\n        pass\n    except BaseException:", "b1_file"),
    ("S5-flock-after-open", "    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    conn = open_subtitles_db(path)", "    conn = open_subtitles_db(path)\n    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)", "refuses_while"),
    ("S6-plain-opener-recovers", "        ensure_subtitles_schema(conn)\n    except BaseException:", "        ensure_subtitles_schema(conn)\n        _recover_translate_jobs(conn, 0)\n    except BaseException:", "recovery_through"),
]
