---
name: workflow-authoring
description: How to build a workflow - what un already does for you and must be routed through, the contract the loader holds you to, how to shape one so the decisions are yours and the judgement is the agent's, and the traps that have already cost a build. Read it before writing anything into .un/workflows/.
---
# Agent instructions:

## What a workflow is

Python that drives one or more agents through several turns and decides what happens next from a real outcome: an exit code, a parsed result, a file that is or is not there. Most of the file is ordinary Python. An agent is asked only where judgement is unavoidable.

The gate is the product. `un` cannot be talked out of an `if` on a subprocess return code, and that is the whole reason to write one of these instead of a prompt.

## Requirement: everything goes through un

**A workflow does not run without un, so what it needs from un comes from un.** This is the first requirement, not a style preference: it is what makes a workflow observable, gated, costed and recorded rather than a script that happens to live in `.un/workflows/`.

Before writing a line, find the un capability for each thing the workflow needs:

| What you need | What you call | Never instead |
|---|---|---|
| One agent action with an answer you can use | `payload(session, prompt, fields=[...])` | A provider SDK, `requests`, an API key of your own |
| An answer from a subagent or a fork you run yourself | `expect(...)` before the run, `submitted(...)` after | A sentinel, a tag, or a heading you parse out of the reply |
| A raw agent turn | `run_agent(session, prompt)` | as above |
| Several named subagents at once | `fanout(session, agents, prompt)` | `ThreadPoolExecutor` over your own calls |
| One subagent | `use("agents", "run")(session, name, prompt)` | as above |
| A project script on un's interpreter | `script(session, path, *args, timeout=...)` | `subprocess`, `sys.executable` by hand |
| Any other command | `use("shell", session.shell)(session).run(line, timeout)` | `subprocess`, `os.system` |
| A `--json` command's data | `json_result(ran)` | `json.loads` on raw output with your own try/except |
| A conversation that must not see another's answers | `session.fork("<suffix>")` | A second `Session` of your own |
| Asking the OPERATOR a question mid-run | `use("ask", session.approval)(session, question, details, options, multi=False)` | `input()`, a prompt to the agent asking it to guess |
| Reading or writing a file | `use("fs", session.fs)(session)`, then `.read(path)`, `.write(path, text)`, `.glob(...)`, `.grep(...)` | `Path.read_text`, `Path.write_text`, `open` |
| Telling the operator something failed | `session.report("<source>", text)` | `print` to stderr, `logging` |
| Progress the operator watches | `print(...)` | as above |
| Frontmatter or a YAML header | `from un import frontmatter` | A YAML dependency |
| The project root | `session.root`, or `project_root()` | `os.getcwd()`, walking upward yourself |
| The process's verdict | `return EXIT_OK` / `EXIT_FAILED`, or your own int | `sys.exit`, `raise SystemExit` |

Routing through un is what puts an agent turn in the session's history, fires the hook chains around it, accrues its spend against the operator's meter, and lets a sandboxed shell backend cover a command. A call that goes around un has none of that, and the operator cannot see it happened.

**File access goes through the `fs:` service, not through `pathlib` directly.** One seam for every read and write means a sandboxed or remote backend covers the workflow too. It also does two things by hand you would otherwise forget: `write` creates the parent directories, and it takes a lock on the target, so two writers naming one path cannot leave you the loser's content. `Path(__file__).parent` to locate your own prompts is fine, and so is `Path` as a path type; it is `read_text`, `write_text` and `open` that belong to the seam.

```python
fs = use("fs", session.fs)(session)
prompt = fs.read(str(HERE / "review.md"))
fs.write(str(out), body)
```

A relative path resolves against `session.cwd`, which is not necessarily the project root and is never your workflow's own directory. Pass an absolute path, or build one from `session.root` or `Path(__file__).parent`.

**Asking the operator mid-run is legitimate.** A workflow that needs a human decision at step three asks for one through `ask:` rather than guessing or delegating the guess to a model. The adapter renders a numbered list and returns the values picked, or `None` where the operator declined, which is an outcome to branch on like any other.

