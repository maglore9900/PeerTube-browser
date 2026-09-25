"""Durable agent memory: `Remember` and `Recall`, a SessionStart hook injecting the index, and the memory curation pass.

One fact per markdown file under `.un/memory/`, indexed by `MEMORY.md`; only the index reaches the prompt, capped at `LIMIT` lines. The index is never rebuilt from disk, because deleting a line is how a memory is pruned. Recalls are recorded under `.un/learning/`, never in the memory file.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from un.core import locked
from un import Session, frontmatter, hook, tool, use
# `refused` is the only thing confining names to `.un/memory/`.
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


@hook("ToolEnd")
def record_read(*, session: Session, call: dict) -> None:
    """Stamp a successful Recall of an existing memory in the curator state, as `skills.record_use` does.

    On ToolEnd so `Recall` itself stays read-only. A refused call has no `result` key. Subagent recalls count too.
    """
    if not session.self_learning:
        return
    if call.get("name") != "Recall" or "result" not in call:
        return
    name = (call.get("input") or {}).get("name")
    if not isinstance(name, str) or refused("memory", name) or not memory_path(session, name).is_file():
        return
    state = curation.load(session, STATE)
    record = state.setdefault("memories", {}).setdefault(name, {})
    # Truthiness, not `int`: a hand-edited count must not raise.
    record["uses"] = int(record.get("uses") or 0) + 1
    record["last_use_at"] = datetime.now(timezone.utc).isoformat()
    curation.save(session, STATE, state)


# ---------------------------------------------------------------------------
# Curation: reporting on what nobody recalls
# ---------------------------------------------------------------------------

TARGET = "memory"
REPORT = "memory-curation-report.md"

# The agent `revise` arms. Its tool list lacks Recall and Skill, so it does not touch the usage clocks.
REVISER = "reviser"

# Carries the whole index, not `_snapshot`: the reviser judges the full collection.
REVISE_PROMPT = (
    "Here is the whole memory index, every memory in the collection. Only the newest {limit} "
    "lines of it reach a session's system prompt and it is {size} lines long, so "
    "{dropped} of these reach no prompt at all. Decide leave, update, merge or promote for each "
    "one and carry out what you decide, opening a memory's file when you need what is in it."
    "\n\n{index}\n\n{skills}")

# Stated explicitly: an empty skills section would read as "no skills" and invite duplicate promotions.
NO_SKILLS = ("No skill collection was available on this pass, so nothing is known about what "
             "the skills already cover. Do not promote anything.")

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
    """The names the index lists, in the order it lists them."""
    out = []
    for line in text.splitlines():
        if line.startswith("- ["):
            out.append(line[3:].split("]", 1)[0])
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


def _findings(text: str, on_disk: list[str], records: dict, now: datetime, after_days: int,
              retired: list[dict], since: datetime) -> list[tuple[str, list[str]]]:
    """The whole report, as (heading, lines). Pure: no disk, no clock."""
    listed = _pointers(text)
    cutoff = now - timedelta(days=after_days)
    reaching = _snapshot(text)

    def record(name):
        entry = records.get(name)
        return entry if isinstance(entry, dict) else None

    def cold(name):
        entry = record(name)
        if entry is None:
            return None
        stamp = curation.parse(entry.get("last_use_at"))
        return stamp if stamp is not None and stamp < cutoff else None

    def unread(name):
        """No readable `last_use_at` stamp. Seeded records exist for every memory, so the record's absence alone is not enough."""
        entry = record(name)
        return entry is None or curation.parse(entry.get("last_use_at")) is None

    return [
        ("Pointers with no file", [f"- {name}" for name in listed if name not in on_disk]),
        ("Files with no pointer", [f"- {name}" for name in on_disk if name not in listed]),
        ("Never read", [f"- {name}" for name in on_disk if unread(name)]),
        (f"Cold for more than {after_days} days",
         [f"- {name} - last read {cold(name).date().isoformat()}" for name in on_disk if cold(name)]),
        ("Possibly superseded", _superseded(sorted(set(listed) | set(on_disk)))),
        ("Dropped from the prompt",
         [f"- {line[3:].split(']', 1)[0]}" for line in text.splitlines()
          if line.startswith("- [") and line not in reaching]),
        (f"Retired since {since.date().isoformat()}", _retired(retired, since)),
    ]


def _render(findings: list[tuple[str, list[str]]], now: datetime) -> str:
    """The report as markdown. Empty findings keep their heading, so a quiet pass is distinguishable from one that did not look."""
    parts = [f"# Memory curation report\n\nGenerated {now.isoformat()}. Read-only: this pass proposes, "
             f"and the operator decides.\n"]
    for heading, lines in findings:
        parts.append(f"## {heading} ({len(lines)})\n\n" + "\n".join(lines or ["- none"]) + "\n")
    return "\n".join(parts)


_REVISING: threading.Thread | None = None

# Sessions already told there is no reviser; reported once each.
_REVISER_REPORTED: set[str] = set()


