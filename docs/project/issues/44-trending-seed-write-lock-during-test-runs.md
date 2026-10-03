# The active suite's trending seed holds whitelist.db's write lock while other lanes serve

Status: bug, needs-triage
Origin: build 45-trending-from-source-instances (plan `docs/project/plans/46-45-trending-from-source-instances.md`), Step 8

## Problem

`tests/active/conftest.py` has a session fixture, `trending_seed`, that the `engine` fixture depends on. In every lane that starts an Engine, it runs `DELETE FROM trending_ranks` and then re-inserts every host's top 100 catalogue videos (`TRENDING_SEED_SQL`) into the shared dev `engine/server/db/whitelist.db`. It runs under the Engine start lock, which only serialises Engine starts. Other lanes' Engines are already serving from the same file.

Measured on 2026-10-03 with a throwaway probe (now in `delete_me/probe_step8_seed_timing.py`):
- `PRAGMA journal_mode` is `delete` (rollback journal, not WAL).
- The seed writes 88,648 rows. The delete takes 0.01 s, the insert 4.40 s and the commit 0.23 s, for a total of 4.64 s holding the write lock.
- The Engine's connections (`engine/server/data/db.py`) use sqlite's default 5 s busy timeout.

In rollback mode, readers are blocked once the writer escalates to EXCLUSIVE. That happens at commit, or earlier if the insert spills the page cache. An Engine read or write that waits past 5 s raises `database is locked`, and the recommendations routes turn that into a 500 `Recommendations request failed`. With the seed taking about 4.6 s on its own, a slower disk or a loaded machine can push it past the limit.

This has not been confirmed as a cause. The one 500 seen in this build's `--compare` (`test_similar.py::test_a_mode_outside_the_ordered_set_answers_the_seed_its_pre_build_spelling_did[recommendations]`, on a lane that took 135 s instead of 48 s) had no retained Engine log. It matches the existing intermittent described in memory `upnext-pin-engine-500-intermittent`, which predates this build. The seed adds a new, regular writer to that same file.

The seed is also rewritten on every lane start even though its content is deterministic, so all but the first rewrite in a run are redundant.

## Proposed solution

Pick one, measuring the lock time before and after:
- Skip the rewrite when the table already holds exactly the seed, for example by comparing a row count and a checksum of `TRENDING_SEED_SQL`'s output with the table, or by recording a marker for the catalogue's state.
- Seed once per suite run rather than once per lane, before any Engine starts.
- Give the session Engine a private copy of the ranks, so it does not write the shared file at all.

To confirm the cause, run the suite with `PYTEST_DEBUG_TEMPROOT=<project>/tmp/<dir>` so every lane's `engine.log` survives, then look for `database is locked` tracebacks near a lane's seed time.

## Related

- `tests/active/conftest.py` `trending_seed`, `TRENDING_SEED_SQL`, `ENGINE_START_LOCK`.
- Memory `upnext-pin-engine-500-intermittent`.
- `docs/project/issues/43-updater-trending-launch-failure-skips-similarity.md` (the same build).

## Comments
