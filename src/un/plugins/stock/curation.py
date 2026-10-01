"""Shared bookkeeping for the skill and memory curation passes, one JSON state file per collection under `.un/learning/` (ADR-0027), and the runner every background learning pass goes through.

Registers nothing, so any plugin can import it. Curator state lives here, never in the artefact being measured.
"""

from __future__ import annotations

import json
import threading
import tomllib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from un import Session, use
from un.core import CONFIG, locked, un_dir

DIR = "learning"

LEARNING = "self_learning"
CURATE = "curate"
SKILLS = "skills"
MEMORY = "memory"
TARGETS = (SKILLS, MEMORY)
EVERY_DAYS = "every_days"
ENABLE = "enable"

# Memory table only: arms the accuracy auditor and the memory editor, which rewrites memories (ADR-0017). Off by default.
REVISE = "revise"
DEFAULT_REVISE = False

# Memory table only: how many items the accuracy check takes per pass.
CHECK_BATCH = "check_batch"
DEFAULT_CHECK_BATCH = 10

DEFAULT_EVERY_DAYS = 7

# Renamed keys, refused by name with their replacement.
MOVED = {"every_hours": EVERY_DAYS}

# Named here because plugins that cannot import each other share them.
SKILLS_STATE = "skill-curator.json"
MEMORY_STATE = "memory-curator.json"

# `metadata: {author: agent}` marks a skill the agent may amend or retire.
AGENT = "agent"

# Outside `.un/skills/`, or discovery would still find retired skills (ADR-0027).
ARCHIVE = "archive"
RETIREMENTS = "retirements.jsonl"

AMENDMENTS = "amendments.jsonl"
AMENDMENT_DIR = "amendments"

INDEX = "MEMORY.md"

VISIBILITY = "visibility"

# `agents:run` hands a refusal back as text; a reply opening with one of these means the agent never ran.
# rat-tail: matched on wording; a typed refusal from `agents:run` would remove this.
REFUSALS = ("refused:", "the subagent ran no turns")

# The live thread per learning agent, and the (agent, session id) pairs already told that agent is missing.
# rat-tail: per process; a second process wastes a fork, and CandidateMark/CandidatePlace refuse a second write.
_RUNNING: dict[str, threading.Thread] = {}
_REPORTED: set[tuple[str, str]] = set()


def run(session: Session, agent: str, prompt: str, measure: Callable[[], object],
        commit: Callable[[object], None]) -> None:
    """One background pass, synchronously. `measure()` runs before the fork and `commit(before)` only once it returns a reply, so a pass counts by difference; a raising or refused fork is reported (ADR-0023) and commits nothing."""
    before = measure()
    try:
        reply = use("agents", "run")(session, agent, prompt)
    except Exception as exc:  # noqa: BLE001
        session.report(agent, f"{type(exc).__name__}: {exc}")
        return
    if reply.startswith(REFUSALS):
        session.report(agent, reply)
        return
    commit(before)


def absent(session: Session, agent: str, missing: str) -> bool:
    """Whether `agent` cannot run here: a disabled subagents plugin is silent, and a missing agent is reported once per session."""
    try:
        available = use("agents", "names")()
    except LookupError:
        return True
    if agent in available:
        return False
    if (agent, session.id) not in _REPORTED:
        _REPORTED.add((agent, session.id))
        session.report(agent, missing)
    return True


def launch(session: Session, agent: str, missing: str, target: Callable[..., None],
           args: Callable[[], tuple | None]) -> None:
    """Start `target(session, *args())` on a non-daemon thread, one per agent at a time.

    `absent` decides whether the agent can run, and `args()` returning None means there is nothing to do. A thread rather than a lock, so a raising pass cannot wedge it.
    """
    if absent(session, agent, missing):
        return
    running = _RUNNING.get(agent)
    if running is not None and running.is_alive():
        return
    extra = args()
    if extra is None:
        return
    _RUNNING[agent] = thread = threading.Thread(target=target, args=(session, *extra), daemon=False)
    thread.start()


def table_name(target: str) -> str:
    return f"[{LEARNING}.{CURATE}.{target}]"


def path(session: Session, name: str) -> Path:
    return un_dir(session.root, DIR) / name


def archive_dir(session: Session, kind: str) -> Path:
    """Where retired artefacts of one collection go."""
    return path(session, ARCHIVE) / kind


