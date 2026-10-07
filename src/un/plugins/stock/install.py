"""The `un install` verb: scaffold `.un/`, its config files, and a starter `AGENTS.md`.

Idempotent and non-destructive: existing files and directories are never overwritten, and an existing `config.toml` only gains the keys it lacks, commented out beneath their documentation, inside its own tables where it has them. Static content is read from `un/defaults/` (see `DATA_FILES`); the `[permissions]` and `[sandbox]` sections of `config.toml` are rendered from the permission tables on each run so they cannot drift. Linux only.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import sys
import textwrap
import tomllib
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import NamedTuple

import un
from un import EXIT_FAILED, EXIT_OK, EXIT_USAGE, REGISTRY, service
from un.core import UN_DIR, project_root
# The module, so the policy tables are read live.
from un import core

# Directory name -> what reads it.
DIRECTORIES = {
    "sessions": "transcripts, written by session_transcripts",
    "memory": "<name>.md per fact plus the MEMORY.md index, written by the remember tool",
    "rules": "*.md operator rules, read by rules",
    "skills": "<name>/SKILL.md, read by skills; the curator's state lives in .un/learning/",
    "agents": "<name>.md subagent definitions, read by subagents",
    "commands": "<name>.md prompt commands at any depth, path-named, read by commands",
    "hooks": "<name>.md plus the script it names, read by hooks",
    "themes": "<name>.toml role tables, read by theme",
    "tools": "<name>/TOOL.md plus the script it names, read by tools",
    "workflows": "a .py at any depth declaring its name in a YAML header, driving the agent with exit-code gates, read by workflows",
    "oauth": "<name>.credentials.json per issuer, written by un login",
}


def _toml(value: bool) -> str:
    return "true" if value else "false"


# Scaffolded as `.un/banner.txt` so it can be replaced; `repl.py` holds the same mark as its fallback.
BANNER = """\
                __       __   __
 __ _____  ___ / /____ _/ /  / /__
/ // / _ \\(_-</ __/ _ `/ _ \\/ / -_)
\\_,_/_//_/___/\\__/\\_,_/_.__/_/\\__/
                   __
  ___  __ ____ _  / /  ___ ____
 / _ \\/ // /  \' \\/ _ \\/ -_) __/
/_//_/\\_,_/_/_/_/_.__/\\__/_/
"""

PERMISSIONS = """\
# Operator permission rules for un.
#
# Only the rules YOU write. The built-in table is not repeated here - it is toggled by the booleans in the [permissions] section of .un/config.toml, and anything in this file is ADDED to whatever those leave in place.
#
# The grammar is Tool(spec):
#
#   Bash(PROGRAM)              the program, whatever arguments it carries
#   Bash(PROGRAM:-f,--flag)    ...only when it carries those flags
#   Read(GLOB), Write(GLOB)    a path, globbed; a leading ! inverts it
#   Tool(NAME)                 a whole registered tool, by its registered name
#
# A path spec with no glob in it covers the path it names AND everything beneath it, so Write(src) is Write(src/**) and you do not type the stars yourself. Write a glob and it is used exactly as you wrote it.
#
# A Write rule also claims Edit on the same path, in all three arrays. Not the reverse: an Edit needs the file to already exist, where a Write creates and truncates one.
#
# A deny overrides ask, and ask overrides an allow whatever order they are written in. An allow written here cannot displace a built-in deny.
#   Deny > Ask > Allow
#
# Warning: An unparseable rule, or one naming an unregistered tool, stops un from starting and names this file.
# For example, you have set a permission for a built in tool that doesn't exist or no longer exists because you disabled the plugin.
#
# Examples:
# allow = ["Bash(ps -aef)"]
# ask = ["Write(**/migrations/**)"]
# deny = ["Bash(curl)",]
#
# Trailing commas are fine.

allow = []
ask = []
deny = []
"""

AGENTS = """\
# AGENTS.md

How to work in this repo. Replace this file with what an agent needs to know
before it touches anything here: the commands that build and test, the
conventions that are not obvious from the code, and what to leave alone.

`un` injects this file into the system prompt of every session, once, exactly as
written. Text left here unedited is text the model reads every run.

