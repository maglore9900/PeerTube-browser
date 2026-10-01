"""`theme:load`: a skin under `.un/themes/` as a flat dict of name -> string. Writes nothing.

`[roles]` keys are unprefixed; `[glyphs]`, `[decorators]`, `[layout]` and `[labels]` are prefixed with their table name. Imports no renderer, so the data serves any interface. A bad skin is a finding on top of the built-in table, never a failed start.
"""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

from un import service
from un.core import refused, un_dir

# The same file `un install` copies to `.un/themes/default.toml`, so the two cannot drift. Keys name what text is (`tool_result`); values are rich style strings.
BUILT_IN = resources.files("un") / "defaults" / "themes" / "default-theme.toml"


def _built_in() -> dict[str, str]:
    """The shipped roles. Unguarded: a broken shipped file is a broken install and should fail loudly."""
    raw = tomllib.loads(BUILT_IN.read_text(encoding="utf-8"))
    return {k: str(v) for k, v in raw["roles"].items()}


ROLES = _built_in()

DEFAULT = "default"


@service("theme:load")
def load(cwd: Path, name: str = DEFAULT) -> tuple[dict, str | None]:
    """The table for skin `name` layered over the built-in one, and any finding. Never raises.

    `refused` keeps `name` (from config) inside `.un/themes/`.
    """
    if refusal := refused("theme", name):
        return dict(ROLES), f"refused: {refusal}"
    path = un_dir(cwd, "themes") / f"{name}.toml"
    if not path.is_file():
        # The default needs no file; any other missing name is reported.
        return dict(ROLES), None if name == DEFAULT else f"no theme {name!r} at {path}"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return dict(ROLES), f"{path}: {exc}"
    roles = raw.get("roles")
    if not isinstance(roles, dict):
        # Includes an empty file, which parses cleanly.
        return dict(ROLES), f"{path}: no [roles] table"
    # Values coerced to str, since rich raises on a non-string style.
    merged = dict(ROLES) | {k: str(v) for k, v in roles.items()}
    for table in ("glyphs", "decorators", "layout", "labels"):
        if isinstance(extra := raw.get(table), dict):
            merged |= {f"{table}.{k}": str(v) for k, v in extra.items()}
    return merged, None
