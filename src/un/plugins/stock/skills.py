"""Skills: the `Skill` tool (bodies on demand, names and descriptions in the prompt) and `SkillManage`.

`SkillManage` sets `name` and stamps `metadata: {author: agent}` itself, and only amends skills carrying that marker; nothing is ever deleted, and `patch` refuses a result with a broken header. Frontmatter is parsed by `core.frontmatter`, which records rather than raises.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
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
    """List enabled skills' names and descriptions. Nothing for a session without the `Skill` tool."""
    if session.tools is not None and "Skill" not in session.tools:
        return None
    # Reported once per session, or skills vanish unexplained.
    if config_error := core.enabled_lenient(session.root, "skills", "skill")[1]:
        session.report("skills: config", config_error)
    return listing(session)


@service("skills:list")
def listing(session: Session) -> str | None:
    """Every enabled skill's name and description, or None. Also a service, for the memory editor, which lacks the `Skill` tool."""
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


def _pinned(data: dict) -> bool:
    """Whether `metadata.pinned` is exactly True (so `pinned: "no"` does not pin)."""
    metadata = data.get("metadata")
    return isinstance(metadata, dict) and metadata.get("pinned") is True


ENABLE = "enable"
