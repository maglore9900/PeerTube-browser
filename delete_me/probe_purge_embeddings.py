import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("checkpoint", Path(__file__).with_name("test_45_trending_from_source_instances_phase1.py"))
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


def test_probe(tmp_path):
    conn = checkpoint._db(tmp_path / "whitelist.db", [("a-v1", "a.example"), ("b-v1", "b.example")])
    print("BEFORE", [row[0] for row in conn.execute("SELECT video_id FROM video_embeddings ORDER BY video_id")])
    counts = checkpoint.purge_host_data(conn, "a.example")
    print("COUNTS", counts)
    print("AFTER", [row[0] for row in conn.execute("SELECT video_id FROM video_embeddings ORDER BY video_id")])
