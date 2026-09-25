# How to write a rule

A rule is text you wrote for the agent to read, injected into the conversation on a schedule you set. The body goes in whole, so rules are for text that is short and always relevant. Write a [skill](how-to-write-a-skill.md) instead when the instructions are long and only occasionally needed.

Rules are advisory. Nothing the agent does is checked against one. Use a [hook](how-to-write-a-hook.md) when you need enforcement.

## The smallest working rule

One `.md` file under `.un/rules/`, plus a table in `.un/config.toml`.

```markdown
---
trigger:
  event: TurnStart
---

Run the linter before claiming a task is finished.
```

```toml
[rules.linting]
enable = true
```

The name is the filename stem: `.un/rules/linting.md` is `[rules.linting]`. A rule with no table, or a table without `enable`, is off.

`trigger` is required. Rules are re-read on every turn, so an edit takes effect on the next one.

## Also: AGENTS.md

`AGENTS.md` at the project root is a rule with no header and no config entry. It is read once at session start and reaches the model exactly as written, fenced as `<project-instructions>`. Put standing project context there and use `.un/rules/` for anything needing a trigger or a selector.

## When it fires

`trigger` must carry at least one of three keys.

| Inside `trigger` | Fires |
|---|---|
| `event: SessionStart` | Once, in the system prompt |
| `event: TurnStart` | Once per prompt |
| `path: <glob>` | When a tool call touches a matching file, once per turn |
| `every: N` | On prompts 1, 1+N, 1+2N, so the moment beside it has to arrive more than once |

Name `path` alone and the moment is implied from it. Name `event` too and the event wins, with the path kept as a filter.

```yaml
---
trigger:
  path: "src/**/*.sql"
---

Every query in this directory goes through the parameter binder. Never format SQL with an f-string.
```

`path` matches a tool argument literally named `path`. `Bash(cat .env)` and `Glob(pattern=".env*")` do not match, because `Glob` spells a path `pattern` while `Grep` spells a regex the same way.

A path rule fires once per turn, not once per matching call, so two parallel `Read` calls under one glob produce one injection.

## Who it applies to

`provider`, `model` and `agent` sit flat beside `trigger`. Each is a glob or a comma-separated list. Leave one out and it has no opinion. Declared selectors narrow together.

```yaml
---
trigger:
  every: 3
model: "claude-sonnet-*, gpt-5*"
agent: main
---

Do not add dependencies. Check what is already in pyproject.toml first.
```

Selectors on `model` exist because model behaviour is not uniform: a reminder a weak model needs is context a strong one wastes.

`agent` names a [subagent](how-to-write-an-agent.md) by its frontmatter `name`. The main conversation is spelled `main`.

## How it arrives

`message_type` is `system` by default, `user` by opt-in.

System is the default because user-role content is forgeable by anything that writes into what the model reads, so a file the agent reads could otherwise spell a rule. Choose `user` only when the model needs the text where it is already looking, and understand you are giving that protection up.

| Trigger | `system` | `user` |
|---|---|---|
| `event: SessionStart` | The system prompt | Folded into the prompt |
| `event: TurnStart` | A system message after the prompt | Folded into the prompt |
| `path:` touched | A system message after the tool results | Appended to the tool result |

## Checking what is on

```
un rules
```

Reports three states apart, because each has a different fix:

```
enabled:
  house_style      TurnStart as system

present, not enabled - add [rules.<name>] with enable = true to .un/config.toml:
  draft            TurnStart as system

unreadable frontmatter:
  broken: no trigger in its frontmatter; name at least one of event, path, every
```

## When frontmatter is broken

Nothing is guessed silently and no rule is dropped. Every problem is collected into one sentence, the body still reaches the model, and the rendered rule is annotated:

```
## linting (unreadable frontmatter - unknown key 'cadence'; known: agent, message_type, model, provider, trigger; no trigger in its frontmatter; name at least one of event, path, every; applying every turn)
```

An unreadable dial always widens: an undeliverable event falls back to every turn, a path that could never be satisfied is dropped while the declared moment is kept, and a stride that could never advance is dropped the same way. `every: 3` beside `event: SessionStart` is that case, `SessionStart` arriving once at prompt 1 where the count never moves, so the stride is dropped and told while the rule still fires.

Only `SessionStart`, `TurnStart` and `PostToolUse` may be named in `trigger.event`. A rule naming any other event is put back on the turn and told.

`trigger.event` and `trigger.path` each take one value or a comma-separated list, so a rule can name several moments or several globs:

```yaml
trigger:
  event: SessionStart, TurnStart
```

The rule's text is delivered at each moment it names, routed through `message_type` per moment as a single one already is. A moment named twice counts once. The checks above apply to every entry and name the one that failed: a list carrying an undeliverable moment puts the whole rule back on the turn, a `path` declared beside a moment where no tool call has happened is dropped, naming that moment, and a stride beside a moment that cannot advance it is dropped for every moment in the list.