Standing instructions that should be repeated as a session goes on belong in
`.un/rules/*.md` instead, where each file says in its own frontmatter when it
fires, which conversations it applies to, and which message carries it.
"""

# `.un/` holds transcripts; keep it to the owning account.
UN_DIR_MODE = 0o700

DEFAULTS = resources.files("un") / "defaults"

# Target under `.un/` -> source file under `defaults/`.
DATA_FILES = {
    # Written with the rendered sections appended, not verbatim.
    "config.toml": "default-config.toml",
    # Copied so the operator can update stale prices; `context.py` falls back to the packaged one.
    "models.toml": "models.toml",
    "commands/learn.md": "commands/learn-command.md",
    "commands/apply-amendment.md": "commands/apply-amendment-command.md",
    "skills/skill-authoring/SKILL.md": "skills/skill-authoring-skill.md",
    "skills/ast-grep/SKILL.md": "skills/ast-grep-skill.md",
    "skills/workflow-authoring/SKILL.md": "skills/workflow-authoring-skill.md",
    # A subdirectory keeps seeded agents apart from the operator's; discovery recurses.
    "agents/learning/detector.md": "agents/detector-agent.md",
    "agents/learning/admitter.md": "agents/admitter-agent.md",
    "agents/learning/implementor.md": "agents/implementor-agent.md",
    "agents/learning/accuracy-auditor.md": "agents/accuracy-auditor-agent.md",
    "agents/learning/memory-editor.md": "agents/memory-editor-agent.md",
    "agents/learning/amendment-applier.md": "agents/amendment-applier-agent.md",
    # Docs for the operator; not in `DIRECTORIES`, which lists what loaders read.
    "docs/subagent-example.md": "subagent-template.md",
    "docs/how-to-write-a-skill.md": "howto/howto-skill.md",
    "docs/how-to-write-a-hook.md": "howto/howto-hook.md",
    "docs/how-to-write-an-agent.md": "howto/howto-agent.md",
    "docs/how-to-write-a-rule.md": "howto/howto-rule.md",
    "docs/how-to-write-a-plugin.md": "howto/howto-plugin.md",
    "docs/how-to-write-a-tool.md": "howto/howto-tool.md",
    "docs/how-to-write-a-theme.md": "howto/howto-theme.md",
    "docs/how-to-write-a-workflow.md": "howto/howto-workflow.md",
    # `default-theme.toml` is also `theme.py`'s built-in table.
    "themes/default.toml": "themes/default-theme.toml",
    "themes/nord.toml": "themes/nord-theme.toml",
    "themes/ember.toml": "themes/ember-theme.toml",
    "themes/mono.toml": "themes/mono-theme.toml",
    "themes/tactical.toml": "themes/tactical-theme.toml",
    "themes/analog.toml": "themes/analog-theme.toml",
}

# Shipped defaults read in place and never scaffolded: `context.py` reads the summary prompt from the package, and `.un/compaction.md` overrides it only when the operator writes one.
SHIPPED_ONLY = ("compaction.md",)


def _permissions_section() -> str:
    """The `[permissions]` table rendered from `POLICIES`: one key per togglable policy, with its rules and note as comments.

    Appended after the template, since TOML has no way back to the root table.
    """
    lines = [
        "",
        "# --------------------------Permissions--------------------------------",
        "# Below are un default permissions that are established in the base code so you do not need to do so in permissions.toml.",
        "# They can be disabled/enabled below. Please read the justification for their current setting, changing settings introduces risk.",
        "[permissions]",
        "",
        "# Allow everything the table did not DENY, including calls no rule matched.",
        "# Leaving it false means strict still asks about those.",
        f"dangerous_allow = {_toml(core.DEFAULT_TOGGLES['dangerous_allow'])}",
    ]
    for policy in core.POLICIES:
        if not policy.toggle:
            continue
        lines.append("")
        lines.append(f"# {policy.why}:")
        lines.extend(f"#   {rule}" for rule in policy.rules)
        if policy.note:
            lines.append("#")
            lines.extend(f"# {line}" for line in textwrap.wrap(policy.note, 74))
        lines.append(
            f"{policy.name} = {_toml(core.DEFAULT_TOGGLES[policy.name])}")
    return "\n".join(lines) + "\n"


def _sandbox_section() -> str:
    """The `[sandbox]` table rendered from `SANDBOX_POLICIES`, disabled by default."""
    lines = [
        "",
        "# ----------------------------Sandbox----------------------------------",
        "# Mode 1 denies the paths below outright, which is what survives dangerous_allow:",
        "# that setting widens every ask to an allow and leaves a deny as it is.",
        "# It does not contain code execution: an agent that can run `python3.12 -c`, or",
        "# write a script and run it, is not confined by it. See docs/wiki/un/sandbox.md.",
        "[sandbox]",
        "",
        "# Off by default. Nothing below is enforced until this is true.",
        f"enabled = {_toml(core.DEFAULT_SANDBOX['enabled'])}",
        "",
        "# 1 = un's own rules deny the areas below. 2 is reserved for an external sandbox",
        "# provider and is not implemented; an enabled sandbox at mode 2 refuses to start.",
        f"mode = {core.DEFAULT_SANDBOX['mode']}",
    ]
    for policy in core.SANDBOX_POLICIES:
        lines.append("")
        lines.append(f"# {policy.why}:")
        lines.append(
            f"{policy.name} = {_toml(core.DEFAULT_SANDBOX[policy.name])}")
    return "\n".join(lines) + "\n"


# The template's own conventions: `[table]` or `# [table]`, and `key = ...` or `# key = ...` with at most one space after the `#`, so indented doc lines are prose. A key starts with a letter, so "# 1 = un's own rules..." is prose too.
_TABLE_LINE = re.compile(r"#? ?\[{1,2}\s*([^\[\]]+?)\s*\]{1,2}\s*$")
_KEY_LINE = re.compile(r"#? ?([A-Za-z][A-Za-z0-9_-]*)\s*=")
# Any assignment in the operator's file, commented, indented or dotted; only the key's name is kept.
_ASSIGNED = re.compile(r"[#\s]*(?:[A-Za-z0-9_-]+\s*\.\s*)*([A-Za-z][A-Za-z0-9_-]*)\s*=")

MISSING_BANNER = """
# ------------------------Added by un install--------------------------
# Keys un ships in tables this file does not have yet, with their documentation, all commented out.
# To use one, uncomment it together with its [table] line. A key whose table this file already has was put inside that table instead.
"""


def missing_keys(rendered: str, existing: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(`table.key` for each key of `rendered` whose name `existing` never assigns, (table, commented paragraph) for each paragraph documenting one, "" for the root). A paragraph's own `[table]` line is left out. A table with a segment ending in `_name`, such as `agents.agent_name`, is an example and offers no key.

    rat-tail: presence is by NAME in any table, so a new key sharing a name assigned elsewhere is never offered; table-path presence is the upgrade.
    """
    assigned = {m.group(1) for line in existing.splitlines() if (m := _ASSIGNED.match(line))}
    table, keys, found = "", [], []
    for paragraph in (p.splitlines() for p in re.split(r"\n\s*\n", rendered) if p.strip()):
        home, kept = None, []
        for line in paragraph:
            if match := _TABLE_LINE.match(line):
                table = match.group(1)
                continue
            if ((match := _KEY_LINE.match(line)) and match.group(1) not in assigned
                    and not any(part.endswith("_name") for part in table.split("."))):
                keys.append(f"{table}.{match.group(1)}" if table else match.group(1))
                home = table
            kept.append(line if line.startswith("#") else f"# {line}")
        if home is not None:
            found.append((home, kept))
    return keys, found