**Do not re-derive what another tool in the project already answers.** Where a script, plugin or skill resolves something (a root directory, a config value, a manifest), load its resolver and ask it rather than reading the same file a second way. Two readers of one question eventually disagree, and the day they do, the workflow acts on a different answer than the thing it is driving. Loading a sibling module by path is the cheap way:

```python
import importlib.util

spec = importlib.util.spec_from_file_location("their_env", root / "path/to/_env.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

## The contract the loader holds you to

`src/un/plugins/stock/workflows.py` finds, registers, gates and launches your file. What it does, in the order it does it:

1. **It walks `.un/workflows/` to full depth** and reads every `.py` WITHOUT importing it. Your module body does not run at scan time, and must not need to.
2. **It reads your module docstring** and parses a YAML header out of it. The header's `name` is what your workflow is called. The filename is not consulted.
3. **It checks a top-level `def run` exists.** Defined inside an `if` or a class, it does not count.
4. **It reads `[workflows.<name>]` from `.un/config.toml`.** Absent or `enable = false` means your workflow is registered, listed, and refuses every launch.
5. **It registers `workflow:<name>`, and `slash:workflows:<name>` if enabled.**
6. **On launch it calls the permission gate BEFORE importing your module**, so a refused launch never executes a line of your file.
7. **It imports your module and calls `run(session, *argv)`.** Your return value becomes the exit code, unaltered.

What it refuses, each with a reason the operator sees in `un workflows`: a file that is not UTF-8 text, a file that does not parse, a header that does not parse, a header missing `name` or `description`, a name that is not lowercase letters, digits and hyphens, a name a workflow already holds, and a module with no top-level `run`.

**A `.py` with no header at all is passed over in silence**, so a private helper module beside your workflow is not a broken workflow. It is not a workflow.

Two things the loader does NOT do for you: it does not pass the project root (take `session.root`), and it does not put your directory on the import path (a sibling module is loaded by path, as above).

## The file

```python
"""---
name: typecheck
description: One sentence: what it does, so an operator listing workflows knows.
---
"""


def run(session, *argv) -> int:
    ...
    return 0
```

`argv` arrives as strings, because it comes off the command line. Convert what you need.

A workflow with files of its own keeps them in a directory beside it and reads them relative to itself, because un composes no path to them:

```
.un/workflows/my-workflow/
    my-workflow.py
    review.md
    report-template.md
```

```python
from pathlib import Path

