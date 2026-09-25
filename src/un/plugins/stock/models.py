"""Model context windows and per-token prices, and the two reductions over usage rows that surfaces display. Writes nothing.

Data layers, lowest first: the shipped `un/defaults/models.toml` (or the project's `.un/models.toml` copy), a probed window, then `[models."<name>"]` in `.un/config.toml`. Cost is cumulative over every record of the session, subagents included, each row priced by its own model; fullness is the latest main-record row only, since every turn resends the history.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from un import Profile, Session, hook, service, use
from un.core import CONFIG, UN_DIR, providers

SHIPPED = resources.files("un") / "defaults" / "models.toml"
PROJECT = UN_DIR / "models.toml"

KINDS = ("input", "cache_read", "cache_write", "output")

# A size, not a price: zero is invalid here, where a zero rate is real.
CONTEXT = "context"

# Holds the probed window, and guards against probing twice when `/reload` re-fires SessionStart. Not named MODELS: a test scans for constants whose name contains "model".
STATE_KEY = "models"


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
        except (OSError, tomllib.TOMLDecodeError):
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
        except (OSError, tomllib.TOMLDecodeError) as exc:
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

    The probe service is resolved and called under separate guards, so a probe raising LookupError is not mistaken for no probe.
    """
    if STATE_KEY in session.state:
        return None
    probed, probe = None, None
    try:
        profile = _profile(session.root, session.provider)
    except ValueError as exc:
        # Reported, not raised: SessionStart must not stop a session over a config typo.
        session.report("models: table", str(exc))
        profile = None
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
    session.state[STATE_KEY] = {"window": probed}
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
    latest = _split(rows[-1], _adaptor(session.root, session.provider))
    return (latest["input"] + latest["cache_read"] + latest["cache_write"]) / size


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