def _revise_pass(session: Session, text: str) -> None:
    """One reviser pass, on its own thread, shaped like `learning._placed_pass`.

    Notes this pass's merges, promotions and amendments, counted by difference in the logs. A promoted skill is named because it is present but not enabled or audited.
    """
    before = len(curation.retirements(session))
    before_raised = len(curation.amendments(session))
    try:
        use("agents", "run")(session, REVISER, _revise_prompt(session, text))
    except Exception as exc:  # noqa: BLE001
        session.report(REVISER, f"{type(exc).__name__}: {exc}")
        return
    rows = curation.retirements(session)[before:]
    raised = curation.amendments(session)[before_raised:]
    if not curation.visible(session.root) or not (rows or raised):
        return
    merged = sum(1 for row in rows if row.get("action") == "merged")
    promoted = [row.get("into") for row in rows if row.get("action") == "promoted"]
    if merged:
        session.note(REVISER, f"{merged} memories merged away; each one says why in "
                              f"{curation.RETIREMENTS}")
    if promoted:
        session.note(REVISER, f"promoted into {', '.join(promoted)} - present but NOT enabled "
                              f"and NOT audited; run skill-auditor over it, then add "
                              f"[skills.<name>] enable = true")
    if raised:
        session.note(REVISER, f"{len(raised)} amendment plan(s) raised under "
                              f".un/{curation.DIR}/{curation.AMENDMENT_DIR}/ - NOTHING was "
                              f"changed; read one and apply it by hand, or delete it to decline")


def _revise(session: Session, text: str) -> None:
    """Start the reviser on a non-daemon thread, one pass at a time. A missing `reviser.md` is reported once; a disabled subagents plugin is silent."""
    global _REVISING
    try:
        available = use("agents", "names")()
    except LookupError:
        return
    if REVISER not in available:
        if session.id not in _REVISER_REPORTED:
            _REVISER_REPORTED.add(session.id)
            session.report(REVISER, f"no {REVISER}.md in .un/agents/, so the collection was "
                                    f"reported on but not revised; `un install` seeds it")
        return
    if _REVISING is not None and _REVISING.is_alive():
        return
    _REVISING = threading.Thread(target=_revise_pass, args=(session, text), daemon=False)
    _REVISING.start()


def _revise_prompt(session: Session, text: str) -> str:
    """The reviser's prompt: the whole index, the skills list (or `NO_SKILLS`), and how many lines miss the prompt."""
    reaching = _snapshot(text)
    dropped = sum(1 for line in text.splitlines()
                  if line.startswith("- [") and line not in reaching)
    try:
        skills = use("skills", "list")(session) or NO_SKILLS
    except LookupError:
        skills = NO_SKILLS
    return REVISE_PROMPT.format(limit=LIMIT, size=len(text.splitlines()), dropped=dropped,
                                index=text, skills=skills)


def curate(session: Session) -> None:
    """The memory curation pass: retire stale memories, write the report, and optionally start the reviser.

    Called from `inject` so it finishes before the index is read. Gated like `skills.curate`: off in forks, and the first run only stamps `last_run_at`.
    """
    if not session.self_learning or session.agent:
        return None
    every_days, after_days, revise = curation.settings(session.root, TARGET)
    if not every_days:
        return None

    state = curation.load(session, STATE)
    now = datetime.now(timezone.utc)
    last = curation.parse(state.get("last_run_at"))
    if last is None:
        state["last_run_at"] = now.isoformat()
        curation.save(session, STATE, state)
        return None
    if now - last < timedelta(days=every_days):
        return None

    folder = root(session)
    names = _on_disk(folder)
    records = state.get("memories")
    # Every memory is eligible; unlike skills, there is no operator-authored kind.
    notes = curation.apply(
        session, state, "memories", TARGET, lambda name: memory_path(session, name),
        curation.transitions(names, set(names), records if isinstance(records, dict) else {}, now,
                             after_days),
        now)

    # The report re-reads disk after retiring, so it describes the collection as it now is. `last` must stay parsed before `apply` restamped it.
    path = index_path(session)
    text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    report = curation.path(session, REPORT)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        _render(_findings(text, _on_disk(folder), state.get("memories") or {}, now,
                          after_days, curation.retirements(session), last), now),
        encoding="utf-8")

    curation.save(session, STATE, state)
    if notes and curation.visible(session.root):
        for line in notes:
            session.note("memory: curate", f"retired {line}")

    # Last, after the report is written, so the report describes what the reviser was given.
    if revise:
        _revise(session, text)
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


@hook("SessionStart")
def inject(*, session: Session) -> str | None:
    """Run curation, then inject the memory guidance and the bounded index.

    The guidance is sent even with no memories, or the agent never learns to remember. Sessions whose tool list lacks `Remember` get nothing.
    """
    curate(session)
    if session.tools is not None and "Remember" not in session.tools:
        return None
    # The reviser already gets the whole index in its prompt.
    if session.agent == REVISER:
        return GUIDANCE
    path = index_path(session)
    notes = _snapshot(path.read_text(encoding="utf-8").strip()) if path.exists() else ""
    return f"{GUIDANCE}\n\n{notes}" if notes else GUIDANCE
