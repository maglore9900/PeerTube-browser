"""Durable agent memory: `Remember` and `Recall`, a SessionStart hook injecting the index, and the memory curation pass.

One fact per markdown file under `.un/memory/`, indexed by `MEMORY.md`; only the index reaches the prompt, capped at `LIMIT` lines. The index is never rebuilt from disk, because deleting a line is how a memory is pruned.
"""

from __future__ import annotations

import bisect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from un.core import locked
from un import Session, frontmatter, hook, service, tool, use
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
    """The accuracy check over `batch`, then one memory editor pass, shaped like `learning._placed_pass`.

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

    Called from `inject` so it finishes before the index is read. Off in forks, and the first run only stamps `last_run_at`. With `revise` on, the editor's commit stamps it instead.
    """
    if not session.self_learning or session.agent:
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
    """Wait out this session's learning passes before the process exits; `learning` registers the same, so either plugin alone suffices."""
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
