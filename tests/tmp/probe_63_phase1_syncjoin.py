import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_63_catalog_update_weekly_increments_phase1 import _run_crawl_main, updater  # noqa: E402,F401


def test_probe_sync_join_without_increments(updater, monkeypatch, tmp_path):
    join = tmp_path / "join-one.json"
    join.write_text('[{"host": "new.example"}]', encoding="utf-8")
    run = _run_crawl_main(updater, monkeypatch, tmp_path, extra=["--sync-join-whitelist", "--whitelist-url", join.as_uri()])
    print("PROBE error", type(run["error"]).__name__, run["error"])
    print("PROBE children", [Path(c[1]).name if len(c) > 1 else c for c in run["calls"]])
    assert False
