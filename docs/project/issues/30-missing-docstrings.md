# Docstrings for modules and functions that lack them

Status: enhancement, needs-triage
Origin: task 11, [M8][F5]

## Problem

Descriptions are missing in places, making module and function purpose harder to grasp quickly.

## Proposed solution

Add short docstrings where they are missing:

- Modules: 2-5 lines, what the module does and its main responsibilities.
- Functions/classes: 1-2 lines, what it does and what it returns.
- Only where non-obvious; avoid noise.

## Related

- Best done last; earlier passes are rewritten as other work lands.
- The retired `AGENTS.md` required docstrings on every new or modified module, class and function. That rule no longer applies after the switch to devsecops unless it is restated somewhere.

## Comments
