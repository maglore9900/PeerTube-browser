# unstable_number

`un` is a plugin-first agent harness for the command line.

```
$ un chat "what does this repo do?" --provider openai
$ un run tdd "a function slugify(text) that lowercases and hyphenates"
```

## Features

- **`tool`**: many, all offered to the model. Has a name and a JSON schema the model sees.
- **`hook`**: many, all fire on an event. Invisible to the model, and the only veto point.
- **`commands`**: slash commands, requires yaml header with description.
- **`skills`**: agent skills, just like skills everywhere, requires yaml header with name and description.
- **`memory`**: where memories are stored. you can create your own and preseed it, but rules is a better place for that.
- **`rules`**: rules are md files injected into session state to keep agents doing what you want. unlike claude code, you can set an interval timer. See rules below.
- **`plugins`**: plugins are where you can change how the un harness functions. See plugins below.

### Permissions
<add a simple description of the default behavior regarding permissions. do not talk about the permissions talk about what is allowed and blocked. I will later add the why.>

### Workflows

Workflows are python scripts that drive the agent with gates it cannot deviate from: the script branches on a real command's exit code, so the verdict comes from the tool rather than from the model's account of it.

Write one as a `.py` anywhere under `.un/workflows/`, declaring itself in a YAML header in its module docstring and defining a top-level `def run(session, *argv) -> int`. The header's `name` is what the workflow is called, so a file may sit in its own subdirectory beside the prompts it ships with. un reads both by PARSING the file and imports it only once a launch has been approved, so the script never runs at scan time. Add `[workflows.<name>]` with `enable = true` to `.un/config.toml` to turn it on. `un install` scaffolds a `workflow-authoring` skill with the full contract.

un ships no workflow of its own — the capability is stock, the workflows are aftermarket.

## Runtime and Options

`un` is installed into the project environment, not onto your PATH. 

```
pixi run un repl         # or: pixi shell, then just `un repl`
```

```
un repl                     the interactive prompt loop
un chat                     the same loop: one session, many turns, one process
un chat PROMPT              one-shot. Prints the session id to stderr so you can resume.
un resume SESSION_ID PROMPT continue a saved session
un run WORKFLOW [ARGS...]   run a workflow; its exit code becomes un's
un workflows                what .un/workflows/ registered, and what was refused
un plugins                  every registered extension, first- and third-party alike
```

Assistant text streams as it is generated, and tool calls appear as they happen. Stdout carries the model's answer alone. Everything else goes to stderr: tool progress, the session id, the `--stats` usage line, an approval question, and in the REPL the prompt, the status lines and slash-command output. A one-shot run therefore redirects straight into a file, and the progress still shows on the terminal while it runs:

```
un chat 'summarise this repo' > summary.txt
```

`un chat` exit codes:

| code | meaning |
|---|---|
| `0` | it answered |
| `1` | provider fault |
| `2` | usage error |
| `3` | hit `--max-turns` with tool calls still outstanding |

Flags on all of them: `--provider`, `--model`, `--effort`, `--fs`, `--shell`, `--approval`, `--max-turns`, `--stats`, `--plugin`, `--disable-plugin`. All but `--effort` and `--max-turns` can be set once in `.un/config.toml` instead, described under Launch configuration below; both of those are profile keys, written under `[providers.<name>]`.

`--max-turns` bounds provider calls made with **no human interaction between them**. Submitting a prompt, answering an approval or an `AskUser`, and having a line you typed mid-turn picked up each start a fresh budget. A headless run - piped input, `un chat 'PROMPT'`, a workflow pass - gets none of those, so there the number is an absolute ceiling.

`--fs`, `--shell` and `--approval` pick the service behind each seam, the same way `--provider` does, so a plugin registering `approval:slack` is selected by name with no core change.

`--provider` does a little more than the others: it names a **provider profile**, and a profile carries an endpoint and a model as well as itself. `--model` therefore declares no default. Unset, it comes from the selected profile. See Providers below.

`--disable-plugin NAME` skips a plugin; `--plugin MODULE` imports one that is not an entry point at all. Both are repeatable. Neither reaches enforcement, which is not a plugin, as described below.

## Launch configuration

Every flag above has a default, and any of them can be set once in `.un/config.toml` at the project root.

