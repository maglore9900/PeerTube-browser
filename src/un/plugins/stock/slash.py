"""The built-in slash commands, each a `slash:<name>` service listed by /help, plus commands authored as `.un/commands/**/*.md`. Handled locally. Only `/rename` writes, through the transcript plugin."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from un import (REGISTRY, RunPrompt, Session, core, frontmatter, reapply,
                service, use, variants)

from un.core import CONFIG, QUIT, SESSIONS, SLUG, UN_DIR, new_id, scan

# The module, not its names: `cli.DISABLED_BY_FLAG` is reassigned after this file is imported.
from un.plugins.stock import cli, plugin_config

# Plugins `/reload` cannot drop: `commands` (which runs `/reload`) and `interactive` (which reads the keys). Both can still be disabled at launch.
UNDROPPABLE = frozenset({"commands", "interactive"})

# `/reload`'s rescan order: agents' unavailable-tool notes read the tool registry, so tools run first. Other kinds follow, sorted.
KINDS = ("commands", "tools", "agents", "hooks", "workflows")


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
    return run


def _name(path: Path, here: Path) -> str:
    """The command name from the file's path below `here`, segments joined by `:`."""
    return ":".join(path.relative_to(here).with_suffix("").parts)


def _reason(name: str, text: str) -> str | None:
    """Why this file is not a command, or None; one distinct message per rule."""
    for part in name.split(":"):
        if not SLUG.fullmatch(part):
            return (f"bad segment {part!r}: every directory and the file must be "
                    "lowercase letters, digits and hyphens")
    if name in QUIT:
        return f"/{name} leaves the session and cannot be redefined"
    if f"slash:{name}" in REGISTRY["service"]:
        # What survives `scan`'s drop is a plugin's or another kind's; refused rather than letting `_register` raise.
        return f"/{name} is already a command"

    data, body, error = frontmatter.parse(text)
    if error:
        return error
    if not str(data.get(REQUIRED) or "").strip():
        return f"no {REQUIRED} in its frontmatter"
    if not body:
        return "no body, and the body is the prompt"
    return None


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Register every qualifying `.un/commands/**/*.md` as `/dir:name`. Returns (newly registered, refused).

    Takes a path, not a Session, because it runs at import. Re-runnable: `scan` drops the previous scan's commands first, so an edited or deleted file takes effect. Refusals are keyed by relative path, so same-named files in different directories stay distinct.
    """
    registered: list[str] = []

    def read(where: Path, path: Path, text: str, on) -> str | None:
        name = _name(path, where / COMMANDS)
        if refusal := _reason(name, text):
            return refusal
        data, body, _ = frontmatter.parse(text)
        service(f"slash:{name}")(_prompt_command(body, str(data[REQUIRED]).strip()))
        registered.append(name)
        return None

    REFUSED.clear()
    REFUSED.update(scan(root, "commands", COMMANDS, "**/*.md", read))
    return registered, dict(REFUSED)


@service("commands:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/commands/` for `/reload`."""
    return discover(cwd)


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


def _instant(stamp) -> datetime | None:
    """An aware instant from an ISO stamp or a session id's naive local timestamp; None if neither parses."""
    if not isinstance(stamp, str):
        return None
    for parse in (datetime.fromisoformat, lambda s: datetime.strptime(s[:15], "%Y%m%dT%H%M%S")):
        try:
            return parse(stamp).astimezone()
        except ValueError:
            continue
    return None


def _summary(rows, root: Path, session_id: str) -> tuple[str, str, datetime | None]:
    """A record's first question (which identifies it), its last few lines (which distinguish similar ones), and when it was last written to."""
    record = rows(root, session_id)
    spoken = [(row.get("role"), _text(row.get("content"))) for row in record if "role" in row]
    opened = next((text for role, text in spoken if role == "user" and text.strip()), "")
    tail = [f"{'>' if role == 'user' else '<'} {_oneline(text, PREVIEW_WIDTH)}"
            for role, text in spoken[-PREVIEW_ROWS:] if text.strip()]
    last = next((at for row in reversed(record) if (at := _instant(row.get("un_at")))), None)
    return _oneline(opened, FIRST_WIDTH), "\n".join(tail), last


def _options(rows, root: Path, ids: list[str], named: dict[str, str]) -> tuple[dict, ...]:
    """One picker option per id, most recently used first, labelled by its name where it has one, with all four keys set: `ask:` adapters index them directly.

    A record with no stamped row sorts by the time its id records it started.
    """
    built = []
    for session_id in ids:
        opened, tail, last = _summary(rows, root, session_id)
        used = last or _instant(session_id) or datetime.fromtimestamp(0).astimezone()
        built.append((used, {"label": f"{named.get(session_id, session_id)}  {_age(session_id)}".strip(),
                             "value": session_id, "description": opened, "preview": tail}))
    # Stable, so records used at the same instant keep their newest-started-first order.
    built.sort(key=lambda pair: pair[0], reverse=True)
    return tuple(option for _, option in built)


