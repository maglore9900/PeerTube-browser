import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_63_catalog_update_weekly_increments_phase1 import HOSTS, VALID_POINTER, _is, _run_crawl_main, updater  # noqa: E402,F401


def test_probe_control_in_subdir_after_a_refused_run(updater, monkeypatch, tmp_path):
    state = tmp_path / "pointer" / "p.json"
    state.parent.mkdir()
    state.write_bytes(VALID_POINTER)
    first = _run_crawl_main(updater, monkeypatch, tmp_path, extra=["--increments", "-1"], state=state)
    print("PROBE first error", repr(first["error"]), "calls", first["calls"])
    control = _run_crawl_main(updater, monkeypatch, tmp_path / "control")
    print("PROBE control error", repr(control["error"]))
    print("PROBE control hosts_at_channels", control["hosts_at_channels"])
    print("PROBE control instances child", any(_is(cmd, "instances-cli.js") for cmd in control["calls"]))
    print("PROBE control children", [Path(c[1]).name if len(c) > 1 else c for c in control["calls"]])
    control2 = _run_crawl_main(updater, monkeypatch, tmp_path / "control2", extra=["--increments", "7"], state=state)
    print("PROBE control2 error", repr(control2["error"]), "calls", control2["calls"])
    assert False
