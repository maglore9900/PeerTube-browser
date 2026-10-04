from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_56_split_translate_worker_phase3 import _hold_main_loop, _stop  # noqa: E402
from test_translate_worker import FIRST_BEAT_SECONDS, RESUME_SECONDS, _beat, _jobs, _next_beat, _paths, _require_tools, _run_argv, _whitelist  # noqa: E402


def test_probe_release_path(tmp_path: Path) -> None:
    _require_tools()
    paths = _paths(tmp_path)
    _whitelist(paths["whitelist"], [], deny=False)
    argv = _run_argv(paths) + ["--stall-seconds", "4"]
    out_path = tmp_path / "run.out"
    with out_path.open("wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, cwd=tmp_path)
        try:
            first = _next_beat(paths["subtitles"], proc, None, FIRST_BEAT_SECONDS)
            print("PROBE first", first, "pid", proc.pid)
            stalled, after, released_ms = _hold_main_loop(paths, proc, out_path)
            print("PROBE stalled", stalled, "after", after, "released_ms", released_ms)
            resumed = _next_beat(paths["subtitles"], proc, after, RESUME_SECONDS)
            print("PROBE resumed", resumed, "ge_release", resumed is not None and resumed[0] >= released_ms)
            print("PROBE jobs", _jobs(paths["subtitles"]), "beat", _beat(paths["subtitles"]))
            print("PROBE stop", _stop(proc))
            print("PROBE out", out_path.read_text(encoding="utf-8", errors="replace")[-1500:])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    assert False, "probe: read the PROBE lines"
