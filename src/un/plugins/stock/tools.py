"""Drop-in tools registered from `.un/tools/<name>/TOOL.md`: no packaging or entry point. Writes nothing.

un never imports a tool; it spawns the declared script with argv as a list. Discovered at import (like `slash.py`'s file commands) and re-runnable; refusals are collected, not raised. Every tool here is marked `un_from_file`, so the permission table treats it as a stranger and asks on first use until a rule says otherwise.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from un import EXIT_OK, REGISTRY, Session, frontmatter, service, tool

from un.core import DEFAULT_TIMEOUT, RESERVED_TOOL, SLUG, UN_DIR, run_child, scan
from un.plugins.stock.output import CAP_SENTENCE, capped

TOOLS = UN_DIR / "tools"

MANIFEST = "TOOL.md"

# `name` is the agent-facing tool name; `run` is the script.
REQUIRED = ("name", "description", "run")

# Every drop-in takes argv strings; its description tells the model how to call it.
SCHEMA = {
    "type": "object",
    "properties": {"args": {"type": "array", "items": {"type": "string"}}},
}

# Refused directories and why, shown by `un tools` and `/reload`.
REFUSED: dict[str, str] = {}


def _target(here: Path, path: str) -> Path | None:
    """`path` resolved to a file inside the tool directory, or None. Duplicates `skills._target` rather than import a plugin."""
    candidate = (here / path).resolve()
    if not candidate.is_relative_to(here) or candidate == here or candidate.is_dir():
        return None
    return candidate


def _reason(name: str, here: Path, data: dict, error: str | None) -> str | None:
    """Why this directory is not a tool, or None; one distinct message per rule.

    The directory name must be a slug (it is a path segment); the tool name is the author's choice.
    """
    if not SLUG.fullmatch(name):
        return "the directory name must be lowercase letters, digits and hyphens"
    if error:
        return error
    for key in REQUIRED:
        if not str(data.get(key) or "").strip():
            return f"no {key} in its frontmatter"

    tool_name = str(data["name"]).strip()
    if tool_name == RESERVED_TOOL:
        # `core.tool` would raise and stop un starting.
        return (f"the tool name {tool_name!r} is reserved: it is the permission rule "
                "that claims a whole tool by name")
    if tool_name in REGISTRY["tool"]:
        return f"a tool named {tool_name!r} is already registered"

    script = _target(here, str(data["run"]).strip())
    if script is None or not script.is_file():
        return f"run must name a file inside {name}/, and {data['run']!r} does not"
    if not os.access(script, os.X_OK):
        # Executed directly via its shebang, so it must be executable.
        return f"{data['run']!r} is not executable; chmod +x it"
    return None


def _script_tool(script: Path):
    """A registered callable that runs `script` through `run_child` (allowlisted env, tree kill on timeout)."""

    def run(*, session: Session, args: tuple[str, ...] = ()) -> str:
        code, output = run_child([str(script), *args], cwd=session.cwd,
                                 timeout=DEFAULT_TIMEOUT)
        # Cut before the trailer, so the status is never the part omitted and never counted against the cap.
        output = capped(output)
        if code == 0:
            return output or "[no output]"
        # State the failure, or empty output would read as quiet success.
        return f"{output}\n[exit status {code}]".strip()

    return run


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Register every qualifying `.un/tools/<name>/`. Returns (newly registered, refused).

    Takes a path because it runs at import. Re-runnable: `scan` drops the previous scan's tools first, so an edited or deleted directory takes effect. Refusals are keyed by directory name.
    """
    registered: list[str] = []

    def read(where: Path, path: Path, text: str, on) -> str | None:
        here = path.parent
        data, _, error = frontmatter.parse(text)
        if refusal := _reason(here.name, here, data, error):
            return refusal
        name = str(data["name"]).strip()
        tool(name, f"{str(data['description']).strip()} {CAP_SENTENCE}", SCHEMA)(
            _script_tool(_target(here, str(data["run"]).strip())))
        registered.append(name)
        return None

    REFUSED.clear()
    REFUSED.update(scan(root, "tools", TOOLS, f"*/{MANIFEST}", read,
                        key=lambda rel: rel.parent.as_posix()))
    return registered, dict(REFUSED)


@service("tools:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/tools/` for `/reload`."""
    return discover(cwd)


@service("command:tools")
def tools_(args: argparse.Namespace) -> int:
    """list the tools registered from .un/tools/, and any that were refused"""
    discover()

    lines = [f"  {name:<16} {fn.un_meta['description']}"
             for name, fn in sorted(REGISTRY["tool"].items())
             if getattr(fn, "un_from_file", False)]
    print("tools:\n" + "\n".join(lines) if lines else f"no tools in {TOOLS}/")
    if REFUSED:
        print("\nnot registered:\n" + "\n".join(
            f"  {name}: {why}" for name, why in sorted(REFUSED.items())))
    return EXIT_OK


# At import, so tools are in the model's list for the first turn.
discover()
