"""Operator text injected into the session: `AGENTS.md` and `.un/rules/*.md`. Not the permission table. Writes nothing.

Rule bodies go straight into the conversation, with no index or tool. `trigger`, the selectors and `message_type` are parsed by `un.core`, shared with `hooks.py`; a rule is only text and never executes anything.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path

from un import EXIT_OK, Session, core, frontmatter, hook, service

from un.core import CONFIG, project_root, un_dir

# The first file found wins; the singular is a legacy spelling.
PROJECT_FILES = ("AGENTS.md", "AGENT.md")

# Moments a rule may declare. Others either ignore returns or are reached only by routing. Checked here, before `core.route` would raise (ADR-0014).
DELIVERABLE = frozenset({"SessionStart", core.TURN_EVENT, core.PATH_EVENT})

# Valid frontmatter keys; anything else (such as the retired `cadence:`) is reported.
KNOWN = frozenset(("trigger", "message_type") + core.SELECTOR_KEYS)

# Per-turn dedup record in `Session.state`.
STATE_KEY = "rules.fired"


@dataclass(frozen=True)
class Rule:
    """One rule file, with its moment, its audience, its delivery and its config answer."""

    name: str
    body: str
    trigger: core.Trigger
    selectors: core.Selectors
    message_type: str
    path: Path
    enabled: bool
    frontmatter_error: str | None = None


def _load(path: Path, on: frozenset[str]) -> Rule:
    """One rule, with every frontmatter problem collected (not just the first) rather than raised; the body always survives."""
    data, body, error = frontmatter.parse(path.read_text(encoding="utf-8"))
    when, trigger_error = core.trigger(data)
    who, selector_error = core.selectors(data)
    delivery, delivery_error = core.message_type(data)

    unknown = None
    if extra := sorted(set(data) - KNOWN, key=str):
        # `key=str`: YAML reads a bare `on:` as True, and sorting a bool with strs raises.
        unknown = f"unknown key {str(extra[0])!r}; known: {', '.join(sorted(KNOWN))}"

    stray_path = None
    # A path only matches on tool use; beside any other moment the rule could never fire.
    if when.path:
        for moment in when.event:
            if moment != core.PATH_EVENT:
                stray_path = (f"a path cannot be matched on {moment}, where no tool call "
                              "has happened; drop one of the two")
                when = replace(when, path=())
                break

    inert_stride = None
    # SessionStart fires once, so a stride there does nothing. Checked before `undeliverable` rewrites the moments; the stride falls back to 1.
    if when.every > 1 and "SessionStart" in when.event:
        inert_stride = ("a stride cannot advance on SessionStart, which fires once at "
                        "turn zero; drop one of the two")
        when = replace(when, every=1)

    undeliverable = None
    for moment in when.event:
        if moment not in DELIVERABLE:
            undeliverable = (f"a rule is text and cannot be delivered on {moment}; "
                             f"a rule fires on: {', '.join(sorted(DELIVERABLE))}")
            # The whole declaration falls back to every turn: fallbacks apply a rule more, never less.
            when = replace(when, event=(core.TURN_EVENT,))
            break

    problems = [note for note in (error, unknown, trigger_error, selector_error,
                                  delivery_error, stray_path, inert_stride,
                                  undeliverable) if note]
    return Rule(name=path.stem, body=body, trigger=when, selectors=who,
                message_type=delivery, path=path, enabled=path.stem in on,
                frontmatter_error="; ".join(problems) or None)


def _scan(root: Path) -> tuple[list[Rule], str | None]:
    """Every rule on disk in name order, enabled or not (so `command:rules` can list the disabled ones), and any config error."""
    # Lenient: this runs every turn.
    on, config_error = core.enabled_lenient(root, "rules", "rule")
    folder = un_dir(root, "rules")
    found = [_load(p, on) for p in sorted(folder.glob("*.md"))] if folder.is_dir() else []
    return found, config_error


def discover(session: Session) -> list[Rule]:
    """Every rule on disk, re-read per call so edits apply on the next turn.

    rat-tail: no caching.
    """
    return _scan(session.root)[0]


def _applies(session: Session, rule: Rule, event: str, touched: tuple = ()) -> bool:
    """Whether `rule` is enabled, routes to `event`, selects this conversation, is due this turn, and (for a path rule) matches a call in `touched`.

    Every delivery hook goes through here, so a disabled rule never arrives.
    """
    if not rule.enabled:
        return False
    if not any(core.route(moment, rule.message_type) == event
               for moment in rule.trigger.event):
        return False
    if not core.selects(rule.selectors, session):
        return False
    if session.turn_index % rule.trigger.every:
        return False
    if not rule.trigger.path:
        return True
    return any(core.triggered(rule.trigger, args) for args in touched)


def _once(session: Session, rule: Rule) -> bool:
    """True the first time `rule` fires this turn, recording it. Stops a path rule firing once per matching call."""
    fired = session.state.setdefault(STATE_KEY, {})
    if fired.get(rule.name) == session.turn_index:
        return False
    fired[rule.name] = session.turn_index
    return True


def _selected(session: Session, event: str) -> list[Rule]:
    return [rule for rule in discover(session) if _applies(session, rule, event)]


def _fired(session: Session, event: str, touched: tuple) -> list[Rule]:
    """Rules due on `event` for these calls, each marked so it fires once per turn. Only rules that apply are marked."""
    return [rule for rule in discover(session)
            if _applies(session, rule, event, touched) and _once(session, rule)]


def _fence(tag: str, body: str) -> str:
    """Tag operator text so it is not read as harness instruction."""
    return f"<{tag}>\n{body}\n</{tag}>"


def _render(selected: list[Rule]) -> str | None:
    """The selected rules as one fenced block, or None (not "", which would erase a chained value)."""
    if not selected:
        return None
    parts = []
    for rule in selected:
        note = (f" (unreadable frontmatter - {rule.frontmatter_error}; applying every "
                f"turn)" if rule.frontmatter_error else "")
        parts.append(f"## {rule.name}{note}\n\n{rule.body}")
    return _fence("rules", "\n\n".join(parts))


@hook("SessionStart")
def instructions(*, session: Session) -> str | None:
    """`AGENTS.md`, if the project has one. Absent is normal and silent."""
    for name in PROJECT_FILES:
        path = session.root / name
        if path.is_file() and (text := path.read_text(encoding="utf-8").strip()):
            return _fence("project-instructions", text)
    return None


@hook("SessionStart")
def session_rules(*, session: Session) -> str | None:
    """Rules the operator wants stated once, at the top."""
    return _render(_selected(session, "SessionStart"))


@hook("TurnStart")
def turn_rules(*, session: Session) -> str | None:
    """Rules due on this turn (a stride fires on turns 0, N, 2N...), plus a report every turn of config errors and of enabled rules with broken headers.

    rat-tail: reports repeat every turn until fixed.
    """
    found, config_error = _scan(session.root)
    if config_error:
        session.report("rules: config", config_error)
    for rule in found:
        if rule.enabled and rule.frontmatter_error:
            session.report(f"rules: {rule.name}", rule.frontmatter_error)
    return _render([r for r in found if _applies(session, r, core.TURN_EVENT)])


@hook("UserPromptSubmit")
def prompt_rules(*, value: str, session: Session) -> str | None:
    """User-message rules appended to the prompt. A chain: returns the whole new prompt, or None to pass it through."""
    block = _render(_selected(session, "UserPromptSubmit"))
    return f"{value}\n\n{block}" if block else None


@hook("PostToolUse")
def tool_rules_user(*, value: str, session: Session, name: str, args: dict) -> str | None:
    """User-message path rules appended to this call's result (a chain, as `prompt_rules`)."""
    block = _render(_fired(session, core.PATH_EVENT, (args,)))
    return f"{value}\n\n{block}" if block else None