def retirements_path(session: Session) -> Path:
    return path(session, RETIREMENTS)


def by_agent(data: dict) -> bool:
    """Whether a parsed frontmatter mapping has `metadata.author == "agent"`."""
    metadata = data.get("metadata")
    return isinstance(metadata, dict) and metadata.get("author") == AGENT


def pointer(name: str) -> str:
    """The opening of the index line `Remember` writes. To recognise an existing line, use `indexes`."""
    return f"- [{name}]("


def indexes(line: str, name: str) -> bool:
    """Whether this `MEMORY.md` line links to `name.md`, whatever its link text. The `](` and `.md)` stop `a` matching `a-b`."""
    return line.startswith("- [") and f"]({name}.md)" in line


def log(session: Session, row: dict, name: str = RETIREMENTS) -> None:
    """Append one row to a log, under the file lock."""
    target = path(session, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with locked(target), target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def rows(session: Session, name: str) -> list[dict]:
    """Every object row of a log, in order; [] when absent, and never creates the file. Torn or non-object lines are skipped."""
    target = path(session, name)
    if not target.is_file():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def amendments(session: Session) -> list[dict]:
    """Every amendment raised, in order. The plans they index sit in `AMENDMENT_DIR`."""
    return rows(session, AMENDMENTS)


def retirements(session: Session) -> list[dict]:
    """Every retirement, in order."""
    return rows(session, RETIREMENTS)


def load(session: Session, name: str) -> dict:
    """The state, or {} when unreadable. Never raises: an empty state retires nothing."""
    target = path(session, name)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(session: Session, name: str, state: dict) -> None:
    target = path(session, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Locked: stamps arrive from ToolEnd listeners on several worker threads.
    with locked(target):
        target.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _positive(path: Path, target: str, key: str, value) -> int:
    """A whole number above zero, or a ValueError naming the file, table and key. `type`, not `isinstance`: bool is an int."""
    if type(value) is not int or value < 1:
        raise ValueError(
            f"{path}: {table_name(target)}.{key} must be a positive whole number, not {value!r}")
    return value


def settings(root: Path, target: str) -> tuple[int, bool, int] | bool:
    """One collection's `[self_learning.curate.<target>]`: (every_days, revise, check_batch) for memory, where 0 days means off; for skills, whether the table is present and enabled.

    The table's presence opts in; `enable = false` parks it.
    """
    off = (0, DEFAULT_REVISE, DEFAULT_CHECK_BATCH) if target == MEMORY else False

    path = Path(root) / CONFIG
    if not path.is_file():
        return off
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc

    table = raw.get(LEARNING)
    if table is None:
        return off
    if not isinstance(table, dict):
        raise ValueError(f"{path}: [{LEARNING}] must be a table")
    curate = table.get(CURATE)
    if curate is None:
        return off
    if not isinstance(curate, dict):
        raise ValueError(f"{path}: [{LEARNING}.{CURATE}] must be a table of its own")

    moved = sorted(set(curate) - set(TARGETS))
    if moved:
        raise ValueError(
            f"{path}: [{LEARNING}.{CURATE}] is two tables now - {moved[0]!r} belongs in "
            f"{table_name(SKILLS)} or {table_name(MEMORY)}, one per collection")

    entry = curate.get(target)
    if entry is None:
        return off
    if not isinstance(entry, dict):
        raise ValueError(f"{path}: {table_name(target)} must be a table of its own")

    # Before the unknown-key check, so a renamed key gets its specific message.
    for old in sorted(set(entry) & set(MOVED)):
        raise ValueError(
            f"{path}: {table_name(target)} has {old!r}, which is {MOVED[old]!r} now - the pass "
            f"runs once a session and counts in days. The default moved with the name: "
            f"{EVERY_DAYS} = {DEFAULT_EVERY_DAYS}.")

    # Likewise: the memory table's keys on the skills table are misplaced, not unknown.
    if target != MEMORY and REVISE in entry:
        raise ValueError(
            f"{path}: {table_name(target)} has {REVISE!r}, which is {table_name(MEMORY)}'s key - "
            f"it arms the memory editor over the memory collection and there is no skill equivalent")
    for key in (EVERY_DAYS, CHECK_BATCH):
        if target != MEMORY and key in entry:
            raise ValueError(
                f"{path}: {table_name(target)} has {key!r}, which is {table_name(MEMORY)}'s "
                f"key - the skills table takes only {ENABLE!r}")

    allowed = {ENABLE} | ({EVERY_DAYS, REVISE, CHECK_BATCH} if target == MEMORY else set())
    extra = sorted(set(entry) - allowed)
    if extra:
        raise ValueError(
            f"{path}: {table_name(target)} has unknown key {extra[0]!r}; the keys are "
            f"{', '.join(repr(key) for key in sorted(allowed))}")

    on = entry.get(ENABLE, True)
    if type(on) is not bool:
        raise ValueError(f"{path}: {table_name(target)}.{ENABLE} must be true or false, not {on!r}")

    revise = entry.get(REVISE, DEFAULT_REVISE)
    if type(revise) is not bool:
        raise ValueError(
            f"{path}: {table_name(target)}.{REVISE} must be true or false, not {revise!r}")

    if target != MEMORY:
        return on
    # Last, so a parked table is validated too: a parked typo still waits for them.
    every = _positive(path, target, EVERY_DAYS, entry.get(EVERY_DAYS, DEFAULT_EVERY_DAYS))
    batch = _positive(path, target, CHECK_BATCH, entry.get(CHECK_BATCH, DEFAULT_CHECK_BATCH))
    return (every, revise, batch) if on else off


def parse(stamp) -> datetime | None:
    """An ISO stamp, or None when unreadable. Callers treat None as no evidence, not as old."""
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def visible(root: Path) -> bool:
    """Whether the learning loop's notes reach the operator: false only for `[self_learning] visibility = false`. Faults are reported regardless (ADR-0023)."""
    try:
        raw = tomllib.loads((Path(root) / CONFIG).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True
    table = raw.get(LEARNING)
    return not (isinstance(table, dict) and table.get(VISIBILITY) is False)


def free(folder: Path, stem: str, suffix: str) -> Path:
    """The first unused `<stem><suffix>`, `<stem>-2<suffix>`, ... under `folder`, so nothing is overwritten."""
    candidate = folder / f"{stem}{suffix}"
    n = 1
    while candidate.exists():
        n += 1
        candidate = folder / f"{stem}-{n}{suffix}"
    return candidate


def unlink(session: Session, name: str) -> str | None:
    """Remove this memory's line from `MEMORY.md` and return it (for the log), or None if absent. Locked across read and write."""
    target = un_dir(session.root, "memory") / INDEX
    if not target.is_file():
        return None
    with locked(target):
        lines = target.read_text(encoding="utf-8").splitlines()
        removed = next((line for line in lines if indexes(line, name)), None)
        if removed is not None:
            target.write_text("\n".join(l for l in lines if not indexes(l, name)) + "\n",
                              encoding="utf-8")
    return removed


def _announce(session: Session, kind: str, name: str, reason: str, archived_as: str) -> None:
    """Record the retirement in the transcript. `collection=`, because `event` already takes `kind`."""
    try:
        use("session", "event")(session, "curate", collection=kind, name=name, reason=reason,
                                archived_as=archived_as)
    except Exception:  # noqa: BLE001
        pass


def retire(session: Session, kind: str, name: str, source: Path, action: str, reason: str,
           into: str | None = None) -> Path | str:
    """Move one artefact into the archive, unlink a memory's index line, log and announce it. Returns the new path, or an error string.

    The move goes first, so an interruption never leaves an index line pointing at nothing archived. The caller drops the curator record.

    rat-tail: ordered steps, not a transaction; add a journal if a retire must be resumable.
    """
    folder = archive_dir(session, kind)
    folder.mkdir(parents=True, exist_ok=True)
    target = free(folder, source.stem, source.suffix)
    try:
        source.replace(target)
    except OSError as exc:
        # Returned, not raised: `Retire` hands it back as its result.
        return f"could not archive {source} to {target}: {type(exc).__name__}: {exc}"
    line = unlink(session, name) if kind == "memory" else None
    # Relative to the archive root, so the log survives the project moving.
    archived_as = target.relative_to(path(session, ARCHIVE)).as_posix()
    log(session, {
        "at": datetime.now(timezone.utc).isoformat(), "kind": kind, "name": name,
        "archived_as": archived_as, "action": action, "reason": reason,
        "into": into or None, "pointer": line})
    _announce(session, kind, name, reason, archived_as)
    return target

