# 54-translate-job-handle

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-54-translate-job-handle.record.md`._

## Requirements

### Purpose

Move a translate job's invariants out of the callers and into the subtitles store (`engine/server/data/subtitles.py`). Today the callers carry four rules: the `started_at` compare-and-set on every write for a claimed job, the open-then-migrate order, recovery only under the worker's flock, and the whitelist/denylist resolve. They also carry the rules for a translatable video, which are duplicated between the `/internal/translate` routes and the translate worker. This is a refactor. Observable behaviour stays the same, apart from the one approved change described under "End ready from an instance track". It folds in issue 57 (resolve a translatable video once). Issue 56's job-pipeline part depends on it.

### Job handle

- `claim_translate_job` (or its replacement) returns a job handle, or `None` when no job for the target language is queued. The claim itself is unchanged: in one IMMEDIATE transaction, the oldest `queued` row by `queued_at` then rowid becomes `running`, gets `started_at` and has `attempts` raised by 1.
- The handle is a small class or dataclass in `engine/server/data/subtitles.py`. It carries the job's key (`video_id`, `instance_domain`, `target_language`), its `started_at` and its `attempts`. It either holds the store connection or takes it per call; the design step chooses which.
- The handle exposes these operations. Each one does the compare-and-set internally: it matches only while the row is `running` with this claim's `started_at`. Each reports whether the claim still held.
  1. **Write running cues:** rewrite the whole `cues_json` (as `_cues_text`, i.e. `allow_nan=False`) and set `detected_language`. Same as today's `store_running_cues`.
  2. **End ready:** state `ready`, the full start-sorted `cues_json`, `fetched_at` = `finished_at` = the given time. Same as today's `finish_translate_ready`.
  3. **End already_english:** state `already_english`, `detected_language`, `finished_at`. Same as today's `finish_translate_already_english`.
  4. **End failed:** state `failed`, `error` text, `finished_at`. Partial cues stay. Same as today's `finish_translate_failed`.
  5. **Requeue:** state `queued`, `attempts - 1`, with `queued_at` kept. Same as today's `requeue_translate_job`.
  6. **End ready from an instance track:** see the next section.
- How a lost claim is reported is the design step's choice, made once for every operation: either return `bool` (claim held), or raise one exception that the worker maps to its `JobTakenOver` path.
- No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `requeue_translate_job` and `mark_translate_finished` are removed from the store's public interface. `_update_claim` may remain as a private helper. `store_ready_subtitles` stays: the route still uses it.

### End ready from an instance track (one store operation)

- This replaces the worker's `store_ready_subtitles` + `mark_translate_finished` pair (`translate-worker.py` `generate`) with one conditional UPDATE. It applies only while the row is `running` with this claim's `started_at`.
- While the claim holds, it leaves exactly today's row: state `ready`, source `instance`, `track_text` set, `cues_json` set, `fetched_at` set and `finished_at` set. The cues are encoded as `store_ready_subtitles` encodes them today: `json.dumps(cues, ensure_ascii=False, separators=(",", ":"))`, which allows NaN. They are not encoded with `_cues_text`. Other job columns (`detected_language`, `error`, `attempts`, `queued_at`, `started_at`) are left as they are, as the upsert leaves them today.
- Approved simplification: a single timestamp supplies both `fetched_at` and `finished_at`. Today two separate `now_ms()` calls set them.
- Approved behaviour change: when the claim was lost, the operation changes nothing. Today the worker's upsert overwrites the Engine's row and then stamps `finished_at`. The worker then takes its takeover path: it logs `taken over by the instance track video_id=… host=…` and writes nothing further for the job.

### Takeover (unchanged behaviour)

- The Engine state route's instance-track store (`_store_cues` → `store_ready_subtitles`, an unconditional upsert) still replaces a running row, so the instance track wins the race. Making it conditional is out of scope.
- After such a takeover, every handle operation reports the claim lost. The worker's `JobTakenOver` path stays: it logs the takeover and writes nothing further for that job, which means no `failed` end and no requeue.
- The real writer is the state route's instance-track store, racing an enqueue and a claim. The route reads no row (or a `failed`/`already_english` row) and fetches the instance, which takes up to its 15 s budget. Meanwhile a job is enqueued and claimed, and the route's upsert then lands on the running row. An older blue/green Engine is a possible further writer. The `JobTakenOver` docstring and any docstrings that say "B1's route" (`run_job`, `_update_claim`/handle) must name this writer. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` § "Takeover by the Instance Track" already describes it; it is updated only where it names removed functions. `CONTEXT.md` already defines "Claim" and "taken over" and needs no change unless the wording of the handle requires it.

### Opening the store

- One open function in `subtitles.py` creates the parent directory (`mkdir(parents=True, exist_ok=True)`), connects in WAL mode with today's busy timeout and lock-retry loop (`connect_subtitles_db`), and migrates the schema (`ensure_subtitles_schema`).
- The Engine start (`engine/server/api/server.py`, currently lines 371-372) uses it. The open stays where it is in start-up order: after `prepare_trending_override`, so a rejected start still creates nothing. The worker's `enqueue` command and its `run` service use it too. None of these callers calls anything else to open the store.
- The heartbeat thread's own connection (`heartbeat_loop`) may use it too, or may keep the plain connect; the design step decides.
- On a fresh path, opening creates the directory and the full schema. On a B1-era file, it adds the job columns. The existing concurrent-opener guarantees hold: no `duplicate column`, no `database is locked`, and WAL afterwards.

### Recovery under the flock

- `recover_translate_jobs` logic is unchanged: rows at `attempts >= MAX_CLAIMS` become `failed` with `worker stopped while running twice`, and other `running` rows go back to `queued`.
- Callers must not be able to run it without the worker's flock by mistake. Two acceptable shapes: a worker-service store opener that runs recovery and can only be called while the flock is held (for example, it acquires the flock itself or takes the held lock as an argument), or recovery that takes proof of the lock. A test, or the type of the call, shows this.

### Route store access

- In `engine/server/api/handlers/internal_translate.py`, three sites each repeat the "hold `server.subtitles_db_lock`, take `server.subtitles_db`, treat `None` as closed" block: `_read_key`, `_store_cues` and the enqueue in `handle_internal_translate_enqueue`. One helper replaces all three.
- Responses for a closed store are unchanged:
  - state read: no row and `available: false`;
  - track store: a no-op, logged;
  - enqueue: `{"state": "none", "available": false}`, nothing queued.
- `sqlite3.Error` handling is unchanged: the read logs `cache read failed` and answers no row, not available; the store logs `cache write failed`; the enqueue logs and answers 503 `{"error": "Translate store unavailable"}`. The enqueue's beat check and enqueue stay under one lock hold.
- The route tests' `SimpleNamespace` server fake (`db`, `db_lock`, `video_error_threshold`, `subtitles_db`, `subtitles_db_lock`, `statement_timeout_seconds`) stays as it is. Changing it is not required.

### Resolve a translatable video (issue 57)

- One function takes a whitelist connection, a video id, a normalised host and an error threshold. It returns either the whitelisted row or a refusal, and never writes an HTTP response. The refusals are:
  - not in whitelist: `fetch_video_row` with the threshold finds no row;
  - host denied: `normalize_host(row["instance_domain"])` is in `list_active_denied_hosts(conn)`;
  - a missing host (`None` or empty): refused, never matched against the id on any host (`fetch_video_row` with a `None` host matches any host).
- The `/internal/translate` routes and the translate worker both use it, and its location must be importable by both. The worker already imports from `handlers.*` via `api/` on `sys.path`.
- Route: `_resolve_translate_key` keeps its own 400 validation of the `{id, host}` body: invalid JSON, `Missing id or host`, `Invalid host`. It calls the shared function on `server.db` under `server.db_lock` with `server.video_error_threshold`, and maps any refusal to its current 404 `{"error": "Video not found"}`. It keeps using the row's canonical `video_id`, `instance_domain` and `video_uuid or video_id`.
- Worker: `resolve_video` keeps its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its stored-duration bound (a NULL duration passes). It maps refusals to its current texts: `not in whitelist`, `host denied`, `duration Ns over Ms`. The `enqueue` command's `refused: invalid id or host` check is unchanged, and so are `generate`'s `sqlite3.OperationalError` → `WhitelistBusy` mapping and its exit codes.

### Documentation

- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` and the "Translate worker and its store contract" section of `engine/server/README.md` describe three things: the job handle and its operations, the takeover writer (the state route's instance-track store racing an enqueue and a claim), and the single store opener (plus how recovery is tied to the flock).
- The module docstrings of `subtitles.py`, `internal_translate.py` and `translate-worker.py` stop naming removed functions.

### Acceptance criteria

- [ ] No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. The five per-claim functions and `mark_translate_finished` are no longer public in the store.
- [ ] Every handle operation (running cues, ready, already_english, failed, requeue, ready from instance track) is a no-op that reports the claim lost when the row is no longer `running` with the claim's `started_at`. A test proves this for each operation.
- [ ] Ending ready from an instance track while the claim holds leaves state `ready`, source `instance`, the track text and cues, and `fetched_at` and `finished_at` set. When the claim was lost, it changes nothing.
- [ ] A state-route instance-track store over a running row still wins. The worker then logs the takeover and writes nothing further for that job.
- [ ] Opening the store on a fresh path creates the directory and the full schema, and opening a B1-era file adds the job columns. The Engine and the worker's `enqueue` and `run` entry points call nothing else to open the store.
- [ ] Recovery cannot be called from the worker without the flock held. A test or the type of the call shows this.
- [ ] The three route sites use one store-access helper, and route responses for a closed store are unchanged.
- [ ] One resolve function serves both the routes and the worker. A missing host is refused, and a denied host is refused on the row's normalised domain. The routes' 400 and 404 responses and the worker's refusal texts are unchanged.
- [ ] The existing tests pass: `tests/active/test_internal_translate.py`, `tests/active/test_translate_worker.py` and `tests/active/test_subtitles.py`. They are rewritten only where they used the removed functions or the claim tuple, for example the subprocess writer script in `test_subtitles.py` and the row-seeding helpers in `test_internal_translate.py`. The worker test for "the instance holds an English track" still sees ready/instance with the parsed cues and track text, and `finished_at` taken during the run.
- [ ] The docs listed above describe the handle, the takeover writer and the single store opener.

### Out of scope

- Making the state route's instance-track store conditional (a running job winning the race).
- Removing `JobTakenOver`.
- The source-instance fetch adapter (issue 53, already delivered) and the rest of the worker split (issue 56): timing parameters and moving the pipeline out of the script.
- Changing job states, `MAX_CLAIMS`, recovery's requeue-once rule, the queue cap or the heartbeat.
- Any schema change beyond what the store opener already migrates.
- Replacing the route tests' `SimpleNamespace` server fake.
- Closing issue 57 in the tracker. That is housekeeping after delivery, as covered by 54, and not part of the code build.

### Baseline suite state

- Pre-build suite exited 0, not a variant run. The selective runner chose 1 of 65 groups (`test_search_fusion.py`, 10 passed), and 64 groups were unchanged and not re-run. The translate route, translate worker and subtitles store tests were therefore not freshly run at baseline; they are presumed green from their last recorded pass.

### Notes on the tree

- The issue's line references are out of date since issue 53 landed. The claim tuple is built at `translate-worker.py:437`. The upsert-then-stamp is at `:407-408`. The opener sites are `:131-135` (enqueue) and `:531-535` (run), plus the heartbeat at `:465`. `JobTakenOver` is at `:87-88`, and the route's lock sites are `internal_translate.py:157-160`, `:179-182` and `:261-263`. The behaviour the issue describes matches the code.

## High-level plan

### Approach

The work touches three code files and no new modules: `engine/server/data/subtitles.py` (the store), `engine/server/api/handlers/internal_translate.py` (the routes and the shared resolve) and `engine/server/db/jobs/translate-worker.py` (the worker). `engine/server/api/server.py` changes by one call, and the docs and tests follow.

**Job handle.** `subtitles.py` gets a small frozen dataclass, `TranslateJob`. It holds the store connection the claim was made on, plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`. `claim_translate_job` keeps its name, signature and IMMEDIATE transaction (oldest `queued` by `queued_at` then rowid, set `running` and `started_at`, raise `attempts` by 1). It now returns this handle, built from the row it already re-reads, or `None`. The handle holds the connection rather than taking it per call. Every write for a claim must go to the connection that claimed it, and holding it means no caller can pair a handle with the wrong connection (the heartbeat thread has its own). It also lets `generate` and `translate_audio` stop carrying a connection argument at all.

The handle has six methods, each a thin call to the private `_update_claim`, which keeps its single conditional UPDATE matching `state = 'running' AND started_at = ?`. Each method takes its timestamp from the caller, as today:
- write running cues (`_cues_text`, plus `detected_language`);
- end ready (start-sorted cues via `_cues_text`, `fetched_at` = `finished_at` = the given time);
- end already_english;
- end failed (partial cues stay);
- requeue (`queued`, `attempts - 1`, `queued_at` untouched);
- end ready from an instance track.

`_update_claim` takes the handle's fields instead of a loose key, so the claim tuple exists only inside the module. The five per-claim functions and `mark_translate_finished` are deleted. `store_ready_subtitles` stays.

**Lost claim reported as `bool`.** Every method returns `True` when the claim held and `False` otherwise. This is today's contract, so the worker's control flow is unchanged:
- `translate_audio` still raises `JobTakenOver` on `False` from running cues, already_english and ready.
- `generate` raises it on `False` from the new instance-track end.
- `run_job` still ignores the result of requeue and end failed, as today. A takeover that lands during a stop or a failure therefore still writes nothing and logs what it logs today.

**End ready from an instance track.** One conditional UPDATE through `_update_claim` sets:
- state `ready`;
- source `instance`;
- `track_text`;
- `cues_json`;
- `fetched_at` = `finished_at` = one timestamp.

It leaves every other job column alone. The cues are encoded by a private helper that `store_ready_subtitles` also switches to: `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`, NaN allowed, not `_cues_text`. One helper keeps the two instance-track writers encoding identically. `SOURCE_INSTANCE` moves into `subtitles.py` beside `SOURCE_WHISPER`. `internal_translate.py` imports it from there, so its own name still resolves. The worker no longer needs it at all, because the handle method fixes the source. In `generate`, the upsert-then-stamp at `:407-408` becomes one call with one `now_ms()`. A `False` result raises `JobTakenOver`, and the existing `taken over by the instance track video_id=… host=…` log line follows. This is the approved change: a lost claim now writes nothing, where today the upsert overwrites the Engine's row.