@hook("ToolResults")
def tool_rules_system(*, session: Session, calls: list) -> str | None:
    """System-message path rules, after the batch; PostToolUse results are user-role and cannot carry them."""
    return _render(_fired(session, "ToolResults",
                          tuple(call.get("input") for call in calls)))


@service("command:rules")
def rules_(args: argparse.Namespace) -> int:
    """list the rules defined in .un/rules/, which are enabled, and what was refused"""
    found, config_error = _scan(project_root() or Path.cwd())
    if config_error:
        print(f"{config_error}\n  every rule is off until this is fixed\n")
    live = [rule for rule in found if rule.enabled]
    idle = [rule for rule in found if not rule.enabled]
    broken = [rule for rule in found if rule.frontmatter_error]

    def shown(rule: Rule) -> str:
        """When it fires and how it arrives."""
        return f"{', '.join(rule.trigger.event)} as {rule.message_type}"

    if live:
        print("enabled:\n" + "\n".join(
            f"  {rule.name:<16} {shown(rule)}" for rule in live))
    if idle:
        print(("\n" if live else "") + f"present, not enabled - add [rules.<name>] with "
              f"{core.ENABLE} = true to {CONFIG.as_posix()}:\n" + "\n".join(
                  f"  {rule.name:<16} {shown(rule)}" for rule in idle))
    if not found:
        print(f"no rules in {un_dir(Path('.'), 'rules').as_posix()}/")
    if broken:
        # Includes disabled rules, which nothing else reports.
        print("\nunreadable frontmatter:\n" + "\n".join(
            f"  {rule.name}: {rule.frontmatter_error}" for rule in broken))
    return EXIT_OK
