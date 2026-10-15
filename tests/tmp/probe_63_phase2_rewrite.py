"""Probe: mod-3 groups and the run at --increments 3 over a stale N=7 pointer; the lock refusal when the lock file holds a live pid."""
import hashlib
import importlib.util
import os
from pathlib import Path

_spec = importlib.util.spec_from_file_location("phase2_checkpoint_rw", Path(__file__).with_name("test_63_catalog_update_weekly_increments_phase2.py"))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)


def test_groups3():
    print("GROUPS3", {h: int(hashlib.sha1(h.encode("utf-8")).hexdigest(), 16) % 3 for h in t.HOSTS})


def test_n3_over_stale_pointer(monkeypatch, tmp_path):
    mod = t._load_job("probe_updater_phase2_rw", "updater-worker.py")
    state = t._pointer(tmp_path, t.PRIOR_POINTER)
    run = t._run_increment_main(mod, monkeypatch, tmp_path, state=state, extra=["--increments", "3"])
    print("N3", repr(run["error"]), run["hosts_at_channels"], run["pointer_at_merge"], run["pointer_at_popularity"], len(run["similarity"]))


def test_lock_live_pid(monkeypatch, tmp_path):
    mod = t._load_job("probe_updater_phase2_rw2", "updater-worker.py")
    state = t._pointer(tmp_path, t.PRIOR_POINTER)
    (tmp_path / "run.lock").write_text(str(os.getpid()), encoding="utf-8")
    run = t._run_increment_main(mod, monkeypatch, tmp_path, state=state)
    print("LOCK", os.getpid(), type(run["error"]).__name__, str(run["error"]), run["calls"], state.read_bytes() == t.PRIOR_POINTER, (tmp_path / "run.lock").read_text())
    assert False, "show output"
