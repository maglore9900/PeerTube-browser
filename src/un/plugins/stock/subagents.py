"""Subagents: `.un/agents/**/*.md` definitions run as forked conversations through the `Task` tool. Writes nothing itself.

Discovered at import so `Task` is ready for the first turn; broken files are refused with a reason. Presence is not activation: an agent runs only when `[agents.<name>] enable = true` (ADR-0017). A `tools:` entry written `Tool(x, ...)` is parsed by `core.parse_scopes` and served through `agents:scopes`. Agents live in a plain dict, so a rescan rebuilds them and `/reload` picks up edits. Each child gets its own transcript.
"""

from __future__ import annotations

import argparse
import sys
import threading
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from un import (EXIT_OK, REGISTRY, Denied, ProviderError, Session, core, frontmatter,
                providers, run_agent, service, tool, use)

from un.core import CONFIG, EFFORTS, SLUG, UN_DIR, parse_scopes, project_root, scan

AGENTS_DIR = UN_DIR / "agents"

# Required frontmatter; the body, also required, is the system prompt.
REQUIRED = ("name", "description")

KNOWN = frozenset({"name", "description", "tools", "provider", "model", "effort",
                   "history", "max_turns"})

ENABLE = "enable"

# Selectors use `main` for the main agent, so no subagent may take it.
# rat-tail: duplicated from `hooks.py` rather than importing that plugin.
RESERVED = "main"

# Agents of the learning loop, enabled by `self_learning` (ADR-0022) in addition to ordinary activation: the passes' agents, and the applier `/apply-amendment` dispatches.
LEARNING = frozenset({"detector", "admitter", "implementor", "accuracy-auditor", "memory-editor",
                      "amendment-applier"})

# Agents `un install` seeds, never granted `Task`: a learning fork answers its own asks, and that consent must not reach a descendant.
# rat-tail: the learning agents are every stock agent today; add another here if install seeds one.
STOCK = LEARNING

TASK = "Task"

# The `Session.state` key naming the Task call a child runs for, which `transcript.py` stamps on its usage rows.
# rat-tail: duplicated in `transcript.py` rather than importing that plugin.
RUN_KEY = "subagents.run"

# Scalar keys of `[agents]`, beside the activation sub-tables, and their defaults.
BOUNDS = {"max_task_depth": 3, "max_running": 20}
# The bounds in force.
LIMITS: dict[str, int] = dict(BOUNDS)

# Subagents running now across the process, which `max_running` bounds.
_running = 0
_slots = threading.Lock()

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
    # The `tools:` the file declared; omitted grants nothing. Resolved late by `granted`, since drop-in tools register after this module.
    declared: frozenset[str] = frozenset()
    provider: str = ""
    # Unchecked (the endpoint judges it); "" inherits.
    model: str = ""
    # Checked against `EFFORTS`; "" inherits.
    effort: str = ""
    # A `history:` filter name, unchecked at import; "" inherits.
    history: str = ""
    # 0 uses the session's bound.
    max_turns: int = 0
    # Tool -> the specs its `Tool(...)` entries scope it to; a tool absent here is unscoped.
    scopes: dict[str, tuple[str, ...]] = field(default_factory=dict, hash=False)

    def granted(self) -> frozenset[str]:
        """The declared tools the current registry holds, less `Task` for a stock agent."""
        granted = self.declared & frozenset(REGISTRY["tool"])
        return granted - {TASK} if self.name in STOCK else granted

    def missing(self) -> list[str]:
        """Declared tools that no plugin registered."""
        return sorted(self.declared - frozenset(REGISTRY["tool"]))


def _bounds(root: Path) -> dict[str, int]:
    """`[agents]`'s bounds over their defaults. Raises ValueError naming a bad one."""
    path = Path(root) / CONFIG
    table = tomllib.loads(path.read_text(encoding="utf-8")).get("agents", {}) if path.is_file() else {}
    table = table if isinstance(table, dict) else {}
    found = {key: table.get(key, default) for key, default in BOUNDS.items()}
    for key, value in found.items():
        # `type`, not `isinstance`: bool is an int.
        if type(value) is not int or value < 0:
            raise ValueError(f"{path}: [agents].{key} must be a whole number, 0 or more, "
                             f"not {value!r}")
    return found


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


def _declared(data: dict) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    """The declared `tools:` and its scopes; an omitted key grants nothing. Raises ValueError."""
    if "tools" not in data:
        return frozenset(), {}
    return parse_scopes(data["tools"])


def _known(tool: str, root: Path) -> frozenset[str] | None:
    """What a `tool` scope may name, or None when nothing can say: an unchecked tool, or the plugin that knows is off.

    `SkillManage` is unchecked because it may create the skill it names.
    """
    try:
        if tool == "Skill":
            return frozenset(use("skills", "names")(root))
        if tool == "Recall":
            return frozenset(use("memory", "names")(root))
    except LookupError:
        return None
    if tool == "Workflow":
        return frozenset(core.variants("workflow"))
    if tool == TASK:
        return frozenset(AGENTS)
    return None


