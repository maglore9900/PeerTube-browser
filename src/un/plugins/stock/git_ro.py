"""The GitRo tool: read-only git, as an allowlist rather than a forwarder.

Every token after the subcommand must exactly match that subcommand's flag table; the only model bytes reaching git are one revision and pathspecs after `--`, both judged by the permission table before the spawn. `PINS` and `SAFE` close the routes by which repository config or attributes could name a program to run. git's output and error text are judged too: listed paths go through the deny table, patch segments survive only when the listing predicted their header, formats un cannot filter per path come back whole or not at all, and refusals are announced by rule, never by path. See `docs/project/plans/108-git-ro-argument-surface.md`.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from un import Session, core, tool, use
from un.core import DEFAULT_TIMEOUT, spawn_child
# By name: `_reply` binds a local `output`, which would shadow the module.
from un.plugins.stock.output import CAP_SENTENCE, capped

# What this plugin loses while another is disabled; `core.load` reports it.
UN_DEGRADED_WITHOUT = {"file_system": "GitRo does not announce the paths it withheld"}

RECORD, CONTENT, OPAQUE, BY_CALL = "record", "content", "opaque", "by-call"

# Announced as a rule: display output no listed path accounts for is withheld.
UNATTRIBUTED = "GitRo: output no path could be attributed to"

# Per subcommand: flag -> the output kind it selects, or None when it does not choose a format. Keys are also the literals emitted into argv.
SUBCOMMANDS = {
    "status": {"-s": RECORD, "--short": RECORD, "-b": None, "--branch": None, "--porcelain": RECORD},
    "diff": {"--cached": None, "--staged": None, "--stat": OPAQUE, "--name-only": RECORD, "--name-status": RECORD},
    "log": {"--oneline": BY_CALL, "-p": CONTENT, "--patch": CONTENT, "--stat": OPAQUE, "-n": None},
    "show": {"--stat": OPAQUE, "--name-only": RECORD},
    "blame": {"-w": None, "-C": None, "-M": None, "-L": None},
}

# The kind of a call naming no format flag.
BARE = {"status": OPAQUE, "diff": CONTENT, "log": BY_CALL, "show": CONTENT, "blame": BY_CALL}
# Non-format flags change which paths are in scope, so the listing invocation carries them too.
SELECTORS = frozenset(flag for flags in SUBCOMMANDS.values() for flag, kind in flags.items() if kind is None)
# Subcommands that take a revision before `--`, and a pathspec after it.
REV = frozenset({"diff", "show"})
PATHSPEC = frozenset({"diff", "log", "blame"})

# Flags taking a value: the pattern it must fullmatch, and the hint shown to the model.
VALUED = {"-n": (r"\d+", "count"), "-L": (r"\d+,\d+", "start,end")}

# The machine-readable form whose paths are judged, per subcommand.
LISTING = {"status": ("--porcelain", "-z"), "diff": ("--name-status", "-z"), "log": ("--name-status", "-z", "--format="), "show": ("--name-status", "-z", "--format="), "blame": ("--porcelain",)}

# On every invocation. The first keys and `--no-pager` stop config naming a program to run; the rest keep path spelling and diff headers in the form un judges. git ignores unknown `-c` keys.
PINS = ("--no-pager", "-c", "core.fsmonitor=false", "-c", "diff.external=", "-c", "log.showSignature=false", "-c", "color.ui=never",
        "-c", "core.quotePath=false", "-c", "status.relativePaths=false", "-c", "diff.relative=false",
        "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false", "-c", "diff.srcPrefix=a/", "-c", "diff.dstPrefix=b/")

# Per subcommand: `--no-textconv` is the only way to block a textconv driver un cannot name in a pin.
SAFE = {"status": (), "diff": ("--no-ext-diff", "--no-textconv"), "log": ("--no-ext-diff", "--no-textconv"), "show": ("--no-ext-diff", "--no-textconv"), "blame": ("--no-textconv",)}


def _refuse(message: str) -> None:
    raise ValueError(f"git_ro: {message}; this tool is read-only, "
                     "ask the user to run it")


def _refused(session: Session, target: str) -> str:
    """The deny rule refusing `target` to GitRo, or "". Also checks the part after the first colon, since `HEAD:.env` names `.env`."""
    judge = use("permissions", "denied_path")
    return next((rule for candidate in (target, *target.split(":", 1)[1:])
                 if (rule := judge(session, "GitRo", candidate))), "")


def _usage() -> str:
    """The accepted surface as prose for the tool description, generated from the tables."""
    shown = []
    for sub, flags in SUBCOMMANDS.items():
        spelled = [f"{flag} <{VALUED[flag][1]}>" if flag in VALUED else flag for flag in flags]
        slots = (" [<rev>]" if sub in REV else "") + (" [-- <path>]" if sub in PATHSPEC else "")
        shown.append(f"{sub} [{' | '.join(spelled)}]{slots}")
    return "; ".join(shown)


class Call(NamedTuple):
    """One accepted call. `rev` and `paths` are the only model strings that reach argv."""

    sub: str
    flags: tuple[str, ...]  # keys of `SUBCOMMANDS[sub]`, in table order
    values: dict[str, str]  # `-n` / `-L` values, re-rendered from parsed integers
    rev: str | None
    paths: tuple[str, ...]


def _free(token: str, slot: str) -> None:
    """Refuse a revision or path that git could read as an option, pathspec magic (leading `:`), or a glob."""
    if not token:
        _refuse(f"an empty {slot} names nothing")
    for byte, named in (("\0", "a NUL"), ("\n", "a newline"), ("\r", "a carriage return")):
        if byte in token:
            _refuse(f"{token!r} is not an allowed {slot}; it contains {named}")
    if token[0] in "-:":
        _refuse(f"{token!r} is not an allowed {slot}; it begins with {token[0]!r}")
    if set(token) & set("*?["):
        _refuse(f"{token!r} is not an allowed {slot}; git expands a pattern to paths un never judged")


def _value(matched: str) -> str:
    """Re-render a valued flag's digits from parsed integers, so none of the model's bytes are forwarded."""
    return ",".join(str(int(part)) for part in matched.split(","))


def _accept(args: list[str]) -> Call:
    """Parse `args` against the subcommand's table without spawning anything; refuse anything not in it."""
    if not args:
        _refuse(f"no subcommand was given; args[0] must name one of {', '.join(SUBCOMMANDS)}")
    sub, rest = args[0], list(args[1:])
    if sub not in SUBCOMMANDS:
        _refuse(f"{sub!r} is not an allowed subcommand; args[0] must name one of "
                f"{', '.join(SUBCOMMANDS)}")
    table = SUBCOMMANDS[sub]
    taken: list[str] = []
    values: dict[str, str] = {}
    rev: str | None = None
    paths: list[str] = []
    pathspec = False
    index = 0
    while index < len(rest):
        token = rest[index]
        index += 1
        if pathspec:
            _free(token, "path")
            paths.append(token)
        elif token == "--":
            if sub not in PATHSPEC:
                _refuse(f"{sub!r} takes no path; only {', '.join(sorted(PATHSPEC))} read a pathspec after '--'")
            pathspec = True
        elif token in table:
            # At most one format flag, or argv order would decide which git honours.
            if table[token] is not None and (chosen := next((flag for flag in taken if table[flag] is not None), "")):
                _refuse(f"{token!r} and {chosen!r} both choose an output format; name at most one")
            taken.append(token)
            if token in VALUED:
                pattern, hint = VALUED[token]
                if index >= len(rest):
                    _refuse(f"{token!r} needs a <{hint}> value")
                value = rest[index]
                index += 1
                if not re.fullmatch(pattern, value):
                    _refuse(f"{value!r} is not a valid <{hint}> for {token!r}")
                values[token] = _value(value)
        elif token.startswith("-"):
            _refuse(f"{token!r} is not an allowed flag for {sub!r}")
        elif sub not in REV:
            _refuse(f"{sub!r} takes no revision; only {', '.join(sorted(REV))} take one")
        elif rev is not None:
            _refuse(f"{token!r} is a second revision; {sub!r} takes at most one")
        else:
            # A revision: `show HEAD:.env` names a file, so it is shape-gated like a path.
            _free(token, "revision")
            rev = token
    return Call(sub, tuple(flag for flag in table if flag in taken), values, rev, tuple(paths))