HERE = Path(__file__).parent
prompt = (HERE / "review.md").read_text(encoding="utf-8")
```

Turn it on with `[workflows.<name>]` and `enable = true` in `.un/config.toml`. A workflow written, edited, enabled or disabled after launch reaches a running session on `/reload`, with no relaunch.

## Shape: you decide, the agent judges

**Every decision with a right answer belongs in Python, in a named function that takes plain arguments and returns plain data.** `run` is wiring: it resolves inputs, calls those functions, drives the agent where judgement is needed, and returns an exit code.

| The step is | Who does it |
|---|---|
| Choosing, filtering, ordering, counting, grouping, placing, formatting | You, in a function |
| Reading a file, running a command, branching on its result | You, in `run` |
| Judging quality, writing prose, deciding what a document means | An agent |
| Anything you could write down the rule for | You. Write the rule down. |

An agent turn costs a provider call, cannot be reproduced, and re-judges what may already have been settled. A function costs nothing, gives the same answer twice, and can be exercised on its own. **When you catch yourself writing a prompt that asks an agent to concatenate, group or sort something, that is a function you have not written yet.**

This split is also what makes a workflow inspectable: a reader can see what the workflow decides without reading a prompt, and the prompts carry only what genuinely needed a mind.

## Prompts are files, not string literals

Python owns the process; markdown owns what an agent is asked. A prompt in a `.md` beside the workflow can be read, reviewed and edited without touching code, and the workflow stays a page of logic instead of a page of prose in quotes.

Fill a template by whole-string replacement, never `str.format` and never an f-string over agent text:

```python
body = template.replace("<target/>", target).replace("<findings/>", findings)
```

**`.format()` raises on any `{` in the text.** Agent prose contains braces constantly: JSON, code samples, set notation. A template filled with `.format` works until the first finding that quotes a dict.

## Handling what an agent hands back

Agent output is untrusted structure. It carries headings at any depth, fenced blocks, your own delimiters quoted back at you, and whatever the model felt like emitting.

**Never locate anything in it by markdown structure.** Slicing "from this heading to the next heading" breaks the moment a fragment carries a heading of its own, and it breaks silently: you get half a finding, or somebody else's quoted document pooled as though an agent had raised it.

Where you must contain agent text, delimit it with something its content cannot forge, and neutralise that delimiter on the way in:

```python
def _safe(text: str) -> str:
    """Agent text made safe to sit inside the report's own delimiters."""
    for tag in ("target", "fragment"):
        text = text.replace(f"</{tag}>", f"&lt;/{tag}&gt;").replace(f"<{tag} ", f"&lt;{tag} ")
    return text

block = f'<fragment auditor="{name}">\n{_safe(fragment)}\n</fragment>\n'
```

Reading it back is then an exact match on the delimiter rather than a guess about structure.

**If you do split agent markdown, be fence-aware.** A `### ` inside a fenced block is an auditor quoting a document, not a section of its answer. Track the fence as you walk the lines.

**Take an answer through `Submit`, never out of the reply.** Seed the conversation that will answer with `expect`, put the paragraph it returns in the agent's prompt, run the agent, and read the answer back with `submitted`. The agent calls `Submit` with the fields as its arguments, `Submit(verdict="...", findings="...")`, so each part arrives as its own string and nothing is parsed out of prose. `payload` does all of this for the workflow's own session.

```python
how = expect(session, "reviewer", ["verdict", "findings"])
use("agents", "run")(session, "reviewer", f"{brief}\n\n{how}")
answer = submitted(session, "reviewer")   # {"verdict": ..., "findings": ...} or None
if answer is None:
    session.report("my-workflow", "reviewer handed in no answer")
    return EXIT_FAILED
```

- `agent` is `"main"` for the conversation `session` holds, or the name `agents:run` forks a subagent under. The seed is keyed by the id of the conversation that will answer, `session.id` or `<session.id>-<agent>`, so seed the session the subagent is forked FROM.
- Named `fields` means exactly those fields, none empty or whitespace. `fields=None` accepts any non-empty set of non-empty fields. An empty list, or a field named `session` or `background`, raises `ValueError`.
- A field with nothing to say takes the word your prompt gives it, usually `none`. Name that word in the prompt.
- A call that does not fit the seed is rejected inside the agent's conversation, as a result beginning `rejected:` that names the fault and shows the call to make. It does not end the turn, so the agent fixes it itself and you never see the bad attempt.
- An accepted call ends the agent's turn with no further provider call, and stops any background job still running.
- `submitted` clears the seed whether or not an answer came, so call it once per `expect`.
- A conversation nobody seeded is not shown `Submit` at all, and a seeded one needs no permission rule for it.
- Seeds and answers live in process memory, so a restart mid-dispatch loses the answer.

A handed-in answer says nothing about whether it is any good; your own gate decides that.

## What the run produces

**Decide deliberately whether the agents in your workflow may write.** A workflow may drive a main agent with the full tool set, and for plenty of jobs that is the point. But where the workflow has a rule about what must not change, holding it by construction beats stating it in a prompt: ask for the content, write it yourself through `fs`, and give the agents nothing that writes. An agent that cannot write cannot damage what it was only supposed to read, whatever a prompt does or does not talk it into.

State which posture you chose in the module docstring. A reader of a workflow that drives a writing agent needs to know that was a decision rather than an oversight.

**An output file is a record.** Name it for what produced it, including the scope it ran over, and never overwrite one:

```python
stem = f"report-{date}" + (f"-{scope}" if scope else "")
out = directory / f"{stem}.md"
nth = 2
while out.exists():
    out = directory / f"{stem}-{nth}.md"
    nth += 1
```

A name carrying only the date collides with every other run that day, and the loser is a record nothing reproduces. Derive the scope part from the RESOLVED input rather than from what the operator typed, or two spellings of one run write two files.

## The rule that makes a gate hold

Branch on `ran.code`, not on text in `ran.output`, and put the branch in Python, not in a prompt.

```python
ran = script(session, "scripts/run_tests.py", "--quiet", timeout=600)
if ran.code != 0:
    run_agent(session, f"Make these tests pass:\n{ran.output[-4000:]}")
```

`Ran.code` is an integer field for exactly this reason. Recovering a number by parsing formatted output is how a gate ends up passing because the character "0" appeared in a traceback.

Quote anything that reaches a command, with `shlex.quote`. A branch name interpolated straight into a shell string is an injection the first time the workflow runs in CI.

```python
ran = use("shell", session.shell)(session).run(f"git diff {shlex.quote(ref)}", 60)
```

## What you may call

```python
from un import EXIT_FAILED, EXIT_OK, frontmatter, run_agent, use
from un.plugins.stock.workflows import expect, fanout, json_result, payload, script, submitted
```

- `use("fs", session.fs)(session)` - the file seam: `read(path)`, `read_bytes(path)`, `write(path, content)`, `glob(pattern, path)`, `grep(pattern, path, mode=...)`. Paths are strings.
- `use("ask", session.approval)(session, question, details, options, *, multi=False)` - ask the operator, where each option is a dict carrying at least a `label` and the `value` returned for it. Answers come back as a list of values, or `None` where the operator declined or nobody was there.

- `payload(session, prompt, *, fields=None, retries=1)` - one agent action on `session` itself, its answer handed in through `Submit` and returned as a `dict[str, str]`. A run that ends without an accepted `Submit` is asked again with a fresh seed, up to `retries` times. Returns `None` when no answer ever came. Raises `ValueError` if the session's `tools` leaves out `Submit`.
- `expect(session, agent="main", fields=None)` - seed the conversation `agent` will answer as, and get back the "How to answer" paragraph to put in its prompt.
- `submitted(session, agent="main")` - the answer that conversation handed in as a `dict[str, str]`, or `None`. Clears the seed either way.
- `fanout(session, agents, prompt, *, usable=None)` - several named subagents on one prompt, concurrently. Returns what answered and what never did. `usable` is your own validator; an answer it rejects counts as never given. **The names must be distinct**, because a forked session id is derived from the agent's name, so two concurrent runs of one agent would write one transcript from two threads. Several jobs for one agent means calling this once per job.
- `script(session, path, *args, timeout=180)` - a project script on un's own interpreter, through the session's shell seam. **`timeout` is keyword-only.** Passing it positionally puts an integer where an argument string belongs, and the command dies assembling itself.
- `json_result(ran)` - a `--json` command's data, or the reason there is none. Returns a pair and never raises.
- `run_agent(session, prompt, max_turns=None)` - one agent turn sequence when you want the raw `Reply` rather than a handed-in answer.
- `session.fork("<suffix>")` - a fresh conversation, same settings, no history.

## Running one

`un run <name> [args...]` from the command line, the `Workflow` tool from inside a session, or `/workflows:<name>` in the REPL. All three reach the same gated callable, so an operator rule written for one covers the others.

The operator is asked before a workflow runs, and can allow one permanently with `Workflow(<name>)` in `.un/permissions.toml`. A project at the dangerous tier allows it without asking.

**Run it end to end before calling it done.** A workflow's failures live in the places nothing else reaches: an argument that is keyword-only, a path that resolves differently under a real root, an agent that returns a shape the parser did not expect. The first real run is where those surface.
