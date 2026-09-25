"""The learning worklist and its three background passes (ADR-0022).

`CandidateAdd` records a span of a session record worth a closer look; `CandidateMark` and `CandidatePlace` fill in what later passes decided, and nothing is ever removed. `detect`, `admit` and `place` are TurnStart hooks that run the seeded detector, admitter and implementor agents on their own threads, each over an input the pass computes. `Retire` and `Amend` let an agent archive a folded-in artefact or propose a rule change. Independent of `memory`, so either plugin can be disabled.
"""

from __future__ import annotations

from pathlib import Path

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone

from un.core import locked, refused
from un import Session, frontmatter, hook, tool, use
from un.plugins.stock import curation
from un.core import un_dir


# ---------------------------------------------------------------------------
# The candidate worklist
# ---------------------------------------------------------------------------

LEARNING = "learning"

CANDIDATES = "candidates.jsonl"


def candidates_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / CANDIDATES


# Pass logs. Only `passes.jsonl` rows carry `session` and `end`, which `cursor` reads.
ADMISSIONS = "admissions.jsonl"


def admissions_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / ADMISSIONS


PASSES = "passes.jsonl"


def passes_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / PASSES


PLACEMENTS = "placements.jsonl"


def placements_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / PLACEMENTS


def _jsonl(path: Path) -> list[dict]:
    """Every JSON object row in a file, in order; [] when absent. Torn or non-object lines are skipped."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _rewrite(path: Path, rows: list[dict]) -> None:
    """Replace a JSONL file atomically, so a killed process leaves the original intact.

    rat-tail: lines `_jsonl` skipped do not survive the rewrite.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8")
    tmp.replace(path)


def cursor(session: Session, session_id: str) -> int:
    """How far into one record detection has read: the largest `end` in the pass log, or 0. Derived, so a failed pass advances nothing.

    `type(...) is int`, because bool is an int. rat-tail: reads the whole pass log per call.
    """
    ends = [row.get("end") for row in _jsonl(passes_path(session))
            if row.get("session") == session_id and type(row.get("end")) is int]
    return max(ends, default=0)


@tool(
    "CandidateAdd",
    "Note one spot in a session record that looks worth a closer read later. `topic` is "
    "what you think is there, in your own words; `session_id`, `start` and `end` say "
    "where, as a half-open row range. Writes nothing to memory or skills.",
    {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "session_id": {"type": "string"},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        },
        "required": ["topic", "session_id", "start", "end"],
    },
)
def candidate_add(*, session: Session, topic: str, session_id: str,
                  start: int, end: int) -> str:
    """Append one candidate after checking its range exists in the record, so a bad pointer is caught by the caller that wrote it. Failures return text."""
    if not topic.strip():
        return "a candidate needs a topic saying what is there"
    try:
        known = use("session", "records")(session.root)
    except LookupError:
        return ("the session_transcripts plugin is not loaded, so no record can be "
                "validated and no candidate can be written")
    # rat-tail: duplicates `transcript.session_read`'s refusal wording rather than coupling the plugins.
    if session_id not in known:
        return (f"no session record named {session_id!r}; readable: "
                f"{', '.join(known) or 'none'}")
    total = len(use("session", "rows")(session.root, session_id))
    if not 0 <= start < end <= total:
        return (f"rows {start}-{end} are outside {session_id}, which has {total}; "
                f"ask for a half-open range within 0-{total}")

    path = candidates_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Mark and placement slots are written as None, so `is None` means "not yet" for every reader.
    row = {"id": uuid.uuid4().hex,
           "at": datetime.now(timezone.utc).isoformat(), "topic": topic.strip(),
           "session": session_id, "start": start, "end": end,
           "disposition": None, "reason": None, "marked": None,
           "destination": None, "action": None, "target": None, "note": None,
           "placed": None}
    with locked(path), path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return f"noted: {session_id}#{start}-{end}"


# An enum, so the admission ratio is countable without a model (ADR-0022).
DISPOSITIONS = ("admitted", "rejected")