def _kind(call: Call) -> str:
    """How this call's output is judged: its format flag's kind, else the subcommand's bare kind, with two exceptions."""
    if call.sub == "blame" and {"-C", "-M"} & set(call.flags):
        # These name the source path of copied or moved lines, which the call never named.
        return OPAQUE
    if call.sub == "show" and call.rev is not None and ":" in call.rev:
        return BY_CALL
    return next((kind for flag in call.flags if (kind := SUBCOMMANDS[call.sub][flag]) is not None),
                BARE[call.sub])


def _argv(call: Call, *, listing: bool) -> list[str]:
    """Build the command line in a fixed order, so the listing and display invocations share hardening and operands."""
    argv = ["git", *PINS, call.sub]
    for flag in call.flags:
        if listing and flag not in SELECTORS:
            continue
        argv.append(flag)
        if flag in call.values:
            argv.append(call.values[flag])
    argv.extend(SAFE[call.sub])
    if listing:
        argv.extend(LISTING[call.sub])
    if call.rev is not None:
        argv.append(call.rev)
    if call.paths:
        argv.append("--")
        argv.extend(call.paths)
    return argv


def _toplevel(session: Session) -> Path:
    """The repository top level (nearest `.git` above `session.cwd`), which git's output paths are relative to under `PINS`."""
    # rat-tail: wrong for a bare repository; `git rev-parse --show-toplevel` would cost a spawn per call.
    return next((directory for directory in (session.cwd, *session.cwd.parents) if (directory / ".git").exists()), session.cwd)


