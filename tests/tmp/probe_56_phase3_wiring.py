"""Probe: the phase 3 checkpoint's two tests against tmp copies of the worker: `wired` (heartbeat_loop takes stall_seconds, command_run passes args.stall_seconds; both green expected) and `hard4` (the comparison hard-coded to 4; the 60 s test red expected)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_56_split_translate_worker_phase3 as checkpoint  # noqa: E402
from test_translate_worker import ENGINE_PY, SERVER_DIR, WORKER  # noqa: E402

SIG_OLD = "def heartbeat_loop(db_path: Path, stop: threading.Event, progress: dict[str, float]) -> None:"
SIG_NEW = "def heartbeat_loop(db_path: Path, stop: threading.Event, progress: dict[str, float], *, stall_seconds: float = STALL_SECONDS) -> None:"
CMP_OLD = 'if time.monotonic() - progress["at"] <= STALL_SECONDS:'
THREAD_OLD = "beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)"
THREAD_NEW = 'beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), kwargs={"stall_seconds": args.stall_seconds}, daemon=True)'
VARIANTS = {"wired": 'if time.monotonic() - progress["at"] <= stall_seconds:', "hard4": 'if time.monotonic() - progress["at"] <= 4:'}


def _copy(root: Path, cmp_new: str) -> Path:
    path = root / "a" / "db" / "jobs" / "translate-worker.py"
    path.parent.mkdir(parents=True)
    text = WORKER.read_text()
    for old in (SIG_OLD, CMP_OLD, THREAD_OLD):
        assert text.count(old) == 1, old
    path.write_text(text.replace(SIG_OLD, SIG_NEW).replace(CMP_OLD, cmp_new).replace(THREAD_OLD, THREAD_NEW))
    return path


@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("test", ["test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on", "test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall"])
def test_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str, test: str) -> None:
    script = _copy(tmp_path / "copy", VARIANTS[variant])
    monkeypatch.setenv("PYTHONPATH", f"{SERVER_DIR}:{SERVER_DIR / 'api'}")
    real = checkpoint._run_argv
    monkeypatch.setattr(checkpoint, "_run_argv", lambda paths: [str(ENGINE_PY), str(script), *real(paths)[2:]])
    work = tmp_path / "work"
    work.mkdir()
    getattr(checkpoint, test)(work)