def _insertion_points(lines: list[str]) -> dict[str, int]:
    """Where a key goes in each LIVE table of `lines`, "" for the root: after the region's last non-blank line, ahead of the comments directly above the next header, which belong to that header. A table repeated in the file keeps its first.

    rat-tail: a line scan, not a parse. A table only dotted keys or an inline table define has no header, so its keys go to the bottom block, and an array continuation line starting with `[` reads as a header; a TOML tokenizer is the upgrade.
    """
    headers = [(i, m.group(1)) for i, line in enumerate(lines)
               if not line.lstrip().startswith("#") and (m := _HEADER.match(line.strip()))]
    points: dict[str, int] = {}
    for (start, name), stop in zip([(-1, "")] + headers, [i for i, _ in headers] + [len(lines)]):
        end = stop
        if stop < len(lines):
            while end - 1 > start and lines[end - 1].lstrip().startswith("#"):
                end -= 1
        while end - 1 > start and not lines[end - 1].strip():
            end -= 1
        points.setdefault(name, end)
    return points


def _add_missing(config: Path, rendered: str) -> list[str]:
    """Add to `config`, commented, each key `rendered` has and it lacks: inside its table when `config` has that table, above the first table for a root key, else at the bottom; the keys added. A config that is not UTF-8 is named on stderr and left alone."""
    try:
        before = config.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"un install cannot read {UN_DIR}/config.toml to compare its keys: {exc}", file=sys.stderr)
        return []
    keys, paragraphs = missing_keys(rendered, before)
    if not keys:
        return keys
    lines = (before if not before or before.endswith("\n") else before + "\n").splitlines(keepends=True)
    points = _insertion_points(lines)
    inside: dict[int, list[list[str]]] = {}
    bottom, last = [], None
    for table, paragraph in paragraphs:
        if table in points:
            inside.setdefault(points[table], []).append(paragraph)
        else:
            bottom.append(([f"# [{table}]"] if table != last else []) + paragraph)
            last = table
    # Bottom-up, so an insertion never moves an index still to be used.
    for index in sorted(inside, reverse=True):
        block = "\n\n".join("\n".join(p) for p in inside[index]) + "\n"
        trail = "\n" if index < len(lines) and lines[index].strip() else ""
        lines[index:index] = [("\n" if index else "") + block + trail]
    text = "".join(lines)
    if bottom:
        text += MISSING_BANNER + "\n" + "\n\n".join("\n".join(p) for p in bottom) + "\n"
    # A whole-file rewrite, so a spare and a rename: a crash leaves the old file or the new.
    spare = config.with_name(f".{config.name}.{os.getpid()}")
    spare.write_text(text, encoding="utf-8")
    shutil.copymode(config, spare)
    os.replace(spare, config)
    return keys


