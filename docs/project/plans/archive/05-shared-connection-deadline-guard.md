# Shared-connection deadline without a per-request progress-handler install

Issue: `docs/project/issues/archive/31-shared-connection-deadline-deadlock-guard.md`

## Requirements

### What was asked

Build the guard the 2026-09-26 deadlock fix left open: "nothing yet stops a future long query from being added on the shared connection without a lock". Operator's choice of guarantee, verbatim from the option chosen: "Remove the cause" — one progress handler per connection installed at startup, reading a per-thread deadline, so requests never call `set_progress_handler`.

### Purpose

A request's time budget on the Engine's shared SQLite connection must never be able to hang the whole process, whatever a later caller does. Today the guarantee rests on a convention — every statement on `server.db` runs under `db_lock` — that nothing enforces.

### Current state (read 2026-09-26)

- `engine/server/data/db.py` `statement_deadline(conn, seconds, lock=None)` calls `conn.set_progress_handler` on entry and exit, under `lock` when one is passed.
- `engine/server/api/handlers/similar.py` `_statement_deadline` wraps every `do_GET`/`do_POST` in it with `lock=server.db_lock`.
- `engine/server/data/search.py` `search_deadline` calls it with no lock on the dedicated `search_db`, relying on its caller holding `search_db_lock`. `search_connection` falls back to `server.db`/`db_lock` when `search_db` is absent.
- Every `server.db` access found by search runs under `db_lock` today. Two fall back to no lock when the server object lacks one: `data/similarity_candidates.py:167`, `api/recommendations/candidates/similar_from_likes.py:49`.
- Mechanism: `set_progress_handler` holds the GIL while waiting for the connection mutex; a running statement holds the mutex and needs the GIL to call its Python handler. Both wait forever.

### Acceptance criteria

1. A long statement running on a connection in one thread, while another thread enters and leaves a request deadline on the same connection, does not deadlock: both threads return.
2. A statement that runs past its request's budget raises `sqlite3.OperationalError` recognised by `is_interrupted_error`, and the Engine answers 503 as today.
3. A deadline set by one thread never interrupts a statement run by another thread, including job code sharing the connection with no deadline.

### In scope

`engine/server/data/db.py`; the deadline call sites in `engine/server/api/handlers/similar.py` and `engine/server/data/search.py`; wherever the Engine opens its connections.

### Out of scope

- Moving further routes onto dedicated connections.
- Removing `db_lock` or changing which code holds it; it still serialises statements on the shared connection.
- The `lock is None` fallbacks in `similarity_candidates.py` and `similar_from_likes.py`, unless this build makes them wrong.

### Consistency constraints

New code matches the style of `db.py` (reST-style `:param:` docstrings, module-level constants, `from __future__ import annotations`). Backwards compatibility of `statement_deadline`'s signature is not required.

### Conflicts

None found.

### Test trees for this build

- `active`: `tests/active`
- `working`: `tests/tmp`

The checkpoint runs under the root pixi env (`.pixi/envs/default`, pytest 9.1.1), which lacks the Engine's `faiss`/`torch`. It imports `engine/server/data/db.py` only, which needs the standard library alone.

### Baseline suite state

`validate_tests.py` run 2026-09-26 at Step 0, fresh: `tests/active` empty, no tests collected, exit 0. Green, vacuously.

### Skill note

`workflows/dev_flow.md` Step 1 names `templates/capture_template.md`, which does not exist; this file follows `templates/plan_template.md`, which its success criteria name.

## High-level plan

Approved by the operator 2026-09-26.

### Approach

`engine/server/data/db.py` gains `install_deadline_handler(conn)`, which sets one progress handler that returns 1 only when the calling thread's deadline has passed. The deadline lives in a module-level `threading.local`; SQLite invokes the handler on the thread stepping the statement, so a deadline scopes to that thread's own statements (AC3). `connect_db` and `connect_readonly_db` install it when they open a connection — these produce `server.db` and `search_db`, the only connections that carry request deadlines.