@service("slash:new")
def new(session: Session, rest: str) -> str:
    """Start a fresh session, leaving this one on disk.

    Adopts a new id in place and re-bases the system prompt (as `core.reapply` does), so SessionStart runs again on the next turn. A no-op before the first turn.
    """
    if not session.messages:
        return ""
    left, carried = session.id, len(session.messages)
    session.adopt(new_id())
    session.rebase()
    return f"left {left} ({carried} messages), started {session.id}"


@service("slash:rename")
def rename(session: Session, rest: str) -> str:
    """Name this session, so /resume offers it by name. Asks for one when none is given.

    Each run of spaces is stored as one `-`, so the name can be typed after `/resume` or `un resume` unquoted.
    """
    try:
        store = use("session", "rename")
    except LookupError as exc:
        return str(exc)
    if not rest:
        try:
            ask = use("ask", session.approval)
        except LookupError:
            return (f"this run has no way to ask ({session.approval!r} answers approvals "
                    f"only); name it instead with /rename <name>")
        opened = next((text for message in session.messages if message.get("role") == "user"
                       and (text := _text(message.get("content"))).strip()), "")
        suggested = re.sub(r" +", "-", _oneline(opened, FIRST_WIDTH))
        answered = ask(session, "Name this session",
                       f"/resume will offer {session.id} under this name.",
                       ({"label": suggested, "value": suggested, "description": "",
                         "preview": ""},) if suggested else ())
        if not answered:
            return f"nothing given; {session.id} is unchanged"
        rest = answered[0]
    try:
        stored = store(session.root, session.id, re.sub(r" +", "-", rest.strip()))
    except ValueError as exc:
        return f"not renamed: {exc}"
    return f"{session.id} is now named {stored!r}"


@service("slash:resume")
def resume(session: Session, rest: str) -> str:
    """Join a previous session, picked from a list or named outright.

    Switches in place (adopt, then restore), leaving the current record on disk. A picked answer and a typed argument go through the same membership check. Every failure returns text, since `core.slash` does not catch a command's raise.
    """
    try:
        records = use("session", "records")
        rows = use("session", "rows")
        restore = use("session", "restore")
        names = use("session", "names")
    except LookupError as exc:
        return str(exc)

    known = records(session.root)
    if not known:
        return f"no session records under {SESSIONS}/"
    try:
        named, unreadable = names(session.root), ""
    except ValueError as exc:
        # Ids still work; the damage is named wherever a name would have mattered.
        named, unreadable = {}, f" ({exc})"

    picked = rest.strip()
    if not picked:
        try:
            ask = use("ask", session.approval)
        except LookupError:
            return (f"this run has no way to ask ({session.approval!r} answers approvals "
                    f"only); name one instead with /resume <id>. {_listing(known)}")
        answered = ask(session, "Which session?",
                       f"joining one leaves {session.id}, which stays on disk.{unreadable}",
                       _options(rows, session.root, _recent(known), named))
        if not answered:
            return f"nothing picked; still in {session.id}"
        picked = answered[0].strip()

    # An id is tried first, so a name never shadows one; a name whose holder has no record stays as typed, to be refused below.
    if picked not in known and (held := {given: sid for sid, given in named.items()}.get(picked)) in known:
        picked = held
    if picked == session.id:
        # Rebuilding from disk would discard the token count and the read ledger.
        return f"already in {session.id}"
    if picked not in known:
        return f"no session record named {picked!r}. {_listing(known)}{unreadable}"

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

    # `load` rebinds FALLOUT rather than mutating it, so this keeps the pre-reload value.
    before = core.FALLOUT
    try:
        added, dropped = reapply(session, disabled=disabled | cli.DISABLED_BY_FLAG,
                                 enabled=enabled)
    except ValueError as exc:
        return str(exc)  # an alias.json drift, which `plugin_table` refuses to start on
    for name, text in core.FALLOUT.items():
        if before.get(name) != text:
            session.report(name, text)

    # Every running plugin's `<kind>:discover`, so a disabled plugin gets no line and a new kind needs no edit here. A file-authored service is never one, however it is named.
    found = {key.rsplit(":", 1)[0]: fn for key, fn in REGISTRY["service"].items()
             if key.endswith(":discover") and not getattr(fn, "un_from_file", False)}
    lines: list[str] = []
    refusals: dict[str, str] = {}
    for kind in sorted(found, key=lambda k: (KINDS.index(k) if k in KINDS else len(KINDS), k)):
        names, refused_here = found[kind](session.root)
        lines.append(f"{kind}: " + (", ".join(names) if names else "none enabled"))
        refusals.update(refused_here)
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
    lines += [f"  refused {name}: {why}" for name, why in sorted(refusals.items())]
    return "\n".join(lines)


# At import, so a command typed on the first line is already registered; `/reload` rescans from the session root.
discover()
