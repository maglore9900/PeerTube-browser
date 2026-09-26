"""Skills: the `Skill` tool (bodies on demand, names and descriptions in the prompt), `SkillManage`, and the skill curation pass.

`SkillManage` sets `name` and stamps `metadata: {author: agent}` itself, and only amends skills carrying that marker; nothing is ever deleted, and `patch` refuses a result with a broken header. The curator, called from `index` before the listing is built, retires agent-written, unpinned skills nobody has read for `retire_after_days` to `.un/learning/archive/skills/` (ADR-0029); it is off unless `[self_learning.curate.skills]` is set. Usage stamps live in `.un/learning/skill-curator.json`, never in a skill. Frontmatter is parsed by `core.frontmatter`, which records rather than raises.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from un.core import locked
from un import Session, core, frontmatter, hook, service, tool, use
# `refused` is the only thing confining skill names to `.un/skills/`.
from un.core import CONFIG, refused, un_dir
from un.plugins.stock import curation

AGENT = curation.AGENT

ACTIONS = ("create", "write", "patch")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    # Keyed by directory name, which `[skills.<name>]` and `SkillManage` both use.
    enabled: bool = False
    frontmatter_error: str | None = None
    agent_created: bool = False
    pinned: bool = False


def _marked(data: dict) -> bool:
    """Whether the frontmatter claims the agent as author."""
    return curation.by_agent(data)



def _load(folder: Path, on: frozenset[str] = frozenset()) -> Skill:
    path = folder / "SKILL.md"
    data, body, error = frontmatter.parse(path.read_text(encoding="utf-8"))

    return Skill(
        # The directory name stands in when the header is unreadable.
        name=str(data.get("name") or folder.name),
        description=str(data.get("description") or ""),
        body=body,
        path=path,
        enabled=folder.name in on,
        frontmatter_error=error,
        agent_created=_marked(data),
        pinned=_pinned(data),
    )


def root(session: Session) -> Path:
    return un_dir(session.root, "skills")


def home(session: Session, name: str) -> Path:
    """The directory one skill lives in."""
    return root(session) / name


def _target(here: Path, path: str) -> Path | None:
    """`path` resolved to a file inside the skill directory, or None. Resolving catches `..` and absolute paths alike."""
    candidate = (here / path).resolve()
    if not candidate.is_relative_to(here) or candidate == here or candidate.is_dir():
        return None
    return candidate


def _existing(session: Session, name: str) -> Skill | None:
    """The skill in directory `name` (which may differ from its frontmatter name), or None."""
    here = home(session, name)
    return (_load(here, _enabled(session.root))
            if (here / "SKILL.md").is_file() else None)


def _guarded(session: Session, name: str) -> str | None:
    """Refuse amending a skill this tool did not author, including adding files beside its SKILL.md."""
    entry = _existing(session, name)
    if entry is None:
        return f"no skill named {name!r}; create it first"
    if not entry.agent_created:
        return f"skill {name!r} was authored by an operator; SkillManage only amends its own"
    return None


def _stamped(name: str, content: str) -> tuple[str | None, str | None]:
    """`content` with `name` and the agent marker forced, or a refusal. The model controls only description and body.

    rat-tail: re-serialising drops YAML comments.
    """
    data, body, error = frontmatter.parse(content)
    if error:
        return None, f"refused: {error}"
    if not str(data.get("description") or "").strip():
        return None, "refused: SKILL.md frontmatter needs a description"

    data["name"] = name
    metadata = data.get("metadata")
    data["metadata"] = ({**metadata, "author": AGENT} if isinstance(metadata, dict)
                        else {"author": AGENT})
    return frontmatter.render(data, body), None


def _invalid(name: str, text: str) -> str | None:
    """What a patched SKILL.md got wrong, or None. `patch` refuses where `write` would repair."""
    data, _, error = frontmatter.parse(text)
    if error:
        return f"the result has {error}"
    if str(data.get("name") or "") != name:
        return "the result renames the skill"
    if not str(data.get("description") or "").strip():
        return "the result leaves no description"
    if not _marked(data):
        return "the result drops the agent-created marker"
    return None


def _document(name: str, description: str, body: str) -> str:
    """A SKILL.md built from parts, so identity and provenance are right by construction."""
    return frontmatter.render(
        {"name": name, "description": description, "metadata": {"author": AGENT}}, body)


def _enabled(where: Path) -> frozenset[str]:
    """Skills enabled by `[skills.<name>]`; empty when the config is unreadable (`index` reports that)."""
    return core.enabled_lenient(where, "skills", "skill")[0]


def _scan(where: Path) -> list[Skill]:
    """Every skill under the project root `where`, in directory order, enabled or not."""
    folder = un_dir(where, "skills")
    if not folder.is_dir():
        return []
    on = _enabled(where)
    return [
        _load(child, on)
        for child in sorted(folder.iterdir())
        if child.is_dir() and (child / "SKILL.md").is_file()
    ]


def discover(session: Session) -> list[Skill]:
    """Every skill on disk in name order, enabled or not, since a disabled skill still occupies its name."""
    return _scan(session.root)


@service("skills:names")
def names(where: Path) -> list[str]:
    """Every skill's frontmatter name on disk under `where`, for a `Skill(...)` scope to be checked against."""
    return [entry.name for entry in _scan(where)]