**Takeover unchanged.** The state route's `_store_cues` still calls the unconditional `store_ready_subtitles`, so the instance track still wins over a running row. Every handle method then matches nothing. The docstrings of `JobTakenOver`, `run_job`, `_update_claim` and the handle name the real writer: the state route's instance-track store, racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. They no longer say "B1's route".

**Single store opener.** `open_subtitles_db(path)` in `subtitles.py` does three things in order:
1. creates the parent directory;
2. calls `connect_subtitles_db`, keeping the WAL switch, the 30 s busy timeout and the lock-retry loop;
3. runs `ensure_subtitles_schema`.

If the migration raises, it closes the connection before re-raising. Three callers use it: `server.py` (its two lines at 371-372, in the same place, after `prepare_trending_override`), the worker's `enqueue` (replacing `:131-135`) and the worker service opener below. `connect_subtitles_db` and `ensure_subtitles_schema` stay public, because the tests and the heartbeat use them. The concurrent-opener guarantees come for free: the opener only composes the two functions that provide them today.

**Heartbeat keeps the plain connect.** The beat thread starts only after the main thread's opener has migrated the file. Re-running the migration there would be a pointless extra IMMEDIATE transaction on every service start, so this decision is to keep `connect_subtitles_db` there.

**Recovery tied to the flock.** `subtitles.py` gets a worker-service opener, `open_translate_worker_store(path, lock_fd, finished_at)`, which returns the connection and the `(requeued, failed)` counts. Before anything touches the file, it re-asserts `flock(lock_fd, LOCK_EX | LOCK_NB)` on the descriptor it was given:
- On a descriptor whose open file description already holds the lock (the worker's), this is a no-op.
- When another process or open file description holds the lock, it raises `BlockingIOError` before the file is opened. Nothing is created or written.
- On an unlocked descriptor it takes the lock. Either way recovery can only run while the flock is held.

It then calls `open_subtitles_db` and recovery. `recover_translate_jobs` becomes private `_recover_translate_jobs` with its logic unchanged, so nothing outside the module can call it bare. `command_run` keeps its own LOCK_NB acquire first, which preserves the `another worker holds` log line and exit 6 before the store is opened. It then replaces `:531-536` with the one call. `fcntl` is imported inside that function, so the Engine's import of `subtitles.py` gains nothing.

Tests:
- a second open file description holding the lock makes the opener raise and leaves the subtitles file absent;
- with the lock held, recovery runs exactly as today's recovery test expects.

**Route store access.** One context manager in `internal_translate.py`, `_subtitles_store(server)`, holds `server.subtitles_db_lock` for its body and yields `server.subtitles_db`, which is `None` when the store is closed. The three sites (`_read_key`, `_store_cues`, the enqueue) use it. Each keeps its own `sqlite3.Error` handler and its own closed-store answer, because the three answers differ:
- the read answers no row, not available;
- the enqueue answers `{"state": "none", "available": false}`;
- the track store gains one info log line on a closed store, which is the operator's decision.

The enqueue's beat check and enqueue stay inside one `with`. The route tests' `SimpleNamespace` fake is untouched.

**Resolve a translatable video (issue 57).** `resolve_translatable_video(conn, video_id, host, error_threshold)` lives in `handlers/internal_translate.py`. That is the route's own module, and the worker already imports it via `api/` on `sys.path`. It returns `(row, None)` or `(None, refusal)` and writes no response. The refusal is one of three strings:
- `missing host`, for a `None` or empty host, decided before any lookup;
- `not in whitelist`, when `fetch_video_row` with the threshold finds no row;
- `host denied`, when the row's `normalize_host(instance_domain)` is in `list_active_denied_hosts(conn)`.

The middle two are exactly the worker's current texts.

- **Route:** `_resolve_translate_key` keeps its own body validation and its three 400s. It calls the shared function on `server.db` under one `server.db_lock` hold, which merges today's two hold sites into one, with `server.video_error_threshold`. Any refusal maps to 404 `VIDEO_NOT_FOUND`, and the route keeps using the canonical `video_id`, `instance_domain` and `video_uuid or video_id`. It drops its `resolve_video_row` import.
- **Worker:** `resolve_video` keeps its signature (tests monkeypatch it), its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its duration bound. Refusals pass through unchanged, except `missing host`, which maps to `not in whitelist`. That is what an empty host yields today, and `enqueue` refuses such a host earlier anyway. `generate`'s `OperationalError` → `WhitelistBusy` mapping and all exit codes are untouched.

**Tests.** Rewritten only where the removed functions, the claim tuple or the claim's return are used:
- `test_subtitles.py`: the subprocess writer script, the claim test's subscripting, the `fetch_subtitle_state` test and the recovery test, which now goes through the lock-taking opener.
- `test_internal_translate.py`: `_claimed` and `_seed`, plus the two running/failed sequences at `:755-792`.
- `test_translate_worker.py`: `Rig.claim`, `Rig.run` and the fetch-reason test's `run_job` call, because `run_job` no longer takes a connection.

New tests:
- a parametrised store test for the six handle methods: after a `store_ready_subtitles` takeover, each returns `False` and leaves the row byte-identical;
- the instance-track end while the claim holds;
- the opener on a fresh nested path and on a B1-era file;
- the route's closed-store log line.

The existing worker test for "the instance holds an English track" should pass unchanged in its assertions.

**Docs.** Three docs are updated:
- `TRANSLATE_WORKER.md`: the start-order step that names `ensure_subtitles_schema` and recovery, the handle and its methods, the opener and the flock tie, and § Takeover only where it names removed functions.
- `engine/server/README.md` § "Translate worker and its store contract": the same three topics.
- The module docstrings of the three code files.

### Alternatives considered

- **Handle takes the connection per call.** This would keep `run_job(conn, job, …)` and spare two test call sites. Rejected: the handle would be pairable with any connection, including the heartbeat's, and `generate`/`translate_audio` would keep threading a connection whose only job is to match the claim's.
- **Raise a `ClaimLost` exception from the store.** Rejected: the worker would then need a second exception mapped onto `JobTakenOver` (and removing `JobTakenOver` is out of scope). The requeue and end-failed calls in `run_job`'s handlers, which ignore a lost claim today, would need new try blocks. `bool` is today's contract and changes no control flow.
- **Recovery takes the lock fd as an argument.** This is the other acceptable shape. Rejected because the service would still call open and then recover as two steps. Folding open and recovery behind the lock check gives the service one call and leaves no public recovery to misuse.
- **A lock object or class for the flock.** Rejected as an interface with one implementation: the raw fd plus a non-blocking re-assert is the proof.
- **Put the resolve in `handlers/video.py` or a new module.** `video.py` is the generic video module and the denylist rule is translate-specific. A new module would be one more file. `internal_translate.py` is already imported by both callers.
- **A route helper that takes a callable and a closed-store default.** It would centralise the `None` branch too. Rejected because the three sites' closed answers and error handling differ, so the callable form would need three lambdas and a default per site. That is more indirection than the repetition it removes.
- **Heartbeat on the full opener.** Rejected, as above: a redundant migration transaction per start for no guarantee gained.

### Risks and gotchas

- **flock semantics.** A flock belongs to an open file description, so the re-assert succeeds only on the descriptor the worker locked. A second `os.open` of the same lock file in the same process is refused, which is what the test relies on. On an unlocked descriptor the re-assert acquires the lock rather than failing. That still satisfies "never recover without the flock", but the docstring must say so plainly.
- **The Engine opener now creates a missing parent directory.** For the default path it already exists, because of the random-cache `mkdir` just before. For a custom `--subtitles-db` in a missing directory, start-up now succeeds where it failed before. The open is still after `prepare_trending_override`, so a rejected start still creates nothing.
- **Route resolve now uses one `db_lock` hold instead of two.** It holds the lock marginally longer and removes a window between lookup and denylist read. Responses do not change.
- **NaN in instance-track cues.** The instance-track end must keep the NaN-allowing encoding by contract. `parse_webvtt` cannot produce NaN, so this only matters for fidelity with `store_ready_subtitles`. Sharing one encoding helper keeps the two from drifting.
- **Stale copies outside the active suite.** `delete_me/` and `tests/tmp/` probes import the removed functions and will break if run. They are not in the active suite and are left alone.
- **Unverified baseline.** The three active test files were not freshly run at baseline. A pre-existing red there would show up during this build and look like a regression.

### Tradeoffs the operator is asked to accept

- **`run_job` loses its connection argument.** The worker tests' `Rig.run` and the fetch-reason test change their `run_job` call. These are the call sites that pass the claim's result, but strictly it is a signature change beyond the removed functions.
- **The recovery test changes.** `test_subtitles.py`'s recovery test now goes through the lock-taking opener because recovery is private. This follows from the flock requirement, not from the removed-function list.
- **The handle is not subscriptable.** Tests that read `job["started_at"]` from `claim_translate_job` switch to attributes.
- **New log line.** The route's closed-store track store gains one info log line (the operator's decision). This is a second small observable change beside the approved instance-track one.
- **`missing host` folds into `not in whitelist` on the worker side.** The worker reports a missing-host refusal as `not in whitelist`, to keep its texts unchanged. Today's behaviour is the same, but the two causes stay indistinguishable in the worker's error column.

## Impacts


<impacts>
<impact path="engine/server/data/subtitles.py" element="module docstring (line 3)">
**What changes.** The docstring says "B1's route upserts state 'ready' with source 'instance'", and describes job columns "added in place by ensure_subtitles_schema". It must now describe four things:
- the claim handle (`TranslateJob`) and its six claim-conditional methods;
- `open_subtitles_db` as the one opener (mkdir, then WAL connect, then migrate);
- `open_translate_worker_store` as the only way to run recovery, and only under the worker's flock;
- the instance-track writers: the state route's unconditional `store_ready_subtitles` and the handle's conditional instance-track end.

**Depends on it.** Nothing at runtime.

**Risk.** None functionally. It goes stale if left alone, because "B1's route" is the wording the plan retires.
</impact>
<impact path="engine/server/data/subtitles.py" element="imports (lines 5-12)">
**What changes.**
- Add `from dataclasses import dataclass` for `TranslateJob`.
- `fcntl` must NOT be imported at module level. The plan imports it inside `open_translate_worker_store` only, so the Engine's import of this module gains nothing.
- `json`, `sqlite3`, `time`, `contextmanager`, `Path`, `Any` and `Iterator` stay.

**Depends on it.** These modules import this one:
- `server.py` (line 106);
- `internal_translate.py` (line 22);
- `translate-worker.py` (line 44);
- the three active test files, including the subprocess scripts in `test_subtitles.py` (UPGRADE_SCRIPT, ENGINE_SCRIPT, WORKER_SCRIPT), which import `data.subtitles` under ENGINE_PY.

**Risk.** Low. A module-level `fcntl` import would still work on Linux, but it breaks the plan's stated guarantee.
</impact>
<impact path="engine/server/data/subtitles.py" element="SOURCE_INSTANCE constant (new, beside SOURCE_WHISPER at line 16)">
**What changes.** `SOURCE_INSTANCE = "instance"` moves here from `internal_translate.py:29`.

**Depends on it.**
- `internal_translate.py`: re-imports it, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves. `_store_cues` uses it at line 182.
- The new handle method for the instance-track end uses it to fix the source.
- `translate-worker.py:47` imports it today. After this change it must not, or it has to import it from its new home.
- Stale copies import it from `handlers.internal_translate`: `delete_me/test_53_source_instance_fetch_adapter_phase2.py` and the `tests/tmp/probe_53_*` files. They still resolve, because the route keeps the name.

**Risk.** Low. Tests write the literal `"instance"` (`test_internal_translate.py:618`, `test_translate_worker.py:1042`, `test_subtitles.py:107`), so the value must stay byte-identical.
</impact>
<impact path="engine/server/data/subtitles.py" element="store_ready_subtitles (lines 104-115) and the new private instance-cues encoder">
**What changes.** The inline `json.dumps(cues, ensure_ascii=False, separators=(",", ":"))` at line 114 moves into a new private helper, which the instance-track handle method also uses. The encoding must stay exactly as it is: NaN allowed, so no `allow_nan=False`. It must NOT become `_cues_text`. Signature, upsert SQL and docstring otherwise stay. The docstring's "a running job's conditional updates then match nothing" still holds, and now covers the instance-track end as well.

**Depends on it.**
- `internal_translate._store_cues` (line 182), which is the takeover writer.
- Tests: `test_internal_translate._seed` (lines 618, 620); `test_translate_worker.py:1042`, the B1 takeover test; `test_subtitles` ENGINE_SCRIPT (line 107); the new parametrised takeover test.
- `test_internal_translate.py:502` asserts the stored `cues_json` is compact, with no space and no newline.

**Risk.** Medium-low. If the helper picks up `allow_nan=False` or a different separator, the compact assertion at :502 or byte-identity across the two writers breaks. NaN cannot come out of `parse_webvtt`, so a divergence there would go unnoticed by tests.
</impact>
<impact path="engine/server/data/subtitles.py" element="_cues_text (lines 118-120)">
**What changes.** Nothing. It stays the encoder for running cues and for the whisper ready end (`allow_nan=False`).

**Depends on it.** The handle's running-cues and end-ready methods.

**Risk.** The danger is the instance-track end reusing `_cues_text` by mistake. That would make a NaN raise where `store_ready_subtitles` accepts it, which breaks the plan's encoding contract.
</impact>
<impact path="engine/server/data/subtitles.py" element="TranslateJob frozen dataclass and its six methods (new)">
**What changes.** A new `@dataclass(frozen=True)` with these fields: the claiming connection, `video_id`, `instance_domain`, `target_language`, `started_at`, `attempts`. Six methods, each a thin `_update_claim` call returning `bool`, with the timestamp passed in by the caller:
- **running cues:** `cues_json = _cues_text(cues), detected_language = ?`. Today's `store_running_cues`, line 167.
- **end ready:** `state='ready', cues_json, fetched_at = finished_at`. Today's `finish_translate_ready`, line 177.
- **end already_english:** `state='already_english', detected_language, finished_at`. Line 182.
- **end failed:** `state='failed', error, finished_at`. Line 187.
- **requeue:** `state='queued', attempts = attempts - 1`, `queued_at` untouched. Line 172.
- **end ready from an instance track (new):** `state='ready', source='instance', track_text, cues_json` (NaN-allowing encoder), `fetched_at = finished_at`. One timestamp, and no other column touched.

