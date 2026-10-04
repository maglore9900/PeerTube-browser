"""Durable agent memory and the learning loop that feeds it.

`Remember` and `Recall` keep one fact per markdown file under `.un/memory/`, indexed by `MEMORY.md`; a SessionStart hook injects the index, capped at `LIMIT` lines, and runs the memory curation pass. The index is never rebuilt from disk, because deleting a line is how a memory is pruned. The learning loop (ADR-0022) keeps the candidate worklist under `.un/learning/`: `CandidateAdd`, `CandidateMark` and `CandidatePlace` record what the `detect`, `admit` and `place` TurnStart passes found and decided, and `Retire` and `Amend` archive a folded-in artefact or propose a rule change. Every pass runs in the background through `curation.launch`.
"""

from __future__ import annotations

import bisect
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from un.core import locked
from un import Session, frontmatter, hook, service, tool, use
# `refused` is the only thing confining names to their collection directory.
from un.core import refused, un_dir
from un.plugins.stock import curation

TYPES = ("user", "feedback", "project", "reference")

STATE = curation.MEMORY_STATE

INDEX = curation.INDEX
HEADER = "# Memory\n\nDurable notes carried into every session. Read one with `Recall`.\n\n"

# Index lines allowed into the prompt; lines, so one long description cannot crowd out others.
# rat-tail: the omission notice adds two lines beyond this.
LIMIT = 200


def root(session: Session) -> Path:
    return un_dir(session.root, "memory")


def index_path(session: Session) -> Path:
    return root(session) / INDEX


def memory_path(session: Session, name: str) -> Path:
    return root(session) / f"{name}.md"


def _snapshot(text: str) -> str:
    """The index as the prompt gets it: whole, or its last `LIMIT` lines (the newest) under a notice counting dropped pointers. The file itself is never trimmed."""
    lines = text.splitlines()
    if len(lines) <= LIMIT:
        return text
    kept = lines[-LIMIT:]
    dropped = sum(1 for line in lines[:-LIMIT] if line.startswith("- ["))
    return "\n".join(
        [f"({dropped} older memories omitted - full index at .un/memory/{INDEX})", "", *kept]
    )


def _names(session: Session) -> str:
    """Every memory on disk, whether or not the index still lists it."""
    folder = root(session)
    if not folder.is_dir():
        return "none"
    return ", ".join(sorted(p.stem for p in folder.glob("*.md") if p.name != INDEX)) or "none"


def _write_index(session: Session, name: str, description: str) -> None:
    """Add this memory's index line, replacing any line linking to the same file. Other lines are kept as they are."""
    path = index_path(session)
    # Read inside the lock, or concurrent Remembers drop each other's lines.
    with locked(path):
        text = path.read_text(encoding="utf-8") if path.exists() else HEADER
        kept = [line for line in text.splitlines() if not curation.indexes(line, name)]
        line = f"{curation.pointer(name)}{name}.md) - {description.strip()}"
        path.write_text("\n".join([*kept, line]) + "\n", encoding="utf-8")


@tool(
    "Remember",
    "Record one durable fact as its own memory file and index it in MEMORY.md. Use for "
    "preferences, project constraints, and decisions - not for things already in the "
    "code or this conversation.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "type": {"type": "string", "enum": list(TYPES)},
            "fact": {"type": "string"},
        },
        "required": ["name", "description", "type", "fact"],
    },
)
def remember(*, session: Session, name: str, description: str, type: str, fact: str) -> str:
    if refusal := refused("memory", name):
        return refusal
    if type not in TYPES:
        return f"unknown memory type {type!r}; use one of: {', '.join(TYPES)}"

    path = memory_path(session, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path):
        path.write_text(
            frontmatter.render(
                {"name": name, "description": description, "metadata": {"type": type}}, fact),
            encoding="utf-8")
    _write_index(session, name, description)
    return f"remembered: {name}"


