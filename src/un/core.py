"""The core: the plugin registry, the extension contract, and the agent loop.

Plugins import core and never the CLI, so anything shared between plugins lives here, including path constants whose writers are plugins. The permission table, the approval adapters, the allow-rule writer and subagent scopes live here too and register when this module is imported, so no plugin toggle reaches them.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import tomllib
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib.metadata import entry_points
from pathlib import Path
from secrets import token_hex
from types import ModuleType
from typing import Callable, TextIO

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None

# Only this project declares the stock group; `--disable-plugin` relies on that.
STOCK_GROUP = "un.plugins.stock"
AFTERMARKET_GROUP = "un.plugins"

ALIASES = Path(__file__).parent / "alias.json"

# What a `command:` service returns, and what `main` exits with.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
# Bound reached with tool calls outstanding; distinct so a caller can retry with a larger `--max-turns`.
EXIT_EXHAUSTED = 3
# 128 + SIGINT, the shell convention.
EXIT_INTERRUPTED = 130

REGISTRY: dict[str, dict[str, Callable]] = {"service": {}, "tool": {}, "hook": {}}

# The event contract, in full; `hook` validates against it at decoration.
#   collect: call every hook, gather the non-None returns.
#   chain:   fold one value through every hook; each may return a replacement.
EVENTS: dict[str, str] = {
    "SessionStart": "collect: each str returned is appended to the system prompt",
    "UserPromptSubmit": "chain(str): the user's prompt, before it is sent",
    "PreToolUse": "collect: return a Verdict to deny, ask or allow; None means no "
                  "opinion, and no opinion from anybody refuses the call",
    "PostToolUse": "chain(str): the tool's result text, before the model sees it",
    "TurnStart": "collect: each str returned is appended to messages as an operator "
                 "system message, after the user message and before the loop runs",
    "ToolResults": "collect: each str returned is appended to messages as an operator "
                   "system message, once per tool BATCH, after the results the model "
                   "asked for and before its next turn. NOT PostToolUse: that folds one "
                   "call's result text and cannot keep the system role",
    "Turn": "collect: returns ignored; fires after each assistant reply",
    "TurnEnd": "collect: returns ignored; fires once when a turn is finished and un is "
               "ready for input, AFTER the turn is recorded, and on the interrupted path "
               "too with interrupted=True. NOT Turn: that fires per assistant reply, so a "
               "tool loop produces several of them for one turn",
    "OperatorWaitStart": "collect: returns IGNORED; fires when un stops and waits on a "
                "person - an ASK verdict's approval prompt, or the AskUser "
                "tool. Returns are ignored so a hook cannot answer for them",
    "OperatorWaitEnd": "collect: returns IGNORED; fires when that wait ends, however it "
                "ended - answered, declined, or the adapter raised. Guaranteed to "
                "follow every OperatorWaitStart",
    "ToolEnd": "collect: returns ignored; fires once per ATTEMPTED tool call - "
               "including one a verdict refused, which never ran - with the verdict "
               "and the outcome. NOT PostToolUse: that folds the result text before "
               "the model reads it and never sees a denial",
    "SessionEnd": "collect: returns ignored; fires once when an operator's session is "
                "over, with the exit code it ended on, if SessionStart fired in that "
                "session or in any FORK of it (a subagent, or a workflow the Workflow "
                "tool or /workflows:<name> launched). A session that started nothing "
                "fires none. A fork never fires this itself, because only a CLI verb "
                "ends a session. NOT TurnEnd: that fires once per turn, so a "
                "conversation produces many of them and exactly one of these, last",
}


class Quit(Exception):
    """A slash command asked the interface to stop."""


class RunPrompt(Exception):
    """A slash command produced a prompt for the model rather than text to show."""

    def __init__(self, prompt: str) -> None:
        super().__init__(prompt)
        self.prompt = prompt


class NoSuchCommand(Exception):
    """No `slash:` service claims this command name. Not a LookupError, so it differs from one raised inside a command."""


class RecordUnavailable(RuntimeError):
    """Recording was asked for and can never work. Not for a mid-run write failure, which is reported and survived."""


class ProviderError(RuntimeError):
    """A provider could not serve the request, for a reason the user can act on."""


def _register(extension: str, name: str, **meta):
    def decorate(fn):
        if name in REGISTRY[extension]:
            raise ValueError(f"{extension} {name!r} is already registered")
        fn.un_name, fn.un_extension, fn.un_meta = name, extension, meta
        REGISTRY[extension][name] = fn
        return fn

    return decorate


def _drop(module: str) -> None:
    """Remove every registration made by `module`."""
    for entries in REGISTRY.values():
        for key in [k for k, fn in entries.items() if fn.__module__ == module]:
            del entries[key]


def service(key: str):
    """A named capability, conventionally `namespace:name`; one implementation is selected per key at call time."""
    return _register("service", key)


# Reserved: `Tool(NAME)` is the permission rule claiming a whole tool.
RESERVED_TOOL = "Tool"


def tool(name: str, description: str, schema: dict | Callable[[Session], dict | None]):
    """A callable the model may invoke. `schema` is JSON Schema for its kwargs, or a callable taking the session and
    returning it - or None, which hides the tool from that conversation."""
    if name == RESERVED_TOOL:
        raise ValueError(
            f"tool name {name!r} is reserved: it is the permission rule that claims"
            " a whole tool by name")
    return _register("tool", name, description=description, schema=schema)


def hook(event: str):
    """An observer or gate on `event`. See EVENTS for what a return value means."""
    if event not in EVENTS:
        raise ValueError(f"unknown hook event {event!r}; known: {', '.join(EVENTS)}")

    def decorate(fn):
        _register("hook", f"{event}:{fn.__module__}.{fn.__qualname__}", event=event)(fn)
        return fn

    return decorate


def _hooks(event: str) -> list[Callable]:
    return [h for h in REGISTRY["hook"].values() if h.un_meta["event"] == event]


def fire(event: str, **kw) -> list:
    """Call every hook for `event` and return the non-None results. OperatorWaitEnd also resets an attended session's unattended-turn count."""
    if event == "OperatorWaitEnd":
        session = kw.get("session")
        if session is not None and not session.headless:
            session.attended()
    return [r for h in _hooks(event) if (r := h(**kw)) is not None]


def chain(event: str, value, **kw):
    """Fold `value` through every hook for `event`. Returning None passes through."""
    for h in _hooks(event):
        value = h(value=value, **kw) or value
    return value


def variants(namespace: str) -> dict[str, Callable]:
    """Every service under `namespace`, name -> callable, sorted."""
    prefix = f"{namespace}:"
    return {
        key.split(":", 1)[1]: fn
        for key, fn in sorted(REGISTRY["service"].items())
        if key.startswith(prefix)
    }


def use(namespace: str, name: str):
    """Look up one service by namespace and name, at call time."""
    fn = REGISTRY["service"].get(f"{namespace}:{name}")
    if fn is None:
        available = ", ".join(variants(namespace)) or "none"
        raise LookupError(f"no {namespace} {name!r}; available: {available}")
    return fn


# In core so disabling a plugin cannot remove the REPL's exit.
QUIT = frozenset({"quit", "exit", "q"})

# Shape for any supplied string that becomes a path segment or command name.
SLUG = re.compile(r"[a-z0-9-]+")

# Channels written to stderr, and their gutters. A channel absent here is not written at all.
NOTED = {"tool": "  . ", "tool_result": "  | ", "note": ""}

# What an interrupted turn leaves for the model to read.
INTERRUPTED_RESULT = "The operator interrupted this call before it finished."

# Loop-level argument, stripped before the verdict and the call so no rule or tool sees it.
BACKGROUND = "background"
BACKGROUND_FIELD = {
    "type": "boolean",
    "description": "Run this call without holding the conversation. Returns a receipt at "
                   "once; the real output arrives in a later message. Use it when the work "
                   "is long and there is something else worth doing meanwhile.",
}
# AskUser needs an answer now, and an accepted Submit must end the run within its batch.
NEVER_BACKGROUND = frozenset({"AskUser", "Submit"})
RECEIPT = ("Started in the background as job {id}. This call is not finished; its output "
           "arrives in a later message. Carry on with something else.")
DELIVERED = "Job {id} ({shown}) finished:\n{result}"
STOPPED = "Job {id} ({shown}) was cancelled: the turn ended before it finished."
INTERRUPTED_NOTE = "The operator interrupted this turn before it finished."


def refused(kind: str, name: str) -> str | None:
    """The refusal a supplied name earns, or None when it is safe as a path segment.

    `fullmatch`, because `SLUG` is unanchored and a search would accept `../../etc`.
    """
    if SLUG.fullmatch(name):
        return None
    return f"bad {kind} name {name!r}: lowercase letters, digits and hyphens only"


def slash(session, line: str) -> str | None:
    """Handle a /command locally. Returns text to show, or None if the line is not a command.

    Raises `Quit` for a quit spelling and `NoSuchCommand` when nothing claims the name.
    """
    if not line.startswith("/"):
        return None
    name, _, rest = line[1:].partition(" ")
    if name in QUIT:
        raise Quit()
    try:
        found = use("slash", name)
    except LookupError as exc:
        raise NoSuchCommand(str(exc)) from exc
    # Outside the try: a LookupError raised inside the command is not a missing command.
    return found(session, rest.strip())


def _refuse(ep) -> str | None:
    """Import one aftermarket entry point; return why it was refused, or None.

    `UN_PLUGIN` can only be read after the import, so a refusal undoes it.
    """
    module = ep.value
    try:
        loaded = ep.load()
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    else:
        declared = getattr(loaded, "UN_PLUGIN", None)
        described = declared.get("description") if isinstance(declared, dict) else None
        if isinstance(described, str) and described.strip():
            return None
        reason = ("it does not declare itself; an aftermarket plugin needs a module-level"
                  ' UN_PLUGIN = {"description": "..."} carrying a non-empty description,'
                  " which is what `un plugins` prints")
    _drop(module)
    sys.modules.pop(module, None)
    return reason


# The disabled set the last `load` applied, grown by the plugins it took with it, and what it cost: plugin name -> what the operator is told.
# Rebound, never mutated, so a reader mid-reload sees one whole value.
DISABLED: frozenset[str] = frozenset()
FALLOUT: dict[str, str] = {}


def load(extra: tuple[str, ...] = (), disabled: frozenset[str] = frozenset(),
         enabled: frozenset[str] = frozenset()) -> None:
    """Import every enabled plugin module, then every module named in `extra`, then `_settle` what that left.

    Stock first, so an aftermarket plugin claiming a stock key fails rather than displacing it.
    """
    global DISABLED
    # Before any import, so a tool reading it mid-reload never imports what is being dropped.
    DISABLED = frozenset(disabled)
    for group in (STOCK_GROUP, AFTERMARKET_GROUP):
        aftermarket = group is AFTERMARKET_GROUP
        for ep in sorted(entry_points(group=group), key=lambda e: e.name):
            if ep.name in disabled or (aftermarket and ep.name not in enabled):
                continue
            if not aftermarket:
                ep.load()
            elif reason := _refuse(ep):
                print(f"{ep.name}: refused, {reason}", file=sys.stderr)
    for module in extra:
        # Operator-named (config or `--plugin`), the same trust boundary as the API key.
        # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
        importlib.import_module(module)
    _settle()


def _settle() -> None:
    """Drop every disabled plugin however it was imported, then every live plugin holding one of its objects, until nothing changes.

    An object is matched by `__module__` (a module by `__name__`) equal to a disabled plugin's module, so `un`, `un.core` and helper modules never match, and a plain value imported from a disabled plugin carries none and leaves its importer running. Rebinds `DISABLED` and `FALLOUT`.
    """
    global DISABLED, FALLOUT
    modules = {p.name: p.module for p in plugin_table()}
    owners = {module: name for name, module in modules.items()}
    off, fallout = set(DISABLED), {}
    while True:
        gone = {modules[name] for name in off if name in modules}
        for module in gone & sys.modules.keys():
            _drop(module)
            sys.modules.pop(module)
        caught = {}
        for name, module in modules.items():
            live = sys.modules.get(module)
            if live is None or name in off:
                continue
            for value in vars(live).values():
                owner = value.__name__ if isinstance(value, ModuleType) else getattr(value, "__module__", None)
                if owner in gone:
                    caught[name] = owners[owner]
                    break
        if not caught:
            break
        fallout |= {name: f"disabled - it imports {cause}, which is disabled" for name, cause in caught.items()}
        off |= caught.keys()
    # After the fixpoint, so a plugin it took off is no longer live and gets no degraded entry.
    for name, module in modules.items():
        live = sys.modules.get(module)
        for needed, lost in (getattr(live, "UN_DEGRADED_WITHOUT", None) or {}).items():
            if needed in off:
                fallout[name] = f"degraded - {needed} is disabled, so {lost}"
    DISABLED, FALLOUT = frozenset(off), fallout


