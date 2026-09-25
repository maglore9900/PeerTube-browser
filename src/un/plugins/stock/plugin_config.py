"""Plugin state and the two keys that decide it, read and written in one place.

`.un/config.toml` is the source of truth (ADR-0015) and every surface is an editor of it:
`un plugins`, `un plugins enable/disable`, `/plugins` and a text editor all reach the same
file, and nothing but this module knows its format.

Top level rather than in `core` or in a plugin, for two reasons pointing the same way:
`core`'s docstring states nothing in it opens a file for writing, and `cli` reaches this
while `cli` must never import a plugin. So it sits beside `allow_rule.py` under
`plugins/stock/`, declaring no entry point and registering nothing - which is what lets a
plugin import it without `--disable-plugin` reaching anything new.

Writes: `.un/config.toml`, two root keys and nothing else.
"""

from __future__ import annotations

import sys
import textwrap
import tomllib
from pathlib import Path

# The comment-preserving line editor, from the module that already had one. It stays
# there because `allow_rule.py` is in `permissions._PROTECTED` for writing the allow
# array, and moving the write would carry that protection out with it.
from un.plugins.stock.allow_rule import set_array
from un.core import CONFIG, REGISTRY, Plugin, plugin_table

# One key per group, because the two groups are on by different defaults: a stock plugin
# loads unless `disable_plugin` names it, an aftermarket one stays off unless `enable_plugin`
# does.
ENABLE_KEY = "enable_plugin"
DISABLE_KEY = "disable_plugin"


