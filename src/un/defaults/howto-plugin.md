# How to write a plugin

A plugin is a Python module that imports `un` and calls its registration decorators at import time. Nothing else marks it. A [hook](how-to-write-a-hook.md) is a script un spawns, a [skill](how-to-write-a-skill.md) is text un shows the model; a plugin is code running inside un's own process, and it can add tools, replace the provider, replace the filesystem, or add a CLI verb.

Everything un does arrives this way. The conversation loop, the file and shell tools, the permission table and the REPL are all plugin modules, loaded through the same code path yours takes.

## The smallest working plugin

One module, plus an entry point in the distribution that ships it.

```python
# my_package/weather.py
from un import service, tool, hook, Session, Verdict

UN_PLUGIN = {"description": "Weather lookups."}

@tool("Weather", "Look up the forecast for a city.",
      {"type": "object", "properties": {"city": {"type": "string"}},
       "required": ["city"]})
def weather(*, session: Session, city: str) -> str:
    return fetch(city)
```

```toml
# the plugin's own pyproject.toml
[project.entry-points."un.plugins"]
weather = "my_package.weather"
```

`UN_PLUGIN` is required, and its `description` is what `un plugins` prints. A module that does not carry a non-empty one is refused at load.

The entry-point name, `weather` here, is the plugin's only name. It is what `un plugins` prints and what `--disable-plugin` and `enable_plugin` take. The distribution name in `pyproject.toml` is a separate string, and an install script uses both.

## Installing and enabling

Install into the environment `un` runs from. Discovery reads installed metadata through `importlib.metadata` and never scans the filesystem, so a module merely on `sys.path` is not found and there is no `.un/plugins/` directory.

```bash
pixi add --pypi "un-weather @ file:///abs/path/to/plugin"    # or pip install -e
un plugins enable weather
```

`un plugins enable NAME` writes `enable_plugin` in `.un/config.toml` as a targeted line edit, so the comments around the key survive, and a re-run leaves the file as it was. Hand-editing the key does the same thing.

```toml
enable_plugin = ["weather"]
```

An aftermarket plugin does not load until the config names it. `--enable-plugin NAME` does it for one run and writes nothing. The decision lives in the config file because an aftermarket module runs at import and can register anything, and nothing later in the run asks the operator about it.

## The three kinds

Every registration is one of three, and all three land in one process-wide `REGISTRY`. A name already taken raises `ValueError` at import.

| Decorator | Registers | Reached by |
|---|---|---|
| `@service(key)` | A named capability, one implementation per key | `use(namespace, name)`, `variants(namespace)` |
| `@tool(name, description, schema)` | A callable the model may invoke | The agent loop |
| `@hook(event)` | An observer or gate on a named event | `fire(event, ...)`, `chain(event, value, ...)` |

### Tools

`schema` is JSON Schema for the function's keyword arguments. The function takes `session` plus those arguments, all keyword-only, and returns the text the model reads. `description` is the whole of what teaches the model to call it, so write it as instructions rather than as a label. The name `Tool` is reserved, because `Tool(NAME)` is the permission rule claiming a whole tool.

Every call is still judged by the permission table. Registering a tool grants nothing.

### Hooks

An in-process hook is a function, not a script, and is registered against one of eight events. Its return value means something different per event: `collect` events gather every non-`None` return, `chain` events fold one value through each hook in turn.

```python
@hook("PreToolUse")
def no_london(*, session, name, args):
    if name == "Weather" and args.get("city") == "London":
        return Verdict("deny", "not that one")
    return None            # no opinion, which is not approval
```

| Event | Kind | A return means |
|---|---|---|
| `SessionStart` | collect | Text appended to the system prompt |
| `UserPromptSubmit` | chain | Replaces the prompt |
| `PreToolUse` | collect | A `Verdict` of `deny`, `ask` or `allow` |
| `PostToolUse` | chain | Replaces the tool's result text |
| `TurnStart` | collect | Text added as an operator system message |
| `ToolResults` | collect | The same, once per tool batch |
| `Turn` | collect | Ignored; fires after each assistant reply |
| `TurnEnd` | collect | Ignored; fires once when the turn is over and un is ready for input, carrying `interrupted` |
| `ToolEnd` | collect | Ignored; fires once per attempted call, refusals included |
| `OperatorWaitStart` | collect | Ignored; fires when un stops and waits on a person |
| `OperatorWaitEnd` | collect | Ignored; fires when that wait ends, however it ended |
| `SessionEnd` | collect | Ignored; fires once when an operator's session is over, carrying `code` |

An unknown event name raises at decoration. A hook's registry key is built from its module and function name, so two hooks never collide.

