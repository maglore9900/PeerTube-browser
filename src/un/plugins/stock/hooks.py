"""File-authored hooks, declared in `.un/hooks/**/*.md` and enabled in `.un/config.toml`.

A hook fires on an EVENT rather than on a tool call, which puts it outside the layer
`permissions.py` inspects. So ADR-0017 applies as written: a `[hooks.<name>]` table
carrying `enable = true` turns one on, and the file being present only makes it KNOWN.

`subagents.py` is the model for the loader half and `tools.py` for the spawn half.
`discover` collects one distinct sentence per broken rule instead of raising, and runs at
IMPORT so a `SessionStart` hook exists before the first turn.

**un never imports a hook.** The registered callable spawns the declared script as a
subprocess with the event payload as JSON on stdin, and reads its stdout back.

Writes: nothing. The script it spawns writes whatever the operator gave it leave to.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from un import (ASK, DENY, EVENTS, EXIT_OK, REGISTRY, Session, Verdict,
                child_env, core, frontmatter, hook, service, use)

# From `un.core` rather than `un`, the route `tools.py` and `subagents.py` take: a
# re-export binds a second copy of the constant.
#
# `MAIN` moved to core in the selectors build: `rules.py` needs the same reserved word for
# the same `agent:` key, and two copies of it are two things to keep in step.
from un.core import CONFIG, MAIN, UN_DIR, location, project_root, session_file
from un.core import locked

HOOKS_DIR = UN_DIR / "hooks"

# What the frontmatter has to carry. `trigger` says WHEN and `run` says WHAT - without
# either there is nothing to register and nothing to spawn. `run` is a COMMAND LINE, not a
# bare path: see `_command`.
#
# `event` LEFT this tuple in the selectors build. A hook may now fire on a path alone, so
# the requirement became "at least one of event, path, every" - which a flat key set has
# nowhere to express and the `trigger` mapping does.
REQUIRED = ("name", "description", "trigger", "run")

# Keys a definition may declare. Anything else is a typo worth reporting rather than a
# value silently ignored. All four optional keys are shared verbatim with `rules.py` and
# read by `un.core`, so the two loaders cannot come to disagree about what one means.
# The frontmatter key naming a file this hook's stdout is APPENDED to. un does the writing,
# under a lock on that file, so two hooks sharing one target never overlap and the author
# writes no file handling of their own - see `_append_output`.
OUTPUT_FILE_KEY = "output_file"

KNOWN = frozenset(REQUIRED + ("message_type", "visibility", OUTPUT_FILE_KEY)
                  + core.SELECTOR_KEYS)

# The kinds of moment a trigger may name. EXACTLY one of them, which `_reason` enforces.
# All three of `core.TRIGGER_KEYS`, so a hook names a moment one way: outright, by what a
# call touches, or by a stride. `every` alone is a stride on `core.TURN_EVENT`, which is
# what `core.trigger` resolves it to.
#
# A HOOKS policy, not a fact about the file format, which is why it is not beside
# `core.TRIGGER_KEYS` and why `rules.py` does not read it. That loader tolerates a path
# beside an event and nulls the path, on the grounds `_reason`'s `message_type` branch
# states: a rule keeps applying its text, where a hook would be running a script somewhere
# its author did not choose.
TRIGGER_KINDS = core.TRIGGER_KEYS

# The frontmatter key deciding whether a fire is ANNOUNCED, and the default it takes when
# the file leaves it out. Not shared with `rules.py`: a rule contributes text an operator
# reads, where only a hook has a name of its own to print.
VISIBILITY = "visibility"
VISIBLE_DEFAULT = True

# The one key a `[hooks.<name>]` table may carry. The name is the heading, as it is for
# `[agents.<name>]` and `[providers.<name>]`, so there is no `name` field here either.
ENABLE = "enable"

# `.un/config.toml`, spelled as every refusal key here is: project-relative and
# posix-separated. The key a config refusal is filed under and its text have to agree,
# because `un hooks` prints them side by side.
CONFIG_NAME = CONFIG.as_posix()

# rat-tail: the same 120s `shell`, `git_ro` and `tools` use, as a literal. A plugin
# importing another to share a constant couples two independently replaceable things.
DEFAULT_TIMEOUT = 120

# The events whose returns are COLLECTED and joined into the prompt, and so fenced - see
# `_fence`. The chain events are deliberately absent: there the stdout REPLACES a value, so
# a fence would be injected rather than delimiting anything. A set rather than a test
# against one name, or an implementation keyed on `SessionStart` leaves `TurnStart`
# unfenced.
#
# `ToolResults` joined them in the selectors build - the one new collect event. A REROUTED
# hook is fenced too, whatever event it landed on, but that is a property of the hook
# rather than of the event, so `_script_hook` decides it rather than this set.
FENCED = frozenset({"SessionStart", "TurnStart", "ToolResults"})

# The event carrying what the operator typed. Named for `GATE_EVENT`'s reason: a hook
# delivering onto it AMENDS the prompt rather than replacing it, and that rule reads as a
# rule rather than as a string comparison.
#
# The LANDING event decides it, never where the hook came from. `PostToolUse` is the other
# chain event and keeps REPLACE, because rewriting a tool result is what a hook there is
# FOR - where eating the operator's message is nothing any hook meant to do.
PROMPT_EVENT = "UserPromptSubmit"

# The one event whose return is a Verdict rather than text, and so the one where an exit
# code means more than success or failure. Claude Code's contract, matched: exit 2 blocks
# and stderr is the reason the model reads.
GATE_EVENT = "PreToolUse"
DENY_EXIT = 2
# un's own, with no Claude Code equivalent. Without a spelling for ASK a drop-in hook could
# deny but never ask, throwing away the middle ground the permission table is built on.
ASK_EXIT = 3

# The event kind a fire is recorded under, one row per spawn. It answers the two questions
# absence cannot: did this hook run, and did it work.
FIRE_KIND = "hook"

# Every valid hook found, enabled or not, keyed by its frontmatter `name`. Rebuilt whole
# on every scan - see `discover`.
HOOKS: dict[str, "Hook"] = {}

# Files that named themselves a hook and were turned away, and why. Import time has no
# channel to report on, so `un hooks` and `/reload` render this.
REFUSED: dict[str, str] = {}


def _append_output(session: Session | None, entry: Hook, text: str) -> None:
    """Append a hook's stdout to its `output_file`, holding that file for the write.

    The LOCK is why this is un's job rather than the script's. Several hooks can now fire at
    once - a turn's tool calls resolve together - so two writing one file would interleave
    into lines that parse as nothing, or clobber each other outright. Holding the target
    makes them queue on that file and on nothing else: a hook writing somewhere else is not
    delayed for a moment.

    APPEND, never replace. The point of a record is that every writer's line survives; a
    whole-file write keeps only whoever went last, which is the same loss wearing a tidy
    name. Nothing is written for a hook that printed nothing, so a quiet fire leaves no
    blank line behind.

    Reported and survived. A file that cannot be written is not a reason to end a session,
    and this is the same trade `transcript._emit` makes for the same reason.
    """
    if not entry.output_file or not text:
        return
    try:
        with locked(entry.output_file) as target:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(text if text.endswith("\n") else text + "\n")
    except OSError as exc:
        if session is not None:
            session.report(entry.name, f"could not write {entry.output_file}: {exc}")


def _output_file(data: dict, folder: Path, here: Path) -> str | None:
    """Where this hook's stdout is appended, resolved the way `run:` resolves its script.

    Absent is the default and means no file at all, which is what a hook that only speaks to
    the conversation wants. `message_type` decides the OTHER destination, and the two are
    independent: a hook may do both, either, or neither.
    """
    declared = str(data.get(OUTPUT_FILE_KEY) or "").strip()
    return str(_target(folder, here, declared)) if declared else None


@dataclass(frozen=True)
class Hook:
    """One `.un/hooks/**/*.md`, parsed. `enabled` is the config's answer, not the file's."""

    name: str
    description: str
    # The core events this hook is REGISTERED on, which are not always the ones it
    # declared: `trigger.event` says when the author wants it, `message_type` says which
    # container, and `core.ROUTES` turns each pair into the event that can deliver it.
    # `un hooks` prints both, because a reader who wrote `TurnStart` and sees
    # `UserPromptSubmit` otherwise has no way to connect the two.
    #
    # ALIGNED one-to-one with `trigger.event`, so rendering can pair them. The collapse of
    # two declared moments landing on ONE event belongs to registration, not here - see
    # `discover`.
    events: tuple[str, ...]
    script: Path
    path: Path
    enabled: bool
    # When it fires and who it is for, read by `un.core` and shared verbatim with
    # `rules.py`. `trigger.event` is the DECLARED moment; `selectors` fields are None for
    # "no opinion", which is what omitting the key asks for.
    trigger: core.Trigger = core.Trigger()
    selectors: core.Selectors = core.Selectors()
    # Which message carries this hook's stdout, or None when the file declared none - which
    # is the DEFAULT, and is what makes reaching the model an opt-in. See `_delivery`.
    message_type: str | None = None
    # The words after the script in `run:`, passed as argv. Empty for a `run:` that names a
    # path and nothing else, which is every hook that needs no parameter.
    args: tuple[str, ...] = ()
    # Whether a fire is announced on the operator's surface. False silences the ROUTINE
    # lines and nothing else: a failure still reports, and a verdict still reaches the
    # operator under the call it decided rather than as a hook line of its own.
    visible: bool = VISIBLE_DEFAULT
    # Where this hook's stdout is APPENDED, from its `output_file:` key, or None for the
    # hooks that want no file - which is most of them. un opens it, locks it and writes it;
    # the script only prints. A script that redirects to a file ITSELF bypasses all of that
    # and is on its own, which is the documented boundary.
    output_file: str | None = None

    def rerouted(self, landed: str) -> bool:
        """Whether routing moved this hook onto `landed` from a moment it declared.

        Takes the landing event because a hook may hold several, and the caller is pairing
        them off one at a time. A landing event the file never named is one routing produced
        - and routing only happens when `message_type` is declared, which `_reason` then
        requires every declared moment to have a `core.ROUTES` cell for.

        RENDERING only, read by `hooks_` so `un hooks` can print `declared -> registered`.
        A fire does not consult it: what a delivering hook returns is decided by the event it
        LANDED on, never by where it came from, so that two hooks arriving at one event
        behave alike. See `_script_hook`.
        """
        return landed not in self.trigger.event


def _target(base: Path, root: Path, path: str) -> Path | None:
    """`path` resolved against `base` to a FILE inside `root`, or None.

    `tools._target`, duplicated rather than imported across plugins. An ABSOLUTE `run`
    needs no branch: pathlib lets it replace `base` outright, so it still faces the
    containment test - which is why a string check on `..` would be the wrong guard.

    Resolved against the hooks TREE rather than the definition file's own directory, so
    `run` reads the same wherever the file is nested. CONTAINED by the project root rather
    than by that tree, so a hook may run a script filed with the thing it guards.

    A LEADING `@location` is substituted first and comes back absolute, so it faces the
    same containment test - a token is a spelling for paths inside the project, never a way
    out. `location` RAISES for a token outside its six, which `_reason` turns into a
    finding.
    """
    if path.startswith("@"):
        path = str(location(root, path))
    candidate = (base / path).resolve()
    if not candidate.is_relative_to(root) or candidate.is_dir():
        return None
    return candidate


def _command(run: str) -> tuple[str, tuple[str, ...]]:
    """`run:` split into the script and the words handed to it as argv.

    A COMMAND LINE rather than a bare path, so one guard is parameterised per hook -
    `auditor_bash_guard.sh check-prose` and the same script with `lint-bundle` are two
    hooks over one file. Claude Code spells it on one line and these are translated from
    that.

    `shlex.split` rather than `str.split`, so a path with a space is reachable by quoting.
    Nothing runs THROUGH a shell - `_script_hook` spawns argv with `shell=False` - so this
    borrows shell QUOTING and none of its evaluation.
    """
    words = shlex.split(run)
    if not words:
        # Reachable only from a `run:` that is entirely quotes, which the REQUIRED check
        # reads as present.
        raise ValueError("run names no script")
    return words[0], tuple(words[1:])


# YAML reserves `@` as an indicator, so an unquoted `run: @project_root/...` fails to scan
# and never arrives as a value. The parser says "ScannerError", naming neither the field
# nor the character that has to change, so this reads the raw text and says both.
_UNQUOTED_AT = re.compile(r"^\s*(\w+)\s*:\s*@", re.MULTILINE)


def _unquoted(text: str) -> str | None:
    """A usable sentence for the one scan failure a location token causes, or None.

    Consulted ONLY when the parse already failed, so a `@` living anywhere else in a file
    that scans cannot be mistaken for it.
    """
    found = _UNQUOTED_AT.search(text)
    if not found:
        return None
    key = found.group(1)
    return (f"{key} starts with @, which YAML reads as a reserved indicator rather than "
            f'text; quote it - {key}: "@project_root/..."')


def _registered(when: core.Trigger, delivery: str | None) -> tuple[str, ...]:
    """The core events a hook actually registers on, one per moment it declared.

    Routing exists to find a CONTAINER for text, so it applies only where a container is
    actually in question - which is exactly when the file asked for one. A hook that
    declared no `message_type` delivers nothing to the model, so there is nothing to place
    and it registers on the moments it named: `event: PostToolUse` means that event, and a
    trigger whose event was IMPLIED by a path means `PostToolUse` too.

    `core.route` rather than a `ROUTES.get` with a fallback: where `delivery` is declared,
    `_reason` has already refused every moment the table has no cell for, so a pair arriving
    here unroutable is a bug in un rather than an operator's typo - and guessing a container
    for text someone asked to place is the one thing worse than raising on it.

    Aligned with `when.event` rather than deduped, so `hooks_` can pair each declared
    moment with where it landed. Two moments CAN land on one event - `SessionStart` and
    `TurnStart` asking for `user` both reach `UserPromptSubmit` - and collapsing that is
    `discover`'s job, because binding the same callable twice is a registration fault
    rather than a rendering one.
    """
    if delivery is None:
        return when.event
    return tuple(core.route(moment, delivery) for moment in when.event)


def _fence(name: str, body: str) -> str:
    """Delimit a hook's output from harness instruction, and say which hook wrote it.

    Collected returns are joined into one system prompt with no delimiter, so without this
    the text reads as something the harness said. The NAME is what this adds over
    `rules._fence`: a hook's text is generated at runtime from data un has never seen, so a
    reader finding unexpected instructions needs to be told which file produced them.
    """
    return f'<hook name="{name}">\n{body}\n</hook>'


def enabled(root: Path) -> frozenset[str]:
    """The names under `[hooks.<name>]` whose `enable` is true. Empty when there is none.

    `core.enabled` does the reading, shared with `subagents`, `rules` and `skills` so four
    copies of one validator cannot drift apart. Absent is the pre-feature behaviour rather
    than an error, while malformed IS one, named after the file.

    The project-relative file spelling is this caller's and is passed in; `subagents` names
    it absolutely.
    """
    return core.enabled(root, "hooks", "hook", CONFIG_NAME)


def _reason(data: dict, error: str | None, folder: Path, root: Path) -> str | None:
    """Why this file is not a hook, or None. One distinct sentence per rule.

    Distinct because a reader told only "refused" has to guess which rule they broke.

    No name-shape check, deliberately, and it is where this loader departs from
    `subagents._reason`. `core.SLUG` guards a string that becomes a path segment; an
    agent's name becomes its transcript filename, where a hook's name lands only in a
    `[hooks.<name>]` table key and a `REGISTRY["hook"]` key.
    """
    if error:
        # The parser's own reason, passed through rather than re-worded.
        return error
    # BEFORE the REQUIRED check, and the order matters during a migration. A definition in
    # the retired spelling breaks two rules at once - it carries `targets:` AND declares no
    # `trigger` - and "no trigger in its frontmatter" is true, generic, and does not tell
    # the author which key made their file stale. Naming the retired key does.
    #
    # `key=str` for `rules._load`'s reason: YAML 1.1 resolves a bare `on:` to the boolean
    # True, and sorting a bool against a str raises - at import, from a dropped-in file.
    extra = sorted(set(data) - KNOWN, key=str)
    if extra:
        # ALL of them, not just the first. A definition in the retired spelling carries two
        # dead keys - `targets:` and a flat `event:` - and naming one sends the author back
        # for a second refusal after they fix it.
        label = "unknown keys" if len(extra) > 1 else "unknown key"
        listed = ", ".join(repr(str(key)) for key in extra)
        return f"{label} {listed}; known keys: {', '.join(sorted(KNOWN))}"

    for key in REQUIRED:
        # `or ""` then `.strip()`: an absent key and a whitespace one are different
        # inputs that mean the same thing in a hand-written definition. An empty `trigger`
        # mapping reads as falsy here too, which is one of the six refusals.
        if not str(data.get(key) or "").strip():
            return f"no {key} in its frontmatter"

    name = str(data["name"]).strip()
    if name in HOOKS:
        # Asymmetric on purpose: the first definition keeps the name, and the reason
        # names the file that already holds it.
        return f"a hook named {name!r} is already defined by {HOOKS[name].path.name}"

    # The three shared readers, in the order an author would fix them. Each returns its
    # own sentence, so a hook is turned away naming the key that has to change.
    when, trigger_error = core.trigger(data)
    if trigger_error:
        return trigger_error
    for moment in when.event:
        # BEFORE `core.hook` sees it, which raises on an unknown event - and this runs at
        # import, so that raise is a typo in a dropped-in file taking the session down,
        # which ADR-0014 exists to prevent. Names what un HAS, because the realistic way to
        # land here is an event name from another harness.
        #
        # PER MOMENT, and the whole file is refused if any one of them is unknown. Naming
        # ONE moment rather than the declared list is the operator-facing half: a reader
        # handed back everything they wrote has to work out which name un objected to.
        # Registering the valid moments and dropping the rest would be worse still - the
        # hook would half-work, with nothing saying why the others never fire.
        if moment not in EVENTS:
            return f"unknown event {moment!r}; known: {', '.join(EVENTS)}"

    # A trigger names ONE kind. Read from the RAW mapping rather than from `when`:
    # `core.trigger` implies an event for a path that named none, so by the time there is a
    # `Trigger` in hand, "the author wrote both" and "un filled one in" are the same value.
    #
    # COUNTED rather than paired, so a kind carrying several values stays one kind - and
    # `len(kinds) > 1` rather than `!= 1`, because a trigger naming NO kind is already
    # refused by the `REQUIRED` loop above, which reads an empty mapping as a blank value.
    # An author who wrote nothing needs to be told that, not told to choose between keys
    # they never wrote.
    kinds = [key for key in TRIGGER_KINDS if data["trigger"].get(key) is not None]
    if len(kinds) > 1:
        # Names the keys FOUND and no event, on purpose: the rule is about how many kinds
        # were named, and quoting the moment would describe the moment instead.
        return (f"a trigger names one of {', '.join(TRIGGER_KINDS)}, and this one names "
                f"{' and '.join(kinds)}; drop all but one")

    _, selector_error = core.selectors(data)
    if selector_error:
        return selector_error

    delivery, delivery_error = _delivery(data)
    if delivery_error:
        # A hook REFUSES where a rule falls back and says so: a rule keeps applying its
        # text, where a hook would be running a script somewhere its author did not choose.
        return delivery_error
    if delivery is not None:
        # `PreToolUse` returns a Verdict, `Turn` and `ToolEnd` ignore returns entirely -
        # none of the three carries a message at all, so asking for one is a mistake worth
        # a sentence rather than a key silently doing nothing.
        #
        # EVERY declared moment has to deliver, not one of them. A file naming a moment
        # that routes beside one that cannot would otherwise be accepted on the strength of
        # the first, and register a hook on an event that can never deliver what it asked
        # for. The sentence names the offending moment, as the event check above does.
        for moment in when.event:
            if (moment, delivery) not in core.ROUTES:
                return (f"message_type has no meaning on {moment}, which carries no "
                        "message; drop the key or name an event that delivers text")

    _, visibility_error = _visible(data)
    if visibility_error:
        return visibility_error

    try:
        # Both raises are ValueError and both want the exception's own words: either
        # sentence beats "run must name a file inside the project", which sends the author
        # to check a path that is correct apart from its prefix.
        first, _ = _command(str(data["run"]).strip())
        script = _target(folder, root, first)
    except ValueError as exc:
        return str(exc)
    if script is None or not script.is_file():
        # `first` rather than the whole `run:` line: quoting the arguments back invites
        # the author to look for the mistake in them.
        return f"run must name a file inside the project, and {first!r} does not"
    if not os.access(script, os.X_OK):
        # un execs the script directly rather than choosing an interpreter, so a hook may
        # be anything with a shebang - and the executable bit is what makes that possible.
        return f"{first!r} is not executable; chmod +x it"
    return None


def _delivery(data: dict) -> tuple[str | None, str | None]:
    """Which message carries this hook's stdout, None for none, and why a value was unreadable.

    `core.message_type` answers for a RULE, where an absent key HAS to mean `system`: a rule
    IS text, and text with no container is a rule that does nothing. A hook is a script, and
    most of them - guards, reporters, status pingers - have nothing to say to the model at
    all. So absence here means the stdout is DROPPED, and reaching the model is what the key
    opts into.

    That asymmetry is the whole reason this WRAPS rather than replaces. Reading a declared
    value, and the sentence naming a typo, stay shared with `rules.py`; only the meaning of
    the key's ABSENCE differs, and it differs because only the consequence does. A rule that
    stopped applying would be an operator's writing silently ignored, where a hook that
    stops speaking is the common case finally spelled correctly.

    A typo is still an error rather than an absence - `_reason` refuses on it. Folding an
    unreadable value into "declared nothing" would turn `message_type: sistem` into a silent
    demotion, which is the failure this key exists to remove rather than one to add.
    """
    if "message_type" not in data:
        return None, None
    return core.message_type(data)


def _visible(data: dict) -> tuple[bool, str | None]:
    """Whether this hook announces its fires, and why a declared value was unreadable.

    `core.message_type`'s posture for a key only hooks have: a typo is named and survived
    rather than raised, and the fallback is the LOUD direction. A file whose `visibility`
    cannot be read keeps announcing, because a silent hook an operator did not ask for is
    a guard they cannot tell is running.

    A bare `true`/`false` only. YAML resolves those to a bool, so anything else here - a
    quoted `"false"` included - is a value the author meant as a switch and un would read
    as on.
    """
    if VISIBILITY not in data:
        return VISIBLE_DEFAULT, None
    if isinstance(raw := data[VISIBILITY], bool):
        return raw, None
    return VISIBLE_DEFAULT, (
        f"{VISIBILITY} must be true or false, and {raw!r} is neither")


def _payload(event: str, kw: dict) -> dict:
    """What the script reads on stdin.

    Every JSON-safe kwarg survives; `session` and `reply` are dropped BY TYPE, where a
    per-event mapping table would fall behind the first time `EVENTS` grows a key.

    `cwd` and `agent` are composed rather than copied, because a script cannot get either
    from any kwarg - `session` is exactly what the type filter removes. `agent` carries
    `Session.agent` VERBATIM, so the main conversation reads ""; substituting `MAIN` here
    would tell a script the main agent is a subagent called `main`.

    `session_id` and `transcript_path` are composed for the same reason, and are what lets
    an external tracker correlate what it is told with what un wrote. Every composed key
    answers "" rather than going missing when there is no session, so a script may
    subscript any of them on any event.
    """
    session = kw.get("session")
    payload = {
        "event": event,
        "agent": session.agent if session is not None else "",
        "cwd": str(session.cwd) if session is not None else "",
        # Composed for `agent`'s reason: a script selected BY provider or model has no other
        # route to which one selected it, `session` being exactly what the type filter drops.
        "provider": session.provider if session is not None else "",
        "model": session.model if session is not None else "",
        "session_id": session.id if session is not None else "",
        # `session.root`, NOT `session.cwd`, though `session_file`'s parameter is named
        # `cwd`: `transcript.py` writes under the root at every one of its sites, and the
        # two differ for any session started in a subdirectory.
        "transcript_path": (str(session_file(session.root, session.id))
                            if session is not None else ""),
    }
    payload.update({
        key: value for key, value in kw.items()
        if value is None or isinstance(value, (str, int, float, bool, list, dict))
    })
    return payload


def _report(session: Session | None, name: str, channel: str, text: str) -> None:
    """Say something about a hook to the OPERATOR, wherever they are.

    `subagents.task`'s split: the session's sink when there is one, stderr when there is
    not, because a headless run has nobody watching the sink.

    rat-tail: `Session.report` is this plus a record row, deliberately NOT merged. `report`
    hardcodes the `error` channel because a report IS a failure; this takes the channel,
    because a hook's remark on a clean exit must not render in red. Merge them if that
    distinction stops mattering.
    """
    if session is not None:
        session.say(channel, f"{name}: {text}")
        if session.emit is not None:
            return
    print(f"un: hooks: {name}: {text}", file=sys.stderr)


def _say_fired(session: Session | None, entry: Hook) -> None:
    """Name the hook on the operator's surface, BEFORE the script is spawned.

    Ahead of the spawn, so a script that hangs is visible for the `DEFAULT_TIMEOUT` seconds
    it hangs. `say` rather than `_report`, because a fire is not a failure and `_report`'s
    stderr half would put one line per tool call into a headless run.

    Silent for a hook declaring `visibility: false`, which is the whole of what that key
    buys: a guard firing on every tool call is noise an operator can switch off without
    switching the guard off.
    """
    if session is not None and entry.visible:
        session.say("tool", f"hook: {entry.name}")


def _record_fired(session: Session | None, entry: Hook, landed: str, outcome: str,
                  **fields) -> None:
    """Append one row saying this hook fired and what it did. Never raises.

    `Session.report`'s guard: reached through `use` so `--disable-plugin session_transcripts`
    removes it cleanly, and a record that cannot be written must not fail a hook that ran
    correctly - ADR-0023. The broad catch is for the lookup and for a bug in a replacement
    writer.

    rat-tail: one row per fire, uncapped, and a `PreToolUse` hook writes one per tool call.
    Bounded by the hook being ENABLED; sample or prune if a project notices the size.
    """
    if session is None:
        return
    try:
        use("session", "event")(session, FIRE_KIND, name=entry.name, event=landed,
                                outcome=outcome, **fields)
    except Exception:  # noqa: BLE001
        pass


def _debug_stdout(session: Session | None, out: str) -> str:
    """A failed hook's stdout, carried only under `--log-debug`.

    Dropped otherwise: a failure's diagnostic is its stderr and its exit status, and a
    script that printed a megabyte before falling over should not put that in an operator's
    terminal on every fire.
    """
    if out and session is not None and session.log_debug:
        return f"\nstdout: {out}"
    return ""


def _touched(kw: dict) -> tuple:
    """The tool arguments in hand on this event, whatever shape it delivers them in.

    `PostToolUse` folds one call and carries `args`; `ToolResults` covers a whole batch and
    carries `calls`. Everything else has neither, which is why a hook with no `path` never
    consults this.
    """
    if isinstance(kw.get("calls"), list):
        return tuple(c.get("input") for c in kw["calls"] if isinstance(c, dict))
    if "args" in kw:
        return (kw["args"],)
    return ()


def _due(entry: Hook, session: Session, kw: dict) -> bool:
    """Whether this hook applies to this conversation, this turn, and this call.

    The same three questions `rules._applies` asks, in the same order and through the same
    core functions - which is the whole of what "the two mirror each other" means. What
    differs is the consequence: a rule that does not apply contributes no text, where a hook
    that does not apply spawns no process.

    A hook fires per CALL rather than once per turn, deliberately and unlike a rule: a rule
    is text an operator wants read once, where a hook is an ACTION, and suppressing the
    second of two matching calls would hide work from a guard.
    """
    if not core.selects(entry.selectors, session):
        return False
    if session.turn_index % entry.trigger.every:
        return False
    if not entry.trigger.path:
        # Falsiness, not `is None`: a trigger that declared no path now holds an empty
        # tuple. Left as an identity test this branch would be skipped, `any()` would fold
        # over nothing, and every hook without a path would silently stop firing.
        return True
    return any(core.triggered(entry.trigger, args) for args in _touched(kw))


def _script_hook(entry: Hook, landed: str):
    """A registered callable that spawns `entry.script`. The only thing un runs for a hook.

    ONE callable per landing event, never one shared across several. `core._register`
    stamps `un_meta` onto the function object, so a single callable bound to three events
    would report only the last one to `core._hooks` and fire on that moment alone - with
    `HOOKS`, `discover`'s return and `un hooks` all still reading correctly. `landed` is
    also what the closure needs: the payload, the fencing rule, the chain rule and the gate
    rule are all properties of the event this registration actually sits on.
    """

    def run(**kw):
        session = kw.get("session")
        if session is not None and not _due(entry, session, kw):
            # Not this conversation, not this turn, or not a call this hook watches. None is
            # already what every event reads as "this hook contributed nothing", so
            # confining one needs no new return contract. Ahead of the spawn, so a hook that
            # does not apply costs no process - which is the observable that separates
            # filtering from spawning and discarding.
            return None
        # BELOW the confinement guard: above it the record would claim a hook ran on every
        # conversation it was kept out of, which is worse than no record.
        _say_fired(session, entry)
        try:
            # `shell=False` with argv as a list, so nothing is parsed by a shell.
            # `child_env()` is ADR-0007's constructive allowlist.
            done = subprocess.run(
                [str(entry.script), *entry.args],
                input=json.dumps(_payload(landed, kw), default=str),
                cwd=session.cwd if session is not None else None,
                env=child_env(),
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            # Bounded rather than waited on: a script that never returns is a session
            # that never returns, on every fire of its event. `exc.stdout` is what was
            # captured before the bound, and a hung script leaves no exit code and no
            # stderr - so it is the one failure whose only evidence is what it printed.
            detail = (f"timed out after {DEFAULT_TIMEOUT}s"
                      + _debug_stdout(session, (exc.stdout or "").strip()))
            _report(session, entry.name, "error", detail)
            _record_fired(session, entry, landed, "timeout", detail=detail)
            return None
        except OSError as exc:
            # The spawn itself failed - the executable bit lost since the scan, the
            # shebang's interpreter gone. Its OWN outcome, because an operator told the
            # hook `failed` would hunt a bug in a script that never executed a line.
            detail = f"could not run: {exc.strerror}"
            _report(session, entry.name, "error", detail)
            _record_fired(session, entry, landed, "spawn-failed", detail=detail)
            return None

        err = done.stderr.strip()
        # BEFORE the exit-code branches, and outside every one of them: a hook that wrote
        # output and then failed still wrote it, and a file that only records clean runs is a
        # record with the interesting half missing.
        _append_output(session, entry, done.stdout)
        if landed == GATE_EVENT:
            # The two codes that mean something, and ONLY here. `decide` is
            # most-restrictive-wins, so either can tighten what the table decided and
            # neither can loosen it. On any other event they are ordinary failures.
            if done.returncode == DENY_EXIT:
                # `err or ...`: an empty reason reaches the model as "Blocked: Read x - ",
                # which tells it nothing. A local, so the row and the `Verdict` carry the
                # same string by construction.
                reason = err or f"denied by the {entry.name} hook"
                _record_fired(session, entry, landed, "deny", reason=reason)
                return Verdict(DENY, reason)
            if done.returncode == ASK_EXIT:
                reason = err or f"the {entry.name} hook asked about this"
                # Recorded as `ask` whatever the person answers next: the row says what
                # the HOOK did, and the gate's final outcome would lose that on a yes.
                _record_fired(session, entry, landed, "ask", reason=reason)
                return Verdict(ASK, reason)
        # Reached by exit 2 and 3 on every OTHER event, where they are not verdicts at all.
        if done.returncode != 0:
            # Fails OPEN, the accepted trade: failing closed would take a session down
            # over a typo in a dropped-in file - ADR-0014. Reported, because an operator
            # whose DENY hook broke has to hear that the call went through.
            detail = f"exit status {done.returncode}"
            if err:
                detail = f"{detail}: {err}"
            detail += _debug_stdout(session, done.stdout.strip())
            _report(session, entry.name, "error", detail)
            _record_fired(session, entry, landed, "failed", detail=detail)
            return None
        if err:
            # Claude Code's rule, kept: stderr on a CLEAN exit is for the operator, not
            # the model. `tool` rather than `error`, because a remark rendered in red
            # trains an operator to ignore the channel carrying real failures.
            #
            # Suppressed by `visibility: false` along with the fire line, both being
            # routine. `_report` prints `<name>: <text>`, so leaving it would put back the
            # name the key was set to remove. The row keeps the remark either way.
            if entry.visible:
                _report(session, entry.name, "tool", err)
            # `outcome` stays `ok` and the text rides its own field, so a reader tells a
            # silent success from a talkative one without the two reading as different
            # outcomes.
            _record_fired(session, entry, landed, "ok", remark=err)
        else:
            _record_fired(session, entry, landed, "ok")

        text = done.stdout.strip()
        if not text:
            # None, never "". A collect event would otherwise put an empty fence in the
            # prompt, and a chain event is worse: `core.chain` folds with `or value`, so
            # None passes the value through where "" erases it.
            return None
        if landed == GATE_EVENT:
            # Nothing to return: this event collects Verdicts. 51c gives that stdout a
            # meaning.
            return None
        if entry.message_type is None:
            # THE DEFAULT. A hook reaches the model only by declaring which message carries
            # it. Most hooks are guards and reporters with nothing to say, and a stray line
            # from one of those used to land in the system prompt on every session start -
            # silently, and as a prompt-injection surface rather than a cosmetic bug.
            #
            # `None` is already every event's reading of "this hook contributed nothing", so
            # confining one needs no new return contract - the same argument the `_due` guard
            # above makes.
            #
            # BELOW the stderr remark and the fire record: a hook that says nothing to the
            # model still says things to the OPERATOR, and still owes a row.
            return None
        if landed == PROMPT_EVENT:
            # AMENDS, never replaces. `core.chain` folds with `value = h(...) or value`, so
            # returning text bare here would eat what the operator typed - which no hook
            # asked for, whether it named this event or was routed onto it from `TurnStart`.
            # The LANDING event decides, so both arrive the same way.
            #
            # Fenced, because a reader finding unexpected instructions inside their own
            # message has to be told which file wrote them.
            return f"{kw['value']}\n\n{_fence(entry.name, text)}"
        # `PostToolUse` is the other chain event and falls through to the bare return, which
        # REPLACES the tool result. Deliberate: rewriting a result before the model reads it
        # is what a hook there is for, and a fence around a redacted one would announce it as
        # hook text rather than as what the tool returned.
        return _fence(entry.name, text) if landed in FENCED else text

    # `core.hook` names a registration by module and qualname, and every wrapper this
    # factory builds shares both - so without this the SECOND hook raises out of
    # `core._register` at import, which ADR-0014 exists to prevent.
    run.__qualname__ = entry.name
    # Read back by `discover` to drop what a previous scan registered. On the registry
    # entry rather than in a module-level set, so the two cannot disagree.
    run.un_from_file = True
    return run


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Read every `.un/hooks/**/*.md`. Returns (enabled hook names, refused).

    Takes a PATH, not a `Session`: this runs at module import so a `SessionStart` hook is
    registered before the first turn, and no `Session` exists then. RECURSIVE, because a
    hook is filed under its frontmatter `name` rather than its file stem.

    Re-runnable, and it REBUILDS rather than skipping what it has, so an edited definition
    takes effect on `/reload`. What makes that safe is `un_from_file`: this drops exactly
    the registrations it made and nothing a Python plugin owns.

    Only an ENABLED hook is registered. A disabled one stays in `HOOKS` for `un hooks` and
    never reaches `REGISTRY`, which is stronger than a check at fire time.
    """
    here = Path(root or project_root() or Path.cwd())
    folder = here / HOOKS_DIR
    HOOKS.clear()
    REFUSED.clear()
    for key in [k for k, fn in REGISTRY["hook"].items()
                if getattr(fn, "un_from_file", False)]:
        del REGISTRY["hook"][key]
    if not folder.is_dir():
        # Not a refusal: a project that has never written a hook is the ordinary state.
        return [], dict(REFUSED)

    try:
        on = enabled(here)
    except ValueError as exc:
        # A broken `[hooks]` table is one finding, not a session that will not start -
        # ADR-0014. Every hook is then off, the safe reading of a file nobody can parse.
        # Filed under the CONFIG's own name, because that is the file to open.
        REFUSED[CONFIG_NAME] = str(exc)
        on = frozenset()

    for path in sorted(folder.rglob("*.md")):
        # Relative to the tree, so two files with one stem in different directories stay
        # distinguishable. The KEY is the path, because the hook's name is not known until
        # the frontmatter parses.
        key = path.relative_to(folder).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            # `frontmatter.parse` never raises; the READ before it does. This runs at
            # import, so an unreadable drop-in file would take the process down - the
            # raise ADR-0014 exists to prevent.
            REFUSED[key] = f"could not be read: {exc.strerror}"
            continue
        data, _, error = frontmatter.parse(text)
        if error:
            # Replaced rather than appended: for this one failure the parser's own words
            # are the part that does not help.
            error = _unquoted(text) or error
        if refusal := _reason(data, error, folder, here):
            REFUSED[key] = refusal
            continue

        name = str(data["name"]).strip()
        # Neither raise is reachable: `_reason` has already run both calls on this string.
        first, args = _command(str(data["run"]).strip())
        # Nor are these three errors: `_reason` refused every definition that produces one.
        when, _ = core.trigger(data)
        chosen, _ = core.selectors(data)
        delivery, _ = _delivery(data)
        seen, _ = _visible(data)
        entry = Hook(
            name=name,
            description=str(data["description"]).strip(),
            events=_registered(when, delivery),
            script=_target(folder, here, first),
            path=path,
            enabled=name in on,
            trigger=when,
            selectors=chosen,
            message_type=delivery,
            args=args,
            visible=seen,
            output_file=_output_file(data, folder, here),
        )
        HOOKS[name] = entry
        if entry.enabled:
            # DEDUPED, and one closure per landing event. Two declared moments can route to
            # the same event - `SessionStart` and `TurnStart` asking for `user` both reach
            # `UserPromptSubmit` - and binding a callable there twice spawns the script
            # twice for one prompt. A fresh closure per event is required separately: see
            # `_script_hook`.
            for landed in dict.fromkeys(entry.events):
                hook(landed)(_script_hook(entry, landed))
    return sorted(name for name, e in HOOKS.items() if e.enabled), dict(REFUSED)