The SET strings must be copied exactly.

**Depends on it.** The worker (`translate_audio`, `generate`, `run_job`, `serve`) and every test that claims a job.

**Risk.**
- **High.** Today the instance-track pair sets `fetched_at` and `finished_at` from two separate `now_ms()` calls. The new method must take one value and set both.
- The `attempts - 1` text has to stay.
- Equality: a frozen dataclass holding a `sqlite3.Connection` compares and hashes the connection field. That is harmless, but `repr` will print the connection object.
- The class is not subscriptable, so every `job["..."]` reader breaks. See the test entries and `serve` at `translate-worker.py:495`.
- Method names are a design choice and are not fixed here. The next step should check them against the docs that will name them.
</impact>
<impact path="engine/server/data/subtitles.py" element="claim_translate_job (lines 139-147)">
**What changes.** Name, signature and the IMMEDIATE transaction stay. The return type goes from `sqlite3.Row | None` to `TranslateJob | None`. The handle is built from the re-read row (line 147) plus the `target_language` argument and `conn`. The docstring must say it returns a handle.

**Depends on it.**
- `translate-worker.serve` (line 485).
- `test_subtitles.py`: lines 133-141 (WORKER_SCRIPT, including `tuple(job)` in the error message at 135, which raises TypeError on a dataclass, though only on the failure path), 338-340, 363-372 and 394.
- `test_internal_translate.py:610` (`_claimed`).
- `test_translate_worker.py`: 542-544 (`Rig.claim`) and 922.

**Risk.** Medium. Every subscript reader fails at once with TypeError, which at least makes it loud. The transaction itself does not change.
</impact>
<impact path="engine/server/data/subtitles.py" element="_update_claim (lines 158-162)">
**What changes.** It takes the handle (or its fields) instead of a loose `(conn, video_id, instance_domain, target_language, started_at)`. It keeps the single `UPDATE … WHERE {_KEY} AND state = 'running' AND started_at = ?` inside `with conn:` and returns `rowcount == 1`. Its docstring must stop saying "B1's route took the row over". Instead it names the state route's instance-track store racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer.

**Depends on it.** The six handle methods only.

**Risk.** Medium. Any change to the WHERE clause or its parameter order breaks every conditional write. The new takeover test is the guard: each method must return False and leave the row byte-identical.
</impact>
<impact path="engine/server/data/subtitles.py" element="store_running_cues, requeue_translate_job, finish_translate_ready, finish_translate_already_english, finish_translate_failed, mark_translate_finished (lines 165-193): deleted">
**What changes.** All six module-level functions are removed.

**Depends on it.** Active code:
- `translate-worker.py:44`, the import, and the call sites at 372, 378, 387, 408, 442, 446, 452 and 459.

Active tests:
- `test_subtitles.py`: 119, 137-141 (WORKER_SCRIPT, inside a string, so grep for the import misses it), 388 and 395;
- `test_internal_translate.py`: 615, 625, 627, 629, 755, 759, 768, 779 and 792.

Stale and inactive files: `tests/tmp/probe_45_*`, `probe_50_phase1_rows.py`, `probe_53_*` (13 hits each), `probe_green.py`, `probe_race.py`, `probe_phase2_worker_cli.py`, `delete_me/*.bak*`.

**Risk.** High for the active tests. A missed reference is an ImportError, and in WORKER_SCRIPT it only shows up as a subprocess exit code. The stale probes will break if run; the plan accepts that.
</impact>
<impact path="engine/server/data/subtitles.py" element="recover_translate_jobs (lines 150-155), renamed private _recover_translate_jobs">
**What changes.** It is renamed to `_recover_translate_jobs`. The logic is unchanged: fail at `attempts >= MAX_CLAIMS` with RECOVERY_ERROR and `finished_at`, then requeue the remaining running rows, in one IMMEDIATE transaction. The docstring's "only under its flock" is now enforced by its only caller.

**Depends on it.**
- `translate-worker.py:44` and `:536`.
- `test_subtitles.py:347`, `:366` and `:372`, the recovery test, which must now go through `open_translate_worker_store`.
- The `test_subtitles.py:17` docstring bullet.

**Risk.** Medium. The failed-before-requeued statement order inside the transaction is what makes `(2, 1)` come out right in the test, so it must stay.
</impact>
<impact path="engine/server/data/subtitles.py" element="open_subtitles_db(path) (new)">
**What changes.** A new public opener:
1. `path.parent.mkdir(parents=True, exist_ok=True)`;
2. `connect_subtitles_db(path)`;
3. `ensure_subtitles_schema(conn)`.

On any exception from the migration it closes the connection and re-raises.

**Depends on it.**
- `server.py:371-372`;
- `translate-worker.command_enqueue` (`:131-135`);
- `open_translate_worker_store`;
- new tests on a fresh nested path and on a B1-era file;
- possibly `test_internal_translate._subtitles_db`, if it is switched to it. That is optional.

**Risk.**
- Low-medium. It must catch `BaseException`, or at least `Exception`, for the close. A missing close only leaks the connection.
- The concurrent-upgrade guarantees (WAL retry and the one-IMMEDIATE migration) come from the two composed functions, so `test_subtitles`' 24-round race test is unaffected as long as it keeps calling them directly.
</impact>
<impact path="engine/server/data/subtitles.py" element="open_translate_worker_store(path, lock_fd, finished_at) (new)">
**What changes.** A new public opener for the worker service:
1. Import `fcntl` locally.
2. Call `fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)`. `BlockingIOError` propagates before any mkdir, connect or file creation.
3. Call `open_subtitles_db(path)`.
4. Call `_recover_translate_jobs(conn, finished_at)`.
5. Return `(conn, (requeued, failed))`.

**Gap in the plan:** it says the opener closes the connection when the migration fails, but not when recovery raises. This function should close `conn` if `_recover_translate_jobs` raises. Today `command_run`'s `finally` closes it (lines 541-545); after the change `conn` is never bound in `command_run` if the opener raises.

**Depends on it.**
- `translate-worker.command_run`;
- new tests: a second `os.open` description holding the lock makes it raise and leaves the subtitles file absent; with the lock held, recovery runs as today's test expects.

**Risk.** High.
- **flock semantics:** the re-assert is a no-op only on the same open file description. On an unlocked fd it acquires the lock, and the docstring must say so.
- **Ordering:** mkdir must come after the flock, or a refused call creates a directory. The new test checks only that the file is absent.
- **Fd ownership:** it must not close or unlock `lock_fd`; `command_run` still owns it (line 547).
</impact>
<impact path="engine/server/data/subtitles.py" element="connect_subtitles_db, ensure_subtitles_schema (lines 25-77): stay public">
**What changes.** Nothing in the code.

**Depends on it.**
- `translate-worker.heartbeat_loop` (line 465) keeps `connect_subtitles_db`.
- Tests use both directly: `test_subtitles.py` (82-88, 97-104, 119-126, 192-195, 217-230); `test_internal_translate.py:418-424`; `test_translate_worker.py:87`, `271-272`, `507-508`, `912-913`, `1041` and `1260`.
- `server.py` and the worker's enqueue stop calling them directly.

**Risk.** None, if they are left as they are.
</impact>
<impact path="engine/server/data/subtitles.py" element="fetch_ready_subtitles, fetch_subtitle_state, fetch_translate_heartbeat, enqueue_translate_job, write_translate_heartbeat, _immediate, _KEY, MAX_CLAIMS, RECOVERY_ERROR, JOB_COLUMNS">
**What changes.** Nothing.

**Depends on it.** The route, the worker, the tests and `engine/server/README.md:35-36`.

**Risk.** None. Listed so the next step can confirm they stay as they are.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="module docstring (lines 1-8)">
**What changes.**
- Paragraph 2 ("An unknown or denylisted video answers 404 … before any remote fetch or store read") stays true. It should say the resolve goes through `resolve_translatable_video`, shared with the worker.
- Paragraph 3 (enqueue: "validates and resolves exactly as the state route does … a closed store included") stays true.
- Mention the new info log line for a closed store on the track store.

**Depends on it.** Nothing at runtime.

**Risk.** None.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="imports (lines 9-26)">
**What changes.**
- Drop `from handlers.video import resolve_video_row` (line 24). Add `from handlers.video import fetch_video_row`, which the shared resolve needs.
- Add `SOURCE_INSTANCE` to the `data.subtitles` import (line 22).
- Add `contextmanager` (and `Iterator` for typing) for `_subtitles_store`.
- `list_active_denied_hosts` and `normalize_host` stay, now used by the shared resolve as well as the body check.

**Depends on it.**
- `router.py:41` imports `handle_internal_translate` and `handle_internal_translate_enqueue`.
- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track`, and the new `resolve_translatable_video`.
- `test_internal_translate.py` loads it via `importlib.import_module("handlers.internal_translate")` (lines 290-294, 391-394).
- `test_source_fetch.py:25` imports helpers from `test_internal_translate`.

**Risk.**
- Import cycle: `handlers.video` does not import `internal_translate`, so there is no cycle.
- The module must stay free of numpy and faster-whisper, because the worker's enqueue path imports it.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="SOURCE_INSTANCE (line 29) and VIDEO_NOT_FOUND comment (line 34)">
**What changes.**
- Line 29's local definition is replaced by the import from `data.subtitles`. The name still resolves as a module attribute.
- Line 34's comment, "The body resolve_video_row answers, reused for a denied host", goes stale: the route no longer calls `resolve_video_row`, and now maps every refusal to this body itself. It must be reworded.

**Depends on it.** `VIDEO_NOT_FOUND` must stay `{"error": "Video not found"}`. The tests' `VIDEO_NOT_FOUND` constant and the Client's `TRANSLATE_NOT_FOUND_ERROR` pin it.

**Risk.** Low, provided the literal is unchanged.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="resolve_translatable_video(conn, video_id, host, error_threshold) (new)">
**What changes.** New. It returns `(row, None)` or `(None, refusal)`:
- `missing host` for a None or empty host, decided before any query;
- `not in whitelist` when `fetch_video_row(conn, video_id, host, error_threshold=…)` returns None;
- `host denied` when `normalize_host(row["instance_domain"]) in list_active_denied_hosts(conn)`.

It writes no response and takes no lock.

**Depends on it.** `_resolve_translate_key`, and the worker's `resolve_video`.

**Risk.** Medium.
- **Order.** The order must be: host check, then the row lookup, then the denylist read only when a row exists. The worker test "any other OperationalError" (`test_translate_worker.py:1079-1091`, drop-column and zero-byte cases) relies on `fetch_video_row` raising first with its own text.
- **Empty host.** A truthy check on host matters: `fetch_video_row` with a None host matches any host.
- **Denylist case.** The denylist row is stored uppercase in the tests. `list_active_denied_hosts` normalises it, so the comparison must stay on normalised values.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_resolve_translate_key (lines 187-215)">
**What changes.**
- Body validation and its three 400s stay byte-identical: `read_json_body`'s message, `Missing id or host`, `Invalid host`.
- The `resolve_video_row` call (line 203) and the separate denylist hold (lines 210-214) become one `with server.db_lock:` around `resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)`.
- Any refusal gives 404 `VIDEO_NOT_FOUND`.
- It returns `(body, row["video_id"], row["instance_domain"], row["video_uuid"] or row["video_id"])`.

**Depends on it.** Both handlers, and these tests:
- the 404 parity tests at `test_internal_translate.py:462-488` and `936-962`;
- the REFUSED table (`924-933`), which includes "known uuid on another host";
- the startup test at 1028-1031, which posts an unknown video to the live Engine.

**Risk.** Medium.
- `resolve_video_row` used to answer 400 `Missing video id` for an empty id. That is unreachable here, because the route already answers `Missing id or host`. Do not reintroduce it.
- The route must keep passing the normalised host.
- The lock is held slightly longer. The SimpleNamespace fake's `db_lock` is a plain `threading.Lock`, so it must not be re-entered.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_subtitles_store(server) context manager (new)">
**What changes.** New `@contextmanager`. It holds `server.subtitles_db_lock` for the whole body and yields `server.subtitles_db`, which may be None. It must not catch exceptions: each caller keeps its own `sqlite3.Error` handler outside the `with`.

**Depends on it.** `_read_key`, `_store_cues` and the enqueue.

**Risk.** Medium-low.
- A generator-based context manager that wraps `yield` in try/except, or one that holds the lock only around the attribute read, would break the "one lock hold" guarantee of the enqueue (beat read plus insert). That guarantee is pinned by the README at line 23.
- The SimpleNamespace fake supplies `subtitles_db` and `subtitles_db_lock`, and the plan leaves it untouched.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_read_key (lines 154-164)">
**What changes.** It uses `_subtitles_store`. A closed store still returns `(None, False)`. A `sqlite3.Error` is still logged `[translate] cache read failed …` and returns `(None, False)`.

**Depends on it.** `handle_internal_translate`, and the tests at `test_internal_translate.py:699-710`, 688-696 and 728-740.

**Risk.** Low.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="_store_cues (lines 176-184)">
**What changes.** It uses `_subtitles_store`. A new INFO log line is written when the store is closed (operator decision); the wording is for the next step to choose. `sqlite3.Error` is still logged `[translate] cache write failed …`. `store_ready_subtitles` stays the unconditional writer, with `SOURCE_INSTANCE` now imported.

**Depends on it.**
- `handle_internal_translate`, at line 245.
- A new route test: closed store plus an instance track gives the log line, and the answer stays `ready`.
- The `_failed_fetches` helper (`test_internal_translate.py:528-529`) filters on the `[translate] instance fetch failed` prefix. The new line must not start with that prefix, or the NONE_CASES exact-list assertions could pick it up.

**Risk.** Low-medium. This is a new observable log line, and the NONE_CASES/budget tests compare exact lists of failed-fetch lines.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="handle_internal_translate_enqueue (lines 253-273)">
**What changes.** The beat check and `enqueue_translate_job` stay inside one `with _subtitles_store(server) as conn:`. A closed store still gives `{"state":"none","available":false}`, and a `sqlite3.Error` still gives 503 `Translate store unavailable` with the `[translate] enqueue failed` log.

**Depends on it.** Tests at `test_internal_translate.py:830-920`.

**Risk.** Low-medium. The availability check must stay inside the same hold.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="handle_internal_translate, _generation_available, fetch_instance_track, parse_webvtt, pick_english_track_path, TARGET_LANGUAGE, HEARTBEAT_FRESH_MS">
**What changes.** Nothing beyond the call into `_resolve_translate_key`. The docstring of `_generation_available` ("The caller holds subtitles_db_lock") stays true.

**Depends on it.** The worker imports `TARGET_LANGUAGE` and `fetch_instance_track`.

**Risk.** None.
</impact>
<impact path="engine/server/api/handlers/video.py" element="resolve_video_row (lines 260-282) and fetch_video_row (lines 24-78)">
**What changes.** Nothing. `resolve_video_row` loses its translate caller but keeps its `/api/video` caller at line 447. `fetch_video_row` gains a caller: the new shared resolve.

**Depends on it.** `/api/video`, `/api/video/refresh` and `test_video.py`.

**Risk.** None, if nothing in it changes. Do not delete `resolve_video_row`.
</impact>
<impact path="engine/server/api/router.py" element="import of handle_internal_translate/handle_internal_translate_enqueue (line 41) and POST_ROUTES (141-142)">
**What changes.** Nothing. The handler names are unchanged.

**Depends on it.** Engine routing. `test_router.py` and the startup test in `test_internal_translate.py`.

**Risk.** None. Listed so the next step can confirm the handler names are unchanged.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 8 (internal_translate summary)">
**What changes.** Optional. It could mention that the module also holds the translatable-video resolve shared with the worker. Nothing it says now is false.

**Depends on it.** Nothing.

**Risk.** None. I am unsure whether the doc pass will want this line touched.
</impact>
<impact path="engine/server/api/server.py" element="import (line 106) and the subtitles open (lines 369-372)">
**What changes.**
- Line 106 changes to `from data.subtitles import open_subtitles_db`.
- Lines 371-372 become `subtitles_db = open_subtitles_db(subtitles_db_path)`, in the same place: after `prepare_trending_override` (351) and after the random-cache mkdir (369).
- The comment at 370 ("After the mkdir above (the default lives in the same directory)") goes partly stale, because the opener now creates its own parent. It should be reworded to keep only the "after prepare_trending_override, so a rejected start creates nothing" point.
- `server.subtitles_db = subtitles_db` (504) and the shutdown close (575-579) are unchanged.

**Depends on it.**
- `test_internal_translate.py:998-1039`: the Engine start creates a missing `subtitles.db` at an overridden path.
- Every test group listing `server.py` in `tests/config.json`: `test_similar`, `test_server_config`, `test_internal_events`, `test_random_cache` and `test_internal_translate`. Each starts the Engine, so all of them exercise this line.

**Risk.** Low-medium. Behaviour change: a custom path in a missing directory now starts instead of failing. The plan accepts this, and the README Notes should say so.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="module docstring (lines 2-9)">
**What changes.**
- Line 8 ("run is the service, in this order: ffmpeg check, flock …, schema and crash recovery …") should name the lock-checked store opener: the flock is re-asserted, then open, migrate and recover.
- Line 6 (`run_job` "takes one claimed job …") should say it now takes the claim handle.
- Line 4 (enqueue "resolves … the way B1's /internal/translate does") should name the shared `resolve_translatable_video`.

**Depends on it.** Nothing.

**Risk.** None.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="imports (lines 41-48)">
**What changes.**
- Line 44 becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat`. The six removed functions, `ensure_subtitles_schema`, `recover_translate_jobs` and `store_ready_subtitles` drop out. `connect_subtitles_db` is still needed by `heartbeat_loop`.
- Line 47 drops `SOURCE_INSTANCE` and adds `resolve_translatable_video`.
- Line 48, `from handlers.video import fetch_video_row`, becomes unused once `resolve_video` delegates. Remove it.
- Line 43: `list_active_denied_hosts` becomes unused. `normalize_host` stays for `command_enqueue`.
- Update the comment at 35, which says "api/ is for server_config, handlers.video.fetch_video_row and the route's fetch_instance_track and constants".
- `fcntl` (14) and `sqlite3` (22) are still used.

