import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from test_translate_worker import HOST, INSTANCE_THEN_JSON, MEDIA_URL, QUEUED_AT, STARTED_AT, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, enqueue_translate_job, open_subtitles_db  # noqa: E402


def test_probe_opened_lists(rig, monkeypatch):
    monkeypatch.setattr(rig.worker, "now_ms", lambda: 10 ** 13)
    assert enqueue_translate_job(rig.conn, "v-1", HOST, "en", 50, QUEUED_AT) == ("queued", "queued")
    rig.job = claim_translate_job(rig.conn, "en", STARTED_AT)
    runner = StubRunner(rig)
    result = rig.run(runner)
    print("PROBE result", result, "transcribes", runner.transcribes)
    print("PROBE instance.opened", rig.instance.opened, "== INSTANCE_THEN_JSON", rig.instance.opened == INSTANCE_THEN_JSON)
    print("PROBE media.opened", rig.media.opened, "== [MEDIA_URL]", rig.media.opened == [MEDIA_URL])


def test_probe_running_row_then_claim(tmp_path):
    import sqlite3
    path = tmp_path / "subtitles.db"
    conn = open_subtitles_db(path)
    print("PROBE enqueue running", enqueue_translate_job(conn, "v-running", HOST, "en", 50, 500))
    first = claim_translate_job(conn, "en", 600)
    print("PROBE first claim", first)
    for video_id, queued_at in [("v-expired", 1000), ("v-unleased", 2000), ("v-expired-late", 2500), ("v-fresh", 3000)]:
        print("PROBE enqueue", video_id, enqueue_translate_job(conn, video_id, HOST, "en", 50, queued_at))
    plain = sqlite3.connect(path)
    plain.row_factory = sqlite3.Row
    before = {row["video_id"]: dict(row) for row in plain.execute("SELECT rowid, * FROM subtitles")}
    second = claim_translate_job(conn, "en", 1_000_000)
    after = {row["video_id"]: dict(row) for row in plain.execute("SELECT rowid, * FROM subtitles")}
    print("PROBE second claim", second)
    print("PROBE running before", before["v-running"])
    print("PROBE running after ", after["v-running"], "unchanged", before["v-running"] == after["v-running"])
    plain.close()
    conn.close()
