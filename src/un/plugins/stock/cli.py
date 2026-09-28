"""The command line: argument parsing and subcommand dispatch, and nothing else.

main(argv) -> int, so the whole surface is callable from a test without a subprocess.

Rendering a turn is `core.run_terminal`'s and the interactive loop is the `repl`
plugin's, both for the same reason `new_session` lives in `core`: a plugin needs them
and a plugin must never import this module. So `un chat` with no prompt reaches the
REPL through `use("command", "repl")` like any other contributed verb, while
`un chat PROMPT` and `un resume` render directly and depend on no plugin at all.

Order matters here: `common` declares what a launch configuration may set, so it is
built first; `.un/config.toml` is then read and validated against it, and only then
are plugins loaded - because a configured --plugin / --disable-plugin decides an import
that has to happen before the real parser can know what subcommands exist.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from un import core
from un.plugins.stock import plugin_config
from un.core import (
    CONFIG,
    EFFORTS,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_USAGE,
    SESSIONS,
    Denied,
    RecordUnavailable,
    Session,
    end_session,
    load,
    main_provider,
    new_session,
    plugin_names,
    project_root,
    providers,
    run_terminal,
    use,
    variants,
)


def _chat(args: argparse.Namespace) -> int:
    if not args.prompt:
        try:
            repl = use("command", "repl")
        except LookupError as exc:
            # The REPL plugin is disabled, so there is nothing to open. The wording is
            # `use`'s, like every other missing variant.
            print(exc, file=sys.stderr)
            return EXIT_USAGE
        return repl(args)
    session = new_session(args)
    # On stderr so stdout stays pipeable. Without it the per-run id is never seen and
    # `un resume` has nothing to be given.
    print(f"session {session.id}  (continue with: un resume {session.id} '...')",
          file=sys.stderr)
    return end_session(session, lambda: run_terminal(
        session, args.prompt, max_turns=session.max_turns, stats=args.stats))


def _resume(args: argparse.Namespace) -> int:
    session = new_session(args, id=args.session_id)
    try:
        restore = use("session", "restore")
    except LookupError as exc:
        # The transcript plugin is disabled, so there is nothing to resume FROM - a
        # different fact from the session not existing, and reported as its own.
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    try:
        restore(session)
    except FileNotFoundError:
        print(f"no transcript for session {args.session_id!r} under {SESSIONS}/",
              file=sys.stderr)
        return EXIT_USAGE
    # The two EXIT_USAGE returns above are deliberately OUTSIDE the bracket: a session
    # whose restore service is disabled or whose transcript is missing never ran a turn, so
    # it never fired SessionStart and has nothing for an end to close.
    return end_session(session, lambda: run_terminal(
        session, args.prompt, max_turns=session.max_turns, stats=args.stats))


def _workflow(args: argparse.Namespace) -> int:
    """Run a workflow. Its return value is the exit code, unaltered.

    A workflow gates on real command results, so its verdict is the thing worth
    surfacing to whatever ran `un` - a CI job, a script, or a person.
    """
    try:
        found = use("workflow", args.name)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    session = new_session(args)
    return end_session(session, lambda: found(session, *args.argv))


def _plugins(args: argparse.Namespace) -> int:
    """List every plugin: the name --disable-plugin takes, what it does, what it gives the model.

    The rendering is `plugin_config.listing`'s, because `/plugins` answers the same
    question mid-session. This end holds the resolved launch state, which is the part the
    file cannot know: a `--disable-plugin` disables a plugin the config never named.
    """
    print(plugin_config.listing(
        frozenset(args.enable_plugin), frozenset(args.disable_plugin)))
    return EXIT_OK


def _plugin_toggle(args: argparse.Namespace) -> int:
    """`un plugins enable NAME` / `un plugins disable NAME`. Permanent, writes CONFIG.

    The decision goes in the file rather than into this process, so hand-editing reaches
    the same result as this verb and neither is a fallback for the other.
    """
    stock, aftermarket = plugin_names()
    on = args.plugin_verb == "enable"
    try:
        _validate_toggle(args.name, stock, aftermarket, on)
    except ValueError as exc:
        # By return rather than SystemExit, so `main` stays callable from a test.
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    print(plugin_config.toggle(
        project_root() or Path.cwd(), args.name,
        stock=args.name in stock, on=on))
    return EXIT_OK


def _validate_toggle(name: str, stock: frozenset[str], aftermarket: frozenset[str],
                     on: bool) -> None:
    """Refuse a name the verbs cannot act on, reusing the disable rules.

    `_validate_disable` already refuses the same three mistakes either verb can make.
    NOT `_validate_enable`: that guards the aftermarket-only config KEY, where this guards
    a VERB meaning "make this load" for either group.

    One carve-out. Enabling a name in `UNDISABLEABLE` is not a mistake - it is already on and cannot be turned off - so `toggle` says so rather than refusing.
    """
    if on and name in UNDISABLEABLE:
        return
    _validate_disable(name, stock, aftermarket)


def _self_learning(path: Path, value) -> bool:
    """`[self_learning].enable`, refusing the root bool it replaced.

    An absent `enable` keeps `Session.self_learning`: the table's presence is not the
    opt-in, the built-in default already is, so an empty table means "as shipped" rather
    than silently meaning off.

    `curate` is admitted and inspected only for keys that were removed, which
    `_retired_curate` refuses; the rest is validated by the plugin that owns it - `cli`
    must never import a plugin.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"{path}: self_learning is a table now - write [self_learning] with "
            f"{core.ENABLE} = true, not self_learning = {str(value).lower()}")
    extra = sorted(set(value) - {core.ENABLE, "visibility", "curate"})
    if extra:
        raise ValueError(
            f"{path}: [self_learning] has unknown key {extra[0]!r}; the keys are "
            f"{core.ENABLE!r}, 'visibility' and the [self_learning.curate] table")
    on = value.get(core.ENABLE, Session.self_learning)
    if type(on) is not bool:
        # `type` rather than `isinstance`: bool is a subclass of int, so `enable = 1` would
        # otherwise land a non-bool on the session.
        raise ValueError(
            f"{path}: [self_learning].{core.ENABLE} must be bool, not {type(on).__name__}")
    return on


