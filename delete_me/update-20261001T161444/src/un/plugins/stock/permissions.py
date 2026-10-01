"""Guard rails on tool use: one PreToolUse hook over three tables, walked deny-first.

No off switch: `cli._validate_disable` refuses `--disable-plugin permissions`. The operator
surface is `.un/config.toml` (`[permissions]`: one boolean per togglable policy, plus
`dangerous_allow`; `[sandbox]`: off by default, and when on, confinements that deny rather
than ask) and `.un/permissions.toml` (operator rules). Absent means built-ins at their
defaults; malformed refuses to start and names itself.

Fail closed on import as much as on no match. See
docs/adr/0001-enforcement-fails-closed.md.

Taking a command apart is `un.core`; every decision about the result stays here.

Read in this order: `DENY_COMMANDS` and its two siblings, `POLICIES`, `_LADDER` and
`evaluate`, `_floor`, `_registered_tool`, `read_permissions`.

Writes: nothing.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

import un
from un import ALLOW, ASK, DENY, REGISTRY, Session, Verdict, hook, service
from un.core import (CONFIG, Fragment, INTERPRETERS, LONGOPT, OAUTH, OPACITY, OPAQUE,
                     RESERVED_TOOL, SESSIONS, SHELL_EXEC, SHELL_EXEC_WHY, UN_DIR,
                     parsed, spawn_child, without_heredocs)

# --- module constants ----------------------------------------------------------

_PKG = Path(un.__file__).parent
_UN_ROOT = _PKG.parent.parent
PATH_TOOLS = frozenset({"Read", "Write", "Edit", "Glob", "Grep", "AstGrep"})
# Whose RULES may name a path, which is wider than whose CALLS are judged by one.
# `GitRo` turns one call into many paths and asks `denied_path` per result, the way
# `Grep` and `Glob` do - but its CALL names no path, and `_registered_tool` skips every
# member of `PATH_TOOLS`, so joining that set would cost the tool the allow that makes
# it usable and send every call to the tier. `Rule.parse` reads this one.
PATH_RULE_TOOLS = PATH_TOOLS | {"GitRo"}
# Membership means this tool's `pattern` IS the path it names. `Grep` and `AstGrep` also
# declare `pattern`, but theirs is a SEARCH EXPRESSION: read as a path it would bind
# nothing against the credential globs and refuse ordinary searches. A tool absent from
# here is not believed, which is the direction ADR-0001 fails in.
PATTERN_IS_PATH = frozenset({"Glob"})
# What a tool searches when it names no `path`. rat-tail: a literal, because the default
# lives on the Python signature rather than in the JSON schema. Kept true to `fs.grep`'s
# `path: str = "."` by hand; the two can drift.
NO_PATH = {"Grep": "."}
COMMAND_TOOLS = frozenset({"Bash"})

# The fourth matcher. A workflow is not a tool, so `Tool(...)` is not made to say it is:
# `Workflow(<name>)` claims ONE file-authored workflow by the name `un run` takes.
WORKFLOW_TOOL = "Workflow"

# What a LAUNCH is gated under, which is deliberately NOT the name of the `Workflow` tool.
# The two are separate calls and each is gated once: the agent loop gates the TOOL call,
# where `_registered_tool` allows it like any stock tool, and `workflows._file_workflow`
# gates the LAUNCH under this name, which no tool holds so it falls to the tier. One name
# for both would ask the operator the same question twice for one launch, which is how a
# person learns to answer without reading it.
WORKFLOW_LAUNCH = "WorkflowLaunch"
_RULE = re.compile(r"^(\w+)\(([^)]*)\)$")
BUILT_IN_TOOLS = ("Read", "Grep", "Glob", "Write", "Edit", "AstGrep")
# The credential policies are generated across THIS tuple rather than the one above.
# `GitRo` returns file contents from a repository, so the four policies have to answer
# for its name - a rule generated for a name nothing asks under never fires, and a name
# asked under with no rule generated for it answers "" forever. See plan 108.
CREDENTIAL_TOOLS = BUILT_IN_TOOLS + ("GitRo",)
WRITE_TOOLS = ("Write", "Edit")
READONLY_PROGRAMS = ("ls", "cat", "echo", "pwd", "head", "tail", "wc", "which", "stat",
                     "du", "find", "diff")

# Everything that ENFORCES permissions, as paths: what DECIDES a verdict, what APPLIES
# one, what PERFORMS the action a verdict judged, what decides whether enforcement runs
# at all, and the two files an operator configures it with.
_PROTECTED = (
    # The two directories. No `/**` suffix: each matches the DIRECTORY and not its
    # contents, so `rm -rf <un>` is refused while `<un>/plugins/stock/repl.py` is writable.
    "<un>",
    "**/.un",
    # ---- decide the verdict ----
    "<un>/__init__.py",                             # re-exports the whole vocabulary
    "<un>/core.py",                                 # Verdict, decide, fire, Session.tier,
                                                    # the agent loop that applies one, and
                                                    # what a command IS before any rule
    "<un>/plugins/stock/permissions.py",            # the table, and evaluate
    "<un>/plugins/stock/hooks.py",                  # a hook's exit code -> a Verdict
    "<un>/plugins/stock/workflows.py",              # imports and runs agent-authored code
    "<un>/plugins/stock/scopes.py",                 # a subagent's tool scopes: grammar and DENY
    # ---- apply it ----
    # The loop that executes a judged call lives in `core.py`, already named above.
    "<un>/plugins/stock/approval.py",               # ANSWERS ask; rewriting it says yes
    "<un>/plugins/stock/allow_rule.py",             # WRITES the allow array on a keypress
    # ---- perform the action it judged ----
    "<un>/plugins/stock/shell.py",
    "<un>/plugins/stock/fs.py",
    # ---- decide whether enforcement runs at all ----
    "<un>/plugins/stock/cli.py",                    # UNDISABLEABLE, load(), the tier
    "<un_root>/pyproject.toml",                     # declares un.plugins.stock
    # ---- the operator's inputs ----
    "**/.un/permissions.toml",
    "**/.un/config.toml",
    "**/.un/agents/**",
    "**/.un/hooks/**",
    "<un>/plugins/stock/plugin_config.py",
)

ASSUMED_ASK = "assumed_ask"
# Like `ASSUMED_ASK`: a table key rather than a decision `evaluate` can return. Its rung
# returns ALLOW, and keeping the table apart is what stops un's own default from being
# indistinguishable from an operator's `allow` line - `load` never touches this one.
PROJECT_READ = "project_read"
_DERIVED = {"write": ("Write", "Edit"), "read": ("Read", "Grep", "Glob", "AstGrep")}
_WHY_MENTION = "names the code that enforces permissions; an operator edits it by hand"
_SHADOWING = frozenset({
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PATH",
})
_WHY_SHADOW = ("places code ahead of the un package on a search path, so the module that "
               "enforces permissions is not the one on disk")
_CD = frozenset({"cd", "pushd"})
_WHY_CD = "enters a directory holding the code that enforces permissions"
_ARG_WIDTH = 120

TIERS = {"strict": ASK, "dangerous": ALLOW}

# The stock package, taken from THIS module's own position rather than spelled as a
# literal. The trailing dot is the whole discriminator: without it `un.plugins.stockade`
# is admitted as stock.
_STOCK_PREFIX = f"{__package__}."
_WHY_REGISTERED = "a tool un ships; the rules above are what qualify it"

PERMISSIONS = UN_DIR / "permissions.toml"

_ARRAYS = {"deny": DENY, "ask": ASK, "allow": ALLOW}

_REMEMBERING = threading.Lock()


# --- the command surface -------------------------------------------------------
#
# What each Bash policy MATCHES, keyed by the policy's name - which is also its key in
# `[permissions]`. Three dicts, one per LEVEL; the KEY supplies `Policy.name` and the DICT
# supplies `Policy.decision`.
#
#   why       operator-facing prose, rendered after the rule text on a refusal. Lowercase,
#             no trailing period - it is a clause, not a sentence.
#   commands  `Rule` specs WITHOUT the `Bash(...)` wrapper. Nothing here is a regex.
#   note      OPTIONAL. Rendered above the key in a scaffolded `.un/config.toml`, saying
#             what turning the key OFF does.
#   toggle    OPTIONAL, default True. False is the FLOOR: no key, nothing turns it off.
#
# PATH policies stay hand-written in `POLICIES`, matching globs against paths rather than
# commands.

_COMMAND_FIELDS = frozenset({"why", "commands", "note", "toggle"})

DENY_COMMANDS = {
    # ---- floor: no toggle key, and nothing that lowers it ----
    "privilege_escalation": {
        "why": "escalates beyond what you were asked to do; ask the user to run it",
        "commands": ["sudo", "doas"],
        "toggle": False,
    },
    # rat-tail: `--a*` over-denies a long option `un` does not have, and costs one rule
    # instead of one per abbreviation of `--approval`.
    "approval_bypass": {
        "why": "this flag lets the run answer its own approvals",
        "commands": ["un:--a*"],
        "toggle": False,
    },
    # `un update` rewrites un's own code, this table included, from whatever path it is handed.
    "update_bypass": {
        "why": "replaces un's own code, the permission table included; ask the user to run it",
        "commands": ["un:update"],
        "toggle": False,
    },
    # Ahead of `git_read_only`, so `git -c ...` is refused by the rule that says WHY
    # rather than by the blanket one. `core.pager` is a shell command.
    "git_execution": {
        "why": "reaches arbitrary execution or a file write THROUGH git",
        "commands": ["git:-c", "git:--config-env", "git:--exec-path", "git:--output"],
        "toggle": False,
    },

    # ---- togglable: one boolean each in `[permissions]` ----
    "git_read_only": {
        "why": "raw git is restricted; the GitRo tool is the read-only route",
        "commands": ["git"],
        "note": "An agent driving git can make unrecoverable mistakes like stashing changes and dropping them. While this is enabled git is blocked for agents and they are provided a read only wrapper called git_ro.py instead.",
    },
    # Shaped after `git_read_only`, for the same reason: the program is denied WHOLE and a
    # gated tool is what makes the denial survivable. ADR 0002 kept `grep` out of
    # `READONLY_PROGRAMS` and named the `Grep` tool instead; this enforces that position.
    #
    # By PROGRAM, not by flag: `grep --recursive` carries no short flag for a `grep:-r`
    # rule to match, and a rule that misses the ordinary spelling reads as coverage.
    "grep_read_only": {
        "why": "raw grep reads whole files and un cannot judge what it returns; the Grep tool is the searching route",
        "commands": ["grep", "rg"],
        "note": "Not all system greps are the same, some are aliased to ugrep, and the possible combinations of grep and the ability to modify files with args is too much of a risk. Agents are provided with a sytem tool (Grep) which is a wrapper and ensures read only. With grep_read_only enabled all other greps are blocked for agent use and only Grep is available. It is unlikely you will need to disable this.",
    },
    # Separate from `grep_read_only` deliberately: nothing here has a tool that replaces
    # it, so sharing one key would mean restoring `tar` to get `cmd | grep x` back.
    #
    # `tar cf - .` settles the by-program question: `cf` lands in `operands`, where a
    # `tar:-c` rule looks in `short`, so a flag-scoped rule fails OPEN on it.
    "deny_bulk_read": {
        "why": "reads a whole tree without naming a file, so no path rule can judge what comes back",
        "commands": ["tar", "rsync", "zip"],
        "note": "This means that an agent could read sensitive contents like credentials. It is difficult to block every permutation of various system tools, so the tools themselves are blocked. Agents are provided Glob and ASTGrep. Disabling deny_bulk_read removes this.",
    },
    "deny_rm_recursive": {
        "why": "a recursive force delete cannot be undone; move it aside instead",
        "commands": ["rm:-rf"],
    },
    "deny_find_destructive": {
        "why": "find acts on everything it matched, without showing you first",
        "commands": ["find:-delete", "find:-exec", "find:-execdir", "find:-ok", "find:-okdir",
                     "find:-fprint", "find:-fprint0", "find:-fprintf", "find:-fls"],
        "note": "false lets -delete, -exec, -execdir, -ok and -okdir delete files or run any command, and -fprint, -fprint0, -fprintf and -fls overwrite any file, including .un/permissions.toml. Each is then allowed without asking.",
    },
    "deny_find_credentials": {
        "why": "lists the files in a directory that holds credentials",
        "commands": ["find:.ssh", "find:.ssh/", "find:*/.ssh", "find:*/.ssh/"],
        "note": "false lets find list the files in a .ssh directory; reading them stays refused either way. Only a find that names the directory is caught: a find over a parent directory still lists what is inside.",
    },
    "deny_destructive_disk": {
        "why": "formats, repartitions or wipes a disk; there is nothing to undo",
        "commands": ["mkfs*", "newfs_*", "wipefs", "diskutil", "hdiutil", "parted",
                     "fdisk", "gdisk", "sgdisk", "cryptsetup", "zpool",
                     "pvcreate", "vgcreate", "lvcreate", "gpt", "asr",
                     "dd:/dev/*"],
        "note": "false lets mkfs, parted, diskutil and the rest run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
    "deny_system_power": {
        "why": "powers down or restarts the machine, ending this session and everything else on it",
        "commands": ["shutdown", "reboot", "halt", "poweroff"],
        "note": "false lets these run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
    "deny_infra_teardown": {
        "why": "tears down infrastructure that is not rebuilt by re-running the command",
        "commands": ["terraform:destroy", "kubectl:delete", "aws:s3,rm,--recursive"],
        "note": "false lets terraform destroy and kubectl delete run as ordinary unlisted programs, so strict asks about them rather than refusing.",
    },
}

ASSUMED_ASK_COMMANDS: dict[str, dict] = {
    "ask_in_place_edit": {
        "why": "edits a file in place, so the previous contents are gone",
        "commands": ["sed:-i", "perl:-pi"],
    },
    "ask_recursive_mode": {
        "why": "changes permissions or ownership over a whole tree",
        "commands": ["chmod:-R", "chown:-R"],
    },
    "ask_force_overwrite": {
        "why": "overwrites the destination without asking",
        "commands": ["mv:-f", "cp:-f", "truncate"],
    },
    "ask_process_kill": {
        "why": "terminates a process that may not be this session's",
        "commands": ["kill:-9", "pkill", "killall"],
    },
    "ask_service_control": {
        "why": "stops or disables a system service",
        "commands": ["systemctl:stop", "systemctl:disable"],
    },
}

ALLOW_COMMANDS = {
    "allow_readonly_commands": {
        "why": "These are safe read-only commands that are already allowed for agents, meaning you do  not need to add entries into permission.toml",
        "commands": list(READONLY_PROGRAMS),
        "note": "Disabling allow_readonly_commands will result in every one becoming a Ask unless you add entries in permission.toml.",
    },
}


# --- rules -----------------------------------------------------------------------

# HOME is passed through to every child unchanged (`core.PASS_THROUGH`), so the shell expands it to the value un holds.
_HOME_VAR = re.compile(r"^(?:\$HOME|\$\{HOME\})(?=/|$)")


def _home_expanded(word: str) -> str:
    home = os.environ.get("HOME")
    return _HOME_VAR.sub(lambda _: home, word, count=1) if home else word


def _resolve(session: Session, path: str) -> Path:
    candidate = Path(_home_expanded(path))
    # The shell expands a leading `~`; judged literally, `~/x` reads as inside the project.
    try:
        candidate = candidate.expanduser()
    except RuntimeError:
        # An unknown `~user` is left literal by the shell too.
        pass
    if not candidate.is_absolute():
        candidate = session.cwd / candidate
    return candidate.resolve()

@dataclass(frozen=True)
class Rule:
    """One entry in the table, and the thing a verdict names.

    `text` is the rule as written, `why` is operator-facing prose, and `unless` comes down
    from the rule's GROUP so the grammar stays one glob per rule.
    """

    text: str
    tool: str
    spec: str
    why: str = ""
    negated: bool = False
    program: str = ""
    short: frozenset[str] = frozenset()
    long: tuple[str, ...] = ()
    operands: tuple[str, ...] = ()
    unless: tuple[str, ...] = ()

    @classmethod
    def parse(cls, text: str, why: str = "", unless: tuple[str, ...] = ()) -> "Rule":
        "`tool(spec)`, rejecting anything no matcher can decide."
        match = _RULE.match(text.strip())
        if not match:
            raise ValueError(f"{text!r} is not a rule: expected tool(spec)")
        tool, spec = match.group(1), match.group(2)
        if tool == RESERVED_TOOL:
            # All-or-nothing for one tool, by NAME. Not registry-checked here, because
            # `parse` runs at import before any tool has registered.
            if ":" in spec:
                raise ValueError(
                    f"{text!r}: a Tool rule takes a name only, not a spec")
            # Emptiness is judged AFTER stripping, or `Tool( )` claims a tool no name
            # can equal.
            if not (spec := spec.strip()):
                raise ValueError(f"{text!r}: names no tool")
            return cls(text, tool, spec, why, unless=unless)
        if tool == WORKFLOW_TOOL:
            # A name only, for `Tool`'s reason one branch up: there is nothing inside a
            # launch for a spec to select on, so a colon is a rule that can never match.
            if ":" in spec:
                raise ValueError(
                    f"{text!r}: a Workflow rule takes a name only, not a spec")
            if not (spec := spec.strip()):
                raise ValueError(f"{text!r}: names no workflow")
            return cls(text, tool, spec, why, unless=unless)
        if tool in PATH_RULE_TOOLS:
            negated = spec.startswith("!")
            return cls(text, tool, spec[1:] if negated else spec, why, negated,
                       unless=unless)
        if tool not in COMMAND_TOOLS:
            raise ValueError(f"{text!r}: no matcher decides {tool!r}")
        program, colon, terms = spec.partition(":")
        if not program:
            raise ValueError(f"{text!r}: names no program")
        if colon and not terms:
            raise ValueError(f"{text!r}: empty term")
        short: set[str] = set()
        long: list[str] = []
        operands: list[str] = []
        single_dash_is_long = program in LONGOPT
        for term in terms.split(",") if terms else []:
            if not term:
                raise ValueError(f"{text!r}: empty term")
            if term.startswith("--") or (single_dash_is_long and term.startswith("-")):
                long.append(term.lstrip("-"))
            elif term.startswith("-"):
                short.update(term[1:])
            else:
                operands.append(term)
        return cls(text, tool, spec, why, False, program,
                   frozenset(short), tuple(long), tuple(operands), unless)

    @property
    def names_path(self) -> bool:
        "Whether this rule names a PATH, as opposed to a program or a tool."
        return (self.tool in PATH_TOOLS
                or (self.tool in COMMAND_TOOLS and bool(self.operands)))


def _substitute(spec: str, session: Session) -> str:
    """Resolve the tokens a static glob cannot spell, then anchor what is still relative. Resolved per CALL, so the table stays shareable and a session that changed directory holds no stale rule.

    A spec that is none of absolute, wildcard-led or token-led is a RELATIVE one, and `_path_matches` resolves the TARGET absolutely - so left alone an operator who wrote `deny = ["Read(src/**)"]` would have blocked nothing. Anchored on `session.root` rather than `cwd`, because a rule's meaning is a fact about the PROJECT.

    The test runs AFTER substitution, so `<` survives only for a token nothing here recognises. Every built-in path spec begins with `/`, `*` or `<`, so this branch is unreachable for all of them.
    """
    root = session.root.resolve().as_posix()
    resolved = (spec.replace("<cwd>", session.cwd.resolve().as_posix())
                    .replace("<project>", root)
                    .replace("<sessions>", SESSIONS.as_posix())
                    .replace("<oauth>", OAUTH.as_posix())
                    .replace("<un_root>", _UN_ROOT.as_posix())
                    .replace("<un>", _PKG.as_posix()))
    if resolved[:1] in ("/", "*", "<"):
        return resolved
    # `./src/**` is the same intent as `src/**`; joined unstripped it produces a `/./`
    # segment that `fnmatch` compares literally against a resolved target with none.
    return f"{root}/{resolved.removeprefix('./')}"


def _fragment_matches(rule: Rule, frag: Fragment) -> bool:
    "One bash rule against one fragment: head MATCHED, and EVERY term present."
    return (bool(rule.program)
            and bool(frag.head)
            and fnmatch.fnmatch(frag.head, rule.program)
            and rule.short <= frag.short
            and all(any(fnmatch.fnmatch(name, term) for name in frag.long)
                    for term in rule.long)
            and all(any(fnmatch.fnmatch(word, term) for word in frag.operands)
                    for term in rule.operands))


def _globbed(resolved: str, pattern: str) -> bool:
    "One resolved path against one glob."
    return (fnmatch.fnmatch(resolved, pattern)
            or (pattern.endswith("/**") and fnmatch.fnmatch(resolved, pattern[:-3])))


def _path_matches(rule: Rule, session: Session, target: str) -> bool:
    """One resolved path against one glob, honouring `unless`, `!` and the tokens."""
    if not target:
        return False
    resolved = _resolve(session, target).as_posix()
    # Ahead of the rule's own glob AND of the inversion: `unless` says this rule does not
    # CLAIM the path, which is different from "matched, then negated". A rule that let go
    # here has no opinion, so the rest of the table is still asked.
    if any(_globbed(resolved, _substitute(spec, session)) for spec in rule.unless):
        return False
    hit = _globbed(resolved, _substitute(rule.spec, session))
    return not hit if rule.negated else hit


def _tool_claims(rule_tool: str, name: str) -> bool:
    """Whether a rule written for `rule_tool` speaks for a call to `name`.

    An `Edit` reads a file, replaces one occurrence and writes it back, so a rule about
    WRITING that path is about the edit too. Never the reverse: `Write` creates files and
    parent directories and truncates whole ones, and an `Edit` rule naming a path grants
    no such thing.

    Global rather than operator-only because there is no built-in rule it can reach: every
    built-in `Write` spec is generated by `_across`, which already emits the `Edit` twin.
    """
    return rule_tool == name or (name == "Edit" and rule_tool == "Write")


_GLOB = ("*", "?", "[")


def _widened(item: str, rule: Rule) -> str:
    """An operator's path spec naming a directory covers what is inside it.

    Operator rules only - `_PROTECTED`'s two directory entries carry no `/**` precisely so
    they match the directory and not its contents, which is what refuses `rm -rf <un>`
    while leaving un's own non-enforcement code writable. A spec that already carries a
    glob is what the operator meant, and an EMPTY spec is left alone: `/**` would match
    every path there is.

    Returns the rule TEXT for the caller to re-parse, so `text` and `spec` cannot disagree
    and `Rule.parse` stays the only place that knows what a rule is.
    """
    if rule.tool not in PATH_TOOLS or not rule.spec or any(g in rule.spec for g in _GLOB):
        return item
    return f"{rule.tool}({'!' if rule.negated else ''}{rule.spec.rstrip('/')}/**)"


def _target(name: str, args: dict) -> str:
    """The path an argument dict names, for the tool it names it for.

    By tool, because `pattern` means two things: the path `Glob` will list, and the
    expression `Grep` will match. A tool with neither gets the empty string, which
    `_path_matches` refuses outright.
    """
    if path := args.get("path"):
        return path
    if name in PATTERN_IS_PATH:
        return args.get("pattern") or ""
    return NO_PATH.get(name, "")


# --- policies ------------------------------------------------------------------


def _across(tools: tuple[str, ...], *specs: str) -> tuple[str, ...]:
    """One rule per tool per spec. The table's only repetition, written once."""
    return tuple(f"{tool}({spec})" for spec in specs for tool in tools)