def reapply(session: Session, disabled: frozenset[str] = frozenset(),
            enabled: frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """Re-apply the enabled plugin set to a running session. Returns (added, dropped).

    Dropped modules leave `sys.modules` so `load` can import them again. The system prompt is always re-based, since skills and rules change without a config change. `--plugin` extras are untouched. See ADR-0016.
    """
    declared = plugin_table()
    live = {p.name for p in declared if p.module in sys.modules}

    dropped = []
    for plugin in declared:
        if plugin.name not in live:
            continue
        if plugin.name in disabled or (not plugin.stock and plugin.name not in enabled):
            _drop(plugin.module)
            sys.modules.pop(plugin.module, None)
            dropped.append(plugin.name)

    load(disabled=disabled, enabled=enabled)
    added = sorted({p.name for p in declared if p.module in sys.modules} - live)

    session.rebase()

    return added, dropped


def plugin_names() -> tuple[frozenset[str], frozenset[str]]:
    """Every declared plugin name as (stock, aftermarket). Imports nothing."""
    table = plugin_table()
    return (
        frozenset(p.name for p in table if p.stock),
        frozenset(p.name for p in table if not p.stock),
    )


@dataclass(frozen=True)
class Plugin:
    """One declared plugin. `description` is empty for an aftermarket plugin, since reading it needs the import."""

    name: str
    module: str
    description: str
    stock: bool


def plugin_table() -> tuple[Plugin, ...]:
    """Every declared plugin, sorted by name. Raises ValueError when `alias.json` disagrees with the entry points."""
    stock = {ep.name: ep.value for ep in entry_points(group=STOCK_GROUP)}
    aftermarket = {ep.name: ep.value for ep in entry_points(group=AFTERMARKET_GROUP)}
    if both := sorted(stock.keys() & aftermarket.keys()):
        raise ValueError(
            f"{', '.join(both)}: claimed by a stock plugin and an aftermarket one; "
            "a plugin name must reach exactly one plugin")

    try:
        described = json.loads(ALIASES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{ALIASES}: {exc}") from exc

    if missing := sorted(stock.keys() - described.keys()):
        raise ValueError(f"{ALIASES}: no entry for {', '.join(missing)}")
    if extra := sorted(described.keys() - stock.keys()):
        raise ValueError(
            f"{ALIASES}: {', '.join(extra)} names no plugin; "
            f"declared: {', '.join(sorted(stock))}")
    for name, module in stock.items():
        declared, actual = described[name]["file"], f"{module.rsplit('.', 1)[-1]}.py"
        if declared != actual:
            raise ValueError(
                f"{ALIASES}: {name} says {declared!r}, but the entry point names "
                f"{actual!r}")

    return tuple(sorted(
        [Plugin(n, m, described[n]["description"], True) for n, m in stock.items()]
        + [Plugin(n, m, "", False) for n, m in aftermarket.items()],
        key=lambda p: p.name,
    ))


@dataclass(frozen=True)
class CacheSpec:
    """What the harness holds stable in its prompt, for providers to translate into caching."""

    # Stable against accidents; `reapply` re-bases deliberately.
    system_stable: bool = True
    # `messages` only ever grows at the end.
    history_append_only: bool = True


class CacheInvariantError(RuntimeError):
    """The harness moved something `CacheSpec` promised to hold still. Raised, because a broken prefix silently re-bills the whole history every turn."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_spec(session: Session) -> CacheSpec:
    """What this session currently guarantees."""
    return CacheSpec(system_stable=session.system_digest is not None,
                     history_append_only=not session.history)


def _sent(session: Session) -> list[dict]:
    """The messages sent this turn: `session.messages` or a `history:` filter's projection of them, then whatever `compaction:send` makes of that list when the service is registered. Never mutates."""
    messages = use("history", session.history)(session) if session.history else session.messages
    # Only the lookup is guarded: a LookupError raised inside the service is a bug, not "no service".
    try:
        send = use("compaction", "send")
    except LookupError:
        return messages
    return send(session, messages)


def _check_prefix(session: Session) -> None:
    """Raise if the system prompt or the history moved. Runs before anything is appended."""
    if (session.system_digest is not None
            and _digest(session.system) != session.system_digest):
        raise CacheInvariantError(
            "session.system changed after SessionStart shaped it, so every later turn "
            "re-bills the whole prompt uncached. Inject per-turn text through the "
            "TurnStart event, which appends and leaves the prefix alone."
        )
    if len(session.messages) < session.messages_watermark:
        raise CacheInvariantError(
            f"session.messages shrank from {session.messages_watermark} to "
            f"{len(session.messages)}. History is append-only: a rewrite invalidates "
            "every cached prefix behind it."
        )


# What a PreToolUse verdict can decide.
DENY = "deny"
ASK = "ask"
# Matches the Claude Agent SDK's permissionDecision literal.
ALLOW = "allow"

# Most restrictive first.
_PRECEDENCE = (DENY, ASK, ALLOW)


@dataclass(frozen=True)
class Verdict:
    """A PreToolUse hook's opinion. No opinion is None, and None is not an approval."""

    decision: str
    reason: str
    # The rule that fired, as `Rule.text`; empty when no rule decided.
    rule: str = ""


def decide(verdicts: list[Verdict]) -> Verdict | None:
    """The verdict to act on: DENY over ASK over ALLOW. None means nobody answered, which is a refusal."""
    for decision in _PRECEDENCE:
        for verdict in verdicts:
            if verdict.decision == decision:
                return verdict
    return None


class Denied(Exception):
    """A headless run hit a DENY. With nobody to redirect the model, the run ends."""

    def __init__(self, verdict: Verdict):
        self.verdict = verdict
        super().__init__(verdict.reason)


@dataclass(frozen=True)
class Gate:
    """What the PreToolUse protocol decided about one tool call. `verdict` is None only when nobody answered."""

    # rat-tail: bare outcome strings; promote to constants if an out-of-tree caller reads them.
    outcome: str
    verdict: Verdict | None
    # For the model; empty when the call runs.
    message: str = ""


def gate(session: Session, name: str, args: dict, call: dict,
         *, lock=nullcontext()) -> Gate:
    """Run the PreToolUse protocol for one tool call, stamping the outcome onto `call` in place.

    Headless is not checked on ASK: the approval adapter fails closed. The caller fires `ToolEnd`.
    """
    shown = use("permissions", "describe")(name, args)
    call["shown"] = shown
    session.say("tool", shown)
    verdict = decide(fire("PreToolUse", session=session, name=name, args=args))
    if verdict is None:
        # No opinion is a refusal (ADR-0001).
        call["reason"] = f"nothing authorised {name}"
        return Gate("blocked", None, f"Blocked: nothing authorised {name}")
    call |= {"decision": verdict.decision, "rule": verdict.rule,
             "reason": verdict.reason}
    if verdict.decision == DENY:
        return Gate("denied" if session.headless else "blocked", verdict,
                    f"Blocked: {shown} - {verdict.reason}")
    if verdict.decision == ASK:
        # Answered here: a backend owning the loop has no interactive surface.
        try:
            approve = use("approval", session.approval)
        except LookupError as exc:
            # Caught here because the SDK swallows exceptions escaping its hooks.
            call["reason"] = str(exc)
            return Gate("blocked", verdict, f"Blocked: {exc}")
        # An empty `rule` means "always" is not offered.
        question, rule = use("permissions", "ask")(session, name, args, verdict)
        # After the approver lookup, so a run with no approver reports no wait.
        fire("OperatorWaitStart", session=session, name=name, reason=verdict.reason)
        try:
            with lock:
                answer = approve(session, question, always=bool(rule))
        finally:
            fire("OperatorWaitEnd", session=session, name=name)
        # Absent means nobody was asked. Membership, so an adapter returning True is a refusal.
        call["approved"] = answer in {"yes", "always"}
        if answer == "always":
            session.say("tool", use("permissions", "remember")(session, name, args))
        if not call["approved"]:
            return Gate("blocked", verdict,
                        f"Declined by the user: {shown} - {verdict.reason}")
    return Gate("run", verdict)


@dataclass(frozen=True)
class Reply:
    """One assistant turn. `content` is Anthropic content-block JSON, the harness's canonical shape."""

    content: list[dict]
    stop_reason: str
    usage: dict

    @property
    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b["type"] == "text")


def _fresh() -> dict:
    """Per-conversation state, freshly built. `fork` and `adopt` reset these fields."""
    return {
        "messages": [],
        "transcript_cursor": 0,
        "files_read": {},
        "state": {},
        "last_recorded": None,
        "messages_watermark": 0,
        "turn_index": 0,
        "unattended_turns": 0,
        "tokens": 0,
        "jobs": {},
        "end_turn": False,
    }


@dataclass
class Job:
    """One tool call in flight, background or not, so an interrupt can reach it. `cancels` is kept off `row`, which is JSON-serialised."""

    block: dict                                    # the `tool_use` it answers
    row: dict                                      # the record row, open until work ends
    # True when the loop continues without waiting for it.
    background: bool = False
    future: Future | None = None
    cancels: list[Callable[[], None]] = field(default_factory=list)
    # Cancelled because the run ended on `end_turn`.
    stopped: bool = False


# The job on this thread; a ContextVar because several calls run concurrently.
_CURRENT: ContextVar[Job | None] = ContextVar("un_current_job", default=None)


def on_cancel(stop: Callable[[], None]) -> None:
    """Register a callable that stops the current tool call's work. A no-op outside a tool call.

    Signals reach only the main thread, so cancellation is a handle, not an exception. Register only what ends the work; the worker cleans up as it unwinds.
    """
    job = _CURRENT.get()
    if job is not None:
        job.cancels.append(stop)


@dataclass
class Session:
    """One conversation's mutable state."""

    id: str
    cwd: Path
    system: str
    # The project root (nearest `.un/`); `cwd` stays where the operator is (ADR-0019). Filled by `__post_init__`.
    root: Path = None  # pyright: ignore[reportAssignmentType]
    # Subagent name, or "" for the main agent. A field because workflow forks also suffix `id`.
    agent: str = ""
    # Workflow and subagent nesting depth, inherited by `fork` so recursion is bounded.
    workflow_depth: int = 0
    messages: list[dict] = field(default_factory=list)
    model: str = "claude-opus-5"
    effort: str = "xhigh"
    provider: str = "anthropic"
    # Backends a sandbox can swap in.
    fs: str = "local"
    shell: str = "local"
    # A `history:` filter applied to what is sent, or "" for none.
    history: str = ""
    # Tools this conversation is shown and may call, or None for all, including ones registered later.
    tools: frozenset[str] | None = None
    approval: str = "cli"       # who answers an "ask" verdict
    # Decides an unmatched tool call: `strict` asks, `dangerous` allows. Not a CLI flag, since the model can reach flags through bash (ADR-0003).
    tier: str = "strict"
    # Default for `run_agent`'s `max_turns`.
    max_turns: int = 50
    # Output sink, if anyone is listening.
    emit: Callable[[str, str], None] | None = None
    # Where an interactive interface reads input; None means the terminal.
    stream: TextIO | None = None
    # True means nobody can answer (fail closed). Set only by `new_session`.
    headless: bool = True
    # Per-plugin state keyed by plugin name. New per-session state goes here, not in a new field.
    # rat-tail: `transcript_cursor` and `files_read` predate this and were not migrated.
    state: dict[str, object] = field(default_factory=dict)
    transcript_cursor: int = 0
    # Path -> sha256 as last read or written, so Write and Edit can refuse unseen or changed files.
    files_read: dict[str, str] = field(default_factory=dict)

    context_injected: bool = False      # has SessionStart shaped `system`
    # `system` before SessionStart shaped it, so `reapply` can re-fire without doubling.
    system_base: str | None = None
    last_recorded: Reply | None = None  # identity guard against a double-recorded turn
    system_digest: str | None = None    # what the prefix check is made against
    messages_watermark: int = 0
    turn_index: int = 0                 # zero-based
    # Provider calls since a person last interacted; what `max_turns` bounds.
    unattended_turns: int = 0
    tokens: int = 0                     # input plus output, every recorded turn
    # Keep full tool results in the written record. Off to bound record size.
    log_debug: bool = False
    # Whether the background learning pass runs (ADR-0022).
    self_learning: bool = True
    # Calls in flight, keyed by tool_use id.
    jobs: dict[str, Job] = field(default_factory=dict)
    # Set by a tool or hook to end the run after the current batch.
    end_turn: bool = False
    # Not reset by `fork`: parent and subagents share it, so a child blocked in a provider call stops at its next turn.
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)
    # Set when this session or any fork of it fires SessionStart, and never cleared, so SessionEnd closes whatever the process started. Shared by reference like `cancelled`.
    started: threading.Event = field(default_factory=threading.Event, repr=False)
    _tokens_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def spend(self, tokens: int) -> None:
        """Add to the token total. Locked, since subagents on pool threads add concurrently."""
        with self._tokens_lock:
            self.tokens += tokens

    def __post_init__(self) -> None:
        """Default `root` to `cwd`."""
        if self.root is None:
            self.root = self.cwd

    def rebase(self) -> None:
        """Put `system` back to what it was before SessionStart shaped it, so the next turn fires SessionStart again. A no-op on an unshaped session."""
        if self.system_base is not None:
            self.system = self.system_base
            self.system_base = None
            self.context_injected = False
            self.system_digest = None

    def fork(self, suffix: str) -> "Session":
        """A fresh conversation with this session's settings and none of its history.

        It is its own session: it starts from this one's unshaped prompt, and SessionStart shapes its own.
        """
        child = replace(self, id=f"{self.id}-{suffix}", **_fresh())
        child.rebase()
        return child

    def adopt(self, session_id: str) -> None:
        """Switch this session to `session_id` in place, clearing conversation state and keeping `system`.

        The caller restores history afterwards; clearing first keeps `_check_prefix` quiet. `session_id` is not checked.
        """
        self.id = session_id
        for name, value in _fresh().items():
            setattr(self, name, value)

    def attended(self) -> None:
        """A person interacted: reset what `max_turns` bounds."""
        self.unattended_turns = 0

    # Channels prefixed with the agent name. `error` and `note` already carry a source.
    TAGGED = ("tool", "tool_result")

    def say(self, channel: str, text: str) -> None:
        """Push output to this session's sink, if any, prefixing tool lines with the agent name."""
        if self.emit is not None:
            if self.agent and channel in self.TAGGED:
                text = f"[{self.agent}] {text}"
            self.emit(channel, text)

    def report(self, source: str, text: str) -> None:
        """Report a failure the caller survived, to the sink (or stderr) and the record. Never raises."""
        line = f"{source}: {text}"
        try:
            self.say("error", line)
            # Stderr only without a sink, or the interface shows it twice.
            if self.emit is None:
                print(f"un: {line}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        try:
            use("session", "event")(self, "error", source=source, text=text)
        except Exception:  # noqa: BLE001
            # LookupError when the transcript plugin is disabled.
            pass

    def note(self, source: str, text: str) -> None:
        """Tell the operator a fact about the run, via the sink or stderr. Never raises."""
        line = f"{source}: {text}"
        try:
            self.say("note", line)
            if self.emit is None:
                print(f"un: {line}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass


# The `agent:` selector's name for the main conversation, whose `Session.agent` is "".
MAIN = "main"

# Role a file's text is delivered in. `system` is the default because nothing the model reads can forge it.
SYSTEM_MESSAGE = "system"
USER_MESSAGE = "user"
MESSAGE_TYPES = (SYSTEM_MESSAGE, USER_MESSAGE)

# Default events: a `path` trigger fires on tool use, anything else on the turn.
PATH_EVENT = "PostToolUse"
TURN_EVENT = "TurnStart"

TRIGGER_KEYS = ("event", "path", "every")
SELECTOR_KEYS = ("provider", "model", "agent")

# (declared event, message type) -> the event a file registers on.
ROUTES = {
    ("SessionStart", SYSTEM_MESSAGE): "SessionStart",
    ("SessionStart", USER_MESSAGE): "UserPromptSubmit",
    (TURN_EVENT, SYSTEM_MESSAGE): TURN_EVENT,
    (TURN_EVENT, USER_MESSAGE): "UserPromptSubmit",
    (PATH_EVENT, SYSTEM_MESSAGE): "ToolResults",
    (PATH_EVENT, USER_MESSAGE): PATH_EVENT,
    # Identity cells, so a hook can opt into delivery on these events directly. Each takes only the role it honestly has.
    ("UserPromptSubmit", USER_MESSAGE): "UserPromptSubmit",
    ("ToolResults", SYSTEM_MESSAGE): "ToolResults",
}


@dataclass(frozen=True)
class Trigger:
    """When a rule or hook fires: named events, paths a tool call touches, and a turn stride."""

    event: tuple[str, ...] = ()
    path: tuple[str, ...] = ()
    every: int = 1


@dataclass(frozen=True)
class Selectors:
    """Whether a rule or hook applies to this conversation: glob sets, None meaning no opinion."""

    provider: frozenset[str] | None = None
    model: frozenset[str] | None = None
    agent: frozenset[str] | None = None


def _globbed(value: str, pattern: str) -> bool:
    """One case-sensitive glob against one value. `src/db/**` also matches `src/db`.

    rat-tail: a case-sensitive twin of `_path_globbed`, which matches paths with `fnmatch`;
    one function once case handling is the same for both.
    """
    return (fnmatch.fnmatchcase(value, pattern)
            or (pattern.endswith("/**") and fnmatch.fnmatchcase(value, pattern[:-3])))


def trigger(data: dict) -> tuple[Trigger, str | None]:
    """Parse the `trigger` mapping. Never raises: an unreadable one falls back to firing every turn and returns the reason."""
    fallback = Trigger(event=(TURN_EVENT,))
    known = ", ".join(TRIGGER_KEYS)
    raw = data.get("trigger")
    if raw is None:
        return fallback, f"no trigger in its frontmatter; name at least one of {known}"
    if not isinstance(raw, dict):
        return fallback, f"trigger must be a mapping of {known}, not {type(raw).__name__}"
    if extra := sorted(set(raw) - set(TRIGGER_KEYS)):
        return fallback, f"unknown trigger key {extra[0]!r}; known: {known}"
    if not raw:
        # After the unknown-key check, so a typo gets the more specific message.
        return fallback, f"trigger names nothing; name at least one of {known}"

    # `dict.fromkeys` drops repeats and keeps order.
    path: tuple[str, ...] = ()
    if (declared := raw.get("path")) is not None:
        if not isinstance(declared, (str, list)):
            return fallback, (
                f"trigger.path must be a glob or a list of them, "
                f"not {type(declared).__name__}")
        path = tuple(dict.fromkeys(frontmatter.entries(declared)))
        if not path:
            return fallback, (
                "trigger.path names nothing; leave the key out or name a glob")

    every = 1
    if "every" in raw:
        value = raw["every"]
        # `type`, not `isinstance`: bool is an int.
        if type(value) is not int or value <= 0:
            return replace(fallback, path=path), (
                f"trigger.every must be a whole number above zero, not {value!r}")
        every = value

    declared = raw.get("event")
    if declared is None:
        event = (PATH_EVENT,) if path else (TURN_EVENT,)
    else:
        if not isinstance(declared, (str, list)):
            return replace(fallback, path=path, every=every), (
                f"trigger.event must be a name or a list of them, "
                f"not {type(declared).__name__}")
        event = tuple(dict.fromkeys(frontmatter.entries(declared)))
        if not event:
            return replace(fallback, path=path, every=every), (
                f"trigger.event names nothing; leave the key out or name one of "
                f"{', '.join(EVENTS)}")
        for name in event:
            if name not in EVENTS:
                return replace(fallback, path=path, every=every), (
                    f"unknown event {name!r}; known: {', '.join(EVENTS)}")
    return Trigger(event=event, path=path, every=every), None


def selectors(data: dict) -> tuple[Selectors, str | None]:
    """Parse the `provider`, `model` and `agent` selectors. A broken key falls back to None (applies everywhere) and returns the reason."""
    found: dict[str, frozenset[str] | None] = {}
    error = None
    for key in SELECTOR_KEYS:
        found[key] = None
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, (str, list)):
            error = error or (
                f"{key} must be a name or a list of them, not {type(value).__name__}")
            continue
        if not (names := frontmatter.entries(value)):
            error = error or (
                f"{key} names nobody; leave the key out to apply to every conversation")
            continue
        found[key] = frozenset(names)
    return Selectors(**found), error


def message_type(data: dict) -> tuple[str, str | None]:
    """Which role carries this file's text. An unknown value falls back to `system` and returns the reason."""
    if (raw := data.get("message_type")) is None and "message_type" not in data:
        return SYSTEM_MESSAGE, None
    if raw in MESSAGE_TYPES:
        return raw, None
    return SYSTEM_MESSAGE, (
        f"unknown message_type {raw!r}; known: {', '.join(MESSAGE_TYPES)}")


def selects(chosen: Selectors, session: "Session") -> bool:
    """Whether every declared selector matches this conversation. Absent selectors match."""
    return all(
        patterns is None or any(_globbed(value, p) for p in patterns)
        for patterns, value in (
            (chosen.provider, session.provider),
            (chosen.model, session.model),
            (chosen.agent, session.agent or MAIN),
        )
    )


def triggered(when: Trigger, args: dict | None) -> bool:
    """Whether this tool call's `path` argument matches any of `when.path`.

    rat-tail: only an argument named `path`; widening must not import `permissions`.
    """
    return (isinstance(target := (args or {}).get("path"), str)
            and any(_globbed(target, glob) for glob in when.path))




def route(event: str, delivery: str) -> str:
    """The event a file registers on for one declared event and message type.

    Raises on an unrouted pair: inputs arrive validated, so a miss is a bug in un.
    """
    try:
        return ROUTES[(event, delivery)]
    except KeyError:
        raise ValueError(
            f"nothing delivers a {event!r} trigger as a {delivery!r} message") from None


# `.un/` layout, relative to the project root.
UN_DIR = Path(".un")
SESSIONS = UN_DIR / "sessions"
# Here, not in the oauth plugin, because `permissions` also needs it.
OAUTH = UN_DIR / "oauth"
CONFIG = UN_DIR / "config.toml"


def un_dir(cwd: Path, name: str) -> Path:
    """Where one kind of `.un/` content lives."""
    return Path(cwd) / UN_DIR / name


def project_root(start: Path | None = None) -> Path | None:
    """The nearest directory at or above `start` holding `.un/`, or None. `start` need not exist."""
    start = Path.cwd() if start is None else Path(start)
    for candidate in (start, *start.parents):
        if (candidate / UN_DIR).is_dir():
            return candidate
    return None


# The `@name` prefixes a `.un/` config path may use, relative to the project root.
LOCATIONS = {
    "project_root": Path("."),
    "commands": UN_DIR / "commands",
    "hooks": UN_DIR / "hooks",
    "skills": UN_DIR / "skills",
    "tools": UN_DIR / "tools",
    "workflows": UN_DIR / "workflows",
}

# rat-tail: a fixed prune set, not a .gitignore parser; ripgrep is the upgrade.
PRUNE = {".git", ".venv", ".pixi", "__pycache__", "node_modules",
         ".mypy_cache", ".pytest_cache"}


def walk(root: Path) -> list[Path]:
    """Every directory and file under `root`, pruned, as sorted root-relative paths. Symlinks leaving `root` are skipped; a missing root gives []."""
    root = Path(root).resolve()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in PRUNE]
        here = Path(dirpath)
        for name in dirnames + filenames:
            entry = here / name
            if entry.is_symlink() and not entry.resolve().is_relative_to(root):
                continue
            found.append(entry.relative_to(root))
    return sorted(found)


def location(root: Path, value: str) -> Path:
    """A `.un/` config path with a leading `@location` replaced. No search, by design."""
    if not value.startswith("@"):
        return Path(value)
    head, _, rest = value[1:].partition("/")
    if head not in LOCATIONS:
        raise ValueError(f"@{head} is not a location; use "
                         + ", ".join(f"@{known}" for known in LOCATIONS))
    return root / LOCATIONS[head] / rest


def session_file(cwd: Path, session_id: str) -> Path:
    """Where one session's transcript lives."""
    return Path(cwd) / SESSIONS / f"{session_id}.jsonl"


# The closed set of efforts a provider profile or agent may name.
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Profile:
    """One `[providers.<name>]` entry. `api_key` names an environment variable, never holds the value."""

    name: str
    # No default: test_core checks the default model is declared once, and one here would collide with `Session.model`.
    model: str
    # "" inherits `--effort`, then `Session.effort`.
    effort: str = ""
    # 0 inherits `--max-turns`, then `Session.max_turns`.
    max_turns: int = 0
    adaptor: str = ""
    url: str = ""
    api_key: str = ""
    main: bool = False
    # Adaptor-specific settings, passed through unvalidated.
    options: dict = field(default_factory=dict)

# Key -> required TOML type. `name` is absent because it is the sub-table key.
FIELD_TYPES: dict[str, type] = {
    "adaptor": str, "url": str, "options": dict,
    "model": str, "effort": str, "api_key": str, "main": bool,
    "max_turns": int,
}


# The only key an activation table carries; everything else is in the extension's own file.
ENABLE = "enable"