def _moved_curate(path: Path, raw: dict) -> None:
    """Refuse a `[skills.curate]` left behind by the pruner's move.

    It still PARSES, and under the per-skill gate it reads as "enable a skill named
    curate" - which names nothing on disk and does nothing at all. The operator's pruner
    stops while every surface reports success, and that is indistinguishable from a pruner
    with nothing to prune. So it is refused, naming where it went.

    Shape-guarded before the lookup: `[skills]` may legitimately be any table, and a
    non-dict here is `core.enabled`'s to refuse rather than this function's to crash on.
    """
    skills = raw.get("skills")
    if isinstance(skills, dict) and "curate" in skills:
        raise ValueError(
            f"{path}: [skills.curate] has moved to [self_learning.curate]; the pruner "
            "belongs to the self-learning loop, and [skills.<name>] now enables a skill")


def _retired_curate(path: Path, raw: dict) -> None:
    """Refuse the curation keys that went with the read clock, and the memory table's keys on the skills table. Here rather than in the plugin that owns the table, because only a launch refusal is fatal (ADR-0014)."""
    learning = raw.get("self_learning")
    curate = learning.get("curate") if isinstance(learning, dict) else None
    if not isinstance(curate, dict):
        return
    for target in ("skills", "memory"):
        table = curate.get(target)
        if isinstance(table, dict) and "retire_after_days" in table:
            raise ValueError(
                f"{path}: [self_learning.curate.{target}] has 'retire_after_days', which is gone - "
                "nothing is retired for going unread; delete the line")
    skills = curate.get("skills")
    for key in ("every_days", "check_batch"):
        if isinstance(skills, dict) and key in skills:
            raise ValueError(
                f"{path}: [self_learning.curate.skills] has {key!r}, which is "
                "[self_learning.curate.memory]'s key - the skills table takes only 'enable'")


def _moved_max_turns(path: Path, raw: dict) -> None:
    """Refuse a root `max_turns` left behind by the move into the provider table.

    `_moved_curate`'s posture on a different key. It parses, it names a real dest, and under
    the old arrangement it bounded the run - so an operator who capped a run in the place
    that used to work would be told nothing and get 50 turns.

    Called BEFORE the accepted-dest loop rather than beside `_moved_curate` after it: the
    loop would report it as an unknown key, which sends someone looking for a typo in a line
    that is spelled correctly and simply lives somewhere else now. Ahead of the type check
    for the same reason - `max_turns = "5"` at the root is a moved key first and a string
    second.

    Both spellings, because `_config` normalises them to one dest and a refusal catching
    only one would be a refusal an operator could get around by typing a hyphen.
    """
    if "max_turns" in raw or "max-turns" in raw:
        raise ValueError(
            f"{path}: max_turns has moved to [providers.<name>].max_turns; a turn bound "
            "belongs with the endpoint serving the turns, and --max-turns still overrides it")


