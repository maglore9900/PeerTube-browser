# How to write a hook

A hook is a script un runs when something happens in a session: a turn starts, a prompt arrives, a tool is about to be called. Unlike a [rule](how-to-write-a-rule.md), a hook acts. It can refuse a tool call, add to a prompt, rewrite a tool result, or add text to the conversation — and by default it does none of those, because reaching the model is something a hook opts into with `message_type`.

Two files: a markdown file declaring the hook, and the script it runs.

## The smallest working hook

```markdown
---
name: deny-log
description: Append every refused tool call to a log.
trigger:
  event: PreToolUse
run: deny-log.py
---
Notes for whoever maintains this. The body is not used.
```

```python
#!/usr/bin/env python3
"""Refuse any Bash call touching the production config."""
import json, sys

payload = json.load(sys.stdin)
args = payload.get("args", {})
if payload["name"] == "Bash" and "prod.env" in args.get("command", ""):
    print("prod.env is off limits", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
```

```
chmod +x .un/hooks/deny-log.py
```

```toml
[hooks.deny-log]
enable = true
```

The heading is the frontmatter `name`. `enable` is the only key the table accepts. A hook with no table is known but does not fire.

## Exit codes

un hands the script a JSON object on stdin and reads its exit code.

| Exit | Means | stdout | stderr |
|---|---|---|---|
| `0` | Ran fine | The hook's return value, but only if you declared a `message_type` | Shown to you |
| `2` | `PreToolUse` only: deny the call | Ignored | The reason, and the model reads it |
| `3` | `PreToolUse` only: ask the operator | Ignored | The reason |
| Anything else | The script failed | Discarded | Reported to you |

A hook fails open. A broken script, a crash, or a timeout at 120 seconds all let the tool call proceed. A `PreToolUse` hook can only tighten what the permission table already decided.

Exit 2 and 3 are verdicts only on `PreToolUse`. On any other event they are ordinary failures.

## Events

**Your script's stdout reaches the model only if the file declares a `message_type`.** Leave the key out — which is the default, and right for most hooks — and un drops whatever you print. A guard that checks something, a reporter that pings a pane, a logger: none of them has anything to say to the model, and none of them should have to remember to stay quiet. The column below is what the key buys you.

| Event | A return means, once you have declared a `message_type` |
|---|---|
| `SessionStart` | On launch, any text appended to the system prompt |
| `UserPromptSubmit` | Appended to the user's prompt; you add to it, you cannot take it away |
| `PreToolUse` | Exit code decides; stdout ignored, and `message_type` is refused here |
| `PostToolUse` | Replaces the tool's result text |
| `TurnStart` | Text added as an operator system message |
| `ToolResults` | The same, once per tool batch |
| `Turn` | Ignored; fires after each assistant reply |
| `TurnEnd` | Ignored; fires once when the turn is over and un is ready for input |
| `ToolEnd` | Ignored; fires once per attempted tool call |
| `OperatorWaitStart` | Ignored; fires when un stops and waits on you |
| `OperatorWaitEnd` | Ignored; fires when that wait ends |
| `SessionEnd` | Ignored; fires once when the session is over |

`Turn`, `TurnEnd` and `SessionEnd` are three different moments. A turn that uses tools produces several assistant replies and so several `Turn` fires; `TurnEnd` fires once, when un has finished and is waiting for you to type; `SessionEnd` fires once for the whole session, when un is exiting and will not be waiting for anything. A conversation of ten turns fires ten `TurnEnd`s and one `SessionEnd`, last.

`SessionEnd` is what you hang work on that should run after un has gone - clearing a status pane, releasing a lock, posting a summary. It carries the exit code the session ended on, so you can tell a clean exit from a Ctrl-C or a provider fault. It fires for an interactive session, a one-shot `un chat`, a `un resume`, and a `un run` workflow; it does NOT fire for a command that opens no session at all, like `un plugins`, nor for a session that was never started - `un resume` against a transcript that does not exist ends nothing, having begun nothing.

`OperatorWaitStart` fires in the two places un stops for a person: an approval prompt, and the `AskUser` tool. `OperatorWaitEnd` always follows it - whether you answered, declined, dismissed the question, or the prompt itself broke. Returns are ignored on both, so a hook cannot answer on your behalf.

un listens to `OperatorWaitEnd` itself, which it does for no other event: a wait that ended in an attended session zeroes the `max_turns` count, so answering a question gives the run a fresh budget. Headless, the pair still fires - a registered approver can refuse with nobody there - and nothing is zeroed, so a headless bound is absolute. Your own listener sees the event either way and changes none of this.

`ToolResults` is where a line you type mid-turn reaches the model, delivered by the REPL's own listener. Your listener is called for the same batch; both returns are appended, in load order.

## What is on stdin

Seven keys are always there: `event`, `agent` (the main conversation reads `""`), `cwd`, `provider`, `model`, `session_id`, `transcript_path`. Each event adds its own:

| Event | Adds |
|---|---|
| `UserPromptSubmit` | `value` - the prompt as it stands |
| `PreToolUse` | `name`, `args` - the tool and its arguments |
| `PostToolUse` | `value`, `name`, `args` |
| `ToolResults` | `calls` - the whole tool batch |
| `ToolEnd` | `call` - one attempted call with its verdict and outcome |
| `TurnEnd` | `interrupted` - true when the turn ended on a Ctrl-C |
| `SessionEnd` | `code` - the exit code the session ended on: `0` clean, `1` a fault, `3` a turn bound reached, `130` a Ctrl-C - and any other number a `un run` workflow returned, since those are yours to choose |
| `OperatorWaitStart` | `name` and `reason` at an approval prompt, `question` at an `AskUser` call |
| `OperatorWaitEnd` | `name` at an approval prompt, nothing at an `AskUser` call |