def unmet() -> dict[str, str]:
    """One note per hook whose `agent` names an agent nothing defined.

    `subagents.unavailable()`'s shape: both loaders scan at IMPORT, so neither can see the
    other's table then, and every caller of this runs afterwards.

    REPORTED rather than refused, and apart from `REFUSED` because the hook DID register:
    the file is correct and the agent may arrive later. Through `use`, so a miss means the
    subagents plugin is off and nothing is said - naming every target as unmet would turn
    a working `--disable-plugin subagents` run into a screenful of findings.

    `MAIN` is subtracted rather than looked up: it names the main conversation, not an
    agent file, so without this every `agent: main` would report as unmet.
    """
    try:
        defined = use("agents", "names")()
    except LookupError:
        return {}
    return {
        entry.name: f"no agent named {', '.join(gone)}; {entry.name} never fires for it"
        for entry in sorted(HOOKS.values(), key=lambda h: h.name)
        if entry.selectors.agent
        and (gone := sorted(entry.selectors.agent - defined - {MAIN}))
    }


@service("hooks:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/hooks/`. The route `/reload` reaches this plugin by.

    A service rather than an import: `slash.py` owns `/reload` and must not import this
    module, or `--disable-plugin hooks` would be a flag that removes nothing.
    """
    registered, refused = discover(cwd)
    # Folded in HERE and not inside `discover`, which also runs at import where the other
    # loader's table is still half-built. `slash.reload_` renders this mapping, so it is
    # the whole of what `/reload` needs.
    return registered, {**refused, **unmet()}


@service("command:hooks")
def hooks_(args: argparse.Namespace) -> int:
    """list the hooks defined in .un/hooks/, which are enabled, and what was refused"""
    # Re-scanned, not merely rendered: this is the surface an author reaches for straight
    # after dropping a file in.
    discover()

    def shown(entry: Hook) -> str:
        """Each declared moment, and the event it registered on when routing moved it.

        Both, because a reader who wrote `TurnStart` and finds `UserPromptSubmit` has no
        way to connect the two - and the arrow is the only place the indirection is visible.

        One entry per DECLARED moment, in declared order, joined with commas - the spelling
        the file itself uses. `entry.events` is aligned with `entry.trigger.event` for this,
        so the pairing needs no second lookup.
        """
        return ", ".join(
            f"{moment} -> {landed}" if entry.rerouted(landed) else moment
            for moment, landed in zip(entry.trigger.event, entry.events))

    live = [h for h in sorted(HOOKS.values(), key=lambda h: h.name) if h.enabled]
    idle = [h for h in sorted(HOOKS.values(), key=lambda h: h.name) if not h.enabled]
    if live:
        print("enabled:\n" + "\n".join(
            f"  {h.name:<16} {shown(h):<30} {h.description}" for h in live))
    if idle:
        # Named apart from a refusal, and told the fix: an operator seeing it under "not
        # registered" would hunt a mistake in a file that is fine.
        print(("\n" if live else "") + f"present, not enabled - add [hooks.<name>] with "
              f"{ENABLE} = true to {CONFIG_NAME}:\n" + "\n".join(
                  f"  {h.name:<16} {shown(h):<30} {h.description}" for h in idle))
    if not HOOKS:
        # Said rather than left blank: an empty list reads as a broken command.
        print(f"no hooks in {HOOKS_DIR}/")
    if REFUSED:
        # The only channel there is, `discover` having run at import where nothing was
        # listening. With the REASON, since a name alone leaves the author guessing.
        print("\nnot registered:\n" + "\n".join(
            f"  {key}: {why}" for key, why in sorted(REFUSED.items())))
    if gone := unmet():
        # Apart from the refusals above because the hook DID register: a capability the
        # file asked for and has not got YET, not a definition turned away.
        print("\nagent naming no defined agent:\n" + "\n".join(
            f"  {name}: {why}" for name, why in sorted(gone.items())))
    return EXIT_OK


# Scanned at IMPORT: `SessionStart` fires inside the first turn, so a hook registered any
# later has already missed it. `core.load()` imports this in the project directory, and
# `/reload` is the recovery when it was not.
discover()

if REFUSED:
    # ADR-0014 spelled out: un starts. Every surface is built after this import, so
    # stderr is the only channel that exists here.
    print("\n".join(f"un: hooks: {key}: {why}" for key, why in sorted(REFUSED.items())),
          file=sys.stderr)
