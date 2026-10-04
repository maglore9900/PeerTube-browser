"""Retired from `tests/active/test_subtitles.py` in the harvest of build 54 (translate job handle).

`test_recovery_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time` was replaced (REPLACES) by build 54's phase 2 checkpoint test, now `test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time`. It carries the same (1, 0) and (2, 1) counts, rows and bystander comparison. It adds that `open_subtitles_db` recovers nothing, armed by the recovery that follows on the same row, and a control that the bystander filter matches two rows. Kept readable; the names it uses come from the active module and are not imported here, and the whole module is skipped.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="retired test, kept for reference")


def test_recovery_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    from data.subtitles import claim_translate_job, open_translate_worker_store

    path = tmp_path / "subtitles.db"
    lock_fd = os.open(tmp_path / "worker.lock", os.O_RDONLY | os.O_CREAT)  # noqa: F821
    fcntl.flock(lock_fd, fcntl.LOCK_EX)  # noqa: F821
    conn = _subtitles(path)  # noqa: F821

    def recover(finished_at: int) -> tuple[int, int]:
        opened, counts = open_translate_worker_store(path, lock_fd, finished_at)
        opened.close()
        return tuple(counts)

    _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})  # noqa: F821
    _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})  # noqa: F821
    _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})  # noqa: F821
    # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
    _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})  # noqa: F821
    _insert(conn, "b1", HOST, B1_READY_INSTANCE)  # noqa: F821
    _, before = _snapshot(path)  # noqa: F821
    bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]

    def job(video_id: str) -> tuple:
        return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

    first = claim_translate_job(conn, "en", 5000)
    assert (first.video_id, first.attempts) == ("t", 1)  # control: t is running after one claim

    assert recover(9000) == (1, 0)
    assert job("t") == ("queued", 1, None, None)  # requeued, its one claim still counted

    second = [claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
    assert [(row.video_id, row.attempts) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

    assert recover(9500) == (2, 1)
    assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)  # noqa: F821
    assert job("o1") == ("queued", 1, None, None)
    assert job("o2") == ("queued", 1, None, None)
    conn.close()
    os.close(lock_fd)  # noqa: F821
    _, after = _snapshot(path)  # noqa: F821
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # recovery touches only running rows
