"""`RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is read from the environment when `server_config` is imported, and `random_cache_refresh_interval_minutes(dev)` lets it win over `--dev`.

- In a child process, an unset variable, `""` and `"  "` leave the constant `None`, and `0` and `7` make it the int.
- `abc`, `-1` and `7.5` make a bare `import server_config` exit with status 1, and the last stderr line names the variable.
- `random_cache_refresh_interval_minutes(False)` and `(True)` give 60 and 0 when the variable is unset or `""`, 0 and 0 when it is `0`, and 5 and 5 when it is `5`.

Each value runs in a fresh child through `sys.executable`, because the constant is computed once, at import.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
VAR = "RANDOM_CACHE_REFRESH_INTERVAL_MINUTES"
# repr so a constant left as the raw env string prints '7' and not 7, and a blank left as '' prints '' and not None.
PRINT_INTERVAL = f"import server_config as c; print(repr(c.{VAR}))"
PRINT_RESOLVED = "import server_config as c; print(repr((c.random_cache_refresh_interval_minutes(False), c.random_cache_refresh_interval_minutes(True))))"


def _run(argv: list[str], value: str | None, var: str = VAR) -> subprocess.CompletedProcess:
    # The value goes only into a copy for the child, never into this process's os.environ.
    env = {key: val for key, val in os.environ.items() if key != var}
    if value is not None:
        env[var] = value
    return subprocess.run(argv, cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)


def _last_stderr_line(run: subprocess.CompletedProcess) -> str:
    # The message itself, not a traceback's source excerpt, which quotes the assignment line and so names the variable for any crash there.
    lines = run.stderr.strip().splitlines()
    return lines[-1] if lines else ""


@pytest.mark.parametrize("value, expected", [(None, "None"), ("", "None"), ("  ", "None"), ("0", "0"), ("7", "7")], ids=["unset", "empty", "blank", "zero", "seven"])
def test_unset_or_blank_gives_none_and_a_non_negative_integer_becomes_the_constant(value, expected):
    run = _run([sys.executable, "-c", PRINT_INTERVAL], value)

    assert run.returncode == 0, run.stderr[-2000:]  # C1
    assert run.stdout.strip() == expected  # C1


@pytest.mark.parametrize("value", ["abc", "-1", "7.5"], ids=["abc", "negative", "fraction"])
def test_a_value_that_is_not_a_non_negative_integer_stops_the_import(value):
    # A bare import: reading the attribute would exit 1 naming the variable with an AttributeError before it exists (observed).
    run = _run([sys.executable, "-c", "import server_config"], value)

    assert run.returncode == 1, run.stderr[-2000:]  # C1
    assert VAR in _last_stderr_line(run), run.stderr[-2000:]  # C1


@pytest.mark.parametrize("value, expected", [(None, "(60, 0)"), ("", "(60, 0)"), ("0", "(0, 0)"), ("5", "(5, 5)")], ids=["unset", "empty", "zero", "five"])
def test_interval_is_the_env_value_when_set_else_0_under_dev_and_60_without(value, expected):
    # `0` separates "is set" from "is truthy": a fallback on a falsy value gives (60, 0) there.
    run = _run([sys.executable, "-c", PRINT_RESOLVED], value)

    assert run.returncode == 0, run.stderr[-2000:]  # C2
    assert run.stdout.strip() == expected  # C2
