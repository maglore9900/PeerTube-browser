# Issue tracker: Local Markdown

Work is tracked as markdown in this repo, split by kind. **An issue is something wrong or something asked for; a feature is something planned and built.** They live in different directories because they have different lifecycles: an issue moves through the triage roles and ends, a feature accumulates a plan and a build record.

| Kind | Lives at | Owned by |
|---|---|---|
| **Issue** — a bug, a defect, a small request | `docs/project/issues/<NN>-<slug>.md` | the `triage` skill |
| **Feature** — a planned, phased build | `docs/project/plans/<NN>-<slug>.md` | the devsecops build workflow |

Neither lives in `.scratch/`. That directory is working space for a session's own artifacts, not tracked work.

Work that is neither an issue nor a feature yet — a one-line roadmap intention with no plan — is listed in `docs/project/roadmap.md` and becomes an issue or a feature file only when someone picks it up.

## Issues

- One file per issue at `docs/project/issues/<NN>-<slug>.md`, numbered from `01`, never a combined tickets file.
- Triage state is a `Status:` line near the top, carrying one category role and one state role. See `triage-labels.md` for the strings.
- Comments and conversation history append to the bottom under a `## Comments` heading.
- An agent brief appends under `## Agent Brief` when the issue reaches `ready-for-agent`.
- A closed issue keeps its file and its number. `Status: wontfix` is how it closes; nothing is moved or deleted.

## Features

- One file per feature at `docs/project/plans/<NN>-<slug>.md`, numbered in the sequence that directory already uses, `archive/` included.
- The plan file IS the working file the build workflow writes: requirements, approved plan, impact inventory, per-phase checkpoint outcomes. `/devsecops:plan` may create it with Requirements and High-level plan filled; a build adopts that same file.
- A delivered or abandoned feature moves to `docs/project/plans/archive/`, which is what keeps the top of `plans/` to work that is live.

## When a skill says "publish to the issue tracker"

Create the file under `docs/project/issues/`, taking the next free number. Where the work is a planned build rather than a defect, it is a feature: create it under `docs/project/plans/` instead, and say which you chose.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The caller normally passes the path or the number directly; a bare number means `docs/project/issues/`.

## Wayfinding operations

Used by `/devsecops:plan`, for exploration that has not become an issue or a feature yet. These stay in `.scratch/`, since a map is a session artifact rather than tracked work. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`questions`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
