"""The built-in slash commands, each a `slash:<name>` service listed by /help, plus commands authored as `.un/commands/**/*.md`. Handled locally. Writes nothing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from un import (REGISTRY, RunPrompt, Session, frontmatter, reapply,
                service, use, variants)

from un.core import CONFIG, QUIT, SESSIONS, SLUG, UN_DIR, new_id

# The module, not its names: `cli.DISABLED_BY_FLAG` is reassigned after this file is imported.
from un.plugins.stock import cli, plugin_config

# Plugins `/reload` cannot drop: the undisableable ones, plus `commands` (which runs `/reload`) and `interactive` (which reads the keys). All can still be disabled at launch.
UNDROPPABLE = cli.UNDISABLEABLE | {"commands", "interactive"}


@service("slash:help")
def help_(session: Session, rest: str) -> str:
    """List the available commands."""
    named = variants("slash")
    width = max([10, *(len(name) for name in named)])
    lines = []
    for name, fn in named.items():
        doc = (fn.__doc__ or "").strip().splitlines()
        lines.append(f"  /{name:<{width}} {doc[0] if doc else ''}")
    # Quit spellings are not services, so list them by hand.
    leaving = ", ".join(f"/{name}" for name in sorted(QUIT))
    out = "commands:\n" + "\n".join(lines) + f"\n  {leaving:<12} Leave."
    if REFUSED:
        # The only place import-time refusals can be reported.
        out += "\n\nnot registered:\n" + "\n".join(
            f"  {name}: {why}" for name, why in sorted(REFUSED.items()))
    return out


@service("slash:stats")
def stats(session: Session, rest: str) -> str:
    """Show what this session has used so far."""
    try:
        rows = use("session", "usage")(session.root, session.id)
    except LookupError as exc:
        # Returned: `core.slash` lets a command's own raise through.
        return str(exc)
    except FileNotFoundError:
        rows = []
    totals: dict[str, int] = {}
    for row in rows:
        for field, value in (row or {}).items():
            if isinstance(value, int):
                totals[field] = totals.get(field, 0) + value
    parts = [f"{k}={v}" for k, v in sorted(totals.items())]
    line = f"messages={len(session.messages)}  " + ("  ".join(parts) or "no usage recorded")
    return line + _meter(session)


def _meter(session: Session) -> str:
    """`  context=42%  cost=$0.83`, dropping unknown figures but keeping zeros. Cost includes subagents; the totals above do not."""
    try:
        meter = use("models", "meter")(session)
    except LookupError:
        return ""
    shown = []
    if meter.fullness is not None:
        shown.append(f"context={meter.fullness:.0%}")
    if meter.cost is not None:
        shown.append(f"cost=${meter.cost:,.2f}")
    return "".join(f"  {part}" for part in shown)


@service("slash:plugins")
def plugins(session: Session, rest: str) -> str:
    """List every plugin, what it does, and whether it is on.

    Reads `.un/config.toml` (ADR-0015), so a command-line `--disable-plugin` is not reflected here.
    """
    return plugin_config.listing(*plugin_config.configured(session.root))


# --- commands authored as files -------------------------------------------------------

COMMANDS = UN_DIR / "commands"

# Required frontmatter key; it is the /help line.
REQUIRED = "description"

# Where the argument text lands in a command body, spelled as Claude Code spells it.
PLACEHOLDER = "$ARGUMENTS"

# Refused command files and why, shown by /help and returned by /reload.
REFUSED: dict[str, str] = {}


def _prompt_command(body: str, description: str):
    """A `slash:` service handing `body` to the model instead of showing it."""

    def run(session: Session, rest: str) -> str:
        # Substituted at `$ARGUMENTS`, else appended, so the argument is never dropped.
        # rat-tail: plain substitution, not a template language.
        if PLACEHOLDER in body:
            raise RunPrompt(body.replace(PLACEHOLDER, rest).strip())
        raise RunPrompt(f"{body}\n\n{rest}" if rest else body)

    run.__doc__ = description
    # Marks file-registered commands, so a re-scan can tell them from plugin ones.
    run.un_from_file = True
    return run


def _name(path: Path, here: Path) -> str:
    """The command name from the file's path below `here`, segments joined by `:`."""
    return ":".join(path.relative_to(here).with_suffix("").parts)


