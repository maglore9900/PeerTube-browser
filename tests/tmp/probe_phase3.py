import json
import sqlite3

from test_10_normalise_instance_hosts_phase3 import DROPPED, JOBS_DIR, _load, _serve


def test_probe(tmp_path):
    sync_whitelist = _load("sw_probe", JOBS_DIR / "sync-whitelist.py")
    updater_worker = _load("uw_probe", JOBS_DIR / "updater-worker.py")
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    sync_whitelist.ensure_whitelist_schema(conn)
    print("SYNC_ONE", sync_whitelist.sync_hosts(conn, {"tube.example"}), conn.execute("SELECT host FROM instances").fetchall())
    conn.close()
    conn = sqlite3.connect(tmp_path / "old.db")
    sync_whitelist.ensure_whitelist_schema(conn)
    print("SYNC_OLD", sync_whitelist.sync_hosts(conn, {"https://tube.example/", "tube.example"}))
    conn.close()
    entries = [*DROPPED, "tube.example.", "https://Other.Example/videos"]
    url = _serve(tmp_path, {"data": [{"host": entry} for entry in entries]})
    print("JOIN_DICT", sorted(updater_worker.fetch_join_hosts(url)))
    print("ALL_NONE_SYNC", sorted(sync_whitelist.fetch_hosts(_serve(tmp_path, DROPPED))))
    assert False
