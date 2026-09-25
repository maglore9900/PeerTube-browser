"""The AskUser tool: put one decision to the operator mid-turn and wait. Writes nothing.

The adapter is `ask:<session.approval>`; an approver with no `ask:` variant (such as `approval:yes`) makes the tool refuse rather than auto-decide. Returning text means the operator answered; every other outcome raises.
"""

from __future__ import annotations

import sys
import threading
from typing import NoReturn

from un import Session, fire, service, tool, use

OTHER = "Other (answer in your own words)"

# One question on the terminal at a time; calls in a batch run on pool threads.
_ASKING = threading.Lock()

_OPTION = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "value": {"type": "string"},
        "description": {"type": "string"},
        "preview": {"type": "string"},
    },
    "required": ["label"],
}


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def _prompt(text: str) -> None:
    print(text, end="", flush=True, file=sys.stderr)


def _refuse(message: str) -> NoReturn:
    raise ValueError(f"AskUser: {message}")


def _normalise(options: list[dict]) -> tuple[dict, ...]:
    """Trim fields, drop blank labels, and default `value` to the label."""
    kept = []
    for option in options:
        label = str(option.get("label", "")).strip()
        if not label:
            continue
        kept.append({
            "label": label,
            "value": str(option.get("value") or label).strip(),
            "description": str(option.get("description", "")).strip(),
            "preview": str(option.get("preview", "")).rstrip(),
        })
    return tuple(kept)


def _picked(typed: str, options: tuple[dict, ...], multi: bool) -> list[str] | None:
    """The values `typed` names, or None so the caller re-asks. Empty entries are ignored; more than one without `multi` is invalid."""
    parts = [part.strip() for part in typed.split(",") if part.strip()]
    if not parts or (len(parts) > 1 and not multi):
        return None
    chosen: list[str] = []
    for part in parts:
        if not part.isdigit() or not 1 <= int(part) <= len(options):
            return None
        value = options[int(part) - 1]["value"]
        if value not in chosen:
            chosen.append(value)
    return chosen


@tool(
    "AskUser",
    "Put one decision to the operator and wait for their answer. Use it when a choice "
    "would materially change the work and you would otherwise be guessing, or when you "
    "need a confirmation before proceeding. Ask exactly one question per call. Each "
    "entry in `options` needs a `label`, and may carry a one-line `description`, a "
    "`value` returned in place of the label, and a `preview` of verbatim example "
    "content - a code snippet, a layout mockup, a config sample - shown beside the "
    "option so the operator can see what they are choosing rather than infer it. Set "
    "`multi_select` to accept more than one. The operator can always answer in their "
    "own words instead of picking, so options are your best guesses, not a limit.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "details": {"type": "string"},
            "options": {"type": "array", "items": _OPTION},
            "multi_select": {"type": "boolean"},
        },
        "required": ["question", "options"],
    },
)
def ask_user(*, session: Session, question: str, options: list[dict] | None = None,
             details: str = "", multi_select: bool = False) -> str:
    """Normalise, resolve the adapter, ask, and report the answer.

    `options` is required by the schema but defaulted here, so a model that omits it gets a useful refusal instead of a TypeError.
    """
    question = question.strip()
    if not question:
        _refuse("question is empty; ask one question per call")
    kept = _normalise(options or [])
    if not kept:
        _refuse("options is missing or empty; supply the choices the operator is picking "
                "between, each an object with a `label` - for a plain confirmation that is "
                '[{"label": "Approve"}, {"label": "Stop"}]. The operator can always answer '
                "in their own words, so the list is your best guesses and not a limit")

    try:
        adapter = use("ask", session.approval)
    except LookupError:
        _refuse(f"this run has no way to ask ({session.approval!r} answers approvals "
                "only); proceed without asking and state the assumption you made")

    # After every refusal, so a call that reaches nobody reports no wait.
    with _ASKING:
        fire("OperatorWaitStart", session=session, question=question)
        try:
            answers = adapter(session, question, details.strip(), kept, multi=multi_select)
        finally:
            fire("OperatorWaitEnd", session=session)
    if answers is None:
        _refuse("the operator dismissed the question without answering")
    return "the operator answered:\n" + "\n".join(f"- {answer}" for answer in answers)


@service("ask:cli")
def ask(session: Session, question: str, details: str, options: tuple[dict, ...],
        *, multi: bool = False) -> list[str] | None:
    """Ask on the terminal: a numbered list with previews stacked under each option, and one typed line.

    Written to stderr so redirected stdout collects only the answer. A headless run with no stream refuses rather than consume stdin.
    """
    if session.stream is None and session.headless:
        _refuse("no one is there to answer; proceed without asking and state the "
                "assumption you made")

    _say(question)
    if details:
        _say(details)
    for number, option in enumerate(options, 1):
        _say(f"  {number}) {option['label']}")
        if option["description"]:
            _say(f"     {option['description']}")
        for line in option["preview"].splitlines():
            _say(f"     | {line}")
    _say(f"  0) {OTHER}")

    span = f"1-{len(options)}" if len(options) > 1 else "1"
    hint = f"Choose {span} separated by commas, or 0" if multi else f"Choose {span}, or 0"
    stream = session.stream or sys.stdin
    while True:
        # An empty line dismisses; EOF reads as empty, so the loop cannot spin.
        _prompt(f"{hint} (empty to dismiss): ")
        typed = stream.readline().strip()
        if not typed:
            return None
        if typed == "0":
            _prompt("Your answer: ")
            written = stream.readline().strip()
            return [written] if written else None
        picked = _picked(typed, options, multi)
        if picked is not None:
            return picked
        _say(f"  not a choice: {typed!r}")
