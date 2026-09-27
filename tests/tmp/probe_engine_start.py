"""Probe: six pytest processes at once, each taking the real `engine` fixture, as six lanes would."""
import subprocess
import sys
from pathlib import Path

INNER = Path(__file__).resolve().parent / "probe_inner_engine.py"


def test_probe_six_lanes_start_engines(tmp_path):
    procs = [subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(INNER), f"--basetemp={tmp_path / str(i)}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for i in range(6)]
    outs = [p.communicate(timeout=600)[0] for p in procs]
    for i, (p, out) in enumerate(zip(procs, outs)):
        print(f"=== lane {i}: exit {p.returncode}")
        print(out[-1500:])
    assert [p.returncode for p in procs] == [0] * 6
