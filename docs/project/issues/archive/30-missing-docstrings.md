# Docstrings for modules and functions that lack them

Status: enhancement, wontfix
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

### Triage (closed): already implemented

The coverage this issue asks for already exists. A structural search of the Python under `engine/` and `client/backend/` found a module docstring on every module (shebang scripts included). It found only five function definitions without one:

- two nested helpers: `flush` in the similarity-cache migration job, and `penalise` inside the up-next handler;
- one helper in a jobs integration test;
- two private one-line helpers in the Client backend: `_store_centroids` (dislikes) and `_key` (blocks).

None of the five is unclear.

The retired `AGENTS.md` rule is the reason the coverage is complete. It also left about 400 placeholder docstrings that only restate the function's name: "Handle X.", "Provide X.", and "Module `<path>`: provide runtime functionality." About 280 are in the Python and about 120 in `client/frontend/src`. Rewriting or removing those would be different work from what this issue asks, and the maintainer chose not to rescope it. Closed as wontfix (already implemented). Nothing is recorded under `docs/project/rejected/`, because the request was not rejected.