Any flag `un` declares is a valid key, except `effort` and `max_turns`, which belong to a provider profile. Keys are the flag's name with or without its hyphen (`log-debug` and `log_debug` both work), so a flag added later is configurable with no new plumbing. A root `max_turns` is refused by name rather than ignored, since it used to be a launch key.

A missing or empty file is a normal state. A wrong one exits 2: an unknown key, a value of the wrong type, or a value outside a flag's permitted set names the file and the key.

```
$ un plugins
/home/you/project/.un/config.toml: [providers.local].max_turns must be int, not str
```

Two details:

- **`plugin` and `disable_plugin` add to their flags rather than being replaced by them.** A configured `disable_plugin = ["oauth"]` plus `--disable-plugin shell_access` disables both. A repeatable flag means "add one more", and a configured entry is one more, so a configured plugin cannot be re-enabled for a single run from the command line.
- **The file is found in the current directory only.** `un` run from a subdirectory reads that directory's config, not the project root's. `.un/sessions/` follows the same rule.

## Providers

To reach anything else, declare one entry per endpoint:

```toml
[providers.ollama]
adaptor = "openai"
url     = "http://localhost:11434/v1"
model   = "llama3.2:3b"
main    = true

[providers.openai]
adaptor = "openai"
url     = "https://api.openai.com/v1"
model   = "gpt-5"
api_key = "OPENAI_API_KEY"

[providers.anthropic]
adaptor = "anthropic"
model   = "claude-opus-5"
```

Every provider sits under the one `providers` key, and the heading names it: `[providers.ollama]` is the profile called `ollama`. There is no `name` field — the name is the key, so TOML refuses two providers sharing one before un reads the file.

`adaptor = "openai"` covers anything speaking the chat-completions API: OpenAI, a local ollama, most self-hosted servers. Each entry is one complete answer, so `un chat "..." --provider openai` selects that endpoint and its model together. `main = true` says which entry a run naming none gets, and exactly one entry may set it.

An aftermarket plugin may claim any other adaptor value. `aftermarket/plugins/ollama/` claims `adaptor = "ollama"` and speaks ollama's native API instead of its compatibility layer, which is what reaches a per-request context size, thinking, and tool arguments that were never serialised to a string. Its `url` takes no `/v1`, and it takes an `options` table:

```toml
[providers.local]
adaptor = "ollama"
url     = "http://localhost:11434"
model   = "gemma4:12b"
options = { num_ctx = 32768 }
```

`options` is passed to the adaptor untouched. un checks that it is a table and nothing more, since validating the keys would mean core learning one endpoint's vocabulary; an adaptor that has no use for it ignores it, as `url` and `api_key` are already ignored by the adaptors that do not need them.

`api_key` holds the **name** of a variable in `.env`, never the key itself. un reads that file and hands the value only to the request that needs it. The value stays out of the process environment, so the model's own `bash` cannot reach it. Omit the field where the endpoint needs no credential, as a local ollama does.

An explicit `--model` beats the profile's, which beats the declared default. A project with no table uses the built-in Anthropic defaults.

## Hook events

| Event | |
|---|---|
| `SessionStart` | beginning of the session |
| `UserPromptSubmit` | after user message submission prior to it being delivered to the agent |
| `TurnStart` | right after user message submission |
| `PreToolUse` | before a tool is used|
| `PostToolUse` | after a tool is used, folding that one call's result text |
| `ToolResults` | once per batch of tool calls, after their results and before the model's next turn |
| `Turn` | after each agent reply |

## Memory, skills and transcripts

- Memory is one file per fact under `.un/memory/`, with `MEMORY.md` beside them as the index. Each memory gets one pointer line, and the index is the only part in the prompt; `recall` reads a body when its description says it matters. Both are committed and human-editable.
- Skills are `.un/skills/<name>/SKILL.md`, indexed into the prompt by name and description with the body read on demand.
- Transcripts are `.un/sessions/<id>.jsonl`.

## Rules

**`.un/rules/*.md` are standing instructions**, and each one says in its own frontmatter when it fires, which conversations it applies to, and which message carries it:

```markdown
---
trigger:
  event: TurnStart
---
Run tests through validate_tests.py, never bare pytest.
```

Three groups, answering three questions. **`trigger` says WHEN**, and is required — at least one of its three keys must be present:

| inside `trigger` | |
|---|---|
| `event` | `SessionStart` for once at the top, `TurnStart` for once per prompt |
| `path` | a glob; fires when a tool call touches a matching file, once per turn |
| `every` | a stride on the turn: your first prompt, then every Nth after |