def unavailable(root: Path | None = None) -> dict[str, str]:
    """A note per agent naming declared tools nothing registered and scoped names nothing matches; computed on demand, after all plugins load."""
    # Resolved upward, since `/reload` passes the operator's cwd rather than the project root.
    here = project_root(root) or Path(root or Path.cwd())
    notes = {}
    for agent in sorted(AGENTS.values(), key=lambda a: a.name):
        found = []
        if gone := agent.missing():
            found.append(f"no tool named {', '.join(gone)}; {agent.name} runs without it")
        for scoped_tool, specs in sorted(agent.scopes.items()):
            known = _known(scoped_tool, here)
            if known is not None and (absent := [s for s in specs if s not in known]):
                found.append(f"{scoped_tool} is scoped to {', '.join(absent)}, which "
                             "names nothing")
        if found:
            notes[agent.name] = "; ".join(found)
    return notes


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
    REGISTRY["tool"][TASK].un_meta["description"] = text


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    AGENTS.clear()
    LIMITS.clear()
    LIMITS.update(BOUNDS)
    try:
        LIMITS.update(_bounds(Path(root or project_root() or Path.cwd())))
        bad = None
    except ValueError as exc:
        bad = str(exc)

    def read(where: Path, path: Path, text: str, on) -> str | None:
        data, body, error = frontmatter.parse(text)
        if refusal := _reason(data, body, error, where):
            return refusal
        try:
            declared, scoped = _declared(data)
        except ValueError as exc:
            return f"tools: {exc}"
        name = str(data["name"]).strip()
        AGENTS[name] = Agent(
            name=name,
            description=str(data["description"]).strip(),
            prompt=body,
            path=path,
            # A bad bound turns every agent off (ADR-0014).
            enabled=name in on and bad is None,
            declared=declared,
            scopes=scoped,
            provider=str(data.get("provider") or "").strip(),
            model=str(data.get("model") or "").strip(),
            effort=str(data.get("effort") or "").strip(),
            history=str(data.get("history") or "").strip(),
            max_turns=int(data.get("max_turns", 0)),
        )
        return None

    REFUSED.clear()
    REFUSED.update(scan(root, "agents", AGENTS_DIR, "**/*.md", read,
                        section="agents", noun="agent", settings=frozenset(BOUNDS)))
    if bad:
        # setdefault: an unparseable file is already reported by `scan`.
        REFUSED.setdefault(CONFIG.as_posix(), bad)
    _describe()
    return sorted(name for name, agent in AGENTS.items() if agent.enabled), dict(REFUSED)


def _child(session: Session, agent: Agent) -> Session:
    """A fork with the agent's prompt, tools and profile and none of the parent's conversation."""
    child = session.fork(agent.name)
    # Set explicitly: a fork off the main agent would otherwise inherit "".
    child.agent = agent.name
    # Every run of one agent shares one record, so this id is what tells the runs apart. `fork` resets `state`, so a grandchild never inherits it.
    child.state[RUN_KEY] = uuid.uuid4().hex
    child.system = agent.prompt
    # Shared with workflow nesting, and copied by every fork below, so depth is per path.
    child.workflow_depth = session.workflow_depth + 1
    child.tools = agent.granted()
    if child.workflow_depth >= LIMITS["max_task_depth"]:
        # The floor: dispatch refuses an ungranted tool, so taking it away is the enforcement.
        child.tools = child.tools - {TASK}
    # Learning passes have nobody to answer an ask (approval:cli would interrupt the operator's REPL), so `self_learning` is the consent; for `amendment-applier` the operator naming the plan is. Asks are still evaluated, so floor DENYs hold, and `approval:yes` never answers "always".
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
    depth = session.workflow_depth + 1
    if depth > LIMITS["max_task_depth"]:
        return (f"refused: a subagent started here would be {depth} deep and "
                f"[agents].max_task_depth in {CONFIG} is {LIMITS['max_task_depth']}")

    global _running
    with _slots:
        if _running >= LIMITS["max_running"]:
            return (f"refused: {_running} subagents are already running and "
                    f"[agents].max_running in {CONFIG} is {LIMITS['max_running']}; wait for one "
                    "to finish or do the work yourself")
        _running += 1
    try:
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
    finally:
        with _slots:
            _running -= 1


@tool(TASK, DESCRIPTION, SCHEMA)
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
        # Broad: some provider errors (e.g. a wrong model) arrive as raw SDK exceptions. Reported on the parent session, which reaches its sink or stderr whatever the child's sink.
        text = f"{type(exc).__name__}: {exc}"
        session.report(subagent_type, text)
        return f"the subagent failed: {text}"


@service("agents:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/agents/` for `/reload`, including tools asked for but unavailable."""
    registered, refused = discover(cwd)
    # Not in `discover`, which also runs at import before the registry is complete.
    return registered, {**refused, **unavailable(cwd)}


@service("agents:scopes")
def scoped(name: str) -> dict[str, tuple[str, ...]]:
    """An agent's tool scopes by agent name, or {} for an unknown agent. Reads the table without rescanning."""
    agent = AGENTS.get(name)
    return dict(agent.scopes) if agent else {}


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