def _config(parser: argparse.ArgumentParser) -> dict:
    """Read .un/config.toml and validate it against the flags `parser` declares.

    Nothing here restates a key, a default or a permitted value: the accepted keys are the
    parser's own dests, the expected type is the type of the declared default, and the
    permitted values are the declared choices - so a flag added to `common` becomes
    configurable with no edit here.

    Raises ValueError, which `main` turns into EXIT_USAGE. Every message names the file and
    the key, because a config file silently ignored is what this exists to prevent.
    """
    path = (project_root() or Path.cwd()) / CONFIG
    if not path.exists():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc

    _moved_max_turns(path, raw)

    # rat-tail: `_actions` is argparse's private list and the only route to a declared
    # `choices`, which is exactly the check argparse skips on a default. If this ever
    # breaks, declare the three facts in a dict here.
    actions = {action.dest: action for action in parser._actions}
    # Effort is a PROFILE key, not a launch key: it is written under `[providers.<name>]`
    # and the flag overrides one on a headless run. Dropped from the accepted dests so a
    # top-level `effort` takes the unknown-key path below, rather than being ignored.
    #
    # This leaves the `choices` check below unreachable, `--effort` being the only flag
    # declaring `choices`. It STAYS: a guard deleted for being currently unreachable is
    # one the next author does not know to re-add.
    actions.pop("effort", None)
    # `max_turns` is a profile key by the same route and for the same reason. Dropped as
    # well as refused above: `_moved_max_turns` names the migration for the operator who
    # had one, and this is what stops the dest existing for anyone who never did.
    actions.pop("max_turns", None)
    config = {}
    for key, value in raw.items():
                # Seven sections belong to somebody else and are checked by that owner:
        # `[permissions]`, `[providers]` (`core.providers`), `[agents]`, `[hooks]`,
        # `[skills]`, `[rules]` and `[workflows]`. This function checks keys against the
        # flags `parser` declares, and none of a rule group, an endpoint profile or an
        # extension activation is a flag.
        #
        # `[memory]` is deliberately NOT among them: nothing owns that section any more,
        # so a skip would leave every `[memory]` key silently ignored.
        #
        # The skip is these keys and nothing else. A top-level `tier`,
        # `dangerous_allow` or `every_hours` stays an unknown key, because each belongs
        # inside one of the sections above and being ignored would leave an operator
        # believing they had set it.
        #
        # `models` is read by `un.plugins.stock.models`, not here, and carries no `enable`
        # - it is a data table rather than an activation one, so it joins this list purely
        # to be let past the argparse check.
        # `keys` is the same kind of table and is read by `un.plugins.stock.repl`, which
        # refuses a bad one as it opens the REPL - the only command the section reaches.
        # `sandbox` is read by `permissions.read_permissions` beside `[permissions]`.
        if key in ("permissions", "providers", "agents", "hooks", "skills", "rules",
                    "models", "keys", "sandbox", "workflows"):
            continue
        if key == "self_learning":
            # A table now, in the shape every extension section uses. READ here rather than
            # skipped: skipping would make a stale root `self_learning = true` a silent
            # no-op, which is a line the operator can see and believes is arming the loop.
            config[key] = _self_learning(path, value)
            continue
        # `--max-turns` is `max_turns` as a dest, and a key named after the flag that
        # declares it must not be a silent miss.
        dest = key.replace("-", "_")
        action = actions.get(dest)
        if action is None:
            known = ", ".join(sorted(actions))
            raise ValueError(f"{path}: unknown key {key!r}; known keys: {known}")
        # The declared default carries the type. A flag declared `default=None` carries
        # none, so fall back to what argparse would apply - without this such a flag
        # rejects every value as "must be NoneType".
        expected = (action.type or str) if action.default is None else type(action.default)
        # `type` rather than `isinstance`: bool is a subclass of int, and
        # `max_turns = true` is a mistake worth reporting.
        if type(value) is not expected:
            raise ValueError(
                f"{path}: {key} must be {expected.__name__}, "
                f"not {type(value).__name__}")
        if isinstance(value, list):
            # A repeatable flag's element type, as argparse would apply it.
            element = action.type or str
            wrong = [item for item in value if type(item) is not element]
            if wrong:
                raise ValueError(
                    f"{path}: {key} must be a list of {element.__name__}; "
                    f"got {wrong[0]!r}")
        if action.choices is not None and value not in action.choices:
            raise ValueError(
                f"{path}: {key} must be one of {', '.join(action.choices)}; "
                f"got {value!r}")
        config[dest] = value

    # Validated HERE, though the only value taken is the default provider name: reading
    # the table now is what makes a malformed one reach the operator as EXIT_USAGE naming
    # the file, rather than as a traceback out of a plugin import three steps later. The
    # skip above makes the section legal; this stops the skip meaning "unchecked".
    # Both migrations this build introduces, refused where a config is read rather than
    # where the moved thing is consumed - so an operator hears about it on the next launch
    # instead of the next time the pruner would have run.
    _moved_curate(path, raw)
    _retired_curate(path, raw)

    here = project_root() or Path.cwd()

    # `[rules]` and `[skills]` for the same reason, and they need the check MORE than the
    # others do. `[agents]`, `[hooks]` and `[workflows]` are read by `core.scan` when their
    # plugin imports, which refuses a bad table and leaves every entry off (ADR-0014)
    # rather than exiting. Rules and skills are discovered lazily on every turn instead, so an
    # unchecked typo would surface as a traceback out of a `TurnStart` hook
    # mid-conversation - the crash ADR-0014 forbids, and the one `rules.py` bends over
    # backwards to avoid for a malformed rule FILE. The returns are discarded: these calls
    # ARE the validation.
    #
    # `core.enabled` rather than the plugin's `rules.enabled`, because `cli` must never
    # import a plugin. The gate lives in core precisely so both can reach it.
    core.enabled(here, "rules", "rule")
    core.enabled(here, "skills", "skill")

    profile = main_provider(providers(here))
    if profile is not None:
        # setdefault, not assignment: a top-level `provider = "..."` is the more specific
        # statement and keeps winning. An explicit --provider beats both, by argparse's
        # own precedence.
        config.setdefault("provider", profile.name)
    return config