@tool(
    "Recall",
    "Read one memory in full, by the name MEMORY.md lists it under.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
def recall(*, session: Session, name: str) -> str:
    if refusal := refused("memory", name):
        return refusal
    path = memory_path(session, name)
    if not path.is_file():
        return f"no memory named {name!r}; remembered: {_names(session)}"
    _, body, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
    return body


# ---------------------------------------------------------------------------
# Curation: the report, the accuracy check and the memory editor
# ---------------------------------------------------------------------------

TARGET = "memory"
REPORT = "memory-curation-report.md"
FINDINGS = "accuracy-findings.md"

# The agent `revise` arms, after the accuracy auditor.
EDITOR = "memory-editor"

# Carries the whole index, not `_snapshot`: the editor judges the full collection.
REVISE_PROMPT = (
    "Here is the whole memory index, every memory in the collection. Only the newest {limit} "
    "lines of it reach a session's system prompt and it is {size} lines long, so "
    "{dropped} of these reach no prompt at all. Act on the accuracy findings at the end first, "
    "then decide leave, update, merge or promote for each memory and carry out what you decide, "
    "opening a memory's file when you need what is in it."
    "\n\n{index}\n\n{skills}\n\n## Accuracy findings\n\n{findings}")

# Stated explicitly: an empty skills section would read as "no skills" and invite duplicate promotions.
NO_SKILLS = ("No skill collection was available on this pass, so nothing is known about what "
             "the skills already cover. Do not promote anything.")

AUDITOR = "accuracy-auditor"

# The last rotation key the auditor was handed, in the curator state (ADR-0027: never in the artefact).
CURSOR = "check_cursor"

AUDIT_PROMPT = (
    "Check each of these {count} items claim by claim against the tree, and return one verdict "
    "per item as your brief describes.\n\n{items}")

# rat-tail: counted from the auditor's `Verdict:` lines, so a reply that drifts from its output format reads as 0 findings.
WRONG = re.compile(r"^Verdict:\s*(?:partly|wholly) wrong", re.MULTILINE | re.IGNORECASE)

# Said explicitly, so the editor does not read a missing section as "everything is accurate".
NO_CHECK = "No accuracy check ran on this pass, so there are no accuracy findings to act on."

# Shared consecutive name tokens that flag two memories as possibly the same fact.
SHARED_TOKENS = 3


def _run(left: str, right: str) -> list[str]:
    """The longest run of consecutive hyphen tokens these two names share."""
    a, b = left.split("-"), right.split("-")
    best: list[str] = []
    for i in range(len(a)):
        for j in range(len(b)):
            length = 0
            while i + length < len(a) and j + length < len(b) and a[i + length] == b[j + length]:
                length += 1
            if length > len(best):
                best = a[i:i + length]
    return best


def _superseded(names: list[str]) -> list[str]:
    """Name pairs sharing a run of at least `SHARED_TOKENS` tokens, longest first. Reported only, never acted on."""
    found = []
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            run = _run(left, right)
            if len(run) >= SHARED_TOKENS:
                found.append((len(run), "-".join(run), left, right))
    found.sort(key=lambda row: (-row[0], row[1]))
    return [f'- "{run}" ({length} tokens) - {left}, {right}' for length, run, left, right in found]


def _pointers(text: str) -> list[str]:
    """The names the index lists, in the order it lists them. A name is the link target, since hand-written lines may carry a title as link text."""
    out = []
    for line in text.splitlines():
        if line.startswith("- ["):
            match = re.search(r"\]\(([^)]+)\.md\)", line)
            out.append(match.group(1) if match else line[3:].split("]", 1)[0])
    return out


def _retired(rows: list[dict], since: datetime) -> list[str]:
    """Retirements at or after `since`, one line each. Rows with unreadable stamps are skipped."""
    out = []
    for row in rows:
        stamp = curation.parse(row.get("at"))
        if stamp is None or stamp < since:
            continue
        into = row.get("into")
        out.append(f"- {row.get('name')} - {row.get('action')}"
                   + (f" into {into}" if into else "")
                   + f"; {row.get('reason')}")
    return out


def _on_disk(folder: Path) -> list[str]:
    """Every memory name on disk, sorted."""
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.md") if p.name != INDEX)


@service("memory:names")
def names(root: Path) -> list[str]:
    """Every memory name on disk under `root`, for a `Recall(...)` scope to be checked against."""
    return _on_disk(un_dir(root, "memory"))


def _findings(text: str, on_disk: list[str], retired: list[dict],
              since: datetime) -> list[tuple[str, list[str]]]:
    """The whole report, as (heading, lines). Pure: no disk, no clock."""
    listed = _pointers(text)
    reaching = _snapshot(text)
    return [
        ("Pointers with no file", [f"- {name}" for name in listed if name not in on_disk]),
        ("Files with no pointer", [f"- {name}" for name in on_disk if name not in listed]),
        ("Possibly superseded", _superseded(sorted(set(listed) | set(on_disk)))),
        ("Dropped from the prompt",
         [f"- {line[3:].split(']', 1)[0]}" for line in text.splitlines()
          if line.startswith("- [") and line not in reaching]),
        (f"Retired since {since.date().isoformat()}", _retired(retired, since)),
    ]


def _batch(rotation: list[str], cursor: str | None, size: int) -> list[str]:
    """The next `size` keys strictly after `cursor` in sorted order, wrapping, each at most once. A cursor that has left the rotation still sorts into place."""
    ordered = sorted(set(rotation))
    start = bisect.bisect_right(ordered, cursor) if cursor else 0
    return (ordered[start:] + ordered[:start])[:size]


def _rotation(session: Session) -> list[str]:
    """`memory:<name>` for every memory on disk. The `memory:` kind prefix leaves room for skills to join later."""
    return [f"memory:{name}" for name in _on_disk(root(session))]


def _item(key: str) -> str:
    """One batch line for the auditor: the key and the file it names."""
    return f"- {key}: .un/memory/{key.split(':', 1)[1]}.md"


def _check(session: Session, batch: list[str]) -> str:
    """Run the auditor over `batch`. On a reply, write it to `FINDINGS`, then advance the cursor, and return it; on a refusal or a raise, report, leave the cursor, and return `NO_CHECK`."""
    if not batch or curation.absent(
            session, AUDITOR, f"no {AUDITOR}.md in .un/agents/, so no accuracy check ran; "
                              f"`un install` seeds it"):
        return NO_CHECK
    prompt = AUDIT_PROMPT.format(count=len(batch), items="\n".join(map(_item, batch)))
    shown = curation.visible(session.root)
    if shown:
        session.note(AUDITOR, f"started: {len(batch)} memories")
    try:
        reply = use("agents", "run")(session, AUDITOR, prompt)
    except Exception as exc:  # noqa: BLE001
        session.report(AUDITOR, f"{type(exc).__name__}: {exc}")
        return NO_CHECK
    if reply.startswith(curation.REFUSALS):
        session.report(AUDITOR, reply)
        return NO_CHECK
    if shown:
        session.note(AUDITOR, f"done: {len(WRONG.findall(reply))} findings")
    findings = f"Checked {datetime.now(timezone.utc).isoformat()}: {', '.join(batch)}\n\n{reply}"
    # Written before the editor runs, so a failed editor run loses nothing.
    target = curation.path(session, FINDINGS)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# Accuracy findings\n\n{findings}\n", encoding="utf-8")
    # Reloaded rather than taken from `curate`, so the save keeps whatever is on disk now.
    state = curation.load(session, STATE)
    state[CURSOR] = batch[-1]
    curation.save(session, STATE, state)
    return findings


def _render(findings: list[tuple[str, list[str]]], now: datetime) -> str:
    """The report as markdown. Empty findings keep their heading, so a quiet pass is distinguishable from one that did not look."""
    parts = [f"# Memory curation report\n\nGenerated {now.isoformat()}. Read-only: this pass proposes, "
             f"and the operator decides.\n"]
    for heading, lines in findings:
        parts.append(f"## {heading} ({len(lines)})\n\n" + "\n".join(lines or ["- none"]) + "\n")
    return "\n".join(parts)


def _revise_pass(session: Session, text: str, batch: tuple[str, ...] | list[str],
                 now: datetime) -> None:
    """The accuracy check over `batch`, then one memory editor pass, shaped like `_placed_pass`.

    Counts this pass's merges, promotions and amendments by difference in the logs, for the editor's done line. Under `visibility` a promotion and an amendment also get a note of their own, because each asks the operator to act. The commit stamps `last_run_at` with `now`.
    """
    def measure() -> tuple[int, int]:
        return len(curation.retirements(session)), len(curation.amendments(session))

    def commit(before: tuple[int, int]) -> str:
        state = curation.load(session, STATE)
        state["last_run_at"] = now.isoformat()
        curation.save(session, STATE, state)
        rows = curation.retirements(session)[before[0]:]
        raised = curation.amendments(session)[before[1]:]
        merged = sum(1 for row in rows if row.get("action") == "merged")
        promoted = [row.get("into") for row in rows if row.get("action") == "promoted"]
        done = f"{merged} merged, {len(promoted)} promoted, {len(raised)} amendments"
        if not curation.visible(session.root):
            return done
        if promoted:
            session.note(EDITOR, f"promoted into {', '.join(promoted)} - present but NOT enabled "
                                  f"and NOT audited; run skill-auditor over it, then add "
                                  f"[skills.<name>] enable = true")
        if raised:
            session.note(EDITOR, f"{len(raised)} amendment plan(s) raised under "
                                  f".un/{curation.DIR}/{curation.AMENDMENT_DIR}/ - NOTHING was "
                                  f"changed; apply one with /apply-amendment <plan>, or delete it "
                                  f"to decline")
        return done

    findings = _check(session, list(batch))
    curation.run(session, EDITOR, _revise_prompt(session, text, findings), measure, commit)


def _revise(session: Session, text: str, batch: list[str], now: datetime) -> None:
    """Start the accuracy check and the memory editor in the background through `curation.launch`, one pass at a time. `now` is the run time the editor's commit stamps."""
    curation.launch(session, EDITOR,
                    f"no {EDITOR}.md in .un/agents/, so the collection was reported on but not "
                    f"checked or revised; `un install` seeds it",
                    _revise_pass, lambda: (text, batch, now))


def _revise_prompt(session: Session, text: str, findings: str = NO_CHECK) -> str:
    """The editor's prompt: the whole index, the skills list (or `NO_SKILLS`), how many lines miss the prompt, and the accuracy findings (or `NO_CHECK`)."""
    reaching = _snapshot(text)
    dropped = sum(1 for line in text.splitlines()
                  if line.startswith("- [") and line not in reaching)
    try:
        skills = use("skills", "list")(session) or NO_SKILLS
    except LookupError:
        skills = NO_SKILLS
    return REVISE_PROMPT.format(limit=LIMIT, size=len(text.splitlines()), dropped=dropped,
                                index=text, skills=skills, findings=findings)


def curate(session: Session) -> None:
    """The memory curation pass: write the report, and optionally start the accuracy check and the memory editor. It retires nothing itself.

    Called from `inject` so it finishes before the index is read. Off in forks (`session.inherited`, `session.agent`), and the first run only stamps `last_run_at`. With `revise` on, the editor's commit stamps it instead.
    """
    if not session.self_learning or session.inherited or session.agent:
        return None
    every_days, revise, check_batch = curation.settings(session.root, TARGET)
    if not every_days:
        return None

    state = curation.load(session, STATE)
    now = datetime.now(timezone.utc)
    last = curation.parse(state.get("last_run_at"))
    if last is not None and now - last < timedelta(days=every_days):
        return None
    if last is None:
        state["last_run_at"] = now.isoformat()
        curation.save(session, STATE, state)
        return None

    path = index_path(session)
    text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    report = curation.path(session, REPORT)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        _render(_findings(text, _on_disk(root(session)), curation.retirements(session), last), now),
        encoding="utf-8")

    if not revise:
        state["last_run_at"] = now.isoformat()
        curation.save(session, STATE, state)
        return None
    # Last, after the report is written, so the report describes what the editor was given. The editor's commit stamps `last_run_at`, so only a completed pass counts as run.
    _revise(session, text, _batch(_rotation(session), state.get(CURSOR), check_batch), now)
    return None


