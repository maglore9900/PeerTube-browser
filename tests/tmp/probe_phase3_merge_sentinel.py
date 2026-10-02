import sqlite3
import subprocess
import sys

from test_41_ann_ids_a_schema_writers_phase3 import EMBEDDINGS, MERGE_JOB, ROWS_SQL, SOURCE_ANN_ID_EMBEDDINGS_SQL, V1_ID, V2_ID, V3_ID, VIDEOS, _seed, sync_job  # noqa: F401


def _seven_column_target(sync_job, path):
    conn = sqlite3.connect(path)
    sync_job.ensure_whitelist_schema(conn)
    sync_job.ensure_content_schema(conn)
    conn.execute("DROP TABLE video_embeddings")
    conn.executescript(SOURCE_ANN_ID_EMBEDDINGS_SQL)
    return conn


def test_probe(sync_job, tmp_path):
    prod_db, staging_db = tmp_path / "prod.db", tmp_path / "staging.db"
    replacement_v1 = ("v1", "a.example", b"\x11\x12", 2, "m2", "t9", V1_ID)
    staged = [replacement_v1, EMBEDDINGS[1] + (V2_ID,), EMBEDDINGS[2] + (V3_ID,)]
    prod = _seven_column_target(sync_job, prod_db)
    _seed(prod, [("v1", "a.example")], [EMBEDDINGS[0] + (555,)])
    print("prod before:", prod.execute(ROWS_SQL).fetchall())
    prod.close()
    staging = _seven_column_target(sync_job, staging_db)
    _seed(staging, [row[:2] for row in VIDEOS], staged)
    staging.close()
    result = subprocess.run([sys.executable, str(MERGE_JOB), "--prod-db", str(prod_db), "--staging-db", str(staging_db)], capture_output=True, text=True)
    print("rc:", result.returncode)
    print("stderr:", result.stderr)
    prod = sqlite3.connect(prod_db)
    print("prod after:", prod.execute(ROWS_SQL).fetchall())
    print("equals staged:", prod.execute(ROWS_SQL).fetchall() == staged)
    prod.close()
    assert False
