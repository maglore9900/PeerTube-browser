import importlib.util
import sqlite3
import time

import pytest

from test_11_fast_similars_response_phase2 import SERVER_DIR, _seed, sync_job  # noqa: F401


def test_probe(sync_job, tmp_path):
    spec = importlib.util.spec_from_file_location("data_db_probe", SERVER_DIR / "data" / "db.py")
    db = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(db)
    out = {}
    for heavy in (True, False):
        path = tmp_path / f"c{heavy}.db"
        _seed(sync_job, path, heavy)
        conn = db.connect_db(path)
        try:
            with db.statement_deadline(0.05):
                time.sleep(0.1)
                try:
                    conn.execute("UPDATE videos SET title = 'x' WHERE video_id = 'v1'")
                    out[heavy] = "ok"
                except sqlite3.OperationalError as exc:
                    out[heavy] = repr(exc)
            conn.rollback()
        finally:
            conn.close()
    print(sqlite3.sqlite_version, out)
    assert False, (sqlite3.sqlite_version, out)
