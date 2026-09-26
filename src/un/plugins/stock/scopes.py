"""Per-agent tool scopes: `Tool(x, y)` in an agent's `tools:` grants the tool and bounds what it may reach.

Not an entry point: `subagents.py` imports it. The grammar lives here with the check, so what a scope MEANS is protected along with how it is enforced (ADR-0004). Path and Bash specs go through `permissions.Rule.parse` and its matchers, so a scope reads exactly as the same text reads in `.un/permissions.toml`. The check only narrows: it answers DENY or nothing, and the permission table still judges every call it lets through.
"""

from __future__ import annotations

import re

from un import DENY, Session, Verdict, hook
from un.core import parsed, use
from un.plugins.stock.permissions import (Rule, _fragment_matches, _path_matches, _target,
                                          _widened)

# Scoped by one named argument: the tool -> the argument judged.
NAMED = {"Skill": "name", "Workflow": "name", "SkillManage": "name", "Recall": "name",
         "Task": "subagent_type"}
# Scoped by path globs, judged against the argument the permission table judges.
PATHS = frozenset({"Read", "Write", "Edit", "Glob", "Grep", "AstGrep"})
# One spec per entry, because a Bash spec's own commas separate flags.
COMMAND = "Bash"
SCOPABLE = frozenset(NAMED) | PATHS | {COMMAND}

# A name, then optionally one parenthesised scope holding no parenthesis of its own.
_ENTRY = re.compile(r"([^()]+?)\s*(?:\(([^()]*)\))?")


def _split(text: str) -> list[str]:
    """`text` split at commas outside parentheses, blanks dropped."""
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _spec(tool: str, spec: str) -> str:
    """One spec as stored, or ValueError from `Rule.parse`. A path spec naming a directory covers what is inside it."""
    if tool in NAMED:
        return spec
    rule = Rule.parse(f"{tool}({spec})")
    # Sliced from the widened TEXT: `Rule.spec` drops a leading `!`, which would invert the scope.
    return _widened(rule.text, rule)[len(tool) + 1:-1] if tool in PATHS else spec


def parse(value: str | list) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    """A `tools:` value as (every tool named, scopes by tool). Raises ValueError naming the entry at fault.

    Rejoined before splitting, because yaml's flow list has already split `[A(x, y)]` at the comma.
    """
    items = [value] if isinstance(value, str) else value
    names: set[str] = set()
    bare: set[str] = set()
    scoped_by: dict[str, str] = {}
    scopes: dict[str, tuple[str, ...]] = {}
    for entry in _split(",".join(str(item) for item in items)):
        match = _ENTRY.fullmatch(entry)
        if match is None:
            raise ValueError(f"{entry!r} is neither a tool name nor Tool(scope)")
        tool, inner = match.group(1), match.group(2)
        names.add(tool)
        if inner is None:
            if tool in scoped_by:
                raise ValueError(f"{scoped_by[tool]!r} scopes {tool}, which is also listed "
                                 "bare; keep one")
            bare.add(tool)
            continue
        if tool not in SCOPABLE:
            raise ValueError(f"{entry!r}: {tool} takes no scope; these do: "
                             f"{', '.join(sorted(SCOPABLE))}")
        if tool in bare:
            raise ValueError(f"{entry!r} scopes {tool}, which is also listed bare; keep one")
        specs = [inner.strip()] if tool == COMMAND else _split(inner)
        if not specs or not specs[0]:
            raise ValueError(f"{entry!r} scopes {tool} to nothing")
        try:
            stored = tuple(_spec(tool, spec) for spec in specs)
        except ValueError as exc:
            raise ValueError(f"{entry!r}: {exc}") from None
        scoped_by.setdefault(tool, entry)
        scopes[tool] = scopes.get(tool, ()) + stored
    return frozenset(names), scopes


def _within(session: Session, name: str, specs: tuple[str, ...], args: dict) -> bool:
    """Whether one call falls inside its tool's scope. A Bash call needs EVERY fragment matched."""
    if name in NAMED:
        return str(args.get(NAMED[name]) or "") in specs
    if name == COMMAND:
        rules = [Rule.parse(f"{COMMAND}({spec})") for spec in specs]
        frags = parsed(args.get("command") or "")
        return bool(frags) and all(any(_fragment_matches(rule, frag) for rule in rules)
                                   for frag in frags)
    target = _target(name, args)
    return any(_path_matches(Rule.parse(f"{name}({spec})"), session, target)
               for spec in specs)


@hook("PreToolUse")
def check(*, session: Session, name: str, args: dict) -> Verdict | None:
    """DENY a call to a scoped tool outside the calling agent's scope; no opinion otherwise."""
    if not session.agent:
        return None
    try:
        specs = use("agents", "scopes")(session.agent).get(name)
    except LookupError:
        # The subagents plugin is off, so no agent file declared a scope.
        return None
    if specs is None or _within(session, name, specs, args):
        return None
    return Verdict(DENY, f"{name} is scoped for {session.agent} to: {', '.join(specs)}")