# Tool -> (the binary it spawns, what the tool is without it). Reported only while the tool is registered, so a disabled plugin is not named.
# rat-tail: held here because install imports no plugin; a per-plugin declaration read off the live module is the upgrade when an aftermarket plugin needs one.
SYSTEM_PACKAGES = {
    "GitRo": ("git", "unavailable - git is not on PATH"),
    "AstGrep": ("ast-grep", "unavailable - ast-grep is not on PATH; it comes with un's environment, so run un inside `pixi run` or `pixi shell`"),
    "Grep": ("rg", "degraded - rg (ripgrep) is not on PATH, so Grep falls back to a slower walk"),
}


def _missing_packages() -> None:
    """Name each registered tool whose binary is missing, and wait for Enter when someone is at the terminal."""
    missing = [f"{name}: {lost}" for name, (binary, lost) in SYSTEM_PACKAGES.items()
               if name in REGISTRY["tool"] and shutil.which(binary) is None]
    if not missing:
        return
    print("\nsystem packages missing:")
    for line in missing:
        print(f"  {line}")
    # A piped install has nobody to answer, as in `cli._confirm_stock`.
    if sys.stdin.isatty():
        print("press Enter to acknowledge ", end="", flush=True)
        sys.stdin.readline()


def _supported() -> bool:
    """rat-tail: linux only, because `UN_DIR_MODE` means nothing on Windows; lifting it needs a Windows way to protect `.un/sessions/`."""
    return sys.platform.startswith("linux")


CACHES = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})


def _owned(rel: Path) -> bool:
    """Whether un owns this path under src/un: everything but caches and each plugins/<name>/ other than stock, which is a third party's."""
    parts = rel.parts
    if CACHES.intersection(parts) or rel.suffix in (".pyc", ".pyo"):
        return False
    return not (len(parts) > 2 and parts[0] == "plugins" and parts[1] != "stock")


def _owned_files(package: Path) -> dict[Path, Path]:
    """Relative path -> file, for every owned file under `package`. Symlinked directories are not followed."""
    found = {}
    for folder, dirs, files in os.walk(package):
        dirs[:] = [d for d in dirs if d not in CACHES]
        for name in files:
            path = Path(folder, name)
            if _owned(rel := path.relative_to(package)):
                found[rel] = path
    return found


# Tables of an exported runtime's pyproject.toml that un owns; every other table is the user's.
OWNED_TABLES = frozenset({"project", "project.scripts", 'project.entry-points."un.plugins.stock"',
                          "build-system", "tool.hatch.build.targets.wheel"})

_HEADER = re.compile(r"\[{1,2}\s*([^\[\]]+?)\s*\]{1,2}\s*(?:#.*)?$")


