import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("cp", Path(__file__).with_name("test_49_translate_whisper_worker_phase1.py"))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def test_probe_upgrade_race(tmp_path):
    bad = []
    for round_no in range(96):
        path = tmp_path / f"race-{round_no}.db"
        cp._b1_file(path)
        synced, results = cp._run_together([(cp.UPGRADE_SCRIPT, [str(path)]), (cp.UPGRADE_SCRIPT, [str(path)])], tmp_path, f"race-{round_no}")
        for rc, out, err in results:
            if rc != 0 or err.strip():
                bad.append((round_no, rc, err.strip().splitlines()[-1:]))
    print("bad", bad)
    assert bad == []


def test_probe_writers(tmp_path):
    path = tmp_path / "subtitles.db"
    cp._b1_file(path)
    synced, results = cp._run_together([(cp.ENGINE_SCRIPT, [str(path), "3", cp.ENGINE_HOST]), (cp.WORKER_SCRIPT, [str(path), "3", cp.WORKER_HOST, str(cp.BEAT_BASE)])], tmp_path, "r8")
    print("synced", synced, [(rc, out, err[-300:]) for rc, out, err in results])
    assert all(rc == 0 for rc, _, _ in results)
