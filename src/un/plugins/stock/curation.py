"""Shared bookkeeping for the skill and memory curation passes: one JSON state file per collection under `.un/learning/` (ADR-0027).

Registers nothing, so any plugin can import it. Usage stamps live here, never in the artefact being measured.
"""

from __future__ import annotations

import json
import tomllib
from datetime import datetime, timedelta, timezone
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
AFTER_DAYS = "retire_after_days"
ENABLE = "enable"

# Memory table only: arms the reviser, which rewrites memories (ADR-0017). Off by default.
REVISE = "revise"
DEFAULT_REVISE = False

DEFAULT_EVERY_DAYS = 7
DEFAULT_AFTER_DAYS = 30

# Renamed keys, refused by name with their replacement.
MOVED = {"every_hours": EVERY_DAYS, "archive_after_days": AFTER_DAYS}

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

# `seeded` starts a clock and judges nothing; `retired` means the artefact was moved.
SEEDED = "seeded"
RETIRED = "retired"

VISIBILITY = "visibility"


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


def settings(root: Path, target: str) -> tuple[int, int] | tuple[int, int, bool]:
    """One collection's `[self_learning.curate.<target>]`: (every_days, retire_after_days), plus `revise` for memory. Zeros mean off.

    The table's presence opts in; `enable = false` parks it. Every early return keeps the target's tuple width.
    """
    off = (0, 0, DEFAULT_REVISE) if target == MEMORY else (0, 0)

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
            f"runs once a session and both its keys are in days. The defaults moved with the "
            f"names: {EVERY_DAYS} = {DEFAULT_EVERY_DAYS}, {AFTER_DAYS} = {DEFAULT_AFTER_DAYS}.")

    # Likewise: `revise` on the skills table is misplaced, not unknown.
    if target != MEMORY and REVISE in entry:
        raise ValueError(
            f"{path}: {table_name(target)} has {REVISE!r}, which is {table_name(MEMORY)}'s key - "
            f"it arms the reviser over the memory collection and there is no skill equivalent")

    allowed = {EVERY_DAYS, AFTER_DAYS, ENABLE} | ({REVISE} if target == MEMORY else set())
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

    every = _positive(path, target, EVERY_DAYS, entry.get(EVERY_DAYS, DEFAULT_EVERY_DAYS))
    after = _positive(path, target, AFTER_DAYS, entry.get(AFTER_DAYS, DEFAULT_AFTER_DAYS))
    # Last, so a parked table is validated too: a parked typo still waits for them.
    if target != MEMORY:
        return (every, after) if on else off
    return (every, after, revise) if on else off


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


def transitions(names: list[str], eligible: set[str], records: dict, now: datetime,
                after_days: int) -> list[tuple[str, str, str]]:
    """What this pass changes, as (name, action, reason). Pure: no disk, no clock.

    Every name without a valid record is seeded; only `eligible` names are judged, and never on the pass that seeds them. Driven by `names`, so records for missing artefacts are ignored.
    """
    cutoff = now - timedelta(days=after_days)
    out = []
    for name in names:
        record = records.get(name)
        if not isinstance(record, dict):
            out.append((name, SEEDED, "first seen; its clock starts now"))
            continue
        if name not in eligible:
            continue
        stamps = [stamp for stamp in (parse(record.get("last_use_at")),
                                      parse(record.get("first_seen_at"))) if stamp is not None]
        anchor = max(stamps) if stamps else None
        # No readable stamp is no evidence, so nothing is retired.
        if anchor is None or anchor > cutoff:
            continue
        # Truthiness, not `int`: a hand-edited `uses` must not raise.
        seen = f"last read {anchor.date().isoformat()}" if record.get("uses") else "never read"
        out.append((name, RETIRED, f"{seen}; older than {after_days} days"))
    return out


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
        # Reported, not raised: this runs inside SessionStart.
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


def apply(session: Session, state: dict, key: str, kind: str, source_of,
          decided: list[tuple[str, str, str]], now: datetime) -> list[str]:
    """Apply the decisions to `state` and perform the retirements; return one line per retirement. The caller saves `state`.

    `source_of` maps a name to its path. `last_run_at` is stamped even when nothing changed.
    """
    records = state.get(key)
    if not isinstance(records, dict):
        # Hand-edited state that is not a mapping is reset, not raised on.
        records = state[key] = {}
    notes = []
    for name, action, reason in decided:
        if action == SEEDED:
            record = records.get(name)
            if not isinstance(record, dict):
                record = records[name] = {"uses": 0, "last_use_at": None}
            record["first_seen_at"] = now.isoformat()
            continue
        landed = retire(session, kind, name, source_of(name), action, reason)
        if isinstance(landed, str):
            # The record stays, so the next pass retries.
            session.report(f"{kind}: curate", landed)
            continue
        records.pop(name, None)
        notes.append(f"{name} - {reason}; archived at {landed}")
    state["last_run_at"] = now.isoformat()
    # rat-tail: only the last pass is kept.
    state["last_run"] = [{"name": n, "action": a, "reason": r} for n, a, r in decided]
    return notes