def _segments(text: str) -> list[tuple[str | None, str]]:
    """(table name, text) runs: the preamble, then each header with the comment lines directly above it and every line below it."""
    runs: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines(keepends=True):
        if match := _HEADER.match(line.strip()):
            above = runs[-1][1]
            carried: list[str] = []
            while above and above[-1].lstrip().startswith("#"):
                carried.insert(0, above.pop())
            runs.append((match.group(1), carried + [line]))
        else:
            runs[-1][1].append(line)
    return [(name, "".join(lines)) for name, lines in runs]


_NAME = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


def _dependency_key(entry: str) -> str:
    """The entry's PEP 508 name, normalised as pip compares names; an entry with no readable name keys on its whole text."""
    match = _NAME.match(entry)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else entry


class Dependencies(NamedTuple):
    merged: list[str]
    added: list[str]
    repinned: list[str]
    kept: list[str]


def merge_dependencies(runtime: list[str], checkout: list[str]) -> Dependencies:
    """The checkout's entries in its order, then each runtime entry whose name the checkout lacks, in the runtime's order."""
    mine = {_dependency_key(e): e for e in runtime}
    theirs = {_dependency_key(e) for e in checkout}
    kept = [e for e in runtime if _dependency_key(e) not in theirs]
    return Dependencies(checkout + kept,
                        [e for e in checkout if _dependency_key(e) not in mine],
                        [e for e in checkout if mine.get(_dependency_key(e), e) != e],
                        kept)


def _declared(pyproject: str) -> list[str]:
    return tomllib.loads(pyproject).get("project", {}).get("dependencies", [])


_DEPENDENCIES = re.compile(r"^[ \t]*dependencies[ \t]*=[ \t]*", re.M)


def _with_dependencies(segment: str, entries: list[str]) -> str:
    """A `[project]` segment with its dependencies value replaced by `entries` on one line, or that line appended when it has none."""
    # A JSON string is a valid TOML basic string.
    value = "[" + ", ".join(json.dumps(e) for e in entries) + "]"
    match = _DEPENDENCIES.search(segment)
    if match is None:
        body = segment.rstrip("\n")
        return f"{body}\ndependencies = {value}{segment[len(body):]}"
    start = match.end()
    # rat-tail: tries each "]" until the array parses, quadratic in its length; a TOML tokenizer if a list ever runs to thousands.
    for end in (i + 1 for i in range(start, len(segment)) if segment[i] == "]"):
        try:
            tomllib.loads("v = " + segment[start:end])
        except tomllib.TOMLDecodeError:
            continue
        return segment[:start] + value + segment[end:]
    raise tomllib.TOMLDecodeError("[project].dependencies has no closing ]", segment, start)


def merge_pyproject(target: str, source: str, dependencies: list[str] | None = None) -> str:
    """`target` with each owned table swapped for `source`'s, byte for byte everywhere else; `dependencies`, when given, replaces `source`'s list.

    Text rather than parse-and-emit: there is no stdlib TOML writer, and the comments are what explain each line.
    """
    theirs = {name: text for name, text in _segments(source) if name in OWNED_TABLES}
    if dependencies is not None and "project" in theirs:
        theirs["project"] = _with_dependencies(theirs["project"], dependencies)
    out: list[str] = []
    seen = set()
    for name, text in _segments(target):
        if name in OWNED_TABLES:
            seen.add(name)
            text = theirs.get(name, "")
        out.append(text)
    for name, text in theirs.items():
        if name not in seen:
            merged = "".join(out)
            out.append(("" if not merged or merged.endswith("\n\n") else
                        "\n" if merged.endswith("\n") else "\n\n") + text)
    return "".join(out)


# Read at call time so tests can repoint it; the image creates it root-owned on a read-only root.
CONTAINER_MARKER = Path("/etc/un-container")

# rat-tail: a hand copy of VERBATIM in scripts/export_runtime.py (and .gitignore's container block), since scripts/ is not importable; one manifest replaces all three when un has its own repo.
DEPLOY_FILES = ("Containerfile", "compose.yaml", "proxy.py", "allowlist.example", "env.example", "reinstall.py")


class Refreshed(NamedTuple):
    copied: list[str]
    parked: list[str]
    parked_in: Path | None
    dependencies: Dependencies
    # Set exactly when pyproject.toml was rewritten.
    backup: Path | None