def enabled(root: Path, section: str, noun: str, label=None,
            settings: frozenset[str] = frozenset()) -> frozenset[str]:
    """Names under `[<section>.<name>]` with `enable = true`. A missing `enable` is false. `settings` are scalar keys the section's owner reads itself, skipped here.

    Empty when the file or section is absent; ValueError when malformed. `label` overrides how the file is named in messages.
    """
    path = Path(root) / CONFIG
    if not path.is_file():
        return frozenset()
    named = path if label is None else label
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{named}: {exc}") from exc
    entries = raw.get(section)
    if entries is None:
        return frozenset()
    if isinstance(entries, dict):
        entries = {name: entry for name, entry in entries.items() if name not in settings}
    if not isinstance(entries, dict) or not all(
            isinstance(entry, dict) for entry in entries.values()):
        raise ValueError(
            f"{named}: [{section}] must be a table of named sub-tables, one per "
            f"{noun} - [{section}.<name>]")

    article = "an" if noun[0] in "aeiou" else "a"
    on = set()
    for name, entry in entries.items():
        extra = sorted(set(entry) - {ENABLE})
        if extra:
            raise ValueError(
                f"{named}: [{section}.{name}] has unknown key {extra[0]!r}; {article} "
                f"{noun} is activated here and described in its own file, so {ENABLE!r} "
                "is the only key")
        value = entry.get(ENABLE, False)
        if type(value) is not bool:
            raise ValueError(
                f"{named}: [{section}.{name}].{ENABLE} must be bool, not "
                f"{type(value).__name__}")
        if value:
            on.add(name)
    return frozenset(on)


def enabled_lenient(root: Path, section: str, noun: str) -> tuple[frozenset[str], str | None]:
    """`enabled`, returning the error instead of raising, for per-turn discovery where a raise would end the session (ADR-0014)."""
    try:
        return enabled(root, section, noun), None
    except ValueError as exc:
        return frozenset(), str(exc)


def scan(root: Path | None, kind: str, folder: Path, pattern: str, read,
        section: str | None = None, noun: str = "", key=None, label=None,
        settings: frozenset[str] = frozenset()) -> dict[str, str]:
    """Rebuild one file-authored kind: drop what `kind`'s last scan registered, then offer each `<root>/<folder>/<pattern>` file to `read`. Returns refusals keyed by `key(relative path)`, default the relative path.

    `read(where, path, text, on)` registers and returns None, or returns why not; `on` is the `[section]` enabled set, None for a kind with no enable table; `label` is how `enabled` names the config in a refusal. Every REGISTRY entry a `read` adds is stamped `un_from_file = kind`, which `_registered_tool` reads, so a kind cannot forget it. Never raises for a file, since it runs at import (ADR-0014).
    """
    where = Path(root or project_root() or Path.cwd())
    for entries in REGISTRY.values():
        for name in [n for n, fn in entries.items() if getattr(fn, "un_from_file", None) == kind]:
            del entries[name]
    refused: dict[str, str] = {}
    here = where / folder
    if not here.is_dir():
        return refused
    on = None
    if section:
        try:
            on = enabled(where, section, noun, label, settings)
        except ValueError as exc:
            # Every entry off: the safe reading of a table nobody can parse.
            refused[CONFIG.as_posix()] = str(exc)
            on = frozenset()
    for path in sorted(here.glob(pattern)):
        rel = path.relative_to(here)
        filed = key(rel) if key else rel.as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            refused[filed] = f"{path.name} could not be read: {exc.strerror}"
            continue
        except UnicodeDecodeError:
            refused[filed] = f"{path.name} could not be read: it is not UTF-8 text"
            continue
        # rat-tail: a registry snapshot per file; a registrar that stamps as it writes if registries grow large.
        before = {extension: set(entries) for extension, entries in REGISTRY.items()}
        why = read(where, path, text, on)
        for extension, entries in REGISTRY.items():
            for name in entries.keys() - before[extension]:
                entries[name].un_from_file = kind
        if why:
            refused[filed] = why
    return refused


def providers(cwd: Path) -> tuple[Profile, ...]:
    """`[providers.<name>]` from `.un/config.toml`, validated, in file order. `()` when absent; ValueError when malformed."""
    path = Path(cwd) / CONFIG
    if not path.is_file():
        return ()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    entries = raw.get("providers")
    if entries is None:
        return ()
    if not isinstance(entries, dict) or not all(
            isinstance(entry, dict) for entry in entries.values()):
        # Usually an old `[[providers]]` array.
        raise ValueError(
            f"{path}: [providers] must be a table of named sub-tables, one per "
            "provider - [providers.<name>]")

    built: list[Profile] = []
    for name, entry in entries.items():
        extra = sorted(set(entry) - set(FIELD_TYPES))
        if extra:
            raise ValueError(
                f"{path}: [providers.{name}] has unknown key {extra[0]!r}; "
                f"known keys: {', '.join(sorted(FIELD_TYPES))}")
        for key, value in entry.items():
            # `type`, not `isinstance`: bool is an int.
            expected = FIELD_TYPES[key]
            if type(value) is not expected:
                raise ValueError(
                    f"{path}: [providers.{name}].{key} must be "
                    f"{expected.__name__}, not {type(value).__name__}")
            if key == "effort" and value not in EFFORTS:
                raise ValueError(
                    f"{path}: [providers.{name}].effort must be one of "
                    f"{', '.join(EFFORTS)}; got {value!r}")
            # Negative only: 0 means inherit, and a negative bound would silently run no turns.
            if key == "max_turns" and value < 0:
                raise ValueError(
                    f"{path}: [providers.{name}].max_turns must be a whole number of "
                    f"turns; got {value!r}")
        # `model` defaults here; see `Profile.model`.
        built.append(Profile(name=name, **{"model": "", **entry}))

    # An empty table fails here too: configured, but naming nothing.
    mains = [p.name for p in built if p.main]
    if len(mains) != 1:
        raise ValueError(
            f"{path}: exactly one [providers.<name>] entry must set main = true; "
            + (f"these set it: {', '.join(mains)}" if mains else "none does"))
    return tuple(built)


def main_provider(profiles: tuple[Profile, ...]) -> Profile | None:
    """The profile with `main = true`, or None when nothing is configured."""
    return next((p for p in profiles if p.main), None)


def env_value(cwd: Path, name: str) -> str | None:
    """One variable from the project's `.env`, else the process environment. Never writes `os.environ`, so it cannot reach a child process.

    rat-tail: `KEY=value`, `#` comments, optional `export`, one layer of quotes; no multi-line values or interpolation.
    """
    path = Path(cwd) / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().removeprefix("export ")
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or key.strip() != name:
                continue
            value = value.strip()
            for quote in ('"', "'"):
                if len(value) > 1 and value.startswith(quote) and value.endswith(quote):
                    return value[1:-1]
            return value
    return os.environ.get(name)


# Environment names a child process may see. An allowlist, because a denylist cannot recognise every credential.
PASS_THROUGH = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "TZ",
    # Windows: the shell does not start without SystemRoot and COMSPEC.
    "SystemRoot", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA",
    "LOCALAPPDATA",
    # rat-tail: proxy URLs can embed credentials, but un is unusable behind a proxy without them.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
})

# Matched by prefix rather than in full, because the locale set is open.
PASS_THROUGH_PREFIXES = ("LC_",)


def child_env(*, keep: tuple[str, ...] = ()) -> dict[str, str]:
    """The environment a child may see, from the allowlist. `keep` adds prefixes; matching is exact or by prefix, never containment."""
    prefixes = PASS_THROUGH_PREFIXES + keep
    return {
        name: value for name, value in os.environ.items()
        if name in PASS_THROUGH or name.startswith(prefixes)
    }


DEFAULT_TIMEOUT = 120  # seconds; the bound a spawn takes unless it names its own
TIMEOUT_CODE = 124  # timeout(1)'s code


def spawn_child(command: str | list[str], *, cwd: Path | None, timeout: float,
                input: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run one child under `child_env()` in its own process group; return its stdout and stderr apart. A string runs through a shell, a list is exec'd.

    Past `timeout` the whole tree is killed and `subprocess.TimeoutExpired` is raised carrying what the child had written. An interrupt kills the tree and re-raises.
    """
    # New process group so a timeout or cancel can kill the whole tree.
    creation = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    process = subprocess.Popen(
        command,
        # A shell for strings is `bash`'s purpose; `child_env` is the control. Lists never touch a shell.
        shell=isinstance(command, str),  # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true
        cwd=cwd,
        env=child_env(),
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **creation,
    )
    # Signal only; this thread's `communicate` reaps.
    on_cancel(lambda: _signal_tree(process))
    try:
        stdout, stderr = process.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Rebuilt from the reaped streams: the stdlib's own exception carries bytes whatever `text` says.
        stdout, stderr = _kill_tree(process)
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from None
    except KeyboardInterrupt:
        # The new process group misses the terminal's SIGINT, so kill the tree. Re-raised: an interrupt ends the turn.
        _kill_tree(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def run_child(command: str | list[str], *, cwd: Path, timeout: int) -> tuple[int, str]:
    """Run one child under a timeout; return (exit code, output). A string runs through a shell, a list is exec'd.

    The child gets `child_env()`, never un's own environment. A timeout returns a message rather than raising.
    """
    try:
        done = spawn_child(command, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired:
        shown = command if isinstance(command, str) else shlex.join(command)
        return TIMEOUT_CODE, f"timed out after {timeout}s: {shown}"
    parts = [part.rstrip() for part in (done.stdout, done.stderr) if part]
    return done.returncode, "\n".join(parts)


def _signal_tree(process: subprocess.Popen) -> None:
    """Kill the process tree without waiting. Safe from any thread; reaping is the owning thread's job.

    rat-tail: taskkill on Windows rather than a psutil dependency.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    process.kill()


def _kill_tree(process: subprocess.Popen) -> tuple[str, str]:
    """Kill the process tree, reap it, and return what it wrote. Only from the thread running the call."""
    _signal_tree(process)
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        # rat-tail: a pipe still held after the group kill yields nothing rather than holding the turn.
        return "", ""


# Narrow on purpose: must not match "system prompt is too long".
SYSTEM_UNSUPPORTED = "role 'system' is not supported"


def fold_system(messages: list[dict]) -> list[dict]:
    """Fold each system message into the user message before it, for models that reject mid-conversation system messages. The result is spoofable."""
    folded: list[dict] = []
    for message in messages:
        previous = folded[-1] if folded else None
        if message.get("role") != "system" or not previous:
            folded.append(dict(message))
            continue
        if previous.get("role") != "user":
            folded.append(dict(message))
            continue
        text = message["content"]
        if isinstance(previous["content"], str):
            previous["content"] = f"{previous['content']}\n\n{text}"
        else:
            previous["content"] = [*previous["content"], {"type": "text", "text": text}]
    return folded


# Advice that fits only when the model is the cause.
SPOOFABLE_ROLE_REMEDY = (" Use a model that supports the system role to keep it "
                          "non-spoofable.")


def warn_spoofable(model: str, emit=None, *,
                   why: str = "rejects mid-conversation system messages",
                   remedy: str = SPOOFABLE_ROLE_REMEDY) -> None:
    """Warn that operator rules are being folded into the spoofable user turn. Via `emit` when given, else stderr."""
    text = (f"warning: {model} {why}, so operator "
            "rules are being folded into the user turn. On this model that channel is "
            "spoofable - anything that writes into what the model reads can spell a "
            f"rule.{remedy}")
    if emit is not None:
        emit("error", text)
        return
    print(text, file=sys.stderr)


SYSTEM = "You are un, a command-line coding agent. Be concise and direct."

def new_id() -> str:
    """A conversation id: start time plus four hex digits. `transcript.RECORD_ID` parses this shape."""
    return f"{datetime.now():%Y%m%dT%H%M%S}-{token_hex(2)}"

def new_session(args, **overrides) -> Session:
    """Build a session from parsed CLI args; `overrides` set fields directly."""
    # Resolved here, not as flag defaults, so `--provider X` picks X's model.
    chosen = next((p for p in providers(project_root() or Path.cwd())
                   if p.name == args.provider), None)
    fields = {
        "id": new_id(),
        "cwd": Path.cwd(),
        # `or Path.cwd()` for callers, such as tests, outside a project.
        "root": project_root() or Path.cwd(),
        "system": SYSTEM,
        "model": args.model or (chosen.model if chosen else "") or Session.model,
        "effort": args.effort or (chosen.effort if chosen else "") or Session.effort,
        "provider": args.provider,
        "fs": args.fs,
        "shell": args.shell,
        "approval": args.approval,
        "history": args.history,
        # `is None`: 0 is a real bound on the command line.
        "max_turns": (args.max_turns if args.max_turns is not None
                      else (chosen.max_turns if chosen else 0) or Session.max_turns),
        "log_debug": args.log_debug,
        "self_learning": args.self_learning,
        # No flag declares this; `cli.main` sets it with `set_defaults`.
        "tier": getattr(args, "tier", Session.tier),
        "headless": not sys.stdin.isatty(),
    }
    fields.update(overrides)
    return Session(**fields)


def record_turn(session: Session, reply: Reply) -> None:
    """Append one assistant turn, count its tokens and fire `Turn`. Idempotent by identity, not equality."""
    if reply is session.last_recorded:
        return
    # Before the fire: the transcript hook writes what `messages` has gained.
    session.messages.append({"role": "assistant", "content": reply.content})
    session.last_recorded = reply
    usage = reply.usage or {}
    # Cache reads are a subset of input tokens, so not added.
    session.spend(usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
    fire("Turn", session=session, reply=reply)


def run_agent(session: Session, prompt: str,
              *, max_turns: int | None = None) -> Reply | None:
    """Run one prompt to a stopping point: shape the prompt, append the user message, loop, record."""
    # `is None`: 0 is a real bound.
    if max_turns is None:
        max_turns = session.max_turns

    # Per-run flags; a new prompt is a new run.
    session.cancelled.clear()
    session.end_turn = False

    session.attended()

    _check_prefix(session)
    if not session.context_injected:
        session.system_base = session.system
        extra = fire("SessionStart", session=session)
        if extra:
            session.system = "\n\n".join([session.system, *extra]).strip()
            session.context_injected = True
            session.started.set()
        # Stamped even without hook output, so a hookless session still counts as stable.
        session.system_digest = _digest(session.system)

    # Derived, so a resumed session is right. Prompts are string-content user messages; tool results are block lists.
    session.turn_index = sum(
        1 for m in session.messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )

    prompt = chain("UserPromptSubmit", prompt, session=session)
    session.messages.append({"role": "user", "content": prompt})

    # A system message must follow a user message and never be first.
    operator = fire("TurnStart", session=session)
    for text in operator:
        session.messages.append({"role": "system", "content": text})

    interrupted = False
    try:
        try:
            reply = _loop(session, max_turns=max_turns)
        except KeyboardInterrupt:
            # Repair `messages` so the next call is valid; the caller decides what the interrupt ends.
            interrupted = True
            _interrupted(session)
            raise
        if reply is not None:
            record_turn(session, reply)
        session.messages_watermark = len(session.messages)
        return reply
    finally:
        # `finally` so TurnEnd fires on an interrupt too.
        fire("TurnEnd", session=session, interrupted=interrupted)


def _interrupted(session: Session) -> None:
    """Make `messages` valid for the next provider call after an interrupt, appending only. Outstanding tool_use blocks get synthetic results, and a note marks the turn."""
    last = session.messages[-1] if session.messages else None
    if last is not None and last.get("role") == "assistant":
        outstanding = [block for block in last["content"]
                       if isinstance(block, dict) and block.get("type") == "tool_use"]
        if outstanding:
            session.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": block["id"],
                 "content": INTERRUPTED_RESULT, "is_error": True}
                for block in outstanding
            ]})
    if session.messages and session.messages[-1].get("role") == "user":
        # User role, since a system message becomes illegal once the next prompt follows it. A block list, so `turn_index` does not count it.
        session.messages.append(
            {"role": "user", "content": [{"type": "text", "text": INTERRUPTED_NOTE}]}
        )
    try:
        use("session", "event")(session, "interrupted", turn=session.turn_index)
    except Exception:  # noqa: BLE001
        # LookupError when the transcript plugin is disabled; must not replace the KeyboardInterrupt.
        pass
    session.messages_watermark = len(session.messages)