`session_id` names the conversation and `transcript_path` is where its record is written, whether or not that file exists yet. Together they are what lets an external tracker match what it is told against what un wrote.

## What your script can see

Your script does not inherit the environment un was launched from. un builds it from an allowlist — `PATH`, `HOME`, `USER`, `SHELL`, `LANG`, `TERM`, `TMPDIR`, `TZ`, locale, and proxy settings — so a variable you exported into your shell is not there, and neither is un's API key. That is deliberate and it is `docs/adr/0007-child-processes-get-a-built-environment.md`.

Your script is spawned as a direct child of un, so on Linux it can still read what un was launched with from `/proc/$PPID/environ` if it genuinely needs a value scoped to your terminal — a multiplexer pane id, for instance. There is no frontmatter key for this and there does not need to be. `.un/hooks/herdr/herdr.py` in the un repository is a worked example.

## Frontmatter reference

Four keys required, five optional.

| Key | Required | Holds |
|---|---|---|
| `name` | Yes | The registry key and the `[hooks.<name>]` table key |
| `description` | Yes | One line, printed by `un hooks` |
| `trigger` | Yes | A mapping naming exactly one of `event`, `path` (globs) or `every` (a stride). `event` and `path` each take one value or a comma-separated list |
| `run` | Yes | A command line; the first word is an executable file, the rest is argv |
| `provider`, `model`, `agent` | No | Globs narrowing which conversations it fires for |
| `message_type` | No | `system` or `user`. Leave it out and your script's stdout goes NOWHERE near the model — this key is how you opt in |
| `visibility` | No | `false` takes the hook's routine lines off your screen |

`event`, `path` and `every` are three ways of naming the same thing — when the hook fires — so name ONE. A trigger naming two is refused, and the refusal quotes back the keys you wrote.

Naming one KIND is not the same as naming one value. `event` and `path` each take a comma-separated list, so one hook covers as many moments or as many globs as it needs:

```yaml
trigger:
  event: SessionStart, TurnStart, TurnEnd
```

That is one hook and one `[hooks.<name>]` entry, registered on all three moments and listed by `un hooks` as a single row. The script is told which moment it fired on in the payload's `event`, so one file can serve all of them. A moment named twice is registered once. If any name in the list is not an event un has, the whole file is refused and the refusal names that one moment — the valid moments are not quietly registered without it. The same reading applies to `message_type`: every moment you name has to be able to deliver it, or the file is refused naming the one that cannot.

Want a hook that fires at a particular moment but only for certain files? Name the moment, and match the glob in your script: `PreToolUse` and `PostToolUse` hand it `args`, `ToolResults` hands it `calls`. Name the `path` alone instead and un does the matching for you, at the moment a path implies.

## Where `run` can point

`run` is resolved from `.un/hooks/` whatever depth the declaring file sits at, and must land inside the project root. A hook can therefore run a script filed beside the thing it guards, keeping one copy of it.

```
.un/
├── hooks/
│   ├── deny-log.md        run: deny-log.py
│   ├── deny-log.py        chmod +x
│   ├── audit/
│   │   ├── guard.md       run: audit/guard.sh
│   │   └── guard.sh
│   └── auditor.md         run: ../skills/wiki/hooks/auditor_bash_guard.sh
└── skills/wiki/hooks/
    └── auditor_bash_guard.sh
```

`run` may also lead with one of five location tokens: `@project_root`, `@commands`, `@hooks`, `@skills`, `@tools`. **The value has to be quoted**, because YAML reads a leading `@` as a reserved indicator.

```yaml
run: "@project_root/scripts/check.sh --strict"
```

Words after the first are handed to the script as argv, so one guard can be parameterised across several hooks.

## Selectors

Leave `agent` out and the hook fires for every conversation, [subagents](how-to-write-an-agent.md) included. Naming one confines it. The main conversation is spelled `main`.

```yaml
agent: [main, researcher]     # both
agent: researcher             # a bare name is a one-item list
agent: main, researcher       # the same, unbracketed
```

`provider` and `model` narrow the same way as globs: `model: "claude-sonnet-*"`.

## How often it fires

Per call. A [rule](how-to-write-a-rule.md) triggered on the same path fires once per turn, but suppressing the second of two matching calls would hide work from a guard.

## What you will see

One line on your terminal before each spawn, `hook: <name>`, and a second carrying stderr if the script wrote any. `visibility: false` removes both, and removes nothing else: a hook that fails still reports, because a guard that fails open and goes quiet is one you believe is running and is not.

Every fire leaves a row in the session record naming its outcome: `ok`, `deny`, `ask`, `failed`, `timeout` or `spawn-failed`. A hook a selector excluded leaves no row, because it never spawns.

## Checking what is registered

```
un hooks
```

Reports four things apart: enabled, present but not enabled, refused with the reason, and any hook whose `agent` names a subagent that does not exist. `/reload` re-scans mid-session.

`un hooks` prints `declared -> registered` when the two differ. A hook does not always register on the event it named: asking for `message_type: user` on `TurnStart` registers it on `UserPromptSubmit`, and a `path`-only trigger asking for `system` registers on `ToolResults`. A hook that declares no `message_type` is never moved — it has no text to place, so it stays where you put it.

## Write protection

`.un/hooks/**` is denied to the agent's write tools at every permission tier, since a hook executes with nothing downstream asking you first. You edit these files by hand.

A `run` pointing outside `.un/hooks/` reaches a script whose protection comes from whatever other glob in `.un/permissions.toml` matches it, so a hook script filed with its skill is writable by the agent until one does.
