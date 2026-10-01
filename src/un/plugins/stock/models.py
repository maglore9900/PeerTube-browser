"""Model context windows and per-token prices, the two reductions over usage rows that surfaces display, and the per-conversation context warning. Writes no file.

Data layers, lowest first: the shipped `un/defaults/models.toml` (or the project's `.un/models.toml` copy), a probed window, then `[models."<name>"]` in `.un/config.toml`. Cost is cumulative over every record of the session, subagents included, each row priced by its own model; the meter's fullness is the latest main-record row only, since every turn resends the history. Separately, the `Turn` hook keeps each conversation's own latest prompt size and fullness on its session and notes the operator once when that reaches `[compaction] threshold`, unless `[compaction] enable` is on. With `[compaction] enable`, the `compaction:send` service replaces the earlier part of what each conversation sends with a summary written by `[compaction] model`, recording each one as a `compacted` event.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from un import CacheSpec, Profile, Session, hook, service, use
from un.core import CONFIG, MAIN, UN_DIR, providers

SHIPPED = resources.files("un") / "defaults" / "models.toml"
PROJECT = UN_DIR / "models.toml"

KINDS = ("input", "cache_read", "cache_write", "output")

# A size, not a price: zero is invalid here, where a zero rate is real.
CONTEXT = "context"

# Holds the probed window, and guards against probing twice when `/reload` re-fires SessionStart. Not named MODELS: a test scans for constants whose name contains "model".
STATE_KEY = "models"

# `anthropic_provider.DEFAULT`'s twin, spelled out because importing that plugin would register it. `launch` probes with it for a session on "anthropic" that no profile claims; other unclaimed providers are not probed.
FALLBACK = Profile(name="anthropic", adaptor="anthropic", model="")


def _clean(raw: dict) -> dict:
    """One `[models.<name>]` table with unusable values dropped field by field, so one typo does not unprice the model.

    Bools are rejected (bool is an int). A zero rate is kept, since local models are free; a zero window is dropped.
    """
    out: dict[str, float | int] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if key == CONTEXT and value > 0:
            out[key] = int(value)
        elif key in KINDS and value >= 0:
            out[key] = float(value)
    return out


def _raw(source) -> object:
    """One TOML file's raw `[models]` value, shared by the table layer and `faults`. Propagates read and parse errors."""
    return tomllib.loads(source.read_text(encoding="utf-8")).get("models")


def _table(raw: object) -> dict[str, dict]:
    """A `[models]` mapping as name -> cleaned entry. Anything else is no table at all."""
    if not isinstance(raw, dict):
        return {}
    return {name: _clean(entry) for name, entry in raw.items()
            if isinstance(entry, dict)}


def _built_in(cwd: Path) -> dict[str, dict]:
    """The base table: the project's `.un/models.toml` if present, else the shipped file.

    An unparseable project file gives an empty table (everything unpriced), not the shipped one. A broken shipped file raises, since that is a broken install. Silent here because this runs per status line; `faults` reports once per session.
    """
    path = Path(cwd) / PROJECT
    if path.is_file():
        try:
            return _table(_raw(path))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return {}
    return _table(_raw(SHIPPED))


def _configured(cwd: Path) -> dict[str, dict]:
    """The `[models]` entries in `.un/config.toml`, re-read per call; {} when absent or unparseable."""
    path = Path(cwd) / CONFIG
    if not path.is_file():
        return {}
    try:
        return _table(_raw(path))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def window(cwd: Path, model: str, probed: int | None = None) -> int | None:
    """The context window in tokens, or None. The operator's entry wins, then the probed value, then the base table."""
    for stated in (_configured(cwd).get(model, {}).get(CONTEXT), probed,
                   _built_in(cwd).get(model, {}).get(CONTEXT)):
        if stated:
            return stated
    return None


def prices(cwd: Path, model: str) -> dict[str, float] | None:
    """Per-kind prices in dollars per million tokens, or None unless both `input` and `output` are stated.

    A missing cache rate falls back to the input rate (a presence test, so a stated zero is kept).
    """
    merged = {**_built_in(cwd).get(model, {}), **_configured(cwd).get(model, {})}
    if "input" not in merged or "output" not in merged:
        return None
    return {kind: merged.get(kind, merged["input"]) for kind in KINDS}