@dataclass(frozen=True)
class Policy:
    "One reason, and every rule that exists for it."

    name: str
    decision: str
    why: str
    rules: tuple[str, ...]
    toggle: bool = True
    unless: tuple[str, ...] = ()
    note: str = ""


def _command_policies(decision: str, entries: dict[str, dict]) -> tuple[Policy, ...]:
    "One `Policy` per entry, the key as its name and `decision` as its decision."
    built = []
    for name, entry in entries.items():
        if unknown := entry.keys() - _COMMAND_FIELDS:
            raise ValueError(f"{name!r}: unknown field(s) {sorted(unknown)}")
        if not entry.get("why"):
            raise ValueError(f"{name!r}: names no reason")
        commands = entry.get("commands")
        if not commands:
            raise ValueError(f"{name!r}: names no commands")
        if isinstance(commands, str):
            raise ValueError(f"{name!r}: commands is a string, not a list of them")
        # An `ASSUMED_ASK` has no key BY DEFINITION, so the class decides rather than
        # every entry repeating `"toggle": False`.
        if decision == ASSUMED_ASK and entry.keys() & {"toggle", "note"}:
            raise ValueError(f"{name!r}: an assumed ask has no toggle key")
        built.append(Policy(
            name, decision, entry["why"],
            tuple(f"Bash({command})" for command in commands),
            toggle=decision != ASSUMED_ASK and entry.get("toggle", True),
            note=entry.get("note", "")))
    return tuple(built)