def _fail_soft(call):
    """Wrap a provider so anything it raises becomes a `ProviderError` carrying its type and message.

    Wraps the resolved callable, so faults in building its arguments keep their traceback.
    """
    def served(**kwargs):
        try:
            return call(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - the seam's whole purpose
            # Not BaseException: KeyboardInterrupt must reach the loop.
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc

    return served


def _loop(session: Session, *, max_turns: int) -> Reply | None:
    """Call the provider, run the requested tools, repeat. Returns None at `max_turns=0`."""
    call = _fail_soft(use("provider", session.provider))
    schemas = _schemas(session)
    reply = None
    # rat-tail: pool as wide as the batch; cap it if batches grow large (ADR-0010).
    pool = ThreadPoolExecutor(thread_name_prefix="un-tool")
    try:
        reply = _turns(session, call, schemas, pool, max_turns=max_turns)
    except KeyboardInterrupt:
        # Signals reach only the main thread, so stop each job's work rather than its thread.
        session.cancelled.set()
        _stop(session, list(session.jobs.values()))
        raise
    finally:
        # Not a `with`: its shutdown waits for the slowest tool.
        pool.shutdown(wait=False, cancel_futures=True)
    return reply


def _turns(session: Session, call, schemas: list[dict], pool: ThreadPoolExecutor,
           *, max_turns: int):
    """The turn loop itself. Split from `_loop` so the interrupt handling reads as one piece."""
    reply = None
    # Not a range: `attended()` resets the count from outside the loop.
    while session.unattended_turns < max_turns:
        if session.cancelled.is_set():
            # Where cancellation reaches work with no stop handle, such as a subagent mid-request.
            break
        # Deliver finished background jobs before the call.
        session.messages.extend(_deliver(session))
        # Counted here so waiting on background jobs costs no turn.
        session.unattended_turns += 1
        reply = call(
            system=session.system,
            messages=_sent(session),
            tools=schemas,
            model=session.model,
            effort=session.effort,
            cache=cache_spec(session),
            # `say`, not `emit`, which is None when headless.
            emit=session.say,
        )
        record_turn(session, reply)

        calls = [b for b in reply.content if b["type"] == "tool_use"]
        if not calls:
            # Nothing to call: wait for background jobs if any remain, else done.
            outstanding = [job.future for job in session.jobs.values() if job.background]
            if _ended(session) or not outstanding:
                break
            wait(outstanding, return_when=FIRST_COMPLETED)
            continue
        # One message for all results; splitting them discourages parallel tool calls.
        results, denied = _dispatch(session, calls, pool)
        session.messages.append({"role": "user", "content": results})
        # Once per batch, after the results, keeping system-after-user.
        for text in fire("ToolResults", session=session, calls=calls):
            session.messages.append({"role": "system", "content": text})
        if denied is not None:
            # Raised after the batch is recorded; only the headless run ends.
            raise Denied(denied)
        # After the results, since the provider rejects an unanswered tool_use.
        if _ended(session):
            break
    return reply


def _stop(session: Session, jobs: list[Job]) -> None:
    """Run every stop handle `jobs` registered."""
    for job in jobs:
        for stop in job.cancels:
            try:
                stop()
            except Exception as exc:  # noqa: BLE001
                # Reported, never raised: must not replace a KeyboardInterrupt or crash an accepted end.
                session.report("cancel", f"{type(exc).__name__}: {exc}")


def _ended(session: Session) -> bool:
    """If a tool or hook set `end_turn`, clear it, stop background jobs still running and return True."""
    if not session.end_turn:
        return False
    session.end_turn = False
    running = [job for job in session.jobs.values() if job.background and not job.future.done()]
    for job in running:
        job.stopped = True
    _stop(session, running)
    return True


def _schemas(session: Session) -> list[dict]:
    """The tool schemas shown to the model, filtered by `session.tools`, eligible ones gaining `background`. Copies, never the registered dicts."""
    shown = []
    for entry in REGISTRY["tool"].values():
        if session.tools is not None and entry.un_name not in session.tools:
            continue
        schema = entry.un_meta["schema"]
        if callable(schema):
            # rat-tail: only Submit shapes its schema per conversation.
            schema = schema(session)
            if schema is None:
                continue
        if entry.un_name not in NEVER_BACKGROUND:
            schema = {**schema, "properties": {**schema.get("properties", {}),
                                               BACKGROUND: BACKGROUND_FIELD}}
        shown.append({"name": entry.un_name,
                      "description": entry.un_meta["description"],
                      "input_schema": schema})
    return shown


def _receipt(block: dict) -> dict:
    """A placeholder result for a backgrounded call; the provider rejects an unanswered tool_use."""
    return {"type": "tool_result", "tool_use_id": block["id"],
            "content": RECEIPT.format(id=block["id"]), "is_error": False}


def _deliver(session: Session) -> list[dict]:
    """Finished background jobs as user messages, removed from `session.jobs`. Block lists, so `turn_index` does not count them."""
    done = [job for job in session.jobs.values()
            if job.background and (job.stopped or job.future.done())]
    messages = []
    for job in done:
        del session.jobs[job.block["id"]]
        # A cancelled future raises on `.result()`.
        if job.stopped or job.future.cancelled():
            messages.append({"role": "user", "content": [{"type": "text", "text": STOPPED.format(
                id=job.block["id"], shown=job.row.get("shown", job.block["name"]))}]})
            continue
        # A call that raised is delivered too, as its error text.
        text, blocks = _split(job.future.result()["content"])
        messages.append({"role": "user", "content": [
            {"type": "text", "text": DELIVERED.format(
                id=job.block["id"],
                shown=job.row.get("shown", job.block["name"]),
                result=text)},
            *(b for b in (blocks or []) if b["type"] != "text")]})
    return messages



def _dispatch(session: Session, calls: list[dict],
              pool: ThreadPoolExecutor) -> tuple[list[dict], Verdict | None]:
    """Gate every call in order, then run them; results in call order.

    Gating first keeps approval prompts sequential. A deny refuses only its own call; a headless deny is returned for the caller to raise once the batch is recorded.
    """
    rows, decided, inputs = [], [], []
    for block in calls:
        # `background` is the loop's argument, stripped before gating; honoured only for tools that allow it.
        args = dict(block["input"])
        wanted = args.pop(BACKGROUND, False) is True and block["name"] not in NEVER_BACKGROUND
        inputs.append(args)
        # Filled in as the call resolves; `input` is what the tool receives.
        row = {"kind": "tool", "id": block["id"], "name": block["name"],
               "input": args, BACKGROUND: wanted, "started": time.monotonic()}
        rows.append(row)
        if session.tools is not None and block["name"] not in session.tools:
            # Before the gate: an ungranted call reaches no hook, rule or approver, since a learning fork answers its own asks.
            row["shown"] = block["name"]
            row["reason"] = f"{block['name']} is not granted to this agent"
            decided.append(Gate("blocked", None, f"Blocked: {row['reason']}"))
            continue
        try:
            # No `lock`: this loop already gates one call at a time.
            decided.append(gate(session, block["name"], args, row))
        except Exception as exc:  # noqa: BLE001
            # A raising hook or approval adapter refuses this call rather than ending the session.
            decided.append(Gate("blocked", None, f"{type(exc).__name__}: {exc}"))

    denied = next((d.verdict for d in decided if d.outcome == "denied"), None)
    # Label results only in a batch, where a result no longer sits under its own call.
    labelled = len(calls) > 1
    jobs = []
    for block, row, gated, args in zip(calls, rows, decided, inputs):
        # A refused call is never backgrounded.
        job = Job(block=block, row=row,
                  background=row[BACKGROUND] and gated.outcome == "run")
        # Before submit, so an interrupt can always see it.
        session.jobs[block["id"]] = job
        job.future = pool.submit(_run_tool, session, job, gated, args, labelled)
        jobs.append(job)

    answers = []
    for job in jobs:
        if job.background:
            # The row stays open and the job in flight until delivery.
            answers.append(_receipt(job.block))
            continue
        answers.append(job.future.result())
        session.jobs.pop(job.block["id"], None)
    return answers, denied


def _run_tool(session: Session, job: Job, decided: Gate, args: dict,
              labelled: bool) -> dict:
    """Run one gated call on a pool thread, publishing the job so the tool can use `on_cancel`."""
    block, call = job.block, job.row
    token = _CURRENT.set(job)
    try:
        return _attempt(session, block, call, decided, args)
    except KeyboardInterrupt:
        # `_result` never ran, so stamp the outcome here.
        call["result"] = INTERRUPTED_RESULT
        call["error"] = True
        raise
    finally:
        _CURRENT.reset(token)
        _close(session, call, labelled=labelled)


def _close(session: Session, call: dict, *, labelled: bool = False) -> None:
    """Stamp the call's duration, emit its result and fire `ToolEnd`."""
    call["ms"] = round((time.monotonic() - call.pop("started")) * 1000)
    # A headless DENY can leave no result; emit nothing then.
    if "result" in call:
        # Label on the first line, which `repl`'s collapse keeps.
        said = f"{call['shown']}\n{call['result']}" if labelled else call["result"]
        session.say("tool_result", said)
    # Outside `_attempt`'s catch-all: a failing listener is a bug, not a tool error.
    try:
        fire("ToolEnd", session=session, call=call)
    except Exception as exc:  # noqa: BLE001
        # Re-raised as RecordUnavailable so `main` reports it by name.
        raise RecordUnavailable(
            f"a ToolEnd listener failed: {type(exc).__name__}: {exc}") from exc


def _attempt(session: Session, block: dict, call: dict, decided: Gate,
             args: dict) -> dict:
    name = block["name"]
    # One catch-all over the tool and PostToolUse: a raising plugin becomes an error result.
    try:
        if decided.outcome != "run":
            return _result(block, decided.message, call, error=True)
        text, blocks = _split(REGISTRY["tool"][name](session=session, **args))
        return _result(
            block,
            chain("PostToolUse", text, session=session, name=name, args=args),
            call,
            blocks=blocks,
        )
    except Exception as exc:  # noqa: BLE001
        return _result(block, f"{type(exc).__name__}: {exc}", call, error=True)


def _split(value: str | list[dict]) -> tuple[str, list[dict] | None]:
    """A tool's return as (text to record, blocks for the provider or None)."""
    if isinstance(value, str):
        return value, None
    return "\n".join(b["text"] for b in value if b["type"] == "text"), value


def _result(block: dict, text: str, call: dict, *, error: bool = False,
            blocks: list[dict] | None = None) -> dict:
    """Build the tool_result block and stamp the same outcome on the row."""
    call["result"] = text
    call["error"] = error
    return {
        "type": "tool_result",
        "tool_use_id": block["id"],
        # Text from the PostToolUse output, not the original; omitted when empty, which the API refuses.
        "content": text if blocks is None else [
            *([{"type": "text", "text": text}] if text else []),
            *(b for b in blocks if b["type"] != "text")],
        "is_error": error,
    }


def _usage_line(reply, stats: bool) -> None:
    """Print the turn's token usage to stderr when `stats` is set."""
    if not stats:
        return
    usage = reply.usage or {}
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens")
    shown = [f"{f}={usage[f]}" for f in fields if f in usage]
    print("  " + "  ".join(shown) if shown else "  (no usage reported)",
          file=sys.stderr)


def _attach_terminal(session: Session, render: Callable | None = None) -> dict:
    """Route session output to the terminal: answer text to stdout, tool progress to stderr. Returns streaming state. A given `render` replaces this."""
    if render is not None:
        session.emit = render
        return {"streamed": False, "open": False}
    # `open`: a stdout line is unterminated.
    state = {"streamed": False, "open": False}

    def emit(channel: str, text: str) -> None:
        if channel == "text":
            state["streamed"] = True
            state["open"] = True
            print(text, end="", flush=True)
        elif channel in NOTED:
            # End the stdout line before writing to stderr.
            if state["open"]:
                print(flush=True)
                state["open"] = False
            print(f"{NOTED[channel]}{text}", flush=True, file=sys.stderr)

    session.emit = emit
    return state


def run_terminal(session: Session, prompt: str, *, max_turns: int, stats: bool,
                 render: Callable[[str, str], None] | None = None) -> int:
    """Run one prompt, rendered to the terminal. Returns EXIT_OK, EXIT_FAILED on a provider fault, or EXIT_EXHAUSTED."""
    seen = _attach_terminal(session, render)
    try:
        reply = run_agent(session, prompt, max_turns=max_turns)
    except ProviderError as exc:
        if render is not None:
            # The renderer owns stderr for the turn.
            render("error", str(exc))
        else:
            print(exc, file=sys.stderr)
        return EXIT_FAILED
    if reply is None:
        # Reachable at `--max-turns 0`.
        return EXIT_OK
    if render is not None:
        render("reply", reply.text)
    elif seen["streamed"]:
        if seen["open"]:
            print()
    else:
        print(reply.text)
    _usage_line(reply, stats)
    # rat-tail: exhaustion is inferred from tool calls left in the reply.
    if any(block["type"] == "tool_use" for block in reply.content):
        print(f"stopped after {max_turns} unattended turns with tool calls outstanding; "
              "the bound counts provider calls since the last human interaction",
              file=sys.stderr)
        return EXIT_EXHAUSTED
    return EXIT_OK


def end_session(session: Session, run: Callable[[], int]) -> int:
    """Run `run` and fire `SessionEnd` with its exit code, if this session or any fork of it fired SessionStart."""
    # Any other exception ends as EXIT_FAILED.
    code = EXIT_FAILED
    try:
        code = run()
        return code
    except KeyboardInterrupt:
        code = EXIT_INTERRUPTED
        raise
    finally:
        if session.started.is_set():
            fire("SessionEnd", session=session, code=code)


# --- command_parse -----------------------------------------------------------------------
#
# Taking a shell command apart. Decisions about the result live in the permissions section.

# Command boundaries. `&` and `|` do not split inside a redirect (`2>&1`, `&>`, `>|`).
_SPLIT = re.compile(r"\|\||&&|[;\n]|(?<!>)\||(?<!>)&(?![>\d])")
_SUBSHELL = re.compile(r"\$\(([^)]*)\)|`([^`]*)`")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})

# `VAR=value`; the value is treated as an argument.
_ASSIGN = re.compile(r"^(\w+)=(.*)$")

# A redirect operator as its own word, or attached to its target (`>out`).
_REDIR_OP = re.compile(r"^(?:\d*|&)(?:>>|>\||>|<)$")
_REDIR_AT = re.compile(r"^(?:\d*|&)(?:>>|>\||>)(.+)$")

# Halves of a redirect the lexer splits (`2`, `>&`, `1`), for `_lex` to rejoin.
_REDIR_PREFIXED = re.compile(r"^(?:>>|>\||>|<)&?$")
_REDIR_DUP = re.compile(r"^\d*(?:>>|>\||>|<)&$")

# Programs that run another program -> positional words to skip before the real head (`pixi run un`).
_WRAPPERS = {
    "env": 0, "nice": 0, "nohup": 0, "command": 0, "exec": 0, "time": 0,
    "stdbuf": 0, "setsid": 0, "ionice": 0, "timeout": 0, "xargs": 0, "npx": 0,
    "pixi": 1, "uv": 1, "poetry": 1, "pdm": 1, "hatch": 1,
}

# Keywords and grouping that precede a command without being one.
_KEYWORDS = frozenset({
    "do", "done", "then", "else", "elif", "fi", "if", "for", "while", "until",
    "in", "case", "esac", "!", ";",
})

# Option spellings folded to one letter. git's `-n` is absent: its meaning differs per subcommand.
# rat-tail: hand-kept; a missing synonym under `dangerous` falls through to allow.
_SYNONYMS = {
    "rm": {"R": "r", "recursive": "r", "force": "f", "dir": "d"},
    "git": {"force": "f"},
}

# Programs whose single-dash options are long names (`find -delete`).
LONGOPT = frozenset({"find", "test"})

# Constructs `fragments` cannot fully decompose, so the matcher asks rather than trust a partial parse. Not a rule, so an operator cannot delete it.
# `shell_flags` matches combined flags (`-lc`) only; a bare `-c` payload is parsed by `fragments`.
OPAQUE = re.compile(
    r"(?P<eval>\beval\b)"
    r"|(?P<nested>\$\([^)]*\$\()"
    r"|(?P<substitution><\(|>\(|<<<)"
    r"|(?P<shell_flags>\b(?:sh|bash|zsh|dash|ksh|fish)\s+-(?=\w*c)\w{2,})"
    r"|(?P<interpreter>\b(?:python|python3|perl|ruby|node|php)\s+(?:-\w+\s+)*-(?:c|e)\b)"
    # A `cd` target built from a variable or substitution, which can assemble a protected path across fragments. Matched raw because `_SUBSHELL.sub` rewrites it before parsing.
    # rat-tail: also matches `cd` mid-fragment (`echo cd $X`); fails closed.
    r"|(?P<cd_target>(?:^|[;&|]|\s)(?:cd|pushd)\s+[^;&|]*[$`])"
)

# One message per `OPAQUE` group, read via `match.lastgroup`.
OPACITY = {
    "eval": "the command is assembled at runtime, so what runs is not what was read",
    "nested": "a nested substitution builds part of this command while it runs",
    "substitution": "process substitution feeds this command output nothing recorded",
    "shell_flags": "combined short flags hide a -c payload the parser does not reach",
    "interpreter": "an interpreter is handed inline code rather than a file",
    "cd_target": "this parsed cleanly, but the cd target is built from a variable, so "
                 "where it lands - and what every later fragment is relative to - is "
                 "unknown",
}


# A shell executing uninspected text. `_floor` refuses these outright, so both are anchored at a command position to avoid matching `ssh` or `a.sh`.
# rat-tail: `cat cmds | xargs sh` is not matched.
_SHELL = r"(?:sh|bash|zsh|dash|ksh|fish)"

SHELL_EXEC = re.compile(
    r"(?P<piped_shell>\|\s*(?:\S*/)?" + _SHELL + r"\b)"
    r"|(?P<shell_stdin>(?:^|[;&|(]|\s)(?:\S*/)?" + _SHELL + r"\s*<)"
)

# One message per `SHELL_EXEC` group.
SHELL_EXEC_WHY = {
    "piped_shell": "this parsed cleanly, but its output is executed by a shell - what "
                   "finally runs was never inspected",
    "shell_stdin": "a shell takes its program from a redirect, so what runs was never "
                   "inspected",
}


def _head_index(words: list[str]) -> int:
    """Index of the program a fragment runs, past keywords, grouping, assignments and wrappers; -1 if none."""
    index = 0
    while index < len(words):
        raw = words[index]
        word = Path(raw.strip("(){};&")).name
        if not word or word in _KEYWORDS or _ASSIGN.match(raw):
            index += 1
            continue
        if word not in _WRAPPERS:
            return index
        index += 1
        # Skip the wrapper's options, assignments and numeric args (`timeout 5`).
        while index < len(words) and (words[index].startswith("-")
                                      or _ASSIGN.match(words[index])
                                      or words[index].isdigit()):
            index += 1
        index += _WRAPPERS[word]
    return -1


def _head(words: list[str]) -> str:
    """The program a fragment actually runs, or "" when it names none."""
    index = _head_index(words)
    return Path(words[index].strip("(){};&")).name if index >= 0 else ""


def _redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """Split a fragment into (arguments, written paths). `/dev/null` and `&N` targets are dropped."""
    kept: list[str] = []
    targets: list[str] = []
    expect = False
    for word in words:  # noqa: B007 - `expect` is read after the loop
        if expect:
            targets.append(word)
            expect = False
            continue
        if _REDIR_OP.match(word):
            # `<` reads: its operand stays an argument.
            expect = not word.endswith("<")
            continue
        if match := _REDIR_AT.match(word):
            targets.append(match.group(1))
            continue
        kept.append(word)
    if expect:
        # A dangling operator keeps "" so the fragment still counts as writing.
        targets.append("")
    return kept, [t for t in targets
                  if t != "/dev/null" and not t.startswith("&")]  # "" is kept


def normalize(words: list[str], head: str) -> tuple[frozenset[str], frozenset[str],
                                                    tuple[str, ...], frozenset[str]]:
    """A fragment's options as sets, so `rm -rf`, `rm -r -f` and `rm --recursive --force` compare equal.

    Returns (short letters, long names, operands, assignment keys). Words after `--` are operands; an assignment contributes both key and value.
    """
    short: set[str] = set()
    long: set[str] = set()
    operands: list[str] = []
    assignments: set[str] = set()
    synonyms = _SYNONYMS.get(head, {})
    single_dash_is_long = head in LONGOPT
    ended = False
    for word in words:
        if ended or not word.startswith("-") or word == "-":
            if match := _ASSIGN.match(word):
                assignments.add(match.group(1))
                operands.append(match.group(2))
            else:
                operands.append(word)
            continue
        if word == "--":
            ended = True
            continue
        if word.startswith("--") or single_dash_is_long:
            name, _, value = word.lstrip("-").partition("=")
            folded = synonyms.get(name)
            (short.add(folded) if folded else long.add(name))
            if value:
                operands.append(value)
            continue
        for letter in word[1:]:
            short.add(synonyms.get(letter, letter))
    return frozenset(short), frozenset(long), tuple(operands), frozenset(assignments)


_SED = {"-e": "code", "--expression": "code", "-f": "file", "--file": "file",
        "-l": "arg", "--line-length": "arg"}
_AWK = {"-e": "code", "--source": "code", "-f": "file", "--file": "file",
        "-v": "arg", "--assign": "arg", "-F": "arg", "--field-separator": "arg"}
# Programs taking their own script as an argument: what each option's value is. With no `code` or `file` option, the first operand is the script.
# rat-tail: sed and awk only; any other program's script is still judged as a path, which fails closed. Add one when its false positives are reported.
_SCRIPT_OPTIONS = {"sed": _SED, "gsed": _SED, "awk": _AWK, "gawk": _AWK, "mawk": _AWK, "nawk": _AWK}


