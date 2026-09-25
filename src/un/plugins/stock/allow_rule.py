#!/usr/bin/env python3
"""Add an allow rule to a project's `.un/permissions.toml`.

What `always` runs when somebody answers an approval question with it. A separate
script rather than an inline write because the file is an operator input that
`docs/adr/0004-enforcement-code-is-immutable.md` puts out of the agent's reach: this is
un acting on a keystroke a person made, not a tool the model can call.

    python -m un.plugins.stock.allow_rule 'Bash(curl)'
    python -m un.plugins.stock.allow_rule 'Bash(curl)' --project ~/code/un_test
    python -m un.plugins.stock.allow_rule 'Read(/etc/**)' --quiet

Idempotent: adding a rule that is already there changes nothing and exits 0.

The write is verified by reading the file back through un's own loader, so a file this
script leaves behind is one `un` will start against. If the verification fails the
original is put back and nothing is kept.

**An allow does not override an OPERATOR'S ask, and does answer un's own.** The table
resolves deny -> ask -> allow(names the path) -> assumed_ask -> allow(program/tool), so a
rule added here does two things: it silences a call the TIER asked about - one no rule
matched - and, when it NAMES THE PATH, it answers an assumed ask, which is un's own
default question about a path nobody configured. `Read(/etc/**)` and `Bash(cat:/etc/hosts)`
name a path; a bare `Bash(cat)` names a program and answers nothing about where. A rule an
operator wrote into the `ask` array is above every allow and stays asking. `--check`
reports what a rule would be, without writing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib

from pathlib import Path

# The array this script writes. The file may carry `deny` and `ask` too; neither is
# something a person should be able to add by answering a question, so neither is
# reachable from here.
KEY = "allow"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 1


def _array_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """The line range of a LIVE `key = [...]`, or None if the file has no live one.

    Live, so the commented `# allow = ["Bash(git:status)"]` the scaffold ships is not
    mistaken for one - that example is the whole reason this cannot just look for the
    key.

    rat-tail: quote tracking is a bare toggle on `"`, with no escape handling. A rule is
    a tool name and a spec - `Read(**/*.[ch])`, `Bash(un:--a*)` - and none of the grammar
    admits a quote, let alone an escaped one. If the grammar ever grows one, this needs a
    real scanner rather than a patch.
    """
    start = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if re.match(rf"\s*{re.escape(key)}\s*=\s*\[", line):
            start = index
            break
    if start is None:
        return None

    depth, quoted = 0, False
    for index in range(start, len(lines)):
        for char in lines[index]:
            if char == '"':
                quoted = not quoted
            elif quoted:
                continue
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return start, index
    raise ValueError(f"{key} array is never closed")


def _render(key: str, rules: list[str]) -> list[str]:
    """One line while it is one rule; a line each once it is more.

    Multi-line early rather than at some width, because this file is edited by hand as
    well as by this script and a growing single line is the shape that stops being
    readable without anyone deciding it should.
    """
    if not rules:
        # Unreachable from `_add`, which only ever appends. `plugin_config` removes, and
        # removing the last name has to leave a key that reads as empty rather than a
        # two-line `key = [` / `]`.
        return [f"{key} = []"]
    if len(rules) == 1:
        return [f"{key} = [{json.dumps(rules[0])}]"]
    return [f"{key} = ["] + [f"    {json.dumps(r)}," for r in rules] + ["]"]


def _insertion_point(lines: list[str]) -> int:
    """Before the first table header, or at the end.

    TOML has no way back to the root table, so a root-level key written after a
    `[section]` belongs to that section instead - which would put the rule somewhere the
    loader does not read while leaving the file perfectly valid. That is the silent
    failure this function exists to prevent.
    """
    for index, line in enumerate(lines):
        if re.match(r"\s*\[", line) and not line.lstrip().startswith("#"):
            return index
    return len(lines)


def _current(path: Path, key: str) -> list[str]:
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    return list(raw.get(key, ()))


def _validated(rule: str) -> None:
    """Parse the rule the way un will. A typo caught here never reaches the file."""
    from un.plugins.stock.permissions import Rule

    Rule.parse(rule)


def _verify(project: Path) -> None:
    """Read the whole file back through un's own loader.

    Not a second `tomllib.loads`: valid TOML is not the bar. The loader checks the key
    names, that every entry is a string, that every rule parses, and that a `Tool(NAME)`
    names something registered - which is the check that catches the realistic mistake,
    and the one that needs the plugins loaded first.
    """
    from un.core import load
    from un.plugins.stock.permissions import read_permissions

    load()
    read_permissions(project)


def set_array(path: Path, key: str, values: list[str]) -> None:
    """Rewrite `key`'s array in `path` and leave every other byte alone.

    The comment-preserving write `docs/adr/0015-config-toml-is-the-source-of-truth.md`
    requires. A live `key = [...]` is replaced in place; where there is none - both
    scaffolds ship their keys commented out as examples - a new one is inserted above the
    first table header, and the commented example survives as the documentation it was
    written to be.

    Public because `un.plugins.stock.plugin_config` writes `.un/config.toml` through it. It
    stays in THIS module rather than moving somewhere more neutrally named: `allow_rule.py`
    is in `permissions._PROTECTED` because it writes the allow array, and relocating the
    write would carry that protection out with it.

    rat-tail: the write is narrower than TOML - single-line arrays at the top level, no
    tables, no multi-line arrays on the way IN. The upgrade path is a real
    comment-preserving round trip, worth buying if a third key ever wants this.
    """
    lines = path.read_text().splitlines() if path.exists() else []
    rendered = _render(key, values)
    span = _array_span(lines, key)

    if span is None:
        at = _insertion_point(lines)
        # A blank line above so the new key does not fuse onto the comment block the
        # scaffold ends with, and one below only when something follows it.
        block = ["", *rendered] if lines else list(rendered)
        if at < len(lines):
            block = [*block, ""]
        lines[at:at] = block
    else:
        lines[span[0]:span[1] + 1] = rendered

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _add(path: Path, rule: str) -> bool:
    """Write the rule in. Returns False when it was already there."""
    rules = _current(path, KEY)
    if rule in rules:
        return False
    set_array(path, KEY, [*rules, rule])
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add an allow rule to a project's .un/permissions.toml.")
    parser.add_argument("rule", help='the rule, e.g. \'Bash(curl)\' or \'Read(/etc/**)\'')
    parser.add_argument(
        "--project", type=Path, default=None,
        help="project root holding .un/ (default: nearest ancestor of the cwd)")
    parser.add_argument(
        "--check", action="store_true",
        help="say whether the rule parses and would take effect; write nothing")
    parser.add_argument("--quiet", action="store_true", help="say nothing on success")
    args = parser.parse_args(argv)

    # Lazily, the way `load` and `Rule` are imported below: this script runs on a
    # keystroke, and `--check` answers without needing `un.core` at all.
    #
    # `un.core.project_root` rather than a copy of the walk. This file carried its own
    # `_project_root` - the same three lines - and plan 11's consistency constraint is one
    # helper used by every consumer, because two walks are only equivalent until somebody
    # changes one. `or Path.cwd()` spells the fallback the deleted copy had built in:
    # `project_root` returns None outside a project, and the refusal below is what turns
    # that into a sentence naming the directory.
    from un.core import project_root, un_dir

    project = (args.project.resolve() if args.project
               else project_root() or Path.cwd())
    path = un_dir(project, "permissions.toml")

    try:
        _validated(args.rule)
    except ValueError as exc:
        print(f"{args.rule!r} is not a rule: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.check:
        print(f"{args.rule} parses; it will silence a call no rule matched, will answer "
              "un's own assumed ask about a path it NAMES, and will not displace an ask "
              "rule an operator wrote")
        return EXIT_OK

    if not path.parent.is_dir():
        print(f"no .un/ under {project}: not an un project", file=sys.stderr)
        return EXIT_USAGE

    original = path.read_text() if path.exists() else None
    try:
        added = _add(path, args.rule)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if not added:
        if not args.quiet:
            print(f"{args.rule} was already allowed in {path}")
        return EXIT_OK

    try:
        _verify(project)
    except Exception as exc:  # noqa: BLE001 - the loader raises several types
        # Put it back. A file this script broke is a project that will not start, and the
        # person who pressed a key to add one rule cannot be expected to repair it.
        if original is None:
            path.unlink()
        else:
            path.write_text(original)
        print(f"{path} rejected {args.rule!r}, so nothing was written: {exc}",
              file=sys.stderr)
        return EXIT_FAILED

    if not args.quiet:
        print(f"allowed {args.rule} in {path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