Name none of them and the file is refused nothing — it still applies — but you are told, because a rule that fires at a moment you did not choose is worse than one that will not load. Name `path` alone and the moment is implied from it; name `event` and it wins.

**`provider`, `model` and `agent` say WHETHER**, flat beside `trigger`. Each is a glob, or a comma-separated list of them, and leaving one out means no opinion:

```yaml
trigger:
  every: 3
model: "claude-sonnet-*, gpt-5*"
agent: researcher
```

That is what a reminder aimed at one model looks like. Model behaviour is not uniform, and context a weak model needs is context a strong one wastes.

**`message_type` says HOW**, and defaults to `system`.

A malformed header keeps the rule: every problem with it is collected into one sentence, the body still applies on the turn fallback, and you hear about it three ways — in the injected text, on the error channel, and wherever your session reports.

### Where a rule arrives

The trigger and the message type together decide which message carries the text:

| | `message_type: system` (default) | `message_type: user` |
|---|---|---|
| `event: SessionStart` | the system prompt | folded into your prompt |
| `event: TurnStart` | a `role: "system"` message after your prompt | folded into your prompt |
| `path:` touched | a `role: "system"` message after the tool results | appended to the tool result |

**`path` matches an argument literally named `path`.** That covers `Read`, `Write`, `Edit` and friends, and any drop-in tool following the same convention. It does not reach inside a `bash` command, and it deliberately does not read `Glob`'s `pattern` — `Grep` spells a regex the same way, and un declines to guess which one it is looking at.

**The default is a `role: "system"` message, never user text.** User-role content is forgeable by anything that writes into what the model reads, so a file the agent reads could otherwise spell a rule. Appending also leaves the cached prefix intact, where editing the system prompt every turn re-bills the whole history.

`message_type: user` is the documented exception and it gives that protection up. Use it when a model needs the text where it is already looking, and not for anything you would mind the model being able to imitate.

One caveat on the default: a model that rejects mid-conversation system messages, `claude-sonnet-5` among them, folds rule text into the user turn anyway and warns on stderr. The forgery protection is gone on such a model whatever you asked for.

### Migrating

`cadence` and the reserved `on:` are both gone, and `trigger` is required — so **every rule written before this needs a header**. The body is never lost while you do it: an unreadable rule keeps applying every turn and tells you so.

| was | is |
|---|---|
| `cadence: turn` | `trigger: {event: TurnStart}` |
| `cadence: session` | `trigger: {event: SessionStart}` |
| `cadence: {every: 3}` | `trigger: {every: 3}` |

A rule is text, not an event handler. Something that runs on an event is a [hook](../../docs/wiki/un/hooks.md), declared in `.un/hooks/<name>.md` and activated in `.un/config.toml`.

## Plugins
**A plugin has exactly one name: the one `un plugins` prints.** Stock and aftermarket are named the same way, with no qualifier:

```
un plugins --disable-plugin shell_access               # an agent with no bash tool
un chat "…" --disable-plugin session_transcripts       # leaves nothing on disk
un plugins --disable-plugin some-third-party           # an installed plugin, same spelling
un --plugin my_scratch_plugin chat "…"            # try a plugin before packaging it
```

A name nothing declares is a usage error listing what does exist:

```
$ un plugins --disable-plugin shell
no plugin 'shell'; available: anthropic_api, ask_user, ast_grep, commands, file_system, …
```

Disabling works by declining to import a module, so it is decided before the import and applies only to what has not loaded yet. That is also why nothing outside a plugin imports another plugin's module: an import anywhere else registers it whatever the flag says. Shared vocabulary, such as where a session's files live, lives in `un.core` instead of in the plugin that uses it most.

**Enforcement is not a plugin, so it cannot be skipped.** The permission table, the `approval:cli` and `approval:yes` adapters, the writer behind an `always` answer and the per-subagent tool scopes an agent file declares as `Tool(x, ...)` in its `tools:` all live in `un.core` and register when it is imported. `permissions`, `approval` and `subagent_scopes` are therefore not plugin names: `--disable-plugin`, a `disable_plugin` entry in `.un/config.toml` and `un plugins disable` refuse each as a name no plugin carries.

`--approval yes` is the same decision one level up: the run answers its own approval prompts, which is what a non-interactive job wants. The permission table keeps that flag out of the agent's reach. A command that spawns another `un` and picks its approver is refused (`R08`), so the choice stays the operator's.

