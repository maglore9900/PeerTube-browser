# Security hardening batch: issues 01-06 in concurrent worktrees

## Decisions so far

- Scope is issues 01-06, the only `ready-for-agent` ones. Operator: "batch them however it makes sense", taking the recommendations. The 22 `needs-triage` issues stay out; each would need `/devsecops:triage` first.
- One feature file per issue, not one combined build: dev-flow caps a build at four phases, and each brief is already one build's requirements.
- All six plan files are written on main before any worktree branches, so `NN` numbers cannot collide.
- Three waves (see below). 04 goes last because it rewrites every 5xx/502 site, and 03 changes which Engine call those sites wrap.
- Harvest runs on main after each merge, never in a worktree. `test_groups` lives in gitignored `.un/.../config.json`, so a worktree's harvest would edit a copy git never merges.

## File overlap (checked against the source this session)

- 06: `engine/server/db/jobs/sync-whitelist.py:219`, `updater-worker.py:414`, a new `engine/server/data` helper, and a TS cross-check. Touches nothing the other issues touch.
- 05: `engine/server/data/interaction_events.py`, `api/handlers/internal_events.py`, `api/server_config.py`, `api/handlers/similar.py:193-233`.
- 02: `client/backend/server.py:171-202, 280, 350, 527`, `engine/.../similar.py:283-303`, `DEPLOYMENT.md`.
- 01: `client/backend/server.py:684-760` (`_handle_user_action`), `client/backend/lib/users_store.py` (`record_like`), `engine/server/data/random_videos.py:247`.
- 03: `client/backend/server.py:49, 446, 837-843, 970-980`, `client/backend/lib/engine_api_client.py:136`, `engine/.../internal_client_reads.py:20`, `engine/server/data/metadata.py:110`.
- 04: `client/backend/server.py` 649-656, 718, 745, 843, 905, 961, 980, 1002; both `http_utils.py`; `internal_events.py:71`; `similar.py:1020-1024`; `server_config.py:370`; `DEPLOYMENT.md:408`; `tests/active/conftest.py` engine fixture env.

## Waves

- Wave 1, three worktrees: 06, 05, 02. Their hunks don't meet, except that 05 and 02 both edit `similar.py`, 150 lines apart.
- Wave 2, two worktrees off the post-wave-1 main: 01, 03. Both edit `server.py` in different handlers. Both edit `users_store.py`: 01 changes `record_like`'s return, and 03's import calls it and ignores the return.
- Wave 3, main tree or one worktree: 04.

## Worktree environment (checked)

- Gitignored and missing from a fresh worktree: `engine/server/db/{whitelist.db 3.4G, similarity-cache.db 6.8G, *.faiss, random-cache.db}`, `engine/.pixi` 5.7G, `client/frontend/node_modules`, `engine/crawler/node_modules`, `.un/` 28M.
- Paths are repo-root relative (`server_config.py:329-333`) and resolved with `.resolve()` (`api/server.py:323-325`), so a symlink resolves to the main tree's file.
- A test Engine writes the interaction schema and events into `whitelist.db` (`api/server.py:328-331`). A symlinked `whitelist.db` is shared by every worktree and by main, which is already true of every test run today.
- `random-cache.db` is rewritten on every Engine start ([[engine-concurrent-start-locks-random-cache]]), so each worktree gets a private copy, not a symlink.
- No editable installs in `engine/.pixi`, so a symlinked env runs the worktree's own code (`ENGINE_SERVER` is `ROOT/...` in `tests/active/conftest.py:31`).
- `config.json` carries an absolute `project_dir`, and workflows run `validate_tests.py` from it. Each worktree needs its own `.un` copy with `project_dir` rewritten.
- `tests/last_test_validation.json` and `tests/last_test_output.txt` are tracked, so every branch conflicts on them. Resolve by taking main's copy, then re-running `--compare` on the merged tree.
- un's sandbox confines a session to its project dir, so worktrees go under `.worktrees/` inside the repo, excluded via `.git/info/exclude`.
- Capacity: 12 cores, 29G RAM (about 20G available). The Engine rate limit is per Engine, so lanes in different worktrees don't share it.

## Plans written (approved 2026-09-26)

- `docs/project/plans/10-normalise-instance-hosts.md` (issue 06, wave 1)
- `docs/project/plans/11-raw-event-retention.md` (issue 05, wave 1)
- `docs/project/plans/12-trusted-proxy-client-address.md` (issue 02, wave 1)
- `docs/project/plans/13-deterministic-event-ids.md` (issue 01, wave 2)
- `docs/project/plans/14-batch-like-resolution.md` (issue 03, wave 2)
- `docs/project/plans/15-tighten-response-defaults.md` (issue 04, wave 3)

## Open questions

- None blocking. Each plan lists its risks.
- `worktree-setup.sh` is untested: this session cannot run `git worktree`. Run its smoke line, plus one Engine-backed test, in the first worktree before starting a build.
