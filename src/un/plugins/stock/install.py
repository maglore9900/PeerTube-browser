"""The `un install` verb: scaffold `.un/`, its config files, and a starter `AGENTS.md`.

Idempotent and non-destructive: existing files and directories are never overwritten. Static content is read from `un/defaults/` (see `DATA_FILES`); the `[permissions]` and `[sandbox]` sections of `config.toml` are rendered from the permission tables on each run so they cannot drift. Linux only.
"""

from __future__ import annotations

import argparse
import filecmp
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
# The only plugin imported here: it cannot be disabled, so importing it registers nothing new. The module, so the tables are read live.
from un.plugins.stock import permissions

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
    # Copied so the operator can update stale prices; `models.py` falls back to the packaged one.
    "models.toml": "models.toml",
    "commands/learn.md": "learn-command.md",
    "skills/skill-authoring/SKILL.md": "skill-authoring-skill.md",
    "skills/ast-grep/SKILL.md": "ast-grep-skill.md",
    "skills/workflow-authoring/SKILL.md": "workflow-authoring-skill.md",
    # A subdirectory keeps seeded agents apart from the operator's; discovery recurses.
    "agents/learning/detector.md": "detector-agent.md",
    "agents/learning/admitter.md": "admitter-agent.md",
    "agents/learning/implementor.md": "implementor-agent.md",
    "agents/learning/accuracy-auditor.md": "accuracy-auditor-agent.md",
    "agents/learning/memory-editor.md": "memory-editor-agent.md",
    # Docs for the operator; not in `DIRECTORIES`, which lists what loaders read.
    "docs/subagent-example.md": "subagent-template.md",
    "docs/how-to-write-a-skill.md": "howto-skill.md",
    "docs/how-to-write-a-hook.md": "howto-hook.md",
    "docs/how-to-write-an-agent.md": "howto-agent.md",
    "docs/how-to-write-a-rule.md": "howto-rule.md",
    "docs/how-to-write-a-plugin.md": "howto-plugin.md",
    "docs/how-to-write-a-tool.md": "howto-tool.md",
    "docs/how-to-write-a-theme.md": "howto-theme.md",
    # `default-theme.toml` is also `theme.py`'s built-in table.
    "themes/default.toml": "default-theme.toml",
    "themes/nord.toml": "nord-theme.toml",
    "themes/ember.toml": "ember-theme.toml",
    "themes/mono.toml": "mono-theme.toml",
    "themes/tactical.toml": "tactical-theme.toml",
    "themes/analog.toml": "analog-theme.toml",
}


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
        f"dangerous_allow = {_toml(permissions.DEFAULT_TOGGLES['dangerous_allow'])}",
    ]
    for policy in permissions.POLICIES:
        if not policy.toggle:
            continue
        lines.append("")
        lines.append(f"# {policy.why}:")
        lines.extend(f"#   {rule}" for rule in policy.rules)
        if policy.note:
            lines.append("#")
            lines.extend(f"# {line}" for line in textwrap.wrap(policy.note, 74))
        lines.append(
            f"{policy.name} = {_toml(permissions.DEFAULT_TOGGLES[policy.name])}")
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
        f"enabled = {_toml(permissions.DEFAULT_SANDBOX['enabled'])}",
        "",
        "# 1 = un's own rules deny the areas below. 2 is reserved for an external sandbox",
        "# provider and is not implemented; an enabled sandbox at mode 2 refuses to start.",
        f"mode = {permissions.DEFAULT_SANDBOX['mode']}",
    ]
    for policy in permissions.SANDBOX_POLICIES:
        lines.append("")
        lines.append(f"# {policy.why}:")
        lines.append(
            f"{policy.name} = {_toml(permissions.DEFAULT_SANDBOX[policy.name])}")
    return "\n".join(lines) + "\n"


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


def merge_pyproject(target: str, source: str) -> str:
    """`target` with each owned table swapped for `source`'s, byte for byte everywhere else.

    Text rather than parse-and-emit: there is no stdlib TOML writer, and the comments are what explain each line.
    """
    theirs = {name: text for name, text in _segments(source) if name in OWNED_TABLES}
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


class Refreshed(NamedTuple):
    copied: list[str]
    parked: list[str]
    parked_in: Path | None
    pyproject: bool


def refresh(source: Path, target: Path) -> Refreshed:
    """Bring `target`'s owned src/un and pyproject tables up to `source`'s; everything else stays.

    An owned file the source no longer carries moves to `target/delete_me/update-<stamp>/src/un/`. The merged manifest is parsed before anything is written, so a merge that would break it raises `tomllib.TOMLDecodeError` with the tree untouched.
    """
    manifest = target / "pyproject.toml"
    before = manifest.read_text(encoding="utf-8")
    merged = merge_pyproject(before, (source / "pyproject.toml").read_text(encoding="utf-8"))
    tomllib.loads(merged)
    new, old = _owned_files(source / "src/un"), _owned_files(target / "src/un")
    copied = sorted(rel for rel, path in new.items()
                    if rel not in old or not filecmp.cmp(path, old[rel], shallow=False))
    stale = sorted(rel for rel in old if rel not in new)
    for rel in copied:
        out = target / "src/un" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new[rel], out)
    # Naive local time, as session ids are stamped.
    parked_in = target / "delete_me" / f"update-{datetime.now():%Y%m%dT%H%M%S}" if stale else None
    for rel in stale:
        out = parked_in / "src/un" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(old[rel], out)
    if merged != before:
        manifest.write_text(merged, encoding="utf-8")
    return Refreshed([str(r) for r in copied], [str(r) for r in stale], parked_in, merged != before)


def _un_root(root: Path) -> Path | None:
    """`root` when it holds un as src/un beside a pyproject.toml naming unstable-number."""
    try:
        name = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None
    return root if name == "unstable-number" and (root / "src/un/core.py").is_file() else None


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
    given = args.source.expanduser().resolve()
    source = _un_root(given) or _un_root(given.parents[1])
    if source is None:
        print(f"un update: {given} is not a un checkout or its src/un", file=sys.stderr)
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
    print(f"updated {target} from {source}")
    for label, paths in (("copied", done.copied), (f"moved into {done.parked_in}", done.parked)):
        if paths:
            print(f"{label}:")
            for entry in paths:
                print(f"  src/un/{entry}")
    print(f"pyproject.toml: {'updated' if done.pyproject else 'unchanged'}; pixi.toml untouched")
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

    scaffold = [(un / "config.toml",
                 defaults.pop("config.toml") + _permissions_section() + _sandbox_section()),
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

    for label, paths in (("created", created), ("already present", existing)):
        if paths:
            print(f"{label}:")
            for entry in paths:
                print(f"  {entry}")

    print(f"\nedit {UN_DIR}/config.toml to set launch defaults, and AGENTS.md to tell "
          f"an agent how to work here.\nAGENTS.md reaches the model exactly as written.")
    _missing_packages()
    return EXIT_OK