def refresh(source: Path, target: Path) -> Refreshed:
    """Bring `target`'s owned src/un and pyproject tables up to `source`'s; everything else stays, and `[project].dependencies` keeps the runtime's own names.

    An owned file the source no longer carries moves to `target/delete_me/update-<stamp>/src/un/`, and a pyproject.toml about to be rewritten is copied to `.../update-<stamp>/pyproject.toml` first. The merged manifest is parsed before anything is written, so a merge that would break it raises `tomllib.TOMLDecodeError` with the tree untouched.
    """
    manifest = target / "pyproject.toml"
    before = manifest.read_text(encoding="utf-8")
    checkout = (source / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = merge_dependencies(_declared(before), _declared(checkout))
    merged = merge_pyproject(before, checkout, dependencies.merged if dependencies.kept else None)
    tomllib.loads(merged)
    changed = merged != before
    new, old = _owned_files(source / "src/un"), _owned_files(target / "src/un")
    copied = sorted(rel for rel, path in new.items()
                    if rel not in old or not filecmp.cmp(path, old[rel], shallow=False))
    stale = sorted(rel for rel in old if rel not in new)
    # Naive local time, as session ids are stamped.
    stamp = target / "delete_me" / f"update-{datetime.now():%Y%m%dT%H%M%S}"
    backup = stamp / "pyproject.toml" if changed else None
    # Before any write, so a stamp that cannot be made leaves src/un and the manifest untouched.
    if changed or stale:
        stamp.mkdir(parents=True, exist_ok=True)
    if backup:
        shutil.copy2(manifest, backup)
    for rel in copied:
        out = target / "src/un" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new[rel], out)
    for rel in stale:
        out = stamp / "src/un" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(old[rel], out)
    if changed:
        manifest.write_text(merged, encoding="utf-8")
    return Refreshed([str(r) for r in copied], [str(r) for r in stale], stamp if stale else None,
                     dependencies, backup)


def _un_root(root: Path) -> Path | None:
    """`root` when it holds un as src/un beside a pyproject.toml naming unstable-number."""
    try:
        name = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None
    return root if name == "unstable-number" and (root / "src/un/core.py").is_file() else None


def _deploy_differs(source: Path, target: Path) -> list[str]:
    """The shipped deploy files `source` carries that `target` lacks or holds with other bytes; an unreadable pair counts as differing."""
    differs = []
    for name in DEPLOY_FILES:
        new, old = source / "deploy" / name, target / "deploy" / name
        try:
            if new.is_file() and not (old.is_file() and filecmp.cmp(new, old, shallow=False)):
                differs.append(name)
        except OSError:
            differs.append(name)
    return differs


def _update_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path, help="a un checkout, or its src/un")


