"""Who answers when a rule says "ask".

A service rather than an inlined input() call so the question can be answered by a
A chat round-trip, or a policy engine, without the loop knowing.

Writes: nothing.
"""

from __future__ import annotations

import sys

from un import Session, service


@service("approval:cli")
def ask(session: Session, question: str, *, always: bool = False) -> str:
    """Ask on the terminal. Anything but an explicit yes is a no, and silence is a no.

    `"yes"`, `"no"` or `"always"`.
    `always` results in an allow rule being written.

    Reads from `session.stream`, a declared field, falling back to stdin when it is
    None. Per-session rather than global: which adapter answers is a property of the
    run, so a workflow can hand one session an auto-approver without changing what
    any other session does.

    Fails closed when nobody is there, and the two fields are not the same question.
    `stream` is an interface that ATTACHED itself - a REPL - and answers however
    it likes, headless or not. `headless` describes the terminal the process was
    launched from. Only with neither is there no one to ask.

    Then stdin is not read AT ALL, which is the point rather than a detail: on a piped
    run the next line is the user's PROMPT, so consuming it would refuse the call and
    swallow the instruction, leaving the model to answer a question nobody asked.
    `approval:yes` stays the explicit opt-in for runs that have accepted the risk.
    """
    if session.stream is None and session.headless:
        # On stderr, beside the question it is refusing: a run blocked in CI has to be
        # diagnosable from its output alone.
        print(f"{question}\n  refused: no one is there to answer", file=sys.stderr)
        return "no"
    # On stderr, beside the refusal above: a question is not an answer, and
    # `un chat '...' > out.txt` must not collect it. Only the question moves - the read
    # below still takes `session.stream`, so a piped run answers from where it always did.
    #
    # The suffix moved INTO the question, because the caller is the one that knows
    # whether `a` is on offer and this adapter would otherwise have to guess.
    print(f"{question} ", end="", flush=True, file=sys.stderr)
    answer = (session.stream or sys.stdin).readline().strip().lower()
    if always and answer in {"a", "always"}:
        return "always"
    return "yes" if answer in {"y", "yes"} else "no"


@service("approval:yes")
def always(session: Session, question: str, *, always: bool = False) -> str:
    """Approve everything. For non-interactive runs that have accepted the risk.

    Selected with `--approval yes`. The flag is in --help, where a model would find
    it, so `permissions` refuses a command that spawns another `un` and picks its own
    approver - the rule `bash(un:--a*)`: the choice stays with whoever runs `un`, not
    with what it runs.

    Never `"always"`, whatever the flag says. A headless run has no operator, and a rule
    in `.un/permissions.toml` outlives the run that wrote it - so this adapter approves
    the call in front of it and never widens what the NEXT one may do. Approving
    everything is a risk somebody accepted for one run; remembering it is not.
    """
    return "yes"