**Depends on it.**
- `_worker()` in `test_translate_worker.py:254-259` and STALL_DRIVER (212-220) both exec the module, so an ImportError fails every worker test.

**Risk.** Medium, since one bad import fails the whole module. Lint-level only otherwise.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="JobTakenOver docstring (lines 87-88)">
**What changes.** Replace "B1's route replaced the running row" with the real writer: the Engine state route's instance-track store (`store_ready_subtitles`), racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. The class itself stays; removing it is out of scope.

**Depends on it.** `translate_audio`, `generate` (new raise) and `run_job`.

**Risk.** None.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="resolve_video (lines 95-112)">
**What changes.**
- The signature `(whitelist_path, video_id, host, max_duration)` stays, because tests monkeypatch it with a 4-argument stand-in at `test_translate_worker.py:661` and at 1102-1103 and 1129-1130.
- Kept: the `connect_readonly_db` connection, `PRAGMA busy_timeout = 30000` and the close in `finally`.
- The body calls `resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)`. The refusal `missing host` maps to `not in whitelist`; the others pass through. The duration bound stays after the row check, with its text `duration {d}s over {m}s`.

**Depends on it.** `command_enqueue`, `generate` and these tests:
- the enqueue refusals table (`test_translate_worker.py:136-138`);
- the claim refusals (348-349);
- the stall test's expected `failed`/`not in whitelist` (1283);
- the whitelist-at-claim tests (1063-1091), which need `OperationalError` texts to come out unchanged so the WhitelistBusy classification in `generate` still applies.

**Risk.** Medium.
- `connect_readonly_db` raising on a deleted file (`unable to open`) must still happen before `resolve_translatable_video`, as today.
- The duration check must stay on the returned row dict.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="command_enqueue (lines 115-150)">
**What changes.** Lines 131-135 (mkdir, connect, ensure) become `conn = open_subtitles_db(args.subtitles_db)` inside the existing `try … except sqlite3.Error`, with `enqueue_translate_job` and the close in `finally`. Output lines and exit codes are unchanged.

**Depends on it.** The enqueue CLI tests (`test_translate_worker.py:763+`), which run the script as a subprocess, and `DEPLOYMENT.md:281-291`.

**Risk.** Low. An `OSError` from mkdir is not a `sqlite3.Error`, so it still propagates uncaught. Today it is raised outside the try, so the behaviour is the same. The structure needs care so that `conn` is defined before the `finally` close.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="translate_audio (lines 346-389)">
**What changes.** The `conn` and `claim` parameters are replaced by the handle, e.g. `translate_audio(job, pipe, runner, max_chunk, stop, progress)`. The three conditional writes become handle methods:
- 372: already_english, with `language, now_ms()`;
- 378: running cues, with `cues, language`;
- 387: end ready, with `cues, now_ms()`.

Each still raises `JobTakenOver` on False. Control flow is unchanged.

**Depends on it.** `generate`, and the pipeline tests: 947-963 (running cues per chunk, observed through the `cues_writes` trigger at 509-512), 966-976, 979-1001 and 1033-1050 (B1 takeover mid-job).

**Risk.** Medium. The order "already_english written before any cue" and "running cues only when `new` is non-empty" must stay exactly as it is.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="generate (lines 392-432)">
**What changes.**
- The signature drops `conn`; `claim` becomes the handle.
- Line 395 becomes `resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)`.
- Lines 407-408 (the unconditional upsert, then the `mark_translate_finished` stamp) become a single handle call to the instance-track end with `fetched[0], fetched[1], now_ms()`. If it returns False, raise `JobTakenOver`. If True, return `"ready from the instance track"`.
- Line 430 passes the handle to `translate_audio`.
- The docstring ("AC3 for one claim (video_id, instance_domain, target_language, started_at)") must name the handle.
- The `OperationalError` to `WhitelistBusy` mapping is unchanged.

**Depends on it.**
- `test_translate_worker.py:1016-1030`: the instance holds an English track, which must end ready/instance with `cues_json == CUES`, `track_text == TRACK` and `finished_at` within the window. It should pass unchanged.
- `run_job`'s takeover log line.

**Risk.** High. This is the one approved behaviour change: after a takeover, the worker no longer overwrites the Engine's row. No existing test covers the lost-claim instance path. The plan's new store test covers the method; nothing yet drives `generate` on a taken-over row. The UPDATE must also leave `detected_language`, `error`, `attempts`, `queued_at` and `started_at` untouched.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="run_job (lines 435-460)">
**What changes.**
- The signature drops `conn`: `run_job(job, args, runner, stop, progress) -> bool`. Line 437's tuple build is deleted.
- Log lines use `job.video_id, job.instance_domain` in place of `*claim[:2]`, with the texts unchanged.
- `requeue_translate_job(conn, *claim)` (442, 446) becomes `job.requeue()`.
- `finish_translate_failed(...)` (452, 459) becomes the handle's end-failed method. Return values are still ignored.
- The docstring's "a row B1's route took over is left as B1 wrote it" must name the real writer.

**Depends on it.**
- `serve` (line 496).
- `Rig.run` (`test_translate_worker.py:554`) and the fetch-reason test (925), which call it with `conn` first.
- `_run_broken` (640-649) and the whitelist tests that read its bool.

**Risk.** Medium. A signature mismatch fails every pipeline test. The bool contract (True only for WhitelistBusy) must survive.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="serve (lines 479-502): not named by the plan">
**What changes.**
- Line 495's log uses `job["video_id"], job["instance_domain"], job["attempts"]` and must switch to attributes. That breaks at runtime with the handle, and the plan does not list it.
- Line 496 becomes `run_job(job, args, runner, stop, progress)`.
- The signature `serve(conn, args, runner, stop, progress)` stays, because it still claims on `conn`. The tests call it as `rig.worker.serve(rig.conn, …)` at `test_translate_worker.py:1111` and 1136.

**Depends on it.**
- `command_run`;
- the back-off tests at 1097-1163;
- the subprocess stall and heartbeat tests, which claim through serve.

**Risk.** High if missed. Every claimed job would raise TypeError at the log line. Inside serve that exception is not caught, so the worker process would die.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="heartbeat_loop (lines 463-476)">
**What changes.** Nothing. It keeps `connect_subtitles_db`, per the plan.

**Depends on it.** The heartbeat and stall subprocess tests (1200-1294).

**Risk.** None. The beat thread starts only after the main thread's opener has migrated the file, so the table exists.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="command_run (lines 511-549)">
**What changes.**
- Its own LOCK_NB acquire, the `another worker holds` log line and exit 6 (517-525) stay first.
- Lines 531-537 (mkdir, connect, ensure, recover) become `conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())`, followed by the same `started pid=… recovered requeued=… failed=…` log line.
- The try/finally must still close `conn` and join the beat. `conn` is now bound only once the opener returns, so the `finally` that closes it must start after that point. See the gap in the `open_translate_worker_store` entry.
- The docstring ("then schema, recovery, …") should name the opener.

**Depends on it.**
- The held-lock test (1169-1197): exits 6, writes nothing, leaves a B1 file byte-identical, no sidecars. It is protected because `command_run`'s own flock fails first.
- The heartbeat and stall tests.
- The `TRANSLATE_WORKER.md` start-order step 5 and `DEPLOYMENT.md:271`.

**Risk.** Medium-high. Wrong try/finally placement either leaks the connection or raises NameError in `finally`. `lock_fd` must remain owned and closed by `command_run` (line 547).
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="exception classes JobFailed/JobStopped/WhitelistBusy, AudioPipe, WhisperRunner, chunk helpers, exit codes, parse_args">
**What changes.** Nothing.

**Depends on it.** Existing tests.

**Risk.** None. Listed so the next step can confirm exit codes 0-6 and the CLI flags are untouched.
</impact>
<impact path="tests/active/test_subtitles.py" element="module docstring (lines 1-24)">
**What changes.**
- Line 12 (concurrent writers) names `claim_translate_job` "which must hand back that key", `store_running_cues` and `finish_translate_ready`. These become handle methods.
- Line 14 names `connect_subtitles_db` + `ensure_subtitles_schema`.
- Line 17 names `recover_translate_jobs`, which now runs through the lock-taking opener.
- New bullets are needed for the handle-method takeover test, the instance-track end, both openers and the flock tie.

**Depends on it.** Nothing.

**Risk.** None.
</impact>
<impact path="tests/active/test_subtitles.py" element="WORKER_SCRIPT subprocess string (lines 115-147)">
**What changes.**
- The import at 119 drops `finish_translate_ready` and `store_running_cues`.
- 133-141 use `job.video_id` and `job.instance_domain`, then call the running-cues and end-ready methods on `job`.
- Line 135's `tuple(job)` in the SystemExit message must change, because a dataclass is not iterable.

**Depends on it.** `test_an_engine_and_a_worker_writing_one_file_at_once…` (282-323) under ENGINE_PY.

**Risk.** Medium. This code lives in a string, so a mistake shows up only as a non-zero subprocess exit, and grep for imports does not find it.
</impact>
<impact path="tests/active/test_subtitles.py" element="claim test (lines 326-343)">
**What changes.** Line 340 reads `job["video_id"]` and the other fields by subscript. It switches to attributes.

**Depends on it.** Nothing else.

**Risk.** Low.
</impact>
<impact path="tests/active/test_subtitles.py" element="recovery test (lines 346-378)">
**What changes.** `recover_translate_jobs` is private now, so each of the two recover calls (366, 372) goes through `open_translate_worker_store(path, lock_fd, 9000/9500)`, with the test holding a flock on a tmp lock file. Each call returns a new connection, which must be closed. `first["video_id"]` (364) and `row["video_id"]` (370) switch to attributes.

**Depends on it.** Nothing else.

**Risk.** Medium.
- Assertions must stay `(1, 0)` and `(2, 1)` with the bystander snapshot.
- The test's own `conn` stays open alongside the opener's connection. That is fine in WAL.
- The opener's migration runs again each time; it is idempotent.
</impact>
<impact path="tests/active/test_subtitles.py" element="fetch_subtitle_state test (lines 387-400)">
**What changes.** Line 388 drops `store_running_cues` from the import. Line 394 keeps the handle instead of `["started_at"]`. Line 395 calls the handle's running-cues method.