def _reason(name: str, path: Path) -> str | None:
    """Why this file is not a command, or None; one distinct message per rule."""
    for part in name.split(":"):
        if not SLUG.fullmatch(part):
            return (f"bad segment {part!r}: every directory and the file must be "
                    "lowercase letters, digits and hyphens")
    if name in QUIT:
        return f"/{name} leaves the session and cannot be redefined"
    claimed = REGISTRY["service"].get(f"slash:{name}")
    if claimed is not None and not getattr(claimed, "un_from_file", False):
        # Refused rather than letting `_register` raise at startup.
        return f"/{name} is already a command"

    data, body, error = frontmatter.parse(path.read_text(encoding="utf-8"))
    if error:
        return error
    if not str(data.get(REQUIRED) or "").strip():
        return f"no {REQUIRED} in its frontmatter"
    if not body:
        return "no body, and the body is the prompt"
    return None


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Register every qualifying `.un/commands/**/*.md` as `/dir:name`. Returns (newly registered, refused).

    Takes a path, not a Session, because it runs at import. Re-runnable: already-registered files are skipped, so `/reload` reports only what changed.
    """
    here = (root or Path.cwd()) / COMMANDS
    REFUSED.clear()
    registered: list[str] = []
    if not here.is_dir():
        return registered, dict(REFUSED)

    for path in sorted(here.rglob("*.md")):
        name = _name(path, here)
        if getattr(REGISTRY["service"].get(f"slash:{name}"), "un_from_file", False):
            continue
        if refusal := _reason(name, path):
            # Keyed by relative path, so same-named files in different directories stay distinct.
            REFUSED[path.relative_to(here).as_posix()] = refusal
            continue
        data, body, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        service(f"slash:{name}")(_prompt_command(body, str(data[REQUIRED]).strip()))
        registered.append(name)
    return registered, dict(REFUSED)


# Previous sessions `/resume` offers.
# rat-tail: each one's record is read whole to summarise it; a tail read would lift the cap.
RECENT = 20


def _recent(known: list[str]) -> list[str]:
    """The newest `RECENT` ids, newest first."""
    return list(reversed(known))[:RECENT]


def _listing(known: list[str]) -> str:
    """The ids an operator may name, for a refusal to end on."""
    return "readable: " + ", ".join(_recent(known))


# Preview size per picker row, clipped here because `ask:cli` does not clip.
PREVIEW_ROWS = 6
PREVIEW_WIDTH = 72

FIRST_WIDTH = 60


def _text(content) -> str:
    """A message's text, from a string or its text blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(block["text"] for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                    and isinstance(block.get("text"), str))


def _oneline(text: str, width: int) -> str:
    """`text` collapsed onto a single clipped row. A row of a menu is one row."""
    flat = " ".join(text.split())
    return f"{flat[:width - 1]}…" if len(flat) > width else flat