`statement_deadline(seconds)` sets the thread-local deadline and restores the previous value on exit, so nesting works. It never touches a connection, so no request path calls `set_progress_handler` and the deadlock mechanism is gone (AC1). The `lock` parameter is removed. `similar.py` `_statement_deadline` and `search.py` `search_deadline` move to the new signature; an overrun still raises `interrupted` and the handlers still answer 503 (AC2).

### Alternatives

- **Enforce `db_lock` on the shared connection** — rejected by the operator: it makes a missed lock fail loudly but leaves the deadlock mechanism in place.
- **`conn.interrupt()` from a timer thread** — interrupts whatever statement is running on the connection, which may belong to another request; violates AC3.

### Risks

- **R1** — A connection not opened through the two helpers has no handler, so a deadline on it silently does nothing. `engine/server/db/jobs/tests/test-security-bundle.py:100` uses a bare `sqlite3.connect` and must install the handler.
- **R2** — The handler is now always installed. Any other GIL-holding sqlite call made from a second thread while a statement runs — a later `set_progress_handler`, `create_function`, `set_authorizer` on a live connection — can still deadlock. No request path does this today; this build removes the one that did and does not guard against new ones.
- **R3** — Every statement without a deadline pays one Python callback per 10,000 VM instructions, including `ensure-video-indexes.py`, which also uses `connect_db`. Expected negligible; not measured.

### Tradeoffs accepted

A small permanent callback cost on every statement on the two connections, and a silent no-op deadline on any connection not opened through the helpers. `db_lock` is still required for statement and transaction correctness; forgetting it no longer hangs the process.

## Impacts