@tool(
    "CandidateMark",
    "Record what you decided about one candidate from the worklist. `id` is the "
    "candidate's id as you were given it; `disposition` is whether you kept it; `reason` "
    "is one or two sentences in your own words - name what you wrote it into, or say why "
    "it was not worth keeping. Mark every candidate you were handed, the ones you reject "
    "as well as the ones you keep.",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "disposition": {"type": "string", "enum": list(DISPOSITIONS)},
            "reason": {"type": "string"},
        },
        "required": ["id", "disposition", "reason"],
    },
)
def candidate_mark(*, session: Session, id: str, disposition: str, reason: str) -> str:
    """Fill the mark slots on one candidate. A second mark is refused, never overwritten. Failures return text and change nothing."""
    if disposition not in DISPOSITIONS:
        return (f"unknown disposition {disposition!r}; use one of: "
                f"{', '.join(DISPOSITIONS)}")
    if not reason.strip():
        return "a mark needs a reason saying what you decided and why"

    path = candidates_path(session)
    # Before the lock, because `locked` would create the file.
    if not path.is_file():
        return f"no candidate with id {id!r} in the worklist"
    # Held from read to rewrite, or concurrent read-modify-writes lose an edit.
    with locked(path):
        rows = _jsonl(path)
        for row in rows:
            if row.get("id") == id:
                break
        else:
            return f"no candidate with id {id!r} in the worklist"
        if row.get("disposition") is not None:
            return (f"candidate {id!r} is already marked {row['disposition']!r}; a mark is "
                    f"the record of what happened and is not rewritten")

        row["disposition"] = disposition
        row["reason"] = reason.strip()
        row["marked"] = datetime.now(timezone.utc).isoformat()
        _rewrite(path, rows)
    return f"marked {id} as {disposition}"


DESTINATIONS = ("memory", "skill", "none")
ACTIONS = ("created", "merged", "declined")


@tool(
    "CandidatePlace",
    "Record where one admitted candidate went. `id` is the candidate's id as you were "
    "given it; `destination` is the store that took it, or `none` when nothing was "
    "written; `action` is what you did there; `target` is the memory or skill name you "
    "wrote or amended, or the one that blocked you, and may be empty only on a decline; "
    "`reason` is one or two sentences in your own words - what it merged with, or what "
    "blocked it. Place every candidate you were handed, the ones you decline as well as "
    "the ones you write.",
    {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "destination": {"type": "string", "enum": list(DESTINATIONS)},
            "action": {"type": "string", "enum": list(ACTIONS)},
            "target": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["id", "destination", "action", "target", "reason"],
    },
)
def candidate_place(*, session: Session, id: str, destination: str, action: str,
                    target: str, reason: str) -> str:
    """Fill the placement slots on one admitted candidate, as `candidate_mark` does.

    Only admitted candidates can be placed, and `none` pairs only with `declined`. `target` is required except on a decline, but recorded when given.
    """
    if destination not in DESTINATIONS:
        return (f"unknown destination {destination!r}; use one of: "
                f"{', '.join(DESTINATIONS)}")
    if action not in ACTIONS:
        return f"unknown action {action!r}; use one of: {', '.join(ACTIONS)}"
    if (destination == "none") != (action == "declined"):
        return (f"destination {destination!r} does not go with action {action!r}; 'none' is "
                f"what a declined candidate carries, and nothing else carries it")
    if not reason.strip():
        return "a placement needs a reason saying where it went and why"
    if action != "declined" and not target.strip():
        return f"a {action} placement needs the name of the memory or skill it wrote"

    path = candidates_path(session)
    if not path.is_file():
        return f"no candidate with id {id!r} in the worklist"
    with locked(path):
        rows = _jsonl(path)
        for row in rows:
            if row.get("id") == id:
                break
        else:
            return f"no candidate with id {id!r} in the worklist"
        if row.get("disposition") != "admitted":
            return (f"candidate {id!r} is marked {row.get('disposition')!r}, not 'admitted'; "
                    f"only what admission kept is placed")
        if row.get("placed") is not None:
            return (f"candidate {id!r} is already placed in {row.get('destination')!r}; a "
                    f"placement is the record of what happened and is not rewritten")

        row["destination"] = destination
        row["action"] = action
        row["target"] = target.strip()
        row["note"] = reason.strip()
        row["placed"] = datetime.now(timezone.utc).isoformat()
        _rewrite(path, rows)
    return f"placed {id} in {destination} ({action})"


