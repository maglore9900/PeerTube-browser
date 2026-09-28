"""Workflows: Python that drives the agent, with gates it cannot talk past.

A workflow is a service under `workflow:<name>`, so `un run` finds it through the same
registry as everything else. There are two routes to one, and this module is both:

- **In Python**, `@service("workflow:<name>")` in a plugin. That is how un itself would
  ship a workflow, and how an aftermarket plugin contributes one. None ships today.
- **In a file**, `.un/workflows/<name>.py`, discovered by `discover` below. That is the
  aftermarket route that needs no distribution and no entry point: an agent writes the
  file, and un registers what it declares.

The point of either is the `if` on a real exit code. The model does not decide whether
the tests passed; pytest does, and a subprocess return code is not open to persuasion.
Commands run through the session's shell seam rather than raw subprocess, so a sandboxed
backend covers workflows too.

**Discovery PARSES; it never imports.** A file under `.un/workflows/` is agent-authored
code, and importing one to read its description would execute it at scan time - before
any permission gate existed to see it, and at `un` startup rather than on request. So the
declaration is read with `ast` and the module is imported only when a launch has been
allowed. That is the single property this module exists to hold.

Writes: nothing directly. The agent a workflow drives may write anything its tools allow.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shlex
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import argparse
import contextlib
import io

from un import EXIT_FAILED, EXIT_OK, REGISTRY, Session, frontmatter, gate, run_agent, service, tool, use
from un import core
from un.core import BACKGROUND, CONFIG, MAIN, SLUG, UN_DIR, scan

# The name a launch is gated under, and the rule kind an operator writes to allow one.
# From `permissions` rather than a second copy: the two must not come to disagree about
# what the matcher is called.
from un.plugins.stock.permissions import WORKFLOW_LAUNCH


WORKFLOWS = UN_DIR / "workflows"

# What a file must declare, and the entry point it must define. ADR-0014's declare-or-be-refused,
# met per kind. The declaration is a YAML header in the MODULE DOCSTRING, which is a string
# literal in the tree - so reading it still executes nothing, which is this module's whole posture.

MARKER = "---"
# `_KEY` suffixed, because `DESCRIPTION` at line 79 is the `Workflow` TOOL's description and a
# second binding of that name silently wins over the first.
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
ENTRY = "run"

# Files that named themselves a workflow and were refused, and why. `tools.REFUSED`'s
# posture and its reason: import time has no channel to report on, so `un workflows`
# renders this. Read by the listing surfaces, so it is populated rather than merely
# returned - a local dict handed back would leave that listing empty.
REFUSED: dict[str, str] = {}

 # Workflows a header declared and no config entry enabled. Keyed by name, valued by the
# relative path, so the listing can say which file is sitting switched off. Separate from
# `REFUSED` because the two are different states with different fixes: one is broken, the
# other is merely off, and an operator shown them together debugs the wrong one.
DISABLED: dict[str, str] = {}

# What the launch refusal and the malformed-table finding both name. `hooks.CONFIG_NAME`'s
# posture: the file to open is the answer, so it is spelled once.
CONFIG_NAME = str(CONFIG)

# The `[<section>.<name>]` table an operator activates a workflow in, and the key inside it.
# The section is passed to `core.enabled`, which serves `[agents]`, `[skills]`, `[hooks]`
# and `[rules]` from the same forty lines.
SECTION = "workflows"
ENABLE = "enable"

# rat-tail: a literal ceiling, not a config key. A workflow launching a workflow is a
# real composition, and three deep is past any sequence anyone has written on purpose;
# raise it, or make it a launch config key, the first time a real one needs four.
MAX_DEPTH = 3

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "args": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}

DESCRIPTION = (
    "Run a workflow: Python that drives several agent turns and gates each step on a "
    "real command's exit code. Takes the workflow's name and its arguments as strings. "
    "Returns the workflow's exit status and whatever it printed."
)


def _launch(session: Session, name: str, args: list[str]) -> str:
    """One launch, on a fork, bounded by depth. The body every launch SURFACE shares.

    Every failure comes back as TEXT. `subagents.task`'s posture and its reason: a raise
    here ends the model's turn over a workflow's bug, where a returned string is something
    it can read and act on.

    The fork is what keeps the workflow's turns out of the calling conversation, and
    `workflow_depth` is what bounds a workflow that launches a workflow; a subagent spawn adds to the same count. The tool is NOT
    withheld from the child - the operator chose a bound over withholding it - so the
    count crossing the fork is the only thing standing between composition and recursion.
    """
    if session.workflow_depth >= MAX_DEPTH:
        return (f"refused: workflows are already {session.workflow_depth} deep and "
                f"{MAX_DEPTH} is the limit")
    try:
        found = use("workflow", name)
    except LookupError as exc:
        return str(exc)

    child = session.fork(name)
    child.workflow_depth = session.workflow_depth + 1
    printed = io.StringIO()
    try:
        # stderr as well as stdout: a file-authored workflow reports its own failure
        # through `session.report`, which writes there, and the model would otherwise be
        # told only `[exit status 1]` with the reason going to a channel it cannot see.
        with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
            code = found(child, *args)
    except Exception as exc:
        # Converted to a documented result rather than swallowed: the model is told which
        # workflow failed and how, which is what `rules/implementation-principles.md`
        # permits and what a bare `except: pass` would not.
        return f"workflow {name!r} raised {type(exc).__name__}: {exc}"
    finally:
        # In `finally` because a workflow that raised part-way still spent what it spent,
        # and `fork` zeroed the child's counter so nothing else will report it.
        session.spend(child.tokens)

    # `git_ro` and `tools._script_tool`'s ending, and their reason: a workflow that
    # printed nothing would otherwise read to the model as having succeeded quietly.
    # `.strip()` covers the empty case, so no branch is needed for it.
    return f"{printed.getvalue().rstrip()}\n[exit status {code}]".strip()



@tool("Workflow", DESCRIPTION, SCHEMA)
def launch(*, session: Session, name: str, args: list[str] = ()) -> str:
    """Run a workflow for the model. One of two callers of `_launch`; the other is the
    `slash:workflows:<name>` entry an operator reaches from the REPL."""
    return _launch(session, name, list(args))


def _slash_launch(name: str, description: str):
    """The REPL's surface onto `_launch`. An ADDITIONAL caller, never a second route.

    A second route would be a second place the launch gate could be got wrong, which is the
    one property this module exists to hold - so this resolves nothing and gates nothing
    itself. The rest of the line reaches `run` as one argument, unsplit; see `run` below.
    """

    def run(session: Session, rest: str) -> str:
        # NOT split. A workflow argument is whatever the operator typed, and that line is routinely prose - a
        # build request, a brief with a table in it - where an apostrophe is an unbalanced quote and a paste
        # has newlines. `shlex` either raises out of `slash`, which `_turns` does not guard and which ends the
        # REPL, or succeeds and silently drops the quoting that carried the meaning. A workflow wanting several
        # arguments splits the string itself, where it knows which of them are paths and which are sentences.
        return _launch(session, name, [rest] if rest.strip() else [])

    # Read back by the listing surfaces the way `_file_workflow` sets it, so the text an
    # author wrote in the header is the text an operator is shown for either entry.
    run.un_description = description
    return run

def _listing(root: Path | None = None) -> str:
    """What registered and what was turned away. One renderer, because `un workflows` and
    `/workflows` answer the same question and two copies would come to disagree.

    Re-scans rather than merely rendering: this is the surface an author reaches for
    straight after writing a workflow, and `discover` is re-runnable precisely so that
    asking the question is allowed to answer it.
    """
    discover(root)
    lines = [f"  {name.split(':', 1)[1]:<16} {fn.un_description}"
             for name, fn in sorted(REGISTRY["service"].items())
             if name.startswith("workflow:") and getattr(fn, "un_from_file", False)
             and name.split(":", 1)[1] not in DISABLED]
    # Said rather than left blank: an empty list reads as a broken command, where "no
    # workflows" is an answer.
    body = "\n".join(lines) if lines else "  no workflows in .un/workflows/"
    if DISABLED:
        # Its own block, above `refused:`. Switched off and broken are different states with
        # different fixes, and an operator shown one list debugs the wrong one.
        body += "\n\ndisabled:\n" + "\n".join(
            f"  {name:<16} {where} - add [{SECTION}.{name}] with {ENABLE} = true"
            for name, where in sorted(DISABLED.items()))
    if REFUSED:
        body += "\n\nrefused:\n" + "\n".join(
            f"  {name:<16} {why}" for name, why in sorted(REFUSED.items()))
    return body


@service("command:workflows")
def workflows_(args: argparse.Namespace) -> int:
    """list the workflows registered from .un/workflows/, and any that were refused"""
    print(_listing())
    return EXIT_OK


@service("slash:workflows")
def slash_workflows(session: Session, rest: str) -> str:
    """list workflows and any that were refused"""
    return _listing(session.root)


def _declared(text: str) -> tuple[dict | None, str | None]:
    """The file's header, read WITHOUT importing it. Three outcomes, because there are three.

    - `(None, None)` - no header. NOT a workflow and NOT a mistake: an ordinary module living
      beside one, which is what makes a workflow's own directory usable.
    - `(None, reason)` - a header that cannot be used. A finding, because the file declared
      itself and got it wrong, and the file is the author's to fix.
    - `(data, None)` - a usable declaration.

    A docstring that OPENS with the marker is a declaration attempt, even when it carries
    nothing. Detecting the header by whether the parsed block came out truthy would make a
    workflow whose header lost its keys silently invisible - the one failure the silent-skip
    rule above is most likely to hide.

    `ast.get_docstring` reads a string literal out of the tree. Nothing is imported and nothing
    is evaluated, which is the property this whole path exists to hold.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        # The parser's own reason, passed through rather than re-worded.
        return None, f"it does not parse: {exc.msg} (line {exc.lineno})"

    doc = ast.get_docstring(tree) or ""
    if not doc.lstrip().startswith(MARKER):
        return None, None

    data, _, error = frontmatter.parse(doc)
    if error:
        # `frontmatter.parse` hands back the exception's class name alone, so the sentence
        # around it is what tells an author which of the rules they broke.
        return None, f"its header does not parse: {error}"
    for key in (NAME_KEY, DESCRIPTION_KEY):
        if not str(data.get(key) or "").strip():
            # An absent key and a whitespace value are different inputs meaning one thing, and
            # the header is hand-written.
            return None, f"no {key} in its header"
    if not any(isinstance(node, ast.FunctionDef) and node.name == ENTRY
               for node in tree.body):
        # Only `tree.body` is walked, so a `run` nested in an `if` or a class does not count.
        # `_file_workflow` calls `getattr(module, ENTRY)`, so accepting a nested one would
        # register a workflow that fails at launch instead of at scan.
        return None, f"no top-level def {ENTRY} in the module"
    return data, None