def _script_words(head: str, words: list[str]) -> tuple[str, ...]:
    """The words after `head` that it reads as a script rather than as a file."""
    options = _SCRIPT_OPTIONS.get(head)
    if options is None:
        return ()
    code: list[str] = []
    first: str | None = None
    explicit = ended = False
    rest = iter(words)
    for word in rest:
        if ended or not word.startswith("-") or word == "-":
            if first is None:
                first = word
            continue
        if word == "--":
            ended = True
            continue
        kind = value = None
        if word.startswith("--"):
            name, eq, attached = word.partition("=")
            if kind := options.get(name):
                value = attached if eq else next(rest, "")
        else:
            for at, letter in enumerate(word[1:], 2):
                if kind := options.get(f"-{letter}"):
                    value = word[at:] or next(rest, "")
                    break
        if kind == "code":
            code.append(value)
        explicit = explicit or kind in ("code", "file")
    if not explicit and first is not None:
        code.append(first)
    return tuple(code)


@dataclass(frozen=True)
class Fragment:
    """One command, taken apart: what it runs, how it was flagged, what it names."""

    head: str
    short: frozenset[str]
    long: frozenset[str]
    operands: tuple[str, ...]
    redirects: tuple[str, ...]
    # Keys of `VAR=value` words; values are in `operands`.
    assignments: frozenset[str] = frozenset()
    # Words the program reads as its own script (sed's, awk's), which name no file.
    code: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        "`operands` less the words in `code`."
        rest = list(self.operands)
        for word in self.code:
            if word in rest:
                rest.remove(word)
        return tuple(rest)


def parsed(command: str) -> list[Fragment]:
    """Every fragment of `command`, resolved and normalised."""
    out = []
    for words in fragments(command):
        args, targets = _redirects(words)
        index = _head_index(args)
        head = Path(args[index].strip("(){};&")).name if index >= 0 else ""
        # Everything but the program word, which need not be word 0.
        rest = args[:index] + args[index + 1:] if index >= 0 else args
        short, long, operands, assignments = normalize(rest, head)
        out.append(
            Fragment(head, short, long, operands, tuple(targets), assignments,
                     _script_words(head, args[index + 1:] if index >= 0 else [])))
    return out


def _lex(piece: str) -> list[str]:
    """Split one pipeline piece into words, with redirect operators as their own words (`a>b` -> `a`, `>`, `b`).

    rat-tail: descriptor forms only (`N>`, `&>`, `N>&M`); process substitution is left to `OPAQUE`, and `without_heredocs` has already cut heredoc bodies.
    """
    lexer = shlex.shlex(piece, posix=True, punctuation_chars=True)
    # Required, or `src/un/core.py` splits into several words.
    lexer.whitespace_split = True
    # Required, or `#` starts a comment.
    lexer.commenters = ""
    words: list[str] = []
    for word in lexer:
        # Rejoin `2`, `>&`, `1` into `2>&1`, only where the source had them adjacent.
        if words and words[-1].isdigit() and _REDIR_PREFIXED.match(word) and words[-1] + word in piece:
            words[-1] += word
        elif words and _REDIR_DUP.match(words[-1]) and word.isdigit() and words[-1] + word in piece:
            words[-1] += word
        else:
            words.append(word)
    return words


# A heredoc operator; `<<<` is a here-string, which `OPAQUE` owns.
_HEREDOC_OP = re.compile(r"(?<!<)<<(?!<)")
# The operator and its delimiter, matched only where bash reads the same word: bare, or wholly single-, double- or backslash-quoted.
_HEREDOC = re.compile(
    r"(?<!<)<<(?!<)(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|(\\?)([\w.\-]+))(?=[\s;&|<>()]|$)")
# `((...))` arithmetic, whose `<<` is a shift.
_ARITH = re.compile(r"\(\([^\n]*?\)\)")
# Interpreters, whose heredoc body is inline code that `permissions` judges as such.
INTERPRETERS = frozenset({"python", "python3", "perl", "ruby", "node", "php"})
# Programs that treat a heredoc body as data, provided no pipe carries it on.
# rat-tail: two programs; any other keeps its body parsed as commands, which fails closed. Add one when its false positives are reported.
_HEREDOC_DATA = frozenset({"cat", "tee"})


def _heredoc_reader(line: str, at: int) -> bool:
    """Whether the heredoc at `at` feeds an interpreter, or a data program whose output no pipe carries on."""
    start = max((m.end() for m in _SPLIT.finditer(line, 0, at)), default=0)
    after = _SPLIT.search(line, at)
    try:
        head = _head(_lex(line[start:after.start() if after else len(line)]))
    except ValueError:
        return False
    return head in INTERPRETERS or (head in _HEREDOC_DATA and not (after and after.group() == "|"))


def _heredocs(spoken: list[str], line: str, lines: list[str], index: int) -> list | None:
    """Each heredoc `line` opens, as (match, quoted, first body line, terminator line); None when bash's reading cannot be confirmed."""
    masked = _ARITH.sub(lambda m: " " * len(m.group()), line)
    # A trailing backslash continues the line, so the body starts later than the next line.
    if (len(line) - len(line.rstrip("\\"))) % 2:
        return None
    try:
        # A quote still open from an earlier line makes this one quoted text.
        _lex("\n".join(spoken))
        words = _lex(masked)
    except ValueError:
        return None
    comment = next((i for i, w in enumerate(words) if w.startswith("#")), len(words))
    found = list(_HEREDOC.finditer(masked))
    if not words[:comment].count("<<") == len(_HEREDOC_OP.findall(masked)) == len(found):
        return None
    out = []
    for match in found:
        dash, single, double, slash, bare = match.groups()
        delimiter = next(d for d in (single, double, bare) if d is not None)
        end = next((i for i in range(index, len(lines))
                    if (lines[i].lstrip("\t") if dash else lines[i]) == delimiter), None)
        if end is None:
            return None
        out.append((match, single is not None or double is not None or bool(slash), index, end))
        index = end + 1
    return out


def without_heredocs(command: str) -> str:
    """`command` with each heredoc body an interpreter or a data program reads cut out, its operator left as a bare `<<` word.

    An unquoted delimiter leaves the body's substitutions live, so they are kept, each on a line of its own. Any other heredoc keeps its body, parsed as commands; one bash's reading of cannot be confirmed stops the cutting, since every later line may be a body.
    """
    if not _HEREDOC_OP.search(command):
        return command
    lines = command.split("\n")
    out: list[str] = []
    spoken: list[str] = []
    live: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not _HEREDOC_OP.search(_ARITH.sub(" ", line)):
            out.append(line)
            spoken.append(line)
            continue
        heredocs = _heredocs(spoken, line, lines, index)
        if heredocs is None:
            return "\n".join(out + lines[index - 1:] + live)
        spoken.append(line)
        end = heredocs[-1][3] + 1
        if all(_heredoc_reader(line, match.start()) for match, *_ in heredocs):
            for match, quoted, first, last in reversed(heredocs):
                line = line[:match.start()] + "<<" + line[match.end():]
                if not quoted:
                    live.extend(m.group() for m in _SUBSHELL.finditer("\n".join(lines[first:last])))
            out.append(line)
        else:
            out.extend(lines[index - 1:end])
        index = end
    return "\n".join(out + live)


def fragments(command: str) -> list[list[str]]:
    """Every argv-shaped command inside `command`: pipeline parts, subshells and `sh -c` payloads."""
    command = without_heredocs(command)
    found: list[list[str]] = []
    for match in _SUBSHELL.finditer(command):
        found.extend(fragments(match.group(1) or match.group(2) or ""))
    text = _SUBSHELL.sub(" ", command)
    for piece in _SPLIT.split(text):
        piece = piece.strip()
        if not piece:
            continue
        try:
            words = _lex(piece)
        except ValueError:
            # Unbalanced quotes: fall back to a plain split.
            words = piece.split()
        if not words:
            continue
        found.append(words)
        # Recurse into `sh -c` payloads, found by head rather than `words[0]` (`FOO=1 sh -c`).
        if _head(words) in _SHELLS:
            for index, word in enumerate(words[1:], 1):
                if word == "-c" and index + 1 < len(words):
                    found.extend(fragments(words[index + 1]))
    return found


# --- frontmatter -------------------------------------------------------------------------


class frontmatter:
    """YAML frontmatter, read without raising and written back."""

    @staticmethod
    def split(text: str) -> tuple[str, str]:
        """Separate YAML frontmatter from the body. Neither part is parsed here."""
        if not text.startswith("---"):
            return "", text
        parts = text.split("---", 2)
        return (parts[1], parts[2]) if len(parts) == 3 else ("", text)


    @staticmethod
    def parse(text: str) -> tuple[dict, str, str | None]:
        """The frontmatter mapping, the stripped body, and an error or None. Never raises, so the body survives a bad header."""
        raw, body = frontmatter.split(text)

        error = None
        data: dict = {}
        try:
            parsed = yaml.safe_load(raw) if raw.strip() else {}
            if isinstance(parsed, dict):
                data = parsed
            elif parsed is not None:
                error = f"frontmatter is {type(parsed).__name__}, expected a mapping"
        except yaml.YAMLError as exc:
            # Class name only; yaml's messages are noisy.
            error = f"unparseable frontmatter: {exc.__class__.__name__}"

        return data, body.strip(), error


    @staticmethod
    def entries(value: str | list) -> list[str]:
        """A multi-value frontmatter value as a list of names: comma-split, stripped, blanks dropped."""
        items = [value] if isinstance(value, str) else value
        spelled = (part.strip() for item in items for part in str(item).split(","))
        return [name for name in spelled if name]


    @staticmethod
    def render(data: dict, body: str) -> str:
        """A document `parse` reads back, keeping key order. Raises on data yaml cannot represent."""
        return f"---\n{yaml.safe_dump(data, sort_keys=False)}---\n\n{body.strip()}\n"


# --- locks -------------------------------------------------------------------------------
#
# One lock per target path, never removed: a dropped lock stops working for whoever is queued on it.
# rat-tail: grows with distinct paths written; add eviction if that becomes unbounded.
_TABLE: dict[str, threading.Lock] = {}
_TABLE_LOCK = threading.Lock()


def _for(target: str) -> threading.Lock:
    with _TABLE_LOCK:
        return _TABLE.setdefault(target, threading.Lock())


@contextmanager
def locked(target: str | os.PathLike):
    """Hold `target` exclusively for the block, creating it if needed. Not reentrant: nesting on one thread deadlocks."""
    path = Path(target).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _for(str(path)):
        # No O_TRUNC: the file is opened only to lock it.
        handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            yield path
        finally:
            os.close(handle)


# --- redact ------------------------------------------------------------------------------
#
# Credentials out of anything written to disk. A COPY, never a mutation.


# Credential name vocabulary, shared by layers 1 and 3.
_NAMES = "KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS"

# Layer 1: values of credential-named environment variables are replaced anywhere.
_CREDENTIAL_NAME = re.compile(rf"_({_NAMES})$")

# rat-tail: values under 8 characters are not matched by value; too many false hits in prose.
_MIN_VALUE = 8

# Layer 2. A key an agent PASSED a credential under, rather than one it read.
_SECRET_KEYS = frozenset({"api_key", "token", "secret", "password", "authorization"})

# An assignment's right-hand side. The length floor skips settings like `PASSWORD_MIN_LENGTH = 12`; the lookahead, backtracking included, keeps it off calls like `os.environ.get(...)`.
_VALUE = (rf"\s*[=:]\s*[\"']?[A-Za-z0-9/+_.\-]{{{_MIN_VALUE},}}[\"']?"
          r"(?![A-Za-z0-9/+_.\-(])")

# Layer 3: credential shapes, for secrets read from disk that layer 1 never saw (ADR 0006).
_SHAPES = re.compile(
    r"(?P<anthropic>sk-ant-[A-Za-z0-9_-]{16,})"
    r"|(?P<github>gh[pousr]_[A-Za-z0-9]{16,})"
    r"|(?P<aws>AKIA[0-9A-Z]{16})"
    # Whole block, or the banner alone when a bounded record cut the key off.
    r"|(?P<pem>-----BEGIN[A-Z ]*PRIVATE KEY-----"
    r"(?:[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----)?)"
    r"|(?P<jwt>eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
    # Before `assignment`, which would otherwise claim `_authToken`.
    rf"|(?P<npm>_authToken{_VALUE})"
    # A credential-named assignment; the name must end in a vocabulary word.
    rf"|(?P<assignment>(?i:\w*_(?:{_NAMES})){_VALUE})"
)


def redact(row: dict) -> dict:
    """A copy of `row` with recognised credentials replaced; the caller's original is untouched."""
    return _scrub(row, _known())


def _known() -> list[tuple[str, str]]:
    """Credential-named environment values, longest first so a containing value is replaced whole. Read per call."""
    found = [(v, n) for n, v in os.environ.items()
             if _CREDENTIAL_NAME.search(n) and len(v) >= _MIN_VALUE]
    return sorted(found, key=lambda pair: len(pair[0]), reverse=True)


