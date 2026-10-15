"""Probe: what the phase-2 harness reads against the current updater, before the pointer write exists."""
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("phase2_checkpoint", Path(__file__).with_name("test_63_catalog_update_weekly_increments_phase2.py"))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)
updater = t.updater


def test_groups():
    print("GROUPS", {h: int(hashlib.sha1(h.encode("utf-8")).hexdigest(), 16) % 7 for h in t.HOSTS})


@pytest.mark.parametrize("prior", [None, t.PRIOR_POINTER])
def test_success(monkeypatch, tmp_path, prior):
    mod = t._load_job("probe_updater_phase2", "updater-worker.py")
    state = t._pointer(tmp_path, prior)
    run = t._run_increment_main(mod, monkeypatch, tmp_path, state=state)
    print("SUCCESS", repr(run["error"]), run["hosts_at_channels"], run["pointer_at_merge"], run["pointer_at_popularity"], len(run["similarity"]), [Path(c[1]).name for c in run["calls"]])


@pytest.mark.parametrize("stop", t.STOPS)
def test_stop(monkeypatch, tmp_path, stop):
    mod = t._load_job("probe_updater_phase2", "updater-worker.py")
    state = t._pointer(tmp_path, t.PRIOR_POINTER)
    fd = None
    if stop == "run-lock-held":
        fd = os.open((tmp_path / "run.lock").as_posix(), os.O_RDONLY | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        run = t._run_increment_main(mod, monkeypatch, tmp_path, state=state, extra=["--fail-before-merge"] if stop == "fail-before-merge" else [], fail_merge=stop == "merge-child-fails")
    finally:
        if fd is not None:
            os.close(fd)
    print("STOP", stop, type(run["error"]).__name__, str(run["error"]), run["hosts_at_channels"], run["pointer_at_merge"], run["pointer_at_popularity"], len(run["calls"]), state.read_bytes() == t.PRIOR_POINTER)