# ---------------------------------------------------------------------------
# Retire: taking an artefact out of its collection, one way
# ---------------------------------------------------------------------------

# Collection directory names.
KINDS = ("skills", "memory")

# Both mean the content moved elsewhere; retiring for disuse is the curation pass's job.
RETIRE_ACTIONS = ("promoted", "merged")


def _present(session: Session, kind: str, name: str) -> bool:
    """Whether this collection holds that name; a skill needs its `SKILL.md`."""
    return ((un_dir(session.root, "skills") / name / "SKILL.md").is_file() if kind == "skills"
            else (un_dir(session.root, "memory") / f"{name}.md").is_file())


def _forget(session: Session, kind: str, name: str) -> None:
    """Drop this artefact's curator record."""
    state_name = curation.SKILLS_STATE if kind == "skills" else curation.MEMORY_STATE
    key = "skills" if kind == "skills" else "memories"
    state = curation.load(session, state_name)
    records = state.get(key)
    if isinstance(records, dict) and records.pop(name, None) is not None:
        curation.save(session, state_name, state)


@tool(
    "Retire",
    "Record that one memory or agent-written skill has been folded into something else, moving it "
    "out of its collection and into `.un/learning/archive/`. `kind` is which collection; `name` is "
    "the memory, or the skill's directory; `action` is `promoted` when the content now lives in a "
    "skill and `merged` when it now lives in another artefact of the same collection; `into` names "
    "that destination and is required; `reason` is one or two sentences saying why. A moved memory "
    "also loses its MEMORY.md line, and a moved skill can no longer be read back. Retiring "
    "something merely because nobody reads it is the timed curation pass's job, not this tool's. A "
    "skill an operator wrote is refused. Ask the operator before calling this - nothing here is "
    "undone automatically.",
    {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "name": {"type": "string"},
            "action": {"type": "string", "enum": list(RETIRE_ACTIONS)},
            "reason": {"type": "string"},
            "into": {"type": "string"},
        },
        "required": ["kind", "name", "action", "reason", "into"],
    },
)
def retire(*, session: Session, kind: str, name: str, action: str, reason: str,
           into: str = "") -> str:
    """Archive one artefact whose content now lives elsewhere, via `curation.retire`. Everything is validated before anything moves; failures return text."""
    if kind not in KINDS:
        return f"unknown kind {kind!r}; use one of: {', '.join(KINDS)}"
    if action not in RETIRE_ACTIONS:
        return f"unknown action {action!r}; use one of: {', '.join(RETIRE_ACTIONS)}"
    if not reason.strip():
        return "a retire needs a reason saying why this is going"
    if refusal := refused("skill" if kind == "skills" else kind, name):
        return refusal

    if kind == "skills":
        source = un_dir(session.root, kind) / name
        if not (source / "SKILL.md").is_file():
            return f"no skill named {name!r} to retire"
        data, _, _ = frontmatter.parse((source / "SKILL.md").read_text(encoding="utf-8"))
        # Operator-written skills are refused; an unreadable header counts as operator-written.
        if not curation.by_agent(data):
            return (f"skill {name!r} was authored by an operator; Retire only archives what the "
                    f"agent wrote")
    else:
        source = un_dir(session.root, kind) / f"{name}.md"
        if not source.is_file():
            return f"no {kind} named {name!r} to retire"

    # `promoted` names a skill, `merged` an artefact of the same collection; it must exist.
    destination = "skills" if action == "promoted" else kind
    noun = "skill" if destination == "skills" else destination
    if refusal := refused(noun, into):
        return f"a {action} names the {noun} that now carries this content: {refusal}"
    if destination == kind and into == name:
        return f"{name!r} cannot be {action} into itself; name the {noun} that now carries it"
    if not _present(session, destination, into):
        return f"no {noun} named {into!r}; a {action} names the {noun} that now carries this"

    landed = curation.retire(session, kind, name, source, action, reason.strip(), into)
    if isinstance(landed, str):
        return landed
    _forget(session, kind, name)
    return f"{action} {name} into {into}; archived at {landed}"