def listing(enabled: frozenset[str], disabled: frozenset[str]) -> str:
    """Every discoverable plugin as one block: name, labels, description, state.

    One block per PLUGIN, not one row per registration. A registry dump answered a
    question nobody asks - `slash:plugins` and `SessionStart:un.plugins.stock.rules.
    instructions` are internal wiring - while the question an operator does ask, "what is
    this and what do I type to turn it off", had no answer anywhere.

    Tools are the only registrations printed, because they are the surface the MODEL sees
    and therefore the thing disabling a plugin visibly takes away. Services and hooks are
    how the harness is wired together; `/help` and `--provider` are where those are chosen.

    `[stock]` marks what this project ships. Aftermarket is unmarked rather than labelled,
    so the listing stays one table with one class of citizen.

    A plugin that is not running says which of three ways it got there. The states are
    DERIVED here rather than recorded anywhere, from the two things that are already
    ground truth: `sys.modules` says what is running, and the two arguments say what was
    asked for. Nothing stores them.

    The arguments are sets rather than a namespace because two callers reach this with
    different things in hand: `cli` holds the resolved launch state, and `/plugins` runs
    mid-session with no argparse anywhere and reads the file. They agree except on a
    plugin disabled by FLAG, which the file cannot know about.
    """
    tools: dict[str, list[str]] = {}
    for name, fn in sorted(REGISTRY["tool"].items()):
        # A drop-in tool from `.un/tools/` is not this listing's to claim. Every one of
        # them is a closure generated inside `un.plugins.stock.tools`, so keying by
        # module would pile the lot onto that plugin's row - and a plugin listing would
        # then speak for tools that are not plugins. `un tools` speaks for those.
        if getattr(fn, "un_from_file", False):
            continue
        tools.setdefault(fn.__module__, []).append(name)

    # `--plugin some.module` imports a plugin that declared no entry point, so
    # `plugin_table` cannot see it and it would be missing from the one command that
    # answers "what is running". Named by its module path, because that IS what the
    # operator typed to get it, and unmarked: it is nobody's stock and `--disable-plugin` does
    # not reach it - dropping the `--plugin` flag is how it goes away.
    declared = plugin_table()
    known = {p.module for p in declared}
    extra = sorted({
        fn.__module__
        for extension in ("service", "tool", "hook")
        for fn in REGISTRY[extension].values()
    } - known)

    blocks = []
    for plugin in [*declared, *(Plugin(m, m, "", False) for m in extra)]:
        module = sys.modules.get(plugin.module)
        # `disabled` is tested FIRST, in the same order `core.load` tests it: a name in
        # both arrays is skipped before the enabled check is ever reached, so it was
        # never imported and never refused. Deriving `refused` first instead reports
        # "enabled, but refused at load" for a plugin nothing tried to load, and sends a
        # reader hunting stderr for a reason that was never printed.
        off = plugin.name in disabled
        # Asked for, not disabled, and not running is the definition of refused, and it
        # needs no state kept anywhere: `core.load` already popped the module back out of
        # `sys.modules`.
        refused = module is None and not off and plugin.name in enabled
        # An aftermarket description lives in its own module and is reachable only once
        # that module is imported. A disabled one therefore has none, which is honest:
        # what it would have said describes something that is not running.
        described = plugin.description or getattr(
            module, "UN_PLUGIN", {}).get("description", "")
        labels = (("   [stock]" if plugin.stock else "")
                  + ("" if module else "   [refused]" if refused else "   [off]"))
        lines = [f"{plugin.name}{labels}"]
        lines += [f"  {line}"
                  for line in textwrap.wrap(described, 74) or ["(no description)"]]
        if module:
            lines.append(f"  tools: {', '.join(tools.get(plugin.module, [])) or 'none'}")
        elif refused:
            lines.append("  enabled, but refused at load; the reason went to stderr")
        elif off:
            lines.append("  disabled for this run")
        else:
            # The only way left to be off: aftermarket, and nobody asked for it. A stock
            # plugin cannot reach here - it loads unless it was named, and being named is
            # the branch above.
            lines.append("  not enabled for this run")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def configured(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """What the FILE says is enabled and disabled, for a caller with no launch state.

    `/plugins` runs mid-session and never saw the command line, so it reads the source of
    truth. `cli` passes its own resolved state instead, which additionally carries
    `--disable-plugin`.
    """
    arrays = _arrays(root)
    return frozenset(arrays[ENABLE_KEY]), frozenset(arrays[DISABLE_KEY])


def _arrays(root: Path) -> dict[str, list[str]]:
    """The two plugin arrays as the file has them. A missing key reads as empty.

    No validation: `cli._config` has already refused a file this cannot read, and every
    caller here runs after that. A second copy of those checks would be the drift one
    seam exists to prevent.
    """
    path = root / CONFIG
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {key: list(raw.get(key, ())) for key in (ENABLE_KEY, DISABLE_KEY)}


def toggle(root: Path, name: str, *, stock: bool, on: bool) -> str:
    """Make `name` load next run, or stop it loading. Returns what to tell the operator.

    The verbs mean what they say, and which array carries the answer depends on which
    group the plugin is in: a stock plugin loads unless `disable_plugin` names it, an
    aftermarket one stays off unless `enable_plugin` does. So `enable` is removal from one
    array and addition to the other, and neither verb has to know about both - except in
    the one case below, where knowing about both is the difference between reporting the
    truth and reporting the key it happened to write.

    `core.load` tests `disabled` BEFORE `enabled`, so an aftermarket plugin named in both
    arrays does not load. Enabling one therefore has to clear `disable_plugin` as well, or the
    write reports success over a plugin that stays off.

    The caller has already refused a name this cannot act on - `cli._validate_toggle` owns
    that, and a second copy here is the drift one seam exists to prevent.

    Says "next run" and claims nothing more. `/reload` applies the same change to a LIVE
    session, reading this file the way every other surface does.
    """
    path = root / CONFIG
    arrays = _arrays(root)
    # The array that decides THIS plugin, and whether the name belongs in it afterwards.
    key, listed = (DISABLE_KEY, not on) if stock else (ENABLE_KEY, on)
    # Enabling an aftermarket plugin also has to take it out of `disable_plugin`, per above.
    # Never the reverse: `disable` removing from `enable_plugin` is already sufficient,
    # and adding to `disable_plugin` as well would leave a name in an array nothing put there.
    clearing = not stock and on and name in arrays[DISABLE_KEY]

    if (name in arrays[key]) == listed and not clearing:
        return f"{name} is already {'enabled' if on else 'disabled'}; {path} unchanged"

    if clearing:
        # No re-read after this. `clearing` is only ever true for an aftermarket plugin
        # being enabled, so `key` is `ENABLE_KEY` and the array below is untouched by it -
        # and `set_array` locates its key in the file it reads for itself each call.
        set_array(path, DISABLE_KEY, _without(arrays[DISABLE_KEY], name))
    if (name in arrays[key]) != listed:
        set_array(path, key,
                  [*arrays[key], name] if listed else _without(arrays[key], name))

    return (f"{'enabled' if on else 'disabled'} {name} in {path}\n"
            f"  takes effect on the next run, or on /reload in a session already open")


def _without(values: list[str], name: str) -> list[str]:
    """`values` minus `name`, order preserved.

    Order rather than sorted: the array is edited by hand too, and rewriting somebody's
    ordering is the same class of surprise as dropping their comments. `allow_rule._add`
    appends for the same reason.
    """
    return [value for value in values if value != name]
