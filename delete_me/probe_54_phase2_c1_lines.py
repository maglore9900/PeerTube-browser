import importlib.util
import sqlite3
import sys
import traceback
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_subtitles  # noqa: E402,F401

import data.subtitles as store  # noqa: E402


def no_wal_open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    store.ensure_subtitles_schema(conn)
    return conn


def no_schema_open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return store.connect_subtitles_db(path)


CHECKPOINT = Path(__file__).with_name("test_54_translate_job_handle_phase2.py")
TESTS = ["test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal", "test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues"]


@pytest.mark.parametrize("opener", [no_wal_open, no_schema_open])
def test_lines(opener, tmp_path):
    store.open_subtitles_db = opener
    spec = importlib.util.spec_from_file_location(f"cp_{opener.__name__}", CHECKPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for i, name in enumerate(TESTS):
        sub = tmp_path / str(i)
        sub.mkdir()
        try:
            getattr(module, name)(sub)
            print(f"\n{opener.__name__} {name[:40]}: pass")
        except BaseException as exc:  # noqa: BLE001
            frame = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == str(CHECKPOINT)][-1]
            print(f"\n{opener.__name__} {name[:40]}: {type(exc).__name__} {str(exc)[:100]!r} at line {frame.lineno}: {frame.line}")
