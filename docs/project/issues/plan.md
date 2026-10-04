# Build order: issues 53-58

The order for the architecture-review issues briefed on 2026-10-04, and which of them can run at the same time in separate worktrees. Issue 57 is folded into 54. Issues 42 and 43 are still `needs-triage` and are not in this plan.

## Why the order matters

None of these issues needs another's code in order to work. The order comes from which files each build edits, because two builds rewriting the same function in parallel worktrees give a merge conflict that someone has to resolve by hand.

| Issue | Main code it edits | Translate worker script | Translate route | Other shared files |
|---|---|---|---|---|
| 53 fetch adapter | new adapter module, `video.py`, `fetch-trending.py` | heavy: imports, `media_host`, `AudioPipe._feed`, `generate` | heavy: fetch code moves out | Engine README, `TRANSLATE_WORKER.md`, worker and route tests |
| 54 job handle | `data/subtitles.py`, `server.py` | heavy: `generate`, `run_job`, `translate_audio`, `command_run`, enqueue | heavy: resolve, the three store-lock blocks | Engine README, `TRANSLATE_WORKER.md`, worker and route tests |
| 55 state contract | new fixture, Client and frontend tests | light: `HEARTBEAT_SECONDS` | light: `HEARTBEAT_FRESH_MS` | Engine README, route tests |
| 56 worker timing | — | heavy: `serve`, `heartbeat_loop`, `AudioPipe`, `run` arguments | none | `TRANSLATE_WORKER.md`, worker tests |
| 58 router | new router module, `handlers/similar.py` | none | none (imported only) | Engine README route list, `test_similar.py` |

53, 54 and 56 all rewrite the worker script, so they go one after another. 58 touches none of the translate code, so it can run alongside anything.

## Order


### Wave 3: 55 and 56 in parallel, once 54 is merged

- **55, the translate state contract.** Most of it is new tests in the Client, the frontend and a fixture. Its one Engine change, a shared heartbeat definition, is easiest to place after 54, because 54's store module is a natural home that both the route and the worker already import.
- **56, worker timing as parameters.** It goes last on the worker script, after 53 and 54 have finished changing `AudioPipe`, `run_job` and `command_run`.
- The two overlap only in the worker's constants block: 55 removes the `HEARTBEAT_SECONDS` literal, and 56 leaves it alone. Expect at most a one-line conflict. Merge whichever finishes first, and rebase the other.

### At a glance

```
wave 1:  53 ───────────┐        58 ──────────────── (merge any time)
wave 2:                └─ 54 ──────┐
wave 3:                            ├─ 55
                                   └─ 56
```

With one worktree at a time, run them in this order: 53, 54, 56, 55, then 58 wherever it fits.

## Running builds in parallel worktrees

These come from earlier builds in this repo:

- **Test map.** Each worktree needs its own `tests/config.json`, with `project_dir` set to that worktree. Test-group entries a build adds there must be checked when merging.
- **Harvest.** The dev-flow harvest step (Step 10) refuses to run in a linked worktree. Merge first, then resume the build's record from the main checkout.
- **Symlinks.** Worktrees symlink `engine/.pixi` and `node_modules`. Check that `git add -A` has not staged those symlinks before committing, because merging them once deleted main's real `node_modules`.
- **Engine-backed tests.** Run each Engine-backed test file in its own `validate_tests.py` call. Several files in one call share one Engine and trip its 60/min rate limit. Two worktrees starting Engines at the same moment can also hit `database is locked` on the random cache; the test fixture retries this.
- **Browser testing.** A Client started from a worktree has its own empty `users.db`, so your browser's profile key is rejected there. Test Translate in the browser from `main` after merging.
- **Shared docs.** The Engine server README is edited by 53, 54, 55 and 58, and `TRANSLATE_WORKER.md` by 53, 54 and 56. Each build edits a different section, so a conflict there should be a simple doc merge, not a code merge.