def _usable(value: object) -> int | None:
    """A probed window if it is a positive int (not a bool), else None. It becomes a divisor."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _entries(raw: object, path: Path) -> list[str]:
    """Operator-facing sentences for what `_clean` would drop from one file's `[models]` value; [] when all usable."""
    if raw is None:
        return []      # no `[models]` section at all, which is an ordinary state
    if not isinstance(raw, dict):
        return [f"[models] in {path} is not a table of named sub-tables, so nothing in it "
                f"sizes or prices a model"]
    out = []
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            out.append(f'[models."{name}"] in {path} is not a table, so it was ignored')
        elif dropped := sorted(set(entry) - set(_clean(entry))):
            out.append(f'[models."{name}"] in {path} states unusable '
                       f'{", ".join(dropped)}, so those were ignored')
    return out


def faults(cwd: Path) -> list[str]:
    """Everything the table layer silently dropped, as sentences. Called once per session from `launch`."""
    out = []
    project, config = Path(cwd) / PROJECT, Path(cwd) / CONFIG
    if project.is_file():
        try:
            out += _entries(_raw(project), project)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            out.append(f"{project} could not be read, so nothing in it sizes or prices a "
                       f"model: {exc}")
    if config.is_file():
        try:
            out += _entries(_raw(config), config)
        except (OSError, tomllib.TOMLDecodeError):
            # Silent: `launch` already reports this file through `core.providers`.
            pass
    return out


def _gap(cwd: Path, model: str, probed: int | None) -> str | None:
    """One sentence naming what `[models."<model>"]` is missing (window, rates, or both), or None."""
    missing = [what for what, known in
               (("a context window", window(cwd, model, probed) is not None),
                ("input and output rates", prices(cwd, model) is not None)) if not known]
    if not missing:
        return None
    return (f'nothing states {" or ".join(missing)} for {model!r} - add a '
            f'[models."{model}"] block to {CONFIG}')


@hook("SessionStart")
def launch(*, session: Session) -> None:
    """Once per session: probe the endpoint for the model's context window, then report table faults and gaps. Adds no prompt text.

    The probe service is resolved and called under separate guards, so a probe raising LookupError is not mistaken for no probe. A session on "anthropic" that no profile claims is probed as FALLBACK; a malformed config is not.
    """
    # "window", not the key: the `Turn` hook also writes under STATE_KEY, and may do so first on a resumed session.
    if "window" in session.state.get(STATE_KEY, {}):
        return None
    probed, probe = None, None
    try:
        profile = _profile(session.root, session.provider)
    except ValueError as exc:
        # Reported, not raised: SessionStart must not stop a session over a config typo.
        session.report("models: table", str(exc))
        profile = None
    else:
        # The session `anthropic_provider.DEFAULT` serves. A table naming only other anthropic profiles still lands here; its turn then fails with LookupError, which is harmless.
        if profile is None and session.provider == FALLBACK.name:
            profile = FALLBACK
    if profile is not None:
        try:
            probe = use("probe", profile.adaptor)
        except LookupError:
            probe = None
    if probe is not None:
        try:
            answer = probe(profile, session.model)
        except Exception as exc:  # noqa: BLE001
            session.report("models: probe", f"could not read a context window for "
                                            f"{session.model!r} from {profile.name!r}: {exc}")
        else:
            probed = _usable(answer)
            # A non-None unusable answer is reported; None means the endpoint states none.
            if probed is None and answer is not None:
                session.report("models: probe",
                               f"{profile.name!r} stated {answer!r} as the context window "
                               f"for {session.model!r}, which is not a usable size")
    session.state.setdefault(STATE_KEY, {})["window"] = probed
    for fault in faults(session.root):
        session.report("models: table", fault)
    if gap := _gap(session.root, session.model, probed):
        session.report("models: table", gap)
    return None


