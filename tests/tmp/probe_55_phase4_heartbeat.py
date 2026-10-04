"""Probe: print the real timeout-chain values the phase 4 checkpoint reads."""
import importlib
import importlib.util
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("cp4", HERE / "test_55_translate_state_contract_phase4.py")
cp4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp4)


def test_probe():
    budget = importlib.import_module("handlers.internal_translate").REQUEST_BUDGET_SECONDS
    socket_timeout = importlib.import_module("data.source_fetch").SOCKET_TIMEOUT_SECONDS
    client_timeout = importlib.import_module("lib.engine_api_client").TRANSLATE_TIMEOUT_SECONDS
    drains = re.findall(r"^DRAIN_SECONDS=(\d+)$", cp4.DEPLOY.read_text(), re.MULTILINE)
    print(f"budget={budget!r} socket={socket_timeout!r} client={client_timeout!r} drains={drains!r}")
    for text in ("DRAIN_SECONDS=30\n    --drain) DRAIN_SECONDS=\"${2:-}\"; shift 2 ;;\n", "DRAIN_SECONDS=\"30\"\n", "DRAIN_SECONDS=30\nDRAIN_SECONDS=45\n"):
        print(repr(text), re.findall(r"^DRAIN_SECONDS=(\d+)$", text, re.MULTILINE))
    assert False, "print"