# ---------------------------------------------------------------------------
# Amend: proposing a change to a file, and changing nothing
# ---------------------------------------------------------------------------

AMEND_FIELDS = ("section", "clause", "because")

AMENDMENT_PLAN = """# Amendment to {target}

Raised from the memory `{from_memory}` on {at}. **Nothing has been changed.** Apply this by hand,
or delete this file to decline it.

## Target

`{target}`, under **{section}**

## Clause to add

{clause}

## Why

{because}

## On applying this

Applying the plan is two actions, not one. Paste the clause into the target, then retire
`{from_memory}`:

```
Retire(kind="memory", name="{from_memory}", action="promoted", into="{target}",
       reason="<what it became in the target>")
```

An approved amendment ALWAYS retires the memory it came from. The clause now lives in a file the
project already follows, so a memory saying the same thing is a second copy to keep in step.

Declining is one action: drop this file and leave the memory alone. The row in
`.un/learning/{log}` stays either way, and is what stops a later pass raising this again.
"""


def _target(root: Path, given: str) -> Path | str:
    """The named file as an absolute path confined to the project, or the refusal. Both sides are resolved so `..` and absolute paths cannot escape."""
    root = Path(root).resolve()
    resolved = (root / given).resolve()
    if not resolved.is_relative_to(root):
        return f"target {given!r} is outside the project"
    if not resolved.is_file():
        return f"no file at {given!r} to amend; a target is one file, not a directory"
    return resolved


@tool(
    "Amend",
    "Raise a plan to add one clause to a rule file that a memory shows to be wrong or "
    "incomplete. `target` is the file carrying that rule, relative to the project root - a "
    "skill, a rules file, a discipline, CONTEXT.md, a command. A file an OPERATOR wrote is as "
    "valid a target as one the agent wrote. `section` is the heading the clause belongs under, "
    "`from_memory` the memory it came from, `clause` the sentence to add written as it would "
    "appear in the target, and `because` what a session following the target as written does "
    "wrong today. **Nothing is edited and nothing moves.** This writes a plan under "
    "`.un/learning/amendments/` and a row recording it, and returns the plan's path; the memory "
    "stays where it is until an operator applies the plan, and applying it always retires that "
    "memory, because the clause then lives in the target. Write `clause` and `section` as the "
    "literal text the target carries, never HTML-escaped: `<tag>`, not `&lt;tag&gt;`. A source "
    "and target already raised is refused, because an operator already has that plan.",
    {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "section": {"type": "string"},
            "from_memory": {"type": "string"},
            "clause": {"type": "string"},
            "because": {"type": "string"},
        },
        "required": ["target", "section", "from_memory", "clause", "because"],
    },
)
def amend(*, session: Session, target: str, section: str, from_memory: str, clause: str,
          because: str) -> str:
    """Write one amendment plan, then its log row. Validated first; failures return text.

    Plan before row: an interruption leaves a re-raisable duplicate rather than a row that blocks the re-raise forever.
    """
    for field, value in zip(AMEND_FIELDS, (section, clause, because)):
        if not value.strip():
            return f"an amendment needs a {field}"
    if refusal := refused("memory", from_memory):
        return refusal
    if not (un_dir(session.root, "memory") / f"{from_memory}.md").is_file():
        return f"no memory named {from_memory!r} to raise an amendment from"
    resolved = _target(session.root, target)
    if isinstance(resolved, str):
        return resolved

    rel = resolved.relative_to(Path(session.root).resolve()).as_posix()
    if any(row.get("from_memory") == from_memory and row.get("target") == rel
           for row in curation.amendments(session)):
        return (f"{from_memory!r} was already raised against {rel!r}; an operator declined that "
                f"plan or has not answered yet, and an approved one would have retired "
                f"{from_memory!r}. Look in .un/{curation.DIR}/{curation.AMENDMENT_DIR}/")

    folder = curation.path(session, curation.AMENDMENT_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).isoformat()
    plan = curation.free(folder, f"{from_memory}--{resolved.stem}", ".md")
    plan.write_text(AMENDMENT_PLAN.format(target=rel, from_memory=from_memory, at=at,
                                          section=section.strip(), clause=clause.strip(),
                                          because=because.strip(), log=curation.AMENDMENTS),
                    encoding="utf-8")
    curation.log(session, {
        "at": at, "from_memory": from_memory, "target": rel, "section": section.strip(),
        "plan": f"{curation.AMENDMENT_DIR}/{plan.name}"}, curation.AMENDMENTS)
    return f"raised an amendment to {rel} from {from_memory}; nothing changed, plan at {plan}"