**Depends on it.** Nothing.

**Risk.** Low.
</impact>
<impact path="tests/active/test_subtitles.py" element="new tests (plan)">
**What changes.** New tests:
- **Handle takeover (parametrised over the six methods):** after a `store_ready_subtitles` takeover, each returns False and the row is byte-identical. The `_snapshot` helper (205-213) suits this.
- **Instance-track end while the claim holds:** state ready, source instance, `track_text`, compact `cues_json`, `fetched_at == finished_at`, other job columns unchanged.
- **`open_subtitles_db`:** on a fresh nested path (parent created) and on a B1-era file (reuse `_b1_file`).
- **`open_translate_worker_store`:** a second open file description holding the lock makes it raise `BlockingIOError` and leaves the file absent. With the lock held, recovery runs.

**Depends on it.** `tests/config.json` group `test_subtitles.py`, which lists only `subtitles.py`.

**Risk.** Low. For the flock test, the second `os.open` must be a separate open file description: a separate `os.open` in the same process, not `os.dup`.
</impact>
<impact path="tests/active/test_internal_translate.py" element="module docstring and _subtitles_db helper (lines 19, 418-424)">
**What changes.** Line 19 says the store is "opened with `connect_subtitles_db` and `ensure_subtitles_schema`, as server.py does", and `_subtitles_db`'s docstring says "as server.py opens it at startup". Both go stale. Either switch the helper to `open_subtitles_db`, or reword both. This is optional; the plan does not list it.

**Depends on it.** Every route test, and `test_source_fetch.py:25`, which imports helpers from this module but not `_subtitles_db`.

**Risk.** Low.
</impact>
<impact path="tests/active/test_internal_translate.py" element="_claimed and _seed (lines 605-631)">
**What changes.**
- `_claimed` returns the handle instead of `["started_at"]`.
- `_seed` drops `finish_translate_already_english`, `finish_translate_failed` and `store_running_cues` from its import (615), and calls the handle methods at 625, 627 and 629.
- `store_ready_subtitles` and `enqueue_translate_job` stay.

**Depends on it.**
- BRANCHES tests (713-740), REFUSED_ROWS (797-815) and the "stored key answers its state" enqueue test (872-883).
- `delete_me` and `tests/tmp` probes import `_seed` (e.g. `probe_50_phase1_rows.py`). They are stale.

**Risk.** Medium. Every stored-state test runs through `_seed`.
</impact>
<impact path="tests/active/test_internal_translate.py" element="running-key tests (lines 753-794)">
**What changes.**
- Lines 755 and 779 drop the removed imports.
- `started_at = _claimed(store)` becomes a handle.
- 759 becomes `job.<running cues>(RUNNING, "fr")`.
- 768 and 792 become `job.<end failed>("boom", NOW)`.

**Depends on it.** Nothing else.

**Risk.** Low.
</impact>
<impact path="tests/active/test_internal_translate.py" element="new closed-store track-store log test (plan)">
**What changes.** A new test: a server with `subtitles_db = None` and an instance holding an English track answers `ready` and logs the new info line once.

**Depends on it.** The `_store_cues` wording.

**Risk.** Low. Existing closed-store tests (699-710, 844-856) use no-track instances and stay green.
</impact>
<impact path="tests/active/test_source_fetch.py" element="import from test_internal_translate (line 25)">
**What changes.** Nothing, as long as `test_internal_translate`'s module-level names CHUNK, HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, WITHIN_CAP, Clock, Response, ScriptedInstance and `_body` keep importing.

**Depends on it.** All of `test_source_fetch`.

**Risk.** Low. A module-level import error in `test_internal_translate` would break this file too.
</impact>
<impact path="tests/active/test_translate_worker.py" element="module docstring (lines 1-50)">
**What changes.**
- Line 10 gives the signature `run_job(conn, job, args, runner, stop, progress)`, which becomes `run_job(job, …)`.
- Line 35 names `Rig.run`.
- Optionally add the lost-claim instance-track behaviour.

**Depends on it.** Nothing.

**Risk.** None.
</impact>
<impact path="tests/active/test_translate_worker.py" element="Rig.claim and Rig.run (lines 538-554)">
**What changes.**
- 544 reads `self.job["video_id"]` and the other fields by subscript, and switches to attributes.
- 554 becomes `self.worker.run_job(self.job, args, runner, …)`.

**Depends on it.** Every pipeline, bounds and whitelist-at-claim test through `rig.run`/`rig.claim`.

**Risk.** Medium. A miss fails most of the file.
</impact>
<impact path="tests/active/test_translate_worker.py" element="fetch-reason test (lines 905-935)">
**What changes.** Line 925 becomes `worker.run_job(job, args, UnreachedRunner(), …)`. The connection opened at 912-913 is still needed to claim and to close.

**Depends on it.** Nothing.

**Risk.** Low.
</impact>
<impact path="tests/active/test_translate_worker.py" element="instance-track and takeover tests (lines 1016-1050)">
**What changes.** These should pass unchanged in their assertions.
- 1016: ready/instance, CUES, TRACK, `finished_at` within the window.
- 1033: the B1 takeover mid-job leaves the row untouched. This exercises the running-cues method returning False.

**Depends on it.** `generate`'s new single call, and the handle.

**Risk.** Medium. These are the guards that `fetched_at`/`finished_at` and the encoding still match. No test drives `generate` through a takeover that lands before the instance-track end. If the next step wants that path pinned, it is a candidate.
</impact>
<impact path="tests/active/test_translate_worker.py" element="serve back-off tests, service subprocess tests, enqueue CLI tests (lines 763-905, 1097-1294)">
**What changes.** Nothing in the tests:
- `serve` keeps `(conn, …)`;
- the subprocess tests run the real `command_run` and `command_enqueue`;
- `resolve_video` keeps its 4-argument signature for `_recording`.

**Depends on it.** `serve`'s attribute access, `command_run`'s opener call and `command_enqueue`'s opener.

**Risk.** Medium. These are the regression net for `command_run`. The held-lock test proves nothing is created when the lock is refused. The heartbeat test proves the opener plus recovery leave a working store.
</impact>
<impact path="tests/config.json" element="test_groups for subtitles.py, internal_translate.py, translate-worker.py, server.py">
**What changes.** Nothing.
- `test_subtitles.py` maps only `subtitles.py`.
- `test_internal_translate.py` and `test_translate_worker.py` map all three code files.
- `server.py` is also mapped by `test_similar.py`, `test_server_config.py`, `test_internal_events.py` and `test_random_cache.py`, so the `server.py` edit pulls those Engine-start suites into the run.

**Depends on it.** The test runner's group selection.

**Risk.** Low. Worth knowing that the build's targeted runs will include those suites.
</impact>
<impact path="tests/tmp/probe_53_draft_translate_worker.py" element="stale probes in tests/tmp (probe_45_*, probe_50_phase1_rows.py, probe_53_* (6 files), probe_green.py, probe_phase2_worker_cli.py, probe_race.py, probe_53_c1_answers.py)">
**What changes.** Nothing. The plan leaves them alone. They import or call removed functions (`claim_translate_job` subscripts, `finish_translate_*`, `store_running_cues`, `recover_translate_jobs`, `run_job(conn, …)`) and will break if run.

**Depends on it.** Nothing in the active suite.

**Risk.** None for the active suite.
</impact>
<impact path="delete_me/test_53_source_instance_fetch_adapter_phase2.py" element="stale delete_me copies (test_53_* and *.bak-harvest53-58-* of internal_translate.py, translate-worker.py, video.py)">
**What changes.** Nothing. They name removed functions and `SOURCE_INSTANCE` in the route.

**Depends on it.** Nothing.

**Risk.** None. They are out of the active suite.
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="§ Run: Start-up Order step 5 (line 72), § Job Pipeline step 2 (line 90), § Stop, Crash and Recovery 'Crash' (line 147), § Takeover (line 151), § Enqueue (line 49), intro (line 13)">
**What changes.**
- Line 72: "Open `subtitles.db`, run `ensure_subtitles_schema`, then crash recovery" becomes: the lock-checked store opener re-asserts the flock, then creates the directory, opens, migrates and recovers, and the counts are logged.
- Line 90: "If there is one, store it `ready` with source `instance` and the job is done" must add "while the claim holds; otherwise the job is taken over and nothing is written".
- Line 147: "under the lock" can name the enforcement, since recovery is reachable only through the lock-checked opener.
- Line 151: "once B1 has written" can be reworded, and the instance-track end should be included among the conditional writes. The plan says to update this section only where it names removed functions. It names none, so this is optional.
- Line 49: "resolved as B1 does" can name `resolve_translatable_video`.
- New text on the claim handle and its methods.

**Depends on it.** `engine/server/README.md:30` and `DEPLOYMENT.md:230` link here.

**Risk.** Documentation only.
</impact>
<impact path="engine/server/README.md" element="§ Translate worker and its store contract (lines 29-36)">
**What changes.**
- Line 32 ("The store functions in `data/subtitles.py` are the contract") gains: `open_subtitles_db` as the single opener; `claim_translate_job` returning a `TranslateJob` handle whose six methods each match only while the row is `running` with the claim's `started_at` and return False once taken over; `open_translate_worker_store` as the only recovery path, under the flock.
- Line 34 ("or `instance` when the instance gained an English track before the claim") stays true, and could add "while the claim holds".

**Depends on it.** `TRANSLATE_WORKER.md:13` refers to this README for the store functions.

**Risk.** Documentation only.
</impact>
<impact path="engine/server/README.md" element="/internal/translate 'Checks before any fetch' bullet (line 17): not in the plan's doc list">
**What changes.** It says "the video resolves as on `/api/video` (`resolve_video_row`, so the error-count threshold applies)". The route no longer calls `resolve_video_row`, so the text must name `resolve_translatable_video`. That function still uses `fetch_video_row` with `video_error_threshold`, so the threshold claim stays true. The plan's docs list names only the store-contract section, so this would be missed.

**Depends on it.** Readers of the Engine API docs.

**Risk.** Documentation only, but the text would be factually stale.
</impact>
<impact path="engine/server/README.md" element="/internal/translate Cache bullet (line 19) and Notes start-up bullet (line 45)">
**What changes.**
- Line 19 ends "a store error is logged and the answer stays `ready`". A closed store now also logs an info line, and this could say so.
- Line 45 ("at start opens `DEFAULT_SUBTITLES_DB_PATH` …, creating the file when missing") should say the parent directory is created too.

**Depends on it.** Readers of the Engine docs.

**Risk.** Documentation only.
</impact>
<impact path="CONTEXT.md" element="Instance caption track (line 19) and Claim (line 22) glossary entries">
**What changes.** Probably none.
- Line 22 already says the worker "drops the job without writing anything further" on a takeover, which is now true for the instance-track end too.
- Line 19 ("The translate worker also stores one, with source `instance`, when it finds the track on claiming a job") could add "while its claim holds". This is optional; the plan says no change unless the handle wording requires it.

**Depends on it.** Glossary readers.

**Risk.** None.
</impact>
<impact path="DEPLOYMENT.md" element="subtitles.db paragraph (line 98) and run flag table (line 271)">
**What changes.** Probably none.
- Line 271 ("exits 6 without opening `subtitles.db`") stays true.
- Line 98 names `[translate] cache write failed` for a locked write. The closed-store info line occurs only during shutdown, so it is optional here.

**Depends on it.** Operators.