POLICIES = (
    # ---- floor: no toggle key, and nothing that lowers it ----
    Policy("enforcement_code", DENY,
          "the code that enforces permissions; an operator edits it by hand",
          _across(WRITE_TOOLS, *_PROTECTED), toggle=False),
    # ---- every command deny, generated ----
    *_command_policies(DENY, DENY_COMMANDS),
    Policy("env_files", DENY, "usually holds credentials",
          _across(CREDENTIAL_TOOLS, "**/.env*"), toggle=False,
          unless=("**/.env.example", "**/.env.sample", "**/.env.template")),
    Policy("private_keys", DENY, "a private key or ssh identity",
          _across(CREDENTIAL_TOOLS, "**/*.pem", "**/.ssh/*", "**/id_rsa*", "**/id_ecdsa*",
                  "**/id_ed25519*"),
          toggle=False),
    Policy("credentials", DENY, "usually holds credentials or a registry token",
          _across(CREDENTIAL_TOOLS, "**/*credentials*", "**/.npmrc", "**/.pypirc"),
          toggle=False),
    Policy("oauth_credentials", DENY, "un keeps OAuth bearer tokens here",
          _across(CREDENTIAL_TOOLS, "**/<oauth>/**"), toggle=False),
    Policy("session_record", DENY, "un writes its own transcripts here",
          _across(WRITE_TOOLS, "**/<sessions>/**"), toggle=False),
    # `git_ro_tool`, `session_read_tool` and `candidate_tool` stood here, one floor ALLOW
    # per sanctioned stock tool. `_registered_tool` states the same thing generally, and
    # additionally requires the stock package.

    # ---- togglable: one boolean each in `[permissions]` ----
    Policy("deny_write_git_dir", DENY, "this path is managed by tooling, not by hand",
          _across(WRITE_TOOLS, "**/.git/**")),

    # ---- project reads: un's own default, its own rung, no key ----
    # Nothing else in the table allows it, so every in-project read fell through to the
    # tier's question. The READ tools only: a write inside the project is still asked.
    Policy("project_reads", PROJECT_READ, "inside the project directory",
          _across(_DERIVED["read"], "<project>/**"), toggle=False),

    # ---- assumed ask: un's own defaults, no key and no permissions.toml entry ----
    Policy("ask_outside_project", ASSUMED_ASK, "outside the project directory",
          _across(BUILT_IN_TOOLS, "!<project>/**"), toggle=False),
    Policy("ask_un_dir", ASSUMED_ASK, "un's own configuration directory",
          _across(WRITE_TOOLS, "**/.un/**"), toggle=False),
    *_command_policies(ASSUMED_ASK, ASSUMED_ASK_COMMANDS),
    *_command_policies(ALLOW, ALLOW_COMMANDS),
)