# ---------------------------------------------------------------------------
# The candidate worklist
# ---------------------------------------------------------------------------

LEARNING = "learning"

CANDIDATES = "candidates.jsonl"


def candidates_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / CANDIDATES


# Pass logs. Only `passes.jsonl` rows carry `session` and `end`, which `cursor` reads.
ADMISSIONS = "admissions.jsonl"

PASSES = "passes.jsonl"


def passes_path(session: Session) -> Path:
    return un_dir(session.root, LEARNING) / PASSES


PLACEMENTS = "placements.jsonl"


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

# `promoted` and `merged` name where the content went; `amended` names a file the content was written into by applying an amendment plan; `stale` means a check against the tree found it wrong, so it goes nowhere.
RETIRE_ACTIONS = ("promoted", "merged", "amended", "stale")

# The one subagent that may retire a memory as `amended`; the main session may too.
APPLIER = "amendment-applier"


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
    "Take one memory or agent-written skill out of its collection, moving it into "
    "`.un/learning/archive/`. `kind` is which collection; `name` is the memory, or the skill's "
    "directory; `action` is `promoted` when the content now lives in a skill, `merged` when it now "
    "lives in another artefact of the same collection, `amended` when an amendment plan's clause "
    "has been written into a file, and `stale` when a check against the tree showed the content is "
    "wrong; `into` names the destination of a promote, merge or amend, is required for those, and "
    "is refused for `stale`. For `amended`, `kind` is `memory`, `into` is the edited file relative "
    "to the project root, and it must match a recorded amendment from this memory whose plan is "
    "still pending under `.un/learning/amendments/`; that plan is archived with the memory. Only "
    "the amendment-applier or the main session may record `amended`, and only once the clause is "
    "in the file. `reason` is one or two sentences saying why, and for `stale` names the file that "
    "shows it is wrong. A moved memory also loses its MEMORY.md line, and a moved skill can no "
    "longer be read back. A skill an operator wrote is refused. Ask the operator before calling "
    "this, unless the operator already chose the amendment plan you are applying - nothing here is "
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
        "required": ["kind", "name", "action", "reason"],
    },
)
def retire(*, session: Session, kind: str, name: str, action: str, reason: str,
           into: str = "") -> str:
    """Archive one artefact whose content now lives elsewhere or was shown wrong, via `curation.retire`. Everything is validated before anything moves; failures return text."""
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

    if action == "stale":
        if into:
            return ("a stale retirement names no destination - the content was wrong, so it went "
                    "nowhere; drop `into`")
    elif action == "amended":
        if kind != "memory":
            return "an amended retirement takes a memory; an amendment is only ever raised from one"
        if session.agent and session.agent != APPLIER:
            return (f"an amended retirement is made by the main session or {APPLIER}, not "
                    f"{session.agent!r}")
        if not into.strip():
            return "an amended retirement names the edited file; give `into`"
        resolved = _target(session.root, into)
        if isinstance(resolved, str):
            return f"an amended retirement names the edited file: {resolved}"
        rel = resolved.as_posix()
        # Matched on target too: one memory can have plans pending against several files.
        row = next((r for r in curation.amendments(session)
                    if r.get("from_memory") == name and r.get("target") == rel), None)
        if row is None:
            return (f"no amendment of {name!r} into {rel!r} (given as {into!r}) is on record in "
                    f".un/{curation.DIR}/{curation.AMENDMENTS}")
        plan = curation.path(session, str(row.get("plan") or ""))
        # Resolved, so a row naming `../memory/x.md` cannot move a live file into the plan archive.
        pending = curation.path(session, curation.AMENDMENT_DIR).resolve()
        if not plan.resolve().is_relative_to(pending) or not plan.is_file():
            return (f"the plan for {name!r} into {rel!r} is no longer under "
                    f".un/{curation.DIR}/{curation.AMENDMENT_DIR}/ (its row names "
                    f"{row.get('plan')!r}); nothing was retired")
        into = rel
    else:
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
    if action == "amended":
        # rat-tail: ordered steps, not a transaction; the memory goes first, so an interruption leaves a pending plan to move by hand, never a pending memory with no plan.
        folder = curation.archive_dir(session, curation.AMENDMENT_DIR)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            filed = curation.free(folder, plan.stem, plan.suffix)
            plan.replace(filed)
        except OSError as exc:
            return (f"amended {name} into {into}; archived at {landed}; but the plan could not be "
                    f"archived ({type(exc).__name__}: {exc}), so it is still at {plan} - move it "
                    f"into {folder} by hand")
        return f"amended {name} into {into}; archived at {landed}; plan archived at {filed}"
    moved = f"retired {name} as stale" if action == "stale" else f"{action} {name} into {into}"
    return f"{moved}; archived at {landed}"


