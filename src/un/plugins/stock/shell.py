"""The bash tool, and the shell seam it runs through.

Separated for the same reason as the filesystem: a sandboxed or remote executor
registers another `shell:` service and the tool is untouched. Workflows run their
commands through this seam too, so a sandbox covers them as well.

Writes: this module executes arbitrary commands, which may write anything. That is the
point of it, and why `rules` gates the tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from un import Session, service, tool, use
from un.core import DEFAULT_TIMEOUT, run_child


@dataclass(frozen=True)
class Ran:
    """What a command did.

    The exit code is a field rather than text baked into the output, because workflows
    gate on it. Recovering an integer by parsing a formatted string back apart is how a
    gate ends up passing because the character "0" appeared somewhere in stdout.
    """

    code: int
    output: str


@service("shell:local")
class LocalShell:
    """Runs commands on this machine, in the session's directory."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, command: str, timeout: int) -> Ran:
        """Run one command in the session's directory and return what it did.

        A dataclass over `core.run_child`'s tuple, because a workflow gating on the exit code
        reads a field rather than an index. The spawn itself is shared with every other child
        un starts - the bound, the process group and the reclamation are `run_child`'s.
        """
        return Ran(*run_child(command, cwd=self.session.cwd, timeout=timeout))


@tool(
    "Bash",
    "Run a shell command in the session directory and return its output.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "seconds; default 120"},
        },
        "required": ["command"],
    },
)
def bash(*, session: Session, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Format what the shell did, for the model.

    A non-zero status is stated rather than implied: a failing command whose output was
    empty would otherwise read as having succeeded quietly.
    """
    ran = use("shell", session.shell)(session).run(command, timeout)
    if ran.code == 0:
        return ran.output or "[no output]"
    return f"{ran.output}\n[exit status {ran.code}]".strip()