DEFAULT_TOGGLES = {p.name: True for p in POLICIES if p.toggle} | {
    "dangerous_allow": False}


# --- the sandbox ---------------------------------------------------------------
#
# A second table, kept out of `POLICIES` because `DEFAULT_TOGGLES` turns on everything
# togglable and a sandbox is off until asked for. Every entry is a DENY: `evaluate` widens
# an ASK under `dangerous_allow` and leaves a DENY alone, which is what makes this a bound.

_INLINE_CODE = ("python:-c", "python3:-c", "perl:-e", "node:-e", "ruby:-e",
                "python:<<", "python3:<<", "perl:<<", "node:<<", "ruby:<<")

SANDBOX_POLICIES = (
    Policy("confine_outside_project", DENY,
           "the sandbox confines this session to the project directory; release with [sandbox] confine_outside_project = false",
           _across(BUILT_IN_TOOLS, "!<project>/**"),
           note="false restores the pre-sandbox policy: strict asks about paths outside the project and dangerous_allow widens that ask to an allow. Where the un package is installed outside the project, this key is the only thing confining it."),
    Policy("confine_un_dir", DENY,
           "the sandbox protects un's own configuration directory; release with [sandbox] confine_un_dir = false",
           _across(WRITE_TOOLS, "**/.un/**"),
           note="Writes only. Reads inside the project stay allowed either way, so the agent keeps its memory, rules and skills. false restores the pre-sandbox ask on the write."),
    Policy("confine_un_package", DENY,
           "the sandbox protects un's own code; release with [sandbox] confine_un_package = false",
           _across(WRITE_TOOLS, "<un>/**"),
           note="Applies only where the un package sits inside the project directory; elsewhere confine_outside_project covers it. false restores the pre-sandbox policy, which for the unprotected part of the package is no rule at all: strict asks and dangerous_allow allows."),
    Policy("confine_inline_code", DENY,
           "the sandbox refuses inline interpreter code, which names no path for a rule to judge; release with [sandbox] confine_inline_code = false",
           tuple(f"Bash({command})" for command in _INLINE_CODE),
           note="Best effort and nothing more. python3.12 -c, an interpreter not listed here, and writing a script then running it all defeat it. Mode 1 does not contain arbitrary code execution."),
)

