"""`INTERACTION_RAW_RETENTION_DAYS` is read from the environment when `server_config` is imported, and a bad value stops the Engine.

- In a child process, `7` and `1` become the int constant, and an unset variable gives the int 30.
- `abc`, `0`, `-3`, `7.5` and `""` make a bare `import server_config` exit with status 1, and the last stderr line names the variable.
- `server.py --help`, run by the Engine's own interpreter, exits 0 and prints its usage when the variable is unset. With `abc` it exits 1 before printing usage, and the last stderr line names the variable.

`RECOMMENDATIONS_DEBUG_ENABLED` is True in a child whose `RECOMMENDATIONS_DEBUG` is `1`, `true`, `yes`, `TRUE` or ` yes `, and False when it is unset, `""`, `0`, `no` or `on`.

`RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` is read at import, and `random_cache_refresh_interval_minutes(dev)` lets it win over `--dev`:

- In a child process, an unset variable, `""` and `"  "` leave the constant `None`, and `0` and `7` make it the int.
- `abc`, `-1` and `7.5` make a bare `import server_config` exit with status 1, and the last stderr line names the variable.
- `random_cache_refresh_interval_minutes(False)` and `(True)` give 60 and 0 when the variable is unset or `""`, 0 and 0 when it is `0`, and 5 and 5 when it is `5`.

The up-next diversity constants, in the Engine's config module and in the Engine's startup log:

- `server_config.py`, loaded from its file, holds SIMILAR_VIDEO_SEARCH_LIMIT 5000, TOP_K 300, NPROBE 32,
  MAX_NPROBE 128, MAX_SEARCH_LIMIT 20000, MIN_SCORE 0.35, TAIL_MIN_SCORE 0.25 and SAMPLE_WINDOW_FACTOR 4, each
  of that type; SIMILAR_VIDEO_TARGET_MIN_POOL is BATCH_SIZE, which is 48, and follows it when the home profile's
  batch_size is 64; and RELATED_VIDEOS_PERSONALIZATION has alpha 0.7 and beta 0.3.
- The session `engine` fixture's log carries a JSON line whose message starts `[similar-server] upnext_config`,
  one per Engine start (as many as its `ann_nprobe_configured` lines), and every such line has exactly those nine
  SIMILAR_VIDEO_* NAME=value tokens, each value the str of the default.
- An Engine started with the nine constants overridden in its config module logs exactly one such line, whose
  tokens carry the overridden values.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, _free_port

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


INTERVAL_VAR = "RANDOM_CACHE_REFRESH_INTERVAL_MINUTES"
# repr so a constant left as the raw env string prints '7' and not 7, and a blank left as '' prints '' and not None.
PRINT_INTERVAL = f"import server_config as c; print(repr(c.{INTERVAL_VAR}))"
PRINT_RESOLVED = "import server_config as c; print(repr((c.random_cache_refresh_interval_minutes(False), c.random_cache_refresh_interval_minutes(True))))"


@pytest.mark.parametrize("value, expected", [(None, "None"), ("", "None"), ("  ", "None"), ("0", "0"), ("7", "7")], ids=["unset", "empty", "blank", "zero", "seven"])
def test_unset_or_blank_gives_none_and_a_non_negative_integer_becomes_the_constant(value, expected):
    # A fresh child per value: the constant is computed once, when server_config is imported.
    run = _run([sys.executable, "-c", PRINT_INTERVAL], value, INTERVAL_VAR)

    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == expected


@pytest.mark.parametrize("value", ["abc", "-1", "7.5"], ids=["abc", "negative", "fraction"])
def test_a_value_that_is_not_a_non_negative_integer_stops_the_import(value):
    # A bare import: reading the attribute would exit 1 naming the variable with an AttributeError before it exists (observed).
    run = _run([sys.executable, "-c", "import server_config"], value, INTERVAL_VAR)

    assert run.returncode == 1, run.stderr[-2000:]
    assert INTERVAL_VAR in _last_stderr_line(run), run.stderr[-2000:]


@pytest.mark.parametrize("value, expected", [(None, "(60, 0)"), ("", "(60, 0)"), ("0", "(0, 0)"), ("5", "(5, 5)")], ids=["unset", "empty", "zero", "five"])
def test_interval_is_the_env_value_when_set_else_0_under_dev_and_60_without(value, expected):
    # `0` separates "is set" from "is truthy": a fallback on a falsy value gives (60, 0) there.
    run = _run([sys.executable, "-c", PRINT_RESOLVED], value, INTERVAL_VAR)

    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == expected


SERVER_CONFIG = API_DIR / "server_config.py"
UPNEXT_PREFIX = "[similar-server] upnext_config"
# Logged once by every start that loads the index, at the point where the upnext_config line is logged.
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
LOG_WAIT_SECONDS = 5
VARIANT_START_SECONDS = 120
# The home profile's literal comes first in the file; the guest_home profile repeats it.
HOME_BATCH_SIZE_LITERAL = '"batch_size": 48,'
# The defaults are the claim, so they stay literals: retuning a default is a requirement change that edits this test.
EXPECTED_DEFAULTS = {
    "SIMILAR_VIDEO_SEARCH_LIMIT": 5000,
    "SIMILAR_VIDEO_TOP_K": 300,
    "SIMILAR_VIDEO_NPROBE": 32,
    "SIMILAR_VIDEO_MAX_NPROBE": 128,
    "SIMILAR_VIDEO_MAX_SEARCH_LIMIT": 20000,
    "SIMILAR_VIDEO_MIN_SCORE": 0.35,
    "SIMILAR_VIDEO_TAIL_MIN_SCORE": 0.25,
    "SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR": 4,
}
EXPECTED_LOG_TOKENS = {
    "SIMILAR_VIDEO_SEARCH_LIMIT": "5000",
    "SIMILAR_VIDEO_TOP_K": "300",
    "SIMILAR_VIDEO_NPROBE": "32",
    "SIMILAR_VIDEO_MAX_NPROBE": "128",
    "SIMILAR_VIDEO_MAX_SEARCH_LIMIT": "20000",
    "SIMILAR_VIDEO_MIN_SCORE": "0.35",
    "SIMILAR_VIDEO_TAIL_MIN_SCORE": "0.25",
    "SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR": "4",
    "SIMILAR_VIDEO_TARGET_MIN_POOL": "48",
}
# Every value differs from its default; DEFAULT_NPROBE's shows in the ann_nprobe_configured line that the overrides reached server.py.
VARIANT_OVERRIDES = {
    "DEFAULT_NPROBE": 25,
    "SIMILAR_VIDEO_SEARCH_LIMIT": 5001,
    "SIMILAR_VIDEO_TOP_K": 301,
    "SIMILAR_VIDEO_NPROBE": 33,
    "SIMILAR_VIDEO_MAX_NPROBE": 129,
    "SIMILAR_VIDEO_MAX_SEARCH_LIMIT": 20001,
    "SIMILAR_VIDEO_MIN_SCORE": 0.36,
    "SIMILAR_VIDEO_TAIL_MIN_SCORE": 0.26,
    "SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR": 5,
    "SIMILAR_VIDEO_TARGET_MIN_POOL": 49,
}
VARIANT_LOG_TOKENS = {
    "SIMILAR_VIDEO_SEARCH_LIMIT": "5001",
    "SIMILAR_VIDEO_TOP_K": "301",
    "SIMILAR_VIDEO_NPROBE": "33",
    "SIMILAR_VIDEO_MAX_NPROBE": "129",
    "SIMILAR_VIDEO_MAX_SEARCH_LIMIT": "20001",
    "SIMILAR_VIDEO_MIN_SCORE": "0.36",
    "SIMILAR_VIDEO_TAIL_MIN_SCORE": "0.26",
    "SIMILAR_VIDEO_SAMPLE_WINDOW_FACTOR": "5",
    "SIMILAR_VIDEO_TARGET_MIN_POOL": "49",
}
# Runs server.py as __main__ with `server_config` bound to the real file's module, the overrides set on it.
VARIANT_RUNNER = """
import importlib.util, json, os, runpy, sys
server, overrides = sys.argv[1], json.loads(sys.argv[2])
api = os.path.dirname(server)
sys.path.insert(0, api)
spec = importlib.util.spec_from_file_location("server_config", os.path.join(api, "server_config.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name, value in overrides.items():
    setattr(module, name, value)
sys.modules["server_config"] = module
sys.argv = [server, *sys.argv[3:]]
runpy.run_path(server, run_name="__main__")
"""


def _load(name: str, source: str):
    spec = importlib.util.spec_from_file_location(name, SERVER_CONFIG)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(SERVER_CONFIG), "exec"), module.__dict__)
    return module


def _payloads(log_path: Path) -> list[dict]:
    payloads = []
    for line in log_path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _messages(log_path: Path, prefix: str) -> list[str]:
    return [payload["message"] for payload in _payloads(log_path) if isinstance(payload.get("message"), str) and payload["message"].startswith(prefix)]


def _tokens(message: str) -> list[tuple[str, ...]]:
    return sorted(tuple(token.split("=", 1)) for token in message[len(UPNEXT_PREFIX):].split() if "=" in token)


def _has_started(log_path: Path) -> bool:
    # The lifecycle start is the Engine's last startup line, logged just before it serves.
    return any(payload.get("event") == "service.lifecycle" and (payload.get("context") or {}).get("state") == "start" for payload in _payloads(log_path))


def _start_variant(log_path: Path) -> None:
    """Start the Engine with VARIANT_OVERRIDES in its config module, logging to log_path, and stop it once it has started."""
    with open(log_path, "w") as log, open(ENGINE_START_LOCK, "w") as start_lock:
        fcntl.flock(start_lock, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            [str(ENGINE_PY), "-c", VARIANT_RUNNER, str(ENGINE_SERVER), json.dumps(VARIANT_OVERRIDES), "--host", "127.0.0.1", "--port", str(_free_port()), "--no-random-cache-refresh"],
            stdout=log, stderr=log,
        )
        try:
            deadline = time.time() + VARIANT_START_SECONDS
            while proc.poll() is None and time.time() < deadline and not _has_started(log_path):
                time.sleep(0.1)
            assert _has_started(log_path), f"the variant Engine did not start within {VARIANT_START_SECONDS}s; see {log_path}"
        finally:
            proc.terminate()
            proc.wait(timeout=30)


def test_the_engine_holds_and_logs_the_upnext_constants_at_their_defaults(engine, tmp_path):
    source = SERVER_CONFIG.read_text()
    module = _load("engine_server_config", source)
    held = {name: getattr(module, name, None) for name in EXPECTED_DEFAULTS}
    # The type is part of the default: a 5000.0 would log as "5000.0" and a 0 as "0".
    assert {name: (type(value), value) for name, value in held.items()} == {name: (type(value), value) for name, value in EXPECTED_DEFAULTS.items()}
    assert module.BATCH_SIZE == 48
    pool = getattr(module, "SIMILAR_VIDEO_TARGET_MIN_POOL", None)
    assert (type(pool), pool) == (int, 48)
    personalization = module.RELATED_VIDEOS_PERSONALIZATION
    assert (personalization.get("alpha"), personalization.get("beta")) == (0.7, 0.3)

    # A second batch size separates "is BATCH_SIZE" from "is 48".
    assert source.count(HOME_BATCH_SIZE_LITERAL) == 2
    variant = _load("engine_server_config_batch_64", source.replace(HOME_BATCH_SIZE_LITERAL, '"batch_size": 64,', 1))
    assert variant.BATCH_SIZE == 64
    assert getattr(variant, "SIMILAR_VIDEO_TARGET_MIN_POOL", None) == 64

    deadline = time.time() + LOG_WAIT_SECONDS
    messages = _messages(engine.db_path, UPNEXT_PREFIX)
    while not messages and time.time() < deadline:
        time.sleep(0.1)
        messages = _messages(engine.db_path, UPNEXT_PREFIX)
    assert messages, f"no {UPNEXT_PREFIX!r} line in {engine.db_path} within {LOG_WAIT_SECONDS}s"
    # The fixture retries a failed start into the same log, so "one" is one per start that loaded the index.
    assert len(messages) == len(_messages(engine.db_path, NPROBE_PREFIX)), messages
    for message in messages:
        assert _tokens(message) == sorted(EXPECTED_LOG_TOKENS.items()), message

    # A start at other values separates "logs the module's values" from "logs the defaults".
    variant_log = tmp_path / "variant_engine.log"
    _start_variant(variant_log)
    assert [message.split()[1] for message in _messages(variant_log, NPROBE_PREFIX)] == ["ann_nprobe_configured=25"], variant_log
    variant_messages = _messages(variant_log, UPNEXT_PREFIX)
    assert [_tokens(message) for message in variant_messages] == [sorted(VARIANT_LOG_TOKENS.items())], variant_messages