class Record(NamedTuple):
    """One listing entry: git's status field and its paths - one, (origin, destination) for a rename or copy, or none for the `-b` branch header."""

    status: str
    paths: tuple[str, ...]


def _records(sub: str, out: str) -> list[Record]:
    """Parse a `-z` listing. `status` and the `--name-status` forms place a rename's second path differently; missing it would desync the parse and fail open. A truncated last record is dropped."""
    fields = [field for field in out.split("\0") if field]
    records, index = [], 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if sub != "status":
            wanted = 2 if field[:1] in ("R", "C") else 1
            if index + wanted <= len(fields):
                records.append(Record(field, tuple(fields[index:index + wanted])))
            index += wanted
        elif field.startswith("##"):
            records.append(Record(field, ()))
        elif field[:2].strip()[:1] in ("R", "C") and index < len(fields):
            records.append(Record(field[:2], (fields[index], field[3:])))
            index += 1
        else:
            records.append(Record(field[:2], (field[3:],)))
    return records


_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\", '"': '"'}


def _unquote(token: str) -> str:
    """Decode git's C-quoted path form, which git still uses for quotes, backslashes and control bytes despite `core.quotePath=false`. Unquoted tokens and malformed escapes pass through; never raises."""
    if len(token) < 2 or not token.startswith('"') or not token.endswith('"'):
        return token
    body, out, index = token[1:-1], [], 0
    while index < len(body):
        char = body[index]
        index += 1
        if char != "\\" or index >= len(body):
            out.append(char)
        elif body[index] in _ESCAPES:
            out.append(_ESCAPES[body[index]])
            index += 1
        elif len(octal := body[index:index + 3]) == 3 and set(octal) <= set("01234567"):
            # One code point per octal, not one byte; the result is only judged, never shown.
            out.append(chr(int(octal, 8)))
            index += 3
        else:
            out.append(char)
    return "".join(out)


def _listed(sub: str, out: str) -> list[Record]:
    """The listing output as records. `blame --porcelain` is not a `-z` form: its paths come from (possibly C-quoted) `filename ` lines."""
    if sub == "blame":
        named = dict.fromkeys(_unquote(line[len("filename "):]) for line in out.splitlines() if line.startswith("filename "))
        return [Record("", (path,)) for path in named]
    return _records(sub, out)


def _filtered(session: Session, records: list[Record]) -> tuple[list[Record], Counter[str]]:
    """The records the deny table leaves, and refusals counted per distinct path by rule. A rename with either path refused is dropped whole."""
    top = _toplevel(session)
    verdicts = {path: _refused(session, str(top / path)) for record in records for path in record.paths}
    return [record for record in records if not any(verdicts[path] for path in record.paths)], Counter(filter(None, verdicts.values()))


def _render(call: Call, records: list[Record]) -> list[str]:
    """The surviving records in git's own spelling for the form the call asked for."""
    lines = []
    for record in records:
        if not record.paths:
            lines.append(record.status)
        elif "--name-only" in call.flags:
            lines.append(record.paths[-1])
        elif call.sub == "status":
            lines.append(f"{record.status} {' -> '.join(record.paths)}")
        else:
            lines.append("\t".join((record.status, *record.paths)))
    return lines


def _headers(records: list[Record]) -> set[str]:
    """The whole `diff --git` header line each record predicts. Compared whole, because a header cannot be split reliably on ` b/`."""
    return {f"diff --git a/{record.paths[0]} b/{record.paths[-1]}" for record in records if record.paths}


def _attributed(out: str, allowed: set[str], known: set[str]) -> tuple[list[str], int]:
    """The display lines whose segment header is allowed, and a count of segments matching no listed record, which are withheld."""
    blocks: list[list[str]] = [[]]
    for line in out.splitlines():
        if line.startswith("diff --git "):
            blocks.append([])
        blocks[-1].append(line)
    preamble, *segments = blocks
    shown, unattributed = [], 0
    if any(line.strip() for line in preamble):
        # Commit metadata passes; any other text before the first header (such as `show <blobid>`) is file content and is withheld.
        if preamble[0].startswith("commit "):
            shown.extend(preamble)
        else:
            unattributed += 1
    for segment in segments:
        if segment[0] in allowed:
            shown.extend(segment)
        elif segment[0] not in known:
            unattributed += 1
    return shown, unattributed