DEFAULT_SANDBOX = {"enabled": False, "mode": 1} | {
    policy.name: True for policy in SANDBOX_POLICIES}

_SANDBOX_MODES = (1, 2)
_WHY_MODE_2 = ("[sandbox] mode 2 is reserved for an external sandbox provider and is not "
               "implemented; set mode = 1, or enabled = false to run unconfined")


def _table(decision: str, toggles: dict[str, bool]) -> tuple[Rule, ...]:
    "Every ENABLED rule of one decision, in policy order."
    return tuple(
        Rule.parse(text, policy.why, policy.unless)
        for policy in POLICIES
        if policy.decision == decision and (not policy.toggle or toggles[policy.name])
        for text in policy.rules
    )


DENY_TABLE = _table(DENY, DEFAULT_TOGGLES)
ASK_TABLE = _table(ASK, DEFAULT_TOGGLES)
ALLOW_TABLE = _table(ALLOW, DEFAULT_TOGGLES)
ASSUMED_ASK_TABLE = _table(ASSUMED_ASK, DEFAULT_TOGGLES)
PROJECT_READ_TABLE = _table(PROJECT_READ, DEFAULT_TOGGLES)
_PROTECTED_RULES = tuple(Rule.parse(f"Write({spec})") for spec in _PROTECTED)


def _protected(session: Session, target: str) -> bool:
    "Is this path one of the enforcement entries?"
    return any(_path_matches(rule, session, target) for rule in _PROTECTED_RULES)


def _protected_dir(session: Session, target: str) -> bool:
    "Is this a directory that HOLDS an enforcement entry?"
    resolved = _resolve(session, target)
    return (resolved == _PKG or _PKG in resolved.parents
            or UN_DIR.name in resolved.parts)


def _floor(session: Session, name: str, args: dict,
           frags: list[Fragment]) -> Verdict | None:
    if name in COMMAND_TOOLS and (
            shell := SHELL_EXEC.search(without_heredocs(args.get("command") or ""))):
        return Verdict(DENY, f"shell exec: {SHELL_EXEC_WHY[shell.lastgroup]}")
    for frag in frags:
        if shadowing := frag.assignments & _SHADOWING:
            return Verdict(DENY, f"{sorted(shadowing)[0]}=: {_WHY_SHADOW}")
        if frag.head in _CD:
            for operand in frag.operands:
                if _protected_dir(session, operand):
                    return Verdict(DENY, f"cd {operand}: {_WHY_CD}")
        if frag.head in READONLY_PROGRAMS:
            continue
        for operand in frag.operands:
            if _protected(session, operand):
                return Verdict(
                    DENY, f"{frag.head or '(assignment)'} {operand}: {_WHY_MENTION}")
    return None


def _opaque(session: Session, name: str, args: dict,
            frags: list[Fragment]) -> Verdict | None:
    if name not in COMMAND_TOOLS:
        return None
    if opaque := OPAQUE.search(without_heredocs(args.get("command") or "")):
        return Verdict(ASK, f"opaque: {OPACITY[opaque.lastgroup]}")
    # A heredoc into an interpreter is inline code, as `-c` is.
    if any(frag.head in INTERPRETERS and "<<" in frag.operands for frag in frags):
        return Verdict(ASK, f"opaque: {OPACITY['interpreter']}")
    # A path built from any variable but HOME is only known once the shell runs.
    for frag in frags:
        for word in (*frag.operands, *frag.redirects):
            if "$" in _home_expanded(word):
                return Verdict(ASK, f"opaque: {word} is built from a variable, so the path it names is not known until it runs")
    return None


# --- the four doors ---------------------------------------------------------------


def _verdict(decision: str, rule: Rule | None, word: str = "") -> Verdict | None:
    """A rule as the thing an operator is shown, or `None` when there was no rule. `word` is the command word a path rule matched."""
    if rule is None:
        return None
    reason = f"{rule.text}: {rule.why}"
    if word:
        reason += f"; the command word {_shown(word)} was read as a path"
    return Verdict(decision, reason, rule=rule.text)


def _claims(rule: Rule, session: Session, name: str, args: dict,
            frag: Fragment | None, implied: bool = True) -> bool:
    if rule.tool == WORKFLOW_TOOL:
        # Both halves. The rule's spec must equal the workflow being launched, AND the
        # CALL must be a launch - without the second, `Workflow(deploy)` would also claim
        # a tool called `deploy`, since `_allow_tool` now walks these rules too.
        return name == WORKFLOW_LAUNCH and rule.spec == (args.get("name") or "")
    if rule.tool == RESERVED_TOOL:
        # By EXACT name: tools are PascalCase, so `Bash(grep)` and `Grep` stay apart.
        return rule.spec == name
    if frag is None:
        # `implied` is the caller's PASS, not a property of the rule: an exact tool match
        # is the better explanation of a verdict, so every table is walked for one before
        # the implication is allowed to answer. See `_objection` and `_path_allowed`.
        matched = _tool_claims(rule.tool, name) if implied else rule.tool == name
        return matched and _path_matches(rule, session, _target(name, args))
    if rule.tool in COMMAND_TOOLS:
        return _fragment_matches(rule, frag)
    # A path the COMMAND names, judged by the rules for the operation it is named for,
    # inverted confinement rules included: the same ASK the `read` tool gets, reached by
    # the other route. Asked per FRAGMENT, so the caller chooses its quantifier.
    operation = next((k for k, tools in _DERIVED.items() if rule.tool in tools), None)
    if operation is None:
        return False
    return any(_path_matches(rule, session, path) for path in _judged(frag, operation))


