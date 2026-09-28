"""The up-next diversity constants, in the Engine's config module and in the Engine's startup log.

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
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ENGINE_SERVER, ENGINE_START_LOCK, ROOT, _free_port, engine  # noqa: E402,F401

SERVER_CONFIG = ROOT / "engine" / "server" / "api" / "server_config.py"
UPNEXT_PREFIX = "[similar-server] upnext_config"
# Logged once by every start that loads the index, at the point where the upnext_config line is logged.
NPROBE_PREFIX = "[similar-server] ann_nprobe_configured="
LOG_WAIT_SECONDS = 5
VARIANT_START_SECONDS = 120
# The home profile's literal comes first in the file; the guest_home profile repeats it.
HOME_BATCH_SIZE_LITERAL = '"batch_size": 48,'
# C1 is a claim about these values (R1, R5), so the operator kept them as literals over hardcoded-spec-mirror: retuning a default is a requirement change that edits this test.
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
    assert {name: (type(value), value) for name, value in held.items()} == {name: (type(value), value) for name, value in EXPECTED_DEFAULTS.items()}  # C1
    assert module.BATCH_SIZE == 48  # C1
    pool = getattr(module, "SIMILAR_VIDEO_TARGET_MIN_POOL", None)
    assert (type(pool), pool) == (int, 48)  # C1
    personalization = module.RELATED_VIDEOS_PERSONALIZATION
    assert (personalization.get("alpha"), personalization.get("beta")) == (0.7, 0.3)  # C1

    # A second batch size separates "is BATCH_SIZE" from "is 48".
    assert source.count(HOME_BATCH_SIZE_LITERAL) == 2
    variant = _load("engine_server_config_batch_64", source.replace(HOME_BATCH_SIZE_LITERAL, '"batch_size": 64,', 1))
    assert variant.BATCH_SIZE == 64
    assert getattr(variant, "SIMILAR_VIDEO_TARGET_MIN_POOL", None) == 64  # C1

    deadline = time.time() + LOG_WAIT_SECONDS
    messages = _messages(engine.db_path, UPNEXT_PREFIX)
    while not messages and time.time() < deadline:
        time.sleep(0.1)
        messages = _messages(engine.db_path, UPNEXT_PREFIX)
    assert messages, f"no {UPNEXT_PREFIX!r} line in {engine.db_path} within {LOG_WAIT_SECONDS}s"  # C2
    # The fixture retries a failed start into the same log, so "one" is one per start that loaded the index.
    assert len(messages) == len(_messages(engine.db_path, NPROBE_PREFIX)), messages  # C2
    for message in messages:
        assert _tokens(message) == sorted(EXPECTED_LOG_TOKENS.items()), message  # C2

    # A start at other values separates "logs the module's values" from "logs the defaults".
    variant_log = tmp_path / "variant_engine.log"
    _start_variant(variant_log)
    assert [message.split()[1] for message in _messages(variant_log, NPROBE_PREFIX)] == ["ann_nprobe_configured=25"], variant_log
    variant_messages = _messages(variant_log, UPNEXT_PREFIX)
    assert [_tokens(message) for message in variant_messages] == [sorted(VARIANT_LOG_TOKENS.items())], variant_messages  # C2
