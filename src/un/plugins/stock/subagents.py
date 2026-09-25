"""Subagents: `.un/agents/**/*.md` definitions run as forked conversations through the `Task` tool. Writes nothing itself.

Discovered at import so `Task` is ready for the first turn; broken files are refused with a reason. Presence is not activation: an agent runs only when `[agents.<name>] enable = true` (ADR-0017). Agents live in a plain dict, so a rescan rebuilds them and `/reload` picks up edits. Each child gets its own transcript.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from un import (EXIT_OK, REGISTRY, Denied, ProviderError, Session, core, frontmatter,
                providers, run_agent, service, tool)

from un.core import CONFIG, EFFORTS, SLUG, UN_DIR, project_root

AGENTS_DIR = UN_DIR / "agents"

# Required frontmatter; the body, also required, is the system prompt.
REQUIRED = ("name", "description")

KNOWN = frozenset({"name", "description", "tools", "provider", "model", "effort",
                   "history", "max_turns"})

ENABLE = "enable"

# Selectors use `main` for the main agent, so no subagent may take it.
# rat-tail: duplicated from `hooks.py` rather than importing that plugin.
RESERVED = "main"

# Agents the learning passes run, enabled by `self_learning` (ADR-0022) in addition to ordinary activation.
LEARNING = frozenset({"detector", "admitter", "implementor", "reviser"})

# Never granted to a subagent: nothing bounds recursion depth. Dropped silently from `tools:`.
WITHHELD = "Task"

# Every valid agent, enabled or not, by frontmatter name; rebuilt on every scan.
AGENTS: dict[str, "Agent"] = {}

# Refused files and why, shown by `un agents` and `/reload`.
REFUSED: dict[str, str] = {}

# `subagent_type` gets an `enum` only when agents are enabled (an empty enum would make `Task` uncallable). Mutated in place by `_describe`.
SCHEMA: dict = {
    "type": "object",
    "properties": {
        "subagent_type": {"type": "string"},
        "prompt": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["subagent_type", "prompt"],
}

DESCRIPTION = (
    "Delegate a task to a subagent: a separate conversation with its own instructions "
    "and its own tools, which reports back one result. It cannot see this conversation, "
    "so `prompt` must carry everything it needs."
)


@dataclass(frozen=True)
class Agent:
    """One `.un/agents/**/*.md`, parsed. `enabled` is the config's answer, not the file's."""

    name: str
    description: str
    prompt: str
    path: Path
    enabled: bool
    # The `tools:` the file declared; None means all. Resolved late by `granted`, since drop-in tools register after this module.
    declared: frozenset[str] | None = None
    provider: str = ""
    # Unchecked (the endpoint judges it); "" inherits.
    model: str = ""
    # Checked against `EFFORTS`; "" inherits.
    effort: str = ""
    # A `history:` filter name, unchecked at import; "" inherits.
    history: str = ""
    # 0 uses the session's bound.
    max_turns: int = 0

    def granted(self) -> frozenset[str]:
        """The tools this agent gets from the current registry, never `WITHHELD`."""
        live = frozenset(REGISTRY["tool"]) - {WITHHELD}
        return live if self.declared is None else self.declared & live

    def missing(self) -> list[str]:
        """Declared tools that no plugin registered."""
        if self.declared is None:
            return []
        return sorted(self.declared - frozenset(REGISTRY["tool"]))


def enabled(root: Path) -> frozenset[str]:
    """Agents enabled by `[agents.<name>]`. Raises ValueError when malformed."""
    return core.enabled(root, "agents", "agent")


def _profiles(root: Path) -> tuple:
    """Every provider profile, or () when the table is malformed (the CLI reports that; raising at import would crash)."""
    try:
        return providers(root)
    except ValueError:
        return ()


def _reason(data: dict, body: str, error: str | None, root: Path) -> str | None:
    """Why this file is not an agent, or None; one distinct message per rule."""
    if error:
        return error
    for key in REQUIRED:
        if not str(data.get(key) or "").strip():
            return f"no {key} in its frontmatter"
    if not body.strip():
        return "no body, and the body is the system prompt"

    name = str(data["name"]).strip()
    if not SLUG.fullmatch(name):
        # It becomes part of the transcript filename.
        return "the name must be lowercase letters, digits and hyphens"
    if name == RESERVED:
        return (f"the name {RESERVED!r} is reserved: an agent selector uses it for the "
                "main agent")
    if name in AGENTS:
        return (f"an agent named {name!r} is already defined by "
                f"{AGENTS[name].path.name}")

    extra = sorted(set(data) - KNOWN)
    if extra:
        return f"unknown key {extra[0]!r}; known keys: {', '.join(sorted(KNOWN))}"

    if "tools" in data and not isinstance(data["tools"], (str, list)):
        # Guarded because a bad value would crash import (a bare `tools:` is None).
        return ("tools must be a tool name or a list of them, not "
                f"{type(data['tools']).__name__}")

    profile = str(data.get("provider") or "").strip()
    if profile and profile not in {p.name for p in _profiles(root)}:
        return f"provider {profile!r} names no [providers.<name>] in {CONFIG}"

    effort = str(data.get("effort") or "").strip()
    if effort and effort not in EFFORTS:
        return f"effort must be one of {', '.join(EFFORTS)}; got {effort!r}"

    turns = data.get("max_turns", 0)
    if type(turns) is not int or turns < 0:
        return "max_turns must be a whole number of turns"
    return None


def _declared(data: dict) -> frozenset[str] | None:
    """The declared `tools:` minus `WITHHELD`, or None when omitted (meaning everything, unlike an empty set)."""
    if "tools" not in data:
        return None
    return frozenset(one for one in frontmatter.entries(data["tools"]) if one != WITHHELD)


def unavailable() -> dict[str, str]:
    """A note per agent naming declared tools nothing registered; computed on demand, after all plugins load."""
    return {
        agent.name: (f"no tool named {', '.join(gone)}; {agent.name} runs without it")
        for agent in sorted(AGENTS.values(), key=lambda a: a.name)
        if (gone := agent.missing())
    }


def _describe() -> None:
    """Update `Task`'s schema enum and description in place to the enabled agents (the tool is registered once)."""
    live = sorted(name for name, agent in AGENTS.items() if agent.enabled)
    field = SCHEMA["properties"]["subagent_type"]
    field.pop("enum", None)
    if live:
        field["enum"] = live

    text = DESCRIPTION
    if live:
        text += "\n\nAvailable subagent_type values:\n" + "\n".join(
            f"- {name}: {AGENTS[name].description}" for name in live)
    else:
        text += ("\n\nNo subagents are enabled, so there is nothing to delegate to. Do "
                 "the work yourself.")
    REGISTRY["tool"][WITHHELD].un_meta["description"] = text


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Read every `.un/agents/**/*.md`, rebuilding `AGENTS`. Returns (enabled agent names, refused).

    Takes a path because it runs at import. Agents are named by frontmatter, so directories are only for arrangement.
    """
    here = Path(root or project_root() or Path.cwd())
    folder = here / AGENTS_DIR
    AGENTS.clear()
    REFUSED.clear()
    if not folder.is_dir():
        _describe()
        return [], dict(REFUSED)

    try:
        on = enabled(here)
    except ValueError as exc:
        # Reported, and every agent off, rather than crashing (ADR-0014).
        REFUSED[CONFIG] = str(exc)
        on = frozenset()

    for path in sorted(folder.rglob("*.md")):
        key = path.relative_to(folder).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # An unreadable file must not crash import.
            REFUSED[key] = f"could not be read: {exc.strerror}"
            continue
        data, body, error = frontmatter.parse(text)
        if refusal := _reason(data, body, error, here):
            REFUSED[key] = refusal
            continue

        name = str(data["name"]).strip()
        AGENTS[name] = Agent(
            name=name,
            description=str(data["description"]).strip(),
            prompt=body,
            path=path,
            enabled=name in on,
            declared=_declared(data),
            provider=str(data.get("provider") or "").strip(),
            model=str(data.get("model") or "").strip(),
            effort=str(data.get("effort") or "").strip(),
            history=str(data.get("history") or "").strip(),
            max_turns=int(data.get("max_turns", 0)),
        )

    _describe()
    return sorted(name for name, agent in AGENTS.items() if agent.enabled), dict(REFUSED)


def _child(session: Session, agent: Agent) -> Session:
    """A fork with the agent's prompt, tools and profile and none of the parent's conversation.

    The four prompt fields reset together, so SessionStart shapes the child's own prompt.
    """
    child = session.fork(agent.name)
    # Set explicitly: a fork off the main agent would otherwise inherit "".
    child.agent = agent.name
    child.system = agent.prompt
    child.system_base = None
    child.system_digest = None
    child.context_injected = False
    child.tools = agent.granted()
    # Learning passes have nobody to answer an ask (approval:cli would interrupt the operator's REPL), so `self_learning` is the consent. Asks are still evaluated, so floor DENYs hold, and `approval:yes` never answers "always".
    if agent.name in LEARNING and session.self_learning:
        child.approval = "yes"
    # Silent, so its tool traffic is not mistaken for the main conversation's; its transcript still records everything.
    child.emit = None

    if agent.provider:
        # A profile applies whole (ADR-0018).
        profile = next(
            (p for p in _profiles(session.root) if p.name == agent.provider), None)
        if profile is not None:
            child.provider = profile.name
            child.model = profile.model or child.model
            child.effort = profile.effort or child.effort
            # A profile's 0 means "none stated", not zero turns.
            child.max_turns = profile.max_turns or child.max_turns

    # The agent's own keys override the profile's; "" inherits.
    if agent.model:
        child.model = agent.model
    if agent.effort:
        child.effort = agent.effort
    if agent.history:
        child.history = agent.history
    return child


@service("agents:run")
def run(session: Session, subagent_type: str, prompt: str, emit=None) -> str:
    """Run one subagent to a stopping point and return its answer. Refusals return text; other failures raise for the caller to handle.

    `emit` opts the child's traffic onto a sink; `Session.say` tags each line with the agent's name so it is not mistaken for the main conversation.
    """
    agent = AGENTS.get(subagent_type)
    if agent is None:
        known = ", ".join(sorted(AGENTS)) or "none"
        return f"refused: no agent named {subagent_type!r}; defined: {known}"
    if not agent.enabled and not (agent.name in LEARNING and session.self_learning):
        return (f"refused: the agent {subagent_type!r} is present but not enabled; add "
                f"[agents.{subagent_type}] with {ENABLE} = true to {CONFIG}")

    child = _child(session, agent)
    if emit is not None:
        # Unwrapped: `Session.say` already adds the agent tag.
        child.emit = emit
    reply = run_agent(child, prompt, max_turns=agent.max_turns or child.max_turns)
    if reply is None:
        return "the subagent ran no turns"
    # Thread-safe add, since parallel `Task` calls finish on pool threads.
    session.spend(child.tokens)
    return reply.text or "[the subagent returned no text]"


@tool(WITHHELD, DESCRIPTION, SCHEMA)
def task(*, session: Session, subagent_type: str, prompt: str,
         description: str = "") -> str:
    """Run one subagent and return its answer as this call's result. Every failure returns text.

    `description` is unused here but rendered by interfaces while the child runs.
    """
    try:
        # Only when the parent has a sink: a non-None emit suppresses the stderr fallback of `report`.
        return run(session, subagent_type, prompt,
                   emit=session.say if session.emit is not None else None)
    except Denied as exc:
        # A headless deny ends the child's run, not the parent's.
        return f"the subagent was stopped: {exc.verdict.reason}"
    except ProviderError as exc:
        # Already prefixed with the provider's exception type.
        text = str(exc)
        session.report(subagent_type, text)
        return f"the subagent failed: {text}"
    except Exception as exc:  # noqa: BLE001
        # Broad: some provider errors (e.g. a wrong model) arrive as raw SDK exceptions. Reported on the parent, since the child is silent.
        text = f"{type(exc).__name__}: {exc}"
        session.report(subagent_type, text)
        return f"the subagent failed: {text}"


@service("agents:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/agents/` for `/reload`, including tools asked for but unavailable."""
    registered, refused = discover(cwd)
    # Not in `discover`, which also runs at import before the registry is complete.
    return registered, {**refused, **unavailable()}


