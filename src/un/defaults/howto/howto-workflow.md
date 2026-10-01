# How to write a workflow

A workflow is Python that drives one or more agents through several turns and decides what happens next from a real outcome: an exit code, a parsed result, a file that is or is not there. The agent cannot talk its way past an `if` on a return code, which is the reason to write one instead of a long prompt. Most of the file is ordinary Python; an agent is asked only where judgement is unavoidable.

Write a [skill](how-to-write-a-skill.md) when you want the agent to follow a procedure, and a workflow when a step must not be skippable or when the next step depends on a result you can check in code.

There are two ways to write one. The short way is to have the agent write it with the `workflow-authoring` skill. The long way is to write it by hand. Both end in the same file, and you enable and run it the same way.

## The short way: have the agent write it

`un install` writes the skill to `.un/skills/workflow-authoring/SKILL.md`, but like every skill it is off until you enable it:

```toml
# .un/config.toml
[skills.workflow-authoring]
enable = true
```

Then describe the workflow to the agent. Say what the gate is (the command whose exit code decides the next step), where judgement is needed, and what the run should leave behind:

```
Using the workflow-authoring skill, write a workflow called tests-green. It runs
`pytest -q`, and while the suite fails it hands the failure output to the agent
to fix, up to three attempts. It exits 0 when the suite passes and 1 otherwise.
```

The agent writes `.un/workflows/<name>/<name>.py`, plus any prompt files beside it. It cannot enable the workflow, because `.un/config.toml` is write-protected. That step is yours:

```toml
[workflows.tests-green]
enable = true
```

Run `/reload`, then `/workflows` to confirm it registered, then `/workflows:tests-green`. Before you run it, read what the agent wrote and check three things:

- Every command the workflow runs is fixed in the file or quoted with `shlex.quote`, and no argument reaches a shell unquoted.
- Each gate branches on `ran.code`, never on text in `ran.output`.
- `run` returns an integer on every path.

The rest of this page explains what a workflow file contains, so you can judge what the agent produced.

## The long way: write it by hand

### The smallest working workflow

```
.un/workflows/tests-green/
└── tests-green.py
```

```python
"""---
name: tests-green
description: Run the test suite, hand failures to the agent, and stop when it passes or after three attempts.
---
"""

from un import EXIT_FAILED, EXIT_OK, run_agent, use

COMMAND = "pytest -q"
ATTEMPTS = 3


def run(session, *argv) -> int:
    shell = use("shell", session.shell)(session)
    for attempt in range(ATTEMPTS):
        ran = shell.run(COMMAND, 600)
        if ran.code == 0:
            print(f"green after {attempt} fix attempt(s)")
            return EXIT_OK
        run_agent(session, f"`{COMMAND}` failed. Make it pass without weakening a test.\n\n{ran.output[-4000:]}")
    session.report("tests-green", f"still failing after {ATTEMPTS} attempts")
    return EXIT_FAILED
```

```toml
# .un/config.toml
[workflows.tests-green]
enable = true
```

```
un workflows
un run tests-green
```

### The header

The module docstring opens with `---` and carries a YAML header. Two keys are required.

| Key | Holds |
|---|---|
| `name` | What the workflow is called: `un run <name>`, `/workflows:<name>`, `[workflows.<name>]`. Lowercase letters, digits and hyphens |
| `description` | One sentence that `un workflows` shows the operator |

The filename is not consulted, so a directory is only somewhere to keep a workflow's files. A `.py` under `.un/workflows/` with no header is not a workflow and is passed over in silence, so helper modules can sit beside one.

### The entry point

A top-level `def run(session, *argv) -> int`. One nested in an `if` or a class does not count. Its return value is the exit code, unaltered. Return an `int` on every path: anything else is reported and turned into a failure, because `SystemExit(None)` would otherwise exit 0.

What `argv` holds depends on who launched the workflow:

| Launched by | `argv` |
|---|---|
| `un run <name> a b c` | `("a", "b", "c")` |
| `/workflows:<name> a b c` in the REPL | `("a b c",)`: the rest of the line as one string, or `()` when it is blank |
| The `Workflow` tool | the model's `args` list |

A workflow that takes several arguments from the REPL splits the string itself. Treat `argv` as untrusted input, because the model can supply it through the `Workflow` tool.

### How the loader treats the file

`src/un/plugins/stock/workflows.py` finds, registers, gates and launches the file. Discovery parses the file and never imports it, so nothing in the module body runs at scan time.

1. It walks `.un/workflows/**/*.py`.
2. It reads the header out of the module docstring and checks for a top-level `run`.
3. It registers `workflow:<name>`. When `[workflows.<name>]` has `enable = true` it also registers `/workflows:<name>`. Otherwise the workflow is listed as disabled and refuses every launch.
4. On launch it puts the launch to the permission gate before importing the module, so a refused launch runs none of your code.
5. It imports the module, calls `run(session, *argv)`, and returns the code. An exception out of the module is reported and becomes exit 1.