@hook("SessionStart")
def index(*, session: Session) -> str | None:
    """Run curation, then list enabled skills' names and descriptions. Nothing for a session without the `Skill` tool."""
    # Called here, not registered, so curation finishes before the listing is built.
    curate(session)
    if session.tools is not None and "Skill" not in session.tools:
        return None
    # Reported once per session, or skills vanish unexplained.
    if config_error := core.enabled_lenient(session.root, "skills", "skill")[1]:
        session.report("skills: config", config_error)
    return listing(session)


@service("skills:list")
def listing(session: Session) -> str | None:
    """Every enabled skill's name and description, or None. Also a service, for the memory reviser, which lacks the `Skill` tool."""
    found = [entry for entry in discover(session) if entry.enabled]
    if session.agent:
        try:
            allowed = use("agents", "scopes")(session.agent).get("Skill")
        except LookupError:
            # The subagents plugin is off, so no agent file declared a scope.
            allowed = None
        if allowed is not None:
            # By frontmatter name, the one the `Skill` tool and its scope both take.
            found = [entry for entry in found if entry.name in allowed]
    if not found:
        return None
    lines = ["# Skills", "", "Read one with the `Skill` tool before doing related work."]
    for entry in found:
        if entry.frontmatter_error:
            lines.append(f"- {entry.name}: (unreadable - {entry.frontmatter_error})")
        else:
            lines.append(f"- {entry.name}: {entry.description}")
    return "\n".join(lines)


@tool(
    "Skill",
    "Read the full instructions for a named skill.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
def skill(*, session: Session, name: str) -> str:
    found = discover(session)
    for entry in found:
        if entry.name == name:
            if not entry.enabled:
                # Said plainly, not hidden, so the operator can act on it.
                return (f"refused: the skill {name!r} is present but not enabled; add "
                        f"[skills.{name}] with {ENABLE} = true to {CONFIG.as_posix()}")
            return entry.body
    available = ", ".join(e.name for e in found if e.enabled) or "none"
    return f"no skill named {name!r}; available: {available}"


@tool(
    "SkillManage",
    "Author a skill under .un/skills/. `create` makes a new one from a description and a "
    "body; `write` replaces its SKILL.md or adds a supporting file; `patch` replaces one "
    "exact occurrence in either. Only skills this tool created can be amended, and nothing "
    "is ever removed.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "body": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        "required": ["action", "name"],
    },
)
def skill_manage(*, session: Session, action: str, name: str, description: str = "",
                 body: str = "", path: str = "SKILL.md", content: str = "",
                 old: str = "", new: str = "") -> str:
    if refusal := refused("skill", name):
        return refusal
    if action not in ACTIONS:
        return f"unknown action {action!r}; use one of: {', '.join(ACTIONS)}"

    here = home(session, name)

    if action == "create":
        if here.exists():
            return f"skill {name!r} already exists; amend it rather than creating it again"
        if not description.strip():
            return "refused: a skill needs a description; it is what the index shows"

        here.mkdir(parents=True)
        (here / "SKILL.md").write_text(_document(name, description, body),
                                       encoding="utf-8")
        # Only an operator can enable it, or the agent would be writing its own standing orders.
        return (f"created skill {name}; it is not enabled - an operator turns it on with "
                f"[skills.{name}] {ENABLE} = true in {CONFIG.as_posix()}")

    if refusal := _guarded(session, name):
        return refusal

    here = here.resolve()
    target = _target(here, path)
    if target is None:
        return f"refused: {path!r} is not a file inside the skill directory"

    is_skill_md = target == here / "SKILL.md"

    if action == "write":
        text = content
        if is_skill_md:
            text, refusal = _stamped(name, content)
            if refusal:
                return refusal

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return f"wrote {name}/{path}"

    if not target.is_file():
        return f"no file {path!r} in skill {name!r}"
    if not old:
        # An empty `old` would match an empty file once and replace it wholesale.
        return "refused: patch needs the text to replace; `old` is empty"

    text = target.read_text(encoding="utf-8")
    found = text.count(old)
    if found != 1:
        return (f"expected exactly one occurrence of that text in {name}/{path}, "
                f"found {found}; include more surrounding context to make it unique")

    patched = text.replace(old, new)
    if is_skill_md and (problem := _invalid(name, patched)):
        return f"refused: {problem}; {name}/{path} left unchanged"

    target.write_text(patched, encoding="utf-8")
    return f"patched {name}/{path}"