@service("agents:names")
def names() -> frozenset[str]:
    """Every defined agent, enabled or not, without rescanning. Used by `hooks.py` to check `agent:` selectors."""
    return frozenset(AGENTS)


@service("command:agents")
def agents_(args: argparse.Namespace) -> int:
    """list the subagents defined in .un/agents/, which are enabled, and what was refused"""
    discover()

    live = [a for a in sorted(AGENTS.values(), key=lambda a: a.name) if a.enabled]
    idle = [a for a in sorted(AGENTS.values(), key=lambda a: a.name) if not a.enabled]
    if live:
        print("enabled:\n" + "\n".join(
            f"  {a.name:<16} {a.description}" for a in live))
    if idle:
        print(("\n" if live else "") + f"present, not enabled - add [agents.<name>] with "
              f"{ENABLE} = true to {CONFIG}:\n" + "\n".join(
                  f"  {a.name:<16} {a.description}" for a in idle))
    if not AGENTS:
        print(f"no agents in {AGENTS_DIR}/")
    if REFUSED:
        print("\nnot registered:\n" + "\n".join(
            f"  {key}: {why}" for key, why in sorted(REFUSED.items())))
    if gone := unavailable():
        print("\ntools asked for and not registered:\n" + "\n".join(
            f"  {name}: {why}" for name, why in sorted(gone.items())))
    return EXIT_OK


# At import, so `Task`'s agent enum is ready for the first turn.
discover()

if REFUSED:
    # Stderr is the only channel at import time.
    print("\n".join(f"un: agents: {key}: {why}" for key, why in sorted(REFUSED.items())),
          file=sys.stderr)