# ---------------------------------------------------------------------------
# Amend: proposing a change to a file, and changing nothing
# ---------------------------------------------------------------------------

AMEND_FIELDS = ("section", "clause", "because")

AMENDMENT_PLAN = """# Amendment to {target}

Raised from the memory `{from_memory}` on {at}. **Nothing has been changed.** Apply it with `/apply-amendment <this file>`, or delete this file to decline it.

## Target

`{target}`, under **{section}**

## Clause to add

{clause}

## Why

{because}

## On applying this

`/apply-amendment` hands this plan to the `amendment-applier` agent. It inserts the clause above under that section, retires `{from_memory}` as `amended` into `{target}`, and the same retirement moves this plan to `.un/learning/archive/amendments/`.

An approved amendment ALWAYS retires the memory it came from. The clause now lives in a file the project already follows, so a memory saying the same thing is a second copy to keep in step.

Declining is one action: drop this file and leave the memory alone. The row in `.un/learning/{log}` stays either way, and is what stops a later pass raising this again.
"""


def _target(root: Path, given: str) -> Path | str:
    """The named file relative to the project root, or the refusal. Both sides are resolved so `..` and absolute paths cannot escape, and every spelling of one file comes back the same."""
    root = Path(root).resolve()
    resolved = (root / given).resolve()
    if not resolved.is_relative_to(root):
        return f"target {given!r} is outside the project"
    if not resolved.is_file():
        return f"no file at {given!r} to amend; a target is one file, not a directory"
    return resolved.relative_to(root)


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
    "stays where it is until an operator runs `/apply-amendment` on the plan, and applying it "
    "always retires that memory, because the clause then lives in the target. Write `clause` and "
    "`section` as the "
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

    rel = resolved.as_posix()
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
    def count() -> int:
        return len(_jsonl(candidates_path(session)))

    def commit(before: int) -> str:
        found = count() - before
        curation.log(session, {"at": datetime.now(timezone.utc).isoformat(), "session": session_id,
                               "start": start, "end": end, "candidates": found}, PASSES)
        return f"{found} candidates"

    curation.run(session, DETECTOR, DETECT_PROMPT.format(session_id=session_id, start=start, end=end),
                 count, commit, f"rows {start}-{end} of {session_id}")


