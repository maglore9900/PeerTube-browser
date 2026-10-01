"""The one cut every child-output tool applies before its text reaches the model: `Bash`, `GitRo`, `AstGrep`, `Workflow` and drop-in script tools.

Registers nothing and is no plugin, so any plugin can import it, and disabling `file_system` or `shell_access` never takes an importer down with it (`core._settle` matches only plugin modules). Applied at the tool layer only: `run_child`, `Ran` and `json_result` keep the whole output, because workflows gate on it.
"""

from __future__ import annotations

# rat-tail: a bound on what one call may spend of the context window, the same kind as `fs.READ_LIMIT`/`GREP_LIMIT`, kept under `transcript.RESULT_CAP` (32768) so the record holds everything the model saw. A config key or a per-call parameter is the upgrade path for a caller that genuinely needs more.
OUTPUT_LIMIT = 30000
HEAD = OUTPUT_LIMIT // 2
TAIL = OUTPUT_LIMIT - HEAD

# Spelled from the constants, so the cap the model is told is the cap enforced.
CAP_SENTENCE = (f"Output longer than {OUTPUT_LIMIT} characters comes back as its first {HEAD} and last {TAIL} "
                "with a `[truncated: ...]` line between them counting what was omitted; narrow the call to see the rest.")


def capped(text: str) -> str:
    """`text` unchanged at or under `OUTPUT_LIMIT`, otherwise its head and tail around one marker line. The marker is spelled only here."""
    if len(text) <= OUTPUT_LIMIT:
        return text
    marker = (f"[truncated: {HEAD} + {TAIL} of {len(text)} characters shown; "
              f"{len(text) - OUTPUT_LIMIT} omitted from the middle. Narrow the command to see them.]")
    return f"{text[:HEAD]}\n{marker}\n{text[len(text) - TAIL:]}"