The module is imported fresh on every launch, so an edit takes effect on the next run. A new, renamed or re-enabled workflow reaches a running session on `/reload`.

The loader does not pass the project root (use `session.root`), and it does not put your directory on `sys.path`. A sibling module is loaded by path with `importlib.util.spec_from_file_location`.

### Refusals

`un workflows` and `/workflows` re-scan and list three states separately: registered, disabled (with the config line that enables it), and refused (with the reason).

| Refusal | Cause |
|---|---|
| `... could not be read: it is not UTF-8 text` | The file's encoding |
| `it does not parse: <msg> (line N)` | A Python syntax error |
| `its header does not parse: <error>` | The docstring opens with `---` but the YAML is broken |
| `no name in its header`, `no description in its header` | A required key is absent or blank |
| `the name 'X' must be lowercase letters, digits and hyphens` | The header's `name` |
| `a workflow named 'X' is already registered` | Two files, one name |
| `no top-level def run in the module` | `run` is missing or nested |

## What `un.plugins.stock.workflows` gives you

Everything a workflow does goes through un: an agent turn through `run_agent` or a subagent service, a command through the shell service, a file through the fs service. That routing puts each turn in the session record, fires the hooks around it, and adds its cost to the session's spend. The stock workflows plugin adds the helpers the existing workflows needed. A workflow imports them directly:

```python
from un import EXIT_FAILED, EXIT_OK, frontmatter, run_agent, use
from un.core import MAIN, UN_DIR, project_root
from un.plugins.stock.workflows import expect, fanout, json_result, launch, payload, script, submitted
```

Plugins must not import other plugins, and workflows are an exception. A workflow file only loads when the workflows plugin has already registered it, so the import finds a module that is already loaded and registers nothing new.

### The helpers

| Name | Signature | What it does |
|---|---|---|
| `payload` | `payload(session, prompt, *, fields=None, retries=1)` | Runs one agent action on `session` and returns the answer it handed in through `Submit` as a `dict[str, str]`. A run that ends without an accepted `Submit` is asked again, up to `retries` times. Returns `None` if no answer ever came. Raises `ValueError` if `session.tools` excludes `Submit` |
| `expect` | `expect(session, agent="main", fields=None)` | Prepares the conversation `agent` will answer in to accept a `Submit`, and returns the "How to answer" paragraph to append to that agent's prompt |
| `submitted` | `submitted(session, agent="main")` | Returns what that conversation handed in, or `None`. Clears the seed either way, so call it once per `expect` |
| `fanout` | `fanout(session, agents, prompt, *, usable=None, workers=None, emit=None)` | Runs several named subagents on one prompt concurrently. Returns `(answers, missing)`. An answer `usable` rejects is re-asked once, alone, and then counted as missing |
| `script` | `script(session, path, *args, timeout=180)` | Runs a Python script on un's own interpreter through the session's shell service. Returns the `Ran` with a non-zero code included. `timeout` is keyword-only |
| `json_result` | `json_result(ran)` | Parses a `--json` command's output into `(data, None)`, or returns `({}, reason)`. Never raises |
| `launch` | `launch(session=session, name="other", args=[...])` | Runs another workflow on a fork of the session, bounded by `MAX_DEPTH`. Returns its printed output and `[exit status N]` as text. Printed output over 30000 characters comes back as its first 15000 and last 15000 with one `[truncated: ...]` line between them, and `[exit status N]` stays the last line. Every failure comes back as text rather than as an exception |

A `Ran` has two fields: `code` (int) and `output` (stdout and stderr joined). `output` is never cut, so `script` and `json_result` see a command's whole output however long it is.

`launch` is the `Workflow` tool itself, so a parent workflow gets the same capped text the model would. To act on another workflow's result, branch on its exit status. To read large data, run the command or script yourself through `script` and parse it with `json_result`.

### Constants and state

| Name | What it is |
|---|---|
| `WORKFLOWS` | `Path(".un/workflows")`, relative to the project root |
| `MAX_DEPTH` | `3`. How deeply workflows may launch workflows. A subagent spawn counts toward the same limit |
| `SECTION`, `ENABLE` | `"workflows"` and `"enable"`: the config table and key that switch a workflow on |
| `REFUSED` | The last scan's refusals: a file's path mapped to the reason. Read it; never write it |
| `DISABLED` | The last scan's workflows that are declared but not enabled: a name mapped to its file. Read it; never write it |
| `discover(root=None)` | Re-scans `.un/workflows/`. Returns `(registered, refused)`. `/reload` already calls it, so a workflow rarely needs to |

### Not for workflows

The module's other names belong to the plugin's own surfaces: `_launch`, `_slash_launch`, `_file_workflow`, `_declared`, `_reason`, `_listing`, `_ask`, `_SEEDS`, `submit` (the `Submit` tool itself), `rescan`, and the command and slash services. Calling them bypasses the launch gate or the seed bookkeeping.

