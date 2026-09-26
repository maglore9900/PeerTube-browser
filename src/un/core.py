"""The core: the plugin registry, the extension contract, and the agent loop.

Plugins import core and never the CLI, so anything shared between plugins lives here, including path constants whose writers are plugins. This module opens no file for writing.
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
                  "over, with the exit code it ended on. A session abandoned before its "
                  "first turn fires none, having fired no SessionStart either. A SUBAGENT "
                  "fires neither: it forks a Session and fires SessionStart into it, and "
                  "only a CLI verb ends a session. NOT TurnEnd: that fires once per turn, "
                  "so a conversation produces many of them and exactly one of these, last",
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


def load(extra: tuple[str, ...] = (), disabled: frozenset[str] = frozenset(),
         enabled: frozenset[str] = frozenset()) -> None:
    """Import every enabled plugin module, then every module named in `extra`.

    Stock first, so an aftermarket plugin claiming a stock key fails rather than displacing it.
    """
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

    if session.system_base is not None:
        session.system = session.system_base
        session.context_injected = False
        session.system_digest = None

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
    """The messages sent this turn: `session.messages`, or a `history:` filter's projection of them. Never mutates."""
    if not session.history:
        return session.messages
    return use("history", session.history)(session)


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
    _tokens_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def spend(self, tokens: int) -> None:
        """Add to the token total. Locked, since subagents on pool threads add concurrently."""
        with self._tokens_lock:
            self.tokens += tokens

    def __post_init__(self) -> None:
        """Default `root` to `cwd`."""
        if self.root is None:
            self.root = self.cwd

    def fork(self, suffix: str) -> "Session":
        """A fresh conversation with this session's settings and none of its history."""
        return replace(self, id=f"{self.id}-{suffix}", **_fresh())

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

    rat-tail: duplicates `permissions._globbed` to keep tool names out of core.
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

    `read(where, path, text, on)` registers and returns None, or returns why not; `on` is the `[section]` enabled set, None for a kind with no enable table; `label` is how `enabled` names the config in a refusal. Every REGISTRY entry a `read` adds is stamped `un_from_file = kind`, which `permissions._registered_tool` reads, so a kind cannot forget it. Never raises for a file, since it runs at import (ADR-0014).
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
    session.tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
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
    """Run `run` and fire `SessionEnd` with its exit code, if the session started."""
    # Any other exception ends as EXIT_FAILED.
    code = EXIT_FAILED
    try:
        code = run()
        return code
    except KeyboardInterrupt:
        code = EXIT_INTERRUPTED
        raise
    finally:
        if session.context_injected:
            fire("SessionEnd", session=session, code=code)


# --- command_parse -----------------------------------------------------------------------
#
# Taking a shell command apart. Decisions about the result live in `permissions.py`.

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


# A shell executing uninspected text. `permissions._floor` refuses these outright, so both are anchored at a command position to avoid matching `ssh` or `a.sh`.
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
            Fragment(head, short, long, operands, tuple(targets), assignments))
    return out


def _lex(piece: str) -> list[str]:
    """Split one pipeline piece into words, with redirect operators as their own words (`a>b` -> `a`, `>`, `b`).

    rat-tail: descriptor forms only (`N>`, `&>`, `N>&M`); heredocs and process substitution are left to `OPAQUE`.
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


def fragments(command: str) -> list[list[str]]:
    """Every argv-shaped command inside `command`: pipeline parts, subshells and `sh -c` payloads."""
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