`core.fire` also acts on `OperatorWaitEnd` itself, ahead of the listeners: a wait that ended in an attended session zeroes what `max_turns` bounds, so a person answering gives the run a fresh budget. Headless it zeroes nothing, since both ask paths fire the pair even when a registered adapter refuses with nobody there. This is the one event core listens to, and it changes nothing about what a listener is handed.

The stock REPL registers a `ToolResults` listener, which is how a line typed during a tool batch reaches the model in that same turn. Returns from every listener are appended in load order, so yours is unaffected by it.

### Services

A service key is spelled `namespace:name`. Claiming an existing namespace replaces an implementation without any caller changing: `session.provider`, `session.fs` and `session.shell` each select one by name at call time.

```python
@service("provider:mycloud")
def mycloud(*, system, messages, tools, model, effort, cache, emit): ...

@service("fs:readonly")
class ReadOnly:
    def __init__(self, session): ...

@service("slash:stats")
def stats(session, rest: str) -> str:
    """Show what this session has used so far."""

@service("command:audit")
def audit(args) -> int:
    """Audit the project. One line of docstring becomes the subcommand's help."""

audit.arguments = lambda parser: parser.add_argument("path")
```

A `command:` service becomes a CLI verb: `un audit`. Its optional `arguments` attribute is called with the verb's argparse subparser, so `un audit src/` hands the function `args.path == "src/"`; without one the verb takes the common flags only. A `slash:` service becomes `/stats`, and `/help` reads its docstring. The namespace is a plain string, so a plugin may claim one un has never heard of and reach it through `REGISTRY` itself.

## What the public API is

`un` itself. `un/__init__.py` re-exports exactly what a plugin author needs: `service`, `tool`, `hook`, `use`, `variants`, `new_session`, `run_agent`, `Session`, the `Verdict` vocabulary, `gate`, `fire`, `chain`, `Reply`, `ProviderError`, `child_env`, `record_turn`, `session_file`, `run_terminal` and the `EXIT_*` constants, among others.

Two rules bound it:

* **Never import `un.plugins.stock.cli`.** Plugins are imported by the CLI and must not import it back. `new_session`, `run_terminal` and the exit constants live in `un.core` for that reason.
* **Never import another plugin.** Importing one registers it no matter what `--disable-plugin` said. Shared code goes somewhere that registers nothing, which is `un.core`: `un_dir` and `refused` for facts about the project directory, and `frontmatter` for the frontmatter format. Both are re-exported, so a plugin spells them `from un import frontmatter`.

## When one is refused

An enabled plugin that raises on import, or that carries no usable `UN_PLUGIN`, is refused rather than fatal. Every registration it already made is dropped, the module is removed from `sys.modules`, the reason goes to stderr naming the plugin, and un starts with the rest. A plugin the operator never enabled is never imported, so there is nothing to refuse.

## Disabling

```
un chat "hi" --disable-plugin weather
```

`disable_plugin` in `.un/config.toml` is the permanent form, and the two union. Both are validated before anything is imported, so a name in neither group refuses to start and lists what is available. A colon in the name is refused outright.

Two stock plugins cannot be skipped by either route, and naming one refuses the run: `permissions`, which enforces tool guards, and `subagent_scopes`, which holds each subagent to the `Tool(x, ...)` scopes its agent file declares and loads whether or not `subagents` does. The match is exact, so a third-party `permissionsx` or `subagent_scopesx` stays disableable.

## Naming

A name claimed by both the stock group and the aftermarket one refuses to start, before anything is imported, because a bare `--disable-plugin` name would otherwise skip two plugins. A third party cannot check against a list they do not control, so name a plugin for what it is rather than for the thing it talks to.

## Inspecting what loaded

```
un plugins
```

One block per plugin: name, description, and the tools it gives the model. `[stock]` marks what un ships. An installed plugin that is not running says which of three ways it got there.

| Label | Body | Meaning |
|---|---|---|
| none | `tools: ...` | Running |
| `[off]` | `disabled for this run` | Named on `--disable-plugin` or `disable_plugin` |
| `[off]` | `not enabled for this run` | Aftermarket, never enabled |
| `[refused]` | `enabled, but refused at load` | Enabled, imported, rejected |

An installed but disabled plugin shows no description, because the listing reads entry points without importing anything and an aftermarket description lives inside its module.

## When not to write one

If all you want is to give the agent a command-line program, drop a directory into `.un/tools/` with a `TOOL.md` manifest instead. It needs no distribution, no entry point and no install step. A plugin is for what a drop-in tool cannot do: replacing a service, gating in-process, or adding a CLI verb.