# ---------------------------------------------------------------------------
# The two reductions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Meter:
    """How full the session's window is and what it has cost. None means unknown, not zero; `fullness` is not capped at 1.0."""

    fullness: float | None   # the LATEST main-record turn against the window
    cost: float | None       # US dollars, CUMULATIVE across every record of the session


def _count(row: dict, key: str) -> float:
    """One counter from a usage row, or 0 when it is not a number. Rows arrive unvalidated, and this runs on the render path."""
    value = row.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def _split(row: dict, adaptor: str) -> dict[str, float]:
    """One usage row as the four kinds. OpenAI input tokens include cached ones, so they are subtracted there and not for Anthropic."""
    read = _count(row, "cache_read_input_tokens")
    raw = _count(row, "input_tokens")
    fresh = raw - read if adaptor == "openai" else raw
    # Clamped: the endpoint's two numbers need not be consistent.
    return {"input": max(fresh, 0), "cache_read": read,
            "cache_write": _count(row, "cache_creation_input_tokens"),
            "output": _count(row, "output_tokens")}


def _prompt_tokens(row: dict, adaptor: str) -> float:
    """What one request sent: fresh input plus cache reads plus cache writes."""
    kinds = _split(row, adaptor)
    return kinds["input"] + kinds["cache_read"] + kinds["cache_write"]


def _profile(cwd: Path, provider: str) -> Profile | None:
    """The `[providers.<name>]` entry a session names, or None when nothing claims it."""
    return next((p for p in providers(cwd) if p.name == provider), None)


def _adaptor(cwd: Path, provider: str) -> str:
    """The adaptor a profile name uses; "anthropic" when no profile claims it, matching `anthropic_provider.DEFAULT`."""
    found = _profile(cwd, provider)
    return found.adaptor if found else "anthropic"


def _fullness(session: Session, rows: list[dict]) -> float | None:
    """The latest row's context tokens over the session model's window, or None. Uses the session's model, not the row's stamp."""
    size = window(session.root, session.model,
                  session.state.get(STATE_KEY, {}).get("window"))
    if not rows or not size:
        return None
    return _prompt_tokens(rows[-1], _adaptor(session.root, session.provider)) / size


def _cost(cwd: Path, rows: list[dict]) -> float | None:
    """Dollars over every row, priced by each row's own model.

    Rows with no model stamp are skipped. Any row naming an unpriced model makes the whole figure None rather than an understated subtotal, as does having nothing priceable.
    """
    total, priced = 0.0, False
    for row in rows:
        model = row.get("model")
        if not model:
            continue
        rate = prices(cwd, model)
        if rate is None:
            return None
        priced = True
        for kind, count in _split(row, _adaptor(cwd, row.get("provider", ""))).items():
            total += count * rate[kind] / 1_000_000
    return total if priced else None


@service("models:meter")
def meter(session: Session) -> Meter:
    """Both numbers for this session. Cost reads subagent records too; fullness reads only the main one."""
    read = use("session", "usage")
    try:
        own = read(session.root, session.id)
        everything = read(session.root, session.id, True)
    except FileNotFoundError:
        # No turn taken yet: both unknown.
        return Meter(fullness=None, cost=None)
    return Meter(fullness=_fullness(session, own),
                 cost=_cost(session.root, everything))


# ---------------------------------------------------------------------------
# The context warning and compaction
# ---------------------------------------------------------------------------

COMPACTION = "compaction"
THRESHOLD = 0.8
# `core.new_id`'s stamp; `Session.fork` appends `-<suffix>` to it.
_ROOT_ID = re.compile(r"\d{8}T\d{6}-[0-9a-f]{4}")
# The summary system prompt, read in place from the package and never scaffolded; the project's OVERRIDE replaces it when readable.
PROMPT = resources.files("un") / "defaults" / "compaction.md"
OVERRIDE = UN_DIR / "compaction.md"
# rat-tail: characters per token, set low so the estimate runs high; a tokenizer is the upgrade path.
CHARS_PER_TOKEN = 3
LEAD = "Summary of the conversation so far:\n\n"