**Risk.** None.
</impact>
<impact path="docs/project/issues/54-translate-job-handle.md" element="Status line and archive move">
**What changes.** At delivery, per `docs/project/triage-labels.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. Issue 57 is already `wontfix` and folded in, so it needs no change. Issue 56 (`56-split-translate-worker.md`) depends on 54's handle and may want a note.

**Depends on it.** The issue tracker.

**Risk.** None. This is a tracker step, probably outside this build step.
</impact>
</impacts>


## Documentation to update

- [ ] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - - **Start-up Order step 5 (line 72):** replace `ensure_subtitles_schema` plus recovery with the lock-checked store opener: flock re-assert, mkdir, open, migrate, recover, then log the counts.
- **Job Pipeline step 2 (line 90):** the instance track is stored ready/instance only while the claim holds; otherwise the job is taken over and nothing is written.
- **New text:** the claim handle (`TranslateJob`), its six methods, each returning False after a takeover.
- **Enqueue (line 49):** optionally name the shared `resolve_translatable_video`.
- **Crash bullet (line 147):** recovery is reachable only through the lock-checked opener.
- **§ Takeover (line 151):** touch only if wording requires; it names no removed function.
- [ ] `engine/server/README.md` - - **§ "Translate worker and its store contract" (lines 29-36):**
  - `open_subtitles_db` as the single opener;
  - `claim_translate_job` returning the `TranslateJob` handle with its claim-conditional methods;
  - `open_translate_worker_store`, with recovery only under the flock.
- **Line 17:** replace `resolve_video_row` with `resolve_translatable_video`. The threshold and denylist still apply.
- **Line 19:** mention the closed-store info log line.
- **Notes, line 45:** the Engine start now also creates the parent directory of `DEFAULT_SUBTITLES_DB_PATH`.
- [ ] `engine/server/data/subtitles.py` - Module docstring and docstrings to update:
- `claim_translate_job` (returns a handle);
- `_update_claim` and the handle (name the real takeover writer, not "B1's route");
- `store_ready_subtitles` (shared encoder);
- the two new openers (flock re-assert semantics, including that it acquires the lock on an unlocked fd);
- `_recover_translate_jobs`.
- [ ] `engine/server/api/handlers/internal_translate.py` - - **Module docstring:** the shared resolve, and the closed-store log line.
- **`VIDEO_NOT_FOUND` comment (line 34):** it no longer comes from `resolve_video_row`.
- **Docstrings:** `_resolve_translate_key`, `_store_cues`, the new `_subtitles_store` and `resolve_translatable_video`.
- [ ] `engine/server/db/jobs/translate-worker.py` - - **Module docstring (lines 4, 6, 8):** the shared resolve, the handle, and the lock-checked opener in the start order.
- **`JobTakenOver` docstring:** the real writer.
- **`run_job`, `generate` and `command_run` docstrings:** update to match.
- **Comment at line 35:** about what `api/` is on the path for.
- [ ] `engine/server/api/server.py` - The comment at line 370 ("After the mkdir above (the default lives in the same directory)…") goes partly stale, because the opener creates its own parent. Keep the `prepare_trending_override` ordering reason.
- [ ] `CONTEXT.md` - Optional: in "Instance caption track" (line 19), the worker stores the track only while its claim holds. "Claim" (line 22) already matches.
- [ ] `tests/active/test_subtitles.py` - Module docstring lines 12, 14 and 17 name removed or renamed functions. Add bullets for the new handle, opener and flock tests.
- [ ] `tests/active/test_translate_worker.py` - The docstring's `run_job(conn, job, …)` signature (line 10) becomes `run_job(job, …)`.
- [ ] `tests/active/test_internal_translate.py` - Docstring line 19 and the `_subtitles_db` helper docstring say the store is opened "as server.py does" with `connect`+`ensure`. Reword, or switch the helper to `open_subtitles_db`.

## Implementation plan

## Draft implementation: translate job handle (issue 54, folds in 57)

I read all three code files, `server.py:340-379`, `handlers/video.py` (`fetch_video_row` and `resolve_video_row`) and the test call sites the impacts name. Each item below gives the code as it should land, in the style of the file it goes into: one-line docstrings, one statement per line, no softwrap.

### What the build has to test (worked out first)

1. **Six handle methods after a takeover.** Each returns `False` and leaves the row byte-identical, checked with `_snapshot`.
2. **Instance-track end while the claim holds.** The row becomes ready/instance with track text and compact cues, `fetched_at == finished_at`, and the other job columns are unchanged.
3. **Instance-track end after a lost claim, driven through `generate`.** The worker leaves the Engine's row as it is and logs the takeover line. This is the one approved behaviour change, and no existing test reaches it, so it gets a new worker test.
4. **`open_subtitles_db`.** On a fresh nested path it creates the directory and the full schema in WAL mode. On a B1-era file it adds the job columns.
5. **`open_translate_worker_store`.** When a second open file description holds the flock, it raises `BlockingIOError` and the subtitles file is absent. With the lock held, recovery returns `(1, 0)` and then `(2, 1)` as today.
6. **Route.** A closed store with an instance track answers `ready` and writes the new info line once. The other closed-store answers are unchanged.
7. **Resolve.** `missing host`, `not in whitelist` and `host denied` (uppercase stored deny) are refused. Route 400/404 and worker texts are unchanged (existing tables).
8. **Regression net.** The three active files stay green, plus the Engine-start groups pulled in by `server.py`.

### Module map

| File | Change |
|---|---|
| `engine/server/data/subtitles.py` | Adds `SOURCE_INSTANCE`, `_instance_cues_text`, `TranslateJob` (6 methods), `open_subtitles_db` and `open_translate_worker_store`. `claim_translate_job` returns the handle. `recover_translate_jobs` becomes `_recover_translate_jobs`. `_update_claim` takes the handle. The 5 per-claim functions and `mark_translate_finished` are deleted. |
| `engine/server/api/handlers/internal_translate.py` | Adds `resolve_translatable_video` and `_subtitles_store`. Three sites now go through the helper. `SOURCE_INSTANCE` is imported. `resolve_video_row` is dropped. |
| `engine/server/db/jobs/translate-worker.py` | Handle threaded through `run_job`, `generate` and `translate_audio`. `serve` uses attributes. `resolve_video` delegates. Both openers are used. Imports trimmed. |
| `engine/server/api/server.py` | One import and one call. |
| tests and docs | As listed below. |

No new modules and no new dependency. `fcntl` is imported inside one function only.

---

### `engine/server/data/subtitles.py`

**Imports**

```python
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
```

**Constants:** add beside `SOURCE_WHISPER`, byte-identical to the route's old value.

```python
SOURCE_WHISPER = "whisper"
SOURCE_INSTANCE = "instance"
```

**Opener:** goes after `ensure_subtitles_schema`.

```python
def open_subtitles_db(path: Path) -> sqlite3.Connection:
    """The one store opener for the Engine and the worker: create the parent directory, connect in WAL (connect_subtitles_db's busy timeout and lock retry), migrate (ensure_subtitles_schema); the connection is closed if the migration raises."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_subtitles_db(path)
    try:
        ensure_subtitles_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn
```

**Shared instance-track encoder.** `store_ready_subtitles` switches to it. Its SQL and signature are unchanged. Its docstring gains: "the cues are encoded by `_instance_cues_text`, as the handle's instance-track end encodes them".

```python
def _instance_cues_text(cues: list[dict[str, Any]]) -> str:
    """Compact JSON for an instance track's cues_json, shared by store_ready_subtitles and TranslateJob.end_ready_from_instance so the two writers encode alike; NaN allowed, unlike _cues_text."""
    return json.dumps(cues, ensure_ascii=False, separators=(",", ":"))
```

In `store_ready_subtitles`, the last tuple element becomes `_instance_cues_text(cues)`. `_cues_text` is unchanged.

**Handle and claim**

```python
@dataclass(frozen=True)
class TranslateJob:
    """One claim on a running job: the connection it was claimed on, its key, its started_at and attempts. Every method is one conditional UPDATE that matches only while the row is running with this started_at, and answers whether the claim still held; False means the Engine state route's instance-track store (store_ready_subtitles) replaced the row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did."""

    conn: sqlite3.Connection = field(repr=False, compare=False)
    video_id: str
    instance_domain: str
    target_language: str
    started_at: int
    attempts: int

    def write_running_cues(self, cues: list[dict[str, Any]], detected_language: str) -> bool:
        """Rewrite the running job's whole cues_json after a chunk (AC4)."""
        return _update_claim(self, "cues_json = ?, detected_language = ?", (_cues_text(cues), detected_language))

    def end_ready(self, cues: list[dict[str, Any]], finished_at: int) -> bool:
        """End ready with the full, start-sorted cue list; fetched_at is set so the ready reader sees a normal ready row."""
        return _update_claim(self, "state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?", (_cues_text(cues), finished_at, finished_at))

    def end_already_english(self, detected_language: str, finished_at: int) -> bool:
        """End already_english; English is detected before any cue is written, so cues_json was never set."""
        return _update_claim(self, "state = 'already_english', detected_language = ?, finished_at = ?", (detected_language, finished_at))

    def end_failed(self, error: str, finished_at: int) -> bool:
        """End failed with its error text; partial cues stay in cues_json, unread because a failed row's cues are never served."""
        return _update_claim(self, "state = 'failed', error = ?, finished_at = ?", (error, finished_at))

    def requeue(self) -> bool:
        """Put the job back without spending its claim (a stop mid-job, or whitelist.db unavailable at claim); queued_at is kept, so it stays at the head of the queue."""
        return _update_claim(self, "state = 'queued', attempts = attempts - 1", ())

    def end_ready_from_instance(self, track_text: str, cues: list[dict[str, Any]], finished_at: int) -> bool:
        """End ready with the instance's English track, source instance, one timestamp for fetched_at and finished_at; every other job column is left as it is."""
        return _update_claim(self, "state = 'ready', source = ?, track_text = ?, cues_json = ?, fetched_at = ?, finished_at = ?", (SOURCE_INSTANCE, track_text, _instance_cues_text(cues), finished_at, finished_at))


def claim_translate_job(conn: sqlite3.Connection, target_language: str, started_at: int) -> TranslateJob | None:
    """Flip the oldest queued job to running, in one short transaction; its TranslateJob handle on conn, or None."""
    with _immediate(conn):
        row = conn.execute("SELECT video_id, instance_domain FROM subtitles WHERE state = 'queued' AND target_language = ? ORDER BY queued_at, rowid LIMIT 1", (target_language,)).fetchone()
        if row is None:
            return None
        key = (row[0], row[1], target_language)
        conn.execute(f"UPDATE subtitles SET state = 'running', started_at = ?, attempts = attempts + 1 WHERE {_KEY}", (started_at, *key))
        claimed = conn.execute(f"SELECT video_id, instance_domain, started_at, attempts FROM subtitles WHERE {_KEY}", key).fetchone()
    return TranslateJob(conn, claimed["video_id"], claimed["instance_domain"], target_language, claimed["started_at"], claimed["attempts"])


def _update_claim(job: TranslateJob, assignments: str, values: tuple[Any, ...]) -> bool:
    """One conditional UPDATE on job's running row, on the connection that claimed it; False (rowcount 0) once the state route's instance-track store, or an older blue/green Engine, replaced the row."""
    with job.conn:
        cursor = job.conn.execute(f"UPDATE subtitles SET {assignments} WHERE {_KEY} AND state = 'running' AND started_at = ?", (*values, job.video_id, job.instance_domain, job.target_language, job.started_at))
    return cursor.rowcount == 1
```

`TranslateJob` is defined before `claim_translate_job`. Python resolves `_update_claim` at call time, so its later position is fine.

**Decision on equality and repr.** `conn` is marked `repr=False, compare=False`. Two handles for the same claim then compare equal, and `repr` does not print a connection object. That costs one `field(...)`, which is already in stdlib `dataclasses`.

**SET strings:**
- the five existing methods: copied verbatim from the deleted functions, including `attempts = attempts - 1`;
- `end_ready_from_instance`: sets exactly the columns the upsert's `DO UPDATE` sets today (state, source, fetched_at, track_text, cues_json), plus `finished_at`, which `mark_translate_finished` set. `detected_language`, `error`, `attempts`, `queued_at` and `started_at` are untouched.

**Recovery and the worker opener**

```python
def _recover_translate_jobs(conn: sqlite3.Connection, finished_at: int) -> tuple[int, int]:
    """Requeue a running row once, fail it when found running a second time; (requeued, failed). Private: reached only through open_translate_worker_store, under the worker's flock."""
    # body unchanged: failed UPDATE first, then requeue, in one _immediate


def open_translate_worker_store(path: Path, lock_fd: int, finished_at: int) -> tuple[sqlite3.Connection, tuple[int, int]]:
    """The worker service's opener: re-assert the flock on lock_fd (LOCK_EX | LOCK_NB) before the file is touched, then open_subtitles_db and crash recovery; (conn, (requeued, failed)). On the descriptor that already holds the lock the re-assert is a no-op; on an unlocked descriptor it takes the lock; when another open file description holds it, BlockingIOError is raised and nothing is created. lock_fd stays the caller's to close."""
    import fcntl

    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    conn = open_subtitles_db(path)
    try:
        return conn, _recover_translate_jobs(conn, finished_at)
    except BaseException:
        conn.close()
        raise
```

This also closes the impact's gap: the connection is closed if recovery raises. The flock comes before `open_subtitles_db`, so a refused call creates no directory either.

**Deleted:** `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `mark_translate_finished`, and the public `recover_translate_jobs`.

**Unchanged:** `connect_subtitles_db`, `ensure_subtitles_schema`, `_immediate`, the fetchers, `enqueue_translate_job`, `write_translate_heartbeat`, `_KEY`, `MAX_CLAIMS`, `RECOVERY_ERROR`, `JOB_COLUMNS`.

**Module docstring, paragraph 2, replaced:**

> The Engine state route stores an instance's English track with store_ready_subtitles, an unconditional upsert to state 'ready', source 'instance'. Plan 49's translate worker adds the job states and the source 'whisper'; state and source stay plain TEXT. open_subtitles_db is the one opener (mkdir, WAL connect, migrate in place); open_translate_worker_store adds crash recovery and is the only way to run it, with the worker's flock re-asserted first. claim_translate_job hands back a TranslateJob whose six methods (running cues, ready, already_english, failed, requeue, ready from the instance track) each match only while the row is running with that claim's started_at, so the state route's upsert landing on a running row wins and every later job write is a no-op. A running job's cues are a whole-cues_json rewrite after each chunk, so fetch_ready_subtitles reads a ready row of either source unchanged, and the state route reads a running row's cues so far through fetch_subtitle_state. The file is in WAL mode: both blue/green Engines and the translate worker (claim, per-chunk rewrites, a heartbeat) write it.

---

### `engine/server/api/handlers/internal_translate.py`

**Imports**

```python
from contextlib import contextmanager
from typing import Any, Iterator
...
from data.subtitles import SOURCE_INSTANCE, enqueue_translate_job, fetch_subtitle_state, fetch_translate_heartbeat, store_ready_subtitles
...
from handlers.video import fetch_video_row
```

- The `SOURCE_INSTANCE = "instance"` line is deleted. The name still resolves as a module attribute through the import, so the stale probes keep working.
- The `VIDEO_NOT_FOUND` comment becomes: `# Answered for every refusal of resolve_translatable_video, so the route does not reveal which check failed; the body /api/video answers for an unknown video.`

**Shared resolve:** placed above `_generation_available`.

```python
def resolve_translatable_video(conn: sqlite3.Connection, video_id: str, host: str | None, error_threshold: int | None) -> tuple[dict[str, Any] | None, str | None]:
    """The whitelisted row and None, or None and the refusal: missing host (decided before any lookup, since fetch_video_row with no host matches the id on any host), not in whitelist (fetch_video_row with error_threshold), host denied (the row's normalised domain is actively denied). Shared by both /internal/translate routes and the translate worker; takes no lock and writes no response."""
    if not host:
        return None, "missing host"
    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)
    if row is None:
        return None, "not in whitelist"
    if normalize_host(row["instance_domain"]) in list_active_denied_hosts(conn):
        return None, "host denied"
    return row, None
```

The order is host, then row, then denylist. The denylist is read only when a row exists, so an `OperationalError` from `fetch_video_row` surfaces first with its own text, as the worker's busy/unopenable classification needs.

**Store access helper**

```python
@contextmanager
def _subtitles_store(server: Any) -> Iterator[sqlite3.Connection | None]:
    """Hold subtitles_db_lock for the whole body and yield subtitles_db, None when the store is closed; errors pass through to the caller's own handler."""
    with server.subtitles_db_lock:
        yield server.subtitles_db
```

**`_read_key`**

```python
    try:
        with _subtitles_store(server) as conn:
            if conn is None:
                return None, False
            return fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE), _generation_available(conn)
    except sqlite3.Error as exc:
        logging.warning("[translate] cache read failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
        return None, False
```

**`_store_cues`.** The docstring gains "a closed store (shutdown) stores nothing and is logged".

```python
    try:
        with _subtitles_store(server) as conn:
            if conn is None:
                logging.info("[translate] cache closed, track not stored video_id=%s host=%s", video_id, instance_domain)
                return
            store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())
    except sqlite3.Error as exc:
        logging.warning("[translate] cache write failed video_id=%s host=%s: %s", video_id, instance_domain, exc)
```

