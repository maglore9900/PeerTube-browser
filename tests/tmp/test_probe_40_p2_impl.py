from pathlib import Path
import subprocess

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"


def test_probe_tsc_search_page():
    run = subprocess.run([str(FRONTEND / "node_modules" / ".bin" / "tsc"), "--noEmit"], cwd=FRONTEND, capture_output=True, text=True)
    lines = run.stdout.splitlines()
    print("exit", run.returncode, "total lines", len(lines))
    print("\n".join(sorted({l.split("(")[0] for l in lines if "error TS" in l})))
    search = [l for l in lines if "pages/search" in l]
    print("SEARCH:", "\n".join(search) or "none")
    assert not search
