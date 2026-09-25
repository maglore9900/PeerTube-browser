# How to write a tool

A tool hands the agent a capability. Drop a directory into `.un/tools/` with a `TOOL.md` manifest and it is registered: no distribution, no entry point, no install step, no key in `.un/config.toml`. An ordinary command-line program is already a tool, because un passes the model's `args` straight through as argv and maps nothing.

A [plugin](how-to-write-a-plugin.md) alters un's behaviour and can register a tool in Python. This is the other route, and it is the one to reach for first.

## The smallest working tool

```
.un/tools/wordcount/
├── TOOL.md
└── wordcount.py        chmod +x
```

```markdown
---
name: WordCount
description: >
  Count words in a file. `args` is argv: the first is a path, and `--lines` counts lines
  instead. Prints one number.
run: wordcount.py
---

Operator-facing notes. Optional, and un never reads them.
```

```python
#!/usr/bin/env python3
import sys
from pathlib import Path

path, *rest = sys.argv[1:]
text = Path(path).read_text()
print(len(text.splitlines()) if "--lines" in rest else len(text.split()))
```

```
chmod +x .un/tools/wordcount/wordcount.py
un tools
```

## The manifest

YAML frontmatter, the same format skills, commands and hooks use. Three keys, all required.

| Key | Holds |
|---|---|
| `name` | The agent-facing tool name. Any spelling you like |
| `description` | What the model reads to decide whether and how to call it |
| `run` | An executable file inside the tool's own directory |

The body is operator documentation and is optional, because a tool's payload is its script. If the tool needs packages or a running service, say so there.

The directory name is a path segment un composes, so it must be lowercase letters, digits and hyphens. The tool `name` is yours: un enforces no case convention and refuses only what it cannot function through, which is an empty name, the reserved `Tool`, and a name another tool already holds.

## The description is the whole contract

Every drop-in tool registers one fixed schema:

```python
{"type": "object",
 "properties": {"args": {"type": "array", "items": {"type": "string"}}}}
```

The model supplies `args`, un runs `[script, *args]`. Nothing in the manifest declares parameters, so `description` is the only thing teaching the model to drive the script. Write it as instructions: what the subcommands are, what the arguments mean, what comes back, and which failures are not failures. `un tools` prints it, and the model reads it on every turn.

## What un runs

`subprocess.run` with argv as a list and `shell=False`, so nothing is parsed by a shell. `cwd` is the session directory, the environment comes from `child_env()` (a fixed allowlist, not your shell's environment), and the bound is 120 seconds.

The return is stdout and stderr rstripped and joined with a newline, `[no output]` when a zero exit printed nothing, and `[exit status N]` appended on a non-zero exit. That last line is why a script should exit non-zero when it fails: a silent failure would otherwise read to the model as having worked.

**un never imports a tool.** It execs the file directly rather than choosing an interpreter, so a tool may be Python, bash or anything with a shebang and an executable bit. un's own environment is unaffected by what the tool needs.

`run` must resolve to a file inside the tool's own directory. An absolute path or an `..` escape leaves that directory and is refused.

## Refusals

A broken directory is one finding, not a session that will not start. Discovery collects refusals and un starts anyway.

| Refusal | Cause |
|---|---|
| `the directory name must be lowercase letters, digits and hyphens` | The directory, not the tool name |
| `unparseable frontmatter: <error>` | The parser's own reason |
| `no <key> in its frontmatter` | A required key absent, or blank |
| `the tool name 'Tool' is reserved` | It is the permission rule claiming a whole tool |
| `a tool named 'X' is already registered` | Two directories, one name |
| `run must name a file inside <dir>/` | Containment failed, or the file is not there |
| `'X' is not executable; chmod +x it` | No executable bit |
| `TOOL.md could not be read: <reason>` | The read failed |

A directory with no `TOOL.md` is ignored rather than refused, since not everything under `.un/tools/` claims to be a tool.

## Checking what registered

```
un tools
```

Re-scans and prints what registered and what was refused, with the reason. It is the only channel: discovery runs at import, where nothing is listening.

```
tools:
  WordCount        Count words in a file ...

not registered:
  scraper: no description in its frontmatter
```

`/reload` re-scans mid-session and reports new tools beside its `commands:` line, so a tool dropped in while un is running costs no restart.

## Permissions

Registration makes a tool callable. The permission table decides whether a call runs, and a drop-in gets the answer un gives a stranger: under the default `strict` tier a tool nobody has written a rule for is asked about on first call. Dropping a directory in is not by itself a decision to let it run unprompted.

```toml
# .un/permissions.toml
allow = ["Tool(WordCount)"]
```

`dangerous_allow = true` allows instead of asking, and a dropped-in tool then executes unprompted along with everything else unlisted.

Unlike `.un/hooks/` and `.un/agents/`, `.un/tools/` is not write-protected, so the agent can maintain the tools it works with. A tool you want protected needs a `Write(...)` rule of its own.

## When to write a plugin instead

A drop-in tool cannot replace a service, gate another tool's call, or add a CLI verb. It runs as a subprocess and only when the model calls it. If you need code running inside un's process, that is a [plugin](how-to-write-a-plugin.md), and its `@tool` decorator registers a tool with a schema of your own design rather than the fixed `args` array, or with a function of the session that returns the schema, or `None` to hide the tool from that conversation.