@hook("TurnStart")
def detect(*, session: Session) -> None:
    """Every `DETECT_EVERY` turns, run the detector over one unread span, one pass at a time, through `curation.launch`.

    Skipped in forks (`session.inherited`, `session.agent`), so a workflow or a detector never launches a pass the operator's `live`, `stop` and `settle` cannot see, and at turn 0. A missing `detector.md` is reported before forking, or the pass would advance the cursor finding nothing.
    """
    if not session.self_learning or session.inherited or session.agent or not session.turn_index:
        return None
    if session.turn_index % DETECT_EVERY:
        return None
    curation.launch(session, DETECTOR,
                    f"no {DETECTOR}.md in .un/agents/, so nothing was indexed; `un install` seeds it",
                    _detected, lambda: _unread(session))
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
    """One admission pass, shaped like `_detected`. The log row counts this pass's marks by difference."""
    listing = "\n".join(
        f"- {row['id']} - {row.get('topic', '')} "
        f"(session:{row.get('session')}#{row.get('start')}-{row.get('end')})"
        for row in batch)

    def commit(before: tuple[int, int]) -> str:
        after_marked, after_admitted = _marks(session)
        marked, admitted = after_marked - before[0], after_admitted - before[1]
        curation.log(session, {"at": datetime.now(timezone.utc).isoformat(), "read": len(batch),
                               "marked": marked, "admitted": admitted}, ADMISSIONS)
        return f"{marked} marked, {admitted} admitted"

    curation.run(session, ADMITTER, ADMIT_PROMPT.format(count=len(batch), batch=listing),
                 lambda: _marks(session), commit, f"{len(batch)} candidates")


