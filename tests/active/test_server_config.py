"""`INTERACTION_RAW_RETENTION_DAYS` is read from the environment when `server_config` is imported, and a bad value stops the Engine.

- In a child process, `7` and `1` become the int constant, and an unset variable gives the int 30.
- `abc`, `0`, `-3`, `7.5` and `""` make a bare `import server_config` exit with status 1, and the last stderr line names the variable.
- `server.py --help`, run by the Engine's own interpreter, exits 0 and prints its usage when the variable is unset. With `abc` it exits 1 before printing usage, and the last stderr line names the variable.

`RECOMMENDATIONS_DEBUG_ENABLED` is True in a child whose `RECOMMENDATIONS_DEBUG` is `1`, `true`, `yes`, `TRUE` or ` yes `, and False when it is unset, `""`, `0`, `no` or `on`.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import ENGINE_PY, ROOT

API_DIR = ROOT / "engine" / "server" / "api"
VAR = "INTERACTION_RAW_RETENTION_DAYS"
# repr so a constant left as the raw env string prints '7' and not 7.
PRINT_DAYS = f"import server_config as c; print(repr(c.{VAR}))"


def _run(argv: list[str], value: str | None, var: str = VAR) -> subprocess.CompletedProcess:
    # The value goes only into a copy for the child, never into this process's os.environ: the Engine fixture and `test_similar.py` import `server_config` here.
    env = {key: val for key, val in os.environ.items() if key != var}
    if value is not None:
        env[var] = value
    return subprocess.run(argv, cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)


def _last_stderr_line(run: subprocess.CompletedProcess) -> str:
    # The message itself, not a traceback's source excerpt, which quotes the assignment line and so names the variable for any crash there.
    lines = run.stderr.strip().splitlines()
    return lines[-1] if lines else ""


@pytest.mark.parametrize("value, expected", [("7", "7"), ("1", "1"), (None, "30")], ids=["seven", "one", "unset"])
def test_a_positive_integer_becomes_the_constant_and_unset_gives_30(value, expected):
    run = _run([sys.executable, "-c", PRINT_DAYS], value)

    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == expected


@pytest.mark.parametrize("value", ["abc", "0", "-3", "7.5", ""], ids=["abc", "zero", "negative", "fraction", "empty"])
def test_a_value_that_is_not_a_positive_integer_stops_the_import(value):
    # A bare import: reading the attribute would exit 1 naming the variable with an AttributeError before it exists (observed).
    run = _run([sys.executable, "-c", "import server_config"], value)

    assert run.returncode == 1, run.stderr[-2000:]
    assert VAR in _last_stderr_line(run), run.stderr[-2000:]


def test_server_py_exits_before_argument_parsing_on_a_bad_value():
    # pytest's own interpreter has no numpy, so `server.py` exits 1 there whatever the env holds (observed).
    ok = _run([str(ENGINE_PY), str(API_DIR / "server.py"), "--help"], None)
    assert ok.returncode == 0, ok.stderr[-2000:]  # control: the entry point runs in this interpreter
    assert "--port PORT" in ok.stdout  # control: and reaches argparse

    run = _run([str(ENGINE_PY), str(API_DIR / "server.py"), "--help"], "abc")

    assert run.returncode == 1, run.stderr[-2000:]
    assert VAR in _last_stderr_line(run), run.stderr[-2000:]
    assert "--port PORT" not in run.stdout  # it stopped before parsing arguments


DEBUG_VAR = "RECOMMENDATIONS_DEBUG"
# repr so a flag left as the raw env string prints '1' and not True.
PRINT_DEBUG_FLAG = "import server_config as c; print(repr(c.RECOMMENDATIONS_DEBUG_ENABLED))"


@pytest.mark.parametrize("value, expected", [
    ("1", "True"),
    ("true", "True"),
    ("yes", "True"),
    ("TRUE", "True"),
    (" yes ", "True"),
    (None, "False"),
    ("", "False"),
    ("0", "False"),
    ("no", "False"),
    ("on", "False"),
], ids=["one", "true", "yes", "upper-true", "padded-yes", "unset", "empty", "zero", "no", "on"])
def test_flag_is_true_only_for_1_true_or_yes(value, expected):
    # A fresh child per value: the flag is computed once, when server_config is imported, so one process can read only one env value.
    run = _run([sys.executable, "-c", PRINT_DEBUG_FLAG], value, DEBUG_VAR)

    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == expected
