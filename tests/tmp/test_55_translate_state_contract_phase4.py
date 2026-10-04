"""Phase 4 checkpoint of plan 55: the translate worker's heartbeat interval and the Engine's freshness window are defined once, in engine/server/api/server_config.py, and the translate timeouts across Engine, Client and deploy script stay in order.

- Heartbeat (C1): server_config.py's source holds exactly one HEARTBEAT_FRESH_MS assignment, its expression names HEARTBEAT_SECONDS, and evaluated in the module's own namespace it gives 15000 (an int, the module's value) with the real interval and 21000 with 7.0. The handler module's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal. Neither internal_translate.py nor translate-worker.py binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself; the handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module.
- Timeout chain (C2): the handler's REQUEST_BUDGET_SECONDS plus data.source_fetch's SOCKET_TIMEOUT_SECONDS is below lib.engine_api_client's TRANSLATE_TIMEOUT_SECONDS, which is below the DRAIN_SECONDS default that scripts/deploy-bluegreen.sh assigns on exactly one line of its own.

Behaviour at the 15 000 / 15 001 ms edges is test_internal_translate.py's BEATS claim, and the worker's beat is test_translate_worker.py's; this file claims only where the numbers come from and how they relate.
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
BACKEND_DIR = ROOT / "client" / "backend"
# The order conftest and test_internal_translate.py leave: the Engine's dirs ahead of the Client's, so `data` is the Engine's and `lib` the Client's.
for _path in (BACKEND_DIR, SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

SERVER_CONFIG = API_DIR / "server_config.py"
HANDLER = API_DIR / "handlers" / "internal_translate.py"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
DEPLOY = ROOT / "scripts" / "deploy-bluegreen.sh"
HEARTBEAT_NAMES = {"HEARTBEAT_SECONDS", "HEARTBEAT_FRESH_MS"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _assigned_values(tree: ast.Module, name: str) -> list[ast.expr]:
    """The value expression of every assignment to `name`, plain or annotated, anywhere in the module."""
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
            values.append(node.value)
    return values


def _stored_names(tree: ast.Module) -> set[str]:
    """Every name the module binds by assignment, augmented assignment, unpacking, loop or with target."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}


def _importing_modules(tree: ast.Module, name: str) -> set[str]:
    """The modules a `from X import` binds `name` from, under its own name."""
    return {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names if (alias.asname or alias.name) == name}


def _evaluate(expression: ast.expr, heartbeat_seconds: float) -> object:
    """The expression's value in server_config's own namespace with HEARTBEAT_SECONDS replaced, so a derivation through other module names still evaluates."""
    import server_config

    namespace = {**vars(server_config), "HEARTBEAT_SECONDS": heartbeat_seconds}
    return eval(compile(ast.Expression(expression), str(SERVER_CONFIG), "eval"), namespace)


def test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it():
    import server_config

    values = _assigned_values(_tree(SERVER_CONFIG), "HEARTBEAT_FRESH_MS")
    assert len(values) == 1, f"server_config.py assigns HEARTBEAT_FRESH_MS {len(values)} times; expected exactly once"  # C1
    (expression,) = values
    assert "HEARTBEAT_SECONDS" in {node.id for node in ast.walk(expression) if isinstance(node, ast.Name)}, ast.unparse(expression)  # C1: derived from the interval, not a literal
    real = _evaluate(expression, server_config.HEARTBEAT_SECONDS)
    assert real == 15000 and type(real) is int, (ast.unparse(expression), real)  # C1: the real interval gives today's window, as an int
    assert server_config.HEARTBEAT_FRESH_MS == real  # control: the evaluated expression is the module's value
    # A wrong derivation that names the interval but ignores it (`int(15_000 + HEARTBEAT_SECONDS * 0)`) still gives an int 15000 above; another interval tells them apart.
    assert _evaluate(expression, 7.0) == 21000, ast.unparse(expression)  # C1

    handler = importlib.import_module("handlers.internal_translate")
    # Identity, not equality: a handler literal 15_000 equals the derived value but is a different int object (observed in the probe).
    assert handler.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS  # C1

    for path, imported in ((HANDLER, "HEARTBEAT_FRESH_MS"), (WORKER, "HEARTBEAT_SECONDS")):
        tree = _tree(path)
        assert _stored_names(tree) & HEARTBEAT_NAMES == set(), f"{path.name} binds {sorted(_stored_names(tree) & HEARTBEAT_NAMES)} itself"  # C1
        assert _importing_modules(tree, imported) == {"server_config"}, f"{path.name} imports {imported} from {sorted(_importing_modules(tree, imported), key=str)}"  # C1


def test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain():
    budget = importlib.import_module("handlers.internal_translate").REQUEST_BUDGET_SECONDS
    socket_timeout = importlib.import_module("data.source_fetch").SOCKET_TIMEOUT_SECONDS
    client_timeout = importlib.import_module("lib.engine_api_client").TRANSLATE_TIMEOUT_SECONDS
    # Line-anchored, so the `--drain) DRAIN_SECONDS="${2:-}"` override and the validation line do not count.
    drains = re.findall(r"^DRAIN_SECONDS=(\d+)$", DEPLOY.read_text(), re.MULTILINE)
    assert len(drains) == 1, f"deploy-bluegreen.sh has {len(drains)} DRAIN_SECONDS default lines: {drains}"
    drain = int(drains[0])
    assert budget + socket_timeout < client_timeout, (budget, socket_timeout, client_timeout)  # C2
    assert client_timeout < drain, (client_timeout, drain)  # C2