def _reason(name: str) -> str | None:
    """Why this NAME cannot be registered, or None. The name is the header's, not the file's.

    It became the checked thing when the header started supplying it: a name is what un composes
    a registry key and a path segment from, and the filename is now the author's own business.
    """
    if not SLUG.fullmatch(name):
        return f"the name {name!r} must be lowercase letters, digits and hyphens"
    if REGISTRY["service"].get(f"workflow:{name}") is not None:
        return f"a workflow named {name!r} is already registered"
    return None


def _file_workflow(path: Path, name: str, description: str, *, enabled: bool = True):
    """Registered callable that runs a workflow file only after gate approval.

    Gate runs before module execution (`exec_module`) so a refused launch never executes
    workflow code (unlike gate-after-execution, which would run code first then refuse).
    A single gate serves CLI (`cli._workflow`) and Workflow tool paths, preventing bypass.
    Module not in `sys.modules` to avoid caching (edited workflow runs new code; modules not
    shared between projects).
    """

    def run(session: Session, *argv: str) -> int:
        if not enabled:
            # BEFORE the gate and long before `exec_module`. A workflow nobody switched on
            # must not reach the operator as a question, and must not have run a line of
            # the file by the time it is refused. The message names the two things they
            # would type: `subagents.run`'s posture for an agent present but not enabled.
            session.report(f"workflow:{name}",
                            f"present but not enabled; add [{SECTION}.{name}] with "
                            f"{ENABLE} = true to {CONFIG_NAME}")
            return EXIT_FAILED
        # Gated as a LAUNCH, not as the `Workflow` tool: the agent loop already gated
        # that tool call, and gating both under one name asks the operator the same
        # question twice for one launch. No tool holds this name, so the rung that
        # allows a stock tool cannot claim it and the tier decides.
        args = {"name": name, "args": list(argv)}
        call = {"kind": "tool", "name": WORKFLOW_LAUNCH, "input": args}
        decided = gate(session, WORKFLOW_LAUNCH, args, call)
        if decided.outcome != "run":
            session.say("tool", decided.message)
            return EXIT_FAILED

        spec = importlib.util.spec_from_file_location(f"un.workflow.{name}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            # The module body runs HERE, so a workflow that names something it never
            # imported fails at this line rather than at `run` - which is the shape an
            # agent copying a template produces, and the one static discovery cannot see.
            spec.loader.exec_module(module)
            code = getattr(module, ENTRY)(session, *argv)
        except Exception as exc:
            # Reported and converted, never swallowed. A workflow is aftermarket code, so
            # a raise out of it is somebody else's bug: `cli.main` catches three
            # exceptions and this is not one of them, so without this an operator gets a
            # raw traceback and a CI job gets whatever CPython decided to exit with.
            session.report(f"workflow:{name}", f"{type(exc).__name__}: {exc}")
            return EXIT_FAILED
        if not isinstance(code, int):
            # `cli._workflow` hands this straight to `SystemExit`, and `SystemExit(None)`
            # exits 0 - so a workflow that forgot to return would report SUCCESS. The
            # quietest way this contract can break, and the reason it is checked.
            session.report(f"workflow:{name}",
                           f"returned {type(code).__name__}, not an exit code")
            return EXIT_FAILED
        return code

    # Carried on the callable because `service` takes no description the way `tool` does:
    # a service key is all `_register` files. The listing surfaces read it back from here,
    # so the text an author wrote in `UN_WORKFLOW` is the text an operator is shown.
    run.un_description = description
    return run


def discover(root: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Register every qualifying `.un/workflows/**/*.py`. Returns (runnable, refused).

    RECURSIVE, and a workflow is named by its HEADER rather than by its path, so a directory is only a place to keep a workflow's files. Takes a PATH, not a `Session`, because it runs at module import; `/reload` passes `session.root`.

    Re-runnable: `scan` drops the previous scan's workflows first, so an edited or deleted file and a changed `[workflows]` entry all take effect. A declared workflow the table does not enable is registered, listed in `DISABLED`, and refuses every launch.
    """
    registered: list[str] = []
    DISABLED.clear()

    def read(where: Path, path: Path, text: str, on) -> str | None:
        declared, refusal = _declared(text)
        if declared is None:
            # No refusal and no declaration means an ordinary module: silence, not a finding.
            return refusal
        name = str(declared[NAME_KEY]).strip()
        if refusal := _reason(name):
            return refusal
        if name not in on:
            # `setdefault`, so the first file to claim a name is the one reported.
            DISABLED.setdefault(name, path.relative_to(where / WORKFLOWS).as_posix())
        description = str(declared[DESCRIPTION_KEY]).strip()
        service(f"workflow:{name}")(_file_workflow(path, name, description, enabled=name in on))
        if name in on:
            service(f"slash:workflows:{name}")(_slash_launch(name, description))
            registered.append(name)
        return None

    REFUSED.clear()
    REFUSED.update(scan(root, "workflows", WORKFLOWS, "**/*.py", read,
                        section=SECTION, noun="workflow"))
    return registered, dict(REFUSED)


@service("workflows:discover")
def rescan(cwd: Path) -> tuple[list[str], dict[str, str]]:
    """Re-scan `.un/workflows/`. The route `/reload` reaches this plugin by.

    A service rather than an import, because `slash.py` owns `/reload` and must not import
    this module: `--disable-plugin workflows` would then be a flag that removes nothing.
    """
    return discover(cwd)


discover()

# ---- what a workflow drives un WITH --------------------------------------------------
#
# A workflow is Python that gates on real outcomes, and these are the four things the
# first one needed that had nothing to do with its subject. They live here rather than in
# any workflow because every one routes through un: a workflow reaches a provider, a
# subagent or a shell only by asking un to, so the shapes those asks take are un's.


def payload(session: Session, prompt: str, *, fields=None, retries: int = 1) -> dict[str, str] | None:
    """One agent action, its answer handed in through `Submit`. None when none was ever accepted.

    `fields` names what the answer must carry, or None for any non-empty fields. A run that ends without an accepted
    `Submit` is asked again, with a fresh seed, up to `retries` times.

    Through `run_agent` rather than the provider service, which is what puts the prompt in `session.messages`, fires
    the hook chains around the turn and accrues the spend.
    """
    if session.tools is not None and "Submit" not in session.tools:
        raise ValueError("payload: this session cannot see the Submit tool")
    ask = f"{prompt}\n\n{expect(session, MAIN, fields)}"
    for attempt in range(retries + 1):
        run_agent(session, ask)
        if (answer := submitted(session)) is not None:
            return answer
        if attempt < retries:
            ask = f"Your last turn ended without an accepted Submit. Hand your answer in now.\n\n{expect(session, MAIN, fields)}"
    session.report("workflow", "no answer was ever handed in through Submit")
    return None


def _ask(session: Session, name: str, prompt: str, emit=None) -> str:
    """One subagent. A raise out of it is THAT agent's failure, not the workflow's, so it
    comes back as text for `fanout`'s validator to judge like any other answer.

    `emit` is forwarded to `agents:run`, which tags what reaches it with the agent's name.
    Without one a fanned dispatch runs SILENT, and a workflow's longest waits are usually
    its concurrent ones: an operator watching a blank terminal cannot tell a working agent
    from a wedged one, which is the case that sink exists for. Several children writing to
    one sink interleave, and the name on each line is what makes that readable."""
    try:
        return use("agents", "run")(session, name, prompt, emit=emit)
    except Exception as exc:  # noqa: BLE001
        return f"[{name} raised {type(exc).__name__}: {exc}]"


def fanout(session: Session, agents, prompt: str, *, usable=None,
           workers: int | None = None, emit=None) -> tuple[dict[str, str], list[str]]:
    """`agents` on one prompt, concurrently. Returns (what answered, what never did).

    ONE prompt and DISTINCT names, both deliberate. `subagents._child` derives the forked
    session id from the agent's NAME, so two concurrent runs of one agent would write one
    transcript from two threads; a caller with several jobs for one agent calls this once
    per job. The rest is safe by design: `Session.spend` takes a lock precisely because a
    batch of `Task` calls already runs its subagents on several pool threads at once.

    `usable` decides whether an answer is an answer. A subagent that refuses returns TEXT,
    so truthiness alone would bank a refusal as a result. One that fails the test is
    re-dispatched ALONE - its partners have their own results already, and re-running them
    spends a subagent each to re-answer a question that was answered.
    """
    check = usable or (lambda text: bool((text or "").strip()))
    names = list(agents)
    with ThreadPoolExecutor(max_workers=workers or len(names),
                            thread_name_prefix="un-workflow") as pool:
        futures = {name: pool.submit(_ask, session, name, prompt, emit) for name in names}
        got = {name: future.result() for name, future in futures.items()}

    missing: list[str] = []
    for name, answer in list(got.items()):
        if check(answer):
            continue
        retry = _ask(session, name, prompt, emit)
        if check(retry):
            got[name] = retry
        else:
            missing.append(name)
            got.pop(name)
    return got, missing


def script(session: Session, path, *args: str, timeout: int = 180):
    """Run a project script on un's own interpreter, through the session's shell seam.

    `sys.executable` rather than `python`: the interpreter that imported un is the one
    with un's dependencies, and a workflow runs wherever un was launched from. Through the
    seam rather than `subprocess`, so a sandboxed backend covers this too. The path is
    QUOTED, because one carrying a space is otherwise two arguments.

    Returns the `Ran` unaltered, a non-zero code included. A workflow exists to gate on
    that code, so raising here would take the decision away from the one making it.
    """
    line = " ".join([sys.executable, shlex.quote(str(path)), *args])
    return use("shell", session.shell)(session).run(line, timeout)


def json_result(ran) -> tuple[dict, str | None]:
    """A `--json` command's data, or the reason there is none. Never raises.

    `Ran.code` answers "did it fail" and stays the gate for that. This answers "what did
    it find", which is the question a workflow filtering findings has to ask - and it asks
    it of PARSED data, never of formatted output. The reason names the exit code and what
    the command said, because a caller told only "it failed" cannot say what to open.
    """
    try:
        data = json.loads(ran.output)
    except json.JSONDecodeError:
        return {}, f"did not return JSON (exit {ran.code}): {ran.output[-500:]}"
    if not isinstance(data, dict):
        return {}, f"returned {type(data).__name__}, not an object (exit {ran.code})"
    return data, None


# ---- the answer an agent hands in --------------------------------------------------
#
# `Submit` replaces "end the reply with a sentinel and put each part in a tag". The workflow seeds the
# conversation that will answer (`expect`), the agent hands its answer in as the tool's arguments, and a call
# the workflow cannot use is refused inside that conversation, where the agent can fix it. An accepted call
# ends the agent's run, and the workflow reads the answer back (`submitted`).

# Keyed by the id of the conversation that will answer. rat-tail: process memory, so a restart mid-dispatch loses
# the answer; persist this dict if that ever matters.
_SEEDS: dict[str, dict] = {}
_SEEDS_LOCK = threading.Lock()

SUBMIT_DESCRIPTION = (
    "Hand in your answer to a workflow step. Each argument is one field the step names, its value that field's "
    "full content as text. Give every field named and no other; none may be empty, and a field with nothing to "
    "say takes the word the step gives it, usually `none`. A rejection says what is wrong and shows the call to "
    "make. An accepted call ends your turn and cancels any background job still running.")


def _key(session: Session, agent: str) -> str:
    # `subagents._child` forks on the agent's NAME, so a subagent answers as `<id>-<name>`.
    return session.id if agent == MAIN else f"{session.id}-{agent}"


def expect(session: Session, agent: str = MAIN, fields=None) -> str:
    """Seed the conversation `agent` will run as, and return the paragraph its prompt needs.

    `fields` None accepts any non-empty fields; named, the answer must be exactly those. Seeding clears an earlier
    answer, so a run that never submits reads as None rather than as the last run's.
    """
    names = None if fields is None else [str(name).strip() for name in fields]
    if names is not None and not names:
        raise ValueError("expect: name at least one field, or pass fields=None to accept any")
    if names and (clash := {"session", BACKGROUND} & set(names)):
        raise ValueError(f"expect: {', '.join(sorted(clash))} cannot be a field name")
    with _SEEDS_LOCK:
        _SEEDS[_key(session, agent)] = {"fields": names}
    wanted = (f"with exactly these arguments: {', '.join(f'`{name}`' for name in names)}" if names
              else "with one argument per field the step asks for")
    return (f"## How to answer\n\nHand your answer in by calling the `Submit` tool {wanted}. Each value is that "
            f"field's full content as text; a field with nothing to say takes the word the step gives it, usually "
            f"`none`. A rejection says what is wrong, so fix it and call `Submit` again.")


def submitted(session: Session, agent: str = MAIN) -> dict[str, str] | None:
    """What `agent` had accepted, or None where nothing was. Ends the seed either way."""
    with _SEEDS_LOCK:
        seed = _SEEDS.pop(_key(session, agent), None)
    return seed.get("answer") if seed else None


def _submit_schema(session: Session) -> dict | None:
    """What this conversation is shown of `Submit`: its seed, as the tool's arguments. Nothing where no workflow seeded it."""
    with _SEEDS_LOCK:
        seed = _SEEDS.get(session.id)
    if seed is None:
        return None
    if seed["fields"] is None:
        return {"type": "object", "additionalProperties": {"type": "string"}, "minProperties": 1}
    return {"type": "object", "additionalProperties": False, "required": list(seed["fields"]),
            "properties": {name: {"type": "string", "description": f"The full content of `{name}`."} for name in seed["fields"]}}


@tool("Submit", SUBMIT_DESCRIPTION, _submit_schema)
def submit(*, session: Session, **fields) -> str:
    """Check an answer against this conversation's seed and keep it.

    A rejection is TEXT, never a raise: it is the agent's next instruction, and it has to reach the conversation
    that can act on it.
    """
    given = {str(name).strip(): value if isinstance(value, str) else json.dumps(value)
             for name, value in fields.items()}
    with _SEEDS_LOCK:
        seed = _SEEDS.get(session.id)
        if seed is None:
            return "rejected: no workflow step is waiting on an answer from this conversation."
        wanted = seed["fields"]
        problems = []
        if not given:
            problems.append("no fields were given")
        # A seed that names its fields names ALL of them: a missing one and an extra one are the same mistake.
        if wanted and (missing := [name for name in wanted if name not in given]):
            problems.append(f"missing {', '.join(missing)}")
        if wanted and (extra := [name for name in given if name not in wanted]):
            problems.append(f"{', '.join(extra)} is not a field of this step")
        if empty := [name for name, value in given.items() if not value.strip()]:
            problems.append(f"{', '.join(empty)} is empty - a field with nothing to say takes the word the step "
                            f"gives it, usually `none`")
        if problems:
            # The whole call rather than a list of names: an agent copies a shape more reliably than it builds one.
            shape = json.dumps({name: "<its full content>" for name in wanted} if wanted
                               else {"<field name>": "<its full content>"}, indent=2)
            return f"rejected: {'; '.join(problems)}. Call Submit again with exactly these arguments:\n{shape}"
        seed["answer"] = given
    session.end_turn = True
    return f"accepted: {', '.join(given)}"
