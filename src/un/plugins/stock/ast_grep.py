"""The AstGrep tool: structural code search through the `ast-grep` binary. Writes nothing.

`path` is required because parsing a whole tree is expensive. The binary is called as `ast-grep`, never `sg`, which on Linux is util-linux's setgid command.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter

from un import Session, tool, use
from un.plugins.stock.fs import withheld

# rat-tail: duplicates the 120s other tools use rather than importing another plugin.
DEFAULT_TIMEOUT = 120

INSTALL = (
    "ast-grep is not installed, so structural search is unavailable. Install it with "
    "one of:\n"
    "  pixi add --pypi ast-grep-cli\n"
    "  cargo install ast-grep --locked\n"
    "  npm install -g @ast-grep/cli\n"
    "Do not run `sg` instead: on Linux that is util-linux's setgid command."
)

_TEXT = {"type": "string"}

# A refused path containing one of these cannot be excluded exactly, so the call is refused.
_GLOB_META = set("*?[]\\!")


def _run(argv: list[str], path: str, session: Session):
    """One ast-grep spawn against `path`. Only exit 2+ is a failure: `run` and `scan` disagree on the code for no matches."""
    done = subprocess.run(argv + ["--", path], cwd=session.cwd, capture_output=True,
                          text=True, timeout=DEFAULT_TIMEOUT)
    if done.returncode >= 2:
        raise ValueError(f"ast-grep failed: {done.stderr.strip()}")
    return done


def _refused(stdout: str, session: Session) -> dict[str, str]:
    """Each matched path the permission table refuses for AstGrep, mapped to the refusing rule."""
    judge = use("permissions", "denied_path")
    return {hit: rule for hit in stdout.splitlines()
            if (rule := judge(session, "AstGrep", hit))}


@tool(
    "AstGrep",
    "Structural code search: matches on the syntax tree rather than on text, so "
    "`find_user($$$ARGS)` finds that call however it is wrapped or line-broken and does "
    "NOT find the same characters in a comment or a string. Reach for it when what you "
    "are looking for is a SHAPE; `Grep` is better for everything else and is faster. "
    "Name exactly one of `pattern` or `rule`. `pattern` is a single-node search - "
    "metavariables are `$NAME` for one node and `$$$NAME` for many - with `lang` "
    "optional, since the language is inferred from file extensions. `rule` is an inline "
    "YAML rule and is the only way to express a relational or composite query "
    "(`inside`, `has`, `all`, `any`, `not`); put `stopBy: end` on every relational rule "
    "or it stops at the first non-matching node. `path` is required. Read the `ast-grep` "
    "skill before writing anything beyond a bare pattern. Needs the `ast-grep` binary, "
    "and says so plainly when it is missing.",
    {"type": "object",
     "properties": {"pattern": _TEXT, "rule": _TEXT, "lang": _TEXT, "path": _TEXT},
     "required": ["path"]},
)
def ast_grep(*, session: Session, path: str, pattern: str | None = None,
             rule: str | None = None, lang: str | None = None) -> str:
    if (pattern is None) == (rule is None):
        raise ValueError(
            "name exactly one of `pattern` or `rule`: `pattern` is a single-node "
            "search, `rule` is inline YAML for a relational or composite query")
    binary = shutil.which("ast-grep")
    if binary is None:
        return INSTALL
    if pattern is not None:
        argv = [binary, "run", "--pattern", pattern]
        argv += ["--lang", lang] if lang else []
    else:
        argv = [binary, "scan", "--inline-rules", rule]
    # Two passes: list matching files, then search again excluding refused ones, so the binary never opens them.
    first = _run(argv + ["--files-with-matches"], path, session)
    if not first.stdout.strip():
        return "no matches"
    refused = _refused(first.stdout, session)
    if unspellable := [hit for hit in refused if _GLOB_META & set(hit)]:
        # Fails closed, and gives counts only, never the paths.
        raise ValueError(
            "refusing this search: it reaches a file the credential rules refuse whose "
            "name contains a glob character, so it cannot be excluded exactly "
            f"({len(unspellable)} of {len(refused)} refused). Search a narrower path.")
    # `--globs` overrides every other ignore rule, including an inline rule's `files:`.
    exclusions = [arg for hit in refused for arg in ("--globs", f"!{hit}")]
    done = _run(argv + exclusions, path, session)
    shown = done.stdout.strip()
    lines = ([shown] if shown else []) + withheld(Counter(refused.values()))
    # All matches refused answers with the notice alone, never "no matches".
    return "\n".join(lines) if lines else "no matches"