def _source(session: Session) -> str:
    """The conversation's name: its agent, else `main/<fork suffix>`, else `main`. A workflow fork keeps its parent's empty `agent`, so its suffix is what tells it apart."""
    if session.agent:
        return session.agent
    root = _ROOT_ID.match(session.id)
    suffix = session.id[root.end():].lstrip("-") if root else ""
    return f"{MAIN}/{suffix}" if suffix else MAIN


def _settings(cwd: Path) -> dict:
    """`[compaction]` re-read per call as enable, threshold, provider and model. Anything absent, unreadable or unusable reads as its default, and `enable` reads false without a usable model, since `cli._config` refuses both at launch."""
    try:
        table = tomllib.loads((Path(cwd) / CONFIG).read_text(encoding="utf-8")).get(COMPACTION)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        table = None
    table = table if isinstance(table, dict) else {}
    threshold = table.get("threshold")
    # `type`, not `isinstance`: bool is an int.
    if type(threshold) not in (int, float) or not 0 < threshold < 1:
        threshold = THRESHOLD
    provider, model = (value if type(value) is str and value else None
                       for value in (table.get("provider"), table.get("model")))
    return {"enable": table.get("enable") is True and model is not None,
            "threshold": threshold, "provider": provider, "model": model}


def _prompt(cwd: Path) -> str:
    """The summary system prompt: `.un/compaction.md` when it reads as UTF-8, else the shipped file."""
    try:
        return (Path(cwd) / OVERRIDE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return PROMPT.read_text(encoding="utf-8")


def _head(messages: list[dict]) -> int:
    """Where the head ends: the first assistant message's index, or the list's length."""
    return next((i for i, m in enumerate(messages) if m.get("role") == "assistant"), len(messages))


def _projection(messages: list[dict], held: dict) -> list[dict]:
    """What is sent: the list itself with no summary held, else head, the summary as one user text block, then everything from the point on."""
    if "summary" not in held:
        return messages
    summary = {"role": "user", "content": [{"type": "text", "text": LEAD + held["summary"]}]}
    return messages[:_head(messages)] + [summary] + messages[held["point"]:]


def _block(block: dict) -> str:
    """One content block as plain text; media and anything unknown as a bracketed placeholder."""
    kind = block.get("type")
    if kind == "text":
        return str(block.get("text", ""))
    if kind == "tool_use":
        return f"[called {block.get('name')}] {json.dumps(block.get('input'), default=str)}"
    if kind == "tool_result":
        inner = block.get("content")
        return "[result] " + (inner if isinstance(inner, str) else "\n".join(_block(b) for b in inner or [] if isinstance(b, dict)))
    return f"[{kind}]"


def _render(messages: list[dict], earlier: str | None) -> str:
    """The earlier summary and the covered messages as role-labelled paragraphs.

    rat-tail: plain text, so no tool schema is needed and any adaptor can summarise, but the summariser sees tool calls as prose; sending raw blocks with the tool schemas is the upgrade.
    """
    parts = [f"Earlier summary:\n{earlier}"] if earlier else []
    for message in messages:
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        parts.append(f"{message.get('role', '?')}:\n" + "\n".join(_block(b) for b in blocks if isinstance(b, dict)))
    return "\n\n".join(parts)


@hook("Turn")
def measure(*, session: Session, reply) -> None:
    """Keep this reply's prompt size and share of the window on the session, and, unless `[compaction] enable` is on, note the operator once per conversation, the first time that share reaches the threshold. Must not raise: `fire` does not isolate listeners."""
    held = session.state.setdefault(STATE_KEY, {})
    size = window(session.root, session.model, held.get("window"))
    if not size:
        return None
    try:
        adaptor = _adaptor(session.root, session.provider)
    except ValueError:
        # A provider table broken mid-session; launch reports config faults, and this reply goes unmeasured.
        return None
    tokens = _prompt_tokens(reply.usage or {}, adaptor)
    held["prompt_tokens"], held["fullness"] = tokens, tokens / size
    settings = _settings(session.root)
    # The size is stored either way; the notice only exists to tell the operator to turn compaction on.
    if settings["enable"] or held.get("warned") or held["fullness"] < settings["threshold"]:
        return None
    held["warned"] = True
    session.note(_source(session), f"context is {tokens / size:.0%} full ({tokens:,.0f} of {size:,} tokens); set [compaction] "
                       f'enable = true and model = "<summary model>" in {CONFIG} to compact it automatically')
    return None


@service("compaction:send")
def send(session: Session, messages: list[dict]) -> list[dict]:
    """The list to send: `messages` itself when compaction is off or a `history:` filter is set, else the held projection, compacting first when the estimated request reaches the threshold of the lower window and some message before the newest exchange is uncovered. A summary call that fails, returns no text or outlives a cancel is reported and stores nothing, leaving that send as it stood; an interrupt is reported and re-raised. Never touches `session.messages`, writes no usage row and fires no `Turn`."""
    settings = _settings(session.root)
    # Off returns the very list, and writes no state: `_sent` and every unfiltered caller rely on identity. A filter's list is already a projection, so its points would not line up with `session.messages`.
    if not settings["enable"] or session.history:
        return messages
    held = session.state.get(STATE_KEY, {})
    if held.get("point", 0) > len(messages):
        # Stale: drop the summary rather than cut what it no longer lines up with.
        held.pop("summary", None)
        held.pop("point", None)
    current = _projection(messages, held)
    turns = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    # Fewer than two exchanges, or nothing uncovered before the newest one: send as it stands.
    if len(turns) < 2 or held.get("point", turns[0]) >= turns[-1]:
        return current
    sizes = [s for s in (window(session.root, session.model, held.get("window")), window(session.root, settings["model"])) if s]
    measured = held.get("prompt_tokens")
    if not sizes or not measured:
        return current
    # The measured request that produced the last reply, plus that reply and everything after it.
    estimate = measured + len(json.dumps(messages[turns[-1]:], default=str)) / CHARS_PER_TOKEN
    if estimate < settings["threshold"] * min(sizes):
        return current
    name = settings["provider"] or session.provider
    covered = _render(messages[held.get("point", turns[0]):turns[-1]], held.get("summary"))
    try:
        # One-off call: no breakpoint, so no cache-write premium.
        reply = use("provider", name)(system=_prompt(session.root), messages=[{"role": "user", "content": [{"type": "text", "text": covered}]}], tools=[], model=settings["model"], effort=session.effort, cache=CacheSpec(system_stable=False, history_append_only=False), emit=None)
    except KeyboardInterrupt:
        # Re-raised so the turn ends through `core._interrupted`.
        session.report(COMPACTION, "the summary call was interrupted, so no summary was stored")
        raise
    except Exception as exc:  # noqa: BLE001
        # Any failure, a missing provider included, costs only this send's compaction; the next crossing tries again.
        session.report(COMPACTION, f"the summary call failed, so this request goes uncompacted: {exc}")
        return current
    # A child's call runs on a pool thread, where Ctrl-C arrives only as `cancelled`.
    if session.cancelled.is_set():
        session.report(COMPACTION, "the session was cancelled during the summary call, so its summary was discarded")
        return current
    summary = reply.text.strip()
    if not summary:
        session.report(COMPACTION, "the summary call returned no text, so no summary was stored")
        return current
    try:
        # Coerced so an odd usage loses its counts, not the `compacted` row.
        usage = reply.usage if isinstance(reply.usage, dict) else {}
        use("session", "event")(session, "compacted", summary=summary, point=turns[-1], usage={**usage, "model": settings["model"], "provider": name, "agent": "compactor"})
    except LookupError:
        # The transcript plugin is disabled, so there is no record to write to; the compaction still holds.
        pass
    except Exception as exc:  # noqa: BLE001
        session.report(COMPACTION, f"the compacted event was not recorded: {exc}")
    held = session.state.setdefault(STATE_KEY, {})
    held["summary"], held["point"] = summary, turns[-1]
    return _projection(messages, held)
