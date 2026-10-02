# How to write an agent

A subagent is a second conversation with its own system prompt, its own tool set and its own transcript. The main agent delegates to it through the `Task` tool and gets back one result. Use one to keep a large, self-contained job out of the main conversation's context, or to run a job on a cheaper model.

## The smallest working agent

One `.md` file under `.un/agents/`, plus a table in `.un/config.toml`.

```markdown
---
name: researcher
description: Searches the codebase and reports findings. Read-only.
tools: [Read, Grep, Glob]
---
You are a research agent. Read widely, edit nothing, report what you found.

Answer with file paths and line numbers. Say what you did not find as well as what you did.
```

```toml
[agents.researcher]
enable = true
```

The body is the system prompt. `name`, `description` and a non-empty body are required.

`name` must be lowercase letters, digits and hyphens, because it becomes the forked session's id and so its transcript filename. `main` is reserved and refused, since hooks and rules spell the main conversation `main`.

`description` is what the main agent reads when it chooses between agents. Write it as selection criteria, not as a title.

`subagent-example.md`, beside this file, is a commented-out definition with every key annotated. Copy it into `.un/agents/<name>.md` and uncomment what you need. It cannot live in `.un/agents/` itself: discovery reads that tree recursively and would refuse a commented-out file for having no frontmatter.

## Optional frontmatter

`tools`, `provider`, `model`, `effort` and `max_turns`. Any other key is refused by name.
An omitted `max_turns` takes the one `[providers.<name>]` gives the profile this agent
names, and the session's own where that profile names none.

```markdown
---
name: drafter
description: Drafts release notes from a diff. Writes to docs/ only.
tools: Read, Grep, Write
provider: ollama
model: qwen3
effort: low
max_turns: 20
---
```

`provider` names a `[providers.<name>]` entry in `.un/config.toml`, so one word selects an endpoint. `model` is what gets sent there, `effort` is how hard it thinks, `max_turns` is how many provider calls its loop may make with no human interaction between them. All four are independent, and anything left out is inherited: from the named profile where you named one, from the main agent otherwise. `effort: low` with no `provider` keeps the main agent's endpoint and just thinks less, which is what makes a background pass cheap.

An agent inherits whether anyone is there to ask. Started from an interactive session it is attended, so an `AskUser` of its own reaches you and answering gives that agent a fresh budget; started from a piped or one-shot run it is headless and `max_turns` is an absolute ceiling on its work.

`provider`, `effort` and `max_turns` are checked when the file loads, so a bad one is refused and listed by `un agents`. `model` is checked against nothing, because only the endpoint can judge a model name. A wrong one appears as the endpoint's error on the agent's first turn. When a subagent fails and the message is about a model, that is the key to look at.

## The tool list

`tools:` is the whole grant. Omit it, or write an empty list, and the agent gets no tools at all.

```yaml
tools: [Read, Grep]     # bracketed
tools: Read, Grep       # the same, unbracketed
tools: Read             # a bare name is a one-item list
tools: []               # no tools at all
```

The list acts on the schema sent to the model, so the agent is shown only what it may call and spends no turn discovering the rest. Everything that passes the filter is still judged by the permission table, the same as the main agent's calls.

List `Task` and the agent can delegate to other agents in turn. `Task(researcher, drafter)` limits it to the agents named. Depth is bounded: the main agent is depth 0, and an agent at `[agents].max_task_depth` (default 3) in `.un/config.toml` is not given `Task` whatever it lists. `[agents].max_running` (default 20) caps how many subagents run at once, and a spawn past it is refused with a message the calling agent reads. The self-learning agents never get `Task`.

Naming a tool that does not exist leaves the agent registered with what is real and reports the rest:

```
tools asked for and not registered:
  researcher: no tool named NoSuchTool; researcher runs without it
```

## What a spawn actually does

The child is a fork of the parent session carrying its settings and none of its history. Six things are replaced: the system prompt (your body), the tool set, the output sink (off, so the child's tool traffic stays out of your terminal), the provider profile, the agent identity, and the approval answerer.

The child receives the project's rules and skills index against its own prompt, so a rule with `agent: researcher` reaches it and one with `agent: main` does not.

Its transcript lands at `.un/sessions/<parent-id>-<agent-name>.jsonl`. What it spends is added back to the parent's token count.

## When one fails

Every failure comes back to the main agent as text it can read and work around, including a denial inside the child. Because the child's own output sink is off, a failure that is not a denial is also reported to you on the error channel. A denial goes only to the model.

## Layout and naming

Discovery recurses, so directories are yours to arrange:

```
.un/agents/
└── research/
    └── researcher.md
```

`.un/agents/research/researcher.md` defines the agent called `researcher`. The filename is not the identity, the frontmatter `name` is. Where two files claim one name the second is refused and told which file holds it.

## Checking what is on

```
un agents
```

Three states, reported apart:

```
enabled:
  researcher       Searches the codebase and reports findings. Read-only.

present, not enabled - add [agents.<name>] with enable = true to .un/config.toml:
  drafter          Drafts release notes from a diff.

not registered:
  bad.md: no description in its frontmatter
```

A refusal is filed under the file's path rather than the name it claimed, since a file that did not parse has no trusted name.

`/reload` re-scans mid-session and an edited definition takes effect.

## The seeded agents

`un install` writes `.un/agents/learning/detector.md`, `.un/agents/learning/admitter.md`, `.un/agents/learning/implementor.md`, `.un/agents/learning/accuracy-auditor.md`, `.un/agents/learning/memory-editor.md` and `.un/agents/learning/amendment-applier.md`. They are the self-learning loop's own agents and run without a config table while `self_learning` is true. They are live files you tune, not templates. `un agents` still lists them as present and off, because that command reads the config table alone. The learning passes run the first five; `/apply-amendment` dispatches `amendment-applier` on the one plan you name.

## Write protection

`.un/agents/**` is denied to the agent's write tools at every permission tier. You edit these files by hand.