def _withheld_format(call: Call) -> str:
    """The line standing in for withheld OPAQUE output, naming the format and never a path."""
    named = next((flag for flag in call.flags if SUBCOMMANDS[call.sub][flag] is not None), call.sub)
    return f"[{named}: the whole output was withheld; un cannot filter this format per path]"


def _stderr(session: Session, err: str, refused: Counter[str]) -> str:
    """git's error text, or "" when any token in it names an existing path the deny table refuses. Dropped whole, since messages span lines."""
    # rat-tail: splits on whitespace, so a path containing a space is missed.
    top = _toplevel(session)
    hit = False
    # Strip surrounding punctuation and quoting; count each distinct path once.
    for token in dict.fromkeys(_unquote(word.lstrip("'(").rstrip("',;:.)")) for word in err.split()):
        if not token or token.startswith("-") or not (top / token).exists():
            continue
        if rule := _refused(session, str(top / token)):
            refused[rule] += 1
            hit = True
    return "" if hit else err


def _withheld(refused: Counter[str]) -> list[str]:
    """The withheld notice, which `fs` owns. Imported only while file_system is enabled, since importing it would load it."""
    if "file_system" in core.DISABLED:
        return []
    from un.plugins.stock.fs import withheld
    return withheld(refused)


def _reply(session: Session, done: subprocess.CompletedProcess[str], out: str, refused: Counter[str]) -> str:
    """Assemble the reply: surviving output and judged error text under the output cap, then the refusal notice, then a non-zero exit status. `[no output]` only when nothing was refused."""
    # Judged first, so its refusals are in the notice.
    channel = _stderr(session, done.stderr.rstrip(), refused)
    # Cut before the notice, so the notice can never fall into the omitted middle.
    body = capped("\n".join(part for part in (out, channel) if part))
    output = "\n".join(([body] if body else []) + _withheld(refused))
    if done.returncode == 0:
        return output or "[no output]"
    return f"{output}\n[exit status {done.returncode}]".strip()


def _run(session: Session, argv: list[str], deadline: float) -> subprocess.CompletedProcess[str]:
    """One spawn against a deadline shared by the whole call."""
    try:
        return spawn_child(argv, cwd=session.cwd, timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise ValueError(f"git timed out after {DEFAULT_TIMEOUT}s") from None


def _judge(session: Session, call: Call) -> str:
    """Run the invocations this call's kind needs, listing first, and judge every path git emitted."""
    kind = _kind(call)
    deadline = time.monotonic() + DEFAULT_TIMEOUT
    if kind == BY_CALL:
        # The only path is the one the call named, already judged.
        done = _run(session, _argv(call, listing=False), deadline)
        return _reply(session, done, done.stdout.rstrip(), Counter())
    listing = _run(session, _argv(call, listing=True), deadline)
    records = _listed(call.sub, listing.stdout)
    kept, refused = _filtered(session, records)
    if kind == RECORD:
        # Rendered from the listing; no second spawn.
        return _reply(session, listing, "\n".join(_render(call, kept)), refused)
    if kind == OPAQUE and refused:
        # rat-tail: all or nothing; `--stat` lines could be aligned with records and filtered individually.
        return _reply(session, listing, _withheld_format(call), refused)
    done = _run(session, _argv(call, listing=False), deadline)
    if kind == OPAQUE:
        return _reply(session, done, done.stdout.rstrip(), refused)
    shown, unattributed = _attributed(done.stdout, _headers(kept), _headers(records))
    if unattributed:
        refused[UNATTRIBUTED] += unattributed
    return _reply(session, done, "\n".join(shown), refused)


@tool(
    "GitRo",
    "Run a read-only git command in the session directory and return its output. `args` is a git "
    "command line as a list: the first element names a subcommand and the rest are flags and "
    "paths. Only the subcommands and flags listed here are accepted, exactly as spelled, and "
    "nothing else reaches git - there is no raw git and no way to pass a flag that is not below. "
    f"{CAP_SENTENCE} {_usage()}",
    {
        "type": "object",
        "properties": {
            "args": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["args"],
    },
)
def git_ro(*, session: Session, args: list[str]) -> str:
    """Accept the call, judge its operands before any spawn, then run git and judge its output."""
    if any("\0" in arg for arg in args):
        _refuse("an argument cannot contain a NUL byte")
    call = _accept(args)
    for operand in ([call.rev] if call.rev is not None else []) + list(call.paths):
        if rule := _refused(session, operand):
            _refuse(f"{operand!r} is a path {rule} refuses")
    return _judge(session, call)