def _judged(frag: Fragment, operation: str) -> tuple[str, ...]:
    """The words of `frag` a derived path rule judges: redirect targets for a write, paths for a read."""
    return frag.redirects if operation == "write" else frag.paths


def _path_word(rule: Rule, session: Session, frags: list[Fragment]) -> str:
    """The command word a derived path rule matched, or "" for any other rule."""
    operation = next((k for k, tools in _DERIVED.items() if rule.tool in tools), None)
    if operation is None:
        return ""
    return next((word for frag in frags for word in _judged(frag, operation)
                 if _path_matches(rule, session, word)), "")


def _objection(session: Session, name: str, args: dict, frags: list[Fragment],
               *, decision: str, table: tuple[Rule, ...]) -> Verdict | None:
    # Exact tool match first, the implication second. A built-in path policy is generated
    # by `_across`, which emits the `Write` spec and its `Edit` twin, so a single walk
    # would report the `Write` one for every `Edit` call and an operator would be shown a
    # rule that is true but is not the entry naming their tool. Both passes carry the same
    # `decision`, so this chooses which rule is REPORTED and never whether one fires.
    # rat-tail: the second pass repeats the walk for tools no implication reaches; the
    # tables are dozens of rules and this runs once per call. Guard it on the tool name if
    # a profile ever says otherwise.
    for implied in (False, True):
        for rule in table:
            # A `Tool` rule names the tool, and a path rule against a path tool names one
            # path, so neither is quantified over fragments.
            if rule.tool == RESERVED_TOOL or name not in COMMAND_TOOLS:
                hit = _claims(rule, session, name, args, None, implied)
            else:
                hit = any(_claims(rule, session, name, args, frag, implied)
                          for frag in frags)
            if hit:
                # A Bash call names no path of its own, so say which word was taken for one.
                word = _path_word(rule, session, frags) if name in COMMAND_TOOLS else ""
                return _verdict(decision, rule, word)
    return None


