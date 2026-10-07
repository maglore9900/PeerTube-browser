"""Probe: what the installed tsc says about the search page and data/search.ts under the project tsconfig. The report is the failure message."""
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"


def test_probe():
    run = subprocess.run(["node", str(FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"), "--noEmit", "-p", str(FRONTEND)], capture_output=True, text=True, cwd=FRONTEND)
    lines = run.stdout.splitlines()
    ours = [line for line in lines if "search" in line]
    pytest.fail(f"exit {run.returncode}; {len(lines)} lines total; search lines:\n" + "\n".join(ours) + "\n--- first 15 lines ---\n" + "\n".join(lines[:15]))