# ---------------------------------------------------------------------------
# Curation: retiring what nobody reads
# ---------------------------------------------------------------------------

# Kept under `.un/learning/`, not in each SKILL.md (ADR-0027).
STATE = curation.SKILLS_STATE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state(session: Session) -> dict:
    """The curator's state, or {}. Never raises."""
    return curation.load(session, STATE)


def _records(state: dict) -> dict:
    """The per-skill records, or {} when absent or malformed."""
    records = state.get("skills")
    return records if isinstance(records, dict) else {}


def _save(session: Session, state: dict) -> None:
    curation.save(session, STATE, state)


@hook("ToolEnd")
def record_use(*, session: Session, call: dict) -> None:
    """Stamp a successful `Skill` read in the curator state. On ToolEnd so the tool stays read-only. A headless DENY leaves no `result` key; every other refusal or failure carries a truthy `error`, and reading a disabled skill is a refusal with neither. Subagent reads count.

    rat-tail: load and save are separate calls, so concurrent reads can lose a count.
    """
    if not session.self_learning:
        return
    if call.get("name") != "Skill" or "result" not in call or call.get("error"):
        return
    name = (call.get("input") or {}).get("name")
    # The first match, as `skill()` resolves it: a disabled first match is a call the tool refused.
    entry = next((entry for entry in discover(session) if entry.name == name), None)
    if entry is None or not entry.enabled:
        return

    state = _state(session)
    record = state.setdefault("skills", {}).setdefault(name, {})
    record["uses"] = int(record.get("uses") or 0) + 1
    record["last_use_at"] = _now().isoformat()
    _save(session, state)


def _pinned(data: dict) -> bool:
    """Whether `metadata.pinned` is exactly True (so `pinned: "no"` does not pin)."""
    metadata = data.get("metadata")
    return isinstance(metadata, dict) and metadata.get("pinned") is True


def _eligible(entries) -> set[str]:
    """Skills the pass may retire: agent-written and unpinned. All skills are still seeded."""
    return {entry.name for entry in entries if entry.agent_created and not entry.pinned}


ENABLE = "enable"

# `[self_learning.curate.skills]`, not `[skills]`, whose sub-tables are all read as skills.
TARGET = "skills"


def _curate(root: Path) -> tuple[int, int]:
    """This collection's `[self_learning.curate]` settings."""
    return curation.settings(root, TARGET)


def curate(session: Session) -> None:
    """Retire agent-written skills nobody reads, inline, from `index`. The first run only stamps `last_run_at`; a malformed table raises."""
    # Off with self-learning, and in forks, which would race on `last_run_at`.
    if not session.self_learning or session.agent:
        return None
    every_days, after_days = _curate(session.root)
    if not every_days:
        return None

    state = _state(session)
    now = _now()
    last = curation.parse(state.get("last_run_at"))
    if last is None:
        state["last_run_at"] = now.isoformat()
        _save(session, state)
        return None
    if now - last < timedelta(days=every_days):
        return None

    entries = discover(session)
    # For skills, the records key and the collection directory are both "skills".
    notes = curation.apply(
        session, state, TARGET, TARGET, lambda name: home(session, name),
        curation.transitions([entry.name for entry in entries], _eligible(entries),
                             _records(state), now, after_days),
        now)
    _save(session, state)
    if notes and curation.visible(session.root):
        for line in notes:
            session.note("skills: curate", f"retired {line}")
    return None