def _allow_tool(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    # Both claim-by-name rule kinds. `_claims` holds them apart by the call's name, so a
    # `Workflow(x)` rule cannot allow a tool called `x`; this rung is the one that already
    # exists for "a rule naming a thing outright", so neither a new rung nor a new
    # adjacency is introduced.
    return _verdict(ALLOW, next(
        (r for r in ALLOW_TABLE
         if r.tool in (RESERVED_TOOL, WORKFLOW_TOOL)
         and _claims(r, session, name, args, None)), None))


def _allow_program(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    if name not in COMMAND_TOOLS or not frags:
        return None
    found = None
    for frag in frags:
        if frag.redirects:
            return None
        match = next((r for r in ALLOW_TABLE if r.tool in COMMAND_TOOLS
                      and _claims(r, session, name, args, frag)), None)
        if match is None:
            return None
        found = found or match
    return _verdict(ALLOW, found)


def _path_allowed(session: Session, name: str, args: dict, frags: list[Fragment],
                  table: tuple[Rule, ...]) -> Verdict | None:
    """One PATH table against a call: the target a path tool names, or the paths a command does.

    Two rungs share this - `allow_path` over the operator's table and `project_read` over
    un's own. Deliberately NOT an `_objection` walk: `_claims` routes a `Read(...)` rule
    against a Bash call through `_DERIVED` without looking at the fragment head, so it
    would allow `rm src/x.py` on the grounds that its operand is readable.

    EVERY path a call names must be matched, so one unmatched operand withdraws the whole
    verdict rather than allowing the call on the strength of its innocent half.
    """
    if name in PATH_TOOLS:
        target = _target(name, args)
        # Exact tool match first, for the reason `_objection` states.
        for implied in (False, True):
            match = next(
                (rule for rule in table
                 if rule.names_path
                 and (_tool_claims(rule.tool, name) if implied else rule.tool == name)
                 and _path_matches(rule, session, target)), None)
            if match is not None:
                return _verdict(ALLOW, match)
        return None
    if name not in COMMAND_TOOLS or not frags:
        return None
    found = None
    for frag in frags:
        named = {"write": frag.redirects}
        if frag.head in READONLY_PROGRAMS:
            named["read"] = frag.paths
        if not any(named.values()):
            return None
        for operation, paths in named.items():
            for path in paths:
                match = next(
                    (rule for rule in table
                     if rule.names_path
                     and ((rule.tool in _DERIVED[operation]
                           and _path_matches(rule, session, path))
                          or (rule.tool in COMMAND_TOOLS
                              and _fragment_matches(rule, frag)
                              and any(fnmatch.fnmatch(path, term)
                                      for term in rule.operands)))),
                    None)
                if match is None:
                    return None
                found = found or match
    return _verdict(ALLOW, found)


def _allow_path(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _path_allowed(session, name, args, frags, ALLOW_TABLE)


def _project_read(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _path_allowed(session, name, args, frags, PROJECT_READ_TABLE)

def allow_rule(session: Session, name: str, args: dict) -> tuple[str, str]:
    frag = None
    if name in PATH_TOOLS:
        if not (target := _target(name, args)):
            return "", f"{name} named no path"
        text = f"{name}({_resolve(session, target).as_posix()})"
    elif name in COMMAND_TOOLS:
        frags = parsed(args.get("command") or "")
        if len(frags) != 1:
            return "", f"{len(frags)} commands in one call; allow each on its own"
        frag = frags[0]
        if frag.redirects:
            return "", "the command writes through a redirect"
        if not frag.head:
            return "", "the command names no program"
        terms = [f"-{''.join(sorted(frag.short))}"] if frag.short else []
        terms += [f"--{option}" for option in sorted(frag.long)]
        terms += list(frag.operands)
        text = f"Bash({frag.head}:{','.join(terms)})" if terms else f"Bash({frag.head})"
    elif name == WORKFLOW_LAUNCH:
        # One workflow, not every workflow. The fall-through below would spell
        # `Tool(WorkflowLaunch)`, which is what `permissions:remember` would then persist on an
        # "always" answer - authorising the whole of `.un/workflows/`, including files
        # written after the operator answered.
        if not (workflow := str(args.get("name") or "").strip()):
            return "", "the launch names no workflow"
        text = f"{WORKFLOW_TOOL}({workflow})"
    else:
        text = f"Tool({name})"
    try:
        rule = Rule.parse(text)
    except ValueError as exc:
        return "", str(exc)
    if frag is not None and not _fragment_matches(rule, frag):
        return "", f"{text} does not match the command it came from"
    if name in PATH_TOOLS and not _path_matches(rule, session, _target(name, args)):
        return "", f"{text} does not match the path it came from"
    return text, ""


def _shown(value: object, width: int | None = _ARG_WIDTH) -> str:
    """One argument, as the operator reads it. `width` is None to withhold nothing.

    The caller decides, because the two callers want opposite things - see `describe`.
    """
    text = repr(value)
    if width is None or len(text) <= width:
        return text
    return f"{text[:width]}... ({len(text)} chars)"


@service("permissions:denied_path")
def denied_path(session: Session, name: str, path: str) -> str:
    """The DENY rule refusing `name` this path, as `Rule.text` spells it, or `""`.

    For a call that produces MANY paths from one target: `evaluate` judges the target a
    call NAMES, where a `Grep` rooted at `.` returns results from beneath it that no
    verdict ever saw. The table stays here and the seam asks per result.

    By the CALLING tool's name, not by `Read`: the credential policies are generated with
    `_across(BUILT_IN_TOOLS, ...)`, so a `Grep` rule exists beside every `Read` one.
    """
    verdict = _deny(session, name, {"path": path}, [])
    return verdict.rule if verdict else ""


@service("permissions:describe")
def describe(name: str, args: dict, *, full: bool = False) -> str:
    """One call, rendered for a person. `full` keeps every argument whole.

    Cut by DEFAULT, because the caller that fires on every attempted call is `core.gate`'s
    announcement and a `Write` carries a whole file in `content` - uncut, one edit fills the
    turn. `full=True` is for `ask` below: an operator is being asked to authorise this exact
    call, and approving what you cannot read is the failure that costs more than a long line.

    ONE function with a flag rather than two renderers. The operator sees the announcement
    and then the question, so the two must be the same line wherever nothing was withheld.
    """
    width = None if full else _ARG_WIDTH
    return f"{name}({', '.join(f'{k}={_shown(v, width)}' for k, v in args.items())})"


@service("permissions:ask")
def ask(session: Session, name: str, args: dict, verdict: Verdict) -> tuple[str, str]:
    rule, why = allow_rule(session, name, args)
    offer = f"a -> allow {rule}" if rule else f"a -> unavailable: {why}"
    # WHOLE. This is the one place a person decides whether the call runs, and a command cut
    # at `_ARG_WIDTH` is one they are approving unseen.
    return (f"{describe(name, args, full=True)}\n  {verdict.reason}\n  {offer}\n"
            f"Allow it? [{'y/N/a' if rule else 'y/N'}]"), rule


# --- the ladder ------------------------------------------------------------------
#
# The three table rungs are written out rather than built with `functools.partial`: a
# partial binds its `table` argument to the TUPLE OBJECT at import, where `load` REBINDS
# these globals. These read the global at CALL time.


def _deny(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=DENY, table=DENY_TABLE)


def _ask(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=ASK, table=ASK_TABLE)


def _assumed_ask(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict | None:
    return _objection(session, name, args, frags, decision=ASK,
                      table=ASSUMED_ASK_TABLE)


def _registered_tool(session: Session, name: str, args: dict,
                     frags: list[Fragment]) -> Verdict | None:
    """Every tool a STOCK plugin registered, allowed because it is registered.

    The registry is read per CALL rather than folded into a table at load, because
    `core._drop` clears a disabled plugin's registrations mid-session and a table built at
    launch would keep allowing a tool that no longer exists.

    **It answers for the tool NAME, never for a call whose ARGUMENTS un can already judge.**
    A `Tool(NAME)` rule is all-or-nothing, so returning one for `Bash` would allow the
    COMMAND as well and short-circuit every command rule below. So the tools with their own
    argument-level matcher are skipped here and keep being decided by that matcher and then
    by the tier. An operator's `Tool(Bash)` DENY still refuses the tool wholesale.

    The `Workflow` TOOL is not skipped and is allowed here like any other stock tool. What
    an operator is asked about is the LAUNCH, gated separately under `WORKFLOW_LAUNCH`,
    which no tool holds - so it reaches the tier on its own and the two calls cost one
    question between them rather than two.

    Stock only, and that is TWO tests. An aftermarket plugin is opt-in (ADR-0013), so a
    third party's tools stay at the tier's question - the module test. A DROPPED-IN tool
    needs the second: `tools._script_tool` returns a closure defined in this package, so
    its `__module__` is stock however foreign the script it spawns. `un_from_file` is the
    marker `core.scan` already stamps for `plugin_config.listing`.
    """
    if name in COMMAND_TOOLS or name in PATH_TOOLS:
        return None
    registered = REGISTRY["tool"].get(name)
    if registered is None or not registered.__module__.startswith(_STOCK_PREFIX):
        return None
    if getattr(registered, "un_from_file", False):
        return None
    return Verdict(ALLOW, f"{RESERVED_TOOL}({name}): {_WHY_REGISTERED}",
                   rule=f"{RESERVED_TOOL}({name})")


def _tier(session: Session, name: str, args: dict, frags: list[Fragment]) -> Verdict:
    return Verdict(TIERS[session.tier], f"{session.tier}: no rule matched {name}")

_LADDER = (
    ("floor",         _floor),
    ("deny",          _deny),
    ("opaque",        _opaque),
    ("ask",           _ask),
    ("allow_path",    _allow_path),
    # Below the operator's own allows and above the confinement ask: every objection an
    # operator can write outranks un's default.
    ("project_read",  _project_read),
    ("assumed_ask",   _assumed_ask),
    ("allow_tool",    _allow_tool),
    ("allow_program", _allow_program),
    # Below every objection AND below both operator allow rungs, so a rule somebody wrote
    # always names itself. Above `tier` alone, which is why adding it moved no adjacency.
    ("registered_tool", _registered_tool),
    ("tier",          _tier),
)


@hook("PreToolUse")
def evaluate(*, session: Session, name: str, args: dict) -> Verdict:
    default = TIERS[session.tier]
    frags = parsed(args.get("command") or "") if name in COMMAND_TOOLS else []
    verdict = None
    for _, step in _LADDER:
        if verdict := step(session, name, args, frags):
            break
    if verdict.decision == ASK and default == ALLOW:
        # The rule is carried THROUGH the widening: something objected and the tier
        # overruled it, which is a different fact from nothing objecting at all.
        return Verdict(ALLOW, f"{session.tier}: {verdict.reason}", rule=verdict.rule)
    return verdict


# --- the loader ----------------------------------------------------------------
#
# The only part of this module that touches the filesystem. Reading at import would be
# untestable once imported, and would surface a bad file as a traceback rather than as
# EXIT_USAGE.


@dataclass(frozen=True)
class Loaded:
    """One resolved launch configuration: the tier, and the three tables."""

    tier: str
    deny: tuple[Rule, ...]
    ask: tuple[Rule, ...]
    allow: tuple[Rule, ...]


def _toml(path: Path) -> dict:
    """Parse one file, or `{}` when it is not there.

    Absent means the built-ins alone. Malformed is an error named after the file.
    """
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _read_toggles(path: Path) -> dict[str, bool]:
    """`[permissions]` out of `.un/config.toml`, over the defaults.

    Every key must name a policy that HAS a key, so naming a floor policy is an error
    rather than a no-op: an operator writing `env_files = false` and being ignored believes
    they turned something off.
    """
    toggles = dict(DEFAULT_TOGGLES)
    section = _toml(path).get("permissions", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [permissions] must be a table")
    for key, value in section.items():
        if key not in toggles:
            known = ", ".join(sorted(toggles))
            raise ValueError(f"{path}: unknown [permissions] key {key!r}; known: {known}")
        # `type` rather than `isinstance`: a string "false" is a mistake worth reporting
        # rather than a truthy value.
        if type(value) is not bool:
            raise ValueError(
                f"{path}: [permissions] {key} must be a boolean, not {type(value).__name__}")
        toggles[key] = value
    return toggles


def _read_operator_rules(path: Path) -> dict[str, tuple[Rule, ...]]:
    """The three arrays out of `.un/permissions.toml`, parsed and registry-checked.

    An ABSENT array means no additions of that decision, so the result is keyed on what the
    file carried and an absent `ask` does not zero the ask table. The registry check is for
    OPERATOR rules only: a built-in naming an absent tool means a disabled plugin, where an
    operator's typo is the case nothing else will ever report.
    """
    raw = _toml(path)
    out: dict[str, tuple[Rule, ...]] = {}
    for key, value in raw.items():
        if key not in _ARRAYS:
            known = ", ".join(_ARRAYS)
            raise ValueError(f"{path}: unknown key {key!r}; known keys: {known}")
        if not isinstance(value, list):
            raise ValueError(
                f"{path}: {key} must be a list of rule strings, not {type(value).__name__}")
        rules = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"{path}: {key} must be a list of rule strings; got {item!r}")
            try:
                rule = Rule.parse(item)
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            # The malformed case raised above, on the text the operator wrote, so no
            # expansion is ever attempted on something that is not a rule.
            if (widened := _widened(item, rule)) != item:
                rule = Rule.parse(widened)
            if rule.tool == RESERVED_TOOL and rule.spec not in REGISTRY["tool"]:
                known = ", ".join(sorted(REGISTRY["tool"]))
                raise ValueError(
                    f"{path}: {item!r} names no registered tool {rule.spec!r}; registered: {known}")
            rules.append(rule)
        out[key] = tuple(rules)
    return out


def _read_sandbox(path: Path) -> dict:
    """`[sandbox]` out of `.un/config.toml`, over the defaults.

    Shaped after `_read_toggles`: an unknown key is an error rather than a no-op, because an
    operator who misspells a confinement and is ignored believes they released it.
    """
    sandbox = dict(DEFAULT_SANDBOX)
    section = _toml(path).get("sandbox", {})
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [sandbox] must be a table")
    for key, value in section.items():
        if key not in sandbox:
            known = ", ".join(sorted(sandbox))
            raise ValueError(f"{path}: unknown [sandbox] key {key!r}; known: {known}")
        # `type` rather than `isinstance`: a bool IS an int, so `mode = true` would pass.
        if key == "mode":
            if type(value) is not int or value not in _SANDBOX_MODES:
                raise ValueError(f"{path}: [sandbox] mode must be 1 or 2, not {value!r}")
        elif type(value) is not bool:
            raise ValueError(
                f"{path}: [sandbox] {key} must be a boolean, not {type(value).__name__}")
        sandbox[key] = value
    return sandbox


def _sandbox_table(sandbox: dict, cwd: Path) -> tuple[Rule, ...]:
    """Every enabled confinement as a DENY rule, and nothing when the sandbox is off.

    `confine_un_package` applies only where the package sits inside the project; elsewhere `confine_outside_project` reaches it.
    """
    if not sandbox["enabled"]:
        return ()
    inside = _PKG.resolve().is_relative_to(cwd.resolve())
    return tuple(
        Rule.parse(text, policy.why)
        for policy in SANDBOX_POLICIES
        if sandbox[policy.name] and (policy.name != "confine_un_package" or inside)
        for text in policy.rules
    )


def read_permissions(cwd: Path) -> Loaded:
    """Both files in, resolved tables out. Raises ValueError naming the file.

    Nothing is installed until `load` assigns what this produced, so a file that fails
    validation leaves the previous tables exactly as they were.
    """
    toggles = _read_toggles(cwd / CONFIG)
    sandbox = _read_sandbox(cwd / CONFIG)
    # Refused before any table is built; falling back to mode 1 would leave an operator believing they are contained.
    if sandbox["enabled"] and sandbox["mode"] == 2:
        raise ValueError(f"{cwd / CONFIG}: {_WHY_MODE_2}")
    operator = _read_operator_rules(cwd / PERMISSIONS)
    return Loaded(
        tier="dangerous" if toggles["dangerous_allow"] else "strict",
        # Operator rules are ADDED after the built-ins. The tables are walked deny-first,
        # so an operator `allow` cannot displace a floor deny however it is spelled. Sandbox
        # rules sit in the deny rung too, below the floor and above every operator allow.
        deny=(_table(DENY, toggles) + _sandbox_table(sandbox, cwd)
              + operator.get("deny", ())),
        ask=_table(ASK, toggles) + operator.get("ask", ()),
        allow=_table(ALLOW, toggles) + operator.get("allow", ()),
    )


@service("permissions:load")
def load(cwd: Path) -> str:
    """Read and install the launch configuration; return the tier for `cli`.

    Reached through `use` rather than an import, because `cli` must never import a plugin.
    It runs after `_preload`, so every tool a plugin registers is present for the registry
    check above. The three assignments happen together and last, after every raise.
    """
    global DENY_TABLE, ASK_TABLE, ALLOW_TABLE
    loaded = read_permissions(cwd)
    DENY_TABLE, ASK_TABLE, ALLOW_TABLE = loaded.deny, loaded.ask, loaded.allow
    return loaded.tier


@service("permissions:remember")
def remember(session: Session, name: str, args: dict) -> str:
    """Write this call's allow rule, reinstall the tables, and say what happened.

    Never raises: the operator already approved the call, and a failure to remember it must
    not also refuse it. `un.plugins.stock.allow_rule` as a subprocess rather than a write
    here, because it verifies by reading the file back through un's own loader and restores
    the original when that fails.

    **The re-evaluation is the point.** The note says whether the rule took effect rather
    than reporting the write and stopping.
    """
    rule, why = allow_rule(session, name, args)
    if not rule:
        return f"not remembered: {why}"
    with _REMEMBERING:
        try:
            done = spawn_child(
                [sys.executable, "-P", "-m", "un.plugins.stock.allow_rule", rule,
                 "--project", str(session.root), "--quiet"],
                cwd=session.root, timeout=30)
            if done.returncode != 0:
                # The script's own text, not a summary: it names the directory and the
                # reason.
                return f"{rule} was not written: {(done.stderr or done.stdout).strip()}"
            load(session.root)
        except Exception as exc:  # noqa: BLE001 - subprocess and the loader raise several
            # Reported, never swallowed and never re-raised: the approved call still
            # runs, and they are told the rule did not stick.
            return f"{rule} was not remembered: {type(exc).__name__}: {exc}"
        after = evaluate(session=session, name=name, args=args)
    if after.decision != ALLOW:
        return (f"{rule} is in {session.root / PERMISSIONS}, but {name} still asks: "
                f"{after.reason}")
    return f"allowed {rule} in {session.root / PERMISSIONS}; in effect now"