# ---------------------------------------------------------------------------
# The detection pass
# ---------------------------------------------------------------------------

# Detection fires every this many finished turns. rat-tail: a constant, not a config key (ADR-0022).
DETECT_EVERY = 10

# Rows handed to one pass.
DETECT_ROWS = 200

DETECTOR = "detector"

# Only the range; the criteria live in the seeded `detector.md`.
DETECT_PROMPT = ("Read rows {start} to {end} of session record {session_id} with "
                 "SessionRead, and note with CandidateAdd every span that looks worth a "
                 "closer read later. Note nothing outside that range.")


def _unread(session: Session) -> tuple[str, int, int] | None:
    """The oldest record with unread rows, as (session_id, start, end), or None. A record shorter than its cursor was truncated; it is reported and skipped."""
    for session_id in use("session", "records")(session.root):
        total = len(use("session", "rows")(session.root, session_id))
        seen = cursor(session, session_id)
        if seen > total:
            session.report(DETECTOR, f"{session_id} was read to row {seen} but the record "
                                     f"now has {total}; skipping a truncated record")
            continue
        if seen < total:
            return session_id, seen, min(seen + DETECT_ROWS, total)
    return None


def _detected(session: Session, session_id: str, start: int, end: int) -> None:
    """One detection pass, on its own thread. A failure is reported (ADR-0023) and commits no pass row, so the range is retried.

    Candidates are counted by the worklist's growth, not read from the reply.
    """
    before = len(_jsonl(candidates_path(session)))
    try:
        use("agents", "run")(session, DETECTOR, DETECT_PROMPT.format(
            session_id=session_id, start=start, end=end))
    except Exception as exc:  # noqa: BLE001
        session.report(DETECTOR, f"{type(exc).__name__}: {exc}")
        return
    path = passes_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "session": session_id,
           "start": start, "end": end,
           "candidates": len(_jsonl(candidates_path(session))) - before}
    with locked(path), path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@hook("TurnStart")
def detect(*, session: Session) -> None:
    """Every `DETECT_EVERY` turns, run the detector over one unread span on a non-daemon thread.

    Skipped in forks (`session.agent`) so a detector cannot fork a detector, and at turn 0. A missing `detector.md` is reported before forking, or the pass would advance the cursor finding nothing; a disabled subagents plugin is silent.
    """
    if not session.self_learning or session.agent or not session.turn_index:
        return None
    if session.turn_index % DETECT_EVERY:
        return None
    try:
        available = use("agents", "names")()
    except LookupError:
        return None
    if DETECTOR not in available:
        session.report(DETECTOR, f"no {DETECTOR}.md in .un/agents/, so nothing was indexed; "
                                 f"`un install` seeds it")
        return None
    if (span := _unread(session)) is None:
        return None
    threading.Thread(target=_detected, args=(session, *span), daemon=False).start()
    return None


# ---------------------------------------------------------------------------
# The admission pass
# ---------------------------------------------------------------------------

# A pass is due at this many unmarked candidates, or when one is older than ADMIT_AFTER. rat-tail: constants.
ADMIT_AT = 20
ADMIT_AFTER = 24      # hours
ADMIT_BATCH = 30      # candidates one pass carries

ADMITTER = "admitter"