The new line starts `[translate] cache closed`, not `[translate] instance fetch failed`, so `_failed_fetches` and the NONE_CASES exact-list assertions cannot pick it up.

**`_resolve_translate_key`.** Body validation and the three 400s are byte-identical. The tail becomes:

```python
    host = normalize_host(raw_host)
    if host is None:
        respond_json(handler, 400, {"error": "Invalid host"})
        return None
    with server.db_lock:
        row, _ = resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)
    if row is None:
        respond_json(handler, 404, VIDEO_NOT_FOUND)
        return None
    # The row's own domain and canonical id, never the request's: the fetch goes to the video's instance and the store is keyed once per video.
    canonical_id = row["video_id"]
    return body, canonical_id, row["instance_domain"], row["video_uuid"] or canonical_id
```

There is one `db_lock` hold, which is not re-entered (the fake uses a plain `threading.Lock`). `resolve_video_row`'s unreachable `Missing video id` is not reintroduced.

**Enqueue**

```python
    try:
        # One lock hold, so availability cannot flip between the beat read and the enqueue.
        with _subtitles_store(server) as conn:
            outcome = enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if conn is not None and _generation_available(conn) else None
    except sqlite3.Error as exc:
        ...unchanged
```

**Module docstring**
- Paragraph 2: after "An unknown or denylisted video answers 404 …", add "(resolve_translatable_video, shared with the translate worker)". After "an instance track found then is stored ready over it", add "; with the store closed (shutdown) it is answered but not stored, and an info line says so".
- Paragraph 3: unchanged.

---

### `engine/server/db/jobs/translate-worker.py`

**Path comment and imports**

```python
# api/ is for server_config and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.
...
from data.db import connect_readonly_db
from data.moderation import normalize_host
from data.subtitles import TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat
from data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media
from data.time import now_ms
from handlers.internal_translate import TARGET_LANGUAGE, fetch_instance_track, resolve_translatable_video
```

The `handlers.video` import and `list_active_denied_hosts` are removed. `TranslateJob` is imported for annotations only.

**`JobTakenOver`**

```python
class JobTakenOver(Exception):
    """A claim-conditional write matched no row: the Engine state route's instance-track store (store_ready_subtitles) replaced the running row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did."""
```

**`resolve_video`.** The signature is unchanged. Tests monkeypatch it with four arguments.

```python
def resolve_video(whitelist_path: Path, video_id: str, host: str, max_duration: int) -> tuple[dict[str, Any] | None, str | None]:
    """The whitelisted row and None, or None and the refusal text: resolve_translatable_video with VIDEO_ERROR_THRESHOLD (a missing host reads as not in whitelist), then the stored-duration bound; NULL duration passes."""
    conn = connect_readonly_db(whitelist_path)
    try:
        # sqlite3's 5 s default is shorter than the updater merge's commit; past 30 s this raises, never reads as not-found.
        conn.execute("PRAGMA busy_timeout = 30000")
        row, refusal = resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)
    finally:
        conn.close()
    if refusal is not None:
        return None, "not in whitelist" if refusal == "missing host" else refusal
    duration = row["duration"]
    if isinstance(duration, int) and duration > max_duration:
        return None, f"duration {duration}s over {max_duration}s"
    return row, None
```

`connect_readonly_db` still raises before any query, for example `unable to open` on a deleted file.

**`command_enqueue`.** Replaces lines 131-141.

```python
    try:
        conn = open_subtitles_db(args.subtitles_db)
        try:
            outcome, state = enqueue_translate_job(conn, row["video_id"], row["instance_domain"], TARGET_LANGUAGE, args.cap, now_ms())
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"error: subtitles.db: {exc}")
        return EXIT_ERROR
```

An `OSError` from mkdir is not a `sqlite3.Error`, so it propagates as before.

**`translate_audio`.** The signature becomes `translate_audio(job: TranslateJob, pipe: AudioPipe, runner: Any, max_chunk: int, stop: threading.Event, progress: dict[str, float]) -> str`. Three lines change and nothing else:
- `if not job.end_already_english(language, now_ms()):`
- `if not job.write_running_cues(cues, language):`
- `if not job.end_ready(cues, now_ms()):`

**`generate`**

```python
def generate(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:
    """AC3 for one claim handle, each bound raising JobFailed before the next remote request, a locked or unopenable whitelist.db raising WhitelistBusy, a lost claim raising JobTakenOver; the end state written."""
    try:
        row, refusal = resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)
    ...unchanged
    fetched = fetch_instance_track(instance, video_key)
    if fetched is not None:
        if not job.end_ready_from_instance(fetched[0], fetched[1], now_ms()):
            raise JobTakenOver()
        return "ready from the instance track"
    ...unchanged
    try:
        return translate_audio(job, pipe, runner, args.max_chunk_seconds * SAMPLE_RATE, stop, progress)
    finally:
        pipe.close()
```

**`run_job`**

```python
def run_job(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:
    """Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or unopenable at claim; a row the Engine's instance-track store took over is left as that store wrote it. True only for the whitelist.db requeue."""
    where = (job.video_id, job.instance_domain)
    try:
        state = generate(job, args, runner, stop, progress)
        logging.info("[translate-worker] job %s video_id=%s host=%s", state, *where)
    except JobStopped:
        job.requeue()
        logging.info("[translate-worker] stopped mid-job, requeued video_id=%s host=%s", *where)
    except WhitelistBusy as exc:
        # The attempt is given back, so MAX_CLAIMS recovery never counts these cycles.
        job.requeue()
        logging.warning("[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s", *where, exc)
        return True
    except JobTakenOver:
        logging.info("[translate-worker] taken over by the instance track video_id=%s host=%s", *where)
    except JobFailed as exc:
        job.end_failed(str(exc), now_ms())
        logging.info("[translate-worker] job failed video_id=%s host=%s: %s", *where, exc)
    except Exception as exc:
        # A CUDA out-of-memory fails only this job; the model is dropped so the next job loads it afresh instead of retrying in a loop (AC7).
        if is_cuda_oom(exc):
            runner.unload()
        logging.exception("[translate-worker] job error video_id=%s host=%s", *where)
        job.end_failed(f"{type(exc).__name__}: {exc}", now_ms())
    return False
```

The log texts are unchanged. The results of requeue and end-failed are still ignored.

**`serve`.** Its signature keeps `conn`, which it claims on. Two lines change (one of them the miss the plan did not name):

```python
        logging.info("[translate-worker] claimed video_id=%s host=%s attempts=%s", job.video_id, job.instance_domain, job.attempts)
        if run_job(job, args, runner, stop, progress):
```

**`heartbeat_loop`:** unchanged (plain `connect_subtitles_db`).

**`command_run`.** Its own LOCK_NB, the `another worker holds` log line and exit 6 come first, as now. Then:

```python
    try:
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        progress = {"at": time.monotonic()}
        conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())
        beat: threading.Thread | None = None
        try:
            logging.info("[translate-worker] started pid=%s recovered requeued=%s failed=%s", os.getpid(), requeued, failed)
            beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)
            beat.start()
            serve(conn, args, WhisperRunner(), stop, progress)
        finally:
            stop.set()
            if beat is not None:
                beat.join(HEARTBEAT_SECONDS)
            conn.close()
    finally:
        os.close(lock_fd)
```

`conn` is bound before the inner `try`, so there is no NameError. The opener closes its own connection if migration or recovery fails. `lock_fd` stays owned and closed here. The docstring becomes: "… then the flock before subtitles.db is opened, so a refused second run writes nothing; then open_translate_worker_store (flock re-asserted, open, migrate, recover), the heartbeat thread and the claim loop until SIGTERM."

**Module docstring**
- Line 4: "resolves the video against whitelist.db with the route's resolve_translatable_video".
- Line 6: "run_job takes one claim handle (TranslateJob) through …".
- Line 8: "… flock (a refused second run exits 6 having written nothing), open_translate_worker_store (the flock re-asserted, then open, migrate and crash recovery), a heartbeat thread …".

---

### `engine/server/api/server.py`

- Line 106: `from data.subtitles import open_subtitles_db`
- Lines 370-372:

```python
    # After prepare_trending_override, so a rejected start creates nothing; the opener creates its own parent directory.
    subtitles_db = open_subtitles_db(subtitles_db_path)
```

---

### Tests

