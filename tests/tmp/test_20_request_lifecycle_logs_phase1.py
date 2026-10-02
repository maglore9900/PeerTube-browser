"""A record's `structured_context` extra is its Engine log context verbatim, and the Engine's and the Client's `resolve_request_id` apply one id rule.

- A child logs four records through `configure_engine_logging("verbose")`: `[request.start] request started` with request_id `rid-a` and a context whose `user_agent` is `Mozilla/5.0 (X11; Linux x86_64)`; `[probe] k=v other=w` with context `{"note": "a b=c", "count": 3}`; the same message with no extra; `[probe] crlf` with a `user_agent` holding CR/LF. With `LOG_FORMAT` unset, each `context` equals the given dict, the int included and the message's own `k=v` tokens not merged in; the extra-less record still gets `{"k": "v", "other": "w"}`; the first record's keys are `ts, level, event, message, modes, request_id, context` in that order.
- With `LOG_FORMAT=text` stderr is exactly four lines: the first ends `request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux x86_64) request_id=rid-a`, the second is `… [probe] k=v other=w note=a b=c count=3`, the third keeps today's `… [probe] k=v other=w k=v other=w`, and the CR/LF one reads `user_agent=evil\\r\\nINFO forged` as escaped characters.
- Both request_context modules, loaded by file path: equal `REQUEST_ID_HEADER` and `REQUEST_ID_PATTERN`; each resolver returns `a`, 64×`a`, a 32-hex id, `probe.id-1` and `v1.A_Z-09` verbatim, and for None, "", " ", "abc\\n", "a b", 65×`a`, "é", "a/b", "[x]", "abc\\r\\nX: y" and "abc " returns a 32-hex value that is not the input, distinct across those calls.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "engine" / "server" / "api"
CLIENT_LIB_DIR = ROOT / "client" / "backend" / "lib"
TS_HEAD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z ")
HEX32_RE = re.compile(r"[0-9a-f]{32}")

START_CONTEXT = {"ip": "127.0.0.1", "method": "GET", "url": "http://x/a", "user_agent": "Mozilla/5.0 (X11; Linux x86_64)"}
PROBE_CONTEXT = {"note": "a b=c", "count": 3}
CRLF_CONTEXT = {"user_agent": "evil\r\nINFO forged"}

# Logs four records through the production setup; LOG_FORMAT comes only from the env the test gives the child.
_STRUCTURED_CHILD = textwrap.dedent(
    """
    import json, logging, sys
    from logging_profiles import configure_engine_logging
    start, probe, crlf = json.loads(sys.argv[1])
    configure_engine_logging("verbose")
    logging.info("[request.start] request started", extra={"structured_context": start, "request_id": "rid-a"})
    logging.info("[probe] k=v other=w", extra={"structured_context": probe})
    logging.info("[probe] k=v other=w")
    logging.info("[probe] crlf", extra={"structured_context": crlf})
    """
)

ACCEPTED_IDS = ["a", "a" * 64, "0123456789abcdef0123456789abcdef", "probe.id-1", "v1.A_Z-09"]
REJECTED_IDS = [None, "", " ", "abc\n", "a b", "a" * 65, "é", "a/b", "[x]", "abc\r\nX: y", "abc "]


def _run_structured_child(value: str | None) -> subprocess.CompletedProcess:
    """Run the four-record child with LOG_FORMAT removed from the env, then set to value when it is not None."""
    env = {key: item for key, item in os.environ.items() if key != "LOG_FORMAT"}
    if value is not None:
        env["LOG_FORMAT"] = value
    contexts = json.dumps([START_CONTEXT, PROBE_CONTEXT, CRLF_CONTEXT])
    return subprocess.run([sys.executable, "-c", _STRUCTURED_CHILD, contexts], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=120)


def _json_object(line: str) -> dict | None:
    """The line parsed as a JSON object, or None."""
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _load(name: str, path: Path):
    """Import the module at path under name without touching sys.path, so the Engine's and the Client's modules cannot shadow each other."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_structured_context_is_the_json_context_verbatim():
    run = _run_structured_child(None)
    assert run.returncode == 0, run.stderr[-2000:]
    lines = run.stderr.splitlines()
    payloads = [_json_object(line) for line in lines]
    # Control: four records reached stderr through the production formatter, none through logging.lastResort.
    assert len(lines) == 4 and all(payload is not None for payload in payloads), run.stderr[-2000:]
    start, probe, plain, crlf = payloads

    # Before this phase the record had no context at all: its message holds no key=value token (observed).
    assert start.get("context") == START_CONTEXT, start  # C1
    # A whitespace split would cut the user agent at "Mozilla/5.0"; the key order of the given dict is kept too.
    assert list(start["context"].items()) == list(START_CONTEXT.items()), start  # C1
    assert start["request_id"] == "rid-a", start  # C1
    # Key order included: the watcher and the runbooks read this payload.
    assert list(start) == ["ts", "level", "event", "message", "modes", "request_id", "context"], start  # C1
    # In place of the message's tokens, not merged with them: today this is {"k": "v", "other": "w"}; the int stays an int.
    assert probe.get("context") == PROBE_CONTEXT, probe  # C1
    # A record without the extra still has its message split into key=value fields.
    assert plain.get("context") == {"k": "v", "other": "w"}, plain  # C1
    assert crlf.get("context") == CRLF_CONTEXT, crlf  # C1