# Carries the batch; the admitter cannot read the worklist itself.
ADMIT_PROMPT = (
    "Here are {count} candidates from the learning worklist. Read what each one points at "
    "with SessionRead, decide which are worth keeping, and mark EVERY candidate below with "
    "CandidateMark - the ones you reject as well as the ones you keep. A later pass decides "
    "where what you keep goes, so your reason is what it reads first: say what is in the "
    "span and why it is worth keeping.\n\n{batch}")

# One pass at a time: the backlog stays due while the admitter runs. A thread, not a lock, so a raising pass cannot wedge it.
# rat-tail: per process; a second process wastes a fork but `CandidateMark` refuses double marks.
_ADMITTING: threading.Thread | None = None

# Sessions already told there is no admitter; reported once each (ADR-0023).
_ADMITTER_REPORTED: set[str] = set()


def _unmarked(session: Session) -> list[dict]:
    """Every unmarked candidate with an id, oldest first."""
    return [row for row in _jsonl(candidates_path(session))
            if row.get("id") and row.get("disposition") is None]


def _due(rows: list[dict], stamp: str, count: int, hours: int) -> bool:
    """Whether a backlog is due: at least `count` rows, or one whose `stamp` is `hours` old. Missing, unparseable or naive stamps are skipped, not treated as old."""
    if len(rows) >= count:
        return True
    oldest = None
    for row in rows:
        value = row.get(stamp)
        if not isinstance(value, str):
            continue
        try:
            at = datetime.fromisoformat(value)
        except ValueError:
            continue
        if at.tzinfo is None:
            continue
        oldest = at if oldest is None else min(oldest, at)
    return oldest is not None and (
        datetime.now(timezone.utc) - oldest >= timedelta(hours=hours))


def _marks(session: Session) -> tuple[int, int]:
    """(how many candidates carry a disposition, how many of those say "admitted")."""
    decided = [row.get("disposition") for row in _jsonl(candidates_path(session))
               if row.get("disposition") is not None]
    return len(decided), decided.count("admitted")


def _admitted(session: Session, batch: list[dict]) -> None:
    """One admission pass, on its own thread, shaped like `_detected`. The log row counts this pass's marks by difference."""
    before_marked, before_admitted = _marks(session)
    listing = "\n".join(
        f"- {row['id']} - {row.get('topic', '')} "
        f"(session:{row.get('session')}#{row.get('start')}-{row.get('end')})"
        for row in batch)
    try:
        use("agents", "run")(session, ADMITTER,
                             ADMIT_PROMPT.format(count=len(batch), batch=listing))
    except Exception as exc:  # noqa: BLE001
        session.report(ADMITTER, f"{type(exc).__name__}: {exc}")
        return
    after_marked, after_admitted = _marks(session)
    path = admissions_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "read": len(batch),
           "marked": after_marked - before_marked,
           "admitted": after_admitted - before_admitted}
    with locked(path), path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@hook("TurnStart")
def admit(*, session: Session) -> None:
    """When the backlog is due, run the admitter over the oldest unmarked batch. `detect`'s guards, no stride.

    rat-tail: parses `candidates.jsonl` every turn.
    """
    global _ADMITTING
    if not session.self_learning or session.agent or not session.turn_index:
        return None
    rows = _unmarked(session)
    if not _due(rows, "at", ADMIT_AT, ADMIT_AFTER):
        return None
    try:
        available = use("agents", "names")()
    except LookupError:
        return None
    if ADMITTER not in available:
        if session.id not in _ADMITTER_REPORTED:
            _ADMITTER_REPORTED.add(session.id)
            session.report(ADMITTER, f"no {ADMITTER}.md in .un/agents/, so {len(rows)} "
                                     f"candidates are waiting; `un install` seeds it")
        return None
    if _ADMITTING is not None and _ADMITTING.is_alive():
        return None
    _ADMITTING = threading.Thread(target=_admitted, args=(session, rows[:ADMIT_BATCH]),
                                  daemon=False)
    _ADMITTING.start()
    return None


# ---------------------------------------------------------------------------
# The placement pass
# ---------------------------------------------------------------------------