**`tests/active/test_subtitles.py`**
- **WORKER_SCRIPT:**
  - The import becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, write_translate_heartbeat`.
  - The check becomes `(job.video_id, job.instance_domain) != (key, host)`, and its message becomes `{None if job is None else (job.video_id, job.instance_domain)!r}`.
  - The writes become `job.write_running_cues(first, "fr")` and `job.end_ready(full, 1700000200000 + n)`, with messages naming the methods.
  - The script keeps `connect_subtitles_db`+`ensure_subtitles_schema`, so the race semantics are unchanged.
- **Claim test (line 340):** reads attributes: `(job.video_id, job.instance_domain, job.started_at, job.attempts)`.
- **Recovery test:**
  - It imports `claim_translate_job, open_translate_worker_store`.
  - It opens `lock_fd = os.open(tmp_path / "worker.lock", O_RDONLY|O_CREAT)` and `fcntl.flock(lock_fd, LOCK_EX)`.
  - Each recover call becomes `opened, counts = open_translate_worker_store(path, lock_fd, 9000)`, then `opened.close()`, then `assert tuple(counts) == (1, 0)` (and `(2, 1)` at 9500).
  - It reads `first.video_id`, `first.attempts` and `(row.video_id, row.attempts)`.
  - `os.close(lock_fd)` in a `finally`.
- **`fetch_subtitle_state` test:** `job = claim_translate_job(conn, "en", 2000)`, then `assert job.write_running_cues([...], "fr")`.
- **New `test_every_claim_write_after_an_instance_track_takeover_matches_nothing_and_reports_the_claim_lost`.** Parametrised over the six methods:

```python
CLAIM_WRITES = {
    "running cues": lambda job: job.write_running_cues([{"start": 1.0, "end": 2.0, "text": "x"}], "fr"),
    "ready": lambda job: job.end_ready([{"start": 1.0, "end": 2.0, "text": "x"}], 9000),
    "already_english": lambda job: job.end_already_english("en", 9000),
    "failed": lambda job: job.end_failed("boom", 9000),
    "requeue": lambda job: job.requeue(),
    "ready from instance": lambda job: job.end_ready_from_instance("WEBVTT x", [{"start": 1.0, "end": 2.0, "text": "x"}], 9000),
}
```

  The test enqueues and claims, then runs `store_ready_subtitles(conn, …, "instance", TRACK, CUES, 8000)` and takes a `_snapshot`. It asserts `write(job) is False` and that `_snapshot` is unchanged. A control runs the same write on a fresh claim without the takeover and asserts `True`, so that `False` is shown to be the takeover's doing.
- **New `test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp`:**
  - claim, then `job.write_running_cues(…, "fr")`, then `job.end_ready_from_instance("WEBVTT t", cues, 9000)` is True;
  - the row has state/source `ready`/`instance`, `track_text`, a compact `cues_json` with no space, and `fetched_at == finished_at == 9000`;
  - `detected_language == "fr"`, `error IS NULL`, `attempts == 1`, `queued_at` and `started_at` are unchanged;
  - `fetch_ready_subtitles` returns the cues.
- **New `test_open_subtitles_db_creates_a_missing_directory_and_the_full_schema_in_wal`:** on `tmp_path / "a" / "b" / "subtitles.db"`, the columns equal `ALL_COLUMNS`, the heartbeat table exists and the mode is `wal`.
- **New `test_open_subtitles_db_adds_the_job_columns_to_a_b1_file`:** reuses `_b1_file`; the columns equal `ALL_COLUMNS` and `_old_cues == B1_CUES`.
- **New `test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing`:**
  - `held = os.open(lock)` locked LOCK_EX; `mine = os.open(lock)` is a separate description, not `dup`;
  - `pytest.raises(BlockingIOError)` on `open_translate_worker_store(tmp_path / "sub" / "subtitles.db", mine, 1)`;
  - the file and its parent are absent;
  - control: after closing `held`, the same call succeeds on `mine` and the file exists.
- **Docstring.** Lines 12, 14 and 17 are reworded to the handle methods, the openers and `open_translate_worker_store`. New bullets cover the takeover, the instance end, the openers and the flock.

**`tests/active/test_internal_translate.py`**
- `_claimed` returns `claim_translate_job(store, "en", NOW - 1000)` with annotation `-> "TranslateJob"` and docstring "its claim handle".
- `_seed` imports `enqueue_translate_job, store_ready_subtitles` and calls `_claimed(store).write_running_cues(RUNNING, "fr")`, `.end_failed("boom", NOW - 500)` and `.end_already_english("en", NOW - 500)`.
- Lines 755-792:
  - `job = _claimed(store)`;
  - `assert job.write_running_cues(RUNNING, "fr")`;
  - `assert job.end_failed("boom", NOW)`;
  - the imports keep only `write_translate_heartbeat`.
- `_subtitles_db` switches to `open_subtitles_db(path)`, so the docstring "as server.py opens it" is true again. Line 19 of the module docstring is reworded to match.
- **New `test_a_closed_store_still_answers_an_instance_track_ready_and_logs_that_it_was_not_stored`:**
  - `server = _server(...)` with `subtitles_db = None` and `_instance(True)`;
  - the answer is `[[200, {"state": "ready", "cues": CUES, "available": False}]]`;
  - `caplog` has exactly one record starting `[translate] cache closed, track not stored`.
- **New resolve test** in `test_internal_translate.py`, three cases on the `whitelist` fixture DB:
  - `resolve_translatable_video(conn, VIDEO_ID, None, 0)` and the same with `""` return `(None, "missing host")`, even though the id exists;
  - the denied-host video returns `(None, "host denied")`;
  - an unknown id returns `(None, "not in whitelist")`;
  - the known video returns its row.

**`tests/active/test_translate_worker.py`**
- `Rig.claim` asserts on `(self.job.video_id, self.job.instance_domain, self.job.started_at, self.job.attempts)`.
- `Rig.run` calls `self.worker.run_job(self.job, args, runner, …)`.
- The fetch-reason test calls `worker.run_job(job, args, UnreachedRunner(), …)`.
- Docstring line 10 becomes `run_job(job, args, runner, stop, progress)`, where `job` is the claim handle.
- **New `test_an_instance_track_found_after_the_engine_took_the_row_over_writes_nothing_and_logs_the_takeover`:**
  - The test serves the English listing and track.
  - It wraps `worker.fetch_instance_track` through `monkeypatch.setattr(rig.worker, "fetch_instance_track", …)`. The wrapper calls the real function, then `store_ready_subtitles(b1, "v-1", HOST, "en", "instance", "WEBVTT engine", ENGINE_CUES, 1_700_000_000_000)`, snapshots `rig.row()` and returns the fetched value.
  - Assertions: `rig.row() == taken`, `caplog` has the `taken over by the instance track video_id=v-1 host=…` line, no `failed`, and `runner.transcribes == 0`.
  - This pins the approved behaviour change, which no existing test reaches. Today's code would fail it, because the upsert overwrites `track_text`.
- The existing English-track test at 1016 is unchanged and stays green: the cues decode to `CUES`, `track_text == TRACK`, and `finished_at` is now one `now_ms()` inside the window.

---

### Docs (settled list, as written)

**`TRANSLATE_WORKER.md`**
- Line 72, start-order step 5: "`open_translate_worker_store` re-asserts the flock on the held descriptor, then creates the directory, opens `subtitles.db` in WAL, migrates and runs crash recovery; the counts are logged."
- Line 90: "store it `ready` with source `instance` while the claim holds (`end_ready_from_instance`); if the Engine's store took the row over first, nothing is written and the job is taken over."
- Line 147: "under the lock: recovery is private to the store and reachable only through `open_translate_worker_store`."
- Line 49: "resolved by `resolve_translatable_video`, as the route does".
- A new short subsection, "The Claim Handle": `claim_translate_job` returns a `TranslateJob` holding its connection, with six methods. Each matches only while the row is `running` with the claim's `started_at` and returns `False` after a takeover. `run_job` raises `JobTakenOver` on a `False` result from running cues, ready, already_english or ready-from-instance.
- § Takeover: left as it is (it names no removed function).

**`engine/server/README.md`**
- §29-36: `open_subtitles_db` as the single opener; the `TranslateJob` handle and its methods; `open_translate_worker_store` as the only recovery path, under the flock.
- Line 17: `resolve_translatable_video` (`fetch_video_row` with the error threshold, then the denylist on the row's domain).
- Line 19: "with the store closed, an info line is logged and the answer stays `ready`".
- Line 45: "creating the file and its parent directory when missing". The Notes record that a custom path in a missing directory now starts.

**`CONTEXT.md` line 19:** add "while its claim holds".

---

### Check against the plan and the requirements (pass 1, converged)

| Requirement | Draft |
|---|---|
| Claim unchanged, returns handle or None | `claim_translate_job`: the same transaction, then a `TranslateJob` |
| Handle in `subtitles.py`, key, `started_at`, `attempts`, holds connection | frozen dataclass; `conn` with `repr=False, compare=False` |
| Six operations, the compare-and-set in each, one lost-claim report | six methods, all through `_update_claim`, all `bool` |
| No tuple outside the store; five functions and `mark_translate_finished` gone | deleted; the worker and tests use attributes and methods only |
| Instance end: one UPDATE, columns, NaN-allowing encoding, one timestamp, no-op when lost | `end_ready_from_instance` + `_instance_cues_text`; `generate` raises `JobTakenOver` on `False` |
| Takeover unchanged | `_store_cues` → `store_ready_subtitles`, unconditional |
| Docstrings name the real writer | `TranslateJob`, `_update_claim`, `JobTakenOver`, `run_job` |
| One opener; Engine, enqueue and run use it; heartbeat decided | `open_subtitles_db`; `server.py`, `command_enqueue`, via `open_translate_worker_store`; heartbeat keeps the plain connect |
| Recovery logic unchanged, unreachable without the flock, shown by a test | `_recover_translate_jobs` private; flock re-assert in the only caller; refusal test |
| One route helper; closed-store answers and error handling unchanged; beat and enqueue in one hold | `_subtitles_store`; three sites; one `with` in enqueue |
| Resolve: three refusals, order, both callers, route 400/404, worker texts | `resolve_translatable_video`; `missing host` mapped to `not in whitelist` in the worker |
| `run_job` without `conn`, `serve` attribute access | done; `serve` covered (the impact's miss) |
| Docs and docstrings | listed above |

Two small additions beyond the plan's list, both inside its stated decisions:
1. `open_translate_worker_store` closes the connection when recovery raises. This fixes the gap the impacts flagged.
2. One worker test drives `generate` through a takeover that lands before the instance-track end. It pins the approved behaviour change end to end.

Simplifications, named:
- `TranslateJob` is pinned to one connection. A handle cannot outlive or move off the connection that claimed it. Upgrade path: none needed until a second claimer exists.
- Stale probes in `tests/tmp/` and `delete_me/` that call the removed functions will break if run. This is accepted per the plan.

### Phases

#### Phase 1 - Claim handle [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam 1 is the store module, entered at rung 1 in tests/active/test_subtitles.py with its existing `_snapshot` harness. A parametrised test runs over the six TranslateJob methods (running cues, ready, already_english, failed, requeue, ready from instance). For each it enqueues, claims, takes the row over with `store_ready_subtitles(..., "instance", ...)` and snapshots, then asserts the method returns `False` and the snapshot is unchanged. A control runs the same method on a fresh claim with no takeover and asserts `True`, which shows the `False` comes from the takeover and not from a broken UPDATE. A second store test covers the held-claim control: `end_ready_from_instance` returns True and leaves state `ready`, source `instance`, the track_text, compact cues_json (no space) and `fetched_at == finished_at`, with detected_language, error, attempts, queued_at and started_at unchanged. Seam 2 is the worker's `run_job`/`generate`, entered through the existing `Rig` harness in tests/active/test_translate_worker.py with a served English listing and track. `fetch_instance_track` is wrapped so that, after the real fetch, it runs `store_ready_subtitles` with the Engine's track and snapshots the row. The test asserts the row equals that snapshot (Engine's track_text and cues kept), the `taken over by the instance track video_id=v-1 host=…` log line is present, no `failed` line is present and the runner made 0 transcribes. Today's code fails this because the upsert overwrites track_text. The existing English-instance-track test at :1016 stays green unchanged.

**Intent.** `claim_translate_job` in engine/server/data/subtitles.py returns a TranslateJob handle bound to its connection, and the worker writes every claim-conditional change through it, so once the Engine's instance-track store has replaced a running row, no handle write (including the worker's new end-ready-from-instance-track) changes that row.

- C1 - After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical.
- C2 - When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged.

**Outcome.** ### engine/server/data/subtitles.py
- Added the `TranslateJob` frozen dataclass. It holds the claiming connection (`field(repr=False, compare=False)`) plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`.
- It has six methods. Each is one `_update_claim` call that returns `bool`, with the timestamp passed in by the caller:
  - `write_running_cues(cues, detected_language)`
  - `end_ready(cues, finished_at)`
  - `end_already_english(detected_language, finished_at)`
  - `end_failed(error, finished_at)`
  - `requeue()`
  - `end_ready_from_instance(track_text, cues, finished_at)`
- The first five methods keep the exact SET strings of the functions they replace. `end_ready_from_instance` sets state `ready`, source `instance`, `track_text`, `cues_json`, and `fetched_at` = `finished_at` from one value. It touches no other column.
- `claim_translate_job` keeps its signature and its IMMEDIATE transaction. It now returns a `TranslateJob` built from the re-read row, or `None`.
- `_update_claim(job, assignments, values)` now takes the handle. The WHERE clause is unchanged (`{_KEY} AND state = 'running' AND started_at = ?`), and it still runs inside `with job.conn:`.
- Deleted `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `mark_translate_finished`.
- Added `SOURCE_INSTANCE = "instance"` beside `SOURCE_WHISPER`.
- Added `_instance_cues_text`: compact JSON that allows NaN, i.e. the same encoding `store_ready_subtitles` had inline. `store_ready_subtitles` now calls it, with its SQL and output unchanged, and `end_ready_from_instance` uses it too, so the two instance-track writers encode identically.
- `recover_translate_jobs` is untouched (phase 2).
- Updated the module docstring and the `store_ready_subtitles` docstring to describe the handle and to name the real takeover writer.
- Import added: `from dataclasses import dataclass, field`.

### engine/server/api/handlers/internal_translate.py
- `SOURCE_INSTANCE` is now imported from `data.subtitles` and the local definition is removed, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves.
- Nothing else changed.

### engine/server/db/jobs/translate-worker.py
- Imports:
  - `data.subtitles` now gives `TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, recover_translate_jobs, write_translate_heartbeat`.
  - `SOURCE_INSTANCE` is no longer imported from the route.
- `translate_audio(job, pipe, runner, max_chunk, stop, progress)` now calls `job.end_already_english`, `job.write_running_cues` and `job.end_ready`. Each still raises `JobTakenOver` on `False`, so control flow is unchanged.
- `generate(job, args, runner, stop, progress)`:
  - It resolves with `job.video_id` and `job.instance_domain`.
  - The unconditional `store_ready_subtitles` + `mark_translate_finished` pair is now one `job.end_ready_from_instance(fetched[0], fetched[1], now_ms())`, which raises `JobTakenOver` on `False`. This is the approved behaviour change: after a takeover, the worker writes nothing and logs `taken over by the instance track`.
- `run_job(job, args, runner, stop, progress)` no longer takes `conn` or builds the claim tuple:
  - requeue and end failed go through `job.requeue()` and `job.end_failed(...)`, with their results still ignored;
  - the log texts are unchanged.
- `serve` logs the claimed attributes instead of subscripting, and calls `run_job(job, ...)`.
- Updated the `JobTakenOver` docstring to name the real writer, and the `run_job` and `generate` docstrings plus one sentence of the module docstring to describe the handle.

### tests/active/test_subtitles.py
Edited only where a removed function or a subscripted claim was used:
- `WORKER_SCRIPT`: the import no longer names the removed functions. The key check uses attributes, and the writes use `job.write_running_cues` and `job.end_ready`.
- The claim test, the recovery test and the `fetch_subtitle_state` test read attributes instead of subscripts.
- The `fetch_subtitle_state` test writes running cues through the handle.
- The docstring's concurrent-writers sentence names the handle methods.
- Phase 2 still has to route the recovery test through `open_translate_worker_store`.

### tests/active/test_internal_translate.py
- `_claimed` returns the handle.
- `_seed` and the two running-key tests call `write_running_cues`, `end_failed` and `end_already_english` on it. Their imports drop the removed functions.

### tests/active/test_translate_worker.py
- `Rig.claim` reads attributes.
- `Rig.run` and the fetch-reason test call `run_job(job, ...)` without `conn`.
- The docstring's `run_job` signature is updated to match.

#### Phase 2 - Single opener, flock-tied recovery [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), engine/server/api/server.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED)

**Checkpoint.** The seam is the store module's two openers, entered at rung 1 or 3 in tests/active/test_subtitles.py against real files under tmp_path, reusing the existing `_b1_file` harness. Test 1: `open_subtitles_db(tmp_path/"a"/"b"/"subtitles.db")` creates the directory, the columns equal `ALL_COLUMNS`, the heartbeat table exists and `PRAGMA journal_mode` is `wal`. Test 2: on a `_b1_file`, the columns equal `ALL_COLUMNS` and the old cues equal `B1_CUES`. Test 3 uses two descriptors: `held = os.open(lock)` takes LOCK_EX, and `mine` is a separate `os.open` (not `dup`). `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError, and the file and its parent directory are both absent. Control: once `held` is closed, the same call on `mine` succeeds and the file exists. Test 4 is the rewritten recovery test, run under a held flock through `open_translate_worker_store`. It returns (1, 0) at 9000 and (2, 1) at 9500 and reads the handle's attributes. Engine start (server.py) is covered by the existing Engine-start test groups, kept green.

**Intent.** subtitles.db is opened everywhere through `open_subtitles_db`, which creates the directory, connects in WAL and migrates, and crash recovery can run only through `open_translate_worker_store`, which re-asserts the worker's flock before touching the file.

- C1 - `open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode.
- C2 - `open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock.

**Outcome.** _pending_

#### Phase 3 - Route store helper [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), tests/active/test_internal_translate.py (EDITED)

**Checkpoint.** The seam is the /internal/translate state route, entered through the existing route harness in tests/active/test_internal_translate.py (`_server` SimpleNamespace fake, `_instance(True)` RecordingInstance), the same way the current closed-store tests drive it. With `subtitles_db = None` and an instance track present, the test asserts the answer is exactly `[[200, {"state": "ready", "cues": CUES, "available": False}]]`. It also asserts that caplog holds exactly one record starting `[translate] cache closed, track not stored`, with the video_id and host in it. The existing closed-store read and enqueue tests and the NONE_CASES exact-list assertions stay green unchanged, which shows the other two sites' answers did not move.

**Intent.** The three subtitles-store sites in engine/server/api/handlers/internal_translate.py go through one `_subtitles_store` context manager, and when the instance track is found while the store is closed, the route still answers ready and logs that the track was not stored.

- C1 - With the store closed, an instance track is answered ready and one `[translate] cache closed, track not stored` info line is logged.

**Outcome.** _pending_

#### Phase 4 - Shared translatable-video resolve [code]

**Files touched.** engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED)

**Checkpoint.** The seam is `resolve_translatable_video`, entered at rung 1 in tests/active/test_internal_translate.py on the existing `whitelist` fixture DB. The test asserts that host None and host "" both return `(None, "missing host")` even for the known VIDEO_ID, that the denied-host video returns `(None, "host denied")`, that an unknown id returns `(None, "not in whitelist")` and that the known video returns its row with a None refusal. The existing route 400/404 tables in test_internal_translate.py and the worker refusal-text tables in test_translate_worker.py are the regression net for both callers and stay green unchanged.

**Intent.** Both /internal/translate routes and the translate worker resolve a video through one `resolve_translatable_video` in internal_translate.py, which refuses a missing host before any lookup, then a video not in the whitelist, then an actively denied host.

- C1 - `resolve_translatable_video` returns `missing host`, `not in whitelist` or `host denied` for the matching case, and the row otherwise.

**Outcome.** _pending_


