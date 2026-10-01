"""`engine/engine-upstream.sh`'s `read_active_port` is held to the same snippet case table as the updater's `parse_upstream_snippet`.

- Sourced from the library, `read_active_port` prints the port and exits 0 for every accepted case of tests/active/upstream_snippet_cases.json, and exits non-zero for every rejected case and for a missing file.

The library is sourced by bash in a subprocess, with only /usr/bin and /bin on PATH, and the snippet is written as bytes under tmp.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB_SRC = ROOT / "engine" / "engine-upstream.sh"
CASES_FILE = ROOT / "tests" / "active" / "upstream_snippet_cases.json"
BASH = shutil.which("bash", path="/usr/bin:/bin")


def _case_params() -> list:
    if not CASES_FILE.exists():
        return [pytest.param(None, id="json-case-file-missing")]
    return [pytest.param(case, id=case["id"]) for case in json.loads(CASES_FILE.read_text(encoding="utf-8"))]


def _bash_cases() -> list:
    return _case_params() + [pytest.param({"id": "missing", "text": None, "port": None}, id="missing")]


@pytest.mark.parametrize("case", _bash_cases())
def test_bash_read_active_port_matches_shared_cases(tmp_path: Path, case) -> None:
    """Sourced from engine/engine-upstream.sh, `read_active_port` prints the port and exits 0 for every accepted case of tests/active/upstream_snippet_cases.json, and exits non-zero for every rejected case and for a missing file."""
    assert case is not None, f"{CASES_FILE} is missing"
    assert LIB_SRC.is_file(), f"{LIB_SRC} does not exist"
    path = tmp_path / "peertube-engine-upstream.conf"
    if case["text"] is not None:
        path.write_bytes(case["text"].encode())

    run = subprocess.run([BASH, "-c", 'source "$1" && declare -F read_active_port >/dev/null && echo SOURCED >&2 && read_active_port "$2"', "_", str(LIB_SRC), str(path)], env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)

    assert "SOURCED" in run.stderr, run.stderr  # control: the library sourced and defines read_active_port, so a non-zero exit below is the parser's
    if case["port"] is None:
        assert run.returncode != 0, (run.returncode, run.stdout)  # the deploy refuses this snippet
    else:
        assert (run.returncode, run.stdout.strip()) == (0, str(case["port"])), (run.returncode, run.stdout, run.stderr)  # the active port the deploy flips from