@hook("TurnStart")
def admit(*, session: Session) -> None:
    """When the backlog is due, run the admitter over the oldest unmarked batch. `detect`'s guards, no stride.

    The backlog stays due while the admitter runs, so `curation.launch`'s one-pass-at-a-time guard is what stops a fork per turn. rat-tail: parses `candidates.jsonl` every turn.
    """
    if not session.self_learning or session.inherited or session.agent or not session.turn_index:
        return None
    rows = _unmarked(session)
    if not _due(rows, "at", ADMIT_AT, ADMIT_AFTER):
        return None
    curation.launch(session, ADMITTER,
                    f"no {ADMITTER}.md in .un/agents/, so {len(rows)} candidates are waiting; "
                    f"`un install` seeds it",
                    _admitted, lambda: (rows[:ADMIT_BATCH],))
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


def _placed_pass(session: Session, batch: list[dict]) -> None:
    """One placement pass, shaped like `_admitted`."""
    listing = "\n".join(
        f"- {row['id']} - {row.get('topic', '')} "
        f"(session:{row.get('session')}#{row.get('start')}-{row.get('end')})\n"
        f"  the admitter kept it because: {row.get('reason', '')}"
        for row in batch)

    def commit(before: tuple[int, int, int]) -> str:
        created, merged, declined = (now - was for now, was in zip(_placements(session), before))
        curation.log(session, {"at": datetime.now(timezone.utc).isoformat(), "read": len(batch),
                               "created": created, "merged": merged, "declined": declined},
                     PLACEMENTS)
        return f"{created} created, {merged} merged, {declined} declined"

    curation.run(session, IMPLEMENTOR, PLACE_PROMPT.format(count=len(batch), batch=listing),
                 lambda: _placements(session), commit, f"{len(batch)} candidates")