def _scrub(node, known, *, under=""):
    """Recurse to the string leaves. `under` is the secret-named key we are inside."""
    if isinstance(node, dict):
        return {k: _scrub(v, known, under=under or _secret(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub(v, known, under=under) for v in node]
    if isinstance(node, str):
        return f"[redacted:{under}]" if under else _text(node, known)
    return node


def _secret(key) -> str:
    return key if isinstance(key, str) and key.lower() in _SECRET_KEYS else ""


def _text(text: str, known) -> str:
    for value, name in known:
        text = text.replace(value, f"[redacted:{name}]")
    return _SHAPES.sub(lambda m: f"[redacted:{m.lastgroup}]", text)


# --- permissions ---------------------------------------------------------------
#
# Guard rails on tool use: one PreToolUse hook over three tables, walked deny-first. The operator surface is `.un/config.toml` (`[permissions]`: one boolean per togglable policy, plus `dangerous_allow`; `[sandbox]`: off by default, and when on, confinements that deny rather than ask) and `.un/permissions.toml` (operator rules). Absent means built-ins at their defaults; malformed refuses to start and names itself.
#
# Fail closed on import as much as on no match. See docs/adr/0001-enforcement-fails-closed.md.
#
# Read in this order: `DENY_COMMANDS` and its two siblings, `POLICIES`, `_LADDER` and `evaluate`, `_floor`, `_registered_tool`, `read_permissions`.

# --- module constants ----------------------------------------------------------

_PKG = Path(__file__).parent
_UN_ROOT = _PKG.parent.parent
PATH_TOOLS = frozenset({"Read", "Write", "Edit", "Glob", "Grep", "AstGrep"})
# Whose RULES may name a path, which is wider than whose CALLS are judged by one.
# `GitRo` turns one call into many paths and asks `denied_path` per result, the way
# `Grep` and `Glob` do - but its CALL names no path, and `_registered_tool` skips every
# member of `PATH_TOOLS`, so joining that set would cost the tool the allow that makes
# it usable and send every call to the tier. `Rule.parse` reads this one.
PATH_RULE_TOOLS = PATH_TOOLS | {"GitRo"}
# Membership means this tool's `pattern` IS the path it names. `Grep` and `AstGrep` also
# declare `pattern`, but theirs is a SEARCH EXPRESSION: read as a path it would bind
# nothing against the credential globs and refuse ordinary searches. A tool absent from
# here is not believed, which is the direction ADR-0001 fails in.
PATTERN_IS_PATH = frozenset({"Glob"})
# What a tool searches when it names no `path`. rat-tail: a literal, because the default
# lives on the Python signature rather than in the JSON schema. Kept true to `fs.grep`'s
# `path: str = "."` by hand; the two can drift.
NO_PATH = {"Grep": "."}
COMMAND_TOOLS = frozenset({"Bash"})

# The fourth matcher. A workflow is not a tool, so `Tool(...)` is not made to say it is:
# `Workflow(<name>)` claims ONE file-authored workflow by the name `un run` takes.
WORKFLOW_TOOL = "Workflow"

# What a LAUNCH is gated under, which is deliberately NOT the name of the `Workflow` tool.
# The two are separate calls and each is gated once: the agent loop gates the TOOL call,
# where `_registered_tool` allows it like any stock tool, and `workflows._file_workflow`
# gates the LAUNCH under this name, which no tool holds so it falls to the tier. One name
# for both would ask the operator the same question twice for one launch, which is how a
# person learns to answer without reading it.
WORKFLOW_LAUNCH = "WorkflowLaunch"
_RULE = re.compile(r"^(\w+)\(([^)]*)\)$")
BUILT_IN_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit", "AstGrep")
# The credential policies are generated across THIS tuple rather than the one above.
# `GitRo` returns file contents from a repository, so the four policies have to answer
# for its name - a rule generated for a name nothing asks under never fires, and a name
# asked under with no rule generated for it answers "" forever. See plan 108.
CREDENTIAL_TOOLS = BUILT_IN_TOOLS + ("GitRo",)
WRITE_TOOLS = ("Write", "Edit")
READONLY_PROGRAMS = ("ls", "cat", "echo", "pwd", "head", "tail", "wc", "which", "stat",
                     "du", "find", "diff")

# Everything that ENFORCES permissions, as paths: what DECIDES a verdict, what APPLIES
# one, what PERFORMS the action a verdict judged, what decides whether enforcement runs
# at all, and the two files an operator configures it with.
_PROTECTED = (
    # The two directories. No `/**` suffix: each matches the DIRECTORY and not its
    # contents, so `rm -rf <un>` is refused while `<un>/plugins/stock/repl.py` is writable.
    "<un>",
    "**/.un",
    # ---- decide the verdict ----
    "<un>/__init__.py",                             # re-exports the whole vocabulary
    "<un>/core.py",                                 # Verdict, decide, fire, Session.tier,
                                                    # the agent loop that applies one,
                                                    # what a command IS before any rule,
                                                    # the table and evaluate, the approval
                                                    # adapters that ANSWER ask, the writer
                                                    # of the allow array, and a subagent's
                                                    # tool scopes: grammar and DENY
    "<un>/plugins/stock/hooks.py",                  # a hook's exit code -> a Verdict
    "<un>/plugins/stock/workflows.py",              # imports and runs agent-authored code
    # ---- apply it ----
    # The loop that executes a judged call and the writer of the allow array live in
    # `core.py`, already named above.
    # ---- perform the action it judged ----
    "<un>/plugins/stock/shell.py",
    "<un>/plugins/stock/fs.py",
    # ---- decide whether enforcement runs at all ----
    "<un>/plugins/stock/cli.py",                    # load(), the tier
    "<un_root>/pyproject.toml",                     # declares un.plugins.stock
    # ---- the operator's inputs ----
    "**/.un/permissions.toml",
    "**/.un/config.toml",
    "**/.un/agents/**",
    "**/.un/hooks/**",
    "<un>/plugins/stock/plugin_config.py",
)

ASSUMED_ASK = "assumed_ask"
# Like `ASSUMED_ASK`: a table key rather than a decision `evaluate` can return. Its rung
# returns ALLOW, and keeping the table apart is what stops un's own default from being
# indistinguishable from an operator's `allow` line - `load` never touches this one.
PROJECT_READ = "project_read"
_DERIVED = {"write": ("Write", "Edit"), "read": ("Read", "Grep", "Glob", "AstGrep")}
_WHY_MENTION = "names the code that enforces permissions; an operator edits it by hand"
_SHADOWING = frozenset({
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PATH",
})
_WHY_SHADOW = ("places code ahead of the un package on a search path, so the module that "
               "enforces permissions is not the one on disk")
_CD = frozenset({"cd", "pushd"})
_WHY_CD = "enters a directory holding the code that enforces permissions"
_ARG_WIDTH = 120

TIERS = {"strict": ASK, "dangerous": ALLOW}

# The stock package. The trailing dot is the whole discriminator: without it
# `un.plugins.stockade` is admitted as stock.
_STOCK_PREFIX = f"{STOCK_GROUP}."
_WHY_REGISTERED = "a tool un ships; the rules above are what qualify it"

PERMISSIONS = UN_DIR / "permissions.toml"

_ARRAYS = {"deny": DENY, "ask": ASK, "allow": ALLOW}

_REMEMBERING = threading.Lock()


# --- the command surface -------------------------------------------------------
#
# What each Bash policy MATCHES, keyed by the policy's name - which is also its key in
# `[permissions]`. Three dicts, one per LEVEL; the KEY supplies `Policy.name` and the DICT
# supplies `Policy.decision`.
#
#   why       operator-facing prose, rendered after the rule text on a refusal. Lowercase,
#             no trailing period - it is a clause, not a sentence.
#   commands  `Rule` specs WITHOUT the `Bash(...)` wrapper. Nothing here is a regex.
#   note      OPTIONAL. Rendered above the key in a scaffolded `.un/config.toml`, saying
#             what turning the key OFF does.
#   toggle    OPTIONAL, default True. False is the FLOOR: no key, nothing turns it off.
#
# PATH policies stay hand-written in `POLICIES`, matching globs against paths rather than
# commands.

_COMMAND_FIELDS = frozenset({"why", "commands", "note", "toggle"})

DENY_COMMANDS = {
    # ---- floor: no toggle key, and nothing that lowers it ----
    "privilege_escalation": {
        "why": "escalates beyond what you were asked to do; ask the user to run it",
        "commands": ["sudo", "doas"],
        "toggle": False,
    },
    # rat-tail: `--a*` over-denies a long option `un` does not have, and costs one rule
    # instead of one per abbreviation of `--approval`.
    "approval_bypass": {
        "why": "this flag lets the run answer its own approvals",
        "commands": ["un:--a*"],
        "toggle": False,
    },
    # `un update` rewrites un's own code, this table included, from whatever path it is handed.
    "update_bypass": {
        "why": "replaces un's own code, the permission table included; ask the user to run it",
        "commands": ["un:update"],
        "toggle": False,
    },
    # Ahead of `git_read_only`, so `git -c ...` is refused by the rule that says WHY
    # rather than by the blanket one. `core.pager` is a shell command.
    "git_execution": {
        "why": "reaches arbitrary execution or a file write THROUGH git",
        "commands": ["git:-c", "git:--config-env", "git:--exec-path", "git:--output"],
        "toggle": False,
    },

    # ---- togglable: one boolean each in `[permissions]` ----
    "git_read_only": {
        "why": "raw git is restricted; the GitRo tool is the read-only route",
        "commands": ["git"],
        "note": "An agent driving git can make unrecoverable mistakes like stashing changes and dropping them. While this is enabled git is blocked for agents and they are provided a read only wrapper called git_ro.py instead.",
    },
    # Shaped after `git_read_only`, for the same reason: the program is denied WHOLE and a
    # gated tool is what makes the denial survivable. ADR 0002 kept `grep` out of
    # `READONLY_PROGRAMS` and named the `Grep` tool instead; this enforces that position.
    #
    # By PROGRAM, not by flag: `grep --recursive` carries no short flag for a `grep:-r`
    # rule to match, and a rule that misses the ordinary spelling reads as coverage.
    "grep_read_only": {
        "why": "raw grep reads whole files and un cannot judge what it returns; the Grep tool is the searching route",
        "commands": ["grep", "rg"],
        "note": "Not all system greps are the same, some are aliased to ugrep, and the possible combinations of grep and the ability to modify files with args is too much of a risk. Agents are provided with a sytem tool (Grep) which is a wrapper and ensures read only. With grep_read_only enabled all other greps are blocked for agent use and only Grep is available. It is unlikely you will need to disable this.",
    },
    # Separate from `grep_read_only` deliberately: nothing here has a tool that replaces
    # it, so sharing one key would mean restoring `tar` to get `cmd | grep x` back.
    #
    # `tar cf - .` settles the by-program question: `cf` lands in `operands`, where a
    # `tar:-c` rule looks in `short`, so a flag-scoped rule fails OPEN on it.
    "deny_bulk_read": {
        "why": "reads a whole tree without naming a file, so no path rule can judge what comes back",
        "commands": ["tar", "rsync", "zip"],
        "note": "This means that an agent could read sensitive contents like credentials. It is difficult to block every permutation of various system tools, so the tools themselves are blocked. Agents are provided Glob and ASTGrep. Disabling deny_bulk_read removes this.",
    },
    "deny_rm_recursive": {
        "why": "a recursive force delete cannot be undone; move it aside instead",
        "commands": ["rm:-rf"],
    },
    "deny_find_destructive": {
        "why": "find acts on everything it matched, without showing you first",
        "commands": ["find:-delete", "find:-exec", "find:-execdir", "find:-ok", "find:-okdir",
                     "find:-fprint", "find:-fprint0", "find:-fprintf", "find:-fls"],
        "note": "false lets -delete, -exec, -execdir, -ok and -okdir delete files or run any command, and -fprint, -fprint0, -fprintf and -fls overwrite any file, including .un/permissions.toml. Each is then allowed without asking.",
    },
    "deny_find_credentials": {
        "why": "lists the files in a directory that holds credentials",
        "commands": ["find:.ssh", "find:.ssh/", "find:*/.ssh", "find:*/.ssh/"],
        "note": "false lets find list the files in a .ssh directory; reading them stays refused either way. Only a find that names the directory is caught: a find over a parent directory still lists what is inside.",
    },
    "deny_destructive_disk": {
        "why": "formats, repartitions or wipes a disk; there is nothing to undo",
        "commands": ["mkfs*", "newfs_*", "wipefs", "diskutil", "hdiutil", "parted",
                     "fdisk", "gdisk", "sgdisk", "cryptsetup", "zpool",
                     "pvcreate", "vgcreate", "lvcreate", "gpt", "asr",
                     "dd:/dev/*"],
        "note": "false lets mkfs, parted, diskutil and the rest run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
    "deny_system_power": {
        "why": "powers down or restarts the machine, ending this session and everything else on it",
        "commands": ["shutdown", "reboot", "halt", "poweroff"],
        "note": "false lets these run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
    "deny_infra_teardown": {
        "why": "tears down infrastructure that is not rebuilt by re-running the command",
        "commands": ["terraform:destroy", "kubectl:delete", "aws:s3,rm,--recursive"],
        "note": "false lets terraform destroy and kubectl delete run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
}

ASSUMED_ASK_COMMANDS: dict[str, dict] = {
    "ask_in_place_edit": {
        "why": "edits a file in place, so the previous contents are gone",
        "commands": ["sed:-i", "perl:-pi"],
    },
    "ask_recursive_mode": {
        "why": "changes permissions or ownership over a whole tree",
        "commands": ["chmod:-R", "chown:-R"],
    },
    "ask_force_overwrite": {
        "why": "overwrites the destination without asking",
        "commands": ["mv:-f", "cp:-f", "truncate"],
    },
    "ask_process_kill": {
        "why": "terminates a process that may not be this session's",
        "commands": ["kill:-9", "pkill", "killall"],
    },
    "ask_service_control": {
        "why": "stops or disables a system service",
        "commands": ["systemctl:stop", "systemctl:disable"],
    },
}

ALLOW_COMMANDS = {
    "allow_readonly_commands": {
        "why": "These are safe read-only commands that are already allowed for agents, meaning you do  not need to add entries into permission.toml",
        "commands": list(READONLY_PROGRAMS),
        "note": "Disabling allow_readonly_commands will result in every one becoming a Ask unless you add entries in permission.toml.",
    },
}


# --- rules -----------------------------------------------------------------------

# HOME is passed through to every child unchanged (`core.PASS_THROUGH`), so the shell expands it to the value un holds.
_HOME_VAR = re.compile(r"^(?:\$HOME|\$\{HOME\})(?=/|$)")


def _home_expanded(word: str) -> str:
    home = os.environ.get("HOME")
    return _HOME_VAR.sub(lambda _: home, word, count=1) if home else word


def _resolve(session: Session, path: str) -> Path:
    candidate = Path(_home_expanded(path))
    # The shell expands a leading `~`; judged literally, `~/x` reads as inside the project.
    try:
        candidate = candidate.expanduser()
    except RuntimeError:
        # An unknown `~user` is left literal by the shell too.
        pass
    if not candidate.is_absolute():
        candidate = session.cwd / candidate
    return candidate.resolve()

@dataclass(frozen=True)
class Rule:
    """One entry in the table, and the thing a verdict names.

    `text` is the rule as written, `why` is operator-facing prose, and `unless` comes down
    from the rule's GROUP so the grammar stays one glob per rule.
    """

    text: str
    tool: str
    spec: str
    why: str = ""
    negated: bool = False
    program: str = ""
    short: frozenset[str] = frozenset()
    long: tuple[str, ...] = ()
    operands: tuple[str, ...] = ()
    unless: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str, why: str = "", unless: tuple[str, ...] = ()) -> "Rule":
        "`tool(spec)`, rejecting anything no matcher can decide."
        match = _RULE.match(text.strip())
        if not match:
            raise ValueError(f"{text!r} is not a rule: expected tool(spec)")
        tool, spec = match.group(1), match.group(2)
        if tool == RESERVED_TOOL:
            # All-or-nothing for one tool, by NAME. Not registry-checked here, because
            # `parse` runs at import before any tool has registered.
            if ":" in spec:
                raise ValueError(
                    f"{text!r}: a Tool rule takes a name only, not a spec")
            # Emptiness is judged AFTER stripping, or `Tool( )` claims a tool no name
            # can equal.
            if not (spec := spec.strip()):
                raise ValueError(f"{text!r}: names no tool")
            return cls(text, tool, spec, why, unless=unless)
        if tool == WORKFLOW_TOOL:
            # A name only, for `Tool`'s reason one branch up: there is nothing inside a
            # launch for a spec to select on, so a colon is a rule that can never match.
            if ":" in spec:
                raise ValueError(
                    f"{text!r}: a Workflow rule takes a name only, not a spec")
            if not (spec := spec.strip()):
                raise ValueError(f"{text!r}: names no workflow")
            return cls(text, tool, spec, why, unless=unless)
        if tool in PATH_RULE_TOOLS:
            negated = spec.startswith("!")
            return cls(text, tool, spec[1:] if negated else spec, why, negated,
                       unless=unless)
        if tool not in COMMAND_TOOLS:
            raise ValueError(f"{text!r}: no matcher decides {tool!r}")
        program, colon, terms = spec.partition(":")
        if not program:
            raise ValueError(f"{text!r}: names no program")
        if colon and not terms:
            raise ValueError(f"{text!r}: empty term")
        short: set[str] = set()
        long: list[str] = []
        operands: list[str] = []
        single_dash_is_long = program in LONGOPT
        for term in terms.split(",") if terms else []:
            if not term:
                raise ValueError(f"{text!r}: empty term")
            if term.startswith("--") or (single_dash_is_long and term.startswith("-")):
                long.append(term.lstrip("-"))
            elif term.startswith("-"):
                short.update(term[1:])
            else:
                operands.append(term)
        return cls(text, tool, spec, why, False, program,
                   frozenset(short), tuple(long), tuple(operands), unless)

    @property
    def names_path(self) -> bool:
        "Whether this rule names a PATH, as opposed to a program or a tool."
        return (self.tool in PATH_TOOLS
                or (self.tool in COMMAND_TOOLS and bool(self.operands)))


def _substitute(spec: str, session: Session) -> str:
    """Resolve the tokens a static glob cannot spell, then anchor what is still relative. Resolved per CALL, so the table stays shareable and a session that changed directory holds no stale rule.

    A spec that is none of absolute, wildcard-led or token-led is a RELATIVE one, and `_path_matches` resolves the TARGET absolutely - so left alone an operator who wrote `deny = ["Read(src/**)"]` would have blocked nothing. Anchored on `session.root` rather than `cwd`, because a rule's meaning is a fact about the PROJECT.

    The test runs AFTER substitution, so `<` survives only for a token nothing here recognises. Every built-in path spec begins with `/`, `*` or `<`, so this branch is unreachable for all of them.
    """
    root = session.root.resolve().as_posix()
    resolved = (spec.replace("<cwd>", session.cwd.resolve().as_posix())
                    .replace("<project>", root)
                    .replace("<sessions>", SESSIONS.as_posix())
                    .replace("<oauth>", OAUTH.as_posix())
                    .replace("<un_root>", _UN_ROOT.as_posix())
                    .replace("<un>", _PKG.as_posix()))
    if resolved[:1] in ("/", "*", "<"):
        return resolved
    # `./src/**` is the same intent as `src/**`; joined unstripped it produces a `/./`
    # segment that `fnmatch` compares literally against a resolved target with none.
    return f"{root}/{resolved.removeprefix('./')}"


def _fragment_matches(rule: Rule, frag: Fragment) -> bool:
    "One bash rule against one fragment: head MATCHED, and EVERY term present."
    return (bool(rule.program)
            and bool(frag.head)
            and fnmatch.fnmatch(frag.head, rule.program)
            and rule.short <= frag.short
            and all(any(fnmatch.fnmatch(name, term) for name in frag.long)
                    for term in rule.long)
            and all(any(fnmatch.fnmatch(word, term) for word in frag.operands)
                    for term in rule.operands))


def _path_globbed(resolved: str, pattern: str) -> bool:
    "One resolved path against one glob."
    return (fnmatch.fnmatch(resolved, pattern)
            or (pattern.endswith("/**") and fnmatch.fnmatch(resolved, pattern[:-3])))


def _path_matches(rule: Rule, session: Session, target: str) -> bool:
    """One resolved path against one glob, honouring `unless`, `!` and the tokens."""
    if not target:
        return False
    resolved = _resolve(session, target).as_posix()
    # Ahead of the rule's own glob AND of the inversion: `unless` says this rule does not
    # CLAIM the path, which is different from "matched, then negated". A rule that let go
    # here has no opinion, so the rest of the table is still asked.
    if any(_path_globbed(resolved, _substitute(spec, session)) for spec in rule.unless):
        return False
    hit = _path_globbed(resolved, _substitute(rule.spec, session))
    return not hit if rule.negated else hit


def _tool_claims(rule_tool: str, name: str) -> bool:
    """Whether a rule written for `rule_tool` speaks for a call to `name`.

    An `Edit` reads a file, replaces one occurrence and writes it back, so a rule about
    WRITING that path is about the edit too. Never the reverse: `Write` creates files and
    parent directories and truncates whole ones, and an `Edit` rule naming a path grants
    no such thing.

    Global rather than operator-only because there is no built-in rule it can reach: every
    built-in `Write` spec is generated by `_across`, which already emits the `Edit` twin.
    """
    return rule_tool == name or (name == "Edit" and rule_tool == "Write")


_GLOB = ("*", "?", "[")


def _widened(item: str, rule: Rule) -> str:
    """An operator's path spec naming a directory covers what is inside it.

    Operator rules only - `_PROTECTED`'s two directory entries carry no `/**` precisely so
    they match the directory and not its contents, which is what refuses `rm -rf <un>`
    while leaving un's own non-enforcement code writable. A spec that already carries a
    glob is what the operator meant, and an EMPTY spec is left alone: `/**` would match
    every path there is.

    Returns the rule TEXT for the caller to re-parse, so `text` and `spec` cannot disagree
    and `Rule.parse` stays the only place that knows what a rule is.
    """
    if rule.tool not in PATH_TOOLS or not rule.spec or any(g in rule.spec for g in _GLOB):
        return item
    return f"{rule.tool}({'!' if rule.negated else ''}{rule.spec.rstrip('/')}/**)"


def _target(name: str, args: dict) -> str:
    """The path an argument dict names, for the tool it names it for.

    By tool, because `pattern` means two things: the path `Glob` will list, and the
    expression `Grep` will match. A tool with neither gets the empty string, which
    `_path_matches` refuses outright.
    """
    if path := args.get("path"):
        return path
    if name in PATTERN_IS_PATH:
        return args.get("pattern") or ""
    return NO_PATH.get(name, "")


# --- policies ------------------------------------------------------------------


def _across(tools: tuple[str, ...], *specs: str) -> tuple[str, ...]:
    """One rule per tool per spec. The table's only repetition, written once."""
    return tuple(f"{tool}({spec})" for spec in specs for tool in tools)


@dataclass(frozen=True)
class Policy:
    "One reason, and every rule that exists for it."

    name: str
    decision: str
    why: str
    rules: tuple[str, ...]
    toggle: bool = True
    unless: tuple[str, ...] = ()
    note: str = ""


def _command_policies(decision: str, entries: dict[str, dict]) -> tuple[Policy, ...]:
    "One `Policy` per entry, the key as its name and `decision` as its decision."
    built = []
    for name, entry in entries.items():
        if unknown := entry.keys() - _COMMAND_FIELDS:
            raise ValueError(f"{name!r}: unknown field(s) {sorted(unknown)}")
        if not entry.get("why"):
            raise ValueError(f"{name!r}: names no reason")
        commands = entry.get("commands")
        if not commands:
            raise ValueError(f"{name!r}: names no commands")
        if isinstance(commands, str):
            raise ValueError(f"{name!r}: commands is a string, not a list of them")
        # An `ASSUMED_ASK` has no key BY DEFINITION, so the class decides rather than
        # every entry repeating `"toggle": False`.
        if decision == ASSUMED_ASK and entry.keys() & {"toggle", "note"}:
            raise ValueError(f"{name!r}: an assumed ask has no toggle key")
        built.append(Policy(
            name, decision, entry["why"],
            tuple(f"Bash({command})" for command in commands),
            toggle=decision != ASSUMED_ASK and entry.get("toggle", True),
            note=entry.get("note", "")))
    return tuple(built)


POLICIES = (
    # ---- floor: no toggle key, and nothing that lowers it ----
    Policy("enforcement_code", DENY,
          "the code that enforces permissions; an operator edits it by hand",
          _across(WRITE_TOOLS, *_PROTECTED), toggle=False),
    # ---- every command deny, generated ----
    *_command_policies(DENY, DENY_COMMANDS),
    Policy("env_files", DENY, "usually holds credentials",
          _across(CREDENTIAL_TOOLS, "**/.env*"), toggle=False,
          unless=("**/.env.example", "**/.env.sample", "**/.env.template")),
    Policy("private_keys", DENY, "a private key or ssh identity",
          _across(CREDENTIAL_TOOLS, "**/*.pem", "**/.ssh/*", "**/id_rsa*", "**/id_ecdsa*",
                  "**/id_ed25519*"),
          toggle=False),
    Policy("credentials", DENY, "usually holds credentials or a registry token",
          _across(CREDENTIAL_TOOLS, "**/*credentials*", "**/.npmrc", "**/.pypirc"),
          toggle=False),
    Policy("oauth_credentials", DENY, "un keeps OAuth bearer tokens here",
          _across(CREDENTIAL_TOOLS, "**/<oauth>/**"), toggle=False),
    Policy("session_record", DENY, "un writes its own transcripts here",
          _across(WRITE_TOOLS, "**/<sessions>/**"), toggle=False),
    # `git_ro_tool`, `session_read_tool` and `candidate_tool` stood here, one floor ALLOW
    # per sanctioned stock tool. `_registered_tool` states the same thing generally, and
    # additionally requires the stock package.

    # ---- togglable: one boolean each in `[permissions]` ----
    Policy("deny_write_git_dir", DENY, "this path is managed by tooling, not by hand",
          _across(WRITE_TOOLS, "**/.git/**")),

    # ---- project reads: un's own default, its own rung, no key ----
    # Nothing else in the table allows it, so every in-project read fell through to the
    # tier's question. The READ tools only: a write inside the project is still asked.
    Policy("project_reads", PROJECT_READ, "inside the project directory",
          _across(_DERIVED["read"], "<project>/**"), toggle=False),

    # ---- assumed ask: un's own defaults, no key and no permissions.toml entry ----
    Policy("ask_outside_project", ASSUMED_ASK, "outside the project directory",
          _across(BUILT_IN_TOOLS, "!<project>/**"), toggle=False),
    Policy("ask_un_dir", ASSUMED_ASK, "un's own configuration directory",
          _across(WRITE_TOOLS, "**/.un/**"), toggle=False),
    *_command_policies(ASSUMED_ASK, ASSUMED_ASK_COMMANDS),
    *_command_policies(ALLOW, ALLOW_COMMANDS),
)

DEFAULT_TOGGLES = {p.name: True for p in POLICIES if p.toggle} | {
    "dangerous_allow": False}


# --- the sandbox ---------------------------------------------------------------
#
# A second table, kept out of `POLICIES` because `DEFAULT_TOGGLES` turns on everything
# togglable and a sandbox is off until asked for. Every entry is a DENY: `evaluate` widens
# an ASK under `dangerous_allow` and leaves a DENY alone, which is what makes this a bound.

_INLINE_CODE = ("python:-c", "python3:-c", "perl:-e", "node:-e", "ruby:-e",
                "python:<<", "python3:<<", "perl:<<", "node:<<", "ruby:<<")

SANDBOX_POLICIES = (
    Policy("confine_outside_project", DENY,
           "the sandbox confines this session to the project directory; release with [sandbox] confine_outside_project = false",
           _across(BUILT_IN_TOOLS, "!<project>/**"),
           note="false restores the pre-sandbox policy: strict asks about paths outside the project and dangerous_allow widens that ask to an allow. Where the un package is installed outside the project, this key is the only thing confining it."),
    Policy("confine_un_dir", DENY,
           "the sandbox protects un's own configuration directory; release with [sandbox] confine_un_dir = false",
           _across(WRITE_TOOLS, "**/.un/**"),
           note="Writes only. Reads inside the project stay allowed either way, so the agent keeps its memory, rules and skills. false restores the pre-sandbox ask on the write."),
    Policy("confine_un_package", DENY,
           "the sandbox protects un's own code; release with [sandbox] confine_un_package = false",
           _across(WRITE_TOOLS, "<un>/**"),
           note="Applies only where the un package sits inside the project directory; elsewhere confine_outside_project covers it. false restores the pre-sandbox policy, which for the unprotected part of the package is no rule at all: strict asks and dangerous_allow allows."),
    Policy("confine_inline_code", DENY,
           "the sandbox refuses inline interpreter code, which names no path for a rule to judge; release with [sandbox] confine_inline_code = false",
           tuple(f"Bash({command})" for command in _INLINE_CODE),
           note="Best effort and nothing more. python3.12 -c, an interpreter not listed here, and writing a script then running it all defeat it. Mode 1 does not contain arbitrary code execution."),
)

DEFAULT_SANDBOX = {"enabled": False, "mode": 1} | {
    policy.name: True for policy in SANDBOX_POLICIES}

_SANDBOX_MODES = (1, 2)
_WHY_MODE_2 = ("[sandbox] mode 2 is reserved for an external sandbox provider and is not "
               "implemented; set mode = 1, or enabled = false to run unconfined")


def _table(decision: str, toggles: dict[str, bool]) -> tuple[Rule, ...]:
    "Every ENABLED rule of one decision, in policy order."
    return tuple(
        Rule.parse(text, policy.why, policy.unless)
        for policy in POLICIES
        if policy.decision == decision and (not policy.toggle or toggles[policy.name])
        for text in policy.rules
    )


DENY_TABLE = _table(DENY, DEFAULT_TOGGLES)
ASK_TABLE = _table(ASK, DEFAULT_TOGGLES)
ALLOW_TABLE = _table(ALLOW, DEFAULT_TOGGLES)
ASSUMED_ASK_TABLE = _table(ASSUMED_ASK, DEFAULT_TOGGLES)
PROJECT_READ_TABLE = _table(PROJECT_READ, DEFAULT_TOGGLES)
_PROTECTED_RULES = tuple(Rule.parse(f"Write({spec})") for spec in _PROTECTED)


def _protected(session: Session, target: str) -> bool:
    "Is this path one of the enforcement entries?"
    return any(_path_matches(rule, session, target) for rule in _PROTECTED_RULES)


def _protected_dir(session: Session, target: str) -> bool:
    "Is this a directory that HOLDS an enforcement entry?"
    resolved = _resolve(session, target)
    return (resolved == _PKG or _PKG in resolved.parents
            or UN_DIR.name in resolved.parts)


def _floor(session: Session, name: str, args: dict,
           frags: list[Fragment]) -> Verdict | None:
    if name in COMMAND_TOOLS and (
            shell := SHELL_EXEC.search(without_heredocs(args.get("command") or ""))):
        return Verdict(DENY, f"shell exec: {SHELL_EXEC_WHY[shell.lastgroup]}")
    for frag in frags:
        if shadowing := frag.assignments & _SHADOWING:
            return Verdict(DENY, f"{sorted(shadowing)[0]}=: {_WHY_SHADOW}")
        if frag.head in _CD:
            for operand in frag.operands:
                if _protected_dir(session, operand):
                    return Verdict(DENY, f"cd {operand}: {_WHY_CD}")
        if frag.head in READONLY_PROGRAMS:
            continue
        for operand in frag.operands:
            if _protected(session, operand):
                return Verdict(
                    DENY, f"{frag.head or '(assignment)'} {operand}: {_WHY_MENTION}")
    return None


def _opaque(session: Session, name: str, args: dict,
            frags: list[Fragment]) -> Verdict | None:
    if name not in COMMAND_TOOLS:
        return None
    if opaque := OPAQUE.search(without_heredocs(args.get("command") or "")):
        return Verdict(ASK, f"opaque: {OPACITY[opaque.lastgroup]}")
    # A heredoc into an interpreter is inline code, as `-c` is.
    if any(frag.head in INTERPRETERS and "<<" in frag.operands for frag in frags):
        return Verdict(ASK, f"opaque: {OPACITY['interpreter']}")
    # A path built from any variable but HOME is only known once the shell runs.
    for frag in frags:
        for word in (*frag.operands, *frag.redirects):
            if "$" in _home_expanded(word):
                return Verdict(ASK, f"opaque: {word} is built from a variable, so the path it names is not known until it runs")
    return None


# --- the four doors ---------------------------------------------------------------


def _verdict(decision: str, rule: Rule | None, word: str = "") -> Verdict | None:
    """A rule as the thing an operator is shown, or `None` when there was no rule. `word` is the command word a path rule matched."""
    if rule is None:
        return None
    reason = f"{rule.text}: {rule.why}"
    if word:
        reason += f"; the command word {_shown(word)} was read as a path"
    return Verdict(decision, reason, rule=rule.text)


def _claims(rule: Rule, session: Session, name: str, args: dict,
            frag: Fragment | None, implied: bool = True) -> bool:
    if rule.tool == WORKFLOW_TOOL:
        # Both halves. The rule's spec must equal the workflow being launched, AND the
        # CALL must be a launch - without the second, `Workflow(deploy)` would also claim
        # a tool called `deploy`, since `_allow_tool` now walks these rules too.
        return name == WORKFLOW_LAUNCH and rule.spec == (args.get("name") or "")
    if rule.tool == RESERVED_TOOL:
        # By EXACT name: tools are PascalCase, so `Bash(grep)` and `Grep` stay apart.
        return rule.spec == name
    if frag is None:
        # `implied` is the caller's PASS, not a property of the rule: an exact tool match
        # is the better explanation of a verdict, so every table is walked for one before
        # the implication is allowed to answer. See `_objection` and `_path_allowed`.
        matched = _tool_claims(rule.tool, name) if implied else rule.tool == name
        return matched and _path_matches(rule, session, _target(name, args))
    if rule.tool in COMMAND_TOOLS:
        return _fragment_matches(rule, frag)
    # A path the COMMAND names, judged by the rules for the operation it is named for,
    # inverted confinement rules included: the same ASK the `read` tool gets, reached by
    # the other route. Asked per FRAGMENT, so the caller chooses its quantifier.
    operation = next((k for k, tools in _DERIVED.items() if rule.tool in tools), None)
    if operation is None:
        return False
    return any(_path_matches(rule, session, path) for path in _judged(frag, operation))


def _judged(frag: Fragment, operation: str) -> tuple[str, ...]:
    """The words of `frag` a derived path rule judges: redirect targets for a write, paths for a read."""
    return frag.redirects if operation == "write" else frag.paths


def _path_word(rule: Rule, session: Session, frags: list[Fragment]) -> str:
    """The command word a derived path rule matched, or "" for any other rule."""
    operation = next((k for k, tools in _DERIVED.items() if rule.tool in tools), None)
    if operation is None:
        return ""
    return next((word for frag in frags for word in _judged(frag, operation)
                 if _path_matches(rule, session, word)), "")


def _objection(session: Session, name: str, args: dict, frags: list[Fragment],
               *, decision: str, table: tuple[Rule, ...]) -> Verdict | None:
    # Exact tool match first, the implication second. A built-in path policy is generated
    # by `_across`, which emits the `Write` spec and its `Edit` twin, so a single walk
    # would report the `Write` one for every `Edit` call and an operator would be shown a
    # rule that is true but is not the entry naming their tool. Both passes carry the same
    # `decision`, so this chooses which rule is REPORTED and never whether one fires.
    # rat-tail: the second pass repeats the walk for tools no implication reaches; the
    # tables are dozens of rules and this runs once per call. Guard it on the tool name if
    # a profile ever says otherwise.
    for implied in (False, True):
        for rule in table:
            # A `Tool` rule names the tool, and a path rule against a path tool names one
            # path, so neither is quantified over fragments.
            if rule.tool == RESERVED_TOOL or name not in COMMAND_TOOLS:
                hit = _claims(rule, session, name, args, None, implied)
            else:
                hit = any(_claims(rule, session, name, args, frag, implied)
                          for frag in frags)
            if hit:
                # A Bash call names no path of its own, so say which word was taken for one.
                word = _path_word(rule, session, frags) if name in COMMAND_TOOLS else ""
                return _verdict(decision, rule, word)
    return None


def _allow_tool(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    # Both claim-by-name rule kinds. `_claims` holds them apart by the call's name, so a
    # `Workflow(x)` rule cannot allow a tool called `x`; this rung is the one that already
    # exists for "a rule naming a thing outright", so neither a new rung nor a new
    # adjacency is introduced.
    return _verdict(ALLOW, next(
        (r for r in ALLOW_TABLE
         if r.tool in (RESERVED_TOOL, WORKFLOW_TOOL)
         and _claims(r, session, name, args, None)), None))


def _allow_program(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    if name not in COMMAND_TOOLS or not frags:
        return None
    found = None
    for frag in frags:
        if frag.redirects:
            return None
        match = next((r for r in ALLOW_TABLE if r.tool in COMMAND_TOOLS
                      and _claims(r, session, name, args, frag)), None)
        if match is None:
            return None
        found = found or match
    return _verdict(ALLOW, found)


def _path_allowed(session: Session, name: str, args: dict, frags: list[Fragment],
                  table: tuple[Rule, ...]) -> Verdict | None:
    """One PATH table against a call: the target a path tool names, or the paths a command does.

    Two rungs share this - `allow_path` over the operator's table and `project_read` over
    un's own. Deliberately NOT an `_objection` walk: `_claims` routes a `Read(...)` rule
    against a Bash call through `_DERIVED` without looking at the fragment head, so it
    would allow `rm src/x.py` on the grounds that its operand is readable.

    EVERY path a call names must be matched, so one unmatched operand withdraws the whole
    verdict rather than allowing the call on the strength of its innocent half.
    """
    if name in PATH_TOOLS:
        target = _target(name, args)
        # Exact tool match first, for the reason `_objection` states.
        for implied in (False, True):
            match = next(
                (rule for rule in table
                 if rule.names_path
                 and (_tool_claims(rule.tool, name) if implied else rule.tool == name)
                 and _path_matches(rule, session, target)), None)
            if match is not None:
                return _verdict(ALLOW, match)
        return None
    if name not in COMMAND_TOOLS or not frags:
        return None
    found = None
    for frag in frags:
        named = {"write": frag.redirects}
        if frag.head in READONLY_PROGRAMS:
            named["read"] = frag.paths
        if not any(named.values()):
            return None
        for operation, paths in named.items():
            for path in paths:
                match = next(
                    (rule for rule in table
                     if rule.names_path
                     and ((rule.tool in _DERIVED[operation]
                           and _path_matches(rule, session, path))
                          or (rule.tool in COMMAND_TOOLS
                              and _fragment_matches(rule, frag)
                              and any(fnmatch.fnmatch(path, term)
                                      for term in rule.operands)))),
                    None)
                if match is None:
                    return None
                found = found or match
    return _verdict(ALLOW, found)


def _allow_path(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _path_allowed(session, name, args, frags, ALLOW_TABLE)


def _project_read(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _path_allowed(session, name, args, frags, PROJECT_READ_TABLE)

def allow_rule(session: Session, name: str, args: dict) -> tuple[str, str]:
    frag = None
    if name in PATH_TOOLS:
        if not (target := _target(name, args)):
            return "", f"{name} named no path"
        text = f"{name}({_resolve(session, target).as_posix()})"
    elif name in COMMAND_TOOLS:
        frags = parsed(args.get("command") or "")
        if len(frags) != 1:
            return "", f"{len(frags)} commands in one call; allow each on its own"
        frag = frags[0]
        if frag.redirects:
            return "", "the command writes through a redirect"
        if not frag.head:
            return "", "the command names no program"
        terms = [f"-{''.join(sorted(frag.short))}"] if frag.short else []
        terms += [f"--{option}" for option in sorted(frag.long)]
        terms += list(frag.operands)
        text = f"Bash({frag.head}:{','.join(terms)})" if terms else f"Bash({frag.head})"
    elif name == WORKFLOW_LAUNCH:
        # One workflow, not every workflow. The fall-through below would spell
        # `Tool(WorkflowLaunch)`, which is what `permissions:remember` would then persist on an
        # "always" answer - authorising the whole of `.un/workflows/`, including files
        # written after the operator answered.
        if not (workflow := str(args.get("name") or "").strip()):
            return "", "the launch names no workflow"
        text = f"{WORKFLOW_TOOL}({workflow})"
    else:
        text = f"Tool({name})"
    try:
        rule = Rule.parse(text)
    except ValueError as exc:
        return "", str(exc)
    if frag is not None and not _fragment_matches(rule, frag):
        return "", f"{text} does not match the command it came from"
    if name in PATH_TOOLS and not _path_matches(rule, session, _target(name, args)):
        return "", f"{text} does not match the path it came from"
    return text, ""


def _shown(value: object, width: int | None = _ARG_WIDTH) -> str:
    """One argument, as the operator reads it. `width` is None to withhold nothing.

    The caller decides, because the two callers want opposite things - see `describe`.
    """
    text = repr(value)
    if width is None or len(text) <= width:
        return text
    return f"{text[:width]}... ({len(text)} chars)"


@service("permissions:denied_path")
def denied_path(session: Session, name: str, path: str) -> str:
    """The DENY rule refusing `name` this path, as `Rule.text` spells it, or `""`.

    For a call that produces MANY paths from one target: `evaluate` judges the target a
    call NAMES, where a `Grep` rooted at `.` returns results from beneath it that no
    verdict ever saw. The table stays here and the seam asks per result.

    By the CALLING tool's name, not by `Read`: the credential policies are generated with
    `_across(BUILT_IN_TOOLS, ...)`, so a `Grep` rule exists beside every `Read` one.
    """
    verdict = _deny(session, name, {"path": path}, [])
    return verdict.rule if verdict else ""


@service("permissions:describe")
def describe(name: str, args: dict, *, full: bool = False) -> str:
    """One call, rendered for a person. `full` keeps every argument whole.

    Cut by DEFAULT, because the caller that fires on every attempted call is `core.gate`'s
    announcement and a `Write` carries a whole file in `content` - uncut, one edit fills the
    turn. `full=True` is for `ask` below: an operator is being asked to authorise this exact
    call, and approving what you cannot read is the failure that costs more than a long line.

    ONE function with a flag rather than two renderers. The operator sees the announcement
    and then the question, so the two must be the same line wherever nothing was withheld.
    """
    width = None if full else _ARG_WIDTH
    return f"{name}({', '.join(f'{k}={_shown(v, width)}' for k, v in args.items())})"


@service("permissions:ask")
def permission_question(session: Session, name: str, args: dict, verdict: Verdict) -> tuple[str, str]:
    rule, why = allow_rule(session, name, args)
    offer = f"a -> allow {rule}" if rule else f"a -> unavailable: {why}"
    # WHOLE. This is the one place a person decides whether the call runs, and a command cut
    # at `_ARG_WIDTH` is one they are approving unseen.
    return (f"{describe(name, args, full=True)}\n  {verdict.reason}\n  {offer}\n"
            f"Allow it? [{'y/N/a' if rule else 'y/N'}]"), rule


# --- the ladder ------------------------------------------------------------------
#
# The three table rungs are written out rather than built with `functools.partial`: a
# partial binds its `table` argument to the TUPLE OBJECT at import, where `load` REBINDS
# these globals. These read the global at CALL time.


def _deny(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=DENY, table=DENY_TABLE)


def _ask(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=ASK, table=ASK_TABLE)


def _assumed_ask(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=ASK,
                      table=ASSUMED_ASK_TABLE)


def _registered_tool(session: Session, name: str, args: dict,
                     frags: list[Fragment]) -> Verdict | None:
    """Every tool a STOCK plugin registered, allowed because it is registered.

    The registry is read per CALL rather than folded into a table at load, because
    `core._drop` clears a disabled plugin's registrations mid-session and a table built at
    launch would keep allowing a tool that no longer exists.

    **It answers for the tool NAME, never for a call whose ARGUMENTS un can already judge.**
    A `Tool(NAME)` rule is all-or-nothing, so returning one for `Bash` would allow the
    COMMAND as well and short-circuit every command rule below. So the tools with their own
    argument-level matcher are skipped here and keep being decided by that matcher and then
    by the tier. An operator's `Tool(Bash)` DENY still refuses the tool wholesale.

    The `Workflow` TOOL is not skipped and is allowed here like any other stock tool. What
    an operator is asked about is the LAUNCH, gated separately under `WORKFLOW_LAUNCH`,
    which no tool holds - so it reaches the tier on its own and the two calls cost one
    question between them rather than two.

    Stock only, and that is TWO tests. An aftermarket plugin is opt-in (ADR-0013), so a
    third party's tools stay at the tier's question - the module test. A DROPPED-IN tool
    needs the second: `tools._script_tool` returns a closure defined in the stock package, so
    its `__module__` is stock however foreign the script it spawns. `un_from_file` is the
    marker `core.scan` already stamps for `plugin_config.listing`.
    """
    if name in COMMAND_TOOLS or name in PATH_TOOLS:
        return None
    registered = REGISTRY["tool"].get(name)
    if registered is None or not registered.__module__.startswith(_STOCK_PREFIX):
        return None
    if getattr(registered, "un_from_file", False):
        return None
    return Verdict(ALLOW, f"{RESERVED_TOOL}({name}): {_WHY_REGISTERED}",
                   rule=f"{RESERVED_TOOL}({name})")


def _tier(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict:
    return Verdict(TIERS[session.tier], f"{session.tier}: no rule matched {name}")

_LADDER = (
    ("floor",         _floor),
    ("deny",          _deny),
    ("opaque",        _opaque),
    ("ask",           _ask),
    ("allow_path",    _allow_path),
    # Below the operator's own allows and above the confinement ask: every objection an
    # operator can write outranks un's default.
    ("project_read",  _project_read),
    ("assumed_ask",   _assumed_ask),
    ("allow_tool",    _allow_tool),
    ("allow_program", _allow_program),
    # Below every objection AND below both operator allow rungs, so a rule somebody wrote
    # always names itself. Above `tier` alone, which is why adding it moved no adjacency.
    ("registered_tool", _registered_tool),
    ("tier",          _tier),
)


@hook("PreToolUse")
def evaluate(*, session: Session, name: str, args: dict) -> Verdict:
    default = TIERS[session.tier]
    frags = parsed(args.get("command") or "") if name in COMMAND_TOOLS else []
    verdict = None
    for _, step in _LADDER:
        if verdict := step(session, name, args, frags):
            break
    if verdict.decision == ASK and default == ALLOW:
        # The rule is carried THROUGH the widening: something objected and the tier
        # overruled it, which is a different fact from nothing objecting at all.
        return Verdict(ALLOW, f"{session.tier}: {verdict.reason}", rule=verdict.rule)
    return verdict


# --- the loader ----------------------------------------------------------------
#
# The only part of this module that touches the filesystem. Reading at import would be
# untestable once imported, and would surface a bad file as a traceback rather than as
# EXIT_USAGE.


@dataclass(frozen=True)
class Loaded:
    """One resolved launch configuration: the tier, and the three tables."""

    tier: str
    deny: tuple[Rule, ...]
    ask: tuple[Rule, ...]
    allow: tuple[Rule, ...]


def _toml(path: Path) -> dict:
    """Parse one file, or `{}` when it is not there.

    Absent means the built-ins alone. Malformed is an error named after the file.
    """
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _read_toggles(path: Path) -> dict[str, bool]:
    """`[permissions]` out of `.un/config.toml`, over the defaults.

    Every key must name a policy that HAS a key, so naming a floor policy is an error
    rather than a no-op: an operator writing `env_files = false` and being ignored believes
    they turned something off.
    """
    toggles = dict(DEFAULT_TOGGLES)
    section = _toml(path).get("permissions", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [permissions] must be a table")
    for key, value in section.items():
        if key not in toggles:
            known = ", ".join(sorted(toggles))
            raise ValueError(f"{path}: unknown [permissions] key {key!r}; known: {known}")
        # `type` rather than `isinstance`: a string "false" is a mistake worth reporting
        # rather than a truthy value.
        if type(value) is not bool:
            raise ValueError(
                f"{path}: [permissions] {key} must be a boolean, not {type(value).__name__}")
        toggles[key] = value
    return toggles


def _read_operator_rules(path: Path) -> dict[str, tuple[Rule, ...]]:
    """The three arrays out of `.un/permissions.toml`, parsed and registry-checked.

    An ABSENT array means no additions of that decision, so the result is keyed on what the
    file carried and an absent `ask` does not zero the ask table. The registry check is for
    OPERATOR rules only: a built-in naming an absent tool means a disabled plugin, where an
    operator's typo is the case nothing else will ever report.
    """
    raw = _toml(path)
    out: dict[str, tuple[Rule, ...]] = {}
    for key, value in raw.items():
        if key not in _ARRAYS:
            known = ", ".join(_ARRAYS)
            raise ValueError(f"{path}: unknown key {key!r}; known keys: {known}")
        if not isinstance(value, list):
            raise ValueError(
                f"{path}: {key} must be a list of rule strings, not {type(value).__name__}")
        rules = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"{path}: {key} must be a list of rule strings; got {item!r}")
            try:
                rule = Rule.parse(item)
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            # The malformed case raised above, on the text the operator wrote, so no
            # expansion is ever attempted on something that is not a rule.
            if (widened := _widened(item, rule)) != item:
                rule = Rule.parse(widened)
            if rule.tool == RESERVED_TOOL and rule.spec not in REGISTRY["tool"]:
                known = ", ".join(sorted(REGISTRY["tool"]))
                raise ValueError(
                    f"{path}: {item!r} names no registered tool {rule.spec!r}; registered: {known}")
            rules.append(rule)
        out[key] = tuple(rules)
    return out


def _read_sandbox(path: Path) -> dict:
    """`[sandbox]` out of `.un/config.toml`, over the defaults.

    Shaped after `_read_toggles`: an unknown key is an error rather than a no-op, because an
    operator who misspells a confinement and is ignored believes they released it.
    """
    sandbox = dict(DEFAULT_SANDBOX)
    section = _toml(path).get("sandbox", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [sandbox] must be a table")
    for key, value in section.items():
        if key not in sandbox:
            known = ", ".join(sorted(sandbox))
            raise ValueError(f"{path}: unknown [sandbox] key {key!r}; known: {known}")
        # `type` rather than `isinstance`: a bool IS an int, so `mode = true` would pass.
        if key == "mode":
            if type(value) is not int or value not in _SANDBOX_MODES:
                raise ValueError(f"{path}: [sandbox] mode must be 1 or 2, not {value!r}")
        elif type(value) is not bool:
            raise ValueError(
                f"{path}: [sandbox] {key} must be a boolean, not {type(value).__name__}")
        sandbox[key] = value
    return sandbox


def _sandbox_table(sandbox: dict, cwd: Path) -> tuple[Rule, ...]:
    """Every enabled confinement as a DENY rule, and nothing when the sandbox is off.

    `confine_un_package` applies only where the package sits inside the project; elsewhere `confine_outside_project` reaches it.
    """
    if not sandbox["enabled"]:
        return ()
    inside = _PKG.resolve().is_relative_to(cwd.resolve())
    return tuple(
        Rule.parse(text, policy.why)
        for policy in SANDBOX_POLICIES
        if sandbox[policy.name] and (policy.name != "confine_un_package" or inside)
        for text in policy.rules
    )


def read_permissions(cwd: Path) -> Loaded:
    """Both files in, resolved tables out. Raises ValueError naming the file.

    Nothing is installed until `load` assigns what this produced, so a file that fails
    validation leaves the previous tables exactly as they were.
    """
    toggles = _read_toggles(cwd / CONFIG)
    sandbox = _read_sandbox(cwd / CONFIG)
    # Refused before any table is built; falling back to mode 1 would leave an operator believing they are contained.
    if sandbox["enabled"] and sandbox["mode"] == 2:
        raise ValueError(f"{cwd / CONFIG}: {_WHY_MODE_2}")
    operator = _read_operator_rules(cwd / PERMISSIONS)
    return Loaded(
        tier="dangerous" if toggles["dangerous_allow"] else "strict",
        # Operator rules are ADDED after the built-ins. The tables are walked deny-first,
        # so an operator `allow` cannot displace a floor deny however it is spelled. Sandbox
        # rules sit in the deny rung too, below the floor and above every operator allow.
        deny=(_table(DENY, toggles) + _sandbox_table(sandbox, cwd)
              + operator.get("deny", ())),
        ask=_table(ASK, toggles) + operator.get("ask", ()),
        allow=_table(ALLOW, toggles) + operator.get("allow", ()),
    )


@service("permissions:load")
def load_permissions(cwd: Path) -> str:
    """Read and install the launch configuration; return the tier for `cli`.

    It runs after `_preload`, so every tool a plugin registers is present for the registry
    check above. The three assignments happen together and last, after every raise.
    """
    global DENY_TABLE, ASK_TABLE, ALLOW_TABLE
    loaded = read_permissions(cwd)
    DENY_TABLE, ASK_TABLE, ALLOW_TABLE = loaded.deny, loaded.ask, loaded.allow
    return loaded.tier


@service("permissions:remember")
def remember(session: Session, name: str, args: dict) -> str:
    """Write this call's allow rule, reinstall the tables, and say what happened.

    Never raises: the operator already approved the call, and a failure to remember it must
    not also refuse it. `load_permissions` is the verify: it reads the file back through the
    loader against THIS process's registry, so a `Tool(NAME)` for a tool a `--plugin` module
    registered is found, and a rejected write is put back byte for byte.

    **The re-evaluation is the point.** The note says whether the rule took effect rather
    than reporting the write and stopping.
    """
    rule, why = allow_rule(session, name, args)
    if not rule:
        return f"not remembered: {why}"
    path = session.root / PERMISSIONS
    with _REMEMBERING:
        if not path.parent.is_dir():
            return f"{rule} was not written: no .un/ under {session.root}: not an un project"
        unread = object()
        original, kept = unread, False
        try:
            original = path.read_bytes() if path.exists() else None
            _add(path, rule)
            load_permissions(session.root)
            kept = True
        except Exception as exc:  # noqa: BLE001 - the write and the loader raise several types
            # Reported, never re-raised: the approved call still runs.
            return f"{rule} was not written: {path} rejected {rule!r}, so nothing was written: {exc}"
        finally:
            # Only what this call read can be put back; a directory in the file's place never was.
            if not kept and original is not unread:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(original)
        after = evaluate(session=session, name=name, args=args)
    if after.decision != ALLOW:
        return f"{rule} is in {path}, but {name} still asks: {after.reason}"
    return f"allowed {rule} in {path}; in effect now"


# --- approval ------------------------------------------------------------------
#
# Who answers when a rule says "ask". A service rather than an inlined input() call, so a chat round-trip or a policy engine can answer without the loop knowing.

@service("approval:cli")
def approve_cli(session: Session, question: str, *, always: bool = False) -> str:
    """Ask on the terminal. Anything but an explicit yes is a no, and silence is a no.

    `"yes"`, `"no"` or `"always"`.
    `always` results in an allow rule being written.

    Reads from `session.stream`, a declared field, falling back to stdin when it is
    None. Per-session rather than global: which adapter answers is a property of the
    run, so a workflow can hand one session an auto-approver without changing what
    any other session does.

    Fails closed when nobody is there, and the two fields are not the same question.
    `stream` is an interface that ATTACHED itself - a REPL - and answers however
    it likes, headless or not. `headless` describes the terminal the process was
    launched from. Only with neither is there no one to ask.

    Then stdin is not read AT ALL, which is the point rather than a detail: on a piped
    run the next line is the user's PROMPT, so consuming it would refuse the call and
    swallow the instruction, leaving the model to answer a question nobody asked.
    `approval:yes` stays the explicit opt-in for runs that have accepted the risk.
    """
    if session.stream is None and session.headless:
        # On stderr, beside the question it is refusing: a run blocked in CI has to be
        # diagnosable from its output alone.
        print(f"{question}\n  refused: no one is there to answer", file=sys.stderr)
        return "no"
    # On stderr, beside the refusal above: a question is not an answer, and
    # `un chat '...' > out.txt` must not collect it. Only the question moves - the read
    # below still takes `session.stream`, so a piped run answers from where it always did.
    #
    # The suffix moved INTO the question, because the caller is the one that knows
    # whether `a` is on offer and this adapter would otherwise have to guess.
    print(f"{question} ", end="", flush=True, file=sys.stderr)
    answer = (session.stream or sys.stdin).readline().strip().lower()
    if always and answer in {"a", "always"}:
        return "always"
    return "yes" if answer in {"y", "yes"} else "no"


@service("approval:yes")
def approve_all(session: Session, question: str, *, always: bool = False) -> str:
    """Approve everything. For non-interactive runs that have accepted the risk.

    Selected with `--approval yes`. The flag is in --help, where a model would find
    it, so `permissions` refuses a command that spawns another `un` and picks its own
    approver - the rule `bash(un:--a*)`: the choice stays with whoever runs `un`, not
    with what it runs.

    Never `"always"`, whatever the flag says. A headless run has no operator, and a rule
    in `.un/permissions.toml` outlives the run that wrote it - so this adapter approves
    the call in front of it and never widens what the NEXT one may do. Approving
    everything is a risk somebody accepted for one run; remembering it is not.
    """
    return "yes"


# --- the allow-rule writer -----------------------------------------------------
#
# What `always` runs when somebody answers an approval question with it, through `remember`. The file is an operator input ADR-0004 puts out of the agent's reach: this is un acting on a keystroke a person made, not a tool the model can call. An allow does not override an operator's ask, and does answer un's own assumed ask when it names the path.

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
    well as by `remember` and a growing single line is the shape that stops being
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


def set_array(path: Path, key: str, values: list[str]) -> None:
    """Rewrite `key`'s array in `path` and leave every other byte alone.

    The comment-preserving write `docs/adr/0015-config-toml-is-the-source-of-truth.md`
    requires. A live `key = [...]` is replaced in place; where there is none - both
    scaffolds ship their keys commented out as examples - a new one is inserted above the
    first table header, and the commented example survives as the documentation it was
    written to be.

    Public because `un.plugins.stock.plugin_config` writes `.un/config.toml` through it.

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
    rules = _current(path, "allow")
    if rule in rules:
        return False
    set_array(path, "allow", [*rules, rule])
    return True


# --- subagent scopes -----------------------------------------------------------
#
# Per-agent tool scopes: `Tool(x, y)` in an agent's `tools:` grants the tool and bounds what it may reach. Registered here, so the check holds whether or not `subagents` loads, and the grammar sits with the check, so what a scope MEANS is protected along with how it is enforced (ADR-0004). Path and Bash specs go through `Rule.parse` and its matchers, so a scope reads exactly as the same text reads in `.un/permissions.toml`. The check only narrows: it answers DENY or nothing, and the permission table still judges every call it lets through.

# Scoped by one named argument: the tool -> the argument judged.
SCOPE_NAMED = {"Skill": "name", "Workflow": "name", "SkillManage": "name", "Recall": "name",
               "Task": "subagent_type"}
# Scoped by path globs, judged against the argument the permission table judges.
SCOPE_PATHS = frozenset({"Read", "Write", "Edit", "Glob", "Grep", "AstGrep"})
# One spec per entry, because a Bash spec's own commas separate flags.
SCOPE_COMMAND = "Bash"
SCOPABLE = frozenset(SCOPE_NAMED) | SCOPE_PATHS | {SCOPE_COMMAND}

# A name, then optionally one parenthesised scope holding no parenthesis of its own.
_SCOPE_ENTRY = re.compile(r"([^()]+?)\s*(?:\(([^()]*)\))?")


def _split_scopes(text: str) -> list[str]:
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


def _scope_spec(tool: str, spec: str) -> str:
    """One spec as stored, or ValueError from `Rule.parse`. A path spec naming a directory covers what is inside it."""
    if tool in SCOPE_NAMED:
        return spec
    rule = Rule.parse(f"{tool}({spec})")
    # Sliced from the widened TEXT: `Rule.spec` drops a leading `!`, which would invert the scope.
    return _widened(rule.text, rule)[len(tool) + 1:-1] if tool in SCOPE_PATHS else spec


def parse_scopes(value: str | list) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    """A `tools:` value as (every tool named, scopes by tool). Raises ValueError naming the entry at fault.

    Rejoined before splitting, because yaml's flow list has already split `[A(x, y)]` at the comma.
    """
    items = [value] if isinstance(value, str) else value
    names: set[str] = set()
    bare: set[str] = set()
    scoped_by: dict[str, str] = {}
    scopes: dict[str, tuple[str, ...]] = {}
    for entry in _split_scopes(",".join(str(item) for item in items)):
        match = _SCOPE_ENTRY.fullmatch(entry)
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
        specs = [inner.strip()] if tool == SCOPE_COMMAND else _split_scopes(inner)
        if not specs or not specs[0]:
            raise ValueError(f"{entry!r} scopes {tool} to nothing")
        try:
            stored = tuple(_scope_spec(tool, spec) for spec in specs)
        except ValueError as exc:
            raise ValueError(f"{entry!r}: {exc}") from None
        scoped_by.setdefault(tool, entry)
        scopes[tool] = scopes.get(tool, ()) + stored
    return frozenset(names), scopes


def _within_scope(session: Session, name: str, specs: tuple[str, ...], args: dict) -> bool:
    """Whether one call falls inside its tool's scope. A Bash call needs EVERY fragment matched."""
    if name in SCOPE_NAMED:
        return str(args.get(SCOPE_NAMED[name]) or "") in specs
    if name == SCOPE_COMMAND:
        rules = [Rule.parse(f"{SCOPE_COMMAND}({spec})") for spec in specs]
        frags = parsed(args.get("command") or "")
        return bool(frags) and all(any(_fragment_matches(rule, frag) for rule in rules)
                                   for frag in frags)
    target = _target(name, args)
    return any(_path_matches(Rule.parse(f"{name}({spec})"), session, target)
               for spec in specs)


@hook("PreToolUse")
def check_scope(*, session: Session, name: str, args: dict) -> Verdict | None:
    """DENY a call to a scoped tool outside the calling agent's scope; no opinion otherwise."""
    if not session.agent:
        return None
    try:
        specs = use("agents", "scopes")(session.agent).get(name)
    except LookupError:
        # No agents:scopes service: subagents is not loaded, so no agent file has declared a scope. Expected whenever subagents is disabled; the permission table still judges the call.
        return None
    if specs is None or _within_scope(session, name, specs, args):
        return None
    return Verdict(DENY, f"{name} is scoped for {session.agent} to: {', '.join(specs)}")