### Getting an answer back from an agent

Do not parse structure out of an agent's reply. Have the agent hand its answer in through the `Submit` tool, with one argument per field:

```python
answer = payload(session, "Review the diff below and give a verdict.\n\n" + diff, fields=["verdict", "findings"])
if answer is None:
    return EXIT_FAILED
if answer["verdict"] != "pass":
    ...
```

For a subagent, prepare the conversation it will answer in, run it, and read the answer back:

```python
how = expect(session, "reviewer", ["verdict", "findings"])
use("agents", "run")(session, "reviewer", f"{brief}\n\n{how}")
answer = submitted(session, "reviewer")
```

A `Submit` call that does not match the declared fields is rejected inside the agent's own conversation, and the agent corrects it there. An accepted call ends that agent's turn. A conversation nobody prepared is not shown `Submit`.

### Several agents at once

```python
answers, missing = fanout(session, ["security-auditor", "style-auditor"], brief, usable=lambda text: "VERDICT" in text)
if missing:
    session.report("review", f"no usable answer from {', '.join(missing)}")
    return EXIT_FAILED
```

The names must be distinct, because each forked session's id comes from its agent's name. To give one agent several jobs, call `fanout` once per job.

## The rest of the file's surface

These come from `un` itself, not from the workflows plugin:

| Need | Call |
|---|---|
| A raw agent turn | `run_agent(session, prompt)` |
| One subagent | `use("agents", "run")(session, name, prompt)` |
| Any command | `use("shell", session.shell)(session).run(line, timeout)` |
| Read or write a file | `fs = use("fs", session.fs)(session)`, then `fs.read(path)`, `fs.write(path, text)`, `fs.glob(pattern, path)`, `fs.grep(pattern, path)` |
| Ask the operator | `use("ask", session.approval)(session, question, details, options, multi=False)` |
| A conversation with no history | `session.fork("<suffix>")` |
| Report a failure | `session.report("<source>", text)` |
| A YAML header | `from un import frontmatter` |
| The project root | `session.root`, or `project_root()` from `un.core` |

`fs` paths are strings. A relative path resolves against `session.cwd`, which is neither your workflow's directory nor necessarily the project root, so build paths from `session.root` or `Path(__file__).parent`. `fs.write` creates parent directories and locks the target.

Each option passed to `ask` is a dict with all four keys, `label`, `value`, `description` and `preview`, because the adapters read every one of them; pass `""` for the ones you do not use. The call returns a list of the chosen values, or `None` if the operator dismissed the question. When no one can answer, it raises instead. A headless run raises `ValueError`, and an approval mode with no ask adapter (such as `yes`) makes `use` raise `LookupError`. A workflow that may run unattended catches both.

## What the permission table does and does not see

Launching the workflow is gated: the operator is asked before a file workflow runs. To allow one permanently, add a rule:

```toml
# .un/permissions.toml
allow = ["Workflow(tests-green)"]
```

What runs inside `run` is not gated. Commands through the shell service and writes through the fs service are plain Python calls, and no permission rule applies to them. Only the tool calls of the agents the workflow drives go through the permission table. So:

- Never build a command from `argv` or from agent output without `shlex.quote`. The model can launch a workflow through the `Workflow` tool with arguments of its choosing.
- If the workflow must not change something, build that in. Ask the agent for content, write it yourself through `fs`, and give the agent no write tools. A prompt telling the agent not to write does not stop it.

## Output

`print` is progress for the operator, and `session.report` is for failures. From `un run`, both go straight to the terminal. From `/workflows:<name>` or the `Workflow` tool, both are captured and shown when the workflow ends, followed by `[exit status N]`. The tool hands that text to the model, cut to its first 15000 and last 15000 characters around a `[truncated: ...]` line when it runs past 30000, with `[exit status N]` kept after the cut. `/workflows:<name>` shows it whole.

An output file is a record. Name it for what produced it and the scope it ran over, and never overwrite an earlier one.

## Running one

| From | Form |
|---|---|
| The REPL | `/workflows:<name> <rest of line>` |
| The command line | `un run <name> [args...]` |
| The agent | the `Workflow` tool, `{"name": "<name>", "args": [...]}` |

All three reach the same gated callable. Run it end to end before calling it done: a keyword-only argument passed positionally, a path that resolves somewhere else, or an agent answer of an unexpected shape only shows up on a real run.

## Shipping one in a plugin

A [plugin](how-to-write-a-plugin.md) can register `@service("workflow:<name>")` with the same `run(session, *argv) -> int` signature. `un run` and the `Workflow` tool find it, but it gets no `/workflows:<name>` entry, is not listed by `un workflows`, and its launch is not put to the permission gate. Use a file under `.un/workflows/` unless you are distributing the workflow.