@service("command:update")
def update(args: argparse.Namespace) -> int:
    """update this runtime's src/un and pyproject.toml from a un checkout, keeping what you added"""
    # It rewrites un's own enforcement code, so only a person at a terminal may run it; an agent's shell has its output piped.
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("un update runs only at a terminal; run it yourself from a shell", file=sys.stderr)
        return EXIT_USAGE
    package = Path(un.__file__).resolve().parent
    target = _un_root(package.parents[1])
    if target is None:
        print(f"un update updates an exported runtime, src/un beside its pyproject.toml; this un runs "
              f"from {package}. Reinstall it instead, e.g. `uv tool install --force <checkout>`",
              file=sys.stderr)
        return EXIT_FAILED
    contained = CONTAINER_MARKER.exists()
    parking = target / "delete_me"
    # Only the update service binds a writable delete_me; in the un service it is a root-owned directory on a read-only root.
    if contained and not (parking.is_dir() and os.access(parking, os.W_OK)):
        print(f"un update: in a container it runs only as the update service, which needs {parking} writable; on the host, `mkdir <runtime>/delete_me` as your own user, then from <runtime>/deploy/ run `UN_SOURCE=<checkout root> docker compose --profile update run --rm update`", file=sys.stderr)
        return EXIT_USAGE
    given = args.source.expanduser().resolve()
    # parent.parent, not parents[1]: a path one level below / has no parents[1].
    source = _un_root(given) or _un_root(given.parent.parent)
    if source is None:
        hint = "; set UN_SOURCE to a un checkout's root" if contained else ""
        print(f"un update: {given} is not a un checkout or its src/un{hint}", file=sys.stderr)
        return EXIT_USAGE
    if source == target:
        print(f"un update: {source} is this runtime itself", file=sys.stderr)
        return EXIT_USAGE
    try:
        done = refresh(source, target)
    except tomllib.TOMLDecodeError as exc:
        print(f"un update: the merged pyproject.toml would not parse ({exc}); nothing was written",
              file=sys.stderr)
        return EXIT_FAILED
    except OSError as exc:
        # str() of an OSError carries its filename, which names the path that failed.
        print(f"un update stopped: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"updated {target} from {source}")
    for label, paths in (("copied", done.copied), (f"moved into {done.parked_in}", done.parked)):
        if paths:
            print(f"{label}:")
            for entry in paths:
                print(f"  src/un/{entry}")
    deps = done.dependencies
    for label, entries in (("dependencies added", deps.added), ("dependencies re-pinned", deps.repinned),
                           ("dependencies kept (not in the checkout)", deps.kept)):
        if entries:
            print(f"{label}:")
            for entry in entries:
                print(f"  {entry}")
    saved = f"updated, the previous copy is at {done.backup}" if done.backup else "unchanged"
    print(f"pyproject.toml: {saved}; pixi.toml untouched")
    # Reported, never copied: nothing under deploy/ is writable to un code.
    if (target / "deploy").is_dir() and (differs := _deploy_differs(source, target)):
        print("deploy/ differs from the checkout:")
        for name in differs:
            print(f"  deploy/{name}")
        print("copy them into <runtime>/deploy/ on the host, then run `docker compose build` there")
    if contained:
        print("\nnext: uncomment the package hosts in deploy/allowlist, then from deploy/ on the host run `docker compose --profile reinstall run --rm reinstall` (podman: `podman-compose --profile reinstall run --rm reinstall`)")
    else:
        print("\nnext: pixi install")
    return EXIT_OK


update.arguments = _update_arguments


@service("command:install")
def install(args: argparse.Namespace) -> int:
    """scaffold .un/ and AGENTS.md at the project root, or here if there is none"""
    if not _supported():
        print(f"un install supports linux only; this is {sys.platform}",
              file=sys.stderr)
        return EXIT_FAILED

    # Read every default before writing anything, so a broken install leaves no half-built tree.
    defaults: dict[str, str] = {}
    for target, name in DATA_FILES.items():
        try:
            defaults[target] = (DEFAULTS / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"un install cannot read its default for {UN_DIR}/{target}: {exc}",
                  file=sys.stderr)
            return EXIT_FAILED

    # The existing project, so running from a subdirectory repairs it rather than scaffolding a second one.
    root = project_root() or Path.cwd()
    un = root / UN_DIR

    created: list[str] = []
    existing: list[str] = []

    # The mode applies on creation only; an existing `.un/` is left as it is.
    (existing if un.is_dir() else created).append(f"{UN_DIR}/")
    un.mkdir(mode=UN_DIR_MODE, exist_ok=True)

    for name in DIRECTORIES:
        target = un / name
        (existing if target.is_dir() else created).append(f"{UN_DIR}/{name}/")
        target.mkdir(exist_ok=True)

    rendered = defaults.pop("config.toml") + _permissions_section() + _sandbox_section()
    scaffold = [(un / "config.toml", rendered),
                (un / "permissions.toml", PERMISSIONS),
                (un / "banner.txt", BANNER),
                (root / "AGENTS.md", AGENTS)]
    scaffold += [(un / target, text) for target, text in defaults.items()]

    for path, text in scaffold:
        rel = path.relative_to(root)
        if path.exists():
            existing.append(str(rel))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        created.append(str(rel))

    # A config written just now equals `rendered`, so it gets nothing.
    added = _add_missing(un / "config.toml", rendered)

    for label, paths in (("created", created), ("already present", existing),
                         (f"added to {UN_DIR}/config.toml, commented out", added)):
        if paths:
            print(f"{label}:")
            for entry in paths:
                print(f"  {entry}")

    print(f"\nedit {UN_DIR}/config.toml to set launch defaults, and AGENTS.md to tell "
          f"an agent how to work here.\nAGENTS.md reaches the model exactly as written.")
    _missing_packages()
    return EXIT_OK