def _age(session_id: str) -> str:
    """How long ago the session started, from the id's timestamp (not mtime, which copies change); "" if unparseable."""
    try:
        started = datetime.strptime(session_id[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return ""
    seconds = (datetime.now() - started).total_seconds()
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return "just now"


def _summary(rows, root: Path, session_id: str) -> tuple[str, str]:
    """A record's first question (which identifies it) and its last few lines (which distinguish similar ones)."""
    spoken = [(row.get("role"), _text(row.get("content")))
              for row in rows(root, session_id) if "role" in row]
    opened = next((text for role, text in spoken if role == "user" and text.strip()), "")
    tail = [f"{'>' if role == 'user' else '<'} {_oneline(text, PREVIEW_WIDTH)}"
            for role, text in spoken[-PREVIEW_ROWS:] if text.strip()]
    return _oneline(opened, FIRST_WIDTH), "\n".join(tail)


def _options(rows, root: Path, ids: list[str]) -> tuple[dict, ...]:
    """One picker option per id, with all four keys set: `ask:` adapters index them directly."""
    built = []
    for session_id in ids:
        opened, tail = _summary(rows, root, session_id)
        built.append({"label": f"{session_id}  {_age(session_id)}".strip(),
                      "value": session_id, "description": opened, "preview": tail})
    return tuple(built)


@service("slash:new")
def new(session: Session, rest: str) -> str:
    """Start a fresh session, leaving this one on disk.

    Adopts a new id in place and re-bases the system prompt (as `core.reapply` does), so SessionStart runs again on the next turn. A no-op before the first turn.
    """
    if not session.messages:
        return ""
    left, carried = session.id, len(session.messages)
    session.adopt(new_id())
    if session.system_base is not None:
        session.system = session.system_base
        session.context_injected = False
        session.system_digest = None
    return f"left {left} ({carried} messages), started {session.id}"


@service("slash:resume")
def resume(session: Session, rest: str) -> str:
    """Join a previous session, picked from a list or named outright.

    Switches in place (adopt, then restore), leaving the current record on disk. A picked answer and a typed argument go through the same membership check. Every failure returns text, since `core.slash` does not catch a command's raise.
    """
    try:
        records = use("session", "records")
        rows = use("session", "rows")
        restore = use("session", "restore")
    except LookupError as exc:
        return str(exc)

    known = records(session.root)
    if not known:
        return f"no session records under {SESSIONS}/"

    picked = rest.strip()
    if not picked:
        try:
            ask = use("ask", session.approval)
        except LookupError:
            return (f"this run has no way to ask ({session.approval!r} answers approvals "
                    f"only); name one instead with /resume <id>. {_listing(known)}")
        answered = ask(session, "Which session?",
                       f"joining one leaves {session.id}, which stays on disk.",
                       _options(rows, session.root, _recent(known)))
        if not answered:
            return f"nothing picked; still in {session.id}"
        picked = answered[0].strip()

    if picked == session.id:
        # Rebuilding from disk would discard the token count and the read ledger.
        return f"already in {session.id}"
    if picked not in known:
        return f"no session record named {picked!r}. {_listing(known)}"

    left, carried = session.id, len(session.messages)
    session.adopt(picked)
    try:
        restore(session)
    except FileNotFoundError:
        # The record vanished after `adopt`; name the old id so it can be rejoined.
        return (f"the record for {picked} went while it was being joined, so this session is "
                f"now empty under that id. Rejoin what you left with /resume {left}")
    return (f"left {left} ({carried} messages), joined {picked} "
            f"({len(session.messages)} messages)")


@service("slash:reload")
def reload_(session: Session, rest: str) -> str:
    """Re-read .un/config.toml: extensions, permissions and the launch keys.

    Reloads plugins and the discovered trees, the permission tables and tier, and the `cli.RELOADABLE` launch keys. Provider endpoints (url, adaptor, api_key) and the theme stay as launched. Any `UNDROPPABLE` name refuses the whole reload; command-line `--disable-plugin`s stay applied. Never writes the file; `rest` is ignored.
    """
    try:
        enabled, disabled = plugin_config.configured(session.root)
    except (OSError, ValueError) as exc:
        return f"{session.root / CONFIG}: {exc}"

    if refused := sorted(disabled & UNDROPPABLE):
        return (f"{', '.join(refused)} cannot be dropped mid-session: it is what the "
                f"running session is made of, and dropping it takes away the command that "
                f"would put it back. Nothing was applied - take it out of disable_plugin in "
                f"{session.root / CONFIG} and restart instead.")

    try:
        keys = cli.reloadable(session.root, session.provider)
    except ValueError as exc:
        # Validated before anything is applied.
        return str(exc)

    try:
        added, dropped = reapply(session, disabled=disabled | cli.DISABLED_BY_FLAG,
                                 enabled=enabled)
    except ValueError as exc:
        return str(exc)  # an alias.json drift, which `plugin_table` refuses to start on

    registered, refused_files = discover(session.root)
    lines = ["commands: " + (", ".join(registered) if registered else "nothing new")]
    # The discovered trees are reached through `use` so disabled plugins stay out; a disabled one gets no line. Commands and tools report what is new; agents, hooks and workflows are rebuilt and report the whole enabled set.
    try:
        tool_names, refused_tools = use("tools", "discover")(session.root)
    except LookupError:
        refused_tools = {}
    else:
        lines.append("tools: "
                     + (", ".join(tool_names) if tool_names else "nothing new"))
    try:
        agent_names, refused_agents = use("agents", "discover")(session.root)
    except LookupError:
        refused_agents = {}
    else:
        lines.append("agents: "
                     + (", ".join(agent_names) if agent_names else "none enabled"))
    try:
        hook_names, refused_hooks = use("hooks", "discover")(session.root)
    except LookupError:
        refused_hooks = {}
    else:
        lines.append("hooks: "
                     + (", ".join(hook_names) if hook_names else "none enabled"))
    try:
        workflow_names, refused_workflows = use("workflows", "discover")(session.root)
    except LookupError:
        refused_workflows = {}
    else:
        lines.append("workflows: "
                     + (", ".join(workflow_names) if workflow_names else "nothing new"))
    # Report only keys whose value changed.
    moved = {key: value for key, value in keys.items() if getattr(session, key) != value}
    for key, value in moved.items():
        setattr(session, key, value)
    lines.append("config: " + (", ".join(
        f"{key} = {value}" for key, value in sorted(moved.items())) or "nothing new"))
    # Last, because `Tool(NAME)` rules are checked against a registry that is now complete. `permissions` cannot be dropped, so no LookupError.
    try:
        tier = use("permissions", "load")(session.root)
    except ValueError as exc:
        # The running tables are untouched; reported so the rest of this report survives.
        lines.append(f"permissions: not reloaded - {exc}")
    else:
        # The tier too, or `dangerous_allow` would change the rules but not the fallthrough.
        session.tier = tier
        lines.append(f"permissions: {tier}")
    if added:
        lines.append("enabled: " + ", ".join(added))
    if dropped:
        # Threads a module started at import keep running.
        lines.append("dropped: " + ", ".join(dropped)
                     + " - registrations only; anything started at import keeps running")
    # Refusals repeat on every reload until fixed.
    lines += [f"  refused {name}: {why}" for name, why in sorted(
        {**refused_files, **refused_tools, **refused_agents,
         **refused_hooks}.items())]
    return "\n".join(lines)


# At import, so a command typed on the first line is already registered; `/reload` rescans from the session root.
discover()