### `statement_deadline`
- **path:** `engine/server/data/db.py` (lines 17-65)
- **Changes:** signature `(conn, seconds, lock=None)` → `(seconds)`. Sets a thread-local deadline, restores the previous one on exit; no `set_progress_handler` call.
- **Depends on it:** `similar.py` `_statement_deadline`, `search.py` `search_deadline`, `test-security-bundle.py:100`.
- **Regression risk:** high. Every Engine request passes through it. A deadline not restored on an exception would leak into the next statement on that thread; nesting (request deadline wrapping search's) must restore the outer value.

### `install_deadline_handler` (NEW)
- **path:** `engine/server/data/db.py`
- **Changes:** new function installing one progress handler that compares the calling thread's deadline to `time.monotonic()`.
- **Depends on it:** `connect_db`, `connect_readonly_db`, `test-security-bundle.py`.
- **Regression risk:** medium. The handler runs on every statement on those connections, including when no deadline is set; it must return 0 then.

### `connect_db`
- **path:** `engine/server/data/db.py` (lines 77-81)
- **Changes:** installs the handler on the connection it opens.
- **Depends on it:** `engine/server/api/server.py:324` (`server.db`), `engine/server/db/jobs/ensure-video-indexes.py:34`.
- **Regression risk:** low. Job code gets a handler that never fires (R3).

### `connect_readonly_db`
- **path:** `engine/server/data/db.py` (lines 84-96)
- **Changes:** installs the handler; its docstring's deadlock rationale is rewritten, since the per-request install it describes is gone.
- **Depends on it:** `engine/server/api/server.py:325` (`search_db`).
- **Regression risk:** low.

### `_statement_deadline`
- **path:** `engine/server/api/handlers/similar.py` (lines 288-303)
- **Changes:** calls `statement_deadline(seconds)`; drops `self.server.db` and `lock=`; docstring rewritten.
- **Depends on it:** `do_GET`, `do_POST` (lines 315-323, 380-388), i.e. every Engine route.
- **Regression risk:** high: the entry point for every request.

### `search_deadline` and `search_connection`
- **path:** `engine/server/data/search.py` (lines 32-53, call sites 193-195 and 274-284)
- **Changes:** `search_deadline` calls the new signature. The deadlock rationale in `search_connection`'s docstring and the comment at 275-277 is rewritten: a dedicated connection still keeps long FTS statements from holding `db_lock`, but sharing no longer deadlocks.
- **Depends on it:** `search_videos`, the vector-half metadata fetch.
- **Regression risk:** low. Nested inside the request deadline on the same thread; restore semantics keep the outer one.

### `SimilarityServer.__init__` comment
- **path:** `engine/server/api/server.py` (lines 239-241)
- **Changes:** comment says sharing `db` deadlocks against the per-request install; rewritten to the remaining reason (long statements off `db_lock`).
- **Depends on it:** nothing.
- **Regression risk:** none.

### Task 75 harness
- **path:** `engine/server/db/jobs/tests/test-security-bundle.py` (lines 23, 95-118)
- **Changes:** calls `install_deadline_handler(conn)` on its bare `:memory:` connection and `statement_deadline(0.3)`. The "handler cleared after the block" check keeps its meaning: after the block, a statement is not interrupted.
- **Depends on it:** nothing; run by hand.
- **Regression risk:** without the change, the deadline silently does nothing and "long statement interrupted" fails.

### Unlocked fallbacks
- **path:** `engine/server/data/similarity_candidates.py` (line 167), `engine/server/api/recommendations/candidates/similar_from_likes.py` (line 49)
- **Changes:** none. After this build they can no longer hang the process; they remain unsynchronised statements on a shared connection when the server object lacks `db_lock`, which production never does.
- **Regression risk:** none.

### Highest risk

1. `similar.py` `_statement_deadline` — every request enters through it; a wrong signature is a 500 on every route.
2. `db.py` `statement_deadline` — a deadline not restored on exit, or restored to the wrong value when nested, interrupts statements that should run.
3. `db.py` `install_deadline_handler` — a handler that fires without a deadline, or reads another thread's deadline, breaks AC3 for the whole service.

### Reassessment

**Pass 1.** Opened every path above.

1. *Will it still work as intended?* Yes. `server.db` and `search_db` are the only connections a request deadline covers, and both come from the two helpers (`server.py:324-325`). No request path makes another GIL-holding sqlite call (`create_function`, `set_authorizer`, `set_trace_callback`, `backup`: no matches under `engine/server`).
2. *Ramifications?* With the handler on `search_db` too, the outer request deadline now also covers search statements, so `search_deadline` becomes a nested deadline with the same budget. Harmless under restore semantics; kept rather than removed to stay in scope.
3. *What else must happen?* The task 75 harness must install the handler. Nothing else.
4. *How is functionality altered?* The deadline follows the thread, not the connection: a statement a request thread runs on any handler-equipped connection is bounded by that request's budget. Previously `similarity_db` and `random_cache_db` were never bounded; they still are not, as they get no handler.

Every entry confirmed against its file. New impacts this pass: none. Converged.

### Documentation to update

None. No document outside the code describes the deadline mechanism: the security audit reports under `docs/project/security-audit/` are dated records, not current-state docs. The docstrings and comments above are updated inside the phase. Issue 31 closes when the build does.

## Implementation plan

### Draft (Step 5)

Ladder: rung 3 — `threading.local` and `sqlite3.Connection.set_progress_handler` are stdlib; nothing new is needed.

`engine/server/data/db.py`:

```python
_deadline = threading.local()  # .at: monotonic seconds, or absent/None for no deadline


def _deadline_passed() -> int:
    """Progress handler: abort only the calling thread's statement, only past its deadline."""
    at = getattr(_deadline, "at", None)
    return 1 if at is not None and time.monotonic() > at else 0


def install_deadline_handler(conn: sqlite3.Connection) -> None:
    """Install the one progress handler `statement_deadline` relies on. Call once, at open."""
    conn.set_progress_handler(_deadline_passed, PROGRESS_HANDLER_INSTRUCTIONS)


@contextmanager
def statement_deadline(seconds: float) -> Iterator[None]:
    """Bound this thread's statements, on any connection carrying the handler, by `seconds`."""
    if seconds <= 0:
        yield
        return
    previous = getattr(_deadline, "at", None)
    _deadline.at = time.monotonic() + seconds
    try:
        yield
    finally:
        _deadline.at = previous
```

`connect_db` and `connect_readonly_db` call `install_deadline_handler(conn)` before returning.

Invariants: the handler returns 0 whenever the stepping thread has no deadline (AC3); `statement_deadline` touches no connection (AC1); on exit the thread's previous deadline is restored, so a nested block ends without clearing the outer one.

Call sites: `similar.py` `_statement_deadline` returns `statement_deadline(getattr(self.server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS))`; `search.py` `search_deadline` returns `statement_deadline(seconds)` and drops its `conn` parameter; its two callers drop the argument. `test-security-bundle.py` imports `install_deadline_handler`, calls it on its `:memory:` connection, and calls `statement_deadline(0.3)`.

Checked against the plan and requirements: AC1 by `statement_deadline` never calling into sqlite; AC2 by the handler returning 1 past the deadline, raising the same `interrupted` error `is_interrupted_error` already recognises and `do_GET`/`do_POST` already map to 503; AC3 by the thread-local lookup. Converged on pass 1.

### Phases

#### Phase 1 — Per-thread statement deadline

- **Kind:** code
- **Files:** `engine/server/data/db.py` (EDITED), `engine/server/api/handlers/similar.py` (EDITED), `engine/server/data/search.py` (EDITED), `engine/server/api/server.py` (EDITED, comment only), `engine/server/db/jobs/tests/test-security-bundle.py` (EDITED), `tests/tmp/test_statement_deadline.py` (NEW, checkpoint)
- **Intent (post-phase state):** On a connection opened by `connect_db`, a thread can enter and leave `statement_deadline` while another thread's statement is running on that connection without waiting for it, and a deadline that passes interrupts only statements run by the thread that set it.
- **Clauses:**
  - `C1` — Entering and leaving `statement_deadline` in one thread while another thread's statement is running on the same `connect_db` connection returns without waiting for that statement.
  - `C2` — A passed `statement_deadline` interrupts only statements run by the thread that set it.
- **Checkpoint and seam:** the public functions of `engine/server/data/db.py` — `connect_db` and `statement_deadline` — on a real SQLite file under `tmp_path`, statements long enough to run past a deadline generated by a recursive CTE. No existing pytest harness enters this seam; the precedent is `engine/server/db/jobs/tests/test-security-bundle.py`'s task 75 section, which drives `statement_deadline` with the same kind of CTE.
  - `C1` runs in a child Python process (rung 2): the failure it excludes is a process-wide deadlock that freezes the interpreter running the assertion, so it is observed from outside, by the child exiting within a timeout and reporting that the deadline block returned while the other thread's statement was still running.
  - `C2` runs in-process (rung 1): thread A enters `statement_deadline` and holds it open without executing; thread B, with no deadline, runs a statement outlasting A's budget and must return its exact row count; then A runs a long statement inside its block and must get the interrupted error — the positive control that makes B's completion mean "not interrupted" rather than "no deadline mechanism".
  - The call-site changes in `similar.py` and `search.py` are signature adaptation and carry no clause: those modules import `faiss` and `torch`, which the root pixi env the checkpoint runs under does not have. They are verified by the Engine starting and answering under load (coordination below).

- **Scaffolding (Step 7.1, before the checkpoint):** `db.py` `statement_deadline(seconds)` and `install_deadline_handler(conn)` landed as signatures raising `NotImplementedError`, per `rules/gates.md <red_for_the_right_reason>`; `connect_db` not yet wired. `similar.py` and `search.py` still call the old signature until 7.5; the running services are not restarted until then.
- **Probe (observed, `tests/tmp/probe_old_deadline.py`, against the pre-build `db.py`):** the bounded statement (3-way join, n=600) runs 1.478s and returns 216,000,000. Thread B running it with no deadline while thread A holds `statement_deadline(conn, 0.3)` open: `OperationalError: interrupted`. A child entering `statement_deadline(conn, 5.0)` while another thread's statement runs on the connection: did not exit within 15s (hung).

**Self-check (dispatch 1)** — `tests/tmp/test_statement_deadline.py`

- `C1 — test_statement_deadline.py:92-93, other thread still running after the deadline block was entered and left, and the block took under 0.5s — expected: True, < 0.5s — under a per-connection handler install (pre-build db.py, with or without db_lock, since the other thread holds no lock): the child hangs; observed in the probe as no exit within 15s, reported here by pytest.fail on TimeoutExpired.`
- `C2 — test_statement_deadline.py:134, the setting thread's own statement past its deadline — expected: "interrupted" — under a no-op deadline (bare yield): "completed"; under the scaffolding: "raised NotImplementedError" (observed).`
- `C2 — test_statement_deadline.py:138, the other thread's statement with no deadline, finishing after the setting thread's deadline passed — expected: 216000000 — under a per-connection handler: "interrupted" (observed in the probe).`

Supporting assertions (no row): the child's return code; `other_count == 216000000` and `own_interrupted is True` in C1, which fail a no-op `statement_deadline`; `other_finished_at > deadline_at` in C2, which makes B's completion evidence rather than a race.

1. **Whole claim** — yes. C1's "entering and leaving" is one timed block around both; "returns without waiting" is the elapsed bound plus the other thread still alive afterwards. C2's "only" is both halves: own interrupted, other completed.
2. **Absence only** — no. C2's negative half is armed by line 134 and by line 137's timing; C1's liveness is armed by the own-interrupt control, so a stub that does nothing fails.
3. **Echoed literal** — no. 216,000,000 comes from SQLite's count, not the test; deleting `_deadline_passed`'s body (the handler) turns line 134 red.
4. **One value** — the deadline is read at two threads, one with a deadline and one without, which is the delta the claim is about.
5. **The double** — none. Real SQLite file, real `connect_db`, real threads; the child process is the harness, not a stand-in.
6. **It collects** — `--collect-only`: 2 node ids, matching the two tests.
7. **Observed** — durations and the 216,000,000 count from the probe run; the pre-build behaviour of both scenarios from the probe.
8. **Red** — yes: exit 1, 2 failed.
9. **Right reason** — yes. Test 1 fails at line 89 (return code 1) with the child's stderr showing `NotImplementedError` raised from `db.py:25 statement_deadline`. Test 2 fails at line 134: `'raised NotImplementedError' == 'interrupted'`. The first dispatch-1 run failed test 2 on `KeyError: 'deadline_at'` (harness); rewritten so the thread records what it raised and the C2 assertion comes first.
10. **Observed expected output** — the rows' wrong-implementation values are the probe's observed outputs; the expected values are the probe's measured count and the thresholds above its measured timings.

**Checkpoint audit (dispatch 1)**

- `AUDIT: devsecops-test-shape-auditor — PASS. Predicted failure: test 1 at line 89 (return code 1, child traceback showing NotImplementedError from statement_deadline); test 2 at line 134 with own == "raised NotImplementedError", after line 132 passes because the other thread times out its 5s wait and finishes.`
- `AUDIT: devsecops-test-claim-auditor — PASS. CLAUSE MAP: 10 rows (C1a, C1b, C2a, C2b, D1, D2, N1-N4), all CARRIED.`
- Ledger: no UNCARRIED row, no Critical.
- Recommendations, recorded, not taken:
  1. *Success path and deadline cleared on exit* — the cleared-on-exit behaviour is asserted by `test-security-bundle.py`'s "handler cleared after the block" check, which this phase updates to the new API; an unexpired deadline letting a statement finish is covered by that harness's other checks running under no deadline and by the live load check.
  2. *`seconds` of zero and negative* — the early-return path is unchanged by this build.
  3. *"Running" inferred from `started` plus 0.2s* — accepted by the auditor as meeting the rule; the 1.5s statement leaves margin.

**Changes**

- `engine/server/data/db.py` — `_deadline` (`threading.local`), `_deadline_passed` (the handler), `install_deadline_handler(conn)`; `statement_deadline(seconds)` sets and restores the thread's deadline and touches no connection; `connect_db` and `connect_readonly_db` install the handler; `connect_readonly_db` docstring rewritten; `threading` imported, unused `typing.Any` dropped.
- `engine/server/api/handlers/similar.py` — `_statement_deadline` calls `statement_deadline(seconds)`; docstring rewritten.
- `engine/server/data/search.py` — `search_deadline(server)` drops `conn`; both call sites updated; `search_connection` docstring and the comment above the `search_videos` lock rewritten to the remaining reason for a dedicated connection.
- `engine/server/api/server.py` — the `search_db` comment in `SimilarityServer.__init__` rewritten.
- `engine/server/db/jobs/tests/test-security-bundle.py` — imports `install_deadline_handler`, installs it on its `:memory:` connection, calls `statement_deadline(0.3)`.
- No file outside the phase's list was touched.

**Checkpoint outcome** — PASS. `validate_tests.py tests/tmp/test_statement_deadline.py`: 2 passed, exit 0. `test-security-bundle.py` under the Engine env: all 14 checks pass, including task 75's interrupt and cleared-after-block checks. Live, after `scripts/run-services.sh restart`: `tmp/load_live.sh` 3 rounds of mixed health/channels/search, every request 200, `vectorSearch: true`; `tmp/repro_channels.sh` 6 concurrent `?q=hackin` channel searches plus health probes, every request 200, Engine healthy after.

#### Coordination

- Phase 1, after implementation: restart the services (`scripts/run-services.sh restart`) and run the concurrent load harness from the deadlock fix (`tmp/load_live.sh`), to confirm every route still answers and an overrun still returns 503. This restarts the operator's running Engine and Client.

#### Rationale

One phase: two clauses from one Intent, and every file changes for the same reason. The red will come first as the new API's absence (`statement_deadline(seconds)` does not exist), so at Step 7.2 the scenarios are also run against the current code in a probe under `tests/tmp` using today's signature, to observe that they discriminate — C1's child hanging, C2's thread B interrupted — and the rows record those observed values.

## Inner unit tests

None. The checkpoint expresses both clauses at the seam; the deadline's cleared-on-exit behaviour is already asserted by `test-security-bundle.py`.

## Close

### Refactor pass

None made. The phase introduced no duplication or hard-coding. Left out: removing `search.py` `search_deadline`, which is now a nested deadline inside the request's own. Removing it moves the start of search's budget from lock acquisition to request start, which is a behaviour change and needs its own red, not a refactor.

### Clause accounting

- `P1C1` — carried: CLAUSE MAP rows C1a, C1b, dispatch 1, both auditors PASS.
- `P1C2` — carried: CLAUSE MAP rows C2a, C2b, dispatch 1, both auditors PASS.

### Suite

`validate_tests.py` bare run: exit 0, `tests/active` empty, matching the Step 0 baseline. `--compare`: no prior record to compare against (the Step 0 run collected nothing, so nothing was banked per group). No red.

### Documentation (Step 9)

- Step 3 docs checklist: empty, confirmed. `docs/wiki/` does not exist; `docs/project/adr/` does not exist. The deadline mechanism appears in `docs/project/security-audit/run-2/REPORT.md:144` as the recommended remediation for F10 (`set_progress_handler(... deadline ...)`), a dated audit record — no update.
- `docs/project/issues/archive/31-shared-connection-deadline-deadlock-guard.md` — comment appended recording delivery; closed as `complete`.

### Harvest (Step 10)

`docs/project/plans/archive/harvest-05-shared-connection-deadline-guard-plan.md`. Both checkpoint tests are DURABLE and now live in `tests/active/test_db.py`, mapped to `engine/server/data/db.py`. Each was felled by one mutation and went green again after the restore. The working files are in `delete_me/`. Final run: 2 passed.