# Lower than ADMIT_AT, because this pass's input is a subset of admission's output. rat-tail: constants.
PLACE_AT = 10
PLACE_AFTER = 24      # hours
PLACE_BATCH = 20      # candidates one pass carries

IMPLEMENTOR = "implementor"

# The re-check sentence matters: the fork's store index is a snapshot taken before its first write.
PLACE_PROMPT = (
    "Here are {count} candidates the admitter kept. For each one, decide which store it "
    "belongs in, whether it merges with something already there, and whether writing it "
    "would contradict what is written. Check the store again immediately before every "
    "write - an earlier candidate in this same batch may have just changed it. Write what "
    "survives with Remember or SkillManage, and record EVERY candidate below with "
    "CandidatePlace, the ones you decline as well as the ones you write.\n\n{batch}")

# As `_ADMITTING` and `_ADMITTER_REPORTED`, for the placement pass.
_PLACING: threading.Thread | None = None
_IMPLEMENTOR_REPORTED: set[str] = set()


def _unplaced(session: Session) -> list[dict]:
    """Every admitted, unplaced candidate with an id, oldest first."""
    return [row for row in _jsonl(candidates_path(session))
            if row.get("id") and row.get("disposition") == "admitted"
            and row.get("placed") is None]


def _placements(session: Session) -> tuple[int, int, int]:
    """(created, merged, declined) across the whole worklist."""
    actions = [row.get("action") for row in _jsonl(candidates_path(session))
               if row.get("placed") is not None]
    return (actions.count("created"), actions.count("merged"), actions.count("declined"))


VISIBILITY = curation.VISIBILITY


def _visible(session: Session) -> bool:
    return curation.visible(session.root)


def _placed_pass(session: Session, batch: list[dict]) -> None:
    """One placement pass, on its own thread, shaped like `_admitted`. Also notes the operator of declines, unless visibility is off."""
    before = _placements(session)
    listing = "\n".join(
        f"- {row['id']} - {row.get('topic', '')} "
        f"(session:{row.get('session')}#{row.get('start')}-{row.get('end')})\n"
        f"  the admitter kept it because: {row.get('reason', '')}"
        for row in batch)
    try:
        use("agents", "run")(session, IMPLEMENTOR,
                             PLACE_PROMPT.format(count=len(batch), batch=listing))
    except Exception as exc:  # noqa: BLE001
        session.report(IMPLEMENTOR, f"{type(exc).__name__}: {exc}")
        return
    created, merged, declined = (now - was
                                 for now, was in zip(_placements(session), before))
    if declined and _visible(session):
        # `note`, not `report`: a decline is the pass working, not a fault.
        session.note(IMPLEMENTOR, f"{declined} of {len(batch)} admitted candidates were "
                                  f"declined rather than written; each one says why in "
                                  f"its note in {CANDIDATES}")
    path = placements_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "read": len(batch),
           "created": created, "merged": merged, "declined": declined}
    with locked(path), path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


@hook("TurnStart")
def place(*, session: Session) -> None:
    """When admitted candidates are due, run the implementor over the oldest unplaced batch. `admit`'s guards, aged on `marked`.

    rat-tail: parses `candidates.jsonl` every turn, again after `admit`.
    """
    global _PLACING
    if not session.self_learning or session.agent or not session.turn_index:
        return None
    rows = _unplaced(session)
    if not _due(rows, "marked", PLACE_AT, PLACE_AFTER):
        return None
    try:
        available = use("agents", "names")()
    except LookupError:
        return None
    if IMPLEMENTOR not in available:
        if session.id not in _IMPLEMENTOR_REPORTED:
            _IMPLEMENTOR_REPORTED.add(session.id)
            session.report(IMPLEMENTOR, f"no {IMPLEMENTOR}.md in .un/agents/, so {len(rows)} "
                                        f"admitted candidates are waiting; `un install` "
                                        f"seeds it")
        return None
    if _PLACING is not None and _PLACING.is_alive():
        return None
    _PLACING = threading.Thread(target=_placed_pass, args=(session, rows[:PLACE_BATCH]),
                                daemon=False)
    _PLACING.start()
    return None
