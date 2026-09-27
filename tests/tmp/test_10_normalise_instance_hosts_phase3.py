"""Phase 3 checkpoint: the whitelist-sync and updater jobs normalise hosts-list entries to bare lowercase hosts, as pinned by the literal inputs below.

- `fetch_hosts` in sync-whitelist.py reads a list payload `["https://Tube.Example/", "tube.example"]` as the one host `tube.example`, and `sync_hosts`, given that set on a fresh whitelist schema in a tmp_path SQLite file, returns (1, 0, 1) and leaves exactly the row `tube.example`.
- On a `{"data": [...]}` payload whose `""`, `"   "`, `"."` and `"https://"` entries normalise to None, `fetch_hosts` and `fetch_join_hosts` in updater-worker.py both drop those entries and return exactly `{"tube.example", "other.example"}`.
- `fetch_hosts` on a payload whose every entry normalises to None still raises ValueError "Whitelist contained no hosts.".
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = ROOT / "engine" / "server" / "db" / "jobs"

DROPPED = ["", "   ", ".", "https://"]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def jobs():
    return _load("sync_whitelist_job", JOBS_DIR / "sync-whitelist.py"), _load("updater_worker_job", JOBS_DIR / "updater-worker.py")


def _serve(tmp_path: Path, payload) -> str:
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_uri()


def test_fetch_hosts_collapses_url_and_bare_host_into_one_synced_row(jobs, tmp_path):
    sync_whitelist, _ = jobs
    url = _serve(tmp_path, ["https://Tube.Example/", "tube.example"])
    hosts = sync_whitelist.fetch_hosts(url)
    assert hosts == {"tube.example"}  # C1
    conn = sqlite3.connect(tmp_path / "whitelist.db")
    try:
        sync_whitelist.ensure_whitelist_schema(conn)
        assert sync_whitelist.sync_hosts(conn, hosts) == (1, 0, 1)  # C1
        assert conn.execute("SELECT host FROM instances").fetchall() == [("tube.example",)]  # C1
    finally:
        conn.close()


def test_both_fetchers_drop_entries_that_normalise_to_none(jobs, tmp_path):
    sync_whitelist, updater_worker = jobs
    entries = [*DROPPED, "tube.example.", "https://Other.Example/videos"]
    url = _serve(tmp_path, {"data": [{"host": entry} for entry in entries]})
    assert sync_whitelist.fetch_hosts(url) == {"tube.example", "other.example"}  # C2
    assert updater_worker.fetch_join_hosts(url) == {"tube.example", "other.example"}  # C2


def test_fetch_hosts_still_raises_when_every_entry_normalises_to_none(jobs, tmp_path):
    sync_whitelist, _ = jobs
    url = _serve(tmp_path, DROPPED)
    with pytest.raises(ValueError, match="^Whitelist contained no hosts\\.$"):  # C2
        sync_whitelist.fetch_hosts(url)