@hook("TurnStart")
def place(*, session: Session) -> None:
    """When admitted candidates are due, run the implementor over the oldest unplaced batch. `admit`'s guards, aged on `marked`.

    rat-tail: parses `candidates.jsonl` every turn, again after `admit`.
    """
    if not session.self_learning or session.inherited or session.agent or not session.turn_index:
        return None
    rows = _unplaced(session)
    if not _due(rows, "marked", PLACE_AT, PLACE_AFTER):
        return None
    curation.launch(session, IMPLEMENTOR,
                    f"no {IMPLEMENTOR}.md in .un/agents/, so {len(rows)} admitted candidates are "
                    f"waiting; `un install` seeds it",
                    _placed_pass, lambda: (rows[:PLACE_BATCH],))
    return None


GUIDANCE = """# Memory

You have `Remember` and `Recall`. `Remember` records ONE durable fact as its own file
under .un/memory/ and adds a line to the index below; `Recall` reads one back in full.
Only the index is in this prompt - read a memory when its description says it matters.

Record a preference, a project constraint, or a decision and its reason - anything you
would otherwise have to be told again next time. Do not record what the code or git
history already says, or anything that only matters to this conversation.

- `name` is a short kebab-case slug and becomes the filename; `description` is the one
  line the index shows, and is what a later session decides to read on.
- `type` is one of: `user` (who they are), `feedback` (how to work, and why), `project`
  (ongoing work, goals, constraints), `reference` (pointers to external resources).
- A `feedback` or `project` fact carries **Why:** and **How to apply:** lines under the
  fact itself.
- Link a related memory as [[its-name]].
- Before recording, check the index for one that already covers it and `Remember` under
  that same name to replace it. Two memories on one subject is worse than none."""


@hook("SessionEnd")
def settle(*, session: Session, code: int) -> None:
    """Wait out this session's learning passes before the process exits."""
    curation.settle(session)


@hook("SessionStart")
def inject(*, session: Session) -> str | None:
    """Run curation, then inject the memory guidance and the bounded index.

    The guidance is sent even with no memories, or the agent never learns to remember. Sessions whose tool list lacks `Remember` get nothing.
    """
    curate(session)
    if session.tools is not None and "Remember" not in session.tools:
        return None
    # The editor already gets the whole index in its prompt.
    if session.agent == EDITOR:
        return GUIDANCE
    path = index_path(session)
    notes = _snapshot(path.read_text(encoding="utf-8").strip()) if path.exists() else ""
    return f"{GUIDANCE}\n\n{notes}" if notes else GUIDANCE
