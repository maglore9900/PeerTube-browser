import subprocess
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"


def test_probe():
    tsc = subprocess.run(["npx", "tsc", "--noEmit"], cwd=FRONTEND, capture_output=True, text=True, timeout=600)
    lines = tsc.stdout.splitlines()
    print("TSC", tsc.returncode, len(lines))
    print(sorted({l.split("(")[0] for l in lines if "error TS" in l}))
    print([l for l in lines if "video-card" in l])
    assert False