def _preload(argv: list[str] | None, config: dict) -> None:
    """Honour --plugin / --disable-plugin before anything else is decided.

    Two-phase on purpose: disabling works by declining to import, so it must happen before
    the import, but plugin-contributed subcommands cannot reach the parser until the
    plugins are loaded. The config is read here as well as by the real parser for the same
    reason.

    The two sources UNION rather than one replacing the other, which is what a repeatable
    flag already means. Every disable name is checked before anything is imported, and the
    two are kept apart until then: a flag is a one-off, so a stock plugin named on it is
    challenged, where a configured entry is a decision already made.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--plugin", action="append", default=[])
    pre.add_argument("--disable-plugin", action="append", default=[], dest="disable_plugin")
    pre.add_argument("--enable-plugin", action="append", default=[],
                     dest="enable_plugin")
    known, _ = pre.parse_known_args(argv)

    stock, aftermarket = plugin_names()
    configured = list(config.get("disable_plugin", []))
    flagged = list(known.disable_plugin)
    for name in configured + flagged:
        _validate_disable(name, stock, aftermarket)
    # Both sources, unioned, as the disable names above are: a flag naming one plugin must
    # not silence a file naming another. Unlike a disable there is nothing to confirm -
    # turning an aftermarket plugin on for one run is what the flag is for.
    #
    # Validated before anything is imported, so a launch that failed validation cannot
    # have been half-honoured.
    enabled = frozenset(config.get("enable_plugin", []) + known.enable_plugin)
    for name in sorted(enabled):
        _validate_enable(name, stock, aftermarket)

    disabled = set(configured)
    for name in flagged:
        # A name the config already settled is not asked about: a configured entry
        # cannot be un-set for one run, and a question whose answer is discarded is
        # worse than no question.
        if name in disabled:
            continue
        if _confirm_stock(name, stock):
            disabled.add(name)

    # What the FLAG contributed: `disabled` started as `set(configured)` and the loop
    # added only flagged names that survived `_confirm_stock`, so the difference IS the
    # flag's. Recorded here, the last point the two sources are still apart.
    global DISABLED_BY_FLAG
    DISABLED_BY_FLAG = frozenset(disabled) - frozenset(configured)

    load(extra=tuple(config.get("plugin", []) + known.plugin),
         disabled=frozenset(disabled), enabled=enabled)


# Enforcement has no off switch. Checked here rather than in `load` because `_preload` runs `_validate_disable` over the config's entries and the command line's in one loop, so one clause closes both. Each name is matched exactly: a third-party `permissionsx` or `subagent_scopesx` is somebody else's plugin and stays disableable.
# Name -> what it enforces, the clause its refusal gives. The set is the keys, so no name is added without its reason.
_ENFORCES = {
    "permissions": "tool permissions, and a run with nothing enforcing them is not a run this tool offers. `rules` is a separate plugin and stays disableable",
    "subagent_scopes": "the per-subagent tool scopes an agent file declares as Tool(x, ...) in its tools:, and a subagent run with nothing holding it to its scope is not a run this tool offers",
}
UNDISABLEABLE = frozenset(_ENFORCES)

# What `--disable-plugin` turned off THIS RUN, as distinct from what `.un/config.toml` turned
# off: `/reload` re-reads the file and would otherwise silently undo a one-run flag.
# Written by `_preload`, the only place the two sources are still apart; read by
# `slash.reload_` as a MODULE attribute, since `_preload` reassigns it after the `load()`
# that imports that plugin.
DISABLED_BY_FLAG: frozenset[str] = frozenset()

# The launch keys a live session can be moved to, as `Session` field names. `/reload` re-reads
# these; every other configurable key is either resolved into something a running session
# cannot swap - a provider endpoint, the repl's rendered Consoles - or is already re-read
# where it is consumed.
#
# `approval` is deliberately NOT here. `repl.py` moves it from `cli` to `repl` as the
# interactive surface comes up, because `"cli"` cannot prompt underneath a live footer - and
# the repl is the only place `/reload` runs, so re-reading the file's `"cli"` would reset a
# live session's approver to a value that cannot work.
#
# Written out rather than derived. `Session` carries fields no config key names (`tools`,
# `emit`, `stream`, `headless`, `tier`) and `_config` accepts keys that are not `Session`
# fields (`provider`, `theme`, `stats`, `plugin`), so neither side holds the intersection and
# a derivation would have to restate it anyway.
RELOADABLE = ("fs", "log_debug", "self_learning", "shell")

# The profile-sourced half, read out of the `[providers.<name>]` entry the session is ON
# rather than out of the file's root. Reloadable because each is read off the session at the
# POINT OF USE - `core._turns` hands `model` and `effort` to the provider on every call and
# `run_agent` reads `max_turns` per run - where `url`, `adaptor` and `api_key` were closed
# over by the `provider:<name>` service at plugin import and cannot move without
# re-registering a service mid-session. So a profile has a reloadable half and a
# launch-fixed one; ADR-0018 carries the amendment.
RELOADABLE_PROFILE = ("max_turns", "model", "effort")

# Which of `RELOADABLE` this run took from the COMMAND LINE rather than from the file.
# `DISABLED_BY_FLAG`'s reason, and `DISABLED_BY_FLAG`'s technique: the difference between what
# was parsed and what the file said IS what the flag contributed, so no flag spelling, type,
# default or choice is restated here. Written by `main` after `parse_args`, the last point the
# two sources are still apart; read by `slash.reload_` as a MODULE attribute.
#
# A flag passing the value the file already carried leaves no difference and is not recorded.
# Harmless: the two agreed, so a later edit moving it is what was asked for.
SET_BY_FLAG: frozenset[str] = frozenset()


def reloadable(root: Path, provider: str = "") -> dict[str, object]:
    """The reloadable keys as the file now has them, minus anything a flag decided.

    Two halves. `RELOADABLE` is read from the file's ROOT; `RELOADABLE_PROFILE` from the
    `[providers.<name>]` entry named by `provider`, which is the profile the session is
    running ON - `main` is the only other reader of that table and it resolves the same
    name. Naming none, which is what a caller with no session can do, reads no profile at
    all rather than falling back to the main one: a session may have been launched on
    another, and moving the main profile's values onto it would be worse than moving
    nothing.

    For `/reload`, which re-reads `.un/config.toml` mid-session and never saw the command
    line. Raises ValueError naming the file and the key, which the caller returns as text:
    `_config` validated this file at launch and nothing has validated an edit since.

    The expected type is the type of `Session`'s own field default, the same derivation
    `_config` makes from an argparse default. Neither restates a type.

    A key the file does not carry is LEFT OUT rather than reset to `Session`'s default.
    Deleting a line and never having written one are the same file, so a reset would move a
    session on the strength of something the file cannot say.

    An unknown root key is NOT refused here. That check needs the parser's dests, which `main`
    builds inline, and `_config` already makes it at launch - so a typo reaches the operator as
    exit 2 on the next run rather than blocking the keys this does own.
    """
    path = Path(root) / CONFIG
    if not path.is_file():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    out: dict[str, object] = {}
    for key, value in raw.items():
        # `--max-turns` is `max_turns` as a dest, `_config`'s normalisation: a key spelled
        # after the flag that declares it must not read differently here than at launch.
        dest = key.replace("-", "_")
        if dest not in RELOADABLE or dest in SET_BY_FLAG:
            continue
        if dest == "self_learning":
            # A TABLE since the pruner moved into it, so `_config`'s own reader for it rather
            # than a type check here - a second copy is how two readers of one file come to
            # disagree about what it says.
            out[dest] = _self_learning(path, value)
            continue
        expected = type(getattr(Session, dest))
        # `type` rather than `isinstance`, `_config`'s reason: bool is a subclass of int, and
        # `max_turns = true` is a mistake worth reporting.
        if type(value) is not expected:
            raise ValueError(
                f"{path}: {key} must be {expected.__name__}, not {type(value).__name__}")
        out[dest] = value

    # `providers` has already type- and value-checked the whole table, and it RAISES the
    # same ValueError this function's callers already handle - so a malformed profile edit
    # is reported as text and nothing above is applied, which is why it runs after the root
    # loop has only built a dict.
    #
    # A falsy value is a profile naming none - `effort`'s `""`, `max_turns`'s 0 - and is
    # left out for the reason the root loop leaves out an absent key: it cannot say what a
    # session should move to.
    for profile in providers(Path(root)):
        if profile.name != provider:
            continue
        for dest in RELOADABLE_PROFILE:
            if dest not in SET_BY_FLAG and (value := getattr(profile, dest)):
                out[dest] = value
    return out


def _validate_disable(name: str, stock: frozenset[str],
                      aftermarket: frozenset[str]) -> None:
    """Raise unless `name` names something --disable-plugin can actually disable.

    Three refusals, reported apart, because a single message would send someone looking in
    the wrong place. The first comes first because it is about a name nobody MAY act on
    rather than one nobody can, so a protected name is never reported as merely unknown.

    The second is migration, not validation: a qualified `shell_access` was how a stock
    plugin used to be named, and falling through to "no plugin" would send someone hunting
    for a name they typed correctly under the old spelling.

    A name is looked up in both groups at once, `plugin_table` having already refused to
    start when the two claim the same one. Raises ValueError, which `main` turns into
    EXIT_USAGE.
    """
    if name in UNDISABLEABLE:
        raise ValueError(f"{name} cannot be disabled: it is what enforces {_ENFORCES[name]}. Every plugin but {', '.join(sorted(UNDISABLEABLE))} stays disableable.")
    if ":" in name:
        raise ValueError(
            f"{name!r} is not a plugin name: a plugin is named by one bare word now, "
            f"the one `un plugins` prints. Available: {_available(stock, aftermarket)}")
    if name in stock or name in aftermarket:
        return
    raise ValueError(
        f"no plugin {name!r}; available: {_available(stock, aftermarket)}")


def _validate_enable(name: str, stock: frozenset[str],
                     aftermarket: frozenset[str]) -> None:
    """Raise unless `name` names an aftermarket plugin `enable_plugin` can turn on.

    A stock name is reported apart from an unknown one because it is not a typo: the plugin
    exists and is already running, so "no plugin" would send someone hunting for something
    they named correctly. Stock loading with no config entry is what separates the groups.
    """
    if name in stock:
        raise ValueError(
            f"{name} is a stock plugin and loads without being enabled; enable_plugin "
            f"names aftermarket plugins only. Installed aftermarket plugins: "
            f"{', '.join(sorted(aftermarket)) or 'none'}")
    if name in aftermarket:
        return
    raise ValueError(
        f"no plugin {name!r}; available: {_available(stock, aftermarket)}")


def _available(stock: frozenset[str], aftermarket: frozenset[str]) -> str:
    """Every name --disable-plugin takes. Spelled once, for two messages above."""
    return ", ".join(sorted(stock | aftermarket))


def _confirm_stock(name: str, stock: frozenset[str]) -> bool:
    """Challenge a stock plugin being disabled for one run. True to go ahead.

    Only a flagged name reaches here. Warned every time, and asked only when someone is
    there to answer: on a piped `un chat` the next line of stdin is the user's prompt, not
    an answer to a question nobody asked.

    Provenance is a lookup rather than a spelling. With one bare name for every plugin, the
    group an entry point sits in is the only thing that knows - which is what makes it a
    fact a third party cannot forge.
    """
    if name not in stock:
        return True
    print(f"warning: {name} disables a stock plugin for this run.\n"
          f"  to make it permanent and silence this warning, put it in {CONFIG}:\n"
          f'    disable_plugin = ["{name}"]', file=sys.stderr)
    if not sys.stdin.isatty():
        return True
    # Prompt on stderr and read stdin, so stdout stays a clean stream of the answers.
    print("continue? [y/N] ", end="", flush=True, file=sys.stderr)
    return sys.stdin.readline().strip().lower() == "y"


def main(argv: list[str] | None = None) -> int:
    # `common` is built before anything is loaded: it declares what a config file may set,
    # so it has to exist before the file can be checked against it. It depends on nothing a
    # plugin provides, so building it early is free.
    common = argparse.ArgumentParser(add_help=False)
    # Defaults are read off Session, not restated: a flag default and a declared field
    # default are one fact.
    # `default=None`, not `Session.model`: `new_session` reads None as "nobody asked",
    # which is what lets a `[providers.<name>]` entry supply the model. A flag carrying the
    # default would arrive set on every run and the profile could never win.
    common.add_argument("--model", default=None)
    # `default=None` for `--model`'s reason, one line up, so
    # `[providers.<name>].effort` can supply the value.
    common.add_argument("--effort", default=None, choices=EFFORTS)
    common.add_argument("--provider", default=Session.provider)
    # rat-tail: the default is spelled here rather than read off `theme.DEFAULT`, because
    # this module must not import a plugin. Two copies of one word; move it to `core` if a
    # third appears.
    #
    # Declared even though nothing in `cli` reads it: `_config` derives the keys a config
    # file may set from this parser's dests, so this line is what makes `theme = "nord"` a
    # legal key.
    common.add_argument(
        "--theme", default="default",
        help="which skin the interactive surface renders with, read from "
             ".un/themes/<name>.toml",
    )
    common.add_argument(
        "--fs", default=Session.fs,
        help="which filesystem backend the file tools act through",
    )
    common.add_argument(
        "--shell", default=Session.shell,
        help="which shell backend commands run through",
    )
    common.add_argument(
        "--approval", default=Session.approval,
        help='who answers an "ask" verdict: cli prompts the terminal, '
             "yes approves everything",
    )
    common.add_argument(
        "--history", default=Session.history,
        help="which send-time filter trims the conversation before it is sent; "
             "the default sends every message",
    )
    # `default=None` for `--model`'s reason two lines up, so `[providers.<name>].max_turns`
    # can supply the value and "not passed" stays distinguishable from "passed the default".
    # 0 is a real bound here where it names none in a profile, which is what that
    # distinction buys: a run that starts a session and completes no turn.
    common.add_argument("--max-turns", type=int, default=None)
    common.add_argument(
        "--log-debug", action="store_true", default=Session.log_debug,
        help="keep each tool result in the session record in full, rather than "
             "bounding it",
    )
    common.add_argument(
        "--self-learning", action=argparse.BooleanOptionalAction,
        default=Session.self_learning,
        help="learn from your own sessions: a small model notes in the background what "
             "looks worth keeping as you work. It writes nothing to memory or skills "
             "itself and never asks, since nobody is waiting on it",
    )
    common.add_argument(
        "--plugin", action="append", default=[], metavar="MODULE",
        help="import an extra plugin module that is not an entry point (repeatable)",
    )
    common.add_argument(
        "--disable-plugin", action="append", default=[], metavar="NAME", dest="disable_plugin",
        help="skip a plugin by the name `un plugins` prints (repeatable). A stock "
             "plugin is warned about and, on a terminal, confirmed first; "
             f"{', '.join(sorted(UNDISABLEABLE))} cannot be skipped at all",
    )
    common.add_argument(
        "--enable-plugin", action="append", default=[], metavar="NAME",
        dest="enable_plugin",
        help="load an aftermarket plugin for THIS RUN by the name `un plugins` prints "
             "(repeatable). It writes nothing; `un plugins enable NAME` is the permanent "
             "form and edits .un/config.toml",
    )
    common.add_argument(
        "--stats", action="store_true",
        help="print what the turn cost, including cache reads",
    )

    try:
        config = _config(common)
        # An explicitly passed flag still wins, by argparse's own precedence.
        # `set_defaults` mutates the action objects and `parents=[common]` shares them, so
        # every subparser sees this - including the verbs plugins contribute below.
        common.set_defaults(**config)
        _preload(argv, config)
        # AFTER `_preload`, because the loader checks an operator `Tool(...)` rule against
        # the registry and nothing is registered until the plugins are imported. Inside
        # this `try`, so a mistyped file reaches the operator as EXIT_USAGE, and BEFORE the
        # parser dispatches, because a run that starts and then refuses every tool is
        # indistinguishable from a broken model.
        #
        # `set_defaults` on a dest no action declares puts the tier on the namespace
        # without creating a flag - ADR-0003 held from both ends: the value reaches every
        # subparser, and `--tier` does not exist to override it.
        common.set_defaults(
            tier=use("permissions", "load")(project_root() or Path.cwd()))
    except ValueError as exc:
        # Reported by return rather than SystemExit, because main() is called directly
        # from tests. Nothing has been imported yet - `_preload` checks every name first -
        # so a launch that failed validation cannot have been half-honoured.
        print(exc, file=sys.stderr)
        return EXIT_USAGE

    parser = argparse.ArgumentParser(prog="un", description="A plugin-first agent harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", parents=[common], help="one-shot prompt")
    chat.add_argument("prompt", nargs="?")
    chat.set_defaults(run=_chat)

    resume = sub.add_parser("resume", parents=[common], help="continue a saved session")
    resume.add_argument("session_id")
    resume.add_argument("prompt")
    resume.set_defaults(run=_resume)

    workflow = sub.add_parser("run", parents=[common], help="run a workflow")
    workflow.add_argument("name")
    workflow.add_argument("argv", nargs="*")
    workflow.set_defaults(run=_workflow)

    plugins = sub.add_parser("plugins", parents=[common],
                             help="list plugins, or turn one on or off")
    plugins.set_defaults(run=_plugins)
    # NOT `required`: `un plugins` with no verb still lists. A verb is the permanent
    # decision; the listing is how you find the name to give it.
    verbs = plugins.add_subparsers(dest="plugin_verb")
    for verb in ("enable", "disable"):
        toggled = verbs.add_parser(
            verb, parents=[common], help=f"{verb} a plugin permanently, in {CONFIG}")
        toggled.add_argument("name", metavar="NAME")
        toggled.set_defaults(run=_plugin_toggle)

    # Verbs contributed by plugins, discovered the same way everything else is.
    for name, fn in variants("command").items():
        doc = (fn.__doc__ or "").strip().splitlines()
        added = sub.add_parser(name, parents=[common], help=doc[0] if doc else None)
        # A verb declares its own positionals and flags by carrying `arguments(parser)`.
        if arguments := getattr(fn, "arguments", None):
            arguments(added)
        added.set_defaults(run=fn)

    args = parser.parse_args(argv)
    # What the COMMAND LINE decided, as distinct from what the file did. Recorded here because
    # this is the last point the two are still apart - `_preload` records `DISABLED_BY_FLAG` at
    # its own such point, for the same reason and by the same difference.
    global SET_BY_FLAG
    SET_BY_FLAG = frozenset(
        key for key in RELOADABLE + RELOADABLE_PROFILE
        # `common.get_default`, not `Session`'s own field: three flags declare
        # `default=None` so a profile can supply the value, and comparing that None against
        # `Session.model` would mark every one of them flag-set on every launch - which
        # reads as nothing and silently stops `/reload` moving any of them.
        #
        # `common` rather than `parser`, and the difference is not cosmetic: every one of
        # these dests is declared on `common` and reaches the verbs through
        # `parents=[common]`, so the top-level parser holds none of these actions and
        # `parser.get_default` answers None for all of them - which marks the four ROOT keys
        # flag-set on every launch and kills the half of `/reload` that worked before.
        if getattr(args, key) != config.get(key, common.get_default(key)))
    # Every verb but `install` reads or writes something under the project's `.un/`, so a
    # run outside a project is refused ONCE here rather than per verb, which is a rule the
    # next verb forgets. `install` is the exemption because it CREATES the `.un/` this
    # looks for; exempted by VERB rather than by state, since it is idempotent.
    #
    # AFTER `parse_args` so `--help` and a usage error still answer, and BEFORE `args.run`
    # so no verb starts work it cannot finish. The message names the remedy.
    if args.command != "install" and project_root() is None:
        print("un: no .un/ here or in any parent directory; "
              "run `un install` to set this project up", file=sys.stderr)
        return EXIT_USAGE
    try:
        return args.run(args)
    except KeyboardInterrupt:
        # Every verb, not only the agent ones: a catch narrow enough to name those would
        # leave the rest of the CLI printing a traceback for the same key.
        print("un: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except RecordUnavailable as exc:
        # A plugin that was asked to record could not: a run that dies without naming its
        # cause is indistinguishable from a crash, and this one is an operator's to fix.
        print(f"un: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except Denied as exc:
        # A headless deny, raised out of the agent loop. Caught HERE rather than in
        # `run_terminal`, because `un run` and every plugin-contributed verb reach the loop
        # too. The reason is already `<rule id>: <why>`, so an operator reading CI output
        # can see which rule stopped the run.
        print(exc, file=sys.stderr)
        return EXIT_FAILED


def run() -> None:
    raise SystemExit(main())
