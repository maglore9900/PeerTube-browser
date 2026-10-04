"""Phase 2 checkpoint for `engine/server/db/jobs/translate-worker.py`: how `run --stall-seconds` parses: a positive whole number of seconds, refused at parse time otherwise and the shipped 600 s when omitted. Whether the parsed value reaches `heartbeat_loop` is not asserted here.

- `run --stall-seconds` given 0, -1, 1.5 or x, as the script run under `ENGINE_PY` with every path under `tmp_path`, exits 2 with argparse's refusal of that argument (`argument --stall-seconds: ...`, not `unrecognized arguments`, which a `run` without the flag also prints with exit 2) and creates no subtitles.db, lock or log, all three of which a run without the flag creates at the same paths; the same parser, called in-process, takes 1 as 1.
- `parse_args` on `run` with the flag omitted gives `stall_seconds` 600, the worker's own `STALL_SECONDS`.
"""
from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_translate_worker import STOP_WINDOW_SECONDS, WORKER, _paths, _require_tools, _run_argv, _until, _worker  # noqa: E402

# Each refused by _positive_int: below 1, negative, not whole, not a number. Probed on the sibling `run --max-duration`, which shares _positive_int: all four exit 2 with `argument --max-duration: ...` ("-1" taken as the value) and create nothing.
REFUSED_STALL_SECONDS = ["0", "-1", "1.5", "x"]
# Probed: a `run` without the flag exits 2 with `unrecognized arguments: --stall-seconds <value>`, which also names the flag; the flag's own refusal leads with this.
FLAG_REFUSAL = "argument --stall-seconds:"
# Probed: a run creates subtitles.db, lock and log within 0.06 s of starting.
RUN_START_SECONDS = 30.0


def _parse(worker: ModuleType, monkeypatch: pytest.MonkeyPatch, *argv: str):  # noqa: ANN202
    """The worker's own `parse_args` on `translate-worker.py <argv>`; argparse's exit is turned into a test failure so it cannot end the session."""
    monkeypatch.setattr(sys, "argv", [str(WORKER), *argv])
    try:
        return worker.parse_args()
    except SystemExit as exc:
        pytest.fail(f"parse_args exited {exc.code} on {list(argv)}")


# Service: the stall flag.


@pytest.mark.parametrize("value", REFUSED_STALL_SECONDS)
def test_run_refuses_a_stall_seconds_that_is_not_a_positive_integer_with_exit_2_naming_the_flag_and_creates_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """`run --stall-seconds` given 0, -1, 1.5 or x exits 2 with argparse's refusal of that argument, not an unrecognised-argument error, and leaves no subtitles.db, lock or log, which a run without the flag then creates at the same paths; 1 parses to 1."""
    # argparse exits before the ffmpeg check, but the control run below serves, so it needs ffmpeg too.
    _require_tools()
    paths = _paths(tmp_path)

    # A run that accepted the value would go on to serve, and raise TimeoutExpired here.
    result = subprocess.run(_run_argv(paths) + ["--stall-seconds", value], capture_output=True, text=True, timeout=30, cwd=tmp_path)

    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)  # C1: argparse's usage error, not the service's 0, 1 or 6
    assert FLAG_REFUSAL in result.stderr, result.stderr  # C1: the error names the flag as the argument refused
    assert "unrecognized arguments" not in result.stderr, result.stderr  # C1: the flag exists, so this is its value's refusal and not a run without the flag
    assert not paths["subtitles"].exists()  # C1: no subtitles.db created
    assert not paths["lock"].exists()  # C1: no lock file created
    assert not paths["log"].exists()  # C1: refused before logging was set up, so no log file

    # The same paths without the flag: a run that accepts its arguments creates all three at once (probed: 0.06 s), so their absence above is the refusal's.
    with (tmp_path / "run.out").open("wb") as out:
        proc = subprocess.Popen(_run_argv(paths), stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            assert _until(lambda: all(paths[name].exists() for name in ("subtitles", "lock", "log")), RUN_START_SECONDS), (proc.poll(), sorted(path.name for path in tmp_path.iterdir()))  # control: these are the paths a run creates
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=STOP_WINDOW_SECONDS)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    assert _parse(_worker(), monkeypatch, "run", "--stall-seconds", "1").stall_seconds == 1  # control: the least positive integer is taken, so the refusal above is the value's and not the flag's


def test_run_without_stall_seconds_parses_to_the_shipped_600_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """`parse_args` on `run` with `--stall-seconds` omitted gives `stall_seconds` 600, equal to the worker's `STALL_SECONDS`."""
    worker = _worker()
    args = _parse(worker, monkeypatch, "run")
    assert args.stall_seconds == 600, args  # C2: the shipped 600 s
    assert args.stall_seconds == worker.STALL_SECONDS, (args.stall_seconds, worker.STALL_SECONDS)  # C2: the default agrees with the worker's STALL_SECONDS (probed: 600.0)
