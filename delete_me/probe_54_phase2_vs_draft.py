import fcntl
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_subtitles  # noqa: E402,F401

import data.subtitles as store  # noqa: E402


def draft_open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect_subtitles_db(path)
    try:
        store.ensure_subtitles_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def draft_worker(path, lock_fd, finished_at):
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    conn = store.open_subtitles_db(path)
    try:
        return conn, store.recover_translate_jobs(conn, finished_at)
    except BaseException:
        conn.close()
        raise


def no_wal_open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    store.ensure_subtitles_schema(conn)
    return conn


def no_mkdir_open(path):
    conn = store.connect_subtitles_db(path)
    store.ensure_subtitles_schema(conn)
    return conn


def mkdir_first_worker(path, lock_fd, finished_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    conn = store.open_subtitles_db(path)
    return conn, store.recover_translate_jobs(conn, finished_at)


def blocking_worker(path, lock_fd, finished_at):
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    conn = store.open_subtitles_db(path)
    return conn, store.recover_translate_jobs(conn, finished_at)


def no_lock_worker(path, lock_fd, finished_at):
    conn = store.open_subtitles_db(path)
    return conn, store.recover_translate_jobs(conn, finished_at)


def unlocking_worker(path, lock_fd, finished_at):
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    conn = store.open_subtitles_db(path)
    return conn, store.recover_translate_jobs(conn, finished_at)


def no_recover_worker(path, lock_fd, finished_at):
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return store.open_subtitles_db(path), (0, 0)


def recovering_open(path):
    conn = draft_open(path)
    store.recover_translate_jobs(conn, 1)
    return conn


VARIANTS = {
    "recovering_open": (recovering_open, draft_worker),
    "draft": (draft_open, draft_worker),
    "no_wal": (no_wal_open, draft_worker),
    "no_mkdir": (no_mkdir_open, draft_worker),
    "mkdir_first": (draft_open, mkdir_first_worker),
    "blocking": (draft_open, blocking_worker),
    "no_lock": (draft_open, no_lock_worker),
    "unlocking": (draft_open, unlocking_worker),
    "no_recover": (draft_open, no_recover_worker),
}
CHECKPOINT = Path(__file__).with_name("test_54_translate_job_handle_phase2.py")


def _load(variant):
    opener, worker = VARIANTS[variant]
    store.open_subtitles_db = opener
    store.open_translate_worker_store = worker
    spec = importlib.util.spec_from_file_location(f"cp_{variant}", CHECKPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TESTS = ["test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal", "test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues", "test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing", "test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant(variant, tmp_path):
    module = _load(variant)
    outcomes = []
    for i, name in enumerate(TESTS):
        sub = tmp_path / str(i)
        sub.mkdir()
        try:
            getattr(module, name)(sub)
            outcomes.append((name[:40], "pass"))
        except BaseException as exc:  # noqa: BLE001
            outcomes.append((name[:40], type(exc).__name__, str(exc).splitlines()[0][:120] if str(exc) else ""))
    print(f"\n{variant}:")
    for outcome in outcomes:
        print("   ", outcome)
