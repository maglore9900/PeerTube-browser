from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import _paths, _require_tools, _run_argv, _until, _worker  # noqa: E402


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "x"])
def test_probe_sibling_flag_refusal(tmp_path: Path, value: str) -> None:
    paths = _paths(tmp_path)
    result = subprocess.run(_run_argv(paths) + ["--max-duration", value], capture_output=True, text=True, timeout=30, cwd=tmp_path)
    print("PROBE", value, result.returncode, repr(result.stderr.splitlines()[-1]), sorted(p.name for p in tmp_path.iterdir()))


def test_probe_run_creates_paths(tmp_path: Path) -> None:
    _require_tools()
    paths = _paths(tmp_path)
    started = time.monotonic()
    with (tmp_path / "run.out").open("wb") as out:
        proc = subprocess.Popen(_run_argv(paths), stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            ok = _until(lambda: all(paths[k].exists() for k in ("subtitles", "lock", "log")), 30)
            print("PROBE run", ok, round(time.monotonic() - started, 2), proc.poll(), sorted(p.name for p in tmp_path.iterdir()))
            proc.send_signal(signal.SIGTERM)
            print("PROBE exit", proc.wait(timeout=60), round(time.monotonic() - started, 2))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_probe_stall_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _worker()
    print("PROBE STALL_SECONDS", repr(worker.STALL_SECONDS))
    assert False