def test_structured_context_renders_whole_on_one_escaped_text_line():
    run = _run_structured_child("text")
    assert run.returncode == 0, run.stderr[-2000:]
    # splitlines breaks on CR as well as LF, so an unescaped CR or LF from the context adds a line here.
    lines = run.stderr.splitlines()
    assert len(lines) == 4, lines  # C1
    assert all(TS_HEAD_RE.match(line) for line in lines), lines
    assert all(_json_object(line) is None for line in lines), lines
    start, probe, plain, crlf = (TS_HEAD_RE.sub("", line, count=1) for line in lines)

    # The event and message prefix are left to phase 2's rename; the context tokens follow the message and precede request_id.
    assert start.startswith("INFO ") and start.endswith(" request started ip=127.0.0.1 method=GET url=http://x/a user_agent=Mozilla/5.0 (X11; Linux x86_64) request_id=rid-a"), start  # C1
    assert probe == "INFO probe.info [probe] k=v other=w note=a b=c count=3", probe  # C1
    # Unchanged from before this phase (observed).
    assert plain == "INFO probe.info [probe] k=v other=w k=v other=w", plain  # C1
    # CR and LF written as the two characters backslash-r and backslash-n.
    assert crlf == "INFO probe.info [probe] crlf user_agent=evil\\r\\nINFO forged", crlf  # C1


def test_engine_and_client_resolve_request_id_by_the_same_rule():
    engine = _load("engine_request_context", API_DIR / "request_context.py")
    client = _load("client_request_context", CLIENT_LIB_DIR / "request_context.py")

    assert engine.REQUEST_ID_HEADER == client.REQUEST_ID_HEADER, (engine.REQUEST_ID_HEADER, client.REQUEST_ID_HEADER)  # C2
    assert engine.REQUEST_ID_PATTERN == client.REQUEST_ID_PATTERN, (engine.REQUEST_ID_PATTERN, client.REQUEST_ID_PATTERN)  # C2

    for module in (engine, client):
        # 64 is the upper bound; nginx's $request_id is the 32-hex sample.
        assert [module.resolve_request_id(value) for value in ACCEPTED_IDS] == ACCEPTED_IDS, module.__name__  # C2

        resolved = [module.resolve_request_id(value) for value in REJECTED_IDS]
        # re.match with ^…$ passes "abc\n", \w passes "é", {1,65} passes 65×a, a strip passes "abc " as "abc".
        assert all(HEX32_RE.fullmatch(out) for out in resolved), (module.__name__, list(zip(REJECTED_IDS, resolved)))  # C2
        assert all(out != value for value, out in zip(REJECTED_IDS, resolved)), (module.__name__, resolved)  # C2
        # Fresh per call: a constant fallback id gives one value for all of them.
        assert len(set(resolved)) == len(REJECTED_IDS), (module.__name__, resolved)  # C2