`un plugins` prints one block per plugin: the name `--disable-plugin` takes, what the plugin does, and the tools it gives the model.

```
$ un plugins
file_system   [stock]
  Allows agents to interact with the filesystem (read, write, edit, grep, glob).
  tools: Edit, Glob, Grep, Read, Write

shell_access   [stock]
  Allows shell access and Bash tools (grep, cat, ls, etc).
  tools: Bash
```

### Writing a plugin

The whole API is three decorators and two lookups.

```python
from un import service, tool, hook, use, variants, new_session, Verdict

@tool("weather", "Current weather for a city.",
      {"type": "object", "properties": {"city": {"type": "string"}},
       "required": ["city"]})
def weather(*, session, city):
    return f"it is raining in {city}"

@hook("PreToolUse")
def no_london(*, session, name, args):
    if name == "weather" and args.get("city") == "London":
        return Verdict("deny", "not that one")
    return None            # None is no opinion, not approval

@service("fs:readonly")    # swap the filesystem out from under every file tool
class ReadOnly:
    def __init__(self, session): self.session = session
    def read(self, path): ...
```

Publish it as an entry point and it loads the way a first-party plugin does:

```toml
[project.entry-points."un.plugins"]
weather = "my_package.weather"
```

### Installing a plugin

**Install it into the environment `un` runs from.** The entry point has to reach `importlib.metadata`, so the distribution has to be installed, not merely present on `sys.path`.

```toml
# pixi.toml — pixi installs PyPI dependencies from the manifest and has no `pip`
[pypi-dependencies]
un-widgets = { path = "../un-widgets", editable = true }
```

```bash
pixi install                        # pixi
pip install -e ../un-widgets        # pip, in a virtualenv
pip install un-widgets              # or from an index
```

**Then enable it.** `un plugins` is the manager: it lists with no verb, and `enable` / `disable` write `.un/config.toml` as a targeted line edit, so the comments around the key survive.

```bash
un plugins                      # what exists, and what is on
un plugins enable widgets       # writes enable_plugin = ["widgets"]
un plugins disable widgets
```

`un chat --enable-plugin widgets` does it for one run and writes nothing. Hand-editing `.un/config.toml` does the same thing as running the verb.

The listing shows both states. Installed and off:

```
widgets   [off]
  (no description)
  not enabled for this run
```

The description is missing because `plugin_table` reads entry points without importing anything, and an aftermarket plugin carries its description in its own module. Enabled, the module is imported and it appears, with the tools it registered:

```
widgets
  Make and inspect widgets ...
  tools: WidgetMake, WidgetInspect
```

A plugin that fails to declare itself is refused, and `un` starts anyway. `core._refuse` imports it, looks for a module-level `UN_PLUGIN` dict with a non-empty `description`, and on finding none clears whatever it registered, drops it from `sys.modules`, and prints why. The plugins sorted after it still load.

## Giving the agent a tool

A tool hands the agent a capability.

Drop a directory into `.un/tools/` and it is registered:

```
.un/tools/abrowser/
├── TOOL.md            the manifest
└── abrowser/          whatever the tool is made of
    └── abrowser.py
```

`TOOL.md` declares itself in YAML frontmatter. Three keys, all required: `name` is the agent-facing tool name, `description` is the registration contract and what tells the model how to call it, and `run` names an executable file inside the tool's own directory.

```markdown
---
name: AgentBrowser
description: >
  What this does and how to call it. `args` is passed straight through as argv.
run: abrowser/abrowser.py
---
```

Operator-facing notes. Optional. If the tool needs packages, say so here.

Every tool takes the same fixed schema — an `args` array — and un maps nothing. `GitRo` is the precedent: argv as a list, `shell=False`, no per-tool spelling for un to learn. An ordinary CLI is already a tool, and the `description` is what teaches the model to drive it.

## Design

Two ideas come from existing harnesses.

From `deepseek-harness`: extension points are a **service registry**. A tool calls `fs`, and the session decides which implementation that is. Swap in `fs:sandbox` and no tool changes, no schema changes, and the model sees the same interface. That indirection is what makes every extension point replaceable.

From `pi`: the transcript is JSONL appended as it happens, so a killed process leaves a session that is valid up to its last complete line. Also its hook vocabulary, and its rule that a payload is one of two kinds of line, a message or a usage row.
