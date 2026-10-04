import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_55_translate_state_contract_phase4 as cp  # noqa: E402


def test_probe():
    good = ast.parse("HEARTBEAT_SECONDS = 5.0\n# three beats\nHEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)\n")
    (expr,) = cp._assigned_values(good, "HEARTBEAT_FRESH_MS")
    print("good", cp._evaluate(expr, 5.0), type(cp._evaluate(expr, 5.0)).__name__, cp._evaluate(expr, 7.0))
    floaty = ast.parse("HEARTBEAT_FRESH_MS = HEARTBEAT_SECONDS * 3000\n")
    (expr,) = cp._assigned_values(floaty, "HEARTBEAT_FRESH_MS")
    print("floaty", repr(cp._evaluate(expr, 5.0)))
    ignoring = ast.parse("HEARTBEAT_FRESH_MS = 15_000 + HEARTBEAT_SECONDS * 0\n")
    (expr,) = cp._assigned_values(ignoring, "HEARTBEAT_FRESH_MS")
    print("ignoring", repr(cp._evaluate(expr, 7.0)))
    ann = ast.parse("HEARTBEAT_FRESH_MS: int = 15_000\n")
    print("ann", len(cp._assigned_values(ann, "HEARTBEAT_FRESH_MS")))
    handler_ok = ast.parse("from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP\n")
    handler_bad = ast.parse("from server_config import SUBTITLE_QUEUE_CAP\nHEARTBEAT_FRESH_MS = 15_000\n")
    print("ok", cp._stored_names(handler_ok) & cp.HEARTBEAT_NAMES, cp._importing_modules(handler_ok, "HEARTBEAT_FRESH_MS"))
    print("bad", cp._stored_names(handler_bad) & cp.HEARTBEAT_NAMES, cp._importing_modules(handler_bad, "HEARTBEAT_FRESH_MS"))
    print("real worker", cp._stored_names(cp._tree(cp.WORKER)) & cp.HEARTBEAT_NAMES, cp._importing_modules(cp._tree(cp.WORKER), "HEARTBEAT_SECONDS"))
    print("real handler", cp._stored_names(cp._tree(cp.HANDLER)) & cp.HEARTBEAT_NAMES, cp._importing_modules(cp._tree(cp.HANDLER), "HEARTBEAT_FRESH_MS"))
    assert False
