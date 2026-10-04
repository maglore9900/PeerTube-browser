# Build record - 54-translate-job-handle

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/01-54-translate-job-handle.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# A translate job handle in the subtitles store\n\nStatus: enhancement, ready-for-agent\nOrigin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate \"translate job handle in the subtitles store\" (Strong)\n\n## Problem\n\nA translate job's lifecycle runs through four modules, and the store's interface hands its invariants to the callers:\n\n- After the claim, the worker builds `(video_id, instance_domain, TARGET_LANGUAGE, started_at)` by hand (`engine/server/db/jobs/translate-worker.py:473`). It then passes `*claim` to every finish and requeue call, eight call sites in all, so that `_update_claim` (`engine/server/data/subtitles.py:158-162`) can compare-and-set on `started_at`. The finish and requeue functions (`subtitles.py:165-187`) are one-line wrappers.\n- `store_ready_subtitles` documents \"against a job row it ends the job \u2026 so read state first\" (`subtitles.py:105`). The route follows that rule. The worker instead does an unconditional upsert followed by a conditional `mark_translate_finished` (`translate-worker.py:445-446`).\n- `recover_translate_jobs` is safe only under the worker's flock (`subtitles.py:151`), and only `command_run`'s ordering guarantees that.\n- Every opener must call `ensure_subtitles_schema` after `connect_subtitles_db` and create the directory first (`engine/server/api/server.py:371-372`, `translate-worker.py:136-140, 567-571`).\n- The route repeats the `subtitles_db_lock` / `None` check three times (`internal_translate.py:215-219, 237-240, 320-322`).\n- `JobTakenOver` (`translate-worker.py:92-93, 485-486`) refers to a route taking over a running row. The current route never fetches over a running row (`internal_translate.py:297-300`). The review found no current writer that triggers it, but did not check an older blue/green Engine.\n- Tests fake `server` as a `SimpleNamespace` with three lock and connection attributes (`tests/active/test_internal_translate.py:510-512`).\n\n## Proposed solution\n\nMake the claim return a job handle that carries its own key and `started_at` and exposes the end states: ready with cues, already English, failed with text, requeue, and running cues. The compare-and-set happens inside the handle. Opening the store also migrates it. \"Instance track found while running\" becomes one store operation. Settle whether `JobTakenOver` still has a writer. The interface is not decided yet.\n\n## Related\n\n- `CONTEXT.md`: Translate job, Translate state.\n- Issue 57 (resolve translatable video) is small and fits inside this.\n- Issue 56 (worker split): its job-pipeline part depends on this.\n\n## Comments\n\n**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold except one. `JobTakenOver` does have a current writer. The state route reads the key, and when there is no row it fetches the instance track, which can take up to its 15 s budget. It then stores `ready` with an unconditional upsert. If an enqueue and a claim land in that window, the upsert ends the running job. Older blue/green Engines were not checked. No job handle exists yet, and there are no prior rejections. The maintainer decided:\n\n- **Issue 57 is folded in:** the shared \"resolve a translatable video\" function is part of this brief. Issue 57 should be closed as covered by 54; it was not edited in this run.\n- **The instance track wins a takeover race:** behaviour is unchanged. `JobTakenOver` stays, documented with its real writer.\n- The term \"claim\" (and \"taken over\") is now in `CONTEXT.md`.\n\n## Agent Brief\n\n**Category:** enhancement\n**Summary:** Make a translate job's claim a handle that owns its key, its `started_at` compare-and-set and its end states. Make opening the subtitles store also migrate it. Resolve a translatable video in one function shared by the route and the worker. Behaviour stays the same throughout.\n\n**Current behavior:**\nThe subtitles store hands its invariants to the callers:\n- **The claim.** `claim_translate_job` returns a bare row. The translate worker rebuilds `(video_id, instance_domain, target_language, started_at)` from it by hand and passes it unpacked to `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `requeue_translate_job`. Each of these is a one-line wrapper over one private conditional update, which matches only while the row is `running` with that `started_at`. Each returns `False` when the row was taken over.\n- **The instance track found at claim.** The worker calls `store_ready_subtitles`, an unconditional upsert, and then `mark_translate_finished`, a conditional stamp. `store_ready_subtitles`' own contract says to read state first, and the worker's call does not.\n- **Recovery.** `recover_translate_jobs` is safe only while the worker holds its flock. Only the order of steps in the worker's `run` command guarantees that.\n- **Opening the store.** Every opener (the Engine at start, the worker's enqueue CLI and its `run` service) must create the parent directory, call `connect_subtitles_db` and then `ensure_subtitles_schema`.\n- **The route's store access.** The translate routes repeat the same \"hold `subtitles_db_lock`, take `subtitles_db`, treat `None` as closed\" block three times: the state read, the instance-track store and the enqueue.\n- **Resolving a video, done twice.** The route resolves a video from `{id, host}` with `resolve_video_row`, then the active-denylist check under `db_lock`, writing the 400 or 404 response itself. The worker's `resolve_video` does the same lookup with `fetch_video_row` and `VIDEO_ERROR_THRESHOLD`, the same denylist check, a stored-duration bound and an inline `busy_timeout`. The worker also guards a pitfall: a `None` host matches the id on any host. The two can drift apart.\n- **Tests.** Tests fake the Engine server as a `SimpleNamespace` with `db`, `db_lock`, `subtitles_db`, `subtitles_db_lock` and the threshold.\n\n**Desired behavior:**\n- **Job handle.** Claiming returns a job handle, or nothing when no job is queued. The handle carries the job's key, its `started_at` and its `attempts`, and exposes the claim's operations:\n  - write the running cues so far (with the detected language);\n  - end ready with the full cue list;\n  - end `already_english` with the detected language;\n  - end `failed` with the error text;\n  - requeue without spending the claim;\n  - end ready from an instance caption track.\n\n  Each operation does the compare-and-set on `started_at` internally and reports whether the claim still held. The last operation is a single store operation that writes the track and stamps `finished_at` only while the claim holds. The current upsert-then-stamp is replaced, and the end state is the same as today's. No caller assembles or unpacks a claim tuple.\n- **Takeover.** Unchanged: the Engine's instance-track store still replaces a running row, and a later handle operation then reports the claim lost. The worker's `JobTakenOver` path stays. Its docstring and the worker doc must name the real writer: the state route's instance-track store racing an enqueue and a claim.\n- **Opening the store.** One open function creates the parent directory, connects in WAL mode and migrates the schema. The Engine and every worker entry point use it. The heartbeat thread's connection may use it too.\n- **Recovery** is reachable only together with the worker's flock. For example, a store opener for the worker service runs recovery and can only be called while the flock is held, or recovery takes proof of the lock. A caller cannot run recovery without the lock by mistake.\n- **The route's store access** goes through one helper that holds the lock and treats a closed store the same way the three current sites do: no row and not available for reads, a logged no-op for the track store, and `available: false` with nothing queued for enqueue.\n- **Resolve a translatable video (from issue 57).** One function takes a whitelist connection, a video id, a normalised host and an error threshold. It returns the whitelisted row, or a refusal: not in whitelist, or host denied, checked on the row's normalised domain against the active denylist. It refuses a missing host instead of matching the id on any host. The route maps the refusal to its current 404 `Video not found`. The worker maps it to its current refusal texts and keeps its own stored-duration bound and `busy_timeout`. The route's 400 validation of the `{id, host}` body stays in the route.\n\n**Key interfaces:**\n- The claim's return type becomes a job handle: a small class or dataclass in the subtitles store module, holding the store connection or taking it per call.\n- Handle operations return whether the claim held, or raise one exception the worker maps to its takeover path. Choose one.\n- One store-open function replaces the `connect_subtitles_db` plus `ensure_subtitles_schema` pair at every caller.\n- One resolve function, shared by the `/internal/translate` routes and the translate worker, returns a row or a refusal and never writes an HTTP response.\n\n**Acceptance criteria:**\n- [ ] No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. The five per-claim functions and `mark_translate_finished` are no longer part of the store's public interface.\n- [ ] Every handle operation is a no-op that reports the claim lost when the row is no longer `running` with the claim's `started_at`. A test proves this for each operation.\n- [ ] Ending ready from an instance track while the claim holds leaves exactly today's row: state `ready`, source `instance`, the track and cues, `finished_at` set. When the claim was lost, it changes nothing.\n- [ ] A state-route instance-track store over a running row still wins. The worker then logs the takeover and writes nothing further for that job.\n- [ ] Opening the store on a fresh path creates the directory and the full schema. Opening a B1-era file adds the job columns. The Engine and the worker's enqueue and run entry points call nothing else to open the store.\n- [ ] Recovery cannot be called from the worker without the flock held. A test or the type of the call shows this.\n- [ ] The three route sites use one store-access helper, and route responses for a closed store are unchanged.\n- [ ] One resolve function serves both the routes and the worker. A missing host is refused, a denied host is refused on the row's normalised domain, and the routes' 400 and 404 responses and the worker's refusal texts are unchanged.\n- [ ] The existing translate route, translate worker and subtitles store tests pass, rewritten only where they used the removed functions or the claim tuple.\n- [ ] The translate worker doc and the Engine server README's store-contract section describe the handle, the takeover writer and the single store opener.\n\n**Out of scope:**\n- Making the state route's instance-track store conditional, i.e. a running job winning the race.\n- Removing `JobTakenOver`.\n- The source-instance fetch adapter (issue 53) and the rest of the worker split (issue 56): timing parameters and moving the pipeline out of the script.\n- Changing the job states, `MAX_CLAIMS`, recovery's requeue-once rule, the queue cap or the heartbeat.\n- Any schema change beyond what the store opener already migrates.",
  "request_source": "read from docs/project/issues/54-translate-job-handle.md",
  "slug": "54-translate-job-handle",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Claim handle",
      "checkpoint": "Seam 1 is the store module, entered at rung 1 in tests/active/test_subtitles.py with its existing `_snapshot` harness. A parametrised test runs over the six TranslateJob methods (running cues, ready, already_english, failed, requeue, ready from instance). For each it enqueues, claims, takes the row over with `store_ready_subtitles(..., \"instance\", ...)` and snapshots, then asserts the method returns `False` and the snapshot is unchanged. A control runs the same method on a fresh claim with no takeover and asserts `True`, which shows the `False` comes from the takeover and not from a broken UPDATE. A second store test covers the held-claim control: `end_ready_from_instance` returns True and leaves state `ready`, source `instance`, the track_text, compact cues_json (no space) and `fetched_at == finished_at`, with detected_language, error, attempts, queued_at and started_at unchanged. Seam 2 is the worker's `run_job`/`generate`, entered through the existing `Rig` harness in tests/active/test_translate_worker.py with a served English listing and track. `fetch_instance_track` is wrapped so that, after the real fetch, it runs `store_ready_subtitles` with the Engine's track and snapshots the row. The test asserts the row equals that snapshot (Engine's track_text and cues kept), the `taken over by the instance track video_id=v-1 host=\u2026` log line is present, no `failed` line is present and the runner made 0 transcribes. Today's code fails this because the upsert overwrites track_text. The existing English-instance-track test at :1016 stays green unchanged.",
      "intent": "`claim_translate_job` in engine/server/data/subtitles.py returns a TranslateJob handle bound to its connection, and the worker writes every claim-conditional change through it, so once the Engine's instance-track store has replaced a running row, no handle write (including the worker's new end-ready-from-instance-track) changes that row.",
      "clauses": [
        {
          "id": "C1",
          "text": "After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical."
        },
        {
          "id": "C2",
          "text": "When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged."
        }
      ],
      "files": [
        "engine/server/data/subtitles.py (EDITED)",
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "engine/server/api/handlers/internal_translate.py (EDITED)",
        "tests/active/test_subtitles.py (EDITED)",
        "tests/active/test_internal_translate.py (EDITED)",
        "tests/active/test_translate_worker.py (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/server/data/subtitles.py\n- Added the `TranslateJob` frozen dataclass. It holds the claiming connection (`field(repr=False, compare=False)`) plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`.\n- It has six methods. Each is one `_update_claim` call that returns `bool`, with the timestamp passed in by the caller:\n  - `write_running_cues(cues, detected_language)`\n  - `end_ready(cues, finished_at)`\n  - `end_already_english(detected_language, finished_at)`\n  - `end_failed(error, finished_at)`\n  - `requeue()`\n  - `end_ready_from_instance(track_text, cues, finished_at)`\n- The first five methods keep the exact SET strings of the functions they replace. `end_ready_from_instance` sets state `ready`, source `instance`, `track_text`, `cues_json`, and `fetched_at` = `finished_at` from one value. It touches no other column.\n- `claim_translate_job` keeps its signature and its IMMEDIATE transaction. It now returns a `TranslateJob` built from the re-read row, or `None`.\n- `_update_claim(job, assignments, values)` now takes the handle. The WHERE clause is unchanged (`{_KEY} AND state = 'running' AND started_at = ?`), and it still runs inside `with job.conn:`.\n- Deleted `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `mark_translate_finished`.\n- Added `SOURCE_INSTANCE = \"instance\"` beside `SOURCE_WHISPER`.\n- Added `_instance_cues_text`: compact JSON that allows NaN, i.e. the same encoding `store_ready_subtitles` had inline. `store_ready_subtitles` now calls it, with its SQL and output unchanged, and `end_ready_from_instance` uses it too, so the two instance-track writers encode identically.\n- `recover_translate_jobs` is untouched (phase 2).\n- Updated the module docstring and the `store_ready_subtitles` docstring to describe the handle and to name the real takeover writer.\n- Import added: `from dataclasses import dataclass, field`.\n\n### engine/server/api/handlers/internal_translate.py\n- `SOURCE_INSTANCE` is now imported from `data.subtitles` and the local definition is removed, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves.\n- Nothing else changed.\n\n### engine/server/db/jobs/translate-worker.py\n- Imports:\n  - `data.subtitles` now gives `TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, recover_translate_jobs, write_translate_heartbeat`.\n  - `SOURCE_INSTANCE` is no longer imported from the route.\n- `translate_audio(job, pipe, runner, max_chunk, stop, progress)` now calls `job.end_already_english`, `job.write_running_cues` and `job.end_ready`. Each still raises `JobTakenOver` on `False`, so control flow is unchanged.\n- `generate(job, args, runner, stop, progress)`:\n  - It resolves with `job.video_id` and `job.instance_domain`.\n  - The unconditional `store_ready_subtitles` + `mark_translate_finished` pair is now one `job.end_ready_from_instance(fetched[0], fetched[1], now_ms())`, which raises `JobTakenOver` on `False`. This is the approved behaviour change: after a takeover, the worker writes nothing and logs `taken over by the instance track`.\n- `run_job(job, args, runner, stop, progress)` no longer takes `conn` or builds the claim tuple:\n  - requeue and end failed go through `job.requeue()` and `job.end_failed(...)`, with their results still ignored;\n  - the log texts are unchanged.\n- `serve` logs the claimed attributes instead of subscripting, and calls `run_job(job, ...)`.\n- Updated the `JobTakenOver` docstring to name the real writer, and the `run_job` and `generate` docstrings plus one sentence of the module docstring to describe the handle.\n\n### tests/active/test_subtitles.py\nEdited only where a removed function or a subscripted claim was used:\n- `WORKER_SCRIPT`: the import no longer names the removed functions. The key check uses attributes, and the writes use `job.write_running_cues` and `job.end_ready`.\n- The claim test, the recovery test and the `fetch_subtitle_state` test read attributes instead of subscripts.\n- The `fetch_subtitle_state` test writes running cues through the handle.\n- The docstring's concurrent-writers sentence names the handle methods.\n- Phase 2 still has to route the recovery test through `open_translate_worker_store`.\n\n### tests/active/test_internal_translate.py\n- `_claimed` returns the handle.\n- `_seed` and the two running-key tests call `write_running_cues`, `end_failed` and `end_already_english` on it. Their imports drop the removed functions.\n\n### tests/active/test_translate_worker.py\n- `Rig.claim` reads attributes.\n- `Rig.run` and the fetch-reason test call `run_job(job, ...)` without `conn`.\n- The docstring's `run_job` signature is updated to match."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Single opener, flock-tied recovery",
      "checkpoint": "The seam is the store module's two openers, entered at rung 1 or 3 in tests/active/test_subtitles.py against real files under tmp_path, reusing the existing `_b1_file` harness. Test 1: `open_subtitles_db(tmp_path/\"a\"/\"b\"/\"subtitles.db\")` creates the directory, the columns equal `ALL_COLUMNS`, the heartbeat table exists and `PRAGMA journal_mode` is `wal`. Test 2: on a `_b1_file`, the columns equal `ALL_COLUMNS` and the old cues equal `B1_CUES`. Test 3 uses two descriptors: `held = os.open(lock)` takes LOCK_EX, and `mine` is a separate `os.open` (not `dup`). `open_translate_worker_store(tmp_path/\"sub\"/\"subtitles.db\", mine, 1)` raises BlockingIOError, and the file and its parent directory are both absent. Control: once `held` is closed, the same call on `mine` succeeds and the file exists. Test 4 is the rewritten recovery test, run under a held flock through `open_translate_worker_store`. It returns (1, 0) at 9000 and (2, 1) at 9500 and reads the handle's attributes. Engine start (server.py) is covered by the existing Engine-start test groups, kept green.",
      "intent": "subtitles.db is opened everywhere through `open_subtitles_db`, which creates the directory, connects in WAL and migrates, and crash recovery can run only through `open_translate_worker_store`, which re-asserts the worker's flock before touching the file.",
      "clauses": [
        {
          "id": "C1",
          "text": "`open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode."
        },
        {
          "id": "C2",
          "text": "`open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock."
        }
      ],
      "files": [
        "engine/server/data/subtitles.py (EDITED)",
        "engine/server/api/server.py (EDITED)",
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_subtitles.py (EDITED)",
        "tests/active/test_internal_translate.py (EDITED)"
      ],
      "done": false
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Route store helper",
      "checkpoint": "The seam is the /internal/translate state route, entered through the existing route harness in tests/active/test_internal_translate.py (`_server` SimpleNamespace fake, `_instance(True)` RecordingInstance), the same way the current closed-store tests drive it. With `subtitles_db = None` and an instance track present, the test asserts the answer is exactly `[[200, {\"state\": \"ready\", \"cues\": CUES, \"available\": False}]]`. It also asserts that caplog holds exactly one record starting `[translate] cache closed, track not stored`, with the video_id and host in it. The existing closed-store read and enqueue tests and the NONE_CASES exact-list assertions stay green unchanged, which shows the other two sites' answers did not move.",
      "intent": "The three subtitles-store sites in engine/server/api/handlers/internal_translate.py go through one `_subtitles_store` context manager, and when the instance track is found while the store is closed, the route still answers ready and logs that the track was not stored.",
      "clauses": [
        {
          "id": "C1",
          "text": "With the store closed, an instance track is answered ready and one `[translate] cache closed, track not stored` info line is logged."
        }
      ],
      "files": [
        "engine/server/api/handlers/internal_translate.py (EDITED)",
        "tests/active/test_internal_translate.py (EDITED)"
      ],
      "done": false
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Shared translatable-video resolve",
      "checkpoint": "The seam is `resolve_translatable_video`, entered at rung 1 in tests/active/test_internal_translate.py on the existing `whitelist` fixture DB. The test asserts that host None and host \"\" both return `(None, \"missing host\")` even for the known VIDEO_ID, that the denied-host video returns `(None, \"host denied\")`, that an unknown id returns `(None, \"not in whitelist\")` and that the known video returns its row with a None refusal. The existing route 400/404 tables in test_internal_translate.py and the worker refusal-text tables in test_translate_worker.py are the regression net for both callers and stay green unchanged.",
      "intent": "Both /internal/translate routes and the translate worker resolve a video through one `resolve_translatable_video` in internal_translate.py, which refuses a missing host before any lookup, then a video not in the whitelist, then an actively denied host.",
      "clauses": [
        {
          "id": "C1",
          "text": "`resolve_translatable_video` returns `missing host`, `not in whitelist` or `host denied` for the matching case, and the row otherwise."
        }
      ],
      "files": [
        "engine/server/api/handlers/internal_translate.py (EDITED)",
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_internal_translate.py (EDITED)"
      ],
      "done": false
    }
  ],
  "digests": {
    "tests/tmp/test_54_translate_job_handle_phase1.py": "32ed25a35013cc3b76398056f512b059f8751df3b3b6df10d702637b216b62aa"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261004T121605-e75f-dev-flow"
  ],
  "snapshot": {
    "tree": "c841889bf812343a114aacd31d797d13bd0d2ad9",
    "at": "2026-10-04T12:33:14-04:00"
  },
  "plan": "docs/project/plans/01-54-translate-job-handle.md",
  "record": "docs/project/plans/01-54-translate-job-handle.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nMove a translate job's invariants out of the callers and into the subtitles store (`engine/server/data/subtitles.py`). Today the callers carry four rules: the `started_at` compare-and-set on every write for a claimed job, the open-then-migrate order, recovery only under the worker's flock, and the whitelist/denylist resolve. They also carry the rules for a translatable video, which are duplicated between the `/internal/translate` routes and the translate worker. This is a refactor. Observable behaviour stays the same, apart from the one approved change described under \"End ready from an instance track\". It folds in issue 57 (resolve a translatable video once). Issue 56's job-pipeline part depends on it.\n\n### Job handle\n\n- `claim_translate_job` (or its replacement) returns a job handle, or `None` when no job for the target language is queued. The claim itself is unchanged: in one IMMEDIATE transaction, the oldest `queued` row by `queued_at` then rowid becomes `running`, gets `started_at` and has `attempts` raised by 1.\n- The handle is a small class or dataclass in `engine/server/data/subtitles.py`. It carries the job's key (`video_id`, `instance_domain`, `target_language`), its `started_at` and its `attempts`. It either holds the store connection or takes it per call; the design step chooses which.\n- The handle exposes these operations. Each one does the compare-and-set internally: it matches only while the row is `running` with this claim's `started_at`. Each reports whether the claim still held.\n  1. **Write running cues:** rewrite the whole `cues_json` (as `_cues_text`, i.e. `allow_nan=False`) and set `detected_language`. Same as today's `store_running_cues`.\n  2. **End ready:** state `ready`, the full start-sorted `cues_json`, `fetched_at` = `finished_at` = the given time. Same as today's `finish_translate_ready`.\n  3. **End already_english:** state `already_english`, `detected_language`, `finished_at`. Same as today's `finish_translate_already_english`.\n  4. **End failed:** state `failed`, `error` text, `finished_at`. Partial cues stay. Same as today's `finish_translate_failed`.\n  5. **Requeue:** state `queued`, `attempts - 1`, with `queued_at` kept. Same as today's `requeue_translate_job`.\n  6. **End ready from an instance track:** see the next section.\n- How a lost claim is reported is the design step's choice, made once for every operation: either return `bool` (claim held), or raise one exception that the worker maps to its `JobTakenOver` path.\n- No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `requeue_translate_job` and `mark_translate_finished` are removed from the store's public interface. `_update_claim` may remain as a private helper. `store_ready_subtitles` stays: the route still uses it.\n\n### End ready from an instance track (one store operation)\n\n- This replaces the worker's `store_ready_subtitles` + `mark_translate_finished` pair (`translate-worker.py` `generate`) with one conditional UPDATE. It applies only while the row is `running` with this claim's `started_at`.\n- While the claim holds, it leaves exactly today's row: state `ready`, source `instance`, `track_text` set, `cues_json` set, `fetched_at` set and `finished_at` set. The cues are encoded as `store_ready_subtitles` encodes them today: `json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))`, which allows NaN. They are not encoded with `_cues_text`. Other job columns (`detected_language`, `error`, `attempts`, `queued_at`, `started_at`) are left as they are, as the upsert leaves them today.\n- Approved simplification: a single timestamp supplies both `fetched_at` and `finished_at`. Today two separate `now_ms()` calls set them.\n- Approved behaviour change: when the claim was lost, the operation changes nothing. Today the worker's upsert overwrites the Engine's row and then stamps `finished_at`. The worker then takes its takeover path: it logs `taken over by the instance track video_id=\u2026 host=\u2026` and writes nothing further for the job.\n\n### Takeover (unchanged behaviour)\n\n- The Engine state route's instance-track store (`_store_cues` \u2192 `store_ready_subtitles`, an unconditional upsert) still replaces a running row, so the instance track wins the race. Making it conditional is out of scope.\n- After such a takeover, every handle operation reports the claim lost. The worker's `JobTakenOver` path stays: it logs the takeover and writes nothing further for that job, which means no `failed` end and no requeue.\n- The real writer is the state route's instance-track store, racing an enqueue and a claim. The route reads no row (or a `failed`/`already_english` row) and fetches the instance, which takes up to its 15 s budget. Meanwhile a job is enqueued and claimed, and the route's upsert then lands on the running row. An older blue/green Engine is a possible further writer. The `JobTakenOver` docstring and any docstrings that say \"B1's route\" (`run_job`, `_update_claim`/handle) must name this writer. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` \u00a7 \"Takeover by the Instance Track\" already describes it; it is updated only where it names removed functions. `CONTEXT.md` already defines \"Claim\" and \"taken over\" and needs no change unless the wording of the handle requires it.\n\n### Opening the store\n\n- One open function in `subtitles.py` creates the parent directory (`mkdir(parents=True, exist_ok=True)`), connects in WAL mode with today's busy timeout and lock-retry loop (`connect_subtitles_db`), and migrates the schema (`ensure_subtitles_schema`).\n- The Engine start (`engine/server/api/server.py`, currently lines 371-372) uses it. The open stays where it is in start-up order: after `prepare_trending_override`, so a rejected start still creates nothing. The worker's `enqueue` command and its `run` service use it too. None of these callers calls anything else to open the store.\n- The heartbeat thread's own connection (`heartbeat_loop`) may use it too, or may keep the plain connect; the design step decides.\n- On a fresh path, opening creates the directory and the full schema. On a B1-era file, it adds the job columns. The existing concurrent-opener guarantees hold: no `duplicate column`, no `database is locked`, and WAL afterwards.\n\n### Recovery under the flock\n\n- `recover_translate_jobs` logic is unchanged: rows at `attempts >= MAX_CLAIMS` become `failed` with `worker stopped while running twice`, and other `running` rows go back to `queued`.\n- Callers must not be able to run it without the worker's flock by mistake. Two acceptable shapes: a worker-service store opener that runs recovery and can only be called while the flock is held (for example, it acquires the flock itself or takes the held lock as an argument), or recovery that takes proof of the lock. A test, or the type of the call, shows this.\n\n### Route store access\n\n- In `engine/server/api/handlers/internal_translate.py`, three sites each repeat the \"hold `server.subtitles_db_lock`, take `server.subtitles_db`, treat `None` as closed\" block: `_read_key`, `_store_cues` and the enqueue in `handle_internal_translate_enqueue`. One helper replaces all three.\n- Responses for a closed store are unchanged:\n  - state read: no row and `available: false`;\n  - track store: a no-op, logged;\n  - enqueue: `{\"state\": \"none\", \"available\": false}`, nothing queued.\n- `sqlite3.Error` handling is unchanged: the read logs `cache read failed` and answers no row, not available; the store logs `cache write failed`; the enqueue logs and answers 503 `{\"error\": \"Translate store unavailable\"}`. The enqueue's beat check and enqueue stay under one lock hold.\n- The route tests' `SimpleNamespace` server fake (`db`, `db_lock`, `video_error_threshold`, `subtitles_db`, `subtitles_db_lock`, `statement_timeout_seconds`) stays as it is. Changing it is not required.\n\n### Resolve a translatable video (issue 57)\n\n- One function takes a whitelist connection, a video id, a normalised host and an error threshold. It returns either the whitelisted row or a refusal, and never writes an HTTP response. The refusals are:\n  - not in whitelist: `fetch_video_row` with the threshold finds no row;\n  - host denied: `normalize_host(row[\"instance_domain\"])` is in `list_active_denied_hosts(conn)`;\n  - a missing host (`None` or empty): refused, never matched against the id on any host (`fetch_video_row` with a `None` host matches any host).\n- The `/internal/translate` routes and the translate worker both use it, and its location must be importable by both. The worker already imports from `handlers.*` via `api/` on `sys.path`.\n- Route: `_resolve_translate_key` keeps its own 400 validation of the `{id, host}` body: invalid JSON, `Missing id or host`, `Invalid host`. It calls the shared function on `server.db` under `server.db_lock` with `server.video_error_threshold`, and maps any refusal to its current 404 `{\"error\": \"Video not found\"}`. It keeps using the row's canonical `video_id`, `instance_domain` and `video_uuid or video_id`.\n- Worker: `resolve_video` keeps its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its stored-duration bound (a NULL duration passes). It maps refusals to its current texts: `not in whitelist`, `host denied`, `duration Ns over Ms`. The `enqueue` command's `refused: invalid id or host` check is unchanged, and so are `generate`'s `sqlite3.OperationalError` \u2192 `WhitelistBusy` mapping and its exit codes.\n\n### Documentation\n\n- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` and the \"Translate worker and its store contract\" section of `engine/server/README.md` describe three things: the job handle and its operations, the takeover writer (the state route's instance-track store racing an enqueue and a claim), and the single store opener (plus how recovery is tied to the flock).\n- The module docstrings of `subtitles.py`, `internal_translate.py` and `translate-worker.py` stop naming removed functions.\n\n### Acceptance criteria\n\n- [ ] No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. The five per-claim functions and `mark_translate_finished` are no longer public in the store.\n- [ ] Every handle operation (running cues, ready, already_english, failed, requeue, ready from instance track) is a no-op that reports the claim lost when the row is no longer `running` with the claim's `started_at`. A test proves this for each operation.\n- [ ] Ending ready from an instance track while the claim holds leaves state `ready`, source `instance`, the track text and cues, and `fetched_at` and `finished_at` set. When the claim was lost, it changes nothing.\n- [ ] A state-route instance-track store over a running row still wins. The worker then logs the takeover and writes nothing further for that job.\n- [ ] Opening the store on a fresh path creates the directory and the full schema, and opening a B1-era file adds the job columns. The Engine and the worker's `enqueue` and `run` entry points call nothing else to open the store.\n- [ ] Recovery cannot be called from the worker without the flock held. A test or the type of the call shows this.\n- [ ] The three route sites use one store-access helper, and route responses for a closed store are unchanged.\n- [ ] One resolve function serves both the routes and the worker. A missing host is refused, and a denied host is refused on the row's normalised domain. The routes' 400 and 404 responses and the worker's refusal texts are unchanged.\n- [ ] The existing tests pass: `tests/active/test_internal_translate.py`, `tests/active/test_translate_worker.py` and `tests/active/test_subtitles.py`. They are rewritten only where they used the removed functions or the claim tuple, for example the subprocess writer script in `test_subtitles.py` and the row-seeding helpers in `test_internal_translate.py`. The worker test for \"the instance holds an English track\" still sees ready/instance with the parsed cues and track text, and `finished_at` taken during the run.\n- [ ] The docs listed above describe the handle, the takeover writer and the single store opener.\n\n### Out of scope\n\n- Making the state route's instance-track store conditional (a running job winning the race).\n- Removing `JobTakenOver`.\n- The source-instance fetch adapter (issue 53, already delivered) and the rest of the worker split (issue 56): timing parameters and moving the pipeline out of the script.\n- Changing job states, `MAX_CLAIMS`, recovery's requeue-once rule, the queue cap or the heartbeat.\n- Any schema change beyond what the store opener already migrates.\n- Replacing the route tests' `SimpleNamespace` server fake.\n- Closing issue 57 in the tracker. That is housekeeping after delivery, as covered by 54, and not part of the code build.\n\n### Baseline suite state\n\n- Pre-build suite exited 0, not a variant run. The selective runner chose 1 of 65 groups (`test_search_fusion.py`, 10 passed), and 64 groups were unchanged and not re-run. The translate route, translate worker and subtitles store tests were therefore not freshly run at baseline; they are presumed green from their last recorded pass.\n\n### Notes on the tree\n\n- The issue's line references are out of date since issue 53 landed. The claim tuple is built at `translate-worker.py:437`. The upsert-then-stamp is at `:407-408`. The opener sites are `:131-135` (enqueue) and `:531-535` (run), plus the heartbeat at `:465`. `JobTakenOver` is at `:87-88`, and the route's lock sites are `internal_translate.py:157-160`, `:179-182` and `:261-263`. The behaviour the issue describes matches the code.\n</requirements>\n\n<conflicts>\nBrief \"Behaviour stays the same throughout\" vs brief AC \"When the claim was lost, [ending ready from an instance track] changes nothing\": today the worker's unconditional upsert plus `mark_translate_finished` overwrites the Engine's ready row and stamps `finished_at` even after a takeover, because the Engine's upsert leaves `started_at` untouched. The operator approved the AC's behaviour, with the worker taking its takeover path.\nBrief \"leaves exactly today's row\" vs today's code setting `fetched_at` and `finished_at` from two separate `now_ms()` calls: the operator approved one timestamp for both.\nBrief Problem lists the tests' `SimpleNamespace` server fake as an issue, but Desired behaviour and the ACs ask for no change to it: the operator confirmed it stays.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe work touches three code files and no new modules: `engine/server/data/subtitles.py` (the store), `engine/server/api/handlers/internal_translate.py` (the routes and the shared resolve) and `engine/server/db/jobs/translate-worker.py` (the worker). `engine/server/api/server.py` changes by one call, and the docs and tests follow.\n\n**Job handle.** `subtitles.py` gets a small frozen dataclass, `TranslateJob`. It holds the store connection the claim was made on, plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`. `claim_translate_job` keeps its name, signature and IMMEDIATE transaction (oldest `queued` by `queued_at` then rowid, set `running` and `started_at`, raise `attempts` by 1). It now returns this handle, built from the row it already re-reads, or `None`. The handle holds the connection rather than taking it per call. Every write for a claim must go to the connection that claimed it, and holding it means no caller can pair a handle with the wrong connection (the heartbeat thread has its own). It also lets `generate` and `translate_audio` stop carrying a connection argument at all.\n\nThe handle has six methods, each a thin call to the private `_update_claim`, which keeps its single conditional UPDATE matching `state = 'running' AND started_at = ?`. Each method takes its timestamp from the caller, as today:\n- write running cues (`_cues_text`, plus `detected_language`);\n- end ready (start-sorted cues via `_cues_text`, `fetched_at` = `finished_at` = the given time);\n- end already_english;\n- end failed (partial cues stay);\n- requeue (`queued`, `attempts - 1`, `queued_at` untouched);\n- end ready from an instance track.\n\n`_update_claim` takes the handle's fields instead of a loose key, so the claim tuple exists only inside the module. The five per-claim functions and `mark_translate_finished` are deleted. `store_ready_subtitles` stays.\n\n**Lost claim reported as `bool`.** Every method returns `True` when the claim held and `False` otherwise. This is today's contract, so the worker's control flow is unchanged:\n- `translate_audio` still raises `JobTakenOver` on `False` from running cues, already_english and ready.\n- `generate` raises it on `False` from the new instance-track end.\n- `run_job` still ignores the result of requeue and end failed, as today. A takeover that lands during a stop or a failure therefore still writes nothing and logs what it logs today.\n\n**End ready from an instance track.** One conditional UPDATE through `_update_claim` sets:\n- state `ready`;\n- source `instance`;\n- `track_text`;\n- `cues_json`;\n- `fetched_at` = `finished_at` = one timestamp.\n\nIt leaves every other job column alone. The cues are encoded by a private helper that `store_ready_subtitles` also switches to: `json.dumps(..., ensure_ascii=False, separators=(\",\", \":\"))`, NaN allowed, not `_cues_text`. One helper keeps the two instance-track writers encoding identically. `SOURCE_INSTANCE` moves into `subtitles.py` beside `SOURCE_WHISPER`. `internal_translate.py` imports it from there, so its own name still resolves. The worker no longer needs it at all, because the handle method fixes the source. In `generate`, the upsert-then-stamp at `:407-408` becomes one call with one `now_ms()`. A `False` result raises `JobTakenOver`, and the existing `taken over by the instance track video_id=\u2026 host=\u2026` log line follows. This is the approved change: a lost claim now writes nothing, where today the upsert overwrites the Engine's row.\n\n**Takeover unchanged.** The state route's `_store_cues` still calls the unconditional `store_ready_subtitles`, so the instance track still wins over a running row. Every handle method then matches nothing. The docstrings of `JobTakenOver`, `run_job`, `_update_claim` and the handle name the real writer: the state route's instance-track store, racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. They no longer say \"B1's route\".\n\n**Single store opener.** `open_subtitles_db(path)` in `subtitles.py` does three things in order:\n1. creates the parent directory;\n2. calls `connect_subtitles_db`, keeping the WAL switch, the 30 s busy timeout and the lock-retry loop;\n3. runs `ensure_subtitles_schema`.\n\nIf the migration raises, it closes the connection before re-raising. Three callers use it: `server.py` (its two lines at 371-372, in the same place, after `prepare_trending_override`), the worker's `enqueue` (replacing `:131-135`) and the worker service opener below. `connect_subtitles_db` and `ensure_subtitles_schema` stay public, because the tests and the heartbeat use them. The concurrent-opener guarantees come for free: the opener only composes the two functions that provide them today.\n\n**Heartbeat keeps the plain connect.** The beat thread starts only after the main thread's opener has migrated the file. Re-running the migration there would be a pointless extra IMMEDIATE transaction on every service start, so this decision is to keep `connect_subtitles_db` there.\n\n**Recovery tied to the flock.** `subtitles.py` gets a worker-service opener, `open_translate_worker_store(path, lock_fd, finished_at)`, which returns the connection and the `(requeued, failed)` counts. Before anything touches the file, it re-asserts `flock(lock_fd, LOCK_EX | LOCK_NB)` on the descriptor it was given:\n- On a descriptor whose open file description already holds the lock (the worker's), this is a no-op.\n- When another process or open file description holds the lock, it raises `BlockingIOError` before the file is opened. Nothing is created or written.\n- On an unlocked descriptor it takes the lock. Either way recovery can only run while the flock is held.\n\nIt then calls `open_subtitles_db` and recovery. `recover_translate_jobs` becomes private `_recover_translate_jobs` with its logic unchanged, so nothing outside the module can call it bare. `command_run` keeps its own LOCK_NB acquire first, which preserves the `another worker holds` log line and exit 6 before the store is opened. It then replaces `:531-536` with the one call. `fcntl` is imported inside that function, so the Engine's import of `subtitles.py` gains nothing.\n\nTests:\n- a second open file description holding the lock makes the opener raise and leaves the subtitles file absent;\n- with the lock held, recovery runs exactly as today's recovery test expects.\n\n**Route store access.** One context manager in `internal_translate.py`, `_subtitles_store(server)`, holds `server.subtitles_db_lock` for its body and yields `server.subtitles_db`, which is `None` when the store is closed. The three sites (`_read_key`, `_store_cues`, the enqueue) use it. Each keeps its own `sqlite3.Error` handler and its own closed-store answer, because the three answers differ:\n- the read answers no row, not available;\n- the enqueue answers `{\"state\": \"none\", \"available\": false}`;\n- the track store gains one info log line on a closed store, which is the operator's decision.\n\nThe enqueue's beat check and enqueue stay inside one `with`. The route tests' `SimpleNamespace` fake is untouched.\n\n**Resolve a translatable video (issue 57).** `resolve_translatable_video(conn, video_id, host, error_threshold)` lives in `handlers/internal_translate.py`. That is the route's own module, and the worker already imports it via `api/` on `sys.path`. It returns `(row, None)` or `(None, refusal)` and writes no response. The refusal is one of three strings:\n- `missing host`, for a `None` or empty host, decided before any lookup;\n- `not in whitelist`, when `fetch_video_row` with the threshold finds no row;\n- `host denied`, when the row's `normalize_host(instance_domain)` is in `list_active_denied_hosts(conn)`.\n\nThe middle two are exactly the worker's current texts.\n\n- **Route:** `_resolve_translate_key` keeps its own body validation and its three 400s. It calls the shared function on `server.db` under one `server.db_lock` hold, which merges today's two hold sites into one, with `server.video_error_threshold`. Any refusal maps to 404 `VIDEO_NOT_FOUND`, and the route keeps using the canonical `video_id`, `instance_domain` and `video_uuid or video_id`. It drops its `resolve_video_row` import.\n- **Worker:** `resolve_video` keeps its signature (tests monkeypatch it), its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its duration bound. Refusals pass through unchanged, except `missing host`, which maps to `not in whitelist`. That is what an empty host yields today, and `enqueue` refuses such a host earlier anyway. `generate`'s `OperationalError` \u2192 `WhitelistBusy` mapping and all exit codes are untouched.\n\n**Tests.** Rewritten only where the removed functions, the claim tuple or the claim's return are used:\n- `test_subtitles.py`: the subprocess writer script, the claim test's subscripting, the `fetch_subtitle_state` test and the recovery test, which now goes through the lock-taking opener.\n- `test_internal_translate.py`: `_claimed` and `_seed`, plus the two running/failed sequences at `:755-792`.\n- `test_translate_worker.py`: `Rig.claim`, `Rig.run` and the fetch-reason test's `run_job` call, because `run_job` no longer takes a connection.\n\nNew tests:\n- a parametrised store test for the six handle methods: after a `store_ready_subtitles` takeover, each returns `False` and leaves the row byte-identical;\n- the instance-track end while the claim holds;\n- the opener on a fresh nested path and on a B1-era file;\n- the route's closed-store log line.\n\nThe existing worker test for \"the instance holds an English track\" should pass unchanged in its assertions.\n\n**Docs.** Three docs are updated:\n- `TRANSLATE_WORKER.md`: the start-order step that names `ensure_subtitles_schema` and recovery, the handle and its methods, the opener and the flock tie, and \u00a7 Takeover only where it names removed functions.\n- `engine/server/README.md` \u00a7 \"Translate worker and its store contract\": the same three topics.\n- The module docstrings of the three code files.\n\n### Alternatives considered\n\n- **Handle takes the connection per call.** This would keep `run_job(conn, job, \u2026)` and spare two test call sites. Rejected: the handle would be pairable with any connection, including the heartbeat's, and `generate`/`translate_audio` would keep threading a connection whose only job is to match the claim's.\n- **Raise a `ClaimLost` exception from the store.** Rejected: the worker would then need a second exception mapped onto `JobTakenOver` (and removing `JobTakenOver` is out of scope). The requeue and end-failed calls in `run_job`'s handlers, which ignore a lost claim today, would need new try blocks. `bool` is today's contract and changes no control flow.\n- **Recovery takes the lock fd as an argument.** This is the other acceptable shape. Rejected because the service would still call open and then recover as two steps. Folding open and recovery behind the lock check gives the service one call and leaves no public recovery to misuse.\n- **A lock object or class for the flock.** Rejected as an interface with one implementation: the raw fd plus a non-blocking re-assert is the proof.\n- **Put the resolve in `handlers/video.py` or a new module.** `video.py` is the generic video module and the denylist rule is translate-specific. A new module would be one more file. `internal_translate.py` is already imported by both callers.\n- **A route helper that takes a callable and a closed-store default.** It would centralise the `None` branch too. Rejected because the three sites' closed answers and error handling differ, so the callable form would need three lambdas and a default per site. That is more indirection than the repetition it removes.\n- **Heartbeat on the full opener.** Rejected, as above: a redundant migration transaction per start for no guarantee gained.\n\n### Risks and gotchas\n\n- **flock semantics.** A flock belongs to an open file description, so the re-assert succeeds only on the descriptor the worker locked. A second `os.open` of the same lock file in the same process is refused, which is what the test relies on. On an unlocked descriptor the re-assert acquires the lock rather than failing. That still satisfies \"never recover without the flock\", but the docstring must say so plainly.\n- **The Engine opener now creates a missing parent directory.** For the default path it already exists, because of the random-cache `mkdir` just before. For a custom `--subtitles-db` in a missing directory, start-up now succeeds where it failed before. The open is still after `prepare_trending_override`, so a rejected start still creates nothing.\n- **Route resolve now uses one `db_lock` hold instead of two.** It holds the lock marginally longer and removes a window between lookup and denylist read. Responses do not change.\n- **NaN in instance-track cues.** The instance-track end must keep the NaN-allowing encoding by contract. `parse_webvtt` cannot produce NaN, so this only matters for fidelity with `store_ready_subtitles`. Sharing one encoding helper keeps the two from drifting.\n- **Stale copies outside the active suite.** `delete_me/` and `tests/tmp/` probes import the removed functions and will break if run. They are not in the active suite and are left alone.\n- **Unverified baseline.** The three active test files were not freshly run at baseline. A pre-existing red there would show up during this build and look like a regression.\n\n### Tradeoffs the operator is asked to accept\n\n- **`run_job` loses its connection argument.** The worker tests' `Rig.run` and the fetch-reason test change their `run_job` call. These are the call sites that pass the claim's result, but strictly it is a signature change beyond the removed functions.\n- **The recovery test changes.** `test_subtitles.py`'s recovery test now goes through the lock-taking opener because recovery is private. This follows from the flock requirement, not from the removed-function list.\n- **The handle is not subscriptable.** Tests that read `job[\"started_at\"]` from `claim_translate_job` switch to attributes.\n- **New log line.** The route's closed-store track store gains one info log line (the operator's decision). This is a second small observable change beside the approved instance-track one.\n- **`missing host` folds into `not in whitelist` on the worker side.** The worker reports a missing-host refusal as `not in whitelist`, to keep its texts unchanged. Today's behaviour is the same, but the two causes stay indistinguishable in the worker's error column.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n\n<impacts>\n<impact path=\"engine/server/data/subtitles.py\" element=\"module docstring (line 3)\">\n**What changes.** The docstring says \"B1's route upserts state 'ready' with source 'instance'\", and describes job columns \"added in place by ensure_subtitles_schema\". It must now describe four things:\n- the claim handle (`TranslateJob`) and its six claim-conditional methods;\n- `open_subtitles_db` as the one opener (mkdir, then WAL connect, then migrate);\n- `open_translate_worker_store` as the only way to run recovery, and only under the worker's flock;\n- the instance-track writers: the state route's unconditional `store_ready_subtitles` and the handle's conditional instance-track end.\n\n**Depends on it.** Nothing at runtime.\n\n**Risk.** None functionally. It goes stale if left alone, because \"B1's route\" is the wording the plan retires.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"imports (lines 5-12)\">\n**What changes.**\n- Add `from dataclasses import dataclass` for `TranslateJob`.\n- `fcntl` must NOT be imported at module level. The plan imports it inside `open_translate_worker_store` only, so the Engine's import of this module gains nothing.\n- `json`, `sqlite3`, `time`, `contextmanager`, `Path`, `Any` and `Iterator` stay.\n\n**Depends on it.** These modules import this one:\n- `server.py` (line 106);\n- `internal_translate.py` (line 22);\n- `translate-worker.py` (line 44);\n- the three active test files, including the subprocess scripts in `test_subtitles.py` (UPGRADE_SCRIPT, ENGINE_SCRIPT, WORKER_SCRIPT), which import `data.subtitles` under ENGINE_PY.\n\n**Risk.** Low. A module-level `fcntl` import would still work on Linux, but it breaks the plan's stated guarantee.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"SOURCE_INSTANCE constant (new, beside SOURCE_WHISPER at line 16)\">\n**What changes.** `SOURCE_INSTANCE = \"instance\"` moves here from `internal_translate.py:29`.\n\n**Depends on it.**\n- `internal_translate.py`: re-imports it, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves. `_store_cues` uses it at line 182.\n- The new handle method for the instance-track end uses it to fix the source.\n- `translate-worker.py:47` imports it today. After this change it must not, or it has to import it from its new home.\n- Stale copies import it from `handlers.internal_translate`: `delete_me/test_53_source_instance_fetch_adapter_phase2.py` and the `tests/tmp/probe_53_*` files. They still resolve, because the route keeps the name.\n\n**Risk.** Low. Tests write the literal `\"instance\"` (`test_internal_translate.py:618`, `test_translate_worker.py:1042`, `test_subtitles.py:107`), so the value must stay byte-identical.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"store_ready_subtitles (lines 104-115) and the new private instance-cues encoder\">\n**What changes.** The inline `json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))` at line 114 moves into a new private helper, which the instance-track handle method also uses. The encoding must stay exactly as it is: NaN allowed, so no `allow_nan=False`. It must NOT become `_cues_text`. Signature, upsert SQL and docstring otherwise stay. The docstring's \"a running job's conditional updates then match nothing\" still holds, and now covers the instance-track end as well.\n\n**Depends on it.**\n- `internal_translate._store_cues` (line 182), which is the takeover writer.\n- Tests: `test_internal_translate._seed` (lines 618, 620); `test_translate_worker.py:1042`, the B1 takeover test; `test_subtitles` ENGINE_SCRIPT (line 107); the new parametrised takeover test.\n- `test_internal_translate.py:502` asserts the stored `cues_json` is compact, with no space and no newline.\n\n**Risk.** Medium-low. If the helper picks up `allow_nan=False` or a different separator, the compact assertion at :502 or byte-identity across the two writers breaks. NaN cannot come out of `parse_webvtt`, so a divergence there would go unnoticed by tests.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"_cues_text (lines 118-120)\">\n**What changes.** Nothing. It stays the encoder for running cues and for the whisper ready end (`allow_nan=False`).\n\n**Depends on it.** The handle's running-cues and end-ready methods.\n\n**Risk.** The danger is the instance-track end reusing `_cues_text` by mistake. That would make a NaN raise where `store_ready_subtitles` accepts it, which breaks the plan's encoding contract.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"TranslateJob frozen dataclass and its six methods (new)\">\n**What changes.** A new `@dataclass(frozen=True)` with these fields: the claiming connection, `video_id`, `instance_domain`, `target_language`, `started_at`, `attempts`. Six methods, each a thin `_update_claim` call returning `bool`, with the timestamp passed in by the caller:\n- **running cues:** `cues_json = _cues_text(cues), detected_language = ?`. Today's `store_running_cues`, line 167.\n- **end ready:** `state='ready', cues_json, fetched_at = finished_at`. Today's `finish_translate_ready`, line 177.\n- **end already_english:** `state='already_english', detected_language, finished_at`. Line 182.\n- **end failed:** `state='failed', error, finished_at`. Line 187.\n- **requeue:** `state='queued', attempts = attempts - 1`, `queued_at` untouched. Line 172.\n- **end ready from an instance track (new):** `state='ready', source='instance', track_text, cues_json` (NaN-allowing encoder), `fetched_at = finished_at`. One timestamp, and no other column touched.\n\nThe SET strings must be copied exactly.\n\n**Depends on it.** The worker (`translate_audio`, `generate`, `run_job`, `serve`) and every test that claims a job.\n\n**Risk.**\n- **High.** Today the instance-track pair sets `fetched_at` and `finished_at` from two separate `now_ms()` calls. The new method must take one value and set both.\n- The `attempts - 1` text has to stay.\n- Equality: a frozen dataclass holding a `sqlite3.Connection` compares and hashes the connection field. That is harmless, but `repr` will print the connection object.\n- The class is not subscriptable, so every `job[\"...\"]` reader breaks. See the test entries and `serve` at `translate-worker.py:495`.\n- Method names are a design choice and are not fixed here. The next step should check them against the docs that will name them.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"claim_translate_job (lines 139-147)\">\n**What changes.** Name, signature and the IMMEDIATE transaction stay. The return type goes from `sqlite3.Row | None` to `TranslateJob | None`. The handle is built from the re-read row (line 147) plus the `target_language` argument and `conn`. The docstring must say it returns a handle.\n\n**Depends on it.**\n- `translate-worker.serve` (line 485).\n- `test_subtitles.py`: lines 133-141 (WORKER_SCRIPT, including `tuple(job)` in the error message at 135, which raises TypeError on a dataclass, though only on the failure path), 338-340, 363-372 and 394.\n- `test_internal_translate.py:610` (`_claimed`).\n- `test_translate_worker.py`: 542-544 (`Rig.claim`) and 922.\n\n**Risk.** Medium. Every subscript reader fails at once with TypeError, which at least makes it loud. The transaction itself does not change.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"_update_claim (lines 158-162)\">\n**What changes.** It takes the handle (or its fields) instead of a loose `(conn, video_id, instance_domain, target_language, started_at)`. It keeps the single `UPDATE \u2026 WHERE {_KEY} AND state = 'running' AND started_at = ?` inside `with conn:` and returns `rowcount == 1`. Its docstring must stop saying \"B1's route took the row over\". Instead it names the state route's instance-track store racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer.\n\n**Depends on it.** The six handle methods only.\n\n**Risk.** Medium. Any change to the WHERE clause or its parameter order breaks every conditional write. The new takeover test is the guard: each method must return False and leave the row byte-identical.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"store_running_cues, requeue_translate_job, finish_translate_ready, finish_translate_already_english, finish_translate_failed, mark_translate_finished (lines 165-193): deleted\">\n**What changes.** All six module-level functions are removed.\n\n**Depends on it.** Active code:\n- `translate-worker.py:44`, the import, and the call sites at 372, 378, 387, 408, 442, 446, 452 and 459.\n\nActive tests:\n- `test_subtitles.py`: 119, 137-141 (WORKER_SCRIPT, inside a string, so grep for the import misses it), 388 and 395;\n- `test_internal_translate.py`: 615, 625, 627, 629, 755, 759, 768, 779 and 792.\n\nStale and inactive files: `tests/tmp/probe_45_*`, `probe_50_phase1_rows.py`, `probe_53_*` (13 hits each), `probe_green.py`, `probe_race.py`, `probe_phase2_worker_cli.py`, `delete_me/*.bak*`.\n\n**Risk.** High for the active tests. A missed reference is an ImportError, and in WORKER_SCRIPT it only shows up as a subprocess exit code. The stale probes will break if run; the plan accepts that.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"recover_translate_jobs (lines 150-155), renamed private _recover_translate_jobs\">\n**What changes.** It is renamed to `_recover_translate_jobs`. The logic is unchanged: fail at `attempts >= MAX_CLAIMS` with RECOVERY_ERROR and `finished_at`, then requeue the remaining running rows, in one IMMEDIATE transaction. The docstring's \"only under its flock\" is now enforced by its only caller.\n\n**Depends on it.**\n- `translate-worker.py:44` and `:536`.\n- `test_subtitles.py:347`, `:366` and `:372`, the recovery test, which must now go through `open_translate_worker_store`.\n- The `test_subtitles.py:17` docstring bullet.\n\n**Risk.** Medium. The failed-before-requeued statement order inside the transaction is what makes `(2, 1)` come out right in the test, so it must stay.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"open_subtitles_db(path) (new)\">\n**What changes.** A new public opener:\n1. `path.parent.mkdir(parents=True, exist_ok=True)`;\n2. `connect_subtitles_db(path)`;\n3. `ensure_subtitles_schema(conn)`.\n\nOn any exception from the migration it closes the connection and re-raises.\n\n**Depends on it.**\n- `server.py:371-372`;\n- `translate-worker.command_enqueue` (`:131-135`);\n- `open_translate_worker_store`;\n- new tests on a fresh nested path and on a B1-era file;\n- possibly `test_internal_translate._subtitles_db`, if it is switched to it. That is optional.\n\n**Risk.**\n- Low-medium. It must catch `BaseException`, or at least `Exception`, for the close. A missing close only leaks the connection.\n- The concurrent-upgrade guarantees (WAL retry and the one-IMMEDIATE migration) come from the two composed functions, so `test_subtitles`' 24-round race test is unaffected as long as it keeps calling them directly.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"open_translate_worker_store(path, lock_fd, finished_at) (new)\">\n**What changes.** A new public opener for the worker service:\n1. Import `fcntl` locally.\n2. Call `fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)`. `BlockingIOError` propagates before any mkdir, connect or file creation.\n3. Call `open_subtitles_db(path)`.\n4. Call `_recover_translate_jobs(conn, finished_at)`.\n5. Return `(conn, (requeued, failed))`.\n\n**Gap in the plan:** it says the opener closes the connection when the migration fails, but not when recovery raises. This function should close `conn` if `_recover_translate_jobs` raises. Today `command_run`'s `finally` closes it (lines 541-545); after the change `conn` is never bound in `command_run` if the opener raises.\n\n**Depends on it.**\n- `translate-worker.command_run`;\n- new tests: a second `os.open` description holding the lock makes it raise and leaves the subtitles file absent; with the lock held, recovery runs as today's test expects.\n\n**Risk.** High.\n- **flock semantics:** the re-assert is a no-op only on the same open file description. On an unlocked fd it acquires the lock, and the docstring must say so.\n- **Ordering:** mkdir must come after the flock, or a refused call creates a directory. The new test checks only that the file is absent.\n- **Fd ownership:** it must not close or unlock `lock_fd`; `command_run` still owns it (line 547).\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"connect_subtitles_db, ensure_subtitles_schema (lines 25-77): stay public\">\n**What changes.** Nothing in the code.\n\n**Depends on it.**\n- `translate-worker.heartbeat_loop` (line 465) keeps `connect_subtitles_db`.\n- Tests use both directly: `test_subtitles.py` (82-88, 97-104, 119-126, 192-195, 217-230); `test_internal_translate.py:418-424`; `test_translate_worker.py:87`, `271-272`, `507-508`, `912-913`, `1041` and `1260`.\n- `server.py` and the worker's enqueue stop calling them directly.\n\n**Risk.** None, if they are left as they are.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"fetch_ready_subtitles, fetch_subtitle_state, fetch_translate_heartbeat, enqueue_translate_job, write_translate_heartbeat, _immediate, _KEY, MAX_CLAIMS, RECOVERY_ERROR, JOB_COLUMNS\">\n**What changes.** Nothing.\n\n**Depends on it.** The route, the worker, the tests and `engine/server/README.md:35-36`.\n\n**Risk.** None. Listed so the next step can confirm they stay as they are.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"module docstring (lines 1-8)\">\n**What changes.**\n- Paragraph 2 (\"An unknown or denylisted video answers 404 \u2026 before any remote fetch or store read\") stays true. It should say the resolve goes through `resolve_translatable_video`, shared with the worker.\n- Paragraph 3 (enqueue: \"validates and resolves exactly as the state route does \u2026 a closed store included\") stays true.\n- Mention the new info log line for a closed store on the track store.\n\n**Depends on it.** Nothing at runtime.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"imports (lines 9-26)\">\n**What changes.**\n- Drop `from handlers.video import resolve_video_row` (line 24). Add `from handlers.video import fetch_video_row`, which the shared resolve needs.\n- Add `SOURCE_INSTANCE` to the `data.subtitles` import (line 22).\n- Add `contextmanager` (and `Iterator` for typing) for `_subtitles_store`.\n- `list_active_denied_hosts` and `normalize_host` stay, now used by the shared resolve as well as the body check.\n\n**Depends on it.**\n- `router.py:41` imports `handle_internal_translate` and `handle_internal_translate_enqueue`.\n- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track`, and the new `resolve_translatable_video`.\n- `test_internal_translate.py` loads it via `importlib.import_module(\"handlers.internal_translate\")` (lines 290-294, 391-394).\n- `test_source_fetch.py:25` imports helpers from `test_internal_translate`.\n\n**Risk.**\n- Import cycle: `handlers.video` does not import `internal_translate`, so there is no cycle.\n- The module must stay free of numpy and faster-whisper, because the worker's enqueue path imports it.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"SOURCE_INSTANCE (line 29) and VIDEO_NOT_FOUND comment (line 34)\">\n**What changes.**\n- Line 29's local definition is replaced by the import from `data.subtitles`. The name still resolves as a module attribute.\n- Line 34's comment, \"The body resolve_video_row answers, reused for a denied host\", goes stale: the route no longer calls `resolve_video_row`, and now maps every refusal to this body itself. It must be reworded.\n\n**Depends on it.** `VIDEO_NOT_FOUND` must stay `{\"error\": \"Video not found\"}`. The tests' `VIDEO_NOT_FOUND` constant and the Client's `TRANSLATE_NOT_FOUND_ERROR` pin it.\n\n**Risk.** Low, provided the literal is unchanged.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"resolve_translatable_video(conn, video_id, host, error_threshold) (new)\">\n**What changes.** New. It returns `(row, None)` or `(None, refusal)`:\n- `missing host` for a None or empty host, decided before any query;\n- `not in whitelist` when `fetch_video_row(conn, video_id, host, error_threshold=\u2026)` returns None;\n- `host denied` when `normalize_host(row[\"instance_domain\"]) in list_active_denied_hosts(conn)`.\n\nIt writes no response and takes no lock.\n\n**Depends on it.** `_resolve_translate_key`, and the worker's `resolve_video`.\n\n**Risk.** Medium.\n- **Order.** The order must be: host check, then the row lookup, then the denylist read only when a row exists. The worker test \"any other OperationalError\" (`test_translate_worker.py:1079-1091`, drop-column and zero-byte cases) relies on `fetch_video_row` raising first with its own text.\n- **Empty host.** A truthy check on host matters: `fetch_video_row` with a None host matches any host.\n- **Denylist case.** The denylist row is stored uppercase in the tests. `list_active_denied_hosts` normalises it, so the comparison must stay on normalised values.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_resolve_translate_key (lines 187-215)\">\n**What changes.**\n- Body validation and its three 400s stay byte-identical: `read_json_body`'s message, `Missing id or host`, `Invalid host`.\n- The `resolve_video_row` call (line 203) and the separate denylist hold (lines 210-214) become one `with server.db_lock:` around `resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)`.\n- Any refusal gives 404 `VIDEO_NOT_FOUND`.\n- It returns `(body, row[\"video_id\"], row[\"instance_domain\"], row[\"video_uuid\"] or row[\"video_id\"])`.\n\n**Depends on it.** Both handlers, and these tests:\n- the 404 parity tests at `test_internal_translate.py:462-488` and `936-962`;\n- the REFUSED table (`924-933`), which includes \"known uuid on another host\";\n- the startup test at 1028-1031, which posts an unknown video to the live Engine.\n\n**Risk.** Medium.\n- `resolve_video_row` used to answer 400 `Missing video id` for an empty id. That is unreachable here, because the route already answers `Missing id or host`. Do not reintroduce it.\n- The route must keep passing the normalised host.\n- The lock is held slightly longer. The SimpleNamespace fake's `db_lock` is a plain `threading.Lock`, so it must not be re-entered.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_subtitles_store(server) context manager (new)\">\n**What changes.** New `@contextmanager`. It holds `server.subtitles_db_lock` for the whole body and yields `server.subtitles_db`, which may be None. It must not catch exceptions: each caller keeps its own `sqlite3.Error` handler outside the `with`.\n\n**Depends on it.** `_read_key`, `_store_cues` and the enqueue.\n\n**Risk.** Medium-low.\n- A generator-based context manager that wraps `yield` in try/except, or one that holds the lock only around the attribute read, would break the \"one lock hold\" guarantee of the enqueue (beat read plus insert). That guarantee is pinned by the README at line 23.\n- The SimpleNamespace fake supplies `subtitles_db` and `subtitles_db_lock`, and the plan leaves it untouched.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_read_key (lines 154-164)\">\n**What changes.** It uses `_subtitles_store`. A closed store still returns `(None, False)`. A `sqlite3.Error` is still logged `[translate] cache read failed \u2026` and returns `(None, False)`.\n\n**Depends on it.** `handle_internal_translate`, and the tests at `test_internal_translate.py:699-710`, 688-696 and 728-740.\n\n**Risk.** Low.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_store_cues (lines 176-184)\">\n**What changes.** It uses `_subtitles_store`. A new INFO log line is written when the store is closed (operator decision); the wording is for the next step to choose. `sqlite3.Error` is still logged `[translate] cache write failed \u2026`. `store_ready_subtitles` stays the unconditional writer, with `SOURCE_INSTANCE` now imported.\n\n**Depends on it.**\n- `handle_internal_translate`, at line 245.\n- A new route test: closed store plus an instance track gives the log line, and the answer stays `ready`.\n- The `_failed_fetches` helper (`test_internal_translate.py:528-529`) filters on the `[translate] instance fetch failed` prefix. The new line must not start with that prefix, or the NONE_CASES exact-list assertions could pick it up.\n\n**Risk.** Low-medium. This is a new observable log line, and the NONE_CASES/budget tests compare exact lists of failed-fetch lines.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate_enqueue (lines 253-273)\">\n**What changes.** The beat check and `enqueue_translate_job` stay inside one `with _subtitles_store(server) as conn:`. A closed store still gives `{\"state\":\"none\",\"available\":false}`, and a `sqlite3.Error` still gives 503 `Translate store unavailable` with the `[translate] enqueue failed` log.\n\n**Depends on it.** Tests at `test_internal_translate.py:830-920`.\n\n**Risk.** Low-medium. The availability check must stay inside the same hold.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate, _generation_available, fetch_instance_track, parse_webvtt, pick_english_track_path, TARGET_LANGUAGE, HEARTBEAT_FRESH_MS\">\n**What changes.** Nothing beyond the call into `_resolve_translate_key`. The docstring of `_generation_available` (\"The caller holds subtitles_db_lock\") stays true.\n\n**Depends on it.** The worker imports `TARGET_LANGUAGE` and `fetch_instance_track`.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"resolve_video_row (lines 260-282) and fetch_video_row (lines 24-78)\">\n**What changes.** Nothing. `resolve_video_row` loses its translate caller but keeps its `/api/video` caller at line 447. `fetch_video_row` gains a caller: the new shared resolve.\n\n**Depends on it.** `/api/video`, `/api/video/refresh` and `test_video.py`.\n\n**Risk.** None, if nothing in it changes. Do not delete `resolve_video_row`.\n</impact>\n<impact path=\"engine/server/api/router.py\" element=\"import of handle_internal_translate/handle_internal_translate_enqueue (line 41) and POST_ROUTES (141-142)\">\n**What changes.** Nothing. The handler names are unchanged.\n\n**Depends on it.** Engine routing. `test_router.py` and the startup test in `test_internal_translate.py`.\n\n**Risk.** None. Listed so the next step can confirm the handler names are unchanged.\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 8 (internal_translate summary)\">\n**What changes.** Optional. It could mention that the module also holds the translatable-video resolve shared with the worker. Nothing it says now is false.\n\n**Depends on it.** Nothing.\n\n**Risk.** None. I am unsure whether the doc pass will want this line touched.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"import (line 106) and the subtitles open (lines 369-372)\">\n**What changes.**\n- Line 106 changes to `from data.subtitles import open_subtitles_db`.\n- Lines 371-372 become `subtitles_db = open_subtitles_db(subtitles_db_path)`, in the same place: after `prepare_trending_override` (351) and after the random-cache mkdir (369).\n- The comment at 370 (\"After the mkdir above (the default lives in the same directory)\") goes partly stale, because the opener now creates its own parent. It should be reworded to keep only the \"after prepare_trending_override, so a rejected start creates nothing\" point.\n- `server.subtitles_db = subtitles_db` (504) and the shutdown close (575-579) are unchanged.\n\n**Depends on it.**\n- `test_internal_translate.py:998-1039`: the Engine start creates a missing `subtitles.db` at an overridden path.\n- Every test group listing `server.py` in `tests/config.json`: `test_similar`, `test_server_config`, `test_internal_events`, `test_random_cache` and `test_internal_translate`. Each starts the Engine, so all of them exercise this line.\n\n**Risk.** Low-medium. Behaviour change: a custom path in a missing directory now starts instead of failing. The plan accepts this, and the README Notes should say so.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"module docstring (lines 2-9)\">\n**What changes.**\n- Line 8 (\"run is the service, in this order: ffmpeg check, flock \u2026, schema and crash recovery \u2026\") should name the lock-checked store opener: the flock is re-asserted, then open, migrate and recover.\n- Line 6 (`run_job` \"takes one claimed job \u2026\") should say it now takes the claim handle.\n- Line 4 (enqueue \"resolves \u2026 the way B1's /internal/translate does\") should name the shared `resolve_translatable_video`.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"imports (lines 41-48)\">\n**What changes.**\n- Line 44 becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat`. The six removed functions, `ensure_subtitles_schema`, `recover_translate_jobs` and `store_ready_subtitles` drop out. `connect_subtitles_db` is still needed by `heartbeat_loop`.\n- Line 47 drops `SOURCE_INSTANCE` and adds `resolve_translatable_video`.\n- Line 48, `from handlers.video import fetch_video_row`, becomes unused once `resolve_video` delegates. Remove it.\n- Line 43: `list_active_denied_hosts` becomes unused. `normalize_host` stays for `command_enqueue`.\n- Update the comment at 35, which says \"api/ is for server_config, handlers.video.fetch_video_row and the route's fetch_instance_track and constants\".\n- `fcntl` (14) and `sqlite3` (22) are still used.\n\n**Depends on it.**\n- `_worker()` in `test_translate_worker.py:254-259` and STALL_DRIVER (212-220) both exec the module, so an ImportError fails every worker test.\n\n**Risk.** Medium, since one bad import fails the whole module. Lint-level only otherwise.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"JobTakenOver docstring (lines 87-88)\">\n**What changes.** Replace \"B1's route replaced the running row\" with the real writer: the Engine state route's instance-track store (`store_ready_subtitles`), racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. The class itself stays; removing it is out of scope.\n\n**Depends on it.** `translate_audio`, `generate` (new raise) and `run_job`.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"resolve_video (lines 95-112)\">\n**What changes.**\n- The signature `(whitelist_path, video_id, host, max_duration)` stays, because tests monkeypatch it with a 4-argument stand-in at `test_translate_worker.py:661` and at 1102-1103 and 1129-1130.\n- Kept: the `connect_readonly_db` connection, `PRAGMA busy_timeout = 30000` and the close in `finally`.\n- The body calls `resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)`. The refusal `missing host` maps to `not in whitelist`; the others pass through. The duration bound stays after the row check, with its text `duration {d}s over {m}s`.\n\n**Depends on it.** `command_enqueue`, `generate` and these tests:\n- the enqueue refusals table (`test_translate_worker.py:136-138`);\n- the claim refusals (348-349);\n- the stall test's expected `failed`/`not in whitelist` (1283);\n- the whitelist-at-claim tests (1063-1091), which need `OperationalError` texts to come out unchanged so the WhitelistBusy classification in `generate` still applies.\n\n**Risk.** Medium.\n- `connect_readonly_db` raising on a deleted file (`unable to open`) must still happen before `resolve_translatable_video`, as today.\n- The duration check must stay on the returned row dict.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_enqueue (lines 115-150)\">\n**What changes.** Lines 131-135 (mkdir, connect, ensure) become `conn = open_subtitles_db(args.subtitles_db)` inside the existing `try \u2026 except sqlite3.Error`, with `enqueue_translate_job` and the close in `finally`. Output lines and exit codes are unchanged.\n\n**Depends on it.** The enqueue CLI tests (`test_translate_worker.py:763+`), which run the script as a subprocess, and `DEPLOYMENT.md:281-291`.\n\n**Risk.** Low. An `OSError` from mkdir is not a `sqlite3.Error`, so it still propagates uncaught. Today it is raised outside the try, so the behaviour is the same. The structure needs care so that `conn` is defined before the `finally` close.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"translate_audio (lines 346-389)\">\n**What changes.** The `conn` and `claim` parameters are replaced by the handle, e.g. `translate_audio(job, pipe, runner, max_chunk, stop, progress)`. The three conditional writes become handle methods:\n- 372: already_english, with `language, now_ms()`;\n- 378: running cues, with `cues, language`;\n- 387: end ready, with `cues, now_ms()`.\n\nEach still raises `JobTakenOver` on False. Control flow is unchanged.\n\n**Depends on it.** `generate`, and the pipeline tests: 947-963 (running cues per chunk, observed through the `cues_writes` trigger at 509-512), 966-976, 979-1001 and 1033-1050 (B1 takeover mid-job).\n\n**Risk.** Medium. The order \"already_english written before any cue\" and \"running cues only when `new` is non-empty\" must stay exactly as it is.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"generate (lines 392-432)\">\n**What changes.**\n- The signature drops `conn`; `claim` becomes the handle.\n- Line 395 becomes `resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)`.\n- Lines 407-408 (the unconditional upsert, then the `mark_translate_finished` stamp) become a single handle call to the instance-track end with `fetched[0], fetched[1], now_ms()`. If it returns False, raise `JobTakenOver`. If True, return `\"ready from the instance track\"`.\n- Line 430 passes the handle to `translate_audio`.\n- The docstring (\"AC3 for one claim (video_id, instance_domain, target_language, started_at)\") must name the handle.\n- The `OperationalError` to `WhitelistBusy` mapping is unchanged.\n\n**Depends on it.**\n- `test_translate_worker.py:1016-1030`: the instance holds an English track, which must end ready/instance with `cues_json == CUES`, `track_text == TRACK` and `finished_at` within the window. It should pass unchanged.\n- `run_job`'s takeover log line.\n\n**Risk.** High. This is the one approved behaviour change: after a takeover, the worker no longer overwrites the Engine's row. No existing test covers the lost-claim instance path. The plan's new store test covers the method; nothing yet drives `generate` on a taken-over row. The UPDATE must also leave `detected_language`, `error`, `attempts`, `queued_at` and `started_at` untouched.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"run_job (lines 435-460)\">\n**What changes.**\n- The signature drops `conn`: `run_job(job, args, runner, stop, progress) -> bool`. Line 437's tuple build is deleted.\n- Log lines use `job.video_id, job.instance_domain` in place of `*claim[:2]`, with the texts unchanged.\n- `requeue_translate_job(conn, *claim)` (442, 446) becomes `job.requeue()`.\n- `finish_translate_failed(...)` (452, 459) becomes the handle's end-failed method. Return values are still ignored.\n- The docstring's \"a row B1's route took over is left as B1 wrote it\" must name the real writer.\n\n**Depends on it.**\n- `serve` (line 496).\n- `Rig.run` (`test_translate_worker.py:554`) and the fetch-reason test (925), which call it with `conn` first.\n- `_run_broken` (640-649) and the whitelist tests that read its bool.\n\n**Risk.** Medium. A signature mismatch fails every pipeline test. The bool contract (True only for WhitelistBusy) must survive.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"serve (lines 479-502): not named by the plan\">\n**What changes.**\n- Line 495's log uses `job[\"video_id\"], job[\"instance_domain\"], job[\"attempts\"]` and must switch to attributes. That breaks at runtime with the handle, and the plan does not list it.\n- Line 496 becomes `run_job(job, args, runner, stop, progress)`.\n- The signature `serve(conn, args, runner, stop, progress)` stays, because it still claims on `conn`. The tests call it as `rig.worker.serve(rig.conn, \u2026)` at `test_translate_worker.py:1111` and 1136.\n\n**Depends on it.**\n- `command_run`;\n- the back-off tests at 1097-1163;\n- the subprocess stall and heartbeat tests, which claim through serve.\n\n**Risk.** High if missed. Every claimed job would raise TypeError at the log line. Inside serve that exception is not caught, so the worker process would die.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"heartbeat_loop (lines 463-476)\">\n**What changes.** Nothing. It keeps `connect_subtitles_db`, per the plan.\n\n**Depends on it.** The heartbeat and stall subprocess tests (1200-1294).\n\n**Risk.** None. The beat thread starts only after the main thread's opener has migrated the file, so the table exists.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_run (lines 511-549)\">\n**What changes.**\n- Its own LOCK_NB acquire, the `another worker holds` log line and exit 6 (517-525) stay first.\n- Lines 531-537 (mkdir, connect, ensure, recover) become `conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())`, followed by the same `started pid=\u2026 recovered requeued=\u2026 failed=\u2026` log line.\n- The try/finally must still close `conn` and join the beat. `conn` is now bound only once the opener returns, so the `finally` that closes it must start after that point. See the gap in the `open_translate_worker_store` entry.\n- The docstring (\"then schema, recovery, \u2026\") should name the opener.\n\n**Depends on it.**\n- The held-lock test (1169-1197): exits 6, writes nothing, leaves a B1 file byte-identical, no sidecars. It is protected because `command_run`'s own flock fails first.\n- The heartbeat and stall tests.\n- The `TRANSLATE_WORKER.md` start-order step 5 and `DEPLOYMENT.md:271`.\n\n**Risk.** Medium-high. Wrong try/finally placement either leaks the connection or raises NameError in `finally`. `lock_fd` must remain owned and closed by `command_run` (line 547).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"exception classes JobFailed/JobStopped/WhitelistBusy, AudioPipe, WhisperRunner, chunk helpers, exit codes, parse_args\">\n**What changes.** Nothing.\n\n**Depends on it.** Existing tests.\n\n**Risk.** None. Listed so the next step can confirm exit codes 0-6 and the CLI flags are untouched.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"module docstring (lines 1-24)\">\n**What changes.**\n- Line 12 (concurrent writers) names `claim_translate_job` \"which must hand back that key\", `store_running_cues` and `finish_translate_ready`. These become handle methods.\n- Line 14 names `connect_subtitles_db` + `ensure_subtitles_schema`.\n- Line 17 names `recover_translate_jobs`, which now runs through the lock-taking opener.\n- New bullets are needed for the handle-method takeover test, the instance-track end, both openers and the flock tie.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"WORKER_SCRIPT subprocess string (lines 115-147)\">\n**What changes.**\n- The import at 119 drops `finish_translate_ready` and `store_running_cues`.\n- 133-141 use `job.video_id` and `job.instance_domain`, then call the running-cues and end-ready methods on `job`.\n- Line 135's `tuple(job)` in the SystemExit message must change, because a dataclass is not iterable.\n\n**Depends on it.** `test_an_engine_and_a_worker_writing_one_file_at_once\u2026` (282-323) under ENGINE_PY.\n\n**Risk.** Medium. This code lives in a string, so a mistake shows up only as a non-zero subprocess exit, and grep for imports does not find it.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"claim test (lines 326-343)\">\n**What changes.** Line 340 reads `job[\"video_id\"]` and the other fields by subscript. It switches to attributes.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"recovery test (lines 346-378)\">\n**What changes.** `recover_translate_jobs` is private now, so each of the two recover calls (366, 372) goes through `open_translate_worker_store(path, lock_fd, 9000/9500)`, with the test holding a flock on a tmp lock file. Each call returns a new connection, which must be closed. `first[\"video_id\"]` (364) and `row[\"video_id\"]` (370) switch to attributes.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Medium.\n- Assertions must stay `(1, 0)` and `(2, 1)` with the bystander snapshot.\n- The test's own `conn` stays open alongside the opener's connection. That is fine in WAL.\n- The opener's migration runs again each time; it is idempotent.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"fetch_subtitle_state test (lines 387-400)\">\n**What changes.** Line 388 drops `store_running_cues` from the import. Line 394 keeps the handle instead of `[\"started_at\"]`. Line 395 calls the handle's running-cues method.\n\n**Depends on it.** Nothing.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"new tests (plan)\">\n**What changes.** New tests:\n- **Handle takeover (parametrised over the six methods):** after a `store_ready_subtitles` takeover, each returns False and the row is byte-identical. The `_snapshot` helper (205-213) suits this.\n- **Instance-track end while the claim holds:** state ready, source instance, `track_text`, compact `cues_json`, `fetched_at == finished_at`, other job columns unchanged.\n- **`open_subtitles_db`:** on a fresh nested path (parent created) and on a B1-era file (reuse `_b1_file`).\n- **`open_translate_worker_store`:** a second open file description holding the lock makes it raise `BlockingIOError` and leaves the file absent. With the lock held, recovery runs.\n\n**Depends on it.** `tests/config.json` group `test_subtitles.py`, which lists only `subtitles.py`.\n\n**Risk.** Low. For the flock test, the second `os.open` must be a separate open file description: a separate `os.open` in the same process, not `os.dup`.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"module docstring and _subtitles_db helper (lines 19, 418-424)\">\n**What changes.** Line 19 says the store is \"opened with `connect_subtitles_db` and `ensure_subtitles_schema`, as server.py does\", and `_subtitles_db`'s docstring says \"as server.py opens it at startup\". Both go stale. Either switch the helper to `open_subtitles_db`, or reword both. This is optional; the plan does not list it.\n\n**Depends on it.** Every route test, and `test_source_fetch.py:25`, which imports helpers from this module but not `_subtitles_db`.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"_claimed and _seed (lines 605-631)\">\n**What changes.**\n- `_claimed` returns the handle instead of `[\"started_at\"]`.\n- `_seed` drops `finish_translate_already_english`, `finish_translate_failed` and `store_running_cues` from its import (615), and calls the handle methods at 625, 627 and 629.\n- `store_ready_subtitles` and `enqueue_translate_job` stay.\n\n**Depends on it.**\n- BRANCHES tests (713-740), REFUSED_ROWS (797-815) and the \"stored key answers its state\" enqueue test (872-883).\n- `delete_me` and `tests/tmp` probes import `_seed` (e.g. `probe_50_phase1_rows.py`). They are stale.\n\n**Risk.** Medium. Every stored-state test runs through `_seed`.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"running-key tests (lines 753-794)\">\n**What changes.**\n- Lines 755 and 779 drop the removed imports.\n- `started_at = _claimed(store)` becomes a handle.\n- 759 becomes `job.<running cues>(RUNNING, \"fr\")`.\n- 768 and 792 become `job.<end failed>(\"boom\", NOW)`.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"new closed-store track-store log test (plan)\">\n**What changes.** A new test: a server with `subtitles_db = None` and an instance holding an English track answers `ready` and logs the new info line once.\n\n**Depends on it.** The `_store_cues` wording.\n\n**Risk.** Low. Existing closed-store tests (699-710, 844-856) use no-track instances and stay green.\n</impact>\n<impact path=\"tests/active/test_source_fetch.py\" element=\"import from test_internal_translate (line 25)\">\n**What changes.** Nothing, as long as `test_internal_translate`'s module-level names CHUNK, HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, WITHIN_CAP, Clock, Response, ScriptedInstance and `_body` keep importing.\n\n**Depends on it.** All of `test_source_fetch`.\n\n**Risk.** Low. A module-level import error in `test_internal_translate` would break this file too.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"module docstring (lines 1-50)\">\n**What changes.**\n- Line 10 gives the signature `run_job(conn, job, args, runner, stop, progress)`, which becomes `run_job(job, \u2026)`.\n- Line 35 names `Rig.run`.\n- Optionally add the lost-claim instance-track behaviour.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"Rig.claim and Rig.run (lines 538-554)\">\n**What changes.**\n- 544 reads `self.job[\"video_id\"]` and the other fields by subscript, and switches to attributes.\n- 554 becomes `self.worker.run_job(self.job, args, runner, \u2026)`.\n\n**Depends on it.** Every pipeline, bounds and whitelist-at-claim test through `rig.run`/`rig.claim`.\n\n**Risk.** Medium. A miss fails most of the file.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"fetch-reason test (lines 905-935)\">\n**What changes.** Line 925 becomes `worker.run_job(job, args, UnreachedRunner(), \u2026)`. The connection opened at 912-913 is still needed to claim and to close.\n\n**Depends on it.** Nothing.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"instance-track and takeover tests (lines 1016-1050)\">\n**What changes.** These should pass unchanged in their assertions.\n- 1016: ready/instance, CUES, TRACK, `finished_at` within the window.\n- 1033: the B1 takeover mid-job leaves the row untouched. This exercises the running-cues method returning False.\n\n**Depends on it.** `generate`'s new single call, and the handle.\n\n**Risk.** Medium. These are the guards that `fetched_at`/`finished_at` and the encoding still match. No test drives `generate` through a takeover that lands before the instance-track end. If the next step wants that path pinned, it is a candidate.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"serve back-off tests, service subprocess tests, enqueue CLI tests (lines 763-905, 1097-1294)\">\n**What changes.** Nothing in the tests:\n- `serve` keeps `(conn, \u2026)`;\n- the subprocess tests run the real `command_run` and `command_enqueue`;\n- `resolve_video` keeps its 4-argument signature for `_recording`.\n\n**Depends on it.** `serve`'s attribute access, `command_run`'s opener call and `command_enqueue`'s opener.\n\n**Risk.** Medium. These are the regression net for `command_run`. The held-lock test proves nothing is created when the lock is refused. The heartbeat test proves the opener plus recovery leave a working store.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups for subtitles.py, internal_translate.py, translate-worker.py, server.py\">\n**What changes.** Nothing.\n- `test_subtitles.py` maps only `subtitles.py`.\n- `test_internal_translate.py` and `test_translate_worker.py` map all three code files.\n- `server.py` is also mapped by `test_similar.py`, `test_server_config.py`, `test_internal_events.py` and `test_random_cache.py`, so the `server.py` edit pulls those Engine-start suites into the run.\n\n**Depends on it.** The test runner's group selection.\n\n**Risk.** Low. Worth knowing that the build's targeted runs will include those suites.\n</impact>\n<impact path=\"tests/tmp/probe_53_draft_translate_worker.py\" element=\"stale probes in tests/tmp (probe_45_*, probe_50_phase1_rows.py, probe_53_* (6 files), probe_green.py, probe_phase2_worker_cli.py, probe_race.py, probe_53_c1_answers.py)\">\n**What changes.** Nothing. The plan leaves them alone. They import or call removed functions (`claim_translate_job` subscripts, `finish_translate_*`, `store_running_cues`, `recover_translate_jobs`, `run_job(conn, \u2026)`) and will break if run.\n\n**Depends on it.** Nothing in the active suite.\n\n**Risk.** None for the active suite.\n</impact>\n<impact path=\"delete_me/test_53_source_instance_fetch_adapter_phase2.py\" element=\"stale delete_me copies (test_53_* and *.bak-harvest53-58-* of internal_translate.py, translate-worker.py, video.py)\">\n**What changes.** Nothing. They name removed functions and `SOURCE_INSTANCE` in the route.\n\n**Depends on it.** Nothing.\n\n**Risk.** None. They are out of the active suite.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"\u00a7 Run: Start-up Order step 5 (line 72), \u00a7 Job Pipeline step 2 (line 90), \u00a7 Stop, Crash and Recovery 'Crash' (line 147), \u00a7 Takeover (line 151), \u00a7 Enqueue (line 49), intro (line 13)\">\n**What changes.**\n- Line 72: \"Open `subtitles.db`, run `ensure_subtitles_schema`, then crash recovery\" becomes: the lock-checked store opener re-asserts the flock, then creates the directory, opens, migrates and recovers, and the counts are logged.\n- Line 90: \"If there is one, store it `ready` with source `instance` and the job is done\" must add \"while the claim holds; otherwise the job is taken over and nothing is written\".\n- Line 147: \"under the lock\" can name the enforcement, since recovery is reachable only through the lock-checked opener.\n- Line 151: \"once B1 has written\" can be reworded, and the instance-track end should be included among the conditional writes. The plan says to update this section only where it names removed functions. It names none, so this is optional.\n- Line 49: \"resolved as B1 does\" can name `resolve_translatable_video`.\n- New text on the claim handle and its methods.\n\n**Depends on it.** `engine/server/README.md:30` and `DEPLOYMENT.md:230` link here.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"\u00a7 Translate worker and its store contract (lines 29-36)\">\n**What changes.**\n- Line 32 (\"The store functions in `data/subtitles.py` are the contract\") gains: `open_subtitles_db` as the single opener; `claim_translate_job` returning a `TranslateJob` handle whose six methods each match only while the row is `running` with the claim's `started_at` and return False once taken over; `open_translate_worker_store` as the only recovery path, under the flock.\n- Line 34 (\"or `instance` when the instance gained an English track before the claim\") stays true, and could add \"while the claim holds\".\n\n**Depends on it.** `TRANSLATE_WORKER.md:13` refers to this README for the store functions.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate 'Checks before any fetch' bullet (line 17): not in the plan's doc list\">\n**What changes.** It says \"the video resolves as on `/api/video` (`resolve_video_row`, so the error-count threshold applies)\". The route no longer calls `resolve_video_row`, so the text must name `resolve_translatable_video`. That function still uses `fetch_video_row` with `video_error_threshold`, so the threshold claim stays true. The plan's docs list names only the store-contract section, so this would be missed.\n\n**Depends on it.** Readers of the Engine API docs.\n\n**Risk.** Documentation only, but the text would be factually stale.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate Cache bullet (line 19) and Notes start-up bullet (line 45)\">\n**What changes.**\n- Line 19 ends \"a store error is logged and the answer stays `ready`\". A closed store now also logs an info line, and this could say so.\n- Line 45 (\"at start opens `DEFAULT_SUBTITLES_DB_PATH` \u2026, creating the file when missing\") should say the parent directory is created too.\n\n**Depends on it.** Readers of the Engine docs.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"Instance caption track (line 19) and Claim (line 22) glossary entries\">\n**What changes.** Probably none.\n- Line 22 already says the worker \"drops the job without writing anything further\" on a takeover, which is now true for the instance-track end too.\n- Line 19 (\"The translate worker also stores one, with source `instance`, when it finds the track on claiming a job\") could add \"while its claim holds\". This is optional; the plan says no change unless the handle wording requires it.\n\n**Depends on it.** Glossary readers.\n\n**Risk.** None.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"subtitles.db paragraph (line 98) and run flag table (line 271)\">\n**What changes.** Probably none.\n- Line 271 (\"exits 6 without opening `subtitles.db`\") stays true.\n- Line 98 names `[translate] cache write failed` for a locked write. The closed-store info line occurs only during shutdown, so it is optional here.\n\n**Depends on it.** Operators.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/54-translate-job-handle.md\" element=\"Status line and archive move\">\n**What changes.** At delivery, per `docs/project/triage-labels.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. Issue 57 is already `wontfix` and folded in, so it needs no change. Issue 56 (`56-split-translate-worker.md`) depends on 54's handle and may want a note.\n\n**Depends on it.** The issue tracker.\n\n**Risk.** None. This is a tracker step, probably outside this build step.\n</impact>\n</impacts>\n\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\">\n- **Start-up Order step 5 (line 72):** replace `ensure_subtitles_schema` plus recovery with the lock-checked store opener: flock re-assert, mkdir, open, migrate, recover, then log the counts.\n- **Job Pipeline step 2 (line 90):** the instance track is stored ready/instance only while the claim holds; otherwise the job is taken over and nothing is written.\n- **New text:** the claim handle (`TranslateJob`), its six methods, each returning False after a takeover.\n- **Enqueue (line 49):** optionally name the shared `resolve_translatable_video`.\n- **Crash bullet (line 147):** recovery is reachable only through the lock-checked opener.\n- **\u00a7 Takeover (line 151):** touch only if wording requires; it names no removed function.\n</doc>\n<doc path=\"engine/server/README.md\">\n- **\u00a7 \"Translate worker and its store contract\" (lines 29-36):**\n  - `open_subtitles_db` as the single opener;\n  - `claim_translate_job` returning the `TranslateJob` handle with its claim-conditional methods;\n  - `open_translate_worker_store`, with recovery only under the flock.\n- **Line 17:** replace `resolve_video_row` with `resolve_translatable_video`. The threshold and denylist still apply.\n- **Line 19:** mention the closed-store info log line.\n- **Notes, line 45:** the Engine start now also creates the parent directory of `DEFAULT_SUBTITLES_DB_PATH`.\n</doc>\n<doc path=\"engine/server/data/subtitles.py\">\nModule docstring and docstrings to update:\n- `claim_translate_job` (returns a handle);\n- `_update_claim` and the handle (name the real takeover writer, not \"B1's route\");\n- `store_ready_subtitles` (shared encoder);\n- the two new openers (flock re-assert semantics, including that it acquires the lock on an unlocked fd);\n- `_recover_translate_jobs`.\n</doc>\n<doc path=\"engine/server/api/handlers/internal_translate.py\">\n- **Module docstring:** the shared resolve, and the closed-store log line.\n- **`VIDEO_NOT_FOUND` comment (line 34):** it no longer comes from `resolve_video_row`.\n- **Docstrings:** `_resolve_translate_key`, `_store_cues`, the new `_subtitles_store` and `resolve_translatable_video`.\n</doc>\n<doc path=\"engine/server/db/jobs/translate-worker.py\">\n- **Module docstring (lines 4, 6, 8):** the shared resolve, the handle, and the lock-checked opener in the start order.\n- **`JobTakenOver` docstring:** the real writer.\n- **`run_job`, `generate` and `command_run` docstrings:** update to match.\n- **Comment at line 35:** about what `api/` is on the path for.\n</doc>\n<doc path=\"engine/server/api/server.py\">\nThe comment at line 370 (\"After the mkdir above (the default lives in the same directory)\u2026\") goes partly stale, because the opener creates its own parent. Keep the `prepare_trending_override` ordering reason.\n</doc>\n<doc path=\"CONTEXT.md\">\nOptional: in \"Instance caption track\" (line 19), the worker stores the track only while its claim holds. \"Claim\" (line 22) already matches.\n</doc>\n<doc path=\"tests/active/test_subtitles.py\">\nModule docstring lines 12, 14 and 17 name removed or renamed functions. Add bullets for the new handle, opener and flock tests.\n</doc>\n<doc path=\"tests/active/test_translate_worker.py\">\nThe docstring's `run_job(conn, job, \u2026)` signature (line 10) becomes `run_job(job, \u2026)`.\n</doc>\n<doc path=\"tests/active/test_internal_translate.py\">\nDocstring line 19 and the `_subtitles_db` helper docstring say the store is opened \"as server.py does\" with `connect`+`ensure`. Reword, or switch the helper to `open_subtitles_db`.\n</doc>\n\n</docs_checklist>\n\n<highest_risk>\n1. **`translate-worker.py` `generate` plus the new instance-track handle method in `subtitles.py`.** This is the one approved behaviour change. One conditional UPDATE must set ready, source=instance, `track_text`, NaN-allowing compact `cues_json` and `fetched_at` = `finished_at` from one timestamp, leave every other job column alone, and raise `JobTakenOver` on False. No existing test drives `generate` through a lost claim at this point.\n2. **`subtitles.py` `open_translate_worker_store` and `translate-worker.py` `command_run`.** The flock re-assert has to come before any mkdir or open. The plan says nothing about closing the connection when recovery raises. `command_run`'s try/finally has to be rebuilt around a connection that now exists only after the opener returns. A mistake here either leaks the connection, raises NameError in `finally`, or writes to the store without holding the lock.\n3. **`translate-worker.py` `serve` (line 495) and `run_job` call sites, and `internal_translate.py` `_resolve_translate_key` with the new `resolve_translatable_video`.** `serve` reads `job[\"...\"]` by subscript, which the plan does not list. On a handle that raises TypeError, outside any handler, and kills the worker. The merged resolve has to keep the fetch-row, then denylist, order, its exact refusal and OperationalError texts, and 404 parity, because the route tests, the worker tests and the stall test pin these byte for byte.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked the inventory against `subtitles.py`, `internal_translate.py`, `translate-worker.py`, `server.py:340-384`, `handlers/video.py` (`fetch_video_row`, `resolve_video_row`), `data/moderation.py`, the three active test files and the two docs. Every entry matches the code at the lines it cites. A repository-wide grep for the removed and renamed names finds them only in the three code files, the three active tests, the two docs, the plans and issues, `delete_me/` and `tests/tmp/`. There are no unknown callers. The plan holds as written. The inventory already names its two real weak points: `serve`'s subscripted log line at `translate-worker.py:495`, which the plan does not name, and a connection that is never closed if recovery raises inside `open_translate_worker_store`. Neither conflicts with the plan; both are build details. No test double is widened by the plan, so nothing needs a double-specific recommendation.\n<question id=\"1\">\nYes. Five points were checked against the code. (a) Every conditional write already goes through `_update_claim` with `WHERE {_KEY} AND state = 'running' AND started_at = ?` (`subtitles.py:161`). Holding the claim's fields in the handle changes no SQL. (b) The new instance-track end is one UPDATE through that same WHERE. After a `store_ready_subtitles` takeover it matches nothing, because the upsert sets state `ready`. This replaces today's unconditional upsert at `translate-worker.py:407` and the `mark_translate_finished` stamp at `:408`, which matched on `state='ready' AND started_at`. (c) `list_active_denied_hosts` takes no lock (`moderation.py:137`), so merging the route's two `server.db_lock` holds (`internal_translate.py:203` via `resolve_video_row`, and `:210`) into one hold cannot deadlock on the plain `threading.Lock` (`server.py:292`, and the fake at `test_internal_translate.py:429`). (d) `fetch_video_row` raises before any denylist read (`video.py:36`). The worker's OperationalError classification in `generate` (`:396-400`) and the zero-byte and drop-column tests (`test_translate_worker.py:1081`) therefore still see the same text. (e) `command_run` opens the lock `O_RDONLY` (`:519`) and flocks that descriptor. Re-asserting `LOCK_EX|LOCK_NB` on the same descriptor is a no-op, so the opener succeeds in the service and refuses a separately opened description.\n</question>\n<question id=\"2\">\n- **Lost claim on the instance-track end:** the worker now writes nothing; today it overwrites the Engine's row (the approved change).\n- **One timestamp:** `fetched_at` and `finished_at` come from one value; today they come from two `now_ms()` calls.\n- **Engine start:** `server.py` now creates a missing parent directory for a custom `--subtitles-db`.\n- **Route resolve:** one `db_lock` hold instead of two. The window between the row lookup and the denylist read is gone.\n- **Closed store:** the route logs a new info line when the store is closed.\n- **Signatures:** `run_job` loses its connection argument. `generate` and `translate_audio` take the handle in place of `conn` and `claim`. The claim result is no longer subscriptable.\n- **Recovery:** reachable only through the lock-checked opener.\n- **Stale probes:** the probes in `delete_me/` and `tests/tmp/` break if run.\n- **Wider test run:** `server.py` is mapped in `tests/config.json` by five Engine-start suites, so the build's targeted runs include `test_similar`, `test_server_config`, `test_internal_events` and `test_random_cache`.\n</question>\n<question id=\"3\">\nThese are all already in the inventory; I confirmed each in the files.\n- **`serve`:** `translate-worker.py:495` must switch from `job[\"video_id\"]`, `job[\"instance_domain\"]` and `job[\"attempts\"]` to attributes. Otherwise every claim raises TypeError outside `run_job`'s handlers and the service dies.\n- **Test callers of the old shapes:** `Rig.claim`/`Rig.run` (`test_translate_worker.py:544`, `:554`), the fetch-reason test (`:925`), `WORKER_SCRIPT` in `test_subtitles.py:119-141`, which is a string invisible to import greps, and the claim test (`:340`). Also the recovery test (`:347-372`), the state test (`:388-395`), and `_claimed`/`_seed` plus the running and failed sequences (`test_internal_translate.py:607-629`, `:755-792`).\n- **`command_run`:** its try/finally must be restructured so `conn` is bound before the `finally` that closes it.\n- **Recovery failure:** `open_translate_worker_store` must close its connection if recovery raises.\n- **`resolve_video_row`:** it must stay in `video.py`, because `/api/video` still calls it.\n- **Encoding:** the instance-track encoder must stay byte-identical to `store_ready_subtitles:114` (NaN allowed, compact). `test_internal_translate.py:502` pins the compact form.\n</question>\n<question id=\"4\">\n- **Lost claim:** a worker that finds an instance track after its claim was taken over now leaves the Engine's row exactly as the Engine wrote it, and logs `taken over by the instance track`. Today it overwrites `track_text`, `cues_json` and `fetched_at` with its own fetch, and then stamps `finished_at`.\n- **Successful instance-track end:** `fetched_at == finished_at`.\n- **Engine start:** with a custom subtitles path in a missing directory, the Engine now starts instead of failing.\n- **Closed store:** a track store against a closed store now logs one info line.\n- **Unchanged:** every HTTP response, worker stdout line, exit code and stored error text is unchanged, including the worker's `not in whitelist` for an empty host.\n</question>\n\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. Close the connection in `open_translate_worker_store` when `_recover_translate_jobs` raises: a `try`/`except BaseException: conn.close(); raise` around the recovery call, the same pattern the plan already uses for a failed migration in `open_subtitles_db`. Then, in `command_run`, start the try/finally that joins the beat and closes `conn` only after the opener returns. What it changes: today `command_run`'s `finally` (`translate-worker.py:541-545`) closes the connection when recovery fails; without this, the connection leaks on that path. Cost: about three lines and no new test. The process exits right after anyway, so this is about keeping the contract tidy, not about correctness.\n\n2. Add one worker-level test that drives `generate` through a takeover that lands before the instance-track end. Patch the worker module's `fetch_instance_track` so that it first runs `store_ready_subtitles` on a second connection with different cues, then returns a track. Assert three things: the row equals the Engine's write byte for byte, `run_job` returns False, and the `taken over by the instance track` line is logged. What it changes: it pins the one approved behaviour change at the worker level. Today nothing drives that path; the plan's store test only covers the method on its own. Cost: one test of about 20 lines in `test_translate_worker.py`, reusing `rig` and the pattern of the existing takeover test at `:1033`.\n\n3. Add `engine/server/README.md:17` to the doc pass. It still says the route resolves through `resolve_video_row`, which stops being true. Cost: one sentence. The alternative is a factually stale API doc.\n\n4. Before building, run the three active files once (`test_subtitles.py`, `test_internal_translate.py`, `test_translate_worker.py`) plus the four Engine-start suites that `server.py` pulls in. What it changes: a red test that predates the build gets recognised as baseline, not mistaken for a regression; the plan already lists the unverified baseline as a risk. Cost: one test run. `test_translate_worker.py` needs ffmpeg on PATH, and its held-lock whitelist case waits out a 30 s busy timeout.\n\n5. Test doubles: no action. The plan widens none. The route's `SimpleNamespace` fake already carries `db`, `db_lock`, `video_error_threshold`, `subtitles_db` and `subtitles_db_lock` (`test_internal_translate.py:429`). The `_recording` `resolve_video` stand-ins keep their 4-argument signature. The `cues_writes` trigger (`test_translate_worker.py:512`) already records an instance-track write today, because the upsert's DO UPDATE fires `AFTER UPDATE OF cues_json`. The new conditional UPDATE is recorded the same way, so none of its expected sequences change.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: translate job handle (issue 54, folds in 57)\n\nI read all three code files, `server.py:340-379`, `handlers/video.py` (`fetch_video_row` and `resolve_video_row`) and the test call sites the impacts name. Each item below gives the code as it should land, in the style of the file it goes into: one-line docstrings, one statement per line, no softwrap.\n\n### What the build has to test (worked out first)\n\n1. **Six handle methods after a takeover.** Each returns `False` and leaves the row byte-identical, checked with `_snapshot`.\n2. **Instance-track end while the claim holds.** The row becomes ready/instance with track text and compact cues, `fetched_at == finished_at`, and the other job columns are unchanged.\n3. **Instance-track end after a lost claim, driven through `generate`.** The worker leaves the Engine's row as it is and logs the takeover line. This is the one approved behaviour change, and no existing test reaches it, so it gets a new worker test.\n4. **`open_subtitles_db`.** On a fresh nested path it creates the directory and the full schema in WAL mode. On a B1-era file it adds the job columns.\n5. **`open_translate_worker_store`.** When a second open file description holds the flock, it raises `BlockingIOError` and the subtitles file is absent. With the lock held, recovery returns `(1, 0)` and then `(2, 1)` as today.\n6. **Route.** A closed store with an instance track answers `ready` and writes the new info line once. The other closed-store answers are unchanged.\n7. **Resolve.** `missing host`, `not in whitelist` and `host denied` (uppercase stored deny) are refused. Route 400/404 and worker texts are unchanged (existing tables).\n8. **Regression net.** The three active files stay green, plus the Engine-start groups pulled in by `server.py`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/subtitles.py` | Adds `SOURCE_INSTANCE`, `_instance_cues_text`, `TranslateJob` (6 methods), `open_subtitles_db` and `open_translate_worker_store`. `claim_translate_job` returns the handle. `recover_translate_jobs` becomes `_recover_translate_jobs`. `_update_claim` takes the handle. The 5 per-claim functions and `mark_translate_finished` are deleted. |\n| `engine/server/api/handlers/internal_translate.py` | Adds `resolve_translatable_video` and `_subtitles_store`. Three sites now go through the helper. `SOURCE_INSTANCE` is imported. `resolve_video_row` is dropped. |\n| `engine/server/db/jobs/translate-worker.py` | Handle threaded through `run_job`, `generate` and `translate_audio`. `serve` uses attributes. `resolve_video` delegates. Both openers are used. Imports trimmed. |\n| `engine/server/api/server.py` | One import and one call. |\n| tests and docs | As listed below. |\n\nNo new modules and no new dependency. `fcntl` is imported inside one function only.\n\n---\n\n### `engine/server/data/subtitles.py`\n\n**Imports**\n\n```python\nimport json\nimport sqlite3\nimport time\nfrom contextlib import contextmanager\nfrom dataclasses import dataclass, field\nfrom pathlib import Path\nfrom typing import Any, Iterator\n```\n\n**Constants:** add beside `SOURCE_WHISPER`, byte-identical to the route's old value.\n\n```python\nSOURCE_WHISPER = \"whisper\"\nSOURCE_INSTANCE = \"instance\"\n```\n\n**Opener:** goes after `ensure_subtitles_schema`.\n\n```python\ndef open_subtitles_db(path: Path) -> sqlite3.Connection:\n    \"\"\"The one store opener for the Engine and the worker: create the parent directory, connect in WAL (connect_subtitles_db's busy timeout and lock retry), migrate (ensure_subtitles_schema); the connection is closed if the migration raises.\"\"\"\n    path.parent.mkdir(parents=True, exist_ok=True)\n    conn = connect_subtitles_db(path)\n    try:\n        ensure_subtitles_schema(conn)\n    except BaseException:\n        conn.close()\n        raise\n    return conn\n```\n\n**Shared instance-track encoder.** `store_ready_subtitles` switches to it. Its SQL and signature are unchanged. Its docstring gains: \"the cues are encoded by `_instance_cues_text`, as the handle's instance-track end encodes them\".\n\n```python\ndef _instance_cues_text(cues: list[dict[str, Any]]) -> str:\n    \"\"\"Compact JSON for an instance track's cues_json, shared by store_ready_subtitles and TranslateJob.end_ready_from_instance so the two writers encode alike; NaN allowed, unlike _cues_text.\"\"\"\n    return json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))\n```\n\nIn `store_ready_subtitles`, the last tuple element becomes `_instance_cues_text(cues)`. `_cues_text` is unchanged.\n\n**Handle and claim**\n\n```python\n@dataclass(frozen=True)\nclass TranslateJob:\n    \"\"\"One claim on a running job: the connection it was claimed on, its key, its started_at and attempts. Every method is one conditional UPDATE that matches only while the row is running with this started_at, and answers whether the claim still held; False means the Engine state route's instance-track store (store_ready_subtitles) replaced the row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did.\"\"\"\n\n    conn: sqlite3.Connection = field(repr=False, compare=False)\n    video_id: str\n    instance_domain: str\n    target_language: str\n    started_at: int\n    attempts: int\n\n    def write_running_cues(self, cues: list[dict[str, Any]], detected_language: str) -> bool:\n        \"\"\"Rewrite the running job's whole cues_json after a chunk (AC4).\"\"\"\n        return _update_claim(self, \"cues_json = ?, detected_language = ?\", (_cues_text(cues), detected_language))\n\n    def end_ready(self, cues: list[dict[str, Any]], finished_at: int) -> bool:\n        \"\"\"End ready with the full, start-sorted cue list; fetched_at is set so the ready reader sees a normal ready row.\"\"\"\n        return _update_claim(self, \"state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?\", (_cues_text(cues), finished_at, finished_at))\n\n    def end_already_english(self, detected_language: str, finished_at: int) -> bool:\n        \"\"\"End already_english; English is detected before any cue is written, so cues_json was never set.\"\"\"\n        return _update_claim(self, \"state = 'already_english', detected_language = ?, finished_at = ?\", (detected_language, finished_at))\n\n    def end_failed(self, error: str, finished_at: int) -> bool:\n        \"\"\"End failed with its error text; partial cues stay in cues_json, unread because a failed row's cues are never served.\"\"\"\n        return _update_claim(self, \"state = 'failed', error = ?, finished_at = ?\", (error, finished_at))\n\n    def requeue(self) -> bool:\n        \"\"\"Put the job back without spending its claim (a stop mid-job, or whitelist.db unavailable at claim); queued_at is kept, so it stays at the head of the queue.\"\"\"\n        return _update_claim(self, \"state = 'queued', attempts = attempts - 1\", ())\n\n    def end_ready_from_instance(self, track_text: str, cues: list[dict[str, Any]], finished_at: int) -> bool:\n        \"\"\"End ready with the instance's English track, source instance, one timestamp for fetched_at and finished_at; every other job column is left as it is.\"\"\"\n        return _update_claim(self, \"state = 'ready', source = ?, track_text = ?, cues_json = ?, fetched_at = ?, finished_at = ?\", (SOURCE_INSTANCE, track_text, _instance_cues_text(cues), finished_at, finished_at))\n\n\ndef claim_translate_job(conn: sqlite3.Connection, target_language: str, started_at: int) -> TranslateJob | None:\n    \"\"\"Flip the oldest queued job to running, in one short transaction; its TranslateJob handle on conn, or None.\"\"\"\n    with _immediate(conn):\n        row = conn.execute(\"SELECT video_id, instance_domain FROM subtitles WHERE state = 'queued' AND target_language = ? ORDER BY queued_at, rowid LIMIT 1\", (target_language,)).fetchone()\n        if row is None:\n            return None\n        key = (row[0], row[1], target_language)\n        conn.execute(f\"UPDATE subtitles SET state = 'running', started_at = ?, attempts = attempts + 1 WHERE {_KEY}\", (started_at, *key))\n        claimed = conn.execute(f\"SELECT video_id, instance_domain, started_at, attempts FROM subtitles WHERE {_KEY}\", key).fetchone()\n    return TranslateJob(conn, claimed[\"video_id\"], claimed[\"instance_domain\"], target_language, claimed[\"started_at\"], claimed[\"attempts\"])\n\n\ndef _update_claim(job: TranslateJob, assignments: str, values: tuple[Any, ...]) -> bool:\n    \"\"\"One conditional UPDATE on job's running row, on the connection that claimed it; False (rowcount 0) once the state route's instance-track store, or an older blue/green Engine, replaced the row.\"\"\"\n    with job.conn:\n        cursor = job.conn.execute(f\"UPDATE subtitles SET {assignments} WHERE {_KEY} AND state = 'running' AND started_at = ?\", (*values, job.video_id, job.instance_domain, job.target_language, job.started_at))\n    return cursor.rowcount == 1\n```\n\n`TranslateJob` is defined before `claim_translate_job`. Python resolves `_update_claim` at call time, so its later position is fine.\n\n**Decision on equality and repr.** `conn` is marked `repr=False, compare=False`. Two handles for the same claim then compare equal, and `repr` does not print a connection object. That costs one `field(...)`, which is already in stdlib `dataclasses`.\n\n**SET strings:**\n- the five existing methods: copied verbatim from the deleted functions, including `attempts = attempts - 1`;\n- `end_ready_from_instance`: sets exactly the columns the upsert's `DO UPDATE` sets today (state, source, fetched_at, track_text, cues_json), plus `finished_at`, which `mark_translate_finished` set. `detected_language`, `error`, `attempts`, `queued_at` and `started_at` are untouched.\n\n**Recovery and the worker opener**\n\n```python\ndef _recover_translate_jobs(conn: sqlite3.Connection, finished_at: int) -> tuple[int, int]:\n    \"\"\"Requeue a running row once, fail it when found running a second time; (requeued, failed). Private: reached only through open_translate_worker_store, under the worker's flock.\"\"\"\n    # body unchanged: failed UPDATE first, then requeue, in one _immediate\n\n\ndef open_translate_worker_store(path: Path, lock_fd: int, finished_at: int) -> tuple[sqlite3.Connection, tuple[int, int]]:\n    \"\"\"The worker service's opener: re-assert the flock on lock_fd (LOCK_EX | LOCK_NB) before the file is touched, then open_subtitles_db and crash recovery; (conn, (requeued, failed)). On the descriptor that already holds the lock the re-assert is a no-op; on an unlocked descriptor it takes the lock; when another open file description holds it, BlockingIOError is raised and nothing is created. lock_fd stays the caller's to close.\"\"\"\n    import fcntl\n\n    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    conn = open_subtitles_db(path)\n    try:\n        return conn, _recover_translate_jobs(conn, finished_at)\n    except BaseException:\n        conn.close()\n        raise\n```\n\nThis also closes the impact's gap: the connection is closed if recovery raises. The flock comes before `open_subtitles_db`, so a refused call creates no directory either.\n\n**Deleted:** `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `mark_translate_finished`, and the public `recover_translate_jobs`.\n\n**Unchanged:** `connect_subtitles_db`, `ensure_subtitles_schema`, `_immediate`, the fetchers, `enqueue_translate_job`, `write_translate_heartbeat`, `_KEY`, `MAX_CLAIMS`, `RECOVERY_ERROR`, `JOB_COLUMNS`.\n\n**Module docstring, paragraph 2, replaced:**\n\n> The Engine state route stores an instance's English track with store_ready_subtitles, an unconditional upsert to state 'ready', source 'instance'. Plan 49's translate worker adds the job states and the source 'whisper'; state and source stay plain TEXT. open_subtitles_db is the one opener (mkdir, WAL connect, migrate in place); open_translate_worker_store adds crash recovery and is the only way to run it, with the worker's flock re-asserted first. claim_translate_job hands back a TranslateJob whose six methods (running cues, ready, already_english, failed, requeue, ready from the instance track) each match only while the row is running with that claim's started_at, so the state route's upsert landing on a running row wins and every later job write is a no-op. A running job's cues are a whole-cues_json rewrite after each chunk, so fetch_ready_subtitles reads a ready row of either source unchanged, and the state route reads a running row's cues so far through fetch_subtitle_state. The file is in WAL mode: both blue/green Engines and the translate worker (claim, per-chunk rewrites, a heartbeat) write it.\n\n---\n\n### `engine/server/api/handlers/internal_translate.py`\n\n**Imports**\n\n```python\nfrom contextlib import contextmanager\nfrom typing import Any, Iterator\n...\nfrom data.subtitles import SOURCE_INSTANCE, enqueue_translate_job, fetch_subtitle_state, fetch_translate_heartbeat, store_ready_subtitles\n...\nfrom handlers.video import fetch_video_row\n```\n\n- The `SOURCE_INSTANCE = \"instance\"` line is deleted. The name still resolves as a module attribute through the import, so the stale probes keep working.\n- The `VIDEO_NOT_FOUND` comment becomes: `# Answered for every refusal of resolve_translatable_video, so the route does not reveal which check failed; the body /api/video answers for an unknown video.`\n\n**Shared resolve:** placed above `_generation_available`.\n\n```python\ndef resolve_translatable_video(conn: sqlite3.Connection, video_id: str, host: str | None, error_threshold: int | None) -> tuple[dict[str, Any] | None, str | None]:\n    \"\"\"The whitelisted row and None, or None and the refusal: missing host (decided before any lookup, since fetch_video_row with no host matches the id on any host), not in whitelist (fetch_video_row with error_threshold), host denied (the row's normalised domain is actively denied). Shared by both /internal/translate routes and the translate worker; takes no lock and writes no response.\"\"\"\n    if not host:\n        return None, \"missing host\"\n    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n    if row is None:\n        return None, \"not in whitelist\"\n    if normalize_host(row[\"instance_domain\"]) in list_active_denied_hosts(conn):\n        return None, \"host denied\"\n    return row, None\n```\n\nThe order is host, then row, then denylist. The denylist is read only when a row exists, so an `OperationalError` from `fetch_video_row` surfaces first with its own text, as the worker's busy/unopenable classification needs.\n\n**Store access helper**\n\n```python\n@contextmanager\ndef _subtitles_store(server: Any) -> Iterator[sqlite3.Connection | None]:\n    \"\"\"Hold subtitles_db_lock for the whole body and yield subtitles_db, None when the store is closed; errors pass through to the caller's own handler.\"\"\"\n    with server.subtitles_db_lock:\n        yield server.subtitles_db\n```\n\n**`_read_key`**\n\n```python\n    try:\n        with _subtitles_store(server) as conn:\n            if conn is None:\n                return None, False\n            return fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE), _generation_available(conn)\n    except sqlite3.Error as exc:\n        logging.warning(\"[translate] cache read failed video_id=%s host=%s: %s\", video_id, instance_domain, exc)\n        return None, False\n```\n\n**`_store_cues`.** The docstring gains \"a closed store (shutdown) stores nothing and is logged\".\n\n```python\n    try:\n        with _subtitles_store(server) as conn:\n            if conn is None:\n                logging.info(\"[translate] cache closed, track not stored video_id=%s host=%s\", video_id, instance_domain)\n                return\n            store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())\n    except sqlite3.Error as exc:\n        logging.warning(\"[translate] cache write failed video_id=%s host=%s: %s\", video_id, instance_domain, exc)\n```\n\nThe new line starts `[translate] cache closed`, not `[translate] instance fetch failed`, so `_failed_fetches` and the NONE_CASES exact-list assertions cannot pick it up.\n\n**`_resolve_translate_key`.** Body validation and the three 400s are byte-identical. The tail becomes:\n\n```python\n    host = normalize_host(raw_host)\n    if host is None:\n        respond_json(handler, 400, {\"error\": \"Invalid host\"})\n        return None\n    with server.db_lock:\n        row, _ = resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)\n    if row is None:\n        respond_json(handler, 404, VIDEO_NOT_FOUND)\n        return None\n    # The row's own domain and canonical id, never the request's: the fetch goes to the video's instance and the store is keyed once per video.\n    canonical_id = row[\"video_id\"]\n    return body, canonical_id, row[\"instance_domain\"], row[\"video_uuid\"] or canonical_id\n```\n\nThere is one `db_lock` hold, which is not re-entered (the fake uses a plain `threading.Lock`). `resolve_video_row`'s unreachable `Missing video id` is not reintroduced.\n\n**Enqueue**\n\n```python\n    try:\n        # One lock hold, so availability cannot flip between the beat read and the enqueue.\n        with _subtitles_store(server) as conn:\n            outcome = enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if conn is not None and _generation_available(conn) else None\n    except sqlite3.Error as exc:\n        ...unchanged\n```\n\n**Module docstring**\n- Paragraph 2: after \"An unknown or denylisted video answers 404 \u2026\", add \"(resolve_translatable_video, shared with the translate worker)\". After \"an instance track found then is stored ready over it\", add \"; with the store closed (shutdown) it is answered but not stored, and an info line says so\".\n- Paragraph 3: unchanged.\n\n---\n\n### `engine/server/db/jobs/translate-worker.py`\n\n**Path comment and imports**\n\n```python\n# api/ is for server_config and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.\n...\nfrom data.db import connect_readonly_db\nfrom data.moderation import normalize_host\nfrom data.subtitles import TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat\nfrom data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media\nfrom data.time import now_ms\nfrom handlers.internal_translate import TARGET_LANGUAGE, fetch_instance_track, resolve_translatable_video\n```\n\nThe `handlers.video` import and `list_active_denied_hosts` are removed. `TranslateJob` is imported for annotations only.\n\n**`JobTakenOver`**\n\n```python\nclass JobTakenOver(Exception):\n    \"\"\"A claim-conditional write matched no row: the Engine state route's instance-track store (store_ready_subtitles) replaced the running row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did.\"\"\"\n```\n\n**`resolve_video`.** The signature is unchanged. Tests monkeypatch it with four arguments.\n\n```python\ndef resolve_video(whitelist_path: Path, video_id: str, host: str, max_duration: int) -> tuple[dict[str, Any] | None, str | None]:\n    \"\"\"The whitelisted row and None, or None and the refusal text: resolve_translatable_video with VIDEO_ERROR_THRESHOLD (a missing host reads as not in whitelist), then the stored-duration bound; NULL duration passes.\"\"\"\n    conn = connect_readonly_db(whitelist_path)\n    try:\n        # sqlite3's 5 s default is shorter than the updater merge's commit; past 30 s this raises, never reads as not-found.\n        conn.execute(\"PRAGMA busy_timeout = 30000\")\n        row, refusal = resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)\n    finally:\n        conn.close()\n    if refusal is not None:\n        return None, \"not in whitelist\" if refusal == \"missing host\" else refusal\n    duration = row[\"duration\"]\n    if isinstance(duration, int) and duration > max_duration:\n        return None, f\"duration {duration}s over {max_duration}s\"\n    return row, None\n```\n\n`connect_readonly_db` still raises before any query, for example `unable to open` on a deleted file.\n\n**`command_enqueue`.** Replaces lines 131-141.\n\n```python\n    try:\n        conn = open_subtitles_db(args.subtitles_db)\n        try:\n            outcome, state = enqueue_translate_job(conn, row[\"video_id\"], row[\"instance_domain\"], TARGET_LANGUAGE, args.cap, now_ms())\n        finally:\n            conn.close()\n    except sqlite3.Error as exc:\n        print(f\"error: subtitles.db: {exc}\")\n        return EXIT_ERROR\n```\n\nAn `OSError` from mkdir is not a `sqlite3.Error`, so it propagates as before.\n\n**`translate_audio`.** The signature becomes `translate_audio(job: TranslateJob, pipe: AudioPipe, runner: Any, max_chunk: int, stop: threading.Event, progress: dict[str, float]) -> str`. Three lines change and nothing else:\n- `if not job.end_already_english(language, now_ms()):`\n- `if not job.write_running_cues(cues, language):`\n- `if not job.end_ready(cues, now_ms()):`\n\n**`generate`**\n\n```python\ndef generate(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:\n    \"\"\"AC3 for one claim handle, each bound raising JobFailed before the next remote request, a locked or unopenable whitelist.db raising WhitelistBusy, a lost claim raising JobTakenOver; the end state written.\"\"\"\n    try:\n        row, refusal = resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)\n    ...unchanged\n    fetched = fetch_instance_track(instance, video_key)\n    if fetched is not None:\n        if not job.end_ready_from_instance(fetched[0], fetched[1], now_ms()):\n            raise JobTakenOver()\n        return \"ready from the instance track\"\n    ...unchanged\n    try:\n        return translate_audio(job, pipe, runner, args.max_chunk_seconds * SAMPLE_RATE, stop, progress)\n    finally:\n        pipe.close()\n```\n\n**`run_job`**\n\n```python\ndef run_job(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:\n    \"\"\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or unopenable at claim; a row the Engine's instance-track store took over is left as that store wrote it. True only for the whitelist.db requeue.\"\"\"\n    where = (job.video_id, job.instance_domain)\n    try:\n        state = generate(job, args, runner, stop, progress)\n        logging.info(\"[translate-worker] job %s video_id=%s host=%s\", state, *where)\n    except JobStopped:\n        job.requeue()\n        logging.info(\"[translate-worker] stopped mid-job, requeued video_id=%s host=%s\", *where)\n    except WhitelistBusy as exc:\n        # The attempt is given back, so MAX_CLAIMS recovery never counts these cycles.\n        job.requeue()\n        logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *where, exc)\n        return True\n    except JobTakenOver:\n        logging.info(\"[translate-worker] taken over by the instance track video_id=%s host=%s\", *where)\n    except JobFailed as exc:\n        job.end_failed(str(exc), now_ms())\n        logging.info(\"[translate-worker] job failed video_id=%s host=%s: %s\", *where, exc)\n    except Exception as exc:\n        # A CUDA out-of-memory fails only this job; the model is dropped so the next job loads it afresh instead of retrying in a loop (AC7).\n        if is_cuda_oom(exc):\n            runner.unload()\n        logging.exception(\"[translate-worker] job error video_id=%s host=%s\", *where)\n        job.end_failed(f\"{type(exc).__name__}: {exc}\", now_ms())\n    return False\n```\n\nThe log texts are unchanged. The results of requeue and end-failed are still ignored.\n\n**`serve`.** Its signature keeps `conn`, which it claims on. Two lines change (one of them the miss the plan did not name):\n\n```python\n        logging.info(\"[translate-worker] claimed video_id=%s host=%s attempts=%s\", job.video_id, job.instance_domain, job.attempts)\n        if run_job(job, args, runner, stop, progress):\n```\n\n**`heartbeat_loop`:** unchanged (plain `connect_subtitles_db`).\n\n**`command_run`.** Its own LOCK_NB, the `another worker holds` log line and exit 6 come first, as now. Then:\n\n```python\n    try:\n        stop = threading.Event()\n        for signum in (signal.SIGTERM, signal.SIGINT):\n            signal.signal(signum, lambda *_: stop.set())\n        progress = {\"at\": time.monotonic()}\n        conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())\n        beat: threading.Thread | None = None\n        try:\n            logging.info(\"[translate-worker] started pid=%s recovered requeued=%s failed=%s\", os.getpid(), requeued, failed)\n            beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)\n            beat.start()\n            serve(conn, args, WhisperRunner(), stop, progress)\n        finally:\n            stop.set()\n            if beat is not None:\n                beat.join(HEARTBEAT_SECONDS)\n            conn.close()\n    finally:\n        os.close(lock_fd)\n```\n\n`conn` is bound before the inner `try`, so there is no NameError. The opener closes its own connection if migration or recovery fails. `lock_fd` stays owned and closed here. The docstring becomes: \"\u2026 then the flock before subtitles.db is opened, so a refused second run writes nothing; then open_translate_worker_store (flock re-asserted, open, migrate, recover), the heartbeat thread and the claim loop until SIGTERM.\"\n\n**Module docstring**\n- Line 4: \"resolves the video against whitelist.db with the route's resolve_translatable_video\".\n- Line 6: \"run_job takes one claim handle (TranslateJob) through \u2026\".\n- Line 8: \"\u2026 flock (a refused second run exits 6 having written nothing), open_translate_worker_store (the flock re-asserted, then open, migrate and crash recovery), a heartbeat thread \u2026\".\n\n---\n\n### `engine/server/api/server.py`\n\n- Line 106: `from data.subtitles import open_subtitles_db`\n- Lines 370-372:\n\n```python\n    # After prepare_trending_override, so a rejected start creates nothing; the opener creates its own parent directory.\n    subtitles_db = open_subtitles_db(subtitles_db_path)\n```\n\n---\n\n### Tests\n\n**`tests/active/test_subtitles.py`**\n- **WORKER_SCRIPT:**\n  - The import becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, write_translate_heartbeat`.\n  - The check becomes `(job.video_id, job.instance_domain) != (key, host)`, and its message becomes `{None if job is None else (job.video_id, job.instance_domain)!r}`.\n  - The writes become `job.write_running_cues(first, \"fr\")` and `job.end_ready(full, 1700000200000 + n)`, with messages naming the methods.\n  - The script keeps `connect_subtitles_db`+`ensure_subtitles_schema`, so the race semantics are unchanged.\n- **Claim test (line 340):** reads attributes: `(job.video_id, job.instance_domain, job.started_at, job.attempts)`.\n- **Recovery test:**\n  - It imports `claim_translate_job, open_translate_worker_store`.\n  - It opens `lock_fd = os.open(tmp_path / \"worker.lock\", O_RDONLY|O_CREAT)` and `fcntl.flock(lock_fd, LOCK_EX)`.\n  - Each recover call becomes `opened, counts = open_translate_worker_store(path, lock_fd, 9000)`, then `opened.close()`, then `assert tuple(counts) == (1, 0)` (and `(2, 1)` at 9500).\n  - It reads `first.video_id`, `first.attempts` and `(row.video_id, row.attempts)`.\n  - `os.close(lock_fd)` in a `finally`.\n- **`fetch_subtitle_state` test:** `job = claim_translate_job(conn, \"en\", 2000)`, then `assert job.write_running_cues([...], \"fr\")`.\n- **New `test_every_claim_write_after_an_instance_track_takeover_matches_nothing_and_reports_the_claim_lost`.** Parametrised over the six methods:\n\n```python\nCLAIM_WRITES = {\n    \"running cues\": lambda job: job.write_running_cues([{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], \"fr\"),\n    \"ready\": lambda job: job.end_ready([{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], 9000),\n    \"already_english\": lambda job: job.end_already_english(\"en\", 9000),\n    \"failed\": lambda job: job.end_failed(\"boom\", 9000),\n    \"requeue\": lambda job: job.requeue(),\n    \"ready from instance\": lambda job: job.end_ready_from_instance(\"WEBVTT x\", [{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], 9000),\n}\n```\n\n  The test enqueues and claims, then runs `store_ready_subtitles(conn, \u2026, \"instance\", TRACK, CUES, 8000)` and takes a `_snapshot`. It asserts `write(job) is False` and that `_snapshot` is unchanged. A control runs the same write on a fresh claim without the takeover and asserts `True`, so that `False` is shown to be the takeover's doing.\n- **New `test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp`:**\n  - claim, then `job.write_running_cues(\u2026, \"fr\")`, then `job.end_ready_from_instance(\"WEBVTT t\", cues, 9000)` is True;\n  - the row has state/source `ready`/`instance`, `track_text`, a compact `cues_json` with no space, and `fetched_at == finished_at == 9000`;\n  - `detected_language == \"fr\"`, `error IS NULL`, `attempts == 1`, `queued_at` and `started_at` are unchanged;\n  - `fetch_ready_subtitles` returns the cues.\n- **New `test_open_subtitles_db_creates_a_missing_directory_and_the_full_schema_in_wal`:** on `tmp_path / \"a\" / \"b\" / \"subtitles.db\"`, the columns equal `ALL_COLUMNS`, the heartbeat table exists and the mode is `wal`.\n- **New `test_open_subtitles_db_adds_the_job_columns_to_a_b1_file`:** reuses `_b1_file`; the columns equal `ALL_COLUMNS` and `_old_cues == B1_CUES`.\n- **New `test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing`:**\n  - `held = os.open(lock)` locked LOCK_EX; `mine = os.open(lock)` is a separate description, not `dup`;\n  - `pytest.raises(BlockingIOError)` on `open_translate_worker_store(tmp_path / \"sub\" / \"subtitles.db\", mine, 1)`;\n  - the file and its parent are absent;\n  - control: after closing `held`, the same call succeeds on `mine` and the file exists.\n- **Docstring.** Lines 12, 14 and 17 are reworded to the handle methods, the openers and `open_translate_worker_store`. New bullets cover the takeover, the instance end, the openers and the flock.\n\n**`tests/active/test_internal_translate.py`**\n- `_claimed` returns `claim_translate_job(store, \"en\", NOW - 1000)` with annotation `-> \"TranslateJob\"` and docstring \"its claim handle\".\n- `_seed` imports `enqueue_translate_job, store_ready_subtitles` and calls `_claimed(store).write_running_cues(RUNNING, \"fr\")`, `.end_failed(\"boom\", NOW - 500)` and `.end_already_english(\"en\", NOW - 500)`.\n- Lines 755-792:\n  - `job = _claimed(store)`;\n  - `assert job.write_running_cues(RUNNING, \"fr\")`;\n  - `assert job.end_failed(\"boom\", NOW)`;\n  - the imports keep only `write_translate_heartbeat`.\n- `_subtitles_db` switches to `open_subtitles_db(path)`, so the docstring \"as server.py opens it\" is true again. Line 19 of the module docstring is reworded to match.\n- **New `test_a_closed_store_still_answers_an_instance_track_ready_and_logs_that_it_was_not_stored`:**\n  - `server = _server(...)` with `subtitles_db = None` and `_instance(True)`;\n  - the answer is `[[200, {\"state\": \"ready\", \"cues\": CUES, \"available\": False}]]`;\n  - `caplog` has exactly one record starting `[translate] cache closed, track not stored`.\n- **New resolve test** in `test_internal_translate.py`, three cases on the `whitelist` fixture DB:\n  - `resolve_translatable_video(conn, VIDEO_ID, None, 0)` and the same with `\"\"` return `(None, \"missing host\")`, even though the id exists;\n  - the denied-host video returns `(None, \"host denied\")`;\n  - an unknown id returns `(None, \"not in whitelist\")`;\n  - the known video returns its row.\n\n**`tests/active/test_translate_worker.py`**\n- `Rig.claim` asserts on `(self.job.video_id, self.job.instance_domain, self.job.started_at, self.job.attempts)`.\n- `Rig.run` calls `self.worker.run_job(self.job, args, runner, \u2026)`.\n- The fetch-reason test calls `worker.run_job(job, args, UnreachedRunner(), \u2026)`.\n- Docstring line 10 becomes `run_job(job, args, runner, stop, progress)`, where `job` is the claim handle.\n- **New `test_an_instance_track_found_after_the_engine_took_the_row_over_writes_nothing_and_logs_the_takeover`:**\n  - The test serves the English listing and track.\n  - It wraps `worker.fetch_instance_track` through `monkeypatch.setattr(rig.worker, \"fetch_instance_track\", \u2026)`. The wrapper calls the real function, then `store_ready_subtitles(b1, \"v-1\", HOST, \"en\", \"instance\", \"WEBVTT engine\", ENGINE_CUES, 1_700_000_000_000)`, snapshots `rig.row()` and returns the fetched value.\n  - Assertions: `rig.row() == taken`, `caplog` has the `taken over by the instance track video_id=v-1 host=\u2026` line, no `failed`, and `runner.transcribes == 0`.\n  - This pins the approved behaviour change, which no existing test reaches. Today's code would fail it, because the upsert overwrites `track_text`.\n- The existing English-track test at 1016 is unchanged and stays green: the cues decode to `CUES`, `track_text == TRACK`, and `finished_at` is now one `now_ms()` inside the window.\n\n---\n\n### Docs (settled list, as written)\n\n**`TRANSLATE_WORKER.md`**\n- Line 72, start-order step 5: \"`open_translate_worker_store` re-asserts the flock on the held descriptor, then creates the directory, opens `subtitles.db` in WAL, migrates and runs crash recovery; the counts are logged.\"\n- Line 90: \"store it `ready` with source `instance` while the claim holds (`end_ready_from_instance`); if the Engine's store took the row over first, nothing is written and the job is taken over.\"\n- Line 147: \"under the lock: recovery is private to the store and reachable only through `open_translate_worker_store`.\"\n- Line 49: \"resolved by `resolve_translatable_video`, as the route does\".\n- A new short subsection, \"The Claim Handle\": `claim_translate_job` returns a `TranslateJob` holding its connection, with six methods. Each matches only while the row is `running` with the claim's `started_at` and returns `False` after a takeover. `run_job` raises `JobTakenOver` on a `False` result from running cues, ready, already_english or ready-from-instance.\n- \u00a7 Takeover: left as it is (it names no removed function).\n\n**`engine/server/README.md`**\n- \u00a729-36: `open_subtitles_db` as the single opener; the `TranslateJob` handle and its methods; `open_translate_worker_store` as the only recovery path, under the flock.\n- Line 17: `resolve_translatable_video` (`fetch_video_row` with the error threshold, then the denylist on the row's domain).\n- Line 19: \"with the store closed, an info line is logged and the answer stays `ready`\".\n- Line 45: \"creating the file and its parent directory when missing\". The Notes record that a custom path in a missing directory now starts.\n\n**`CONTEXT.md` line 19:** add \"while its claim holds\".\n\n---\n\n### Check against the plan and the requirements (pass 1, converged)\n\n| Requirement | Draft |\n|---|---|\n| Claim unchanged, returns handle or None | `claim_translate_job`: the same transaction, then a `TranslateJob` |\n| Handle in `subtitles.py`, key, `started_at`, `attempts`, holds connection | frozen dataclass; `conn` with `repr=False, compare=False` |\n| Six operations, the compare-and-set in each, one lost-claim report | six methods, all through `_update_claim`, all `bool` |\n| No tuple outside the store; five functions and `mark_translate_finished` gone | deleted; the worker and tests use attributes and methods only |\n| Instance end: one UPDATE, columns, NaN-allowing encoding, one timestamp, no-op when lost | `end_ready_from_instance` + `_instance_cues_text`; `generate` raises `JobTakenOver` on `False` |\n| Takeover unchanged | `_store_cues` \u2192 `store_ready_subtitles`, unconditional |\n| Docstrings name the real writer | `TranslateJob`, `_update_claim`, `JobTakenOver`, `run_job` |\n| One opener; Engine, enqueue and run use it; heartbeat decided | `open_subtitles_db`; `server.py`, `command_enqueue`, via `open_translate_worker_store`; heartbeat keeps the plain connect |\n| Recovery logic unchanged, unreachable without the flock, shown by a test | `_recover_translate_jobs` private; flock re-assert in the only caller; refusal test |\n| One route helper; closed-store answers and error handling unchanged; beat and enqueue in one hold | `_subtitles_store`; three sites; one `with` in enqueue |\n| Resolve: three refusals, order, both callers, route 400/404, worker texts | `resolve_translatable_video`; `missing host` mapped to `not in whitelist` in the worker |\n| `run_job` without `conn`, `serve` attribute access | done; `serve` covered (the impact's miss) |\n| Docs and docstrings | listed above |\n\nTwo small additions beyond the plan's list, both inside its stated decisions:\n1. `open_translate_worker_store` closes the connection when recovery raises. This fixes the gap the impacts flagged.\n2. One worker test drives `generate` through a takeover that lands before the instance-track end. It pins the approved behaviour change end to end.\n\nSimplifications, named:\n- `TranslateJob` is pinned to one connection. A handle cannot outlive or move off the connection that claimed it. Upgrade path: none needed until a second claimer exists.\n- Stale probes in `tests/tmp/` and `delete_me/` that call the removed functions will break if run. This is accepted per the plan.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam 1 is the store module, entered at rung 1 in tests/active/test_subtitles.py with its existing `_snapshot` harness. A parametrised test runs over the six TranslateJob methods (running cues, ready, already_english, failed, requeue, ready from instance). For each it enqueues, claims, takes the row over with `store_ready_subtitles(..., \"instance\", ...)` and snapshots, then asserts the method returns `False` and the snapshot is unchanged. A control runs the same method on a fresh claim with no takeover and asserts `True`, which shows the `False` comes from the takeover and not from a broken UPDATE. A second store test covers the held-claim control: `end_ready_from_instance` returns True and leaves state `ready`, source `instance`, the track_text, compact cues_json (no space) and `fetched_at == finished_at`, with detected_language, error, attempts, queued_at and started_at unchanged. Seam 2 is the worker's `run_job`/`generate`, entered through the existing `Rig` harness in tests/active/test_translate_worker.py with a served English listing and track. `fetch_instance_track` is wrapped so that, after the real fetch, it runs `store_ready_subtitles` with the Engine's track and snapshots the row. The test asserts the row equals that snapshot (Engine's track_text and cues kept), the `taken over by the instance track video_id=v-1 host=\u2026` log line is present, no `failed` line is present and the runner made 0 transcribes. Today's code fails this because the upsert overwrites track_text. The existing English-instance-track test at :1016 stays green unchanged.</checkpoint>\n<name>Claim handle</name>\n<intent>`claim_translate_job` in engine/server/data/subtitles.py returns a TranslateJob handle bound to its connection, and the worker writes every claim-conditional change through it, so once the Engine's instance-track store has replaced a running row, no handle write (including the worker's new end-ready-from-instance-track) changes that row.</intent>\n<clause_1>After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical.</clause_1>\n<clause_2>When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged.</clause_2>\n<files>engine/server/data/subtitles.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/active/test_translate_worker.py (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>The seam is the store module's two openers, entered at rung 1 or 3 in tests/active/test_subtitles.py against real files under tmp_path, reusing the existing `_b1_file` harness. Test 1: `open_subtitles_db(tmp_path/\"a\"/\"b\"/\"subtitles.db\")` creates the directory, the columns equal `ALL_COLUMNS`, the heartbeat table exists and `PRAGMA journal_mode` is `wal`. Test 2: on a `_b1_file`, the columns equal `ALL_COLUMNS` and the old cues equal `B1_CUES`. Test 3 uses two descriptors: `held = os.open(lock)` takes LOCK_EX, and `mine` is a separate `os.open` (not `dup`). `open_translate_worker_store(tmp_path/\"sub\"/\"subtitles.db\", mine, 1)` raises BlockingIOError, and the file and its parent directory are both absent. Control: once `held` is closed, the same call on `mine` succeeds and the file exists. Test 4 is the rewritten recovery test, run under a held flock through `open_translate_worker_store`. It returns (1, 0) at 9000 and (2, 1) at 9500 and reads the handle's attributes. Engine start (server.py) is covered by the existing Engine-start test groups, kept green.</checkpoint>\n<name>Single opener, flock-tied recovery</name>\n<intent>subtitles.db is opened everywhere through `open_subtitles_db`, which creates the directory, connects in WAL and migrates, and crash recovery can run only through `open_translate_worker_store`, which re-asserts the worker's flock before touching the file.</intent>\n<clause_1>`open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode.</clause_1>\n<clause_2>`open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock.</clause_2>\n<files>engine/server/data/subtitles.py (EDITED), engine/server/api/server.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>The seam is the /internal/translate state route, entered through the existing route harness in tests/active/test_internal_translate.py (`_server` SimpleNamespace fake, `_instance(True)` RecordingInstance), the same way the current closed-store tests drive it. With `subtitles_db = None` and an instance track present, the test asserts the answer is exactly `[[200, {\"state\": \"ready\", \"cues\": CUES, \"available\": False}]]`. It also asserts that caplog holds exactly one record starting `[translate] cache closed, track not stored`, with the video_id and host in it. The existing closed-store read and enqueue tests and the NONE_CASES exact-list assertions stay green unchanged, which shows the other two sites' answers did not move.</checkpoint>\n<name>Route store helper</name>\n<intent>The three subtitles-store sites in engine/server/api/handlers/internal_translate.py go through one `_subtitles_store` context manager, and when the instance track is found while the store is closed, the route still answers ready and logs that the track was not stored.</intent>\n<clause_1>With the store closed, an instance track is answered ready and one `[translate] cache closed, track not stored` info line is logged.</clause_1>\n<files>engine/server/api/handlers/internal_translate.py (EDITED), tests/active/test_internal_translate.py (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>The seam is `resolve_translatable_video`, entered at rung 1 in tests/active/test_internal_translate.py on the existing `whitelist` fixture DB. The test asserts that host None and host \"\" both return `(None, \"missing host\")` even for the known VIDEO_ID, that the denied-host video returns `(None, \"host denied\")`, that an unknown id returns `(None, \"not in whitelist\")` and that the known video returns its row with a None refusal. The existing route 400/404 tables in test_internal_translate.py and the worker refusal-text tables in test_translate_worker.py are the regression net for both callers and stay green unchanged.</checkpoint>\n<name>Shared translatable-video resolve</name>\n<intent>Both /internal/translate routes and the translate worker resolve a video through one `resolve_translatable_video` in internal_translate.py, which refuses a missing host before any lookup, then a video not in the whitelist, then an actively denied host.</intent>\n<clause_1>`resolve_translatable_video` returns `missing host`, `not in whitelist` or `host denied` for the matching case, and the row otherwise.</clause_1>\n<files>engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThere are four phases, each proven by its own checkpoint, and the operator approved the split as presented. Phase 1 has to carry the store handle and the worker rewiring together: `claim_translate_job`'s new return value and the deletion of the five per-claim functions and `mark_translate_finished` break the worker and its tests in the same commit, so splitting them would leave the suite red between phases. Its two clauses are the store-level lost-claim no-op and the one approved behaviour change seen end to end through `generate`. The held-claim instance end goes into the checkpoint as a control, not a third clause. Phase 2 (openers) is independent of the handle except for the recovery test's attribute reads, which phase 1 already rewrites, so it can follow cleanly. Phase 3 (route store helper) and phase 4 (issue 57's shared resolve) both edit internal_translate.py but are unrelated behaviours. They stay separate phases with one clause each, so neither checkpoint carries a compound claim. There is no prose phase: TRANSLATE_WORKER.md, the README, the module docs and CONTEXT.md are documentation that Step 9 updates. Known baseline risk: the three active test files were not freshly run at baseline, so a red result that was already there would show up in phase 1 and look like a regression. The phase 1 author should run the files first.\n</rationale>",
    "author:tests/tmp/test_54_translate_job_handle_phase1.py": "<assertions>\ntests/tmp/test_54_translate_job_handle_phase1.py:71 - control, for each of the six handle methods (parametrised: running cues, ready, already_english, failed, requeue, ready from instance): on a fresh claim with no takeover the method returns True. Excludes a method that always returns False. Supports C1.\ntests/tmp/test_54_translate_job_handle_phase1.py:74 - control, for each method: on that fresh claim the whole-table `_snapshot` changes, so an unchanged row after the takeover is the takeover's doing and not a method that writes nothing. Supports C1.\ntests/tmp/test_54_translate_job_handle_phase1.py:80 - control: after `store_ready_subtitles` on the Engine's own connection, `fetch_ready_subtitles` returns the Engine's cues, so the running row really was replaced. Supports C1.\ntests/tmp/test_54_translate_job_handle_phase1.py:82 - for each of the six methods, after the takeover the method returns exactly False. Excludes an UPDATE keyed on the row alone, and one matching on started_at alone the way `mark_translate_finished` did (the takeover keeps started_at). C1.\ntests/tmp/test_54_translate_job_handle_phase1.py:85 - for each of the six methods, the `_snapshot` taken after the method (every column of every row as SQL literals, rowid included) equals the one taken right after the takeover. Excludes any write that lands on the taken-over row. C1.\ntests/tmp/test_54_translate_job_handle_phase1.py:93 - held-claim control: `end_ready_from_instance` on a held claim returns True. C1 (held-claim control from the checkpoint).\ntests/tmp/test_54_translate_job_handle_phase1.py:94 - held-claim control: `fetch_ready_subtitles` then returns the instance cues. C1 (held-claim control).\ntests/tmp/test_54_translate_job_handle_phase1.py:100-118 - held-claim control: the whole row equals a literal dict. It is ready, source instance, track_text 'WEBVTT t', cues_json the compact literal '[{\"start\":1.0,\"end\":2.0,\"text\":\"Hello\"}]', and fetched_at == finished_at == 9000. detected_language 'fr', error None, attempts 1, queued_at 1000 and started_at 2000 keep the running job's values. Excludes two timestamps, a spaced encoding, and any write to another job column. C1 (held-claim control).\ntests/tmp/test_54_translate_job_handle_phase1.py:138 - control: inside the wrapped `fetch_instance_track`, the real fetch found the served English track (TRACK). Supports C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:139 - control: the Engine's store landed on the running row, which is now ready, instance, with ENGINE_TRACK. Supports C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:140 - control: the rig's cues_writes trigger recorded the Engine's upsert as the literal '[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]', so it would also record a worker write. Supports C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:141 - after `run_job`, the whole-table `_snapshot` equals the one taken at the takeover. Excludes today's upsert-then-stamp, which overwrites track_text, cues_json and fetched_at and stamps finished_at. C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:142 - no cues_json write was made after the takeover (cues_writes unchanged). This also excludes a write that changed the row and then put it back. C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:143 - the `[translate-worker]` log records are exactly [`[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`]. Excludes today's `job ready from the instance track` line, a stub that returns ready without writing, and any `job failed` or `job error` line. C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:144 - the runner made 0 transcribes. C2.\ntests/tmp/test_54_translate_job_handle_phase1.py:145 - the instance opened exactly [CAPTIONS_URL, TRACK_URL] and the media host opened nothing, so no video JSON or media was fetched after the takeover. C2.\n</assertions>\n\n<probes>\nProbe file tests/tmp/probe_54_phase1_observe.py, run with ValidateTests [\"tests/tmp/probe_54_phase1_observe.py\", \"-s\", \"-q\"] (output read from tests/last_test_output.txt; 3 passed).\n(1) Today's per-claim functions after a `store_ready_subtitles` takeover on a separate connection (v-1 queued 1000, claimed 2000, Engine stored at 8000). The snapshot after the takeover was ready/instance, fetched_at 8000, queued_at 1000, started_at 2000 (kept by the upsert), finished_at NULL, attempts 1. `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `requeue_translate_job` each printed `False True` (returned False, snapshot unchanged). `mark_translate_finished` did change the snapshot: finished_at became 9000. So the setup is sound, and a started_at-only match would be caught.\n(2) Encoding: `store_ready_subtitles` with [{\"start\":1.0,\"end\":2.0,\"text\":\"Hello\"}] stored cues_json '[{\"start\":1.0,\"end\":2.0,\"text\":\"Hello\"}]'. Over a running row it left detected_language 'fr', queued_at 1000, started_at 2000, attempts 1, error None and finished_at None. That is where the literal and the kept-column values in the held-claim row come from.\n(3) Today's worker, through Rig with EN_LISTING and TRACK served and `fetch_instance_track` wrapped so the Engine stores its own track after the real fetch. run_job returned False. The fetch returned TRACK with its parsed cues. The row after the run had TRACK, the worker's cues, and a wall-clock fetched_at and finished_at, so it did not equal the takeover snapshot (equal False). cues_writes was ['[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]'] at the takeover, with the worker's cues appended afterwards, so the trigger does record an upsert. The only log record was INFO '[translate-worker] job ready from the instance track video_id=v-1 host=peer.example'. transcribes was 0, the instance opened [captions, en.vtt] and the media host opened [].\nCheckpoint red run: ValidateTests [\"tests/tmp/test_54_translate_job_handle_phase1.py\", \"-q\"] gave 8 failed. All 6 C1 parameters and the held-claim test fail with AttributeError ('sqlite3.Row' object has no attribute write_running_cues / end_ready / end_already_english / end_failed / requeue / end_ready_from_instance), because the handle does not exist yet. In the C2 test, the controls at :138-140 pass and :141 fails: today the row holds the worker's TRACK, cues and a wall-clock fetched_at/finished_at instead of the Engine's 1700000000000 row.\nI could not delete tests/tmp/probe_54_phase1_observe.py because no delete tool is available. It imports functions this phase removes, so it should be deleted along with the other stale tests/tmp probes.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_54_translate_job_handle_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase1.py:73 \u2014 `write(job) is False`, parametrised over all six handle methods (running cues, ready, already_english, failed, requeue, ready from instance). It runs after `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the claimed running row. The control at :71 confirms the Engine's row is in place.</assertion>\n<expected>False for each of the six methods. The current run is red at exactly this line in all six cases with `AttributeError: 'sqlite3.Row' object has no attribute 'write_running_cues'` (and likewise `end_ready`, `end_already_english`, `end_failed`, `requeue`, `end_ready_from_instance`): today's `claim_translate_job` returns a `sqlite3.Row`, not a handle. The probe shows today's five per-claim functions on the same takeover each return False (`running cues False True` \u2026 `requeue False True`), which is the contract the methods take over.</expected>\n<wrong_implementation>A method whose UPDATE leaves out `state = 'running' AND started_at = ?` (for example `end_ready_from_instance` written as the old `store_ready_subtitles` upsert plus an unconditional stamp, or any SET matched on the key alone) matches the Engine's row and returns True. A method that never reports, or always returns True, also fails here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase1.py:76 \u2014 `_snapshot(path) == taken`: every column of every row, rowid included, as quoted SQL literals, reads the same after the write as after the takeover. It is armed by the held-claim controls at :82 and :85, which show the same write on a fresh claim returns True and changes the snapshot.</assertion>\n<expected>Equal: the Engine's row as it landed, i.e. state ready, source instance, fetched_at 8000, the Engine's track_text, cues_json `[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]`, queued_at 1000, started_at 2000, finished_at NULL, error NULL, detected_language NULL, attempts 1. These are the probe's observed takeover snapshot values. Not yet reached in the current run, because :73 fails first on the missing method.</expected>\n<wrong_implementation>An instance-track end that keeps today's pair (`store_ready_subtitles`, then `mark_translate_finished`) rewrites track_text, cues_json and fetched_at, and stamps finished_at. The probe saw `mark_translate_finished` alone turn finished_at NULL into 9000 on the taken-over row. A method that writes some column unconditionally and reports False anyway (a two-statement write where only the second is conditional) also changes the snapshot.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase1.py:143 \u2014 `_snapshot(rig.subtitles) == seen[\"taken\"]` after `run_job`. Here `fetch_instance_track` is wrapped so the real fetch finds the English track (control :140) and the Engine then stores its own different track ready/instance over the running row (control :141).</assertion>\n<expected>Equal to the snapshot taken right after the Engine's store: fetched_at 1700000000000, track_text `WEBVTT\\n\\n00:05.000 --> 00:06.000\\nEngine\\n`, cues_json `[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]`, finished_at NULL. The current run is red at exactly this line: the actual row has the worker's track (`WEBVTT\\n\\n00:03.000 --> 00:04.000\\n<i>World</i>\u2026`), its cues `[{\"start\":1.0,\"end\":2.5,\"text\":\"Hello\"},{\"start\":3.0,\"end\":4.0,\"text\":\"World\"}]`, and fetched_at = finished_at = 1791132912229.</expected>\n<wrong_implementation>Today's `generate` (store_ready_subtitles + mark_translate_finished) overwrites the Engine's row with the worker's track and stamps finished_at, as the run showed. So does a `generate` that calls the new conditional end but ignores its False and then calls the old upsert or another unconditional write.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase1.py:144 \u2014 `rig.cues_writes() == seen[\"writes\"]`: the trigger table recording every cues_json write holds nothing past the Engine's own write. The control at :142 shows the trigger records the Engine's upsert as `[ENGINE_CUES_JSON]`, so it would record a worker upsert too.</assertion>\n<expected>`['[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]']` only. The probe of today's code saw a second entry, `[{\"start\":1.0,\"end\":2.5,\"text\":\"Hello\"},{\"start\":3.0,\"end\":4.0,\"text\":\"World\"}]`, after the takeover.</expected>\n<wrong_implementation>A worker that writes the instance cues and then puts the Engine's value back, or writes the same bytes again, leaves the final snapshot looking right but adds a trigger entry. Today's unconditional upsert adds one, as the probe observed.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase1.py:145 \u2014 the worker's `[translate-worker]` log lines are exactly `[TAKEN_OVER]` = `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`.</assertion>\n<expected>Exactly that one line. The text was observed in probe_54_phase1_takeover_log.py, where today's `JobTakenOver` path (reached by a mid-job takeover) logged `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`. The route's `[translate] instance fetch failed\u2026` line in the same run is excluded by the prefix filter. Today's instance path logs `[translate-worker] job ready from the instance track video_id=v-1 host=peer.example` instead (observed in both the checkpoint run and the probe).</expected>\n<wrong_implementation>A `generate` that ignores the False from the instance-track end logs `job ready from the instance track`. One that maps the lost claim to `JobFailed` or a generic exception logs `job failed \u2026` or `job error \u2026` (and writes a failed end, which :143 also catches). One that falls through to transcription logs a later line.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim \u2014 yes, I found a gap and rewrote. Each docstring clause has an assertion: six methods \u00d7 (False :73, byte-identical snapshot :76), with the held-claim True/changed controls at :82/:85; the held-claim instance end (:95, :96, :105-120); and the worker (:143 row, :144 no further cues write, :145 the only log line, :146 no transcribe, :147 nothing fetched past the track). The gap was ordering: the held-claim control ran first, so the C1 assertions were never reached on a red run. I moved the takeover arm first (:67-76) and the held-claim control after it (:78-85). Green still needs both arms, so the takeover can't pass vacuously.\n2. Absence only \u2014 no after the rewrite. Every negative has a positive control in the same test. The False/unchanged snapshot at :73/:76 is armed by :82 (True on a fresh claim) and :85 (that write changes the row), and :71 shows the Engine's row is in place. The unchanged row/no cues write at :143/:144 is armed by :140 (the real fetch found TRACK), :141 (the Engine's row landed) and :142 (the trigger records an upsert). The log list at :145 is an exact-equality list with a required member.\n3. Echoed literal \u2014 no. Expected values are written-down literals or snapshots taken before the write, never recomputed by the test. Deleting the `state = 'running' AND started_at = ?` condition from `_update_claim`'s UPDATE turns :73/:76 red. Restoring the `store_ready_subtitles`/`mark_translate_finished` pair in `generate` (translate-worker.py:407-408 today) turns :143/:144/:145 red, as the current run shows.\n4. One value \u2014 no. C1 runs across all six methods, each with a fresh claim and its own held control. The snapshots at :76/:143 compare a before-and-after read of the same file; that invariance is the claim, and controls :82/:85 and :141/:142 show the same reads move when a write lands. The :143 snapshot covers every column of every row.\n5. The double \u2014 no project-owned module is replaced. StubRunner stands in for WhisperRunner (the model layer, severed). ScriptedHost sits behind the adapter's `build_opener` patch point. The `fetch_instance_track` wrap calls the real function and only adds the Engine's store after it, to time the race. The store, `generate` and `run_job` run for real.\n6. It collects \u2014 yes. The saved `--collect-only` output lists all 8 test ids (6 parametrised C1 cases, the held-claim test, the worker test) and `8 tests collected`. The summary table's \"no tests\" is how the runner prints a collect-only run. Every import resolved: the run reached each test body. After the edit the run again executed 8 tests. `rig`/`clip` come in as imported fixtures; Rig's `row`, `cues_writes`, `run`, `instance.opened`, `media.opened` and StubRunner's `transcribes` exist on the real classes (test_translate_worker.py:556, :572, :546, :428, :590).\n7. Observed, not predicted \u2014 yes, all observed, with one prediction named here. probe_54_phase1_observe.py (-s) showed: the takeover snapshot; today's five per-claim functions returning False with the snapshot unchanged; `mark_translate_finished` changing finished_at; the compact instance encoding `[{\"start\":1.0,\"end\":2.0,\"text\":\"Hello\"}]` with detected_language \"fr\" kept by the upsert; `fetch_instance_track` returning `(TRACK, cues)`; the trigger recording the Engine's upsert as `['[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]']`; transcribes 0; instance opened `[captions, en.vtt]`; media opened `[]`. The new probe_54_phase1_takeover_log.py showed the exact takeover log text. The one prediction: `fetched_at == finished_at == 9000` in the held-claim row dict comes from the plan's approved one-timestamp rule, and today's code cannot produce it (its `store_ready_subtitles` leaves finished_at NULL, as observed). The implemented method's first run will confirm it. The probe files stay in tests/tmp: I have no delete tool, and they are not in the active suite.\n8. Red, not green \u2014 yes, red. Final `ValidateTests tests/tmp/test_54_translate_job_handle_phase1.py`: `8 failed`, `[exit status 1]`.\n9. Red for the right reason \u2014 yes, after the rewrite. The first run failed all six C1 cases at the CONTROL at :71 (now :82), `assert write(job) is True` \u2192 `AttributeError: 'sqlite3.Row' object has no attribute 'write_running_cues'`. The held-claim test failed at its setup control (:92, `job.write_running_cues(...)`). That counts as a defect, so I rewrote: the takeover arm now runs first, and the held-claim setup sets cues_json/detected_language with one SQL UPDATE, so the first handle call is the one under test. Re-run: all six C1 cases now fail at `tests/tmp/test_54_translate_job_handle_phase1.py:73` `assert write(job) is False  # C1`, with `AttributeError: 'sqlite3.Row' object has no attribute 'write_running_cues'` / `'end_ready'` / `'end_already_english'` / `'end_failed'` / `'requeue'` / `'end_ready_from_instance'`. The control at :71 (Engine row in place) passed first. The method is missing because the phase hasn't built the handle yet. The held-claim test fails at :95 `assert job.end_ready_from_instance(...) is True  # held claim` with `AttributeError: 'sqlite3.Row' object has no attribute 'end_ready_from_instance'`, which is the phase's method. The worker test passes controls :140/:141/:142 and fails at `:143` `assert _snapshot(rig.subtitles) == seen[\"taken\"]  # C2`: the actual row has the worker's World/Hello track, cues `[{\"start\":1.0,\"end\":2.5,\"text\":\"Hello\"},{\"start\":3.0,\"end\":4.0,\"text\":\"World\"}]` and fetched_at = finished_at = 1791132912229, against the Engine's track, fetched_at 1700000000000 and finished_at NULL. Captured log: `[translate-worker] job ready from the instance track video_id=v-1 host=peer.example`. That is today's upsert-then-stamp, the behaviour this phase changes.\n10. Observed expected output \u2014 yes. Each row's `expected` states what the run showed: the AttributeError at :73 for every method and :95; the observed takeover-snapshot values that :76 must keep; the :143 diff values quoted from the run; the trigger list from the probe; the log text from the takeover-log probe. Where the run disagreed with my first draft, I changed the test: the controls failed before the clauses, so I reordered. No expected value was contradicted by a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### engine/server/data/subtitles.py\n- Added the `TranslateJob` frozen dataclass. It holds the claiming connection (`field(repr=False, compare=False)`) plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`.\n- It has six methods. Each is one `_update_claim` call that returns `bool`, with the timestamp passed in by the caller:\n  - `write_running_cues(cues, detected_language)`\n  - `end_ready(cues, finished_at)`\n  - `end_already_english(detected_language, finished_at)`\n  - `end_failed(error, finished_at)`\n  - `requeue()`\n  - `end_ready_from_instance(track_text, cues, finished_at)`\n- The first five methods keep the exact SET strings of the functions they replace. `end_ready_from_instance` sets state `ready`, source `instance`, `track_text`, `cues_json`, and `fetched_at` = `finished_at` from one value. It touches no other column.\n- `claim_translate_job` keeps its signature and its IMMEDIATE transaction. It now returns a `TranslateJob` built from the re-read row, or `None`.\n- `_update_claim(job, assignments, values)` now takes the handle. The WHERE clause is unchanged (`{_KEY} AND state = 'running' AND started_at = ?`), and it still runs inside `with job.conn:`.\n- Deleted `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `mark_translate_finished`.\n- Added `SOURCE_INSTANCE = \"instance\"` beside `SOURCE_WHISPER`.\n- Added `_instance_cues_text`: compact JSON that allows NaN, i.e. the same encoding `store_ready_subtitles` had inline. `store_ready_subtitles` now calls it, with its SQL and output unchanged, and `end_ready_from_instance` uses it too, so the two instance-track writers encode identically.\n- `recover_translate_jobs` is untouched (phase 2).\n- Updated the module docstring and the `store_ready_subtitles` docstring to describe the handle and to name the real takeover writer.\n- Import added: `from dataclasses import dataclass, field`.\n\n### engine/server/api/handlers/internal_translate.py\n- `SOURCE_INSTANCE` is now imported from `data.subtitles` and the local definition is removed, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves.\n- Nothing else changed.\n\n### engine/server/db/jobs/translate-worker.py\n- Imports:\n  - `data.subtitles` now gives `TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, recover_translate_jobs, write_translate_heartbeat`.\n  - `SOURCE_INSTANCE` is no longer imported from the route.\n- `translate_audio(job, pipe, runner, max_chunk, stop, progress)` now calls `job.end_already_english`, `job.write_running_cues` and `job.end_ready`. Each still raises `JobTakenOver` on `False`, so control flow is unchanged.\n- `generate(job, args, runner, stop, progress)`:\n  - It resolves with `job.video_id` and `job.instance_domain`.\n  - The unconditional `store_ready_subtitles` + `mark_translate_finished` pair is now one `job.end_ready_from_instance(fetched[0], fetched[1], now_ms())`, which raises `JobTakenOver` on `False`. This is the approved behaviour change: after a takeover, the worker writes nothing and logs `taken over by the instance track`.\n- `run_job(job, args, runner, stop, progress)` no longer takes `conn` or builds the claim tuple:\n  - requeue and end failed go through `job.requeue()` and `job.end_failed(...)`, with their results still ignored;\n  - the log texts are unchanged.\n- `serve` logs the claimed attributes instead of subscripting, and calls `run_job(job, ...)`.\n- Updated the `JobTakenOver` docstring to name the real writer, and the `run_job` and `generate` docstrings plus one sentence of the module docstring to describe the handle.\n\n### tests/active/test_subtitles.py\nEdited only where a removed function or a subscripted claim was used:\n- `WORKER_SCRIPT`: the import no longer names the removed functions. The key check uses attributes, and the writes use `job.write_running_cues` and `job.end_ready`.\n- The claim test, the recovery test and the `fetch_subtitle_state` test read attributes instead of subscripts.\n- The `fetch_subtitle_state` test writes running cues through the handle.\n- The docstring's concurrent-writers sentence names the handle methods.\n- Phase 2 still has to route the recovery test through `open_translate_worker_store`.\n\n### tests/active/test_internal_translate.py\n- `_claimed` returns the handle.\n- `_seed` and the two running-key tests call `write_running_cues`, `end_failed` and `end_already_english` on it. Their imports drop the removed functions.\n\n### tests/active/test_translate_worker.py\n- `Rig.claim` reads attributes.\n- `Rig.run` and the fetch-reason test call `run_job(job, ...)` without `conn`.\n- The docstring's `run_job` signature is updated to match.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_54_translate_job_handle_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D1\">\n<disposition>justified</disposition>\n<what>Narrowed the prose. The module docstring's first line said `open_subtitles_db` \"is the one store opener\", but no test here goes through the Engine or the worker. It now reads: \"`open_subtitles_db` opens any path or B1-era file as the full schema in WAL\". That is what :71\u201376 and :92\u2013103 assert.</what>\n</item>\n<item id=\"D2\">\n<disposition>fixed</disposition>\n<what>Test 4 now calls `store.open_subtitles_db(path).close()` at :163, after the first claim and before the worker opener. At :164 it asserts `job(\"t\") == (\"running\", 1, None, None)`. Two lines show the row could have been recovered: the control at :161 (t claimed, attempts 1), and :169, where `open_translate_worker_store` then returns (1, 0) on the same row. So :164 is not an empty absence. This excludes an `open_subtitles_db` that also runs recovery. A `recovering_open` variant added to probe_54_phase2_vs_draft.py, the draft opener plus `recover_translate_jobs`, fails test 4 with an AssertionError; the draft openers still pass all four tests. The \"under the worker's flock\" half stays where it was, at :116\u2013119. I also added a matching sentence to the recovery bullet of the docstring.</what>\n</item>\n</items>\n\n<findings_addressed>\nThere were no CRITICAL findings from either auditor. Of the claim auditor's recommendations, I took 1 by narrowing the D1 sentence in the docstring. I took 2 by adding the `open_subtitles_db` no-recovery assertion at :163\u2013164, armed by :161 and :169. I left 3 (`open_subtitles_db` failure mode) and 4 (comparing column declarations): neither is in this phase's `must_prove`, and adding them would grow the checkpoint past the ledger.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1a\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:71 \u2014 `path.parent.is_dir()` after `open_subtitles_db(tmp_path/\"a\"/\"b\"/\"subtitles.db\")`, with the control at :63 showing `a` absent before</assertion>\n<expected>True: the opener creates `a/b`</expected>\n<wrong_implementation>An opener that connects without mkdir. The no_mkdir variant raises OperationalError \"unable to open database file\" at the call.</wrong_implementation>\n</row>\n<row clause=\"C1b\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:73, :74, :75 \u2014 through a fresh plain connection to the nested file: the columns sorted equal ALL_COLUMNS, `[\"state\", \"queued_at\"]` is among the index column lists, and the heartbeat columns are [\"id\", \"beat_at\", \"pid\"]; plus :67, where the returned connection reads `fetch_translate_heartbeat` as None</assertion>\n<expected>All fourteen columns, the (state, queued_at) index, and heartbeat id/beat_at/pid</expected>\n<wrong_implementation>Connect without migrating: columns read [] (probed). A partial migration missing the index or the heartbeat table fails :74 or :75.</wrong_implementation>\n</row>\n<row clause=\"C1c\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:76 \u2014 the nested file's journal_mode, read through a fresh plain connection</assertion>\n<expected>\"wal\"</expected>\n<wrong_implementation>A plain sqlite3.connect plus migrate leaves the rollback journal. The no_wal variant fails tests 1 and 2.</wrong_implementation>\n</row>\n<row clause=\"C1d\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:97, :98, :99 \u2014 the B1 file's columns, index and heartbeat columns after `open_subtitles_db`; plus :92 and :103, where the returned connection and a plain one read B1_CUES</assertion>\n<expected>ALL_COLUMNS, the (state, queued_at) index, heartbeat id/beat_at/pid, and old cues equal to B1_CUES</expected>\n<wrong_implementation>An opener that leaves an existing B1 table unmigrated fails the column, index and heartbeat checks. One that recreates the table loses the rows and fails :92 and :103.</wrong_implementation>\n</row>\n<row clause=\"C1e\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:100 \u2014 the B1 file's journal_mode after the opener; the control at :85 shows \"delete\" before</assertion>\n<expected>\"wal\"</expected>\n<wrong_implementation>Migrating without the WAL connect: ensure_subtitles_schema alone leaves \"delete\" (probed). The no_wal variant fails here.</wrong_implementation>\n</row>\n<row clause=\"C2a\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:116 \u2014 while a separate os.open description holds LOCK_EX, `open_translate_worker_store(path, mine, 1)`, bounded by `_bounded`</assertion>\n<expected>raises BlockingIOError</expected>\n<wrong_implementation>No flock: the no_lock variant fails with \"DID NOT RAISE BlockingIOError\". A blocking LOCK_EX: the blocking variant fails with \"blocked for 10 s\" instead of hanging.</wrong_implementation>\n</row>\n<row clause=\"C2b\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:118, :119 \u2014 after the refusal, neither subtitles.db nor `sub` exists. Controls at :126\u2013127: once the holder is closed, the same call returns (0, 0) and the file exists</assertion>\n<expected>both absent</expected>\n<wrong_implementation>mkdir or connect before the flock. The mkdir_first variant fails at :119.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The one negative assertion added, :164 (t still running after `open_subtitles_db`), is armed on both sides. Before it, :161 shows t was claimed; after it, :169 shows `open_translate_worker_store` returns (1, 0) on that same row, so the row was recoverable. The existing negatives keep their controls: :118\u2013119 by :126\u2013127, and :186 by :155.\n2. No. :164 compares a SELECT on the file against a literal state tuple; the test does not transform anything itself. Adding a recover call to the opener (the probe's recovering_open variant) turns test 4 red.\n3. No. The no-recovery observable at :164 is read on a row that the worker opener then recovers at a different input, :169 (1, 0). It is not read at one point in isolation.\n4. No. No double stands in for a project module. The probe's variants are injected only by the probe file, never by the checkpoint.\n5. Yes, it collects: ValidateTests on the checkpoint collected 4 tests. `store.open_subtitles_db` is reached as a module attribute, and `job` was already defined before :163.\n6. Yes. (\"running\", 1, None, None) was observed: with the plan's draft openers injected (probe_54_phase2_vs_draft.py), test 4 passes, and the recovering_open variant fails test 4 with an AssertionError. I did not see which line raised it. I infer :164, because it is the first point after which recovery could show; a traceback of that variant would confirm it.\n7. Yes. Against today's code all 4 tests fail with AttributeError: at :65 and :90 (open_subtitles_db), :117 (open_translate_worker_store) and now :163 (open_subtitles_db), each after its controls. Leftover probe files that need deleting by hand, since I have no delete tool: tests/tmp/probe_54_phase2_flock.py, probe_54_phase2_vs_draft.py, probe_54_phase2_unlock.py and probe_54_phase2_c1_lines.py.\n</answers>",
    "self_check:tests/tmp/test_54_translate_job_handle_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:67 \u2014 on a/b/subtitles.db with neither directory present, `store.fetch_translate_heartbeat(conn)` on the connection `open_subtitles_db` returned is None</assertion>\n<expected>None: the heartbeat table exists and is empty (seen: the test passes when the probe draft opener, mkdir + connect_subtitles_db + ensure_subtitles_schema, is put in place)</expected>\n<wrong_implementation>An opener that creates the directory and connects but never migrates. Seen in probe_54_phase2_c1_lines.py: OperationalError 'no such table: translate_worker_heartbeat' at line 67.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:71 \u2014 `path.parent.is_dir()` after the opener on the missing nested path</assertion>\n<expected>True: both a and b exist (seen passing under the draft)</expected>\n<wrong_implementation>An opener with no mkdir, i.e. connect_subtitles_db + ensure_subtitles_schema on its own. Seen in the vs_draft probe (no_mkdir): the opener call at line 65 raises OperationalError 'unable to open database file', so the test fails before it gets this far.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:73 and :97 \u2014 `sorted(columns) == sorted(ALL_COLUMNS)`, the file's subtitles columns read through a fresh plain connection, for the nested new file and for the B1 file</assertion>\n<expected>B1's eight columns plus queued_at, started_at, finished_at, error, detected_language, attempts, fourteen in all (seen passing under the draft for both inputs)</expected>\n<wrong_implementation>An opener that connects without migrating. Seen in probe_54_phase2_c1_lines.py: AssertionError at line 97 on the B1 file, which still has only its eight columns. On the nested path that opener already fails at line 67.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:74 and :98 \u2014 `[\"state\", \"queued_at\"] in indexed`, the column lists of the subtitles indexes, for both inputs</assertion>\n<expected>An index covering exactly (state, queued_at) is present (seen passing under the draft for both inputs)</expected>\n<wrong_implementation>An opener that adds the job columns but not the queue index, or that does not migrate at all. Its index lists hold only the primary key's autoindex [video_id, instance_domain, target_language], so the assertion fails. This is a prediction: the not-migrated mutant failed at an earlier line, and no index-only mutant was run.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:75 and :99 \u2014 `heartbeat == [\"id\", \"beat_at\", \"pid\"]`, the translate_worker_heartbeat columns through a plain connection, for both inputs</assertion>\n<expected>[\"id\", \"beat_at\", \"pid\"] (seen passing under the draft for both inputs)</expected>\n<wrong_implementation>An opener that migrates only the subtitles table, or not at all. table_info on a missing table gives [] and the assertion fails. This is a prediction: that mutant was not run on its own.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:76 and :100 \u2014 `mode == \"wal\"`, PRAGMA journal_mode through a fresh plain connection after the opener closed, for both inputs; for the B1 file, line 85 confirms the file started in \"delete\" mode</assertion>\n<expected>\"wal\" (seen passing under the draft for both inputs)</expected>\n<wrong_implementation>An opener that runs mkdir + a bare sqlite3.connect + ensure_subtitles_schema and never switches to WAL. Seen in probe_54_phase2_c1_lines.py: AssertionError at line 76 and at line 100, where the file still reads as rollback journal.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:92 and :103 \u2014 `_old_cues(...) == B1_CUES` on the B1 file after the opener, first through the returned connection and then through a fresh plain one; line 86 shows the same reader returns them before</assertion>\n<expected>{(\"v-1\",\"peer.example\"): [{start 1.0, end 2.5, \"Hello\"}], (\"v-2\",\"other.example\"): [{0.5,1.0,\"One\"},{3.0,4.25,\"Two\"}]} (seen passing under the draft)</expected>\n<wrong_implementation>An opener that brings a B1 file up to the current schema by dropping and recreating the table. fetch_ready_subtitles then returns None for both keys and the dict comparison fails. This is a prediction: that mutant was not run.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:116-117 \u2014 while a separate os.open description holds LOCK_EX, `store.open_translate_worker_store(path, mine, 1)` raises BlockingIOError inside a 10 s SIGALRM bound. Controls at 124-131: once the holder is closed, the same call returns (0, 0) and a third description is refused the lock.</assertion>\n<expected>BlockingIOError raised at once (seen under the draft, which uses flock LOCK_EX|LOCK_NB)</expected>\n<wrong_implementation>Seen in the vs_draft probe. An opener that never locks: 'DID NOT RAISE BlockingIOError'. An opener that locks without LOCK_NB: the alarm fires, 'open_translate_worker_store blocked for 10 s instead of refusing the held flock'. An opener that locks and then unlocks: the line-130 control reads 'DID NOT RAISE BlockingIOError'.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:118 \u2014 `not path.exists()` after the refusal; armed by line 127, where `path.exists()` holds after the same call succeeds</assertion>\n<expected>The file does not exist (seen under the draft; line 127 then reads True)</expected>\n<wrong_implementation>An opener that opens the store first and takes the flock afterwards. The database file exists by the time BlockingIOError is raised, so the assertion fails. This is a prediction: the open-then-lock order was not run as a mutant.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:119 \u2014 `not path.parent.exists()` after the refusal: the sub directory was never created</assertion>\n<expected>The directory does not exist (seen under the draft)</expected>\n<wrong_implementation>An opener that runs path.parent.mkdir before it flocks. Seen in the vs_draft probe (mkdir_first): an AssertionError in this test. It creates no file, so line 118 passes and this line is the one that fails.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. Every docstring bullet has assertions. C1 is covered for the missing nested path (lines 67, 71, 73-76) and for the B1 file (lines 85-86 as controls, then 92, 97-100, 103). C2 is covered at 116-119 with its controls at 124-131. The recovery bullet is covered by the counts (1, 0) and (2, 1), the job rows, the claims read through `.video_id`/`.attempts`, and the bystander comparison.\n2. Absence only: one gap, now fixed. The negatives at 118/119 are armed by 127 (the same call creates the file once the lock is free). The pytest.raises at 116 is armed by 124/126 (the same call on the same descriptor succeeds). The bystander comparison at the end of the recovery test was the gap: it compared two lists picked out by a `\"'z'\"`/`\"'b1'\"` quote() filter I had never seen match anything, so it could have passed as two empty lists. I added a control at line 81, `assert len(bystanders_before) == 2`, and the draft run shows it passing.\n3. Echoed literal: no. Expected values are test-side literals: ALL_COLUMNS from test_subtitles.py's own B1_COLUMNS | JOB_COLUMN_NAMES, [\"id\",\"beat_at\",\"pid\"], \"wal\", B1_CUES. The test never copies a production transformation. Deleting the WAL pragma from the opener turns 76/100 red (seen). Deleting the ensure_subtitles_schema call turns 67/97 red (seen). Deleting the mkdir turns the nested test red at the line-65 call (seen). Deleting the LOCK_NB flock turns 116 red (seen).\n4. One value: no. Schema and journal mode are read for two inputs, a new nested path and a B1 rollback file. The worker opener is read refused, then free with counts (0, 0), then (1, 0) and (2, 1) under recovery.\n5. The double: no. The checkpoint has no doubles. It calls the real data.subtitles module and real sqlite/flock on tmp_path. The monkeypatched openers live only in the probes under tests/tmp/.\n6. It collects: yes. The run collected 4 items (\"collected 4 items\", 4 failed), matching the four tests written. The names imported from test_subtitles all exist (checked: ALL_COLUMNS, B1_CUES, B1_READY_INSTANCE, HOST, RECOVERY_TEXT, _b1_file, _insert, _old_cues, _plain, _snapshot, _subtitles). The phase's names are reached through the module, so their absence fails each test at its own call rather than at collection.\n7. Observed, not predicted: every expected value comes from a run. In probe_54_phase2_vs_draft.py, a draft of the two openers built from the existing store functions, put in place on the module, passes all four checkpoint tests, including the new line-81 control. Seven mutants each turn a test red: no_wal, no_mkdir, mkdir_first, blocking, no_lock, unlocking, no_recover. probe_54_phase2_c1_lines.py shows the line each C1 mutant fails on: no_wal at 76 and 100; no_schema at 67 (OperationalError 'no such table: translate_worker_heartbeat') and 97. Where a row's wrong implementation was never run (missing index only, heartbeat only, drop-and-recreate, open-then-lock), the row says it is a prediction.\n8. Red, not green: yes, it fails. ValidateTests on the checkpoint: \"4 failed\", \"[exit status 1]\".\n9. Red for the right reason: yes. Every failure is the phase's missing opener, reached after the test's controls passed:\n- line 65: \"AttributeError: module 'data.subtitles' has no attribute 'open_subtitles_db'. Did you mean: 'connect_subtitles_db'?\"\n- line 90: the same, after the controls at 85-86 passed\n- line 117: \"AttributeError: module 'data.subtitles' has no attribute 'open_translate_worker_store'\"\n- line 164: the same, after the claim control at 87 and the bystander control at 81 passed\nNo control assertion failed.\n10. Observed expected output: every row's `expected` matches the draft run, where all four checkpoint tests pass. Every row's mutant reading that was actually run matches what the probes printed, and the rows that were not run say so. One limit: these probes stay under tests/tmp/ because I have no delete tool. They are probe_54_phase2_vs_draft.py, probe_54_phase2_c1_lines.py, and an empty test_probe_54_phase2.py.\n</answers>\n\n<exemptions>\nnone\n</exemptions>"
  },
  "requirements": "### Purpose\n\nMove a translate job's invariants out of the callers and into the subtitles store (`engine/server/data/subtitles.py`). Today the callers carry four rules: the `started_at` compare-and-set on every write for a claimed job, the open-then-migrate order, recovery only under the worker's flock, and the whitelist/denylist resolve. They also carry the rules for a translatable video, which are duplicated between the `/internal/translate` routes and the translate worker. This is a refactor. Observable behaviour stays the same, apart from the one approved change described under \"End ready from an instance track\". It folds in issue 57 (resolve a translatable video once). Issue 56's job-pipeline part depends on it.\n\n### Job handle\n\n- `claim_translate_job` (or its replacement) returns a job handle, or `None` when no job for the target language is queued. The claim itself is unchanged: in one IMMEDIATE transaction, the oldest `queued` row by `queued_at` then rowid becomes `running`, gets `started_at` and has `attempts` raised by 1.\n- The handle is a small class or dataclass in `engine/server/data/subtitles.py`. It carries the job's key (`video_id`, `instance_domain`, `target_language`), its `started_at` and its `attempts`. It either holds the store connection or takes it per call; the design step chooses which.\n- The handle exposes these operations. Each one does the compare-and-set internally: it matches only while the row is `running` with this claim's `started_at`. Each reports whether the claim still held.\n  1. **Write running cues:** rewrite the whole `cues_json` (as `_cues_text`, i.e. `allow_nan=False`) and set `detected_language`. Same as today's `store_running_cues`.\n  2. **End ready:** state `ready`, the full start-sorted `cues_json`, `fetched_at` = `finished_at` = the given time. Same as today's `finish_translate_ready`.\n  3. **End already_english:** state `already_english`, `detected_language`, `finished_at`. Same as today's `finish_translate_already_english`.\n  4. **End failed:** state `failed`, `error` text, `finished_at`. Partial cues stay. Same as today's `finish_translate_failed`.\n  5. **Requeue:** state `queued`, `attempts - 1`, with `queued_at` kept. Same as today's `requeue_translate_job`.\n  6. **End ready from an instance track:** see the next section.\n- How a lost claim is reported is the design step's choice, made once for every operation: either return `bool` (claim held), or raise one exception that the worker maps to its `JobTakenOver` path.\n- No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `requeue_translate_job` and `mark_translate_finished` are removed from the store's public interface. `_update_claim` may remain as a private helper. `store_ready_subtitles` stays: the route still uses it.\n\n### End ready from an instance track (one store operation)\n\n- This replaces the worker's `store_ready_subtitles` + `mark_translate_finished` pair (`translate-worker.py` `generate`) with one conditional UPDATE. It applies only while the row is `running` with this claim's `started_at`.\n- While the claim holds, it leaves exactly today's row: state `ready`, source `instance`, `track_text` set, `cues_json` set, `fetched_at` set and `finished_at` set. The cues are encoded as `store_ready_subtitles` encodes them today: `json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))`, which allows NaN. They are not encoded with `_cues_text`. Other job columns (`detected_language`, `error`, `attempts`, `queued_at`, `started_at`) are left as they are, as the upsert leaves them today.\n- Approved simplification: a single timestamp supplies both `fetched_at` and `finished_at`. Today two separate `now_ms()` calls set them.\n- Approved behaviour change: when the claim was lost, the operation changes nothing. Today the worker's upsert overwrites the Engine's row and then stamps `finished_at`. The worker then takes its takeover path: it logs `taken over by the instance track video_id=\u2026 host=\u2026` and writes nothing further for the job.\n\n### Takeover (unchanged behaviour)\n\n- The Engine state route's instance-track store (`_store_cues` \u2192 `store_ready_subtitles`, an unconditional upsert) still replaces a running row, so the instance track wins the race. Making it conditional is out of scope.\n- After such a takeover, every handle operation reports the claim lost. The worker's `JobTakenOver` path stays: it logs the takeover and writes nothing further for that job, which means no `failed` end and no requeue.\n- The real writer is the state route's instance-track store, racing an enqueue and a claim. The route reads no row (or a `failed`/`already_english` row) and fetches the instance, which takes up to its 15 s budget. Meanwhile a job is enqueued and claimed, and the route's upsert then lands on the running row. An older blue/green Engine is a possible further writer. The `JobTakenOver` docstring and any docstrings that say \"B1's route\" (`run_job`, `_update_claim`/handle) must name this writer. `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` \u00a7 \"Takeover by the Instance Track\" already describes it; it is updated only where it names removed functions. `CONTEXT.md` already defines \"Claim\" and \"taken over\" and needs no change unless the wording of the handle requires it.\n\n### Opening the store\n\n- One open function in `subtitles.py` creates the parent directory (`mkdir(parents=True, exist_ok=True)`), connects in WAL mode with today's busy timeout and lock-retry loop (`connect_subtitles_db`), and migrates the schema (`ensure_subtitles_schema`).\n- The Engine start (`engine/server/api/server.py`, currently lines 371-372) uses it. The open stays where it is in start-up order: after `prepare_trending_override`, so a rejected start still creates nothing. The worker's `enqueue` command and its `run` service use it too. None of these callers calls anything else to open the store.\n- The heartbeat thread's own connection (`heartbeat_loop`) may use it too, or may keep the plain connect; the design step decides.\n- On a fresh path, opening creates the directory and the full schema. On a B1-era file, it adds the job columns. The existing concurrent-opener guarantees hold: no `duplicate column`, no `database is locked`, and WAL afterwards.\n\n### Recovery under the flock\n\n- `recover_translate_jobs` logic is unchanged: rows at `attempts >= MAX_CLAIMS` become `failed` with `worker stopped while running twice`, and other `running` rows go back to `queued`.\n- Callers must not be able to run it without the worker's flock by mistake. Two acceptable shapes: a worker-service store opener that runs recovery and can only be called while the flock is held (for example, it acquires the flock itself or takes the held lock as an argument), or recovery that takes proof of the lock. A test, or the type of the call, shows this.\n\n### Route store access\n\n- In `engine/server/api/handlers/internal_translate.py`, three sites each repeat the \"hold `server.subtitles_db_lock`, take `server.subtitles_db`, treat `None` as closed\" block: `_read_key`, `_store_cues` and the enqueue in `handle_internal_translate_enqueue`. One helper replaces all three.\n- Responses for a closed store are unchanged:\n  - state read: no row and `available: false`;\n  - track store: a no-op, logged;\n  - enqueue: `{\"state\": \"none\", \"available\": false}`, nothing queued.\n- `sqlite3.Error` handling is unchanged: the read logs `cache read failed` and answers no row, not available; the store logs `cache write failed`; the enqueue logs and answers 503 `{\"error\": \"Translate store unavailable\"}`. The enqueue's beat check and enqueue stay under one lock hold.\n- The route tests' `SimpleNamespace` server fake (`db`, `db_lock`, `video_error_threshold`, `subtitles_db`, `subtitles_db_lock`, `statement_timeout_seconds`) stays as it is. Changing it is not required.\n\n### Resolve a translatable video (issue 57)\n\n- One function takes a whitelist connection, a video id, a normalised host and an error threshold. It returns either the whitelisted row or a refusal, and never writes an HTTP response. The refusals are:\n  - not in whitelist: `fetch_video_row` with the threshold finds no row;\n  - host denied: `normalize_host(row[\"instance_domain\"])` is in `list_active_denied_hosts(conn)`;\n  - a missing host (`None` or empty): refused, never matched against the id on any host (`fetch_video_row` with a `None` host matches any host).\n- The `/internal/translate` routes and the translate worker both use it, and its location must be importable by both. The worker already imports from `handlers.*` via `api/` on `sys.path`.\n- Route: `_resolve_translate_key` keeps its own 400 validation of the `{id, host}` body: invalid JSON, `Missing id or host`, `Invalid host`. It calls the shared function on `server.db` under `server.db_lock` with `server.video_error_threshold`, and maps any refusal to its current 404 `{\"error\": \"Video not found\"}`. It keeps using the row's canonical `video_id`, `instance_domain` and `video_uuid or video_id`.\n- Worker: `resolve_video` keeps its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its stored-duration bound (a NULL duration passes). It maps refusals to its current texts: `not in whitelist`, `host denied`, `duration Ns over Ms`. The `enqueue` command's `refused: invalid id or host` check is unchanged, and so are `generate`'s `sqlite3.OperationalError` \u2192 `WhitelistBusy` mapping and its exit codes.\n\n### Documentation\n\n- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` and the \"Translate worker and its store contract\" section of `engine/server/README.md` describe three things: the job handle and its operations, the takeover writer (the state route's instance-track store racing an enqueue and a claim), and the single store opener (plus how recovery is tied to the flock).\n- The module docstrings of `subtitles.py`, `internal_translate.py` and `translate-worker.py` stop naming removed functions.\n\n### Acceptance criteria\n\n- [ ] No caller outside the store module builds, unpacks or passes a `(video_id, instance_domain, target_language, started_at)` tuple. The five per-claim functions and `mark_translate_finished` are no longer public in the store.\n- [ ] Every handle operation (running cues, ready, already_english, failed, requeue, ready from instance track) is a no-op that reports the claim lost when the row is no longer `running` with the claim's `started_at`. A test proves this for each operation.\n- [ ] Ending ready from an instance track while the claim holds leaves state `ready`, source `instance`, the track text and cues, and `fetched_at` and `finished_at` set. When the claim was lost, it changes nothing.\n- [ ] A state-route instance-track store over a running row still wins. The worker then logs the takeover and writes nothing further for that job.\n- [ ] Opening the store on a fresh path creates the directory and the full schema, and opening a B1-era file adds the job columns. The Engine and the worker's `enqueue` and `run` entry points call nothing else to open the store.\n- [ ] Recovery cannot be called from the worker without the flock held. A test or the type of the call shows this.\n- [ ] The three route sites use one store-access helper, and route responses for a closed store are unchanged.\n- [ ] One resolve function serves both the routes and the worker. A missing host is refused, and a denied host is refused on the row's normalised domain. The routes' 400 and 404 responses and the worker's refusal texts are unchanged.\n- [ ] The existing tests pass: `tests/active/test_internal_translate.py`, `tests/active/test_translate_worker.py` and `tests/active/test_subtitles.py`. They are rewritten only where they used the removed functions or the claim tuple, for example the subprocess writer script in `test_subtitles.py` and the row-seeding helpers in `test_internal_translate.py`. The worker test for \"the instance holds an English track\" still sees ready/instance with the parsed cues and track text, and `finished_at` taken during the run.\n- [ ] The docs listed above describe the handle, the takeover writer and the single store opener.\n\n### Out of scope\n\n- Making the state route's instance-track store conditional (a running job winning the race).\n- Removing `JobTakenOver`.\n- The source-instance fetch adapter (issue 53, already delivered) and the rest of the worker split (issue 56): timing parameters and moving the pipeline out of the script.\n- Changing job states, `MAX_CLAIMS`, recovery's requeue-once rule, the queue cap or the heartbeat.\n- Any schema change beyond what the store opener already migrates.\n- Replacing the route tests' `SimpleNamespace` server fake.\n- Closing issue 57 in the tracker. That is housekeeping after delivery, as covered by 54, and not part of the code build.\n\n### Baseline suite state\n\n- Pre-build suite exited 0, not a variant run. The selective runner chose 1 of 65 groups (`test_search_fusion.py`, 10 passed), and 64 groups were unchanged and not re-run. The translate route, translate worker and subtitles store tests were therefore not freshly run at baseline; they are presumed green from their last recorded pass.\n\n### Notes on the tree\n\n- The issue's line references are out of date since issue 53 landed. The claim tuple is built at `translate-worker.py:437`. The upsert-then-stamp is at `:407-408`. The opener sites are `:131-135` (enqueue) and `:531-535` (run), plus the heartbeat at `:465`. `JobTakenOver` is at `:87-88`, and the route's lock sites are `internal_translate.py:157-160`, `:179-182` and `:261-263`. The behaviour the issue describes matches the code.",
  "approved": [
    "1",
    "2",
    "3",
    "5",
    "6"
  ],
  "initial_solution": "### Approach\n\nThe work touches three code files and no new modules: `engine/server/data/subtitles.py` (the store), `engine/server/api/handlers/internal_translate.py` (the routes and the shared resolve) and `engine/server/db/jobs/translate-worker.py` (the worker). `engine/server/api/server.py` changes by one call, and the docs and tests follow.\n\n**Job handle.** `subtitles.py` gets a small frozen dataclass, `TranslateJob`. It holds the store connection the claim was made on, plus `video_id`, `instance_domain`, `target_language`, `started_at` and `attempts`. `claim_translate_job` keeps its name, signature and IMMEDIATE transaction (oldest `queued` by `queued_at` then rowid, set `running` and `started_at`, raise `attempts` by 1). It now returns this handle, built from the row it already re-reads, or `None`. The handle holds the connection rather than taking it per call. Every write for a claim must go to the connection that claimed it, and holding it means no caller can pair a handle with the wrong connection (the heartbeat thread has its own). It also lets `generate` and `translate_audio` stop carrying a connection argument at all.\n\nThe handle has six methods, each a thin call to the private `_update_claim`, which keeps its single conditional UPDATE matching `state = 'running' AND started_at = ?`. Each method takes its timestamp from the caller, as today:\n- write running cues (`_cues_text`, plus `detected_language`);\n- end ready (start-sorted cues via `_cues_text`, `fetched_at` = `finished_at` = the given time);\n- end already_english;\n- end failed (partial cues stay);\n- requeue (`queued`, `attempts - 1`, `queued_at` untouched);\n- end ready from an instance track.\n\n`_update_claim` takes the handle's fields instead of a loose key, so the claim tuple exists only inside the module. The five per-claim functions and `mark_translate_finished` are deleted. `store_ready_subtitles` stays.\n\n**Lost claim reported as `bool`.** Every method returns `True` when the claim held and `False` otherwise. This is today's contract, so the worker's control flow is unchanged:\n- `translate_audio` still raises `JobTakenOver` on `False` from running cues, already_english and ready.\n- `generate` raises it on `False` from the new instance-track end.\n- `run_job` still ignores the result of requeue and end failed, as today. A takeover that lands during a stop or a failure therefore still writes nothing and logs what it logs today.\n\n**End ready from an instance track.** One conditional UPDATE through `_update_claim` sets:\n- state `ready`;\n- source `instance`;\n- `track_text`;\n- `cues_json`;\n- `fetched_at` = `finished_at` = one timestamp.\n\nIt leaves every other job column alone. The cues are encoded by a private helper that `store_ready_subtitles` also switches to: `json.dumps(..., ensure_ascii=False, separators=(\",\", \":\"))`, NaN allowed, not `_cues_text`. One helper keeps the two instance-track writers encoding identically. `SOURCE_INSTANCE` moves into `subtitles.py` beside `SOURCE_WHISPER`. `internal_translate.py` imports it from there, so its own name still resolves. The worker no longer needs it at all, because the handle method fixes the source. In `generate`, the upsert-then-stamp at `:407-408` becomes one call with one `now_ms()`. A `False` result raises `JobTakenOver`, and the existing `taken over by the instance track video_id=\u2026 host=\u2026` log line follows. This is the approved change: a lost claim now writes nothing, where today the upsert overwrites the Engine's row.\n\n**Takeover unchanged.** The state route's `_store_cues` still calls the unconditional `store_ready_subtitles`, so the instance track still wins over a running row. Every handle method then matches nothing. The docstrings of `JobTakenOver`, `run_job`, `_update_claim` and the handle name the real writer: the state route's instance-track store, racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. They no longer say \"B1's route\".\n\n**Single store opener.** `open_subtitles_db(path)` in `subtitles.py` does three things in order:\n1. creates the parent directory;\n2. calls `connect_subtitles_db`, keeping the WAL switch, the 30 s busy timeout and the lock-retry loop;\n3. runs `ensure_subtitles_schema`.\n\nIf the migration raises, it closes the connection before re-raising. Three callers use it: `server.py` (its two lines at 371-372, in the same place, after `prepare_trending_override`), the worker's `enqueue` (replacing `:131-135`) and the worker service opener below. `connect_subtitles_db` and `ensure_subtitles_schema` stay public, because the tests and the heartbeat use them. The concurrent-opener guarantees come for free: the opener only composes the two functions that provide them today.\n\n**Heartbeat keeps the plain connect.** The beat thread starts only after the main thread's opener has migrated the file. Re-running the migration there would be a pointless extra IMMEDIATE transaction on every service start, so this decision is to keep `connect_subtitles_db` there.\n\n**Recovery tied to the flock.** `subtitles.py` gets a worker-service opener, `open_translate_worker_store(path, lock_fd, finished_at)`, which returns the connection and the `(requeued, failed)` counts. Before anything touches the file, it re-asserts `flock(lock_fd, LOCK_EX | LOCK_NB)` on the descriptor it was given:\n- On a descriptor whose open file description already holds the lock (the worker's), this is a no-op.\n- When another process or open file description holds the lock, it raises `BlockingIOError` before the file is opened. Nothing is created or written.\n- On an unlocked descriptor it takes the lock. Either way recovery can only run while the flock is held.\n\nIt then calls `open_subtitles_db` and recovery. `recover_translate_jobs` becomes private `_recover_translate_jobs` with its logic unchanged, so nothing outside the module can call it bare. `command_run` keeps its own LOCK_NB acquire first, which preserves the `another worker holds` log line and exit 6 before the store is opened. It then replaces `:531-536` with the one call. `fcntl` is imported inside that function, so the Engine's import of `subtitles.py` gains nothing.\n\nTests:\n- a second open file description holding the lock makes the opener raise and leaves the subtitles file absent;\n- with the lock held, recovery runs exactly as today's recovery test expects.\n\n**Route store access.** One context manager in `internal_translate.py`, `_subtitles_store(server)`, holds `server.subtitles_db_lock` for its body and yields `server.subtitles_db`, which is `None` when the store is closed. The three sites (`_read_key`, `_store_cues`, the enqueue) use it. Each keeps its own `sqlite3.Error` handler and its own closed-store answer, because the three answers differ:\n- the read answers no row, not available;\n- the enqueue answers `{\"state\": \"none\", \"available\": false}`;\n- the track store gains one info log line on a closed store, which is the operator's decision.\n\nThe enqueue's beat check and enqueue stay inside one `with`. The route tests' `SimpleNamespace` fake is untouched.\n\n**Resolve a translatable video (issue 57).** `resolve_translatable_video(conn, video_id, host, error_threshold)` lives in `handlers/internal_translate.py`. That is the route's own module, and the worker already imports it via `api/` on `sys.path`. It returns `(row, None)` or `(None, refusal)` and writes no response. The refusal is one of three strings:\n- `missing host`, for a `None` or empty host, decided before any lookup;\n- `not in whitelist`, when `fetch_video_row` with the threshold finds no row;\n- `host denied`, when the row's `normalize_host(instance_domain)` is in `list_active_denied_hosts(conn)`.\n\nThe middle two are exactly the worker's current texts.\n\n- **Route:** `_resolve_translate_key` keeps its own body validation and its three 400s. It calls the shared function on `server.db` under one `server.db_lock` hold, which merges today's two hold sites into one, with `server.video_error_threshold`. Any refusal maps to 404 `VIDEO_NOT_FOUND`, and the route keeps using the canonical `video_id`, `instance_domain` and `video_uuid or video_id`. It drops its `resolve_video_row` import.\n- **Worker:** `resolve_video` keeps its signature (tests monkeypatch it), its `connect_readonly_db` connection, its `PRAGMA busy_timeout = 30000`, `VIDEO_ERROR_THRESHOLD` and its duration bound. Refusals pass through unchanged, except `missing host`, which maps to `not in whitelist`. That is what an empty host yields today, and `enqueue` refuses such a host earlier anyway. `generate`'s `OperationalError` \u2192 `WhitelistBusy` mapping and all exit codes are untouched.\n\n**Tests.** Rewritten only where the removed functions, the claim tuple or the claim's return are used:\n- `test_subtitles.py`: the subprocess writer script, the claim test's subscripting, the `fetch_subtitle_state` test and the recovery test, which now goes through the lock-taking opener.\n- `test_internal_translate.py`: `_claimed` and `_seed`, plus the two running/failed sequences at `:755-792`.\n- `test_translate_worker.py`: `Rig.claim`, `Rig.run` and the fetch-reason test's `run_job` call, because `run_job` no longer takes a connection.\n\nNew tests:\n- a parametrised store test for the six handle methods: after a `store_ready_subtitles` takeover, each returns `False` and leaves the row byte-identical;\n- the instance-track end while the claim holds;\n- the opener on a fresh nested path and on a B1-era file;\n- the route's closed-store log line.\n\nThe existing worker test for \"the instance holds an English track\" should pass unchanged in its assertions.\n\n**Docs.** Three docs are updated:\n- `TRANSLATE_WORKER.md`: the start-order step that names `ensure_subtitles_schema` and recovery, the handle and its methods, the opener and the flock tie, and \u00a7 Takeover only where it names removed functions.\n- `engine/server/README.md` \u00a7 \"Translate worker and its store contract\": the same three topics.\n- The module docstrings of the three code files.\n\n### Alternatives considered\n\n- **Handle takes the connection per call.** This would keep `run_job(conn, job, \u2026)` and spare two test call sites. Rejected: the handle would be pairable with any connection, including the heartbeat's, and `generate`/`translate_audio` would keep threading a connection whose only job is to match the claim's.\n- **Raise a `ClaimLost` exception from the store.** Rejected: the worker would then need a second exception mapped onto `JobTakenOver` (and removing `JobTakenOver` is out of scope). The requeue and end-failed calls in `run_job`'s handlers, which ignore a lost claim today, would need new try blocks. `bool` is today's contract and changes no control flow.\n- **Recovery takes the lock fd as an argument.** This is the other acceptable shape. Rejected because the service would still call open and then recover as two steps. Folding open and recovery behind the lock check gives the service one call and leaves no public recovery to misuse.\n- **A lock object or class for the flock.** Rejected as an interface with one implementation: the raw fd plus a non-blocking re-assert is the proof.\n- **Put the resolve in `handlers/video.py` or a new module.** `video.py` is the generic video module and the denylist rule is translate-specific. A new module would be one more file. `internal_translate.py` is already imported by both callers.\n- **A route helper that takes a callable and a closed-store default.** It would centralise the `None` branch too. Rejected because the three sites' closed answers and error handling differ, so the callable form would need three lambdas and a default per site. That is more indirection than the repetition it removes.\n- **Heartbeat on the full opener.** Rejected, as above: a redundant migration transaction per start for no guarantee gained.\n\n### Risks and gotchas\n\n- **flock semantics.** A flock belongs to an open file description, so the re-assert succeeds only on the descriptor the worker locked. A second `os.open` of the same lock file in the same process is refused, which is what the test relies on. On an unlocked descriptor the re-assert acquires the lock rather than failing. That still satisfies \"never recover without the flock\", but the docstring must say so plainly.\n- **The Engine opener now creates a missing parent directory.** For the default path it already exists, because of the random-cache `mkdir` just before. For a custom `--subtitles-db` in a missing directory, start-up now succeeds where it failed before. The open is still after `prepare_trending_override`, so a rejected start still creates nothing.\n- **Route resolve now uses one `db_lock` hold instead of two.** It holds the lock marginally longer and removes a window between lookup and denylist read. Responses do not change.\n- **NaN in instance-track cues.** The instance-track end must keep the NaN-allowing encoding by contract. `parse_webvtt` cannot produce NaN, so this only matters for fidelity with `store_ready_subtitles`. Sharing one encoding helper keeps the two from drifting.\n- **Stale copies outside the active suite.** `delete_me/` and `tests/tmp/` probes import the removed functions and will break if run. They are not in the active suite and are left alone.\n- **Unverified baseline.** The three active test files were not freshly run at baseline. A pre-existing red there would show up during this build and look like a regression.\n\n### Tradeoffs the operator is asked to accept\n\n- **`run_job` loses its connection argument.** The worker tests' `Rig.run` and the fetch-reason test change their `run_job` call. These are the call sites that pass the claim's result, but strictly it is a signature change beyond the removed functions.\n- **The recovery test changes.** `test_subtitles.py`'s recovery test now goes through the lock-taking opener because recovery is private. This follows from the flock requirement, not from the removed-function list.\n- **The handle is not subscriptable.** Tests that read `job[\"started_at\"]` from `claim_translate_job` switch to attributes.\n- **New log line.** The route's closed-store track store gains one info log line (the operator's decision). This is a second small observable change beside the approved instance-track one.\n- **`missing host` folds into `not in whitelist` on the worker side.** The worker reports a missing-host refusal as `not in whitelist`, to keep its texts unchanged. Today's behaviour is the same, but the two causes stay indistinguishable in the worker's error column.",
  "conflicts": "none",
  "impacts": "\n<impacts>\n<impact path=\"engine/server/data/subtitles.py\" element=\"module docstring (line 3)\">\n**What changes.** The docstring says \"B1's route upserts state 'ready' with source 'instance'\", and describes job columns \"added in place by ensure_subtitles_schema\". It must now describe four things:\n- the claim handle (`TranslateJob`) and its six claim-conditional methods;\n- `open_subtitles_db` as the one opener (mkdir, then WAL connect, then migrate);\n- `open_translate_worker_store` as the only way to run recovery, and only under the worker's flock;\n- the instance-track writers: the state route's unconditional `store_ready_subtitles` and the handle's conditional instance-track end.\n\n**Depends on it.** Nothing at runtime.\n\n**Risk.** None functionally. It goes stale if left alone, because \"B1's route\" is the wording the plan retires.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"imports (lines 5-12)\">\n**What changes.**\n- Add `from dataclasses import dataclass` for `TranslateJob`.\n- `fcntl` must NOT be imported at module level. The plan imports it inside `open_translate_worker_store` only, so the Engine's import of this module gains nothing.\n- `json`, `sqlite3`, `time`, `contextmanager`, `Path`, `Any` and `Iterator` stay.\n\n**Depends on it.** These modules import this one:\n- `server.py` (line 106);\n- `internal_translate.py` (line 22);\n- `translate-worker.py` (line 44);\n- the three active test files, including the subprocess scripts in `test_subtitles.py` (UPGRADE_SCRIPT, ENGINE_SCRIPT, WORKER_SCRIPT), which import `data.subtitles` under ENGINE_PY.\n\n**Risk.** Low. A module-level `fcntl` import would still work on Linux, but it breaks the plan's stated guarantee.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"SOURCE_INSTANCE constant (new, beside SOURCE_WHISPER at line 16)\">\n**What changes.** `SOURCE_INSTANCE = \"instance\"` moves here from `internal_translate.py:29`.\n\n**Depends on it.**\n- `internal_translate.py`: re-imports it, so `handlers.internal_translate.SOURCE_INSTANCE` still resolves. `_store_cues` uses it at line 182.\n- The new handle method for the instance-track end uses it to fix the source.\n- `translate-worker.py:47` imports it today. After this change it must not, or it has to import it from its new home.\n- Stale copies import it from `handlers.internal_translate`: `delete_me/test_53_source_instance_fetch_adapter_phase2.py` and the `tests/tmp/probe_53_*` files. They still resolve, because the route keeps the name.\n\n**Risk.** Low. Tests write the literal `\"instance\"` (`test_internal_translate.py:618`, `test_translate_worker.py:1042`, `test_subtitles.py:107`), so the value must stay byte-identical.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"store_ready_subtitles (lines 104-115) and the new private instance-cues encoder\">\n**What changes.** The inline `json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))` at line 114 moves into a new private helper, which the instance-track handle method also uses. The encoding must stay exactly as it is: NaN allowed, so no `allow_nan=False`. It must NOT become `_cues_text`. Signature, upsert SQL and docstring otherwise stay. The docstring's \"a running job's conditional updates then match nothing\" still holds, and now covers the instance-track end as well.\n\n**Depends on it.**\n- `internal_translate._store_cues` (line 182), which is the takeover writer.\n- Tests: `test_internal_translate._seed` (lines 618, 620); `test_translate_worker.py:1042`, the B1 takeover test; `test_subtitles` ENGINE_SCRIPT (line 107); the new parametrised takeover test.\n- `test_internal_translate.py:502` asserts the stored `cues_json` is compact, with no space and no newline.\n\n**Risk.** Medium-low. If the helper picks up `allow_nan=False` or a different separator, the compact assertion at :502 or byte-identity across the two writers breaks. NaN cannot come out of `parse_webvtt`, so a divergence there would go unnoticed by tests.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"_cues_text (lines 118-120)\">\n**What changes.** Nothing. It stays the encoder for running cues and for the whisper ready end (`allow_nan=False`).\n\n**Depends on it.** The handle's running-cues and end-ready methods.\n\n**Risk.** The danger is the instance-track end reusing `_cues_text` by mistake. That would make a NaN raise where `store_ready_subtitles` accepts it, which breaks the plan's encoding contract.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"TranslateJob frozen dataclass and its six methods (new)\">\n**What changes.** A new `@dataclass(frozen=True)` with these fields: the claiming connection, `video_id`, `instance_domain`, `target_language`, `started_at`, `attempts`. Six methods, each a thin `_update_claim` call returning `bool`, with the timestamp passed in by the caller:\n- **running cues:** `cues_json = _cues_text(cues), detected_language = ?`. Today's `store_running_cues`, line 167.\n- **end ready:** `state='ready', cues_json, fetched_at = finished_at`. Today's `finish_translate_ready`, line 177.\n- **end already_english:** `state='already_english', detected_language, finished_at`. Line 182.\n- **end failed:** `state='failed', error, finished_at`. Line 187.\n- **requeue:** `state='queued', attempts = attempts - 1`, `queued_at` untouched. Line 172.\n- **end ready from an instance track (new):** `state='ready', source='instance', track_text, cues_json` (NaN-allowing encoder), `fetched_at = finished_at`. One timestamp, and no other column touched.\n\nThe SET strings must be copied exactly.\n\n**Depends on it.** The worker (`translate_audio`, `generate`, `run_job`, `serve`) and every test that claims a job.\n\n**Risk.**\n- **High.** Today the instance-track pair sets `fetched_at` and `finished_at` from two separate `now_ms()` calls. The new method must take one value and set both.\n- The `attempts - 1` text has to stay.\n- Equality: a frozen dataclass holding a `sqlite3.Connection` compares and hashes the connection field. That is harmless, but `repr` will print the connection object.\n- The class is not subscriptable, so every `job[\"...\"]` reader breaks. See the test entries and `serve` at `translate-worker.py:495`.\n- Method names are a design choice and are not fixed here. The next step should check them against the docs that will name them.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"claim_translate_job (lines 139-147)\">\n**What changes.** Name, signature and the IMMEDIATE transaction stay. The return type goes from `sqlite3.Row | None` to `TranslateJob | None`. The handle is built from the re-read row (line 147) plus the `target_language` argument and `conn`. The docstring must say it returns a handle.\n\n**Depends on it.**\n- `translate-worker.serve` (line 485).\n- `test_subtitles.py`: lines 133-141 (WORKER_SCRIPT, including `tuple(job)` in the error message at 135, which raises TypeError on a dataclass, though only on the failure path), 338-340, 363-372 and 394.\n- `test_internal_translate.py:610` (`_claimed`).\n- `test_translate_worker.py`: 542-544 (`Rig.claim`) and 922.\n\n**Risk.** Medium. Every subscript reader fails at once with TypeError, which at least makes it loud. The transaction itself does not change.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"_update_claim (lines 158-162)\">\n**What changes.** It takes the handle (or its fields) instead of a loose `(conn, video_id, instance_domain, target_language, started_at)`. It keeps the single `UPDATE \u2026 WHERE {_KEY} AND state = 'running' AND started_at = ?` inside `with conn:` and returns `rowcount == 1`. Its docstring must stop saying \"B1's route took the row over\". Instead it names the state route's instance-track store racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer.\n\n**Depends on it.** The six handle methods only.\n\n**Risk.** Medium. Any change to the WHERE clause or its parameter order breaks every conditional write. The new takeover test is the guard: each method must return False and leave the row byte-identical.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"store_running_cues, requeue_translate_job, finish_translate_ready, finish_translate_already_english, finish_translate_failed, mark_translate_finished (lines 165-193): deleted\">\n**What changes.** All six module-level functions are removed.\n\n**Depends on it.** Active code:\n- `translate-worker.py:44`, the import, and the call sites at 372, 378, 387, 408, 442, 446, 452 and 459.\n\nActive tests:\n- `test_subtitles.py`: 119, 137-141 (WORKER_SCRIPT, inside a string, so grep for the import misses it), 388 and 395;\n- `test_internal_translate.py`: 615, 625, 627, 629, 755, 759, 768, 779 and 792.\n\nStale and inactive files: `tests/tmp/probe_45_*`, `probe_50_phase1_rows.py`, `probe_53_*` (13 hits each), `probe_green.py`, `probe_race.py`, `probe_phase2_worker_cli.py`, `delete_me/*.bak*`.\n\n**Risk.** High for the active tests. A missed reference is an ImportError, and in WORKER_SCRIPT it only shows up as a subprocess exit code. The stale probes will break if run; the plan accepts that.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"recover_translate_jobs (lines 150-155), renamed private _recover_translate_jobs\">\n**What changes.** It is renamed to `_recover_translate_jobs`. The logic is unchanged: fail at `attempts >= MAX_CLAIMS` with RECOVERY_ERROR and `finished_at`, then requeue the remaining running rows, in one IMMEDIATE transaction. The docstring's \"only under its flock\" is now enforced by its only caller.\n\n**Depends on it.**\n- `translate-worker.py:44` and `:536`.\n- `test_subtitles.py:347`, `:366` and `:372`, the recovery test, which must now go through `open_translate_worker_store`.\n- The `test_subtitles.py:17` docstring bullet.\n\n**Risk.** Medium. The failed-before-requeued statement order inside the transaction is what makes `(2, 1)` come out right in the test, so it must stay.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"open_subtitles_db(path) (new)\">\n**What changes.** A new public opener:\n1. `path.parent.mkdir(parents=True, exist_ok=True)`;\n2. `connect_subtitles_db(path)`;\n3. `ensure_subtitles_schema(conn)`.\n\nOn any exception from the migration it closes the connection and re-raises.\n\n**Depends on it.**\n- `server.py:371-372`;\n- `translate-worker.command_enqueue` (`:131-135`);\n- `open_translate_worker_store`;\n- new tests on a fresh nested path and on a B1-era file;\n- possibly `test_internal_translate._subtitles_db`, if it is switched to it. That is optional.\n\n**Risk.**\n- Low-medium. It must catch `BaseException`, or at least `Exception`, for the close. A missing close only leaks the connection.\n- The concurrent-upgrade guarantees (WAL retry and the one-IMMEDIATE migration) come from the two composed functions, so `test_subtitles`' 24-round race test is unaffected as long as it keeps calling them directly.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"open_translate_worker_store(path, lock_fd, finished_at) (new)\">\n**What changes.** A new public opener for the worker service:\n1. Import `fcntl` locally.\n2. Call `fcntl.flock(lock_fd, LOCK_EX | LOCK_NB)`. `BlockingIOError` propagates before any mkdir, connect or file creation.\n3. Call `open_subtitles_db(path)`.\n4. Call `_recover_translate_jobs(conn, finished_at)`.\n5. Return `(conn, (requeued, failed))`.\n\n**Gap in the plan:** it says the opener closes the connection when the migration fails, but not when recovery raises. This function should close `conn` if `_recover_translate_jobs` raises. Today `command_run`'s `finally` closes it (lines 541-545); after the change `conn` is never bound in `command_run` if the opener raises.\n\n**Depends on it.**\n- `translate-worker.command_run`;\n- new tests: a second `os.open` description holding the lock makes it raise and leaves the subtitles file absent; with the lock held, recovery runs as today's test expects.\n\n**Risk.** High.\n- **flock semantics:** the re-assert is a no-op only on the same open file description. On an unlocked fd it acquires the lock, and the docstring must say so.\n- **Ordering:** mkdir must come after the flock, or a refused call creates a directory. The new test checks only that the file is absent.\n- **Fd ownership:** it must not close or unlock `lock_fd`; `command_run` still owns it (line 547).\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"connect_subtitles_db, ensure_subtitles_schema (lines 25-77): stay public\">\n**What changes.** Nothing in the code.\n\n**Depends on it.**\n- `translate-worker.heartbeat_loop` (line 465) keeps `connect_subtitles_db`.\n- Tests use both directly: `test_subtitles.py` (82-88, 97-104, 119-126, 192-195, 217-230); `test_internal_translate.py:418-424`; `test_translate_worker.py:87`, `271-272`, `507-508`, `912-913`, `1041` and `1260`.\n- `server.py` and the worker's enqueue stop calling them directly.\n\n**Risk.** None, if they are left as they are.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"fetch_ready_subtitles, fetch_subtitle_state, fetch_translate_heartbeat, enqueue_translate_job, write_translate_heartbeat, _immediate, _KEY, MAX_CLAIMS, RECOVERY_ERROR, JOB_COLUMNS\">\n**What changes.** Nothing.\n\n**Depends on it.** The route, the worker, the tests and `engine/server/README.md:35-36`.\n\n**Risk.** None. Listed so the next step can confirm they stay as they are.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"module docstring (lines 1-8)\">\n**What changes.**\n- Paragraph 2 (\"An unknown or denylisted video answers 404 \u2026 before any remote fetch or store read\") stays true. It should say the resolve goes through `resolve_translatable_video`, shared with the worker.\n- Paragraph 3 (enqueue: \"validates and resolves exactly as the state route does \u2026 a closed store included\") stays true.\n- Mention the new info log line for a closed store on the track store.\n\n**Depends on it.** Nothing at runtime.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"imports (lines 9-26)\">\n**What changes.**\n- Drop `from handlers.video import resolve_video_row` (line 24). Add `from handlers.video import fetch_video_row`, which the shared resolve needs.\n- Add `SOURCE_INSTANCE` to the `data.subtitles` import (line 22).\n- Add `contextmanager` (and `Iterator` for typing) for `_subtitles_store`.\n- `list_active_denied_hosts` and `normalize_host` stay, now used by the shared resolve as well as the body check.\n\n**Depends on it.**\n- `router.py:41` imports `handle_internal_translate` and `handle_internal_translate_enqueue`.\n- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track`, and the new `resolve_translatable_video`.\n- `test_internal_translate.py` loads it via `importlib.import_module(\"handlers.internal_translate\")` (lines 290-294, 391-394).\n- `test_source_fetch.py:25` imports helpers from `test_internal_translate`.\n\n**Risk.**\n- Import cycle: `handlers.video` does not import `internal_translate`, so there is no cycle.\n- The module must stay free of numpy and faster-whisper, because the worker's enqueue path imports it.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"SOURCE_INSTANCE (line 29) and VIDEO_NOT_FOUND comment (line 34)\">\n**What changes.**\n- Line 29's local definition is replaced by the import from `data.subtitles`. The name still resolves as a module attribute.\n- Line 34's comment, \"The body resolve_video_row answers, reused for a denied host\", goes stale: the route no longer calls `resolve_video_row`, and now maps every refusal to this body itself. It must be reworded.\n\n**Depends on it.** `VIDEO_NOT_FOUND` must stay `{\"error\": \"Video not found\"}`. The tests' `VIDEO_NOT_FOUND` constant and the Client's `TRANSLATE_NOT_FOUND_ERROR` pin it.\n\n**Risk.** Low, provided the literal is unchanged.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"resolve_translatable_video(conn, video_id, host, error_threshold) (new)\">\n**What changes.** New. It returns `(row, None)` or `(None, refusal)`:\n- `missing host` for a None or empty host, decided before any query;\n- `not in whitelist` when `fetch_video_row(conn, video_id, host, error_threshold=\u2026)` returns None;\n- `host denied` when `normalize_host(row[\"instance_domain\"]) in list_active_denied_hosts(conn)`.\n\nIt writes no response and takes no lock.\n\n**Depends on it.** `_resolve_translate_key`, and the worker's `resolve_video`.\n\n**Risk.** Medium.\n- **Order.** The order must be: host check, then the row lookup, then the denylist read only when a row exists. The worker test \"any other OperationalError\" (`test_translate_worker.py:1079-1091`, drop-column and zero-byte cases) relies on `fetch_video_row` raising first with its own text.\n- **Empty host.** A truthy check on host matters: `fetch_video_row` with a None host matches any host.\n- **Denylist case.** The denylist row is stored uppercase in the tests. `list_active_denied_hosts` normalises it, so the comparison must stay on normalised values.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_resolve_translate_key (lines 187-215)\">\n**What changes.**\n- Body validation and its three 400s stay byte-identical: `read_json_body`'s message, `Missing id or host`, `Invalid host`.\n- The `resolve_video_row` call (line 203) and the separate denylist hold (lines 210-214) become one `with server.db_lock:` around `resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)`.\n- Any refusal gives 404 `VIDEO_NOT_FOUND`.\n- It returns `(body, row[\"video_id\"], row[\"instance_domain\"], row[\"video_uuid\"] or row[\"video_id\"])`.\n\n**Depends on it.** Both handlers, and these tests:\n- the 404 parity tests at `test_internal_translate.py:462-488` and `936-962`;\n- the REFUSED table (`924-933`), which includes \"known uuid on another host\";\n- the startup test at 1028-1031, which posts an unknown video to the live Engine.\n\n**Risk.** Medium.\n- `resolve_video_row` used to answer 400 `Missing video id` for an empty id. That is unreachable here, because the route already answers `Missing id or host`. Do not reintroduce it.\n- The route must keep passing the normalised host.\n- The lock is held slightly longer. The SimpleNamespace fake's `db_lock` is a plain `threading.Lock`, so it must not be re-entered.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_subtitles_store(server) context manager (new)\">\n**What changes.** New `@contextmanager`. It holds `server.subtitles_db_lock` for the whole body and yields `server.subtitles_db`, which may be None. It must not catch exceptions: each caller keeps its own `sqlite3.Error` handler outside the `with`.\n\n**Depends on it.** `_read_key`, `_store_cues` and the enqueue.\n\n**Risk.** Medium-low.\n- A generator-based context manager that wraps `yield` in try/except, or one that holds the lock only around the attribute read, would break the \"one lock hold\" guarantee of the enqueue (beat read plus insert). That guarantee is pinned by the README at line 23.\n- The SimpleNamespace fake supplies `subtitles_db` and `subtitles_db_lock`, and the plan leaves it untouched.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_read_key (lines 154-164)\">\n**What changes.** It uses `_subtitles_store`. A closed store still returns `(None, False)`. A `sqlite3.Error` is still logged `[translate] cache read failed \u2026` and returns `(None, False)`.\n\n**Depends on it.** `handle_internal_translate`, and the tests at `test_internal_translate.py:699-710`, 688-696 and 728-740.\n\n**Risk.** Low.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"_store_cues (lines 176-184)\">\n**What changes.** It uses `_subtitles_store`. A new INFO log line is written when the store is closed (operator decision); the wording is for the next step to choose. `sqlite3.Error` is still logged `[translate] cache write failed \u2026`. `store_ready_subtitles` stays the unconditional writer, with `SOURCE_INSTANCE` now imported.\n\n**Depends on it.**\n- `handle_internal_translate`, at line 245.\n- A new route test: closed store plus an instance track gives the log line, and the answer stays `ready`.\n- The `_failed_fetches` helper (`test_internal_translate.py:528-529`) filters on the `[translate] instance fetch failed` prefix. The new line must not start with that prefix, or the NONE_CASES exact-list assertions could pick it up.\n\n**Risk.** Low-medium. This is a new observable log line, and the NONE_CASES/budget tests compare exact lists of failed-fetch lines.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate_enqueue (lines 253-273)\">\n**What changes.** The beat check and `enqueue_translate_job` stay inside one `with _subtitles_store(server) as conn:`. A closed store still gives `{\"state\":\"none\",\"available\":false}`, and a `sqlite3.Error` still gives 503 `Translate store unavailable` with the `[translate] enqueue failed` log.\n\n**Depends on it.** Tests at `test_internal_translate.py:830-920`.\n\n**Risk.** Low-medium. The availability check must stay inside the same hold.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"handle_internal_translate, _generation_available, fetch_instance_track, parse_webvtt, pick_english_track_path, TARGET_LANGUAGE, HEARTBEAT_FRESH_MS\">\n**What changes.** Nothing beyond the call into `_resolve_translate_key`. The docstring of `_generation_available` (\"The caller holds subtitles_db_lock\") stays true.\n\n**Depends on it.** The worker imports `TARGET_LANGUAGE` and `fetch_instance_track`.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"resolve_video_row (lines 260-282) and fetch_video_row (lines 24-78)\">\n**What changes.** Nothing. `resolve_video_row` loses its translate caller but keeps its `/api/video` caller at line 447. `fetch_video_row` gains a caller: the new shared resolve.\n\n**Depends on it.** `/api/video`, `/api/video/refresh` and `test_video.py`.\n\n**Risk.** None, if nothing in it changes. Do not delete `resolve_video_row`.\n</impact>\n<impact path=\"engine/server/api/router.py\" element=\"import of handle_internal_translate/handle_internal_translate_enqueue (line 41) and POST_ROUTES (141-142)\">\n**What changes.** Nothing. The handler names are unchanged.\n\n**Depends on it.** Engine routing. `test_router.py` and the startup test in `test_internal_translate.py`.\n\n**Risk.** None. Listed so the next step can confirm the handler names are unchanged.\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 8 (internal_translate summary)\">\n**What changes.** Optional. It could mention that the module also holds the translatable-video resolve shared with the worker. Nothing it says now is false.\n\n**Depends on it.** Nothing.\n\n**Risk.** None. I am unsure whether the doc pass will want this line touched.\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"import (line 106) and the subtitles open (lines 369-372)\">\n**What changes.**\n- Line 106 changes to `from data.subtitles import open_subtitles_db`.\n- Lines 371-372 become `subtitles_db = open_subtitles_db(subtitles_db_path)`, in the same place: after `prepare_trending_override` (351) and after the random-cache mkdir (369).\n- The comment at 370 (\"After the mkdir above (the default lives in the same directory)\") goes partly stale, because the opener now creates its own parent. It should be reworded to keep only the \"after prepare_trending_override, so a rejected start creates nothing\" point.\n- `server.subtitles_db = subtitles_db` (504) and the shutdown close (575-579) are unchanged.\n\n**Depends on it.**\n- `test_internal_translate.py:998-1039`: the Engine start creates a missing `subtitles.db` at an overridden path.\n- Every test group listing `server.py` in `tests/config.json`: `test_similar`, `test_server_config`, `test_internal_events`, `test_random_cache` and `test_internal_translate`. Each starts the Engine, so all of them exercise this line.\n\n**Risk.** Low-medium. Behaviour change: a custom path in a missing directory now starts instead of failing. The plan accepts this, and the README Notes should say so.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"module docstring (lines 2-9)\">\n**What changes.**\n- Line 8 (\"run is the service, in this order: ffmpeg check, flock \u2026, schema and crash recovery \u2026\") should name the lock-checked store opener: the flock is re-asserted, then open, migrate and recover.\n- Line 6 (`run_job` \"takes one claimed job \u2026\") should say it now takes the claim handle.\n- Line 4 (enqueue \"resolves \u2026 the way B1's /internal/translate does\") should name the shared `resolve_translatable_video`.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"imports (lines 41-48)\">\n**What changes.**\n- Line 44 becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat`. The six removed functions, `ensure_subtitles_schema`, `recover_translate_jobs` and `store_ready_subtitles` drop out. `connect_subtitles_db` is still needed by `heartbeat_loop`.\n- Line 47 drops `SOURCE_INSTANCE` and adds `resolve_translatable_video`.\n- Line 48, `from handlers.video import fetch_video_row`, becomes unused once `resolve_video` delegates. Remove it.\n- Line 43: `list_active_denied_hosts` becomes unused. `normalize_host` stays for `command_enqueue`.\n- Update the comment at 35, which says \"api/ is for server_config, handlers.video.fetch_video_row and the route's fetch_instance_track and constants\".\n- `fcntl` (14) and `sqlite3` (22) are still used.\n\n**Depends on it.**\n- `_worker()` in `test_translate_worker.py:254-259` and STALL_DRIVER (212-220) both exec the module, so an ImportError fails every worker test.\n\n**Risk.** Medium, since one bad import fails the whole module. Lint-level only otherwise.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"JobTakenOver docstring (lines 87-88)\">\n**What changes.** Replace \"B1's route replaced the running row\" with the real writer: the Engine state route's instance-track store (`store_ready_subtitles`), racing an enqueue and a claim during its up-to-15 s fetch, with an older blue/green Engine as a possible further writer. The class itself stays; removing it is out of scope.\n\n**Depends on it.** `translate_audio`, `generate` (new raise) and `run_job`.\n\n**Risk.** None.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"resolve_video (lines 95-112)\">\n**What changes.**\n- The signature `(whitelist_path, video_id, host, max_duration)` stays, because tests monkeypatch it with a 4-argument stand-in at `test_translate_worker.py:661` and at 1102-1103 and 1129-1130.\n- Kept: the `connect_readonly_db` connection, `PRAGMA busy_timeout = 30000` and the close in `finally`.\n- The body calls `resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)`. The refusal `missing host` maps to `not in whitelist`; the others pass through. The duration bound stays after the row check, with its text `duration {d}s over {m}s`.\n\n**Depends on it.** `command_enqueue`, `generate` and these tests:\n- the enqueue refusals table (`test_translate_worker.py:136-138`);\n- the claim refusals (348-349);\n- the stall test's expected `failed`/`not in whitelist` (1283);\n- the whitelist-at-claim tests (1063-1091), which need `OperationalError` texts to come out unchanged so the WhitelistBusy classification in `generate` still applies.\n\n**Risk.** Medium.\n- `connect_readonly_db` raising on a deleted file (`unable to open`) must still happen before `resolve_translatable_video`, as today.\n- The duration check must stay on the returned row dict.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_enqueue (lines 115-150)\">\n**What changes.** Lines 131-135 (mkdir, connect, ensure) become `conn = open_subtitles_db(args.subtitles_db)` inside the existing `try \u2026 except sqlite3.Error`, with `enqueue_translate_job` and the close in `finally`. Output lines and exit codes are unchanged.\n\n**Depends on it.** The enqueue CLI tests (`test_translate_worker.py:763+`), which run the script as a subprocess, and `DEPLOYMENT.md:281-291`.\n\n**Risk.** Low. An `OSError` from mkdir is not a `sqlite3.Error`, so it still propagates uncaught. Today it is raised outside the try, so the behaviour is the same. The structure needs care so that `conn` is defined before the `finally` close.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"translate_audio (lines 346-389)\">\n**What changes.** The `conn` and `claim` parameters are replaced by the handle, e.g. `translate_audio(job, pipe, runner, max_chunk, stop, progress)`. The three conditional writes become handle methods:\n- 372: already_english, with `language, now_ms()`;\n- 378: running cues, with `cues, language`;\n- 387: end ready, with `cues, now_ms()`.\n\nEach still raises `JobTakenOver` on False. Control flow is unchanged.\n\n**Depends on it.** `generate`, and the pipeline tests: 947-963 (running cues per chunk, observed through the `cues_writes` trigger at 509-512), 966-976, 979-1001 and 1033-1050 (B1 takeover mid-job).\n\n**Risk.** Medium. The order \"already_english written before any cue\" and \"running cues only when `new` is non-empty\" must stay exactly as it is.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"generate (lines 392-432)\">\n**What changes.**\n- The signature drops `conn`; `claim` becomes the handle.\n- Line 395 becomes `resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)`.\n- Lines 407-408 (the unconditional upsert, then the `mark_translate_finished` stamp) become a single handle call to the instance-track end with `fetched[0], fetched[1], now_ms()`. If it returns False, raise `JobTakenOver`. If True, return `\"ready from the instance track\"`.\n- Line 430 passes the handle to `translate_audio`.\n- The docstring (\"AC3 for one claim (video_id, instance_domain, target_language, started_at)\") must name the handle.\n- The `OperationalError` to `WhitelistBusy` mapping is unchanged.\n\n**Depends on it.**\n- `test_translate_worker.py:1016-1030`: the instance holds an English track, which must end ready/instance with `cues_json == CUES`, `track_text == TRACK` and `finished_at` within the window. It should pass unchanged.\n- `run_job`'s takeover log line.\n\n**Risk.** High. This is the one approved behaviour change: after a takeover, the worker no longer overwrites the Engine's row. No existing test covers the lost-claim instance path. The plan's new store test covers the method; nothing yet drives `generate` on a taken-over row. The UPDATE must also leave `detected_language`, `error`, `attempts`, `queued_at` and `started_at` untouched.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"run_job (lines 435-460)\">\n**What changes.**\n- The signature drops `conn`: `run_job(job, args, runner, stop, progress) -> bool`. Line 437's tuple build is deleted.\n- Log lines use `job.video_id, job.instance_domain` in place of `*claim[:2]`, with the texts unchanged.\n- `requeue_translate_job(conn, *claim)` (442, 446) becomes `job.requeue()`.\n- `finish_translate_failed(...)` (452, 459) becomes the handle's end-failed method. Return values are still ignored.\n- The docstring's \"a row B1's route took over is left as B1 wrote it\" must name the real writer.\n\n**Depends on it.**\n- `serve` (line 496).\n- `Rig.run` (`test_translate_worker.py:554`) and the fetch-reason test (925), which call it with `conn` first.\n- `_run_broken` (640-649) and the whitelist tests that read its bool.\n\n**Risk.** Medium. A signature mismatch fails every pipeline test. The bool contract (True only for WhitelistBusy) must survive.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"serve (lines 479-502): not named by the plan\">\n**What changes.**\n- Line 495's log uses `job[\"video_id\"], job[\"instance_domain\"], job[\"attempts\"]` and must switch to attributes. That breaks at runtime with the handle, and the plan does not list it.\n- Line 496 becomes `run_job(job, args, runner, stop, progress)`.\n- The signature `serve(conn, args, runner, stop, progress)` stays, because it still claims on `conn`. The tests call it as `rig.worker.serve(rig.conn, \u2026)` at `test_translate_worker.py:1111` and 1136.\n\n**Depends on it.**\n- `command_run`;\n- the back-off tests at 1097-1163;\n- the subprocess stall and heartbeat tests, which claim through serve.\n\n**Risk.** High if missed. Every claimed job would raise TypeError at the log line. Inside serve that exception is not caught, so the worker process would die.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"heartbeat_loop (lines 463-476)\">\n**What changes.** Nothing. It keeps `connect_subtitles_db`, per the plan.\n\n**Depends on it.** The heartbeat and stall subprocess tests (1200-1294).\n\n**Risk.** None. The beat thread starts only after the main thread's opener has migrated the file, so the table exists.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"command_run (lines 511-549)\">\n**What changes.**\n- Its own LOCK_NB acquire, the `another worker holds` log line and exit 6 (517-525) stay first.\n- Lines 531-537 (mkdir, connect, ensure, recover) become `conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())`, followed by the same `started pid=\u2026 recovered requeued=\u2026 failed=\u2026` log line.\n- The try/finally must still close `conn` and join the beat. `conn` is now bound only once the opener returns, so the `finally` that closes it must start after that point. See the gap in the `open_translate_worker_store` entry.\n- The docstring (\"then schema, recovery, \u2026\") should name the opener.\n\n**Depends on it.**\n- The held-lock test (1169-1197): exits 6, writes nothing, leaves a B1 file byte-identical, no sidecars. It is protected because `command_run`'s own flock fails first.\n- The heartbeat and stall tests.\n- The `TRANSLATE_WORKER.md` start-order step 5 and `DEPLOYMENT.md:271`.\n\n**Risk.** Medium-high. Wrong try/finally placement either leaks the connection or raises NameError in `finally`. `lock_fd` must remain owned and closed by `command_run` (line 547).\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"exception classes JobFailed/JobStopped/WhitelistBusy, AudioPipe, WhisperRunner, chunk helpers, exit codes, parse_args\">\n**What changes.** Nothing.\n\n**Depends on it.** Existing tests.\n\n**Risk.** None. Listed so the next step can confirm exit codes 0-6 and the CLI flags are untouched.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"module docstring (lines 1-24)\">\n**What changes.**\n- Line 12 (concurrent writers) names `claim_translate_job` \"which must hand back that key\", `store_running_cues` and `finish_translate_ready`. These become handle methods.\n- Line 14 names `connect_subtitles_db` + `ensure_subtitles_schema`.\n- Line 17 names `recover_translate_jobs`, which now runs through the lock-taking opener.\n- New bullets are needed for the handle-method takeover test, the instance-track end, both openers and the flock tie.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"WORKER_SCRIPT subprocess string (lines 115-147)\">\n**What changes.**\n- The import at 119 drops `finish_translate_ready` and `store_running_cues`.\n- 133-141 use `job.video_id` and `job.instance_domain`, then call the running-cues and end-ready methods on `job`.\n- Line 135's `tuple(job)` in the SystemExit message must change, because a dataclass is not iterable.\n\n**Depends on it.** `test_an_engine_and_a_worker_writing_one_file_at_once\u2026` (282-323) under ENGINE_PY.\n\n**Risk.** Medium. This code lives in a string, so a mistake shows up only as a non-zero subprocess exit, and grep for imports does not find it.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"claim test (lines 326-343)\">\n**What changes.** Line 340 reads `job[\"video_id\"]` and the other fields by subscript. It switches to attributes.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"recovery test (lines 346-378)\">\n**What changes.** `recover_translate_jobs` is private now, so each of the two recover calls (366, 372) goes through `open_translate_worker_store(path, lock_fd, 9000/9500)`, with the test holding a flock on a tmp lock file. Each call returns a new connection, which must be closed. `first[\"video_id\"]` (364) and `row[\"video_id\"]` (370) switch to attributes.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Medium.\n- Assertions must stay `(1, 0)` and `(2, 1)` with the bystander snapshot.\n- The test's own `conn` stays open alongside the opener's connection. That is fine in WAL.\n- The opener's migration runs again each time; it is idempotent.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"fetch_subtitle_state test (lines 387-400)\">\n**What changes.** Line 388 drops `store_running_cues` from the import. Line 394 keeps the handle instead of `[\"started_at\"]`. Line 395 calls the handle's running-cues method.\n\n**Depends on it.** Nothing.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_subtitles.py\" element=\"new tests (plan)\">\n**What changes.** New tests:\n- **Handle takeover (parametrised over the six methods):** after a `store_ready_subtitles` takeover, each returns False and the row is byte-identical. The `_snapshot` helper (205-213) suits this.\n- **Instance-track end while the claim holds:** state ready, source instance, `track_text`, compact `cues_json`, `fetched_at == finished_at`, other job columns unchanged.\n- **`open_subtitles_db`:** on a fresh nested path (parent created) and on a B1-era file (reuse `_b1_file`).\n- **`open_translate_worker_store`:** a second open file description holding the lock makes it raise `BlockingIOError` and leaves the file absent. With the lock held, recovery runs.\n\n**Depends on it.** `tests/config.json` group `test_subtitles.py`, which lists only `subtitles.py`.\n\n**Risk.** Low. For the flock test, the second `os.open` must be a separate open file description: a separate `os.open` in the same process, not `os.dup`.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"module docstring and _subtitles_db helper (lines 19, 418-424)\">\n**What changes.** Line 19 says the store is \"opened with `connect_subtitles_db` and `ensure_subtitles_schema`, as server.py does\", and `_subtitles_db`'s docstring says \"as server.py opens it at startup\". Both go stale. Either switch the helper to `open_subtitles_db`, or reword both. This is optional; the plan does not list it.\n\n**Depends on it.** Every route test, and `test_source_fetch.py:25`, which imports helpers from this module but not `_subtitles_db`.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"_claimed and _seed (lines 605-631)\">\n**What changes.**\n- `_claimed` returns the handle instead of `[\"started_at\"]`.\n- `_seed` drops `finish_translate_already_english`, `finish_translate_failed` and `store_running_cues` from its import (615), and calls the handle methods at 625, 627 and 629.\n- `store_ready_subtitles` and `enqueue_translate_job` stay.\n\n**Depends on it.**\n- BRANCHES tests (713-740), REFUSED_ROWS (797-815) and the \"stored key answers its state\" enqueue test (872-883).\n- `delete_me` and `tests/tmp` probes import `_seed` (e.g. `probe_50_phase1_rows.py`). They are stale.\n\n**Risk.** Medium. Every stored-state test runs through `_seed`.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"running-key tests (lines 753-794)\">\n**What changes.**\n- Lines 755 and 779 drop the removed imports.\n- `started_at = _claimed(store)` becomes a handle.\n- 759 becomes `job.<running cues>(RUNNING, \"fr\")`.\n- 768 and 792 become `job.<end failed>(\"boom\", NOW)`.\n\n**Depends on it.** Nothing else.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"new closed-store track-store log test (plan)\">\n**What changes.** A new test: a server with `subtitles_db = None` and an instance holding an English track answers `ready` and logs the new info line once.\n\n**Depends on it.** The `_store_cues` wording.\n\n**Risk.** Low. Existing closed-store tests (699-710, 844-856) use no-track instances and stay green.\n</impact>\n<impact path=\"tests/active/test_source_fetch.py\" element=\"import from test_internal_translate (line 25)\">\n**What changes.** Nothing, as long as `test_internal_translate`'s module-level names CHUNK, HOST, OVER_CAP, REFUSED_TARGETS, TRACK_PATH, TRACK_URL, WITHIN_CAP, Clock, Response, ScriptedInstance and `_body` keep importing.\n\n**Depends on it.** All of `test_source_fetch`.\n\n**Risk.** Low. A module-level import error in `test_internal_translate` would break this file too.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"module docstring (lines 1-50)\">\n**What changes.**\n- Line 10 gives the signature `run_job(conn, job, args, runner, stop, progress)`, which becomes `run_job(job, \u2026)`.\n- Line 35 names `Rig.run`.\n- Optionally add the lost-claim instance-track behaviour.\n\n**Depends on it.** Nothing.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"Rig.claim and Rig.run (lines 538-554)\">\n**What changes.**\n- 544 reads `self.job[\"video_id\"]` and the other fields by subscript, and switches to attributes.\n- 554 becomes `self.worker.run_job(self.job, args, runner, \u2026)`.\n\n**Depends on it.** Every pipeline, bounds and whitelist-at-claim test through `rig.run`/`rig.claim`.\n\n**Risk.** Medium. A miss fails most of the file.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"fetch-reason test (lines 905-935)\">\n**What changes.** Line 925 becomes `worker.run_job(job, args, UnreachedRunner(), \u2026)`. The connection opened at 912-913 is still needed to claim and to close.\n\n**Depends on it.** Nothing.\n\n**Risk.** Low.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"instance-track and takeover tests (lines 1016-1050)\">\n**What changes.** These should pass unchanged in their assertions.\n- 1016: ready/instance, CUES, TRACK, `finished_at` within the window.\n- 1033: the B1 takeover mid-job leaves the row untouched. This exercises the running-cues method returning False.\n\n**Depends on it.** `generate`'s new single call, and the handle.\n\n**Risk.** Medium. These are the guards that `fetched_at`/`finished_at` and the encoding still match. No test drives `generate` through a takeover that lands before the instance-track end. If the next step wants that path pinned, it is a candidate.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"serve back-off tests, service subprocess tests, enqueue CLI tests (lines 763-905, 1097-1294)\">\n**What changes.** Nothing in the tests:\n- `serve` keeps `(conn, \u2026)`;\n- the subprocess tests run the real `command_run` and `command_enqueue`;\n- `resolve_video` keeps its 4-argument signature for `_recording`.\n\n**Depends on it.** `serve`'s attribute access, `command_run`'s opener call and `command_enqueue`'s opener.\n\n**Risk.** Medium. These are the regression net for `command_run`. The held-lock test proves nothing is created when the lock is refused. The heartbeat test proves the opener plus recovery leave a working store.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups for subtitles.py, internal_translate.py, translate-worker.py, server.py\">\n**What changes.** Nothing.\n- `test_subtitles.py` maps only `subtitles.py`.\n- `test_internal_translate.py` and `test_translate_worker.py` map all three code files.\n- `server.py` is also mapped by `test_similar.py`, `test_server_config.py`, `test_internal_events.py` and `test_random_cache.py`, so the `server.py` edit pulls those Engine-start suites into the run.\n\n**Depends on it.** The test runner's group selection.\n\n**Risk.** Low. Worth knowing that the build's targeted runs will include those suites.\n</impact>\n<impact path=\"tests/tmp/probe_53_draft_translate_worker.py\" element=\"stale probes in tests/tmp (probe_45_*, probe_50_phase1_rows.py, probe_53_* (6 files), probe_green.py, probe_phase2_worker_cli.py, probe_race.py, probe_53_c1_answers.py)\">\n**What changes.** Nothing. The plan leaves them alone. They import or call removed functions (`claim_translate_job` subscripts, `finish_translate_*`, `store_running_cues`, `recover_translate_jobs`, `run_job(conn, \u2026)`) and will break if run.\n\n**Depends on it.** Nothing in the active suite.\n\n**Risk.** None for the active suite.\n</impact>\n<impact path=\"delete_me/test_53_source_instance_fetch_adapter_phase2.py\" element=\"stale delete_me copies (test_53_* and *.bak-harvest53-58-* of internal_translate.py, translate-worker.py, video.py)\">\n**What changes.** Nothing. They name removed functions and `SOURCE_INSTANCE` in the route.\n\n**Depends on it.** Nothing.\n\n**Risk.** None. They are out of the active suite.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"\u00a7 Run: Start-up Order step 5 (line 72), \u00a7 Job Pipeline step 2 (line 90), \u00a7 Stop, Crash and Recovery 'Crash' (line 147), \u00a7 Takeover (line 151), \u00a7 Enqueue (line 49), intro (line 13)\">\n**What changes.**\n- Line 72: \"Open `subtitles.db`, run `ensure_subtitles_schema`, then crash recovery\" becomes: the lock-checked store opener re-asserts the flock, then creates the directory, opens, migrates and recovers, and the counts are logged.\n- Line 90: \"If there is one, store it `ready` with source `instance` and the job is done\" must add \"while the claim holds; otherwise the job is taken over and nothing is written\".\n- Line 147: \"under the lock\" can name the enforcement, since recovery is reachable only through the lock-checked opener.\n- Line 151: \"once B1 has written\" can be reworded, and the instance-track end should be included among the conditional writes. The plan says to update this section only where it names removed functions. It names none, so this is optional.\n- Line 49: \"resolved as B1 does\" can name `resolve_translatable_video`.\n- New text on the claim handle and its methods.\n\n**Depends on it.** `engine/server/README.md:30` and `DEPLOYMENT.md:230` link here.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"\u00a7 Translate worker and its store contract (lines 29-36)\">\n**What changes.**\n- Line 32 (\"The store functions in `data/subtitles.py` are the contract\") gains: `open_subtitles_db` as the single opener; `claim_translate_job` returning a `TranslateJob` handle whose six methods each match only while the row is `running` with the claim's `started_at` and return False once taken over; `open_translate_worker_store` as the only recovery path, under the flock.\n- Line 34 (\"or `instance` when the instance gained an English track before the claim\") stays true, and could add \"while the claim holds\".\n\n**Depends on it.** `TRANSLATE_WORKER.md:13` refers to this README for the store functions.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate 'Checks before any fetch' bullet (line 17): not in the plan's doc list\">\n**What changes.** It says \"the video resolves as on `/api/video` (`resolve_video_row`, so the error-count threshold applies)\". The route no longer calls `resolve_video_row`, so the text must name `resolve_translatable_video`. That function still uses `fetch_video_row` with `video_error_threshold`, so the threshold claim stays true. The plan's docs list names only the store-contract section, so this would be missed.\n\n**Depends on it.** Readers of the Engine API docs.\n\n**Risk.** Documentation only, but the text would be factually stale.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate Cache bullet (line 19) and Notes start-up bullet (line 45)\">\n**What changes.**\n- Line 19 ends \"a store error is logged and the answer stays `ready`\". A closed store now also logs an info line, and this could say so.\n- Line 45 (\"at start opens `DEFAULT_SUBTITLES_DB_PATH` \u2026, creating the file when missing\") should say the parent directory is created too.\n\n**Depends on it.** Readers of the Engine docs.\n\n**Risk.** Documentation only.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"Instance caption track (line 19) and Claim (line 22) glossary entries\">\n**What changes.** Probably none.\n- Line 22 already says the worker \"drops the job without writing anything further\" on a takeover, which is now true for the instance-track end too.\n- Line 19 (\"The translate worker also stores one, with source `instance`, when it finds the track on claiming a job\") could add \"while its claim holds\". This is optional; the plan says no change unless the handle wording requires it.\n\n**Depends on it.** Glossary readers.\n\n**Risk.** None.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"subtitles.db paragraph (line 98) and run flag table (line 271)\">\n**What changes.** Probably none.\n- Line 271 (\"exits 6 without opening `subtitles.db`\") stays true.\n- Line 98 names `[translate] cache write failed` for a locked write. The closed-store info line occurs only during shutdown, so it is optional here.\n\n**Depends on it.** Operators.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/54-translate-job-handle.md\" element=\"Status line and archive move\">\n**What changes.** At delivery, per `docs/project/triage-labels.md`, the status becomes `complete` and the file moves to `docs/project/issues/archive/`. Issue 57 is already `wontfix` and folded in, so it needs no change. Issue 56 (`56-split-translate-worker.md`) depends on 54's handle and may want a note.\n\n**Depends on it.** The issue tracker.\n\n**Risk.** None. This is a tracker step, probably outside this build step.\n</impact>\n</impacts>\n",
  "docs_checklist": "- [ ] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - - **Start-up Order step 5 (line 72):** replace `ensure_subtitles_schema` plus recovery with the lock-checked store opener: flock re-assert, mkdir, open, migrate, recover, then log the counts.\n- **Job Pipeline step 2 (line 90):** the instance track is stored ready/instance only while the claim holds; otherwise the job is taken over and nothing is written.\n- **New text:** the claim handle (`TranslateJob`), its six methods, each returning False after a takeover.\n- **Enqueue (line 49):** optionally name the shared `resolve_translatable_video`.\n- **Crash bullet (line 147):** recovery is reachable only through the lock-checked opener.\n- **\u00a7 Takeover (line 151):** touch only if wording requires; it names no removed function.\n- [ ] `engine/server/README.md` - - **\u00a7 \"Translate worker and its store contract\" (lines 29-36):**\n  - `open_subtitles_db` as the single opener;\n  - `claim_translate_job` returning the `TranslateJob` handle with its claim-conditional methods;\n  - `open_translate_worker_store`, with recovery only under the flock.\n- **Line 17:** replace `resolve_video_row` with `resolve_translatable_video`. The threshold and denylist still apply.\n- **Line 19:** mention the closed-store info log line.\n- **Notes, line 45:** the Engine start now also creates the parent directory of `DEFAULT_SUBTITLES_DB_PATH`.\n- [ ] `engine/server/data/subtitles.py` - Module docstring and docstrings to update:\n- `claim_translate_job` (returns a handle);\n- `_update_claim` and the handle (name the real takeover writer, not \"B1's route\");\n- `store_ready_subtitles` (shared encoder);\n- the two new openers (flock re-assert semantics, including that it acquires the lock on an unlocked fd);\n- `_recover_translate_jobs`.\n- [ ] `engine/server/api/handlers/internal_translate.py` - - **Module docstring:** the shared resolve, and the closed-store log line.\n- **`VIDEO_NOT_FOUND` comment (line 34):** it no longer comes from `resolve_video_row`.\n- **Docstrings:** `_resolve_translate_key`, `_store_cues`, the new `_subtitles_store` and `resolve_translatable_video`.\n- [ ] `engine/server/db/jobs/translate-worker.py` - - **Module docstring (lines 4, 6, 8):** the shared resolve, the handle, and the lock-checked opener in the start order.\n- **`JobTakenOver` docstring:** the real writer.\n- **`run_job`, `generate` and `command_run` docstrings:** update to match.\n- **Comment at line 35:** about what `api/` is on the path for.\n- [ ] `engine/server/api/server.py` - The comment at line 370 (\"After the mkdir above (the default lives in the same directory)\u2026\") goes partly stale, because the opener creates its own parent. Keep the `prepare_trending_override` ordering reason.\n- [ ] `CONTEXT.md` - Optional: in \"Instance caption track\" (line 19), the worker stores the track only while its claim holds. \"Claim\" (line 22) already matches.\n- [ ] `tests/active/test_subtitles.py` - Module docstring lines 12, 14 and 17 name removed or renamed functions. Add bullets for the new handle, opener and flock tests.\n- [ ] `tests/active/test_translate_worker.py` - The docstring's `run_job(conn, job, \u2026)` signature (line 10) becomes `run_job(job, \u2026)`.\n- [ ] `tests/active/test_internal_translate.py` - Docstring line 19 and the `_subtitles_db` helper docstring say the store is opened \"as server.py does\" with `connect`+`ensure`. Reword, or switch the helper to `open_subtitles_db`.",
  "docs": [
    {
      "path": "engine/server/db/jobs/docs/TRANSLATE_WORKER.md",
      "note": "- **Start-up Order step 5 (line 72):** replace `ensure_subtitles_schema` plus recovery with the lock-checked store opener: flock re-assert, mkdir, open, migrate, recover, then log the counts.\n- **Job Pipeline step 2 (line 90):** the instance track is stored ready/instance only while the claim holds; otherwise the job is taken over and nothing is written.\n- **New text:** the claim handle (`TranslateJob`), its six methods, each returning False after a takeover.\n- **Enqueue (line 49):** optionally name the shared `resolve_translatable_video`.\n- **Crash bullet (line 147):** recovery is reachable only through the lock-checked opener.\n- **\u00a7 Takeover (line 151):** touch only if wording requires; it names no removed function."
    },
    {
      "path": "engine/server/README.md",
      "note": "- **\u00a7 \"Translate worker and its store contract\" (lines 29-36):**\n  - `open_subtitles_db` as the single opener;\n  - `claim_translate_job` returning the `TranslateJob` handle with its claim-conditional methods;\n  - `open_translate_worker_store`, with recovery only under the flock.\n- **Line 17:** replace `resolve_video_row` with `resolve_translatable_video`. The threshold and denylist still apply.\n- **Line 19:** mention the closed-store info log line.\n- **Notes, line 45:** the Engine start now also creates the parent directory of `DEFAULT_SUBTITLES_DB_PATH`."
    },
    {
      "path": "engine/server/data/subtitles.py",
      "note": "Module docstring and docstrings to update:\n- `claim_translate_job` (returns a handle);\n- `_update_claim` and the handle (name the real takeover writer, not \"B1's route\");\n- `store_ready_subtitles` (shared encoder);\n- the two new openers (flock re-assert semantics, including that it acquires the lock on an unlocked fd);\n- `_recover_translate_jobs`."
    },
    {
      "path": "engine/server/api/handlers/internal_translate.py",
      "note": "- **Module docstring:** the shared resolve, and the closed-store log line.\n- **`VIDEO_NOT_FOUND` comment (line 34):** it no longer comes from `resolve_video_row`.\n- **Docstrings:** `_resolve_translate_key`, `_store_cues`, the new `_subtitles_store` and `resolve_translatable_video`."
    },
    {
      "path": "engine/server/db/jobs/translate-worker.py",
      "note": "- **Module docstring (lines 4, 6, 8):** the shared resolve, the handle, and the lock-checked opener in the start order.\n- **`JobTakenOver` docstring:** the real writer.\n- **`run_job`, `generate` and `command_run` docstrings:** update to match.\n- **Comment at line 35:** about what `api/` is on the path for."
    },
    {
      "path": "engine/server/api/server.py",
      "note": "The comment at line 370 (\"After the mkdir above (the default lives in the same directory)\u2026\") goes partly stale, because the opener creates its own parent. Keep the `prepare_trending_override` ordering reason."
    },
    {
      "path": "CONTEXT.md",
      "note": "Optional: in \"Instance caption track\" (line 19), the worker stores the track only while its claim holds. \"Claim\" (line 22) already matches."
    },
    {
      "path": "tests/active/test_subtitles.py",
      "note": "Module docstring lines 12, 14 and 17 name removed or renamed functions. Add bullets for the new handle, opener and flock tests."
    },
    {
      "path": "tests/active/test_translate_worker.py",
      "note": "The docstring's `run_job(conn, job, \u2026)` signature (line 10) becomes `run_job(job, \u2026)`."
    },
    {
      "path": "tests/active/test_internal_translate.py",
      "note": "Docstring line 19 and the `_subtitles_db` helper docstring say the store is opened \"as server.py does\" with `connect`+`ensure`. Reword, or switch the helper to `open_subtitles_db`."
    }
  ],
  "reassessments": 1,
  "draft": "## Draft implementation: translate job handle (issue 54, folds in 57)\n\nI read all three code files, `server.py:340-379`, `handlers/video.py` (`fetch_video_row` and `resolve_video_row`) and the test call sites the impacts name. Each item below gives the code as it should land, in the style of the file it goes into: one-line docstrings, one statement per line, no softwrap.\n\n### What the build has to test (worked out first)\n\n1. **Six handle methods after a takeover.** Each returns `False` and leaves the row byte-identical, checked with `_snapshot`.\n2. **Instance-track end while the claim holds.** The row becomes ready/instance with track text and compact cues, `fetched_at == finished_at`, and the other job columns are unchanged.\n3. **Instance-track end after a lost claim, driven through `generate`.** The worker leaves the Engine's row as it is and logs the takeover line. This is the one approved behaviour change, and no existing test reaches it, so it gets a new worker test.\n4. **`open_subtitles_db`.** On a fresh nested path it creates the directory and the full schema in WAL mode. On a B1-era file it adds the job columns.\n5. **`open_translate_worker_store`.** When a second open file description holds the flock, it raises `BlockingIOError` and the subtitles file is absent. With the lock held, recovery returns `(1, 0)` and then `(2, 1)` as today.\n6. **Route.** A closed store with an instance track answers `ready` and writes the new info line once. The other closed-store answers are unchanged.\n7. **Resolve.** `missing host`, `not in whitelist` and `host denied` (uppercase stored deny) are refused. Route 400/404 and worker texts are unchanged (existing tables).\n8. **Regression net.** The three active files stay green, plus the Engine-start groups pulled in by `server.py`.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/data/subtitles.py` | Adds `SOURCE_INSTANCE`, `_instance_cues_text`, `TranslateJob` (6 methods), `open_subtitles_db` and `open_translate_worker_store`. `claim_translate_job` returns the handle. `recover_translate_jobs` becomes `_recover_translate_jobs`. `_update_claim` takes the handle. The 5 per-claim functions and `mark_translate_finished` are deleted. |\n| `engine/server/api/handlers/internal_translate.py` | Adds `resolve_translatable_video` and `_subtitles_store`. Three sites now go through the helper. `SOURCE_INSTANCE` is imported. `resolve_video_row` is dropped. |\n| `engine/server/db/jobs/translate-worker.py` | Handle threaded through `run_job`, `generate` and `translate_audio`. `serve` uses attributes. `resolve_video` delegates. Both openers are used. Imports trimmed. |\n| `engine/server/api/server.py` | One import and one call. |\n| tests and docs | As listed below. |\n\nNo new modules and no new dependency. `fcntl` is imported inside one function only.\n\n---\n\n### `engine/server/data/subtitles.py`\n\n**Imports**\n\n```python\nimport json\nimport sqlite3\nimport time\nfrom contextlib import contextmanager\nfrom dataclasses import dataclass, field\nfrom pathlib import Path\nfrom typing import Any, Iterator\n```\n\n**Constants:** add beside `SOURCE_WHISPER`, byte-identical to the route's old value.\n\n```python\nSOURCE_WHISPER = \"whisper\"\nSOURCE_INSTANCE = \"instance\"\n```\n\n**Opener:** goes after `ensure_subtitles_schema`.\n\n```python\ndef open_subtitles_db(path: Path) -> sqlite3.Connection:\n    \"\"\"The one store opener for the Engine and the worker: create the parent directory, connect in WAL (connect_subtitles_db's busy timeout and lock retry), migrate (ensure_subtitles_schema); the connection is closed if the migration raises.\"\"\"\n    path.parent.mkdir(parents=True, exist_ok=True)\n    conn = connect_subtitles_db(path)\n    try:\n        ensure_subtitles_schema(conn)\n    except BaseException:\n        conn.close()\n        raise\n    return conn\n```\n\n**Shared instance-track encoder.** `store_ready_subtitles` switches to it. Its SQL and signature are unchanged. Its docstring gains: \"the cues are encoded by `_instance_cues_text`, as the handle's instance-track end encodes them\".\n\n```python\ndef _instance_cues_text(cues: list[dict[str, Any]]) -> str:\n    \"\"\"Compact JSON for an instance track's cues_json, shared by store_ready_subtitles and TranslateJob.end_ready_from_instance so the two writers encode alike; NaN allowed, unlike _cues_text.\"\"\"\n    return json.dumps(cues, ensure_ascii=False, separators=(\",\", \":\"))\n```\n\nIn `store_ready_subtitles`, the last tuple element becomes `_instance_cues_text(cues)`. `_cues_text` is unchanged.\n\n**Handle and claim**\n\n```python\n@dataclass(frozen=True)\nclass TranslateJob:\n    \"\"\"One claim on a running job: the connection it was claimed on, its key, its started_at and attempts. Every method is one conditional UPDATE that matches only while the row is running with this started_at, and answers whether the claim still held; False means the Engine state route's instance-track store (store_ready_subtitles) replaced the row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did.\"\"\"\n\n    conn: sqlite3.Connection = field(repr=False, compare=False)\n    video_id: str\n    instance_domain: str\n    target_language: str\n    started_at: int\n    attempts: int\n\n    def write_running_cues(self, cues: list[dict[str, Any]], detected_language: str) -> bool:\n        \"\"\"Rewrite the running job's whole cues_json after a chunk (AC4).\"\"\"\n        return _update_claim(self, \"cues_json = ?, detected_language = ?\", (_cues_text(cues), detected_language))\n\n    def end_ready(self, cues: list[dict[str, Any]], finished_at: int) -> bool:\n        \"\"\"End ready with the full, start-sorted cue list; fetched_at is set so the ready reader sees a normal ready row.\"\"\"\n        return _update_claim(self, \"state = 'ready', cues_json = ?, fetched_at = ?, finished_at = ?\", (_cues_text(cues), finished_at, finished_at))\n\n    def end_already_english(self, detected_language: str, finished_at: int) -> bool:\n        \"\"\"End already_english; English is detected before any cue is written, so cues_json was never set.\"\"\"\n        return _update_claim(self, \"state = 'already_english', detected_language = ?, finished_at = ?\", (detected_language, finished_at))\n\n    def end_failed(self, error: str, finished_at: int) -> bool:\n        \"\"\"End failed with its error text; partial cues stay in cues_json, unread because a failed row's cues are never served.\"\"\"\n        return _update_claim(self, \"state = 'failed', error = ?, finished_at = ?\", (error, finished_at))\n\n    def requeue(self) -> bool:\n        \"\"\"Put the job back without spending its claim (a stop mid-job, or whitelist.db unavailable at claim); queued_at is kept, so it stays at the head of the queue.\"\"\"\n        return _update_claim(self, \"state = 'queued', attempts = attempts - 1\", ())\n\n    def end_ready_from_instance(self, track_text: str, cues: list[dict[str, Any]], finished_at: int) -> bool:\n        \"\"\"End ready with the instance's English track, source instance, one timestamp for fetched_at and finished_at; every other job column is left as it is.\"\"\"\n        return _update_claim(self, \"state = 'ready', source = ?, track_text = ?, cues_json = ?, fetched_at = ?, finished_at = ?\", (SOURCE_INSTANCE, track_text, _instance_cues_text(cues), finished_at, finished_at))\n\n\ndef claim_translate_job(conn: sqlite3.Connection, target_language: str, started_at: int) -> TranslateJob | None:\n    \"\"\"Flip the oldest queued job to running, in one short transaction; its TranslateJob handle on conn, or None.\"\"\"\n    with _immediate(conn):\n        row = conn.execute(\"SELECT video_id, instance_domain FROM subtitles WHERE state = 'queued' AND target_language = ? ORDER BY queued_at, rowid LIMIT 1\", (target_language,)).fetchone()\n        if row is None:\n            return None\n        key = (row[0], row[1], target_language)\n        conn.execute(f\"UPDATE subtitles SET state = 'running', started_at = ?, attempts = attempts + 1 WHERE {_KEY}\", (started_at, *key))\n        claimed = conn.execute(f\"SELECT video_id, instance_domain, started_at, attempts FROM subtitles WHERE {_KEY}\", key).fetchone()\n    return TranslateJob(conn, claimed[\"video_id\"], claimed[\"instance_domain\"], target_language, claimed[\"started_at\"], claimed[\"attempts\"])\n\n\ndef _update_claim(job: TranslateJob, assignments: str, values: tuple[Any, ...]) -> bool:\n    \"\"\"One conditional UPDATE on job's running row, on the connection that claimed it; False (rowcount 0) once the state route's instance-track store, or an older blue/green Engine, replaced the row.\"\"\"\n    with job.conn:\n        cursor = job.conn.execute(f\"UPDATE subtitles SET {assignments} WHERE {_KEY} AND state = 'running' AND started_at = ?\", (*values, job.video_id, job.instance_domain, job.target_language, job.started_at))\n    return cursor.rowcount == 1\n```\n\n`TranslateJob` is defined before `claim_translate_job`. Python resolves `_update_claim` at call time, so its later position is fine.\n\n**Decision on equality and repr.** `conn` is marked `repr=False, compare=False`. Two handles for the same claim then compare equal, and `repr` does not print a connection object. That costs one `field(...)`, which is already in stdlib `dataclasses`.\n\n**SET strings:**\n- the five existing methods: copied verbatim from the deleted functions, including `attempts = attempts - 1`;\n- `end_ready_from_instance`: sets exactly the columns the upsert's `DO UPDATE` sets today (state, source, fetched_at, track_text, cues_json), plus `finished_at`, which `mark_translate_finished` set. `detected_language`, `error`, `attempts`, `queued_at` and `started_at` are untouched.\n\n**Recovery and the worker opener**\n\n```python\ndef _recover_translate_jobs(conn: sqlite3.Connection, finished_at: int) -> tuple[int, int]:\n    \"\"\"Requeue a running row once, fail it when found running a second time; (requeued, failed). Private: reached only through open_translate_worker_store, under the worker's flock.\"\"\"\n    # body unchanged: failed UPDATE first, then requeue, in one _immediate\n\n\ndef open_translate_worker_store(path: Path, lock_fd: int, finished_at: int) -> tuple[sqlite3.Connection, tuple[int, int]]:\n    \"\"\"The worker service's opener: re-assert the flock on lock_fd (LOCK_EX | LOCK_NB) before the file is touched, then open_subtitles_db and crash recovery; (conn, (requeued, failed)). On the descriptor that already holds the lock the re-assert is a no-op; on an unlocked descriptor it takes the lock; when another open file description holds it, BlockingIOError is raised and nothing is created. lock_fd stays the caller's to close.\"\"\"\n    import fcntl\n\n    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    conn = open_subtitles_db(path)\n    try:\n        return conn, _recover_translate_jobs(conn, finished_at)\n    except BaseException:\n        conn.close()\n        raise\n```\n\nThis also closes the impact's gap: the connection is closed if recovery raises. The flock comes before `open_subtitles_db`, so a refused call creates no directory either.\n\n**Deleted:** `store_running_cues`, `requeue_translate_job`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed`, `mark_translate_finished`, and the public `recover_translate_jobs`.\n\n**Unchanged:** `connect_subtitles_db`, `ensure_subtitles_schema`, `_immediate`, the fetchers, `enqueue_translate_job`, `write_translate_heartbeat`, `_KEY`, `MAX_CLAIMS`, `RECOVERY_ERROR`, `JOB_COLUMNS`.\n\n**Module docstring, paragraph 2, replaced:**\n\n> The Engine state route stores an instance's English track with store_ready_subtitles, an unconditional upsert to state 'ready', source 'instance'. Plan 49's translate worker adds the job states and the source 'whisper'; state and source stay plain TEXT. open_subtitles_db is the one opener (mkdir, WAL connect, migrate in place); open_translate_worker_store adds crash recovery and is the only way to run it, with the worker's flock re-asserted first. claim_translate_job hands back a TranslateJob whose six methods (running cues, ready, already_english, failed, requeue, ready from the instance track) each match only while the row is running with that claim's started_at, so the state route's upsert landing on a running row wins and every later job write is a no-op. A running job's cues are a whole-cues_json rewrite after each chunk, so fetch_ready_subtitles reads a ready row of either source unchanged, and the state route reads a running row's cues so far through fetch_subtitle_state. The file is in WAL mode: both blue/green Engines and the translate worker (claim, per-chunk rewrites, a heartbeat) write it.\n\n---\n\n### `engine/server/api/handlers/internal_translate.py`\n\n**Imports**\n\n```python\nfrom contextlib import contextmanager\nfrom typing import Any, Iterator\n...\nfrom data.subtitles import SOURCE_INSTANCE, enqueue_translate_job, fetch_subtitle_state, fetch_translate_heartbeat, store_ready_subtitles\n...\nfrom handlers.video import fetch_video_row\n```\n\n- The `SOURCE_INSTANCE = \"instance\"` line is deleted. The name still resolves as a module attribute through the import, so the stale probes keep working.\n- The `VIDEO_NOT_FOUND` comment becomes: `# Answered for every refusal of resolve_translatable_video, so the route does not reveal which check failed; the body /api/video answers for an unknown video.`\n\n**Shared resolve:** placed above `_generation_available`.\n\n```python\ndef resolve_translatable_video(conn: sqlite3.Connection, video_id: str, host: str | None, error_threshold: int | None) -> tuple[dict[str, Any] | None, str | None]:\n    \"\"\"The whitelisted row and None, or None and the refusal: missing host (decided before any lookup, since fetch_video_row with no host matches the id on any host), not in whitelist (fetch_video_row with error_threshold), host denied (the row's normalised domain is actively denied). Shared by both /internal/translate routes and the translate worker; takes no lock and writes no response.\"\"\"\n    if not host:\n        return None, \"missing host\"\n    row = fetch_video_row(conn, video_id, host, error_threshold=error_threshold)\n    if row is None:\n        return None, \"not in whitelist\"\n    if normalize_host(row[\"instance_domain\"]) in list_active_denied_hosts(conn):\n        return None, \"host denied\"\n    return row, None\n```\n\nThe order is host, then row, then denylist. The denylist is read only when a row exists, so an `OperationalError` from `fetch_video_row` surfaces first with its own text, as the worker's busy/unopenable classification needs.\n\n**Store access helper**\n\n```python\n@contextmanager\ndef _subtitles_store(server: Any) -> Iterator[sqlite3.Connection | None]:\n    \"\"\"Hold subtitles_db_lock for the whole body and yield subtitles_db, None when the store is closed; errors pass through to the caller's own handler.\"\"\"\n    with server.subtitles_db_lock:\n        yield server.subtitles_db\n```\n\n**`_read_key`**\n\n```python\n    try:\n        with _subtitles_store(server) as conn:\n            if conn is None:\n                return None, False\n            return fetch_subtitle_state(conn, video_id, instance_domain, TARGET_LANGUAGE), _generation_available(conn)\n    except sqlite3.Error as exc:\n        logging.warning(\"[translate] cache read failed video_id=%s host=%s: %s\", video_id, instance_domain, exc)\n        return None, False\n```\n\n**`_store_cues`.** The docstring gains \"a closed store (shutdown) stores nothing and is logged\".\n\n```python\n    try:\n        with _subtitles_store(server) as conn:\n            if conn is None:\n                logging.info(\"[translate] cache closed, track not stored video_id=%s host=%s\", video_id, instance_domain)\n                return\n            store_ready_subtitles(conn, video_id, instance_domain, TARGET_LANGUAGE, SOURCE_INSTANCE, track_text, cues, now_ms())\n    except sqlite3.Error as exc:\n        logging.warning(\"[translate] cache write failed video_id=%s host=%s: %s\", video_id, instance_domain, exc)\n```\n\nThe new line starts `[translate] cache closed`, not `[translate] instance fetch failed`, so `_failed_fetches` and the NONE_CASES exact-list assertions cannot pick it up.\n\n**`_resolve_translate_key`.** Body validation and the three 400s are byte-identical. The tail becomes:\n\n```python\n    host = normalize_host(raw_host)\n    if host is None:\n        respond_json(handler, 400, {\"error\": \"Invalid host\"})\n        return None\n    with server.db_lock:\n        row, _ = resolve_translatable_video(server.db, video_id, host, server.video_error_threshold)\n    if row is None:\n        respond_json(handler, 404, VIDEO_NOT_FOUND)\n        return None\n    # The row's own domain and canonical id, never the request's: the fetch goes to the video's instance and the store is keyed once per video.\n    canonical_id = row[\"video_id\"]\n    return body, canonical_id, row[\"instance_domain\"], row[\"video_uuid\"] or canonical_id\n```\n\nThere is one `db_lock` hold, which is not re-entered (the fake uses a plain `threading.Lock`). `resolve_video_row`'s unreachable `Missing video id` is not reintroduced.\n\n**Enqueue**\n\n```python\n    try:\n        # One lock hold, so availability cannot flip between the beat read and the enqueue.\n        with _subtitles_store(server) as conn:\n            outcome = enqueue_translate_job(conn, canonical_id, instance, TARGET_LANGUAGE, SUBTITLE_QUEUE_CAP, now_ms()) if conn is not None and _generation_available(conn) else None\n    except sqlite3.Error as exc:\n        ...unchanged\n```\n\n**Module docstring**\n- Paragraph 2: after \"An unknown or denylisted video answers 404 \u2026\", add \"(resolve_translatable_video, shared with the translate worker)\". After \"an instance track found then is stored ready over it\", add \"; with the store closed (shutdown) it is answered but not stored, and an info line says so\".\n- Paragraph 3: unchanged.\n\n---\n\n### `engine/server/db/jobs/translate-worker.py`\n\n**Path comment and imports**\n\n```python\n# api/ is for server_config and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.\n...\nfrom data.db import connect_readonly_db\nfrom data.moderation import normalize_host\nfrom data.subtitles import TranslateJob, claim_translate_job, connect_subtitles_db, enqueue_translate_job, open_subtitles_db, open_translate_worker_store, write_translate_heartbeat\nfrom data.source_fetch import READ_CHUNK_BYTES, SourceFetchFailed, fetch_bounded, media_host, stream_media\nfrom data.time import now_ms\nfrom handlers.internal_translate import TARGET_LANGUAGE, fetch_instance_track, resolve_translatable_video\n```\n\nThe `handlers.video` import and `list_active_denied_hosts` are removed. `TranslateJob` is imported for annotations only.\n\n**`JobTakenOver`**\n\n```python\nclass JobTakenOver(Exception):\n    \"\"\"A claim-conditional write matched no row: the Engine state route's instance-track store (store_ready_subtitles) replaced the running row, racing an enqueue and this claim during its up-to-15 s instance fetch, or an older blue/green Engine did.\"\"\"\n```\n\n**`resolve_video`.** The signature is unchanged. Tests monkeypatch it with four arguments.\n\n```python\ndef resolve_video(whitelist_path: Path, video_id: str, host: str, max_duration: int) -> tuple[dict[str, Any] | None, str | None]:\n    \"\"\"The whitelisted row and None, or None and the refusal text: resolve_translatable_video with VIDEO_ERROR_THRESHOLD (a missing host reads as not in whitelist), then the stored-duration bound; NULL duration passes.\"\"\"\n    conn = connect_readonly_db(whitelist_path)\n    try:\n        # sqlite3's 5 s default is shorter than the updater merge's commit; past 30 s this raises, never reads as not-found.\n        conn.execute(\"PRAGMA busy_timeout = 30000\")\n        row, refusal = resolve_translatable_video(conn, video_id, host, VIDEO_ERROR_THRESHOLD)\n    finally:\n        conn.close()\n    if refusal is not None:\n        return None, \"not in whitelist\" if refusal == \"missing host\" else refusal\n    duration = row[\"duration\"]\n    if isinstance(duration, int) and duration > max_duration:\n        return None, f\"duration {duration}s over {max_duration}s\"\n    return row, None\n```\n\n`connect_readonly_db` still raises before any query, for example `unable to open` on a deleted file.\n\n**`command_enqueue`.** Replaces lines 131-141.\n\n```python\n    try:\n        conn = open_subtitles_db(args.subtitles_db)\n        try:\n            outcome, state = enqueue_translate_job(conn, row[\"video_id\"], row[\"instance_domain\"], TARGET_LANGUAGE, args.cap, now_ms())\n        finally:\n            conn.close()\n    except sqlite3.Error as exc:\n        print(f\"error: subtitles.db: {exc}\")\n        return EXIT_ERROR\n```\n\nAn `OSError` from mkdir is not a `sqlite3.Error`, so it propagates as before.\n\n**`translate_audio`.** The signature becomes `translate_audio(job: TranslateJob, pipe: AudioPipe, runner: Any, max_chunk: int, stop: threading.Event, progress: dict[str, float]) -> str`. Three lines change and nothing else:\n- `if not job.end_already_english(language, now_ms()):`\n- `if not job.write_running_cues(cues, language):`\n- `if not job.end_ready(cues, now_ms()):`\n\n**`generate`**\n\n```python\ndef generate(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> str:\n    \"\"\"AC3 for one claim handle, each bound raising JobFailed before the next remote request, a locked or unopenable whitelist.db raising WhitelistBusy, a lost claim raising JobTakenOver; the end state written.\"\"\"\n    try:\n        row, refusal = resolve_video(args.whitelist_db, job.video_id, job.instance_domain, args.max_duration)\n    ...unchanged\n    fetched = fetch_instance_track(instance, video_key)\n    if fetched is not None:\n        if not job.end_ready_from_instance(fetched[0], fetched[1], now_ms()):\n            raise JobTakenOver()\n        return \"ready from the instance track\"\n    ...unchanged\n    try:\n        return translate_audio(job, pipe, runner, args.max_chunk_seconds * SAMPLE_RATE, stop, progress)\n    finally:\n        pipe.close()\n```\n\n**`run_job`**\n\n```python\ndef run_job(job: TranslateJob, args: argparse.Namespace, runner: Any, stop: threading.Event, progress: dict[str, float]) -> bool:\n    \"\"\"Take one claimed job to exactly one end state, or back to queued with its claim unspent when stop is set mid-job or whitelist.db is locked or unopenable at claim; a row the Engine's instance-track store took over is left as that store wrote it. True only for the whitelist.db requeue.\"\"\"\n    where = (job.video_id, job.instance_domain)\n    try:\n        state = generate(job, args, runner, stop, progress)\n        logging.info(\"[translate-worker] job %s video_id=%s host=%s\", state, *where)\n    except JobStopped:\n        job.requeue()\n        logging.info(\"[translate-worker] stopped mid-job, requeued video_id=%s host=%s\", *where)\n    except WhitelistBusy as exc:\n        # The attempt is given back, so MAX_CLAIMS recovery never counts these cycles.\n        job.requeue()\n        logging.warning(\"[translate-worker] whitelist.db unavailable, requeued video_id=%s host=%s: %s\", *where, exc)\n        return True\n    except JobTakenOver:\n        logging.info(\"[translate-worker] taken over by the instance track video_id=%s host=%s\", *where)\n    except JobFailed as exc:\n        job.end_failed(str(exc), now_ms())\n        logging.info(\"[translate-worker] job failed video_id=%s host=%s: %s\", *where, exc)\n    except Exception as exc:\n        # A CUDA out-of-memory fails only this job; the model is dropped so the next job loads it afresh instead of retrying in a loop (AC7).\n        if is_cuda_oom(exc):\n            runner.unload()\n        logging.exception(\"[translate-worker] job error video_id=%s host=%s\", *where)\n        job.end_failed(f\"{type(exc).__name__}: {exc}\", now_ms())\n    return False\n```\n\nThe log texts are unchanged. The results of requeue and end-failed are still ignored.\n\n**`serve`.** Its signature keeps `conn`, which it claims on. Two lines change (one of them the miss the plan did not name):\n\n```python\n        logging.info(\"[translate-worker] claimed video_id=%s host=%s attempts=%s\", job.video_id, job.instance_domain, job.attempts)\n        if run_job(job, args, runner, stop, progress):\n```\n\n**`heartbeat_loop`:** unchanged (plain `connect_subtitles_db`).\n\n**`command_run`.** Its own LOCK_NB, the `another worker holds` log line and exit 6 come first, as now. Then:\n\n```python\n    try:\n        stop = threading.Event()\n        for signum in (signal.SIGTERM, signal.SIGINT):\n            signal.signal(signum, lambda *_: stop.set())\n        progress = {\"at\": time.monotonic()}\n        conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())\n        beat: threading.Thread | None = None\n        try:\n            logging.info(\"[translate-worker] started pid=%s recovered requeued=%s failed=%s\", os.getpid(), requeued, failed)\n            beat = threading.Thread(target=heartbeat_loop, args=(args.subtitles_db, stop, progress), daemon=True)\n            beat.start()\n            serve(conn, args, WhisperRunner(), stop, progress)\n        finally:\n            stop.set()\n            if beat is not None:\n                beat.join(HEARTBEAT_SECONDS)\n            conn.close()\n    finally:\n        os.close(lock_fd)\n```\n\n`conn` is bound before the inner `try`, so there is no NameError. The opener closes its own connection if migration or recovery fails. `lock_fd` stays owned and closed here. The docstring becomes: \"\u2026 then the flock before subtitles.db is opened, so a refused second run writes nothing; then open_translate_worker_store (flock re-asserted, open, migrate, recover), the heartbeat thread and the claim loop until SIGTERM.\"\n\n**Module docstring**\n- Line 4: \"resolves the video against whitelist.db with the route's resolve_translatable_video\".\n- Line 6: \"run_job takes one claim handle (TranslateJob) through \u2026\".\n- Line 8: \"\u2026 flock (a refused second run exits 6 having written nothing), open_translate_worker_store (the flock re-asserted, then open, migrate and crash recovery), a heartbeat thread \u2026\".\n\n---\n\n### `engine/server/api/server.py`\n\n- Line 106: `from data.subtitles import open_subtitles_db`\n- Lines 370-372:\n\n```python\n    # After prepare_trending_override, so a rejected start creates nothing; the opener creates its own parent directory.\n    subtitles_db = open_subtitles_db(subtitles_db_path)\n```\n\n---\n\n### Tests\n\n**`tests/active/test_subtitles.py`**\n- **WORKER_SCRIPT:**\n  - The import becomes `claim_translate_job, connect_subtitles_db, enqueue_translate_job, ensure_subtitles_schema, write_translate_heartbeat`.\n  - The check becomes `(job.video_id, job.instance_domain) != (key, host)`, and its message becomes `{None if job is None else (job.video_id, job.instance_domain)!r}`.\n  - The writes become `job.write_running_cues(first, \"fr\")` and `job.end_ready(full, 1700000200000 + n)`, with messages naming the methods.\n  - The script keeps `connect_subtitles_db`+`ensure_subtitles_schema`, so the race semantics are unchanged.\n- **Claim test (line 340):** reads attributes: `(job.video_id, job.instance_domain, job.started_at, job.attempts)`.\n- **Recovery test:**\n  - It imports `claim_translate_job, open_translate_worker_store`.\n  - It opens `lock_fd = os.open(tmp_path / \"worker.lock\", O_RDONLY|O_CREAT)` and `fcntl.flock(lock_fd, LOCK_EX)`.\n  - Each recover call becomes `opened, counts = open_translate_worker_store(path, lock_fd, 9000)`, then `opened.close()`, then `assert tuple(counts) == (1, 0)` (and `(2, 1)` at 9500).\n  - It reads `first.video_id`, `first.attempts` and `(row.video_id, row.attempts)`.\n  - `os.close(lock_fd)` in a `finally`.\n- **`fetch_subtitle_state` test:** `job = claim_translate_job(conn, \"en\", 2000)`, then `assert job.write_running_cues([...], \"fr\")`.\n- **New `test_every_claim_write_after_an_instance_track_takeover_matches_nothing_and_reports_the_claim_lost`.** Parametrised over the six methods:\n\n```python\nCLAIM_WRITES = {\n    \"running cues\": lambda job: job.write_running_cues([{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], \"fr\"),\n    \"ready\": lambda job: job.end_ready([{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], 9000),\n    \"already_english\": lambda job: job.end_already_english(\"en\", 9000),\n    \"failed\": lambda job: job.end_failed(\"boom\", 9000),\n    \"requeue\": lambda job: job.requeue(),\n    \"ready from instance\": lambda job: job.end_ready_from_instance(\"WEBVTT x\", [{\"start\": 1.0, \"end\": 2.0, \"text\": \"x\"}], 9000),\n}\n```\n\n  The test enqueues and claims, then runs `store_ready_subtitles(conn, \u2026, \"instance\", TRACK, CUES, 8000)` and takes a `_snapshot`. It asserts `write(job) is False` and that `_snapshot` is unchanged. A control runs the same write on a fresh claim without the takeover and asserts `True`, so that `False` is shown to be the takeover's doing.\n- **New `test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp`:**\n  - claim, then `job.write_running_cues(\u2026, \"fr\")`, then `job.end_ready_from_instance(\"WEBVTT t\", cues, 9000)` is True;\n  - the row has state/source `ready`/`instance`, `track_text`, a compact `cues_json` with no space, and `fetched_at == finished_at == 9000`;\n  - `detected_language == \"fr\"`, `error IS NULL`, `attempts == 1`, `queued_at` and `started_at` are unchanged;\n  - `fetch_ready_subtitles` returns the cues.\n- **New `test_open_subtitles_db_creates_a_missing_directory_and_the_full_schema_in_wal`:** on `tmp_path / \"a\" / \"b\" / \"subtitles.db\"`, the columns equal `ALL_COLUMNS`, the heartbeat table exists and the mode is `wal`.\n- **New `test_open_subtitles_db_adds_the_job_columns_to_a_b1_file`:** reuses `_b1_file`; the columns equal `ALL_COLUMNS` and `_old_cues == B1_CUES`.\n- **New `test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing`:**\n  - `held = os.open(lock)` locked LOCK_EX; `mine = os.open(lock)` is a separate description, not `dup`;\n  - `pytest.raises(BlockingIOError)` on `open_translate_worker_store(tmp_path / \"sub\" / \"subtitles.db\", mine, 1)`;\n  - the file and its parent are absent;\n  - control: after closing `held`, the same call succeeds on `mine` and the file exists.\n- **Docstring.** Lines 12, 14 and 17 are reworded to the handle methods, the openers and `open_translate_worker_store`. New bullets cover the takeover, the instance end, the openers and the flock.\n\n**`tests/active/test_internal_translate.py`**\n- `_claimed` returns `claim_translate_job(store, \"en\", NOW - 1000)` with annotation `-> \"TranslateJob\"` and docstring \"its claim handle\".\n- `_seed` imports `enqueue_translate_job, store_ready_subtitles` and calls `_claimed(store).write_running_cues(RUNNING, \"fr\")`, `.end_failed(\"boom\", NOW - 500)` and `.end_already_english(\"en\", NOW - 500)`.\n- Lines 755-792:\n  - `job = _claimed(store)`;\n  - `assert job.write_running_cues(RUNNING, \"fr\")`;\n  - `assert job.end_failed(\"boom\", NOW)`;\n  - the imports keep only `write_translate_heartbeat`.\n- `_subtitles_db` switches to `open_subtitles_db(path)`, so the docstring \"as server.py opens it\" is true again. Line 19 of the module docstring is reworded to match.\n- **New `test_a_closed_store_still_answers_an_instance_track_ready_and_logs_that_it_was_not_stored`:**\n  - `server = _server(...)` with `subtitles_db = None` and `_instance(True)`;\n  - the answer is `[[200, {\"state\": \"ready\", \"cues\": CUES, \"available\": False}]]`;\n  - `caplog` has exactly one record starting `[translate] cache closed, track not stored`.\n- **New resolve test** in `test_internal_translate.py`, three cases on the `whitelist` fixture DB:\n  - `resolve_translatable_video(conn, VIDEO_ID, None, 0)` and the same with `\"\"` return `(None, \"missing host\")`, even though the id exists;\n  - the denied-host video returns `(None, \"host denied\")`;\n  - an unknown id returns `(None, \"not in whitelist\")`;\n  - the known video returns its row.\n\n**`tests/active/test_translate_worker.py`**\n- `Rig.claim` asserts on `(self.job.video_id, self.job.instance_domain, self.job.started_at, self.job.attempts)`.\n- `Rig.run` calls `self.worker.run_job(self.job, args, runner, \u2026)`.\n- The fetch-reason test calls `worker.run_job(job, args, UnreachedRunner(), \u2026)`.\n- Docstring line 10 becomes `run_job(job, args, runner, stop, progress)`, where `job` is the claim handle.\n- **New `test_an_instance_track_found_after_the_engine_took_the_row_over_writes_nothing_and_logs_the_takeover`:**\n  - The test serves the English listing and track.\n  - It wraps `worker.fetch_instance_track` through `monkeypatch.setattr(rig.worker, \"fetch_instance_track\", \u2026)`. The wrapper calls the real function, then `store_ready_subtitles(b1, \"v-1\", HOST, \"en\", \"instance\", \"WEBVTT engine\", ENGINE_CUES, 1_700_000_000_000)`, snapshots `rig.row()` and returns the fetched value.\n  - Assertions: `rig.row() == taken`, `caplog` has the `taken over by the instance track video_id=v-1 host=\u2026` line, no `failed`, and `runner.transcribes == 0`.\n  - This pins the approved behaviour change, which no existing test reaches. Today's code would fail it, because the upsert overwrites `track_text`.\n- The existing English-track test at 1016 is unchanged and stays green: the cues decode to `CUES`, `track_text == TRACK`, and `finished_at` is now one `now_ms()` inside the window.\n\n---\n\n### Docs (settled list, as written)\n\n**`TRANSLATE_WORKER.md`**\n- Line 72, start-order step 5: \"`open_translate_worker_store` re-asserts the flock on the held descriptor, then creates the directory, opens `subtitles.db` in WAL, migrates and runs crash recovery; the counts are logged.\"\n- Line 90: \"store it `ready` with source `instance` while the claim holds (`end_ready_from_instance`); if the Engine's store took the row over first, nothing is written and the job is taken over.\"\n- Line 147: \"under the lock: recovery is private to the store and reachable only through `open_translate_worker_store`.\"\n- Line 49: \"resolved by `resolve_translatable_video`, as the route does\".\n- A new short subsection, \"The Claim Handle\": `claim_translate_job` returns a `TranslateJob` holding its connection, with six methods. Each matches only while the row is `running` with the claim's `started_at` and returns `False` after a takeover. `run_job` raises `JobTakenOver` on a `False` result from running cues, ready, already_english or ready-from-instance.\n- \u00a7 Takeover: left as it is (it names no removed function).\n\n**`engine/server/README.md`**\n- \u00a729-36: `open_subtitles_db` as the single opener; the `TranslateJob` handle and its methods; `open_translate_worker_store` as the only recovery path, under the flock.\n- Line 17: `resolve_translatable_video` (`fetch_video_row` with the error threshold, then the denylist on the row's domain).\n- Line 19: \"with the store closed, an info line is logged and the answer stays `ready`\".\n- Line 45: \"creating the file and its parent directory when missing\". The Notes record that a custom path in a missing directory now starts.\n\n**`CONTEXT.md` line 19:** add \"while its claim holds\".\n\n---\n\n### Check against the plan and the requirements (pass 1, converged)\n\n| Requirement | Draft |\n|---|---|\n| Claim unchanged, returns handle or None | `claim_translate_job`: the same transaction, then a `TranslateJob` |\n| Handle in `subtitles.py`, key, `started_at`, `attempts`, holds connection | frozen dataclass; `conn` with `repr=False, compare=False` |\n| Six operations, the compare-and-set in each, one lost-claim report | six methods, all through `_update_claim`, all `bool` |\n| No tuple outside the store; five functions and `mark_translate_finished` gone | deleted; the worker and tests use attributes and methods only |\n| Instance end: one UPDATE, columns, NaN-allowing encoding, one timestamp, no-op when lost | `end_ready_from_instance` + `_instance_cues_text`; `generate` raises `JobTakenOver` on `False` |\n| Takeover unchanged | `_store_cues` \u2192 `store_ready_subtitles`, unconditional |\n| Docstrings name the real writer | `TranslateJob`, `_update_claim`, `JobTakenOver`, `run_job` |\n| One opener; Engine, enqueue and run use it; heartbeat decided | `open_subtitles_db`; `server.py`, `command_enqueue`, via `open_translate_worker_store`; heartbeat keeps the plain connect |\n| Recovery logic unchanged, unreachable without the flock, shown by a test | `_recover_translate_jobs` private; flock re-assert in the only caller; refusal test |\n| One route helper; closed-store answers and error handling unchanged; beat and enqueue in one hold | `_subtitles_store`; three sites; one `with` in enqueue |\n| Resolve: three refusals, order, both callers, route 400/404, worker texts | `resolve_translatable_video`; `missing host` mapped to `not in whitelist` in the worker |\n| `run_job` without `conn`, `serve` attribute access | done; `serve` covered (the impact's miss) |\n| Docs and docstrings | listed above |\n\nTwo small additions beyond the plan's list, both inside its stated decisions:\n1. `open_translate_worker_store` closes the connection when recovery raises. This fixes the gap the impacts flagged.\n2. One worker test drives `generate` through a takeover that lands before the instance-track end. It pins the approved behaviour change end to end.\n\nSimplifications, named:\n- `TranslateJob` is pinned to one connection. A handle cannot outlive or move off the connection that claimed it. Upgrade path: none needed until a second claimer exists.\n- Stale probes in `tests/tmp/` and `delete_me/` that call the removed functions will break if run. This is accepted per the plan.",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_54_translate_job_handle_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase1.py:73 \u2014 `write(job) is False`, parametrised over all six handle methods (running cues, ready, already_english, failed, requeue, ready from instance). It runs after `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the claimed running row. The control at :71 confirms the Engine's row is in place.",
          "expected": "False for each of the six methods. The current run is red at exactly this line in all six cases with `AttributeError: 'sqlite3.Row' object has no attribute 'write_running_cues'` (and likewise `end_ready`, `end_already_english`, `end_failed`, `requeue`, `end_ready_from_instance`): today's `claim_translate_job` returns a `sqlite3.Row`, not a handle. The probe shows today's five per-claim functions on the same takeover each return False (`running cues False True` \u2026 `requeue False True`), which is the contract the methods take over.",
          "wrong_implementation": "A method whose UPDATE leaves out `state = 'running' AND started_at = ?` (for example `end_ready_from_instance` written as the old `store_ready_subtitles` upsert plus an unconditional stamp, or any SET matched on the key alone) matches the Engine's row and returns True. A method that never reports, or always returns True, also fails here."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase1.py:76 \u2014 `_snapshot(path) == taken`: every column of every row, rowid included, as quoted SQL literals, reads the same after the write as after the takeover. It is armed by the held-claim controls at :82 and :85, which show the same write on a fresh claim returns True and changes the snapshot.",
          "expected": "Equal: the Engine's row as it landed, i.e. state ready, source instance, fetched_at 8000, the Engine's track_text, cues_json `[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]`, queued_at 1000, started_at 2000, finished_at NULL, error NULL, detected_language NULL, attempts 1. These are the probe's observed takeover snapshot values. Not yet reached in the current run, because :73 fails first on the missing method.",
          "wrong_implementation": "An instance-track end that keeps today's pair (`store_ready_subtitles`, then `mark_translate_finished`) rewrites track_text, cues_json and fetched_at, and stamps finished_at. The probe saw `mark_translate_finished` alone turn finished_at NULL into 9000 on the taken-over row. A method that writes some column unconditionally and reports False anyway (a two-statement write where only the second is conditional) also changes the snapshot."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase1.py:143 \u2014 `_snapshot(rig.subtitles) == seen[\"taken\"]` after `run_job`. Here `fetch_instance_track` is wrapped so the real fetch finds the English track (control :140) and the Engine then stores its own different track ready/instance over the running row (control :141).",
          "expected": "Equal to the snapshot taken right after the Engine's store: fetched_at 1700000000000, track_text `WEBVTT\\n\\n00:05.000 --> 00:06.000\\nEngine\\n`, cues_json `[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]`, finished_at NULL. The current run is red at exactly this line: the actual row has the worker's track (`WEBVTT\\n\\n00:03.000 --> 00:04.000\\n<i>World</i>\u2026`), its cues `[{\"start\":1.0,\"end\":2.5,\"text\":\"Hello\"},{\"start\":3.0,\"end\":4.0,\"text\":\"World\"}]`, and fetched_at = finished_at = 1791132912229.",
          "wrong_implementation": "Today's `generate` (store_ready_subtitles + mark_translate_finished) overwrites the Engine's row with the worker's track and stamps finished_at, as the run showed. So does a `generate` that calls the new conditional end but ignores its False and then calls the old upsert or another unconditional write."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase1.py:144 \u2014 `rig.cues_writes() == seen[\"writes\"]`: the trigger table recording every cues_json write holds nothing past the Engine's own write. The control at :142 shows the trigger records the Engine's upsert as `[ENGINE_CUES_JSON]`, so it would record a worker upsert too.",
          "expected": "`['[{\"start\":5.0,\"end\":6.0,\"text\":\"Engine\"}]']` only. The probe of today's code saw a second entry, `[{\"start\":1.0,\"end\":2.5,\"text\":\"Hello\"},{\"start\":3.0,\"end\":4.0,\"text\":\"World\"}]`, after the takeover.",
          "wrong_implementation": "A worker that writes the instance cues and then puts the Engine's value back, or writes the same bytes again, leaves the final snapshot looking right but adds a trigger entry. Today's unconditional upsert adds one, as the probe observed."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase1.py:145 \u2014 the worker's `[translate-worker]` log lines are exactly `[TAKEN_OVER]` = `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`.",
          "expected": "Exactly that one line. The text was observed in probe_54_phase1_takeover_log.py, where today's `JobTakenOver` path (reached by a mid-job takeover) logged `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`. The route's `[translate] instance fetch failed\u2026` line in the same run is excluded by the prefix filter. Today's instance path logs `[translate-worker] job ready from the instance track video_id=v-1 host=peer.example` instead (observed in both the checkpoint run and the probe).",
          "wrong_implementation": "A `generate` that ignores the False from the instance-track end logs `job ready from the instance track`. One that maps the lost claim to `JobFailed` or a generic exception logs `job failed \u2026` or `job error \u2026` (and writes a failed end, which :143 also catches). One that falls through to transcription logs a later line."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical."
        },
        {
          "id": "C2",
          "text": "When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_54_translate_job_handle_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_54_translate_job_handle_phase1.py  8 failed                               0.0s\n  ------------------------------------------------\n  total                                             8 failed                               0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_54_translate_job_handle_phase2.py": {
      "rows": [
        {
          "clause": "C1a",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:71 \u2014 `path.parent.is_dir()` after `open_subtitles_db(tmp_path/\"a\"/\"b\"/\"subtitles.db\")`, with the control at :63 showing `a` absent before",
          "expected": "True: the opener creates `a/b`",
          "wrong_implementation": "An opener that connects without mkdir. The no_mkdir variant raises OperationalError \"unable to open database file\" at the call."
        },
        {
          "clause": "C1b",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:73, :74, :75 \u2014 through a fresh plain connection to the nested file: the columns sorted equal ALL_COLUMNS, `[\"state\", \"queued_at\"]` is among the index column lists, and the heartbeat columns are [\"id\", \"beat_at\", \"pid\"]; plus :67, where the returned connection reads `fetch_translate_heartbeat` as None",
          "expected": "All fourteen columns, the (state, queued_at) index, and heartbeat id/beat_at/pid",
          "wrong_implementation": "Connect without migrating: columns read [] (probed). A partial migration missing the index or the heartbeat table fails :74 or :75."
        },
        {
          "clause": "C1c",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:76 \u2014 the nested file's journal_mode, read through a fresh plain connection",
          "expected": "\"wal\"",
          "wrong_implementation": "A plain sqlite3.connect plus migrate leaves the rollback journal. The no_wal variant fails tests 1 and 2."
        },
        {
          "clause": "C1d",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:97, :98, :99 \u2014 the B1 file's columns, index and heartbeat columns after `open_subtitles_db`; plus :92 and :103, where the returned connection and a plain one read B1_CUES",
          "expected": "ALL_COLUMNS, the (state, queued_at) index, heartbeat id/beat_at/pid, and old cues equal to B1_CUES",
          "wrong_implementation": "An opener that leaves an existing B1 table unmigrated fails the column, index and heartbeat checks. One that recreates the table loses the rows and fails :92 and :103."
        },
        {
          "clause": "C1e",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:100 \u2014 the B1 file's journal_mode after the opener; the control at :85 shows \"delete\" before",
          "expected": "\"wal\"",
          "wrong_implementation": "Migrating without the WAL connect: ensure_subtitles_schema alone leaves \"delete\" (probed). The no_wal variant fails here."
        },
        {
          "clause": "C2a",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:116 \u2014 while a separate os.open description holds LOCK_EX, `open_translate_worker_store(path, mine, 1)`, bounded by `_bounded`",
          "expected": "raises BlockingIOError",
          "wrong_implementation": "No flock: the no_lock variant fails with \"DID NOT RAISE BlockingIOError\". A blocking LOCK_EX: the blocking variant fails with \"blocked for 10 s\" instead of hanging."
        },
        {
          "clause": "C2b",
          "assertion": "tests/tmp/test_54_translate_job_handle_phase2.py:118, :119 \u2014 after the refusal, neither subtitles.db nor `sub` exists. Controls at :126\u2013127: once the holder is closed, the same call returns (0, 0) and the file exists",
          "expected": "both absent",
          "wrong_implementation": "mkdir or connect before the flock. The mkdir_first variant fails at :119."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode."
        },
        {
          "id": "C2",
          "text": "`open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock."
        }
      ],
      "surface": "checkpoint"
    }
  },
  "audits": {
    "tests/tmp/test_54_translate_job_handle_phase1.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n1. The parametrized C1 test errors at line 73, `assert write(job) is False`, with an `AttributeError`. In every case the `CLAIM_WRITES` lambda (lines 40\u201345) calls a handle method on what `claim_translate_job` still returns: a `sqlite3.Row` (engine/server/data/subtitles.py:139\u2013147), not a `TranslateJob`.\n2. The held-claim test errors at line 95, `job.end_ready_from_instance(...)`, the same way.\n3. The C2 test fails at line 143, `assert _snapshot(rig.subtitles) == seen[\"taken\"]`. `generate` still calls `store_ready_subtitles` unconditionally (translate-worker.py:407), so the worker writes `TRACK` over the Engine's `ENGINE_TRACK` row, and `track_text`, `cues_json` and `fetched_at` all differ from the snapshot.\n\nNOT ASSESSED\n1. `exempted_clauses` was not supplied, so the test was treated as having none.\n2. `fixtures_path` was given as \"none found\". I resolved the fixtures `rig` and `clip` and the helpers `_snapshot`, `_subtitles`, `Rig.row`, `Rig.cues_writes` and `StubRunner` directly in tests/active/test_translate_worker.py and tests/active/test_subtitles.py. No conftest.py was read.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 4 must_prove, 13 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | after a `store_ready_subtitles` takeover each of the six methods \"returns False\" | :73 | a handle that reports True (claim still held) after the Engine's upsert, for any of the six parametrized writes at :39-46 | CARRIED |\n| C1b | must_prove | \"leaves the row byte-identical\" | :76 | any write after the takeover, because `_snapshot` compares rowid and `quote()` of every column; also a write keyed on `started_at` alone, which the takeover leaves intact | CARRIED |\n| C2a | must_prove | instance track found after the takeover, \"`generate` writes nothing\" | :143, :144 | the worker's `store_ready_subtitles` over the Engine row (track_text/cues differ, :31-35), `mark_translate_finished` stamping finished_at on the ready row, or a failed-end write | CARRIED |\n| C2b | must_prove | \"the takeover is logged\" | :145 | no log line, a `job ready from the instance track` line, or any additional failed/error line, because the list must equal exactly `[TAKEN_OVER]` | CARRIED |\n| D1 | docstring | \"no write through the claim's `TranslateJob` handle changes it\" | :76 | a handle write that lands on the Engine's row | CARRIED |\n| D2 | docstring | six methods after takeover each return False | :73 | True returned after the takeover | CARRIED |\n| D3 | docstring | \"every column of every row, rowid included, reads the same\" | :76 | a column, type or rowid changed (`_snapshot`, test_subtitles.py:205-211) | CARRIED |\n| D4 | docstring | same method on a fresh claim \"returns True\" | :82 | a method that always returns False | CARRIED |\n| D5 | docstring | \"and changes the row\" | :85 | a method that is a no-op, so an unchanged row would prove nothing | CARRIED |\n| D6 | docstring | claim held: end ready from instance \"returns True\" | :95 | a held-claim end reporting the claim lost | CARRIED |\n| D7a | docstring | leaves \"ready, instance, the track text\" | :105-113 | the wrong state or source left in place (still `whisper`/`running`), or track_text not stored | CARRIED |\n| D7b | docstring | \"the cues as compact JSON\" | :113 | default `json.dumps` separators (spaces), or partial cues left in place | CARRIED |\n| D7c | docstring | \"fetched_at and finished_at both the one given time\" | :111, :116 | fetched_at left at QUEUED_AT (enqueue sets it), finished_at left NULL, or two different clocks | CARRIED |\n| D7d | docstring | \"detected_language, error, attempts, queued_at and started_at as the running job had them\" | :114-119 | detected_language cleared (it was set to \"fr\" at :94), attempts reset or incremented, queued_at/started_at overwritten, a non-NULL error written; clearing error is indistinguishable because the running row's error is already NULL | CARRIED |\n| D8 | docstring | \"the ready reader then returns those cues\" | :96 | a row `fetch_ready_subtitles` cannot read (wrong state, bad cues_json) | CARRIED |\n| D9 | docstring | worker: real fetch found the track, then the Engine stored a different track over the running row | :140, :141, :142 | (controls) a test in which the takeover never happened or the trigger records nothing | CARRIED |\n| D10 | docstring | worker: \"nothing was transcribed and nothing past the caption list and the track was fetched\" | :146, :147 | a worker that falls through to the video JSON, the media download or Whisper after the takeover | CARRIED |\n| N1 | name | \"every claim write after an instance track takeover reports the claim lost\" | :73 | any of the six returning True | CARRIED |\n| N2 | name | \"and leaves the row byte-identical\" | :76 | any byte changed | CARRIED |\n| N3 | name | \"ending ready from the instance track while the claim holds leaves ready instance\" | :109-110 | another state or source | CARRIED |\n| N4 | name | \"with one timestamp\" | :111, :116 | fetched_at \u2260 finished_at | CARRIED |\n| N5 | name | \"and the job columns kept\" | :114-119 | queued_at, started_at, attempts or detected_language overwritten | CARRIED |\n| N6 | name | \"an instance track found after the engine took the row over writes nothing\" | :143, :144 | any subtitles write or cues_json write after the takeover | CARRIED |\n| N7 | name | \"and logs the takeover\" | :145 | the takeover line missing, or other worker lines present | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` has no `TranslateJob` handle. engine/server/data/subtitles.py:139 `claim_translate_job` returns `sqlite3.Row | None`, and no file in `code_under_test` defines `write_running_cues`, `end_ready`, `end_already_english`, `end_failed`, `requeue` or `end_ready_from_instance`. A Grep finds them only in the test, plan docs and test-output files. tests/tmp/test_54_translate_job_handle_phase1.py:39-46 calls them on the object `_claimed` returns at :53.\n   - So I could not check that the six entries at :39-46 are the handle's complete set of claim-conditional writes, which is what C1's \"each of the six\" relies on. C1a/C1b are judged against the six the test lists.\n   - For the same reason I could not check the methods' accepted inputs, so the bounds principle was judged only from what the test passes.\n2. The C2 path goes through `Rig.run` (tests/active/test_translate_worker.py:546-554). It passes the claimed `sqlite3.Row` to `run_job`. Whether `run_job` will receive a handle under this phase cannot be told from the code supplied.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\n1. The parametrized C1 test errors at line 73, `assert write(job) is False`, with an `AttributeError`. In every case the `CLAIM_WRITES` lambda (lines 40\u201345) calls a handle method on what `claim_translate_job` still returns: a `sqlite3.Row` (engine/server/data/subtitles.py:139\u2013147), not a `TranslateJob`.\n2. The held-claim test errors at line 95, `job.end_ready_from_instance(...)`, the same way.\n3. The C2 test fails at line 143, `assert _snapshot(rig.subtitles) == seen[\"taken\"]`. `generate` still calls `store_ready_subtitles` unconditionally (translate-worker.py:407), so the worker writes `TRACK` over the Engine's `ENGINE_TRACK` row, and `track_text`, `cues_json` and `fetched_at` all differ from the snapshot.\n\nNOT ASSESSED\n1. `exempted_clauses` was not supplied, so the test was treated as having none.\n2. `fixtures_path` was given as \"none found\". I resolved the fixtures `rig` and `clip` and the helpers `_snapshot`, `_subtitles`, `Rig.row`, `Rig.cues_writes` and `StubRunner` directly in tests/active/test_translate_worker.py and tests/active/test_subtitles.py. No conftest.py was read.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 4 must_prove, 13 docstring, 7 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | after a `store_ready_subtitles` takeover each of the six methods \"returns False\" | :73 | a handle that reports True (claim still held) after the Engine's upsert, for any of the six parametrized writes at :39-46 | CARRIED |\n| C1b | must_prove | \"leaves the row byte-identical\" | :76 | any write after the takeover, because `_snapshot` compares rowid and `quote()` of every column; also a write keyed on `started_at` alone, which the takeover leaves intact | CARRIED |\n| C2a | must_prove | instance track found after the takeover, \"`generate` writes nothing\" | :143, :144 | the worker's `store_ready_subtitles` over the Engine row (track_text/cues differ, :31-35), `mark_translate_finished` stamping finished_at on the ready row, or a failed-end write | CARRIED |\n| C2b | must_prove | \"the takeover is logged\" | :145 | no log line, a `job ready from the instance track` line, or any additional failed/error line, because the list must equal exactly `[TAKEN_OVER]` | CARRIED |\n| D1 | docstring | \"no write through the claim's `TranslateJob` handle changes it\" | :76 | a handle write that lands on the Engine's row | CARRIED |\n| D2 | docstring | six methods after takeover each return False | :73 | True returned after the takeover | CARRIED |\n| D3 | docstring | \"every column of every row, rowid included, reads the same\" | :76 | a column, type or rowid changed (`_snapshot`, test_subtitles.py:205-211) | CARRIED |\n| D4 | docstring | same method on a fresh claim \"returns True\" | :82 | a method that always returns False | CARRIED |\n| D5 | docstring | \"and changes the row\" | :85 | a method that is a no-op, so an unchanged row would prove nothing | CARRIED |\n| D6 | docstring | claim held: end ready from instance \"returns True\" | :95 | a held-claim end reporting the claim lost | CARRIED |\n| D7a | docstring | leaves \"ready, instance, the track text\" | :105-113 | the wrong state or source left in place (still `whisper`/`running`), or track_text not stored | CARRIED |\n| D7b | docstring | \"the cues as compact JSON\" | :113 | default `json.dumps` separators (spaces), or partial cues left in place | CARRIED |\n| D7c | docstring | \"fetched_at and finished_at both the one given time\" | :111, :116 | fetched_at left at QUEUED_AT (enqueue sets it), finished_at left NULL, or two different clocks | CARRIED |\n| D7d | docstring | \"detected_language, error, attempts, queued_at and started_at as the running job had them\" | :114-119 | detected_language cleared (it was set to \"fr\" at :94), attempts reset or incremented, queued_at/started_at overwritten, a non-NULL error written; clearing error is indistinguishable because the running row's error is already NULL | CARRIED |\n| D8 | docstring | \"the ready reader then returns those cues\" | :96 | a row `fetch_ready_subtitles` cannot read (wrong state, bad cues_json) | CARRIED |\n| D9 | docstring | worker: real fetch found the track, then the Engine stored a different track over the running row | :140, :141, :142 | (controls) a test in which the takeover never happened or the trigger records nothing | CARRIED |\n| D10 | docstring | worker: \"nothing was transcribed and nothing past the caption list and the track was fetched\" | :146, :147 | a worker that falls through to the video JSON, the media download or Whisper after the takeover | CARRIED |\n| N1 | name | \"every claim write after an instance track takeover reports the claim lost\" | :73 | any of the six returning True | CARRIED |\n| N2 | name | \"and leaves the row byte-identical\" | :76 | any byte changed | CARRIED |\n| N3 | name | \"ending ready from the instance track while the claim holds leaves ready instance\" | :109-110 | another state or source | CARRIED |\n| N4 | name | \"with one timestamp\" | :111, :116 | fetched_at \u2260 finished_at | CARRIED |\n| N5 | name | \"and the job columns kept\" | :114-119 | queued_at, started_at, attempts or detected_language overwritten | CARRIED |\n| N6 | name | \"an instance track found after the engine took the row over writes nothing\" | :143, :144 | any subtitles write or cues_json write after the takeover | CARRIED |\n| N7 | name | \"and logs the takeover\" | :145 | the takeover line missing, or other worker lines present | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` has no `TranslateJob` handle. engine/server/data/subtitles.py:139 `claim_translate_job` returns `sqlite3.Row | None`, and no file in `code_under_test` defines `write_running_cues`, `end_ready`, `end_already_english`, `end_failed`, `requeue` or `end_ready_from_instance`. A Grep finds them only in the test, plan docs and test-output files. tests/tmp/test_54_translate_job_handle_phase1.py:39-46 calls them on the object `_claimed` returns at :53.\n   - So I could not check that the six entries at :39-46 are the handle's complete set of claim-conditional writes, which is what C1's \"each of the six\" relies on. C1a/C1b are judged against the six the test lists.\n   - For the same reason I could not check the methods' accepted inputs, so the bounds principle was judged only from what the test passes.\n2. The C2 path goes through `Rig.run` (tests/active/test_translate_worker.py:546-554). It passes the claimed `sqlite3.Row` to `run_job`. Whether `run_job` will receive a handle under this phase cannot be told from the code supplied.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "after a `store_ready_subtitles` takeover each of the six methods \"returns False\"",
            "assertion": ":73",
            "excludes": "a handle that reports True (claim still held) after the Engine's upsert, for any of the six parametrized writes at :39-46",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"leaves the row byte-identical\"",
            "assertion": ":76",
            "excludes": "any write after the takeover, because `_snapshot` compares rowid and `quote()` of every column; also a write keyed on `started_at` alone, which the takeover leaves intact",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "instance track found after the takeover, \"`generate` writes nothing\"",
            "assertion": ":143, :144",
            "excludes": "the worker's `store_ready_subtitles` over the Engine row (track_text/cues differ, :31-35), `mark_translate_finished` stamping finished_at on the ready row, or a failed-end write",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "\"the takeover is logged\"",
            "assertion": ":145",
            "excludes": "no log line, a `job ready from the instance track` line, or any additional failed/error line, because the list must equal exactly `[TAKEN_OVER]`",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"no write through the claim's `TranslateJob` handle changes it\"",
            "assertion": ":76",
            "excludes": "a handle write that lands on the Engine's row",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "six methods after takeover each return False",
            "assertion": ":73",
            "excludes": "True returned after the takeover",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"every column of every row, rowid included, reads the same\"",
            "assertion": ":76",
            "excludes": "a column, type or rowid changed (`_snapshot`, test_subtitles.py:205-211)",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "same method on a fresh claim \"returns True\"",
            "assertion": ":82",
            "excludes": "a method that always returns False",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"and changes the row\"",
            "assertion": ":85",
            "excludes": "a method that is a no-op, so an unchanged row would prove nothing",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "claim held: end ready from instance \"returns True\"",
            "assertion": ":95",
            "excludes": "a held-claim end reporting the claim lost",
            "status": "CARRIED"
          },
          {
            "id": "D7a",
            "source": "docstring",
            "clause": "leaves \"ready, instance, the track text\"",
            "assertion": ":105-113",
            "excludes": "the wrong state or source left in place (still `whisper`/`running`), or track_text not stored",
            "status": "CARRIED"
          },
          {
            "id": "D7b",
            "source": "docstring",
            "clause": "\"the cues as compact JSON\"",
            "assertion": ":113",
            "excludes": "default `json.dumps` separators (spaces), or partial cues left in place",
            "status": "CARRIED"
          },
          {
            "id": "D7c",
            "source": "docstring",
            "clause": "\"fetched_at and finished_at both the one given time\"",
            "assertion": ":111, :116",
            "excludes": "fetched_at left at QUEUED_AT (enqueue sets it), finished_at left NULL, or two different clocks",
            "status": "CARRIED"
          },
          {
            "id": "D7d",
            "source": "docstring",
            "clause": "\"detected_language, error, attempts, queued_at and started_at as the running job had them\"",
            "assertion": ":114-119",
            "excludes": "detected_language cleared (it was set to \"fr\" at :94), attempts reset or incremented, queued_at/started_at overwritten, a non-NULL error written; clearing error is indistinguishable because the running row's error is already NULL",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"the ready reader then returns those cues\"",
            "assertion": ":96",
            "excludes": "a row `fetch_ready_subtitles` cannot read (wrong state, bad cues_json)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "worker: real fetch found the track, then the Engine stored a different track over the running row",
            "assertion": ":140, :141, :142",
            "excludes": "(controls) a test in which the takeover never happened or the trigger records nothing",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "worker: \"nothing was transcribed and nothing past the caption list and the track was fetched\"",
            "assertion": ":146, :147",
            "excludes": "a worker that falls through to the video JSON, the media download or Whisper after the takeover",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"every claim write after an instance track takeover reports the claim lost\"",
            "assertion": ":73",
            "excludes": "any of the six returning True",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"and leaves the row byte-identical\"",
            "assertion": ":76",
            "excludes": "any byte changed",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"ending ready from the instance track while the claim holds leaves ready instance\"",
            "assertion": ":109-110",
            "excludes": "another state or source",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"with one timestamp\"",
            "assertion": ":111, :116",
            "excludes": "fetched_at \u2260 finished_at",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"and the job columns kept\"",
            "assertion": ":114-119",
            "excludes": "queued_at, started_at, attempts or detected_language overwritten",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"an instance track found after the engine took the row over writes nothing\"",
            "assertion": ":143, :144",
            "excludes": "any subtitles write or cues_json write after the takeover",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"and logs the takeover\"",
            "assertion": ":145",
            "excludes": "the takeover line missing, or other worker lines present",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_54_translate_job_handle_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four tests should fail with `AttributeError`, because `data.subtitles` defines neither opener yet:\n- Line 65, `store.open_subtitles_db(path)`. The precondition at line 63 passes first.\n- Line 90, `store.open_subtitles_db(path)`. The B1 controls at lines 85\u201386 pass first.\n- Line 117, `store.open_translate_worker_store(path, mine, 1)`. The `AttributeError` is not a `BlockingIOError`, so it gets past `pytest.raises` at line 116.\n- Line 164, `store.open_translate_worker_store(path, lock_fd, 9000)`. The controls at lines 155 and 161 pass first.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/server.py, engine/server/db/jobs/translate-worker.py and tests/active/test_internal_translate.py. All three exist, but I did not read them in full. The test under audit references none of them. A Grep over engine/ found no definition of `open_subtitles_db` or `open_translate_worker_store` anywhere. I answered the stub question from engine/server/data/subtitles.py, from the helpers the test imports from tests/active/test_subtitles.py (lines 41\u2013213), and from the test's assertion form.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. Its other helpers are imported explicitly from tests/active/test_subtitles.py, so no conftest was needed.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a missing nested path becomes a created directory | :71 | an opener that connects without making `a/b` (the control at :63 says the path is absent first) | CARRIED |\n| C1b | must_prove | missing nested path \u2192 full current schema | :73, :74, :75 | a job column, the `(state, queued_at)` index or the heartbeat table left out | CARRIED |\n| C1c | must_prove | missing nested path \u2192 WAL mode | :76 | an opener that leaves the default rollback journal | CARRIED |\n| C1d | must_prove | a B1-era file \u2192 full current schema | :97, :98, :99 | a B1 file left without the job columns, the index or the heartbeat table | CARRIED |\n| C1e | must_prove | a B1-era file \u2192 WAL mode | :100 (control :85 = `delete`) | a migration that never switches an existing rollback-journal file | CARRIED |\n| C2a | must_prove | refuses with BlockingIOError while another open file description holds the flock | :116 | no flock taken, a blocking flock (stopped by `_bounded`), or a different error raised | CARRIED |\n| C2b | must_prove | creates nothing while refused | :118, :119 | the db opened, or its directory made, before the flock is tried | CARRIED |\n| D1 | docstring | \"`open_subtitles_db` is the one store opener\" | none | nothing checks that the Engine or the worker open the store through it | UNCARRIED |\n| D2 | docstring | \"crash recovery runs only through `open_translate_worker_store`, under the worker's flock\" | :116\u2013119 (under-flock half only) | the refusal path runs no recovery; nothing rules out `open_subtitles_db` also recovering (the B1 and nested files hold no running row, so that would not show) | UNCARRIED |\n| D3 | docstring | the file's state is read back through a fresh plain connection | :72, :96, :101 | a schema seen only through the opener's own connection | CARRIED |\n| D4 | docstring | \"creates both\" `a` and `b`; fourteen columns, index, heartbeat `id, beat_at, pid`, journal `wal` | :71, :73\u201376 | each missing piece, as in C1a\u2013C1c | CARRIED |\n| D5 | docstring | \"The returned connection reads the empty heartbeat\" | :67 | returning a connection that was not migrated (raises: no such table) | CARRIED |\n| D6 | docstring | B1 file: rollback journal with two ready/instance rows (precondition) | :85, :86 | a fixture that is already WAL or has no rows, which would make C1e/D8 trivially true | CARRIED |\n| D7 | docstring | B1 file: \"the same four facts hold afterwards\" | :97\u2013100 | as C1d/C1e | CARRIED |\n| D8 | docstring | both connections read the two old cue lists unchanged | :92, :103 | a migration that recreates the table or loses or rewrites rows | CARRIED |\n| D9 | docstring | C2 refusal: BlockingIOError, and neither the file nor `sub` exists | :116, :118, :119 | as C2a/C2b | CARRIED |\n| D10 | docstring | \"Each call is bounded by an alarm, so an opener that blocks \u2026 fails instead of hanging\" | :116, :123 (`_bounded`, :38) | an opener without LOCK_NB hangs forever instead of failing | CARRIED |\n| D11 | docstring | control: once the holder is closed, the same call returns (0, 0) and the file exists | :126, :127 | a refusal that is unconditional, so the absence at :118 is not caused by the lock | CARRIED |\n| D12 | docstring | a third description is refused, because the opener took the lock on `mine` and kept it | :130\u2013131 | an opener that releases the flock after migrating | CARRIED |\n| D13 | docstring | recovery returns (1, 0) at 9000 and requeues a running job with attempts 1 | :166, :167 | a recovery that fails on the first find, or that resets or spends attempts | CARRIED |\n| D14 | docstring | claimed again: failed with the text at 9500 beside two first-time jobs requeued, returns (2, 1) | :175\u2013178 | failing every running row, or requeuing the twice-run one | CARRIED |\n| D15 | docstring | \"The claims are read through the handle's attributes\" | :161, :170 | a claim that picks the wrong row or attempts value, letting the controls pass for the wrong reason | CARRIED |\n| D16 | docstring | \"a queued row and a ready row are untouched\" | :183 | a recovery UPDATE not limited to `state = 'running'` | CARRIED |\n| N1 | name | test 1: \"creates a missing nested directory and the full schema in wal\" | :71, :73\u201376 | as C1a\u2013C1c | CARRIED |\n| N2 | name | test 2: \"turns a b1 file into the full schema in wal and keeps its old cues\" | :97\u2013100, :92, :103 | as C1d, C1e, D8 | CARRIED |\n| N3 | name | test 3: \"refuses while another description holds the flock and creates nothing\" | :116, :118, :119 | as C2a/C2b | CARRIED |\n| N4 | name | test 4: \"requeues a running job once and fails it when found running a second time\" | :167, :176 | as D13/D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:1\n   D1 is UNCARRIED. The module docstring says `open_subtitles_db` \"is the one store opener\". No test opens the store through `engine/server/api/server.py` or `engine/server/db/jobs/translate-worker.py`, though both are listed as edited. Either assert this at a seam those files go through, or narrow the sentence. This is a docstring row, not a `must_prove` row, so it does not block.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:1\n   D2 is UNCARRIED for its \"only through\" half. The refusal at :116\u2013119 shows nothing runs without the flock. But no test opens a file holding a `running` row through `open_subtitles_db` and checks that the row stays `running`. So an implementation where the Engine's opener also recovers still passes. This is a docstring row, so it does not block.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:61\n   `open_subtitles_db` is only tested on success, at :61 and :79. Its expected failure mode has no test, for example a parent that is a regular file, or a path that cannot be opened.\n4. No rule covers this; noted for the record \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:53\n   \"Full current schema\" is checked through column names (:73), index columns (:74) and heartbeat column names (:75). Declarations are not compared: the primary key, `attempts NOT NULL DEFAULT 0`, and the heartbeat's `CHECK (id = 1)`. The test still rules out the clause's main wrong implementations (a missing column, index or table), so C1b and C1d stay CARRIED.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `open_subtitles_db` and `open_translate_worker_store` do not exist in `engine/server/data/subtitles.py` or anywhere else in `engine/server`. The test expects this: line 26 says each test should fail at its own call. Because there is no definition, I could not check the signatures and return shapes the test assumes against the code: `(path)`, `(path, fd, now)`, and `(conn, (requeued, failed))`. Bounds were judged from the test, the existing `recover_translate_jobs` / `ensure_subtitles_schema`, and the flock sequence in `translate-worker.py` `run` (:517\u2013536).\n2. The phase's `<checkpoint>` text was not supplied. So I could not tell whether it names a seam above the data layer that this checkpoint should also enter, such as the worker's `run` exiting 6 on a held lock. The surface pass was judged against `must_prove` alone, and its clauses are all about the two openers at the data layer.\n3. `tests/active/test_internal_translate.py` is in `code_under_test` but this test never touches it, so I did not read it.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nAll four tests should fail with `AttributeError`, because `data.subtitles` defines neither opener yet:\n- Line 65, `store.open_subtitles_db(path)`. The precondition at line 63 passes first.\n- Line 90, `store.open_subtitles_db(path)`. The B1 controls at lines 85\u201386 pass first.\n- Line 117, `store.open_translate_worker_store(path, mine, 1)`. The `AttributeError` is not a `BlockingIOError`, so it gets past `pytest.raises` at line 116.\n- Line 164, `store.open_translate_worker_store(path, lock_fd, 9000)`. The controls at lines 155 and 161 pass first.\n\nNOT ASSESSED\n1. `code_under_test` lists engine/server/api/server.py, engine/server/db/jobs/translate-worker.py and tests/active/test_internal_translate.py. All three exist, but I did not read them in full. The test under audit references none of them. A Grep over engine/ found no definition of `open_subtitles_db` or `open_translate_worker_store` anywhere. I answered the stub question from engine/server/data/subtitles.py, from the helpers the test imports from tests/active/test_subtitles.py (lines 41\u2013213), and from the test's assertion form.\n2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. Its other helpers are imported explicitly from tests/active/test_subtitles.py, so no conftest was needed.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | a missing nested path becomes a created directory | :71 | an opener that connects without making `a/b` (the control at :63 says the path is absent first) | CARRIED |\n| C1b | must_prove | missing nested path \u2192 full current schema | :73, :74, :75 | a job column, the `(state, queued_at)` index or the heartbeat table left out | CARRIED |\n| C1c | must_prove | missing nested path \u2192 WAL mode | :76 | an opener that leaves the default rollback journal | CARRIED |\n| C1d | must_prove | a B1-era file \u2192 full current schema | :97, :98, :99 | a B1 file left without the job columns, the index or the heartbeat table | CARRIED |\n| C1e | must_prove | a B1-era file \u2192 WAL mode | :100 (control :85 = `delete`) | a migration that never switches an existing rollback-journal file | CARRIED |\n| C2a | must_prove | refuses with BlockingIOError while another open file description holds the flock | :116 | no flock taken, a blocking flock (stopped by `_bounded`), or a different error raised | CARRIED |\n| C2b | must_prove | creates nothing while refused | :118, :119 | the db opened, or its directory made, before the flock is tried | CARRIED |\n| D1 | docstring | \"`open_subtitles_db` is the one store opener\" | none | nothing checks that the Engine or the worker open the store through it | UNCARRIED |\n| D2 | docstring | \"crash recovery runs only through `open_translate_worker_store`, under the worker's flock\" | :116\u2013119 (under-flock half only) | the refusal path runs no recovery; nothing rules out `open_subtitles_db` also recovering (the B1 and nested files hold no running row, so that would not show) | UNCARRIED |\n| D3 | docstring | the file's state is read back through a fresh plain connection | :72, :96, :101 | a schema seen only through the opener's own connection | CARRIED |\n| D4 | docstring | \"creates both\" `a` and `b`; fourteen columns, index, heartbeat `id, beat_at, pid`, journal `wal` | :71, :73\u201376 | each missing piece, as in C1a\u2013C1c | CARRIED |\n| D5 | docstring | \"The returned connection reads the empty heartbeat\" | :67 | returning a connection that was not migrated (raises: no such table) | CARRIED |\n| D6 | docstring | B1 file: rollback journal with two ready/instance rows (precondition) | :85, :86 | a fixture that is already WAL or has no rows, which would make C1e/D8 trivially true | CARRIED |\n| D7 | docstring | B1 file: \"the same four facts hold afterwards\" | :97\u2013100 | as C1d/C1e | CARRIED |\n| D8 | docstring | both connections read the two old cue lists unchanged | :92, :103 | a migration that recreates the table or loses or rewrites rows | CARRIED |\n| D9 | docstring | C2 refusal: BlockingIOError, and neither the file nor `sub` exists | :116, :118, :119 | as C2a/C2b | CARRIED |\n| D10 | docstring | \"Each call is bounded by an alarm, so an opener that blocks \u2026 fails instead of hanging\" | :116, :123 (`_bounded`, :38) | an opener without LOCK_NB hangs forever instead of failing | CARRIED |\n| D11 | docstring | control: once the holder is closed, the same call returns (0, 0) and the file exists | :126, :127 | a refusal that is unconditional, so the absence at :118 is not caused by the lock | CARRIED |\n| D12 | docstring | a third description is refused, because the opener took the lock on `mine` and kept it | :130\u2013131 | an opener that releases the flock after migrating | CARRIED |\n| D13 | docstring | recovery returns (1, 0) at 9000 and requeues a running job with attempts 1 | :166, :167 | a recovery that fails on the first find, or that resets or spends attempts | CARRIED |\n| D14 | docstring | claimed again: failed with the text at 9500 beside two first-time jobs requeued, returns (2, 1) | :175\u2013178 | failing every running row, or requeuing the twice-run one | CARRIED |\n| D15 | docstring | \"The claims are read through the handle's attributes\" | :161, :170 | a claim that picks the wrong row or attempts value, letting the controls pass for the wrong reason | CARRIED |\n| D16 | docstring | \"a queued row and a ready row are untouched\" | :183 | a recovery UPDATE not limited to `state = 'running'` | CARRIED |\n| N1 | name | test 1: \"creates a missing nested directory and the full schema in wal\" | :71, :73\u201376 | as C1a\u2013C1c | CARRIED |\n| N2 | name | test 2: \"turns a b1 file into the full schema in wal and keeps its old cues\" | :97\u2013100, :92, :103 | as C1d, C1e, D8 | CARRIED |\n| N3 | name | test 3: \"refuses while another description holds the flock and creates nothing\" | :116, :118, :119 | as C2a/C2b | CARRIED |\n| N4 | name | test 4: \"requeues a running job once and fails it when found running a second time\" | :167, :176 | as D13/D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:1\n   D1 is UNCARRIED. The module docstring says `open_subtitles_db` \"is the one store opener\". No test opens the store through `engine/server/api/server.py` or `engine/server/db/jobs/translate-worker.py`, though both are listed as edited. Either assert this at a seam those files go through, or narrow the sentence. This is a docstring row, not a `must_prove` row, so it does not block.\n2. whole-claim (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:1\n   D2 is UNCARRIED for its \"only through\" half. The refusal at :116\u2013119 shows nothing runs without the flock. But no test opens a file holding a `running` row through `open_subtitles_db` and checks that the row stays `running`. So an implementation where the Engine's opener also recovers still passes. This is a docstring row, so it does not block.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:61\n   `open_subtitles_db` is only tested on success, at :61 and :79. Its expected failure mode has no test, for example a parent that is a regular file, or a path that cannot be opened.\n4. No rule covers this; noted for the record \u2014 tests/tmp/test_54_translate_job_handle_phase2.py:53\n   \"Full current schema\" is checked through column names (:73), index columns (:74) and heartbeat column names (:75). Declarations are not compared: the primary key, `attempts NOT NULL DEFAULT 0`, and the heartbeat's `CHECK (id = 1)`. The test still rules out the clause's main wrong implementations (a missing column, index or table), so C1b and C1d stay CARRIED.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `open_subtitles_db` and `open_translate_worker_store` do not exist in `engine/server/data/subtitles.py` or anywhere else in `engine/server`. The test expects this: line 26 says each test should fail at its own call. Because there is no definition, I could not check the signatures and return shapes the test assumes against the code: `(path)`, `(path, fd, now)`, and `(conn, (requeued, failed))`. Bounds were judged from the test, the existing `recover_translate_jobs` / `ensure_subtitles_schema`, and the flock sequence in `translate-worker.py` `run` (:517\u2013536).\n2. The phase's `<checkpoint>` text was not supplied. So I could not tell whether it names a seam above the data layer that this checkpoint should also enter, such as the worker's `run` exiting 6 on a held lock. The surface pass was judged against `must_prove` alone, and its clauses are all about the two openers at the data layer.\n3. `tests/active/test_internal_translate.py` is in `code_under_test` but this test never touches it, so I did not read it.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "a missing nested path becomes a created directory",
            "assertion": ":71",
            "excludes": "an opener that connects without making `a/b` (the control at :63 says the path is absent first)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "missing nested path \u2192 full current schema",
            "assertion": ":73, :74, :75",
            "excludes": "a job column, the `(state, queued_at)` index or the heartbeat table left out",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "missing nested path \u2192 WAL mode",
            "assertion": ":76",
            "excludes": "an opener that leaves the default rollback journal",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "a B1-era file \u2192 full current schema",
            "assertion": ":97, :98, :99",
            "excludes": "a B1 file left without the job columns, the index or the heartbeat table",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "a B1-era file \u2192 WAL mode",
            "assertion": ":100 (control :85 = `delete`)",
            "excludes": "a migration that never switches an existing rollback-journal file",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "refuses with BlockingIOError while another open file description holds the flock",
            "assertion": ":116",
            "excludes": "no flock taken, a blocking flock (stopped by `_bounded`), or a different error raised",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "creates nothing while refused",
            "assertion": ":118, :119",
            "excludes": "the db opened, or its directory made, before the flock is tried",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"`open_subtitles_db` is the one store opener\"",
            "assertion": "none",
            "excludes": "nothing checks that the Engine or the worker open the store through it",
            "status": "UNCARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"crash recovery runs only through `open_translate_worker_store`, under the worker's flock\"",
            "assertion": ":116\u2013119 (under-flock half only)",
            "excludes": "the refusal path runs no recovery; nothing rules out `open_subtitles_db` also recovering (the B1 and nested files hold no running row, so that would not show)",
            "status": "UNCARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "the file's state is read back through a fresh plain connection",
            "assertion": ":72, :96, :101",
            "excludes": "a schema seen only through the opener's own connection",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"creates both\" `a` and `b`; fourteen columns, index, heartbeat `id, beat_at, pid`, journal `wal`",
            "assertion": ":71, :73\u201376",
            "excludes": "each missing piece, as in C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"The returned connection reads the empty heartbeat\"",
            "assertion": ":67",
            "excludes": "returning a connection that was not migrated (raises: no such table)",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "B1 file: rollback journal with two ready/instance rows (precondition)",
            "assertion": ":85, :86",
            "excludes": "a fixture that is already WAL or has no rows, which would make C1e/D8 trivially true",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "B1 file: \"the same four facts hold afterwards\"",
            "assertion": ":97\u2013100",
            "excludes": "as C1d/C1e",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "both connections read the two old cue lists unchanged",
            "assertion": ":92, :103",
            "excludes": "a migration that recreates the table or loses or rewrites rows",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "C2 refusal: BlockingIOError, and neither the file nor `sub` exists",
            "assertion": ":116, :118, :119",
            "excludes": "as C2a/C2b",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"Each call is bounded by an alarm, so an opener that blocks \u2026 fails instead of hanging\"",
            "assertion": ":116, :123 (`_bounded`, :38)",
            "excludes": "an opener without LOCK_NB hangs forever instead of failing",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "control: once the holder is closed, the same call returns (0, 0) and the file exists",
            "assertion": ":126, :127",
            "excludes": "a refusal that is unconditional, so the absence at :118 is not caused by the lock",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "a third description is refused, because the opener took the lock on `mine` and kept it",
            "assertion": ":130\u2013131",
            "excludes": "an opener that releases the flock after migrating",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "recovery returns (1, 0) at 9000 and requeues a running job with attempts 1",
            "assertion": ":166, :167",
            "excludes": "a recovery that fails on the first find, or that resets or spends attempts",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "claimed again: failed with the text at 9500 beside two first-time jobs requeued, returns (2, 1)",
            "assertion": ":175\u2013178",
            "excludes": "failing every running row, or requeuing the twice-run one",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"The claims are read through the handle's attributes\"",
            "assertion": ":161, :170",
            "excludes": "a claim that picks the wrong row or attempts value, letting the controls pass for the wrong reason",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"a queued row and a ready row are untouched\"",
            "assertion": ":183",
            "excludes": "a recovery UPDATE not limited to `state = 'running'`",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "test 1: \"creates a missing nested directory and the full schema in wal\"",
            "assertion": ":71, :73\u201376",
            "excludes": "as C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "test 2: \"turns a b1 file into the full schema in wal and keeps its old cues\"",
            "assertion": ":97\u2013100, :92, :103",
            "excludes": "as C1d, C1e, D8",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "test 3: \"refuses while another description holds the flock and creates nothing\"",
            "assertion": ":116, :118, :119",
            "excludes": "as C2a/C2b",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "test 4: \"requeues a running job once and fails it when found running a second time\"",
            "assertion": ":167, :176",
            "excludes": "as D13/D14",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  }
}
```
dev-flow:state -->

## 2026-10-04 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `c841889bf812343a114aacd31d797d13bd0d2ad9` at 2026-10-04T12:33:14-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 65 test groups (64 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 1 - Gather requirements

Approved by the operator.

### requirements

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

### conflicts

Brief "Behaviour stays the same throughout" vs brief AC "When the claim was lost, [ending ready from an instance track] changes nothing": today the worker's unconditional upsert plus `mark_translate_finished` overwrites the Engine's ready row and stamps `finished_at` even after a takeover, because the Engine's upsert leaves `started_at` untouched. The operator approved the AC's behaviour, with the worker taking its takeover path.
Brief "leaves exactly today's row" vs today's code setting `fetched_at` and `finished_at` from two separate `now_ms()` calls: the operator approved one timestamp for both.
Brief Problem lists the tests' `SimpleNamespace` server fake as an issue, but Desired behaviour and the ACs ask for no change to it: the operator confirmed it stays.

## 2026-10-04 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

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

### conflicts

none

## 2026-10-04 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


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


### docs_checklist

<doc path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md">
- **Start-up Order step 5 (line 72):** replace `ensure_subtitles_schema` plus recovery with the lock-checked store opener: flock re-assert, mkdir, open, migrate, recover, then log the counts.
- **Job Pipeline step 2 (line 90):** the instance track is stored ready/instance only while the claim holds; otherwise the job is taken over and nothing is written.
- **New text:** the claim handle (`TranslateJob`), its six methods, each returning False after a takeover.
- **Enqueue (line 49):** optionally name the shared `resolve_translatable_video`.
- **Crash bullet (line 147):** recovery is reachable only through the lock-checked opener.
- **§ Takeover (line 151):** touch only if wording requires; it names no removed function.
</doc>
<doc path="engine/server/README.md">
- **§ "Translate worker and its store contract" (lines 29-36):**
  - `open_subtitles_db` as the single opener;
  - `claim_translate_job` returning the `TranslateJob` handle with its claim-conditional methods;
  - `open_translate_worker_store`, with recovery only under the flock.
- **Line 17:** replace `resolve_video_row` with `resolve_translatable_video`. The threshold and denylist still apply.
- **Line 19:** mention the closed-store info log line.
- **Notes, line 45:** the Engine start now also creates the parent directory of `DEFAULT_SUBTITLES_DB_PATH`.
</doc>
<doc path="engine/server/data/subtitles.py">
Module docstring and docstrings to update:
- `claim_translate_job` (returns a handle);
- `_update_claim` and the handle (name the real takeover writer, not "B1's route");
- `store_ready_subtitles` (shared encoder);
- the two new openers (flock re-assert semantics, including that it acquires the lock on an unlocked fd);
- `_recover_translate_jobs`.
</doc>
<doc path="engine/server/api/handlers/internal_translate.py">
- **Module docstring:** the shared resolve, and the closed-store log line.
- **`VIDEO_NOT_FOUND` comment (line 34):** it no longer comes from `resolve_video_row`.
- **Docstrings:** `_resolve_translate_key`, `_store_cues`, the new `_subtitles_store` and `resolve_translatable_video`.
</doc>
<doc path="engine/server/db/jobs/translate-worker.py">
- **Module docstring (lines 4, 6, 8):** the shared resolve, the handle, and the lock-checked opener in the start order.
- **`JobTakenOver` docstring:** the real writer.
- **`run_job`, `generate` and `command_run` docstrings:** update to match.
- **Comment at line 35:** about what `api/` is on the path for.
</doc>
<doc path="engine/server/api/server.py">
The comment at line 370 ("After the mkdir above (the default lives in the same directory)…") goes partly stale, because the opener creates its own parent. Keep the `prepare_trending_override` ordering reason.
</doc>
<doc path="CONTEXT.md">
Optional: in "Instance caption track" (line 19), the worker stores the track only while its claim holds. "Claim" (line 22) already matches.
</doc>
<doc path="tests/active/test_subtitles.py">
Module docstring lines 12, 14 and 17 name removed or renamed functions. Add bullets for the new handle, opener and flock tests.
</doc>
<doc path="tests/active/test_translate_worker.py">
The docstring's `run_job(conn, job, …)` signature (line 10) becomes `run_job(job, …)`.
</doc>
<doc path="tests/active/test_internal_translate.py">
Docstring line 19 and the `_subtitles_db` helper docstring say the store is opened "as server.py does" with `connect`+`ensure`. Reword, or switch the helper to `open_subtitles_db`.
</doc>


### highest_risk

1. **`translate-worker.py` `generate` plus the new instance-track handle method in `subtitles.py`.** This is the one approved behaviour change. One conditional UPDATE must set ready, source=instance, `track_text`, NaN-allowing compact `cues_json` and `fetched_at` = `finished_at` from one timestamp, leave every other job column alone, and raise `JobTakenOver` on False. No existing test drives `generate` through a lost claim at this point.
2. **`subtitles.py` `open_translate_worker_store` and `translate-worker.py` `command_run`.** The flock re-assert has to come before any mkdir or open. The plan says nothing about closing the connection when recovery raises. `command_run`'s try/finally has to be rebuilt around a connection that now exists only after the opener returns. A mistake here either leaks the connection, raises NameError in `finally`, or writes to the store without holding the lock.
3. **`translate-worker.py` `serve` (line 495) and `run_job` call sites, and `internal_translate.py` `_resolve_translate_key` with the new `resolve_translatable_video`.** `serve` reads `job["..."]` by subscript, which the plan does not list. On a handle that raises TypeError, outside any handler, and kills the worker. The merged resolve has to keep the fetch-row, then denylist, order, its exact refusal and OperationalError texts, and 404 parity, because the route tests, the worker tests and the stall test pin these byte for byte.

## 2026-10-04 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: none.

I checked the inventory against `subtitles.py`, `internal_translate.py`, `translate-worker.py`, `server.py:340-384`, `handlers/video.py` (`fetch_video_row`, `resolve_video_row`), `data/moderation.py`, the three active test files and the two docs. Every entry matches the code at the lines it cites. A repository-wide grep for the removed and renamed names finds them only in the three code files, the three active tests, the two docs, the plans and issues, `delete_me/` and `tests/tmp/`. There are no unknown callers. The plan holds as written. The inventory already names its two real weak points: `serve`'s subscripted log line at `translate-worker.py:495`, which the plan does not name, and a connection that is never closed if recovery raises inside `open_translate_worker_store`. Neither conflicts with the plan; both are build details. No test double is widened by the plan, so nothing needs a double-specific recommendation.
<question id="1">
Yes. Five points were checked against the code. (a) Every conditional write already goes through `_update_claim` with `WHERE {_KEY} AND state = 'running' AND started_at = ?` (`subtitles.py:161`). Holding the claim's fields in the handle changes no SQL. (b) The new instance-track end is one UPDATE through that same WHERE. After a `store_ready_subtitles` takeover it matches nothing, because the upsert sets state `ready`. This replaces today's unconditional upsert at `translate-worker.py:407` and the `mark_translate_finished` stamp at `:408`, which matched on `state='ready' AND started_at`. (c) `list_active_denied_hosts` takes no lock (`moderation.py:137`), so merging the route's two `server.db_lock` holds (`internal_translate.py:203` via `resolve_video_row`, and `:210`) into one hold cannot deadlock on the plain `threading.Lock` (`server.py:292`, and the fake at `test_internal_translate.py:429`). (d) `fetch_video_row` raises before any denylist read (`video.py:36`). The worker's OperationalError classification in `generate` (`:396-400`) and the zero-byte and drop-column tests (`test_translate_worker.py:1081`) therefore still see the same text. (e) `command_run` opens the lock `O_RDONLY` (`:519`) and flocks that descriptor. Re-asserting `LOCK_EX|LOCK_NB` on the same descriptor is a no-op, so the opener succeeds in the service and refuses a separately opened description.
</question>
<question id="2">
- **Lost claim on the instance-track end:** the worker now writes nothing; today it overwrites the Engine's row (the approved change).
- **One timestamp:** `fetched_at` and `finished_at` come from one value; today they come from two `now_ms()` calls.
- **Engine start:** `server.py` now creates a missing parent directory for a custom `--subtitles-db`.
- **Route resolve:** one `db_lock` hold instead of two. The window between the row lookup and the denylist read is gone.
- **Closed store:** the route logs a new info line when the store is closed.
- **Signatures:** `run_job` loses its connection argument. `generate` and `translate_audio` take the handle in place of `conn` and `claim`. The claim result is no longer subscriptable.
- **Recovery:** reachable only through the lock-checked opener.
- **Stale probes:** the probes in `delete_me/` and `tests/tmp/` break if run.
- **Wider test run:** `server.py` is mapped in `tests/config.json` by five Engine-start suites, so the build's targeted runs include `test_similar`, `test_server_config`, `test_internal_events` and `test_random_cache`.
</question>
<question id="3">
These are all already in the inventory; I confirmed each in the files.
- **`serve`:** `translate-worker.py:495` must switch from `job["video_id"]`, `job["instance_domain"]` and `job["attempts"]` to attributes. Otherwise every claim raises TypeError outside `run_job`'s handlers and the service dies.
- **Test callers of the old shapes:** `Rig.claim`/`Rig.run` (`test_translate_worker.py:544`, `:554`), the fetch-reason test (`:925`), `WORKER_SCRIPT` in `test_subtitles.py:119-141`, which is a string invisible to import greps, and the claim test (`:340`). Also the recovery test (`:347-372`), the state test (`:388-395`), and `_claimed`/`_seed` plus the running and failed sequences (`test_internal_translate.py:607-629`, `:755-792`).
- **`command_run`:** its try/finally must be restructured so `conn` is bound before the `finally` that closes it.
- **Recovery failure:** `open_translate_worker_store` must close its connection if recovery raises.
- **`resolve_video_row`:** it must stay in `video.py`, because `/api/video` still calls it.
- **Encoding:** the instance-track encoder must stay byte-identical to `store_ready_subtitles:114` (NaN allowed, compact). `test_internal_translate.py:502` pins the compact form.
</question>
<question id="4">
- **Lost claim:** a worker that finds an instance track after its claim was taken over now leaves the Engine's row exactly as the Engine wrote it, and logs `taken over by the instance track`. Today it overwrites `track_text`, `cues_json` and `fetched_at` with its own fetch, and then stamps `finished_at`.
- **Successful instance-track end:** `fetched_at == finished_at`.
- **Engine start:** with a custom subtitles path in a missing directory, the Engine now starts instead of failing.
- **Closed store:** a track store against a closed store now logs one info line.
- **Unchanged:** every HTTP response, worker stdout line, exit code and stored error text is unchanged, including the worker's `not in whitelist` for an empty host.
</question>


New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Close the connection in `open_translate_worker_store` when `_recover_translate_jobs` raises: a `try`/`except BaseException: conn.close(); raise` around the recovery call, the same pattern the plan already uses for a failed migration in `open_subtitles_db`. Then, in `command_run`, start the try/finally that joins the beat and closes `conn` only after the opener returns. What it changes: today `command_run`'s `finally` (`translate-worker.py:541-545`) closes the connection when recovery fails; without this, the connection leaks on that path. Cost: about three lines and no new test. The process exits right after anyway, so this is about keeping the contract tidy, not about correctness.

2. Add one worker-level test that drives `generate` through a takeover that lands before the instance-track end. Patch the worker module's `fetch_instance_track` so that it first runs `store_ready_subtitles` on a second connection with different cues, then returns a track. Assert three things: the row equals the Engine's write byte for byte, `run_job` returns False, and the `taken over by the instance track` line is logged. What it changes: it pins the one approved behaviour change at the worker level. Today nothing drives that path; the plan's store test only covers the method on its own. Cost: one test of about 20 lines in `test_translate_worker.py`, reusing `rig` and the pattern of the existing takeover test at `:1033`.

3. Add `engine/server/README.md:17` to the doc pass. It still says the route resolves through `resolve_video_row`, which stops being true. Cost: one sentence. The alternative is a factually stale API doc.

4. Before building, run the three active files once (`test_subtitles.py`, `test_internal_translate.py`, `test_translate_worker.py`) plus the four Engine-start suites that `server.py` pulls in. What it changes: a red test that predates the build gets recognised as baseline, not mistaken for a regression; the plan already lists the unverified baseline as a risk. Cost: one test run. `test_translate_worker.py` needs ffmpeg on PATH, and its held-lock whitelist case waits out a 30 s busy timeout.

5. Test doubles: no action. The plan widens none. The route's `SimpleNamespace` fake already carries `db`, `db_lock`, `video_error_threshold`, `subtitles_db` and `subtitles_db_lock` (`test_internal_translate.py:429`). The `_recording` `resolve_video` stand-ins keep their 4-argument signature. The `cues_writes` trigger (`test_translate_worker.py:512`) already records an instance-track write today, because the upsert's DO UPDATE fires `AFTER UPDATE OF cues_json`. The new conditional UPDATE is recorded the same way, so none of its expected sequences change.

## 2026-10-04 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

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

## 2026-10-04 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Claim handle [code]

**Files touched.** engine/server/data/subtitles.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), tests/active/test_subtitles.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/active/test_translate_worker.py (EDITED)

**Checkpoint.** Seam 1 is the store module, entered at rung 1 in tests/active/test_subtitles.py with its existing `_snapshot` harness. A parametrised test runs over the six TranslateJob methods (running cues, ready, already_english, failed, requeue, ready from instance). For each it enqueues, claims, takes the row over with `store_ready_subtitles(..., "instance", ...)` and snapshots, then asserts the method returns `False` and the snapshot is unchanged. A control runs the same method on a fresh claim with no takeover and asserts `True`, which shows the `False` comes from the takeover and not from a broken UPDATE. A second store test covers the held-claim control: `end_ready_from_instance` returns True and leaves state `ready`, source `instance`, the track_text, compact cues_json (no space) and `fetched_at == finished_at`, with detected_language, error, attempts, queued_at and started_at unchanged. Seam 2 is the worker's `run_job`/`generate`, entered through the existing `Rig` harness in tests/active/test_translate_worker.py with a served English listing and track. `fetch_instance_track` is wrapped so that, after the real fetch, it runs `store_ready_subtitles` with the Engine's track and snapshots the row. The test asserts the row equals that snapshot (Engine's track_text and cues kept), the `taken over by the instance track video_id=v-1 host=…` log line is present, no `failed` line is present and the runner made 0 transcribes. Today's code fails this because the upsert overwrites track_text. The existing English-instance-track test at :1016 stays green unchanged.

**Intent.** `claim_translate_job` in engine/server/data/subtitles.py returns a TranslateJob handle bound to its connection, and the worker writes every claim-conditional change through it, so once the Engine's instance-track store has replaced a running row, no handle write (including the worker's new end-ready-from-instance-track) changes that row.

- C1 - After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical.
- C2 - When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged.

**Outcome.** _pending_

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


Needs coordination: none

Rationale: There are four phases, each proven by its own checkpoint, and the operator approved the split as presented. Phase 1 has to carry the store handle and the worker rewiring together: `claim_translate_job`'s new return value and the deletion of the five per-claim functions and `mark_translate_finished` break the worker and its tests in the same commit, so splitting them would leave the suite red between phases. Its two clauses are the store-level lost-claim no-op and the one approved behaviour change seen end to end through `generate`. The held-claim instance end goes into the checkpoint as a control, not a third clause. Phase 2 (openers) is independent of the handle except for the recovery test's attribute reads, which phase 1 already rewrites, so it can follow cleanly. Phase 3 (route store helper) and phase 4 (issue 57's shared resolve) both edit internal_translate.py but are unrelated behaviours. They stay separate phases with one clause each, so neither checkpoint carries a compound claim. There is no prose phase: TRANSLATE_WORKER.md, the README, the module docs and CONTEXT.md are documentation that Step 9 updates. Known baseline risk: the three active test files were not freshly run at baseline, so a red result that was already there would show up in phase 1 and look like a regression. The phase 1 author should run the files first.

## 2026-10-04 - Step 7 - Phase 1 (Claim handle) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`claim_translate_job` in engine/server/data/subtitles.py returns a TranslateJob handle bound to its connection, and the worker writes every claim-conditional change through it, so once the Engine's instance-track store has replaced a running row, no handle write (including the worker's new end-ready-from-instance-track) changes that row.

- C1 - After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical.
- C2 - When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged.

must_prove:
- C1 - After a `store_ready_subtitles` takeover, each of the six TranslateJob methods returns False and leaves the row byte-identical.
- C2 - When the worker finds an instance track after the Engine took the row over, `generate` writes nothing and the takeover is logged.

## 2026-10-04 - Step 7 - Phase 1 (Claim handle) - self-check (audit round 1, send-back 0)

`tests/tmp/test_54_translate_job_handle_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_54_translate_job_handle_phase1.py:73 — `write(job) is False`, parametrised over all six handle methods (running cues, ready, already_english, failed, requeue, ready from instance). It runs after `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the claimed running row. The control at :71 confirms the Engine's row is in place. - expected: False for each of the six methods. The current run is red at exactly this line in all six cases with `AttributeError: 'sqlite3.Row' object has no attribute 'write_running_cues'` (and likewise `end_ready`, `end_already_english`, `end_failed`, `requeue`, `end_ready_from_instance`): today's `claim_translate_job` returns a `sqlite3.Row`, not a handle. The probe shows today's five per-claim functions on the same takeover each return False (`running cues False True` … `requeue False True`), which is the contract the methods take over. - excludes: A method whose UPDATE leaves out `state = 'running' AND started_at = ?` (for example `end_ready_from_instance` written as the old `store_ready_subtitles` upsert plus an unconditional stamp, or any SET matched on the key alone) matches the Engine's row and returns True. A method that never reports, or always returns True, also fails here.
- C1 - tests/tmp/test_54_translate_job_handle_phase1.py:76 — `_snapshot(path) == taken`: every column of every row, rowid included, as quoted SQL literals, reads the same after the write as after the takeover. It is armed by the held-claim controls at :82 and :85, which show the same write on a fresh claim returns True and changes the snapshot. - expected: Equal: the Engine's row as it landed, i.e. state ready, source instance, fetched_at 8000, the Engine's track_text, cues_json `[{"start":5.0,"end":6.0,"text":"Engine"}]`, queued_at 1000, started_at 2000, finished_at NULL, error NULL, detected_language NULL, attempts 1. These are the probe's observed takeover snapshot values. Not yet reached in the current run, because :73 fails first on the missing method. - excludes: An instance-track end that keeps today's pair (`store_ready_subtitles`, then `mark_translate_finished`) rewrites track_text, cues_json and fetched_at, and stamps finished_at. The probe saw `mark_translate_finished` alone turn finished_at NULL into 9000 on the taken-over row. A method that writes some column unconditionally and reports False anyway (a two-statement write where only the second is conditional) also changes the snapshot.
- C2 - tests/tmp/test_54_translate_job_handle_phase1.py:143 — `_snapshot(rig.subtitles) == seen["taken"]` after `run_job`. Here `fetch_instance_track` is wrapped so the real fetch finds the English track (control :140) and the Engine then stores its own different track ready/instance over the running row (control :141). - expected: Equal to the snapshot taken right after the Engine's store: fetched_at 1700000000000, track_text `WEBVTT\n\n00:05.000 --> 00:06.000\nEngine\n`, cues_json `[{"start":5.0,"end":6.0,"text":"Engine"}]`, finished_at NULL. The current run is red at exactly this line: the actual row has the worker's track (`WEBVTT\n\n00:03.000 --> 00:04.000\n<i>World</i>…`), its cues `[{"start":1.0,"end":2.5,"text":"Hello"},{"start":3.0,"end":4.0,"text":"World"}]`, and fetched_at = finished_at = 1791132912229. - excludes: Today's `generate` (store_ready_subtitles + mark_translate_finished) overwrites the Engine's row with the worker's track and stamps finished_at, as the run showed. So does a `generate` that calls the new conditional end but ignores its False and then calls the old upsert or another unconditional write.
- C2 - tests/tmp/test_54_translate_job_handle_phase1.py:144 — `rig.cues_writes() == seen["writes"]`: the trigger table recording every cues_json write holds nothing past the Engine's own write. The control at :142 shows the trigger records the Engine's upsert as `[ENGINE_CUES_JSON]`, so it would record a worker upsert too. - expected: `['[{"start":5.0,"end":6.0,"text":"Engine"}]']` only. The probe of today's code saw a second entry, `[{"start":1.0,"end":2.5,"text":"Hello"},{"start":3.0,"end":4.0,"text":"World"}]`, after the takeover. - excludes: A worker that writes the instance cues and then puts the Engine's value back, or writes the same bytes again, leaves the final snapshot looking right but adds a trigger entry. Today's unconditional upsert adds one, as the probe observed.
- C2 - tests/tmp/test_54_translate_job_handle_phase1.py:145 — the worker's `[translate-worker]` log lines are exactly `[TAKEN_OVER]` = `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`. - expected: Exactly that one line. The text was observed in probe_54_phase1_takeover_log.py, where today's `JobTakenOver` path (reached by a mid-job takeover) logged `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`. The route's `[translate] instance fetch failed…` line in the same run is excluded by the prefix filter. Today's instance path logs `[translate-worker] job ready from the instance track video_id=v-1 host=peer.example` instead (observed in both the checkpoint run and the probe). - excludes: A `generate` that ignores the False from the instance-track end logs `job ready from the instance track`. One that maps the lost claim to `JobFailed` or a generic exception logs `job failed …` or `job error …` (and writes a failed end, which :143 also catches). One that falls through to transcription logs a later line.

<assertions>
tests/tmp/test_54_translate_job_handle_phase1.py:71 - control, for each of the six handle methods (parametrised: running cues, ready, already_english, failed, requeue, ready from instance): on a fresh claim with no takeover the method returns True. Excludes a method that always returns False. Supports C1.
tests/tmp/test_54_translate_job_handle_phase1.py:74 - control, for each method: on that fresh claim the whole-table `_snapshot` changes, so an unchanged row after the takeover is the takeover's doing and not a method that writes nothing. Supports C1.
tests/tmp/test_54_translate_job_handle_phase1.py:80 - control: after `store_ready_subtitles` on the Engine's own connection, `fetch_ready_subtitles` returns the Engine's cues, so the running row really was replaced. Supports C1.
tests/tmp/test_54_translate_job_handle_phase1.py:82 - for each of the six methods, after the takeover the method returns exactly False. Excludes an UPDATE keyed on the row alone, and one matching on started_at alone the way `mark_translate_finished` did (the takeover keeps started_at). C1.
tests/tmp/test_54_translate_job_handle_phase1.py:85 - for each of the six methods, the `_snapshot` taken after the method (every column of every row as SQL literals, rowid included) equals the one taken right after the takeover. Excludes any write that lands on the taken-over row. C1.
tests/tmp/test_54_translate_job_handle_phase1.py:93 - held-claim control: `end_ready_from_instance` on a held claim returns True. C1 (held-claim control from the checkpoint).
tests/tmp/test_54_translate_job_handle_phase1.py:94 - held-claim control: `fetch_ready_subtitles` then returns the instance cues. C1 (held-claim control).
tests/tmp/test_54_translate_job_handle_phase1.py:100-118 - held-claim control: the whole row equals a literal dict. It is ready, source instance, track_text 'WEBVTT t', cues_json the compact literal '[{"start":1.0,"end":2.0,"text":"Hello"}]', and fetched_at == finished_at == 9000. detected_language 'fr', error None, attempts 1, queued_at 1000 and started_at 2000 keep the running job's values. Excludes two timestamps, a spaced encoding, and any write to another job column. C1 (held-claim control).
tests/tmp/test_54_translate_job_handle_phase1.py:138 - control: inside the wrapped `fetch_instance_track`, the real fetch found the served English track (TRACK). Supports C2.
tests/tmp/test_54_translate_job_handle_phase1.py:139 - control: the Engine's store landed on the running row, which is now ready, instance, with ENGINE_TRACK. Supports C2.
tests/tmp/test_54_translate_job_handle_phase1.py:140 - control: the rig's cues_writes trigger recorded the Engine's upsert as the literal '[{"start":5.0,"end":6.0,"text":"Engine"}]', so it would also record a worker write. Supports C2.
tests/tmp/test_54_translate_job_handle_phase1.py:141 - after `run_job`, the whole-table `_snapshot` equals the one taken at the takeover. Excludes today's upsert-then-stamp, which overwrites track_text, cues_json and fetched_at and stamps finished_at. C2.
tests/tmp/test_54_translate_job_handle_phase1.py:142 - no cues_json write was made after the takeover (cues_writes unchanged). This also excludes a write that changed the row and then put it back. C2.
tests/tmp/test_54_translate_job_handle_phase1.py:143 - the `[translate-worker]` log records are exactly [`[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`]. Excludes today's `job ready from the instance track` line, a stub that returns ready without writing, and any `job failed` or `job error` line. C2.
tests/tmp/test_54_translate_job_handle_phase1.py:144 - the runner made 0 transcribes. C2.
tests/tmp/test_54_translate_job_handle_phase1.py:145 - the instance opened exactly [CAPTIONS_URL, TRACK_URL] and the media host opened nothing, so no video JSON or media was fetched after the takeover. C2.
</assertions>

<probes>
Probe file tests/tmp/probe_54_phase1_observe.py, run with ValidateTests ["tests/tmp/probe_54_phase1_observe.py", "-s", "-q"] (output read from tests/last_test_output.txt; 3 passed).
(1) Today's per-claim functions after a `store_ready_subtitles` takeover on a separate connection (v-1 queued 1000, claimed 2000, Engine stored at 8000). The snapshot after the takeover was ready/instance, fetched_at 8000, queued_at 1000, started_at 2000 (kept by the upsert), finished_at NULL, attempts 1. `store_running_cues`, `finish_translate_ready`, `finish_translate_already_english`, `finish_translate_failed` and `requeue_translate_job` each printed `False True` (returned False, snapshot unchanged). `mark_translate_finished` did change the snapshot: finished_at became 9000. So the setup is sound, and a started_at-only match would be caught.
(2) Encoding: `store_ready_subtitles` with [{"start":1.0,"end":2.0,"text":"Hello"}] stored cues_json '[{"start":1.0,"end":2.0,"text":"Hello"}]'. Over a running row it left detected_language 'fr', queued_at 1000, started_at 2000, attempts 1, error None and finished_at None. That is where the literal and the kept-column values in the held-claim row come from.
(3) Today's worker, through Rig with EN_LISTING and TRACK served and `fetch_instance_track` wrapped so the Engine stores its own track after the real fetch. run_job returned False. The fetch returned TRACK with its parsed cues. The row after the run had TRACK, the worker's cues, and a wall-clock fetched_at and finished_at, so it did not equal the takeover snapshot (equal False). cues_writes was ['[{"start":5.0,"end":6.0,"text":"Engine"}]'] at the takeover, with the worker's cues appended afterwards, so the trigger does record an upsert. The only log record was INFO '[translate-worker] job ready from the instance track video_id=v-1 host=peer.example'. transcribes was 0, the instance opened [captions, en.vtt] and the media host opened [].
Checkpoint red run: ValidateTests ["tests/tmp/test_54_translate_job_handle_phase1.py", "-q"] gave 8 failed. All 6 C1 parameters and the held-claim test fail with AttributeError ('sqlite3.Row' object has no attribute write_running_cues / end_ready / end_already_english / end_failed / requeue / end_ready_from_instance), because the handle does not exist yet. In the C2 test, the controls at :138-140 pass and :141 fails: today the row holds the worker's TRACK, cues and a wall-clock fetched_at/finished_at instead of the Engine's 1700000000000 row.
I could not delete tests/tmp/probe_54_phase1_observe.py because no delete tool is available. It imports functions this phase removes, so it should be deleted along with the other stale tests/tmp probes.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_54_translate_job_handle_phase1.py` - 8579 characters, inlined in full

```
"""Phase 1 checkpoint of plan 54: once the Engine's instance-track store has replaced a running row, no write through the claim's `TranslateJob` handle changes it.

Store (C1), `engine/server/data/subtitles.py` called directly on tmp subtitles.db files opened as test_subtitles.py's `_subtitles` opens them, v-1 on peer.example queued at 1000 and claimed at 2000:

- Each of the six handle methods (running cues, ready, already_english, failed, requeue, ready from the instance track), run after `store_ready_subtitles` on the Engine's own connection has stored ready/instance over the running row, returns False, and every column of every row, rowid included, reads the same afterwards. The same method on a fresh claim with no takeover returns True and changes the row, so the unchanged row is the takeover's doing.
- With the claim held, ending ready from the instance track returns True and leaves exactly: ready, instance, the track text, the cues as compact JSON, fetched_at and finished_at both the one given time, and detected_language, error, attempts, queued_at and started_at as the running job had them; the ready reader then returns those cues.

Worker (C2), `run_job` through test_translate_worker.py's `Rig` with the English caption listing and track served: `fetch_instance_track` is wrapped so that, after the real fetch has found the track, the Engine stores its own different track ready/instance over the running row. Afterwards every column of every row reads as the Engine left it and no further cues_json write was made; the only worker log line is `[translate-worker] taken over by the instance track video_id=v-1 host=peer.example`; nothing was transcribed and nothing past the caption list and the track was fetched.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import HOST, _snapshot, _subtitles  # noqa: E402
from test_translate_worker import CAPTIONS_URL, EN_LISTING, TRACK, TRACK_URL, StubRunner, clip, rig  # noqa: E402,F401

from data.subtitles import claim_translate_job, connect_subtitles_db, enqueue_translate_job, fetch_ready_subtitles, store_ready_subtitles  # noqa: E402

QUEUED_AT = 1000
STARTED_AT = 2000
TAKEOVER_AT = 8000
FINISHED_AT = 9000
# The Engine's track differs from the one the worker fetches, so a worker write over the Engine's row shows in track_text and cues_json.
ENGINE_TRACK = "WEBVTT\n\n00:05.000 --> 00:06.000\nEngine\n"
ENGINE_CUES = [{"start": 5.0, "end": 6.0, "text": "Engine"}]
# ENGINE_CUES as store_ready_subtitles encodes them, probed.
ENGINE_CUES_JSON = '[{"start":5.0,"end":6.0,"text":"Engine"}]'
WORKER_CUES = [{"start": 1.0, "end": 2.0, "text": "Hello"}]
TAKEN_OVER = f"[translate-worker] taken over by the instance track video_id=v-1 host={HOST}"

# Every claim-conditional write the handle offers, each with values that change the row when the claim holds.
CLAIM_WRITES = {
    "running cues": lambda job: job.write_running_cues(WORKER_CUES, "fr"),
    "ready": lambda job: job.end_ready(WORKER_CUES, FINISHED_AT),
    "already_english": lambda job: job.end_already_english("en", FINISHED_AT),
    "failed": lambda job: job.end_failed("boom", FINISHED_AT),
    "requeue": lambda job: job.requeue(),
    "ready from instance": lambda job: job.end_ready_from_instance("WEBVTT x", WORKER_CUES, FINISHED_AT),
}


def _claimed(path: Path):  # noqa: ANN202
    """A store at `path` with v-1 queued at QUEUED_AT and claimed at STARTED_AT; the worker's connection and its handle."""
    conn = _subtitles(path)
    assert tuple(enqueue_translate_job(conn, "v-1", HOST, "en", 50, QUEUED_AT)) == ("queued", "queued")
    return conn, claim_translate_job(conn, "en", STARTED_AT)


def _engine_stores(path: Path, track: str, cues: list[dict], fetched_at: int) -> None:
    """The Engine state route's instance-track store, on a connection of its own as the Engine holds one."""
    engine = connect_subtitles_db(path)
    try:
        store_ready_subtitles(engine, "v-1", HOST, "en", "instance", track, cues, fetched_at)
    finally:
        engine.close()


@pytest.mark.parametrize("write", CLAIM_WRITES.values(), ids=CLAIM_WRITES.keys())
def test_every_claim_write_after_an_instance_track_takeover_reports_the_claim_lost_and_leaves_the_row_byte_identical(tmp_path, write):
    held_path = tmp_path / "held.db"
    conn, job = _claimed(held_path)
    held_before = _snapshot(held_path)
    try:
        assert write(job) is True  # C1 control: the claim held, so the write matched
    finally:
        conn.close()
    assert _snapshot(held_path) != held_before  # C1 control: with the claim held this write changes the row, so an unchanged row below is the takeover's doing

    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        _engine_stores(path, ENGINE_TRACK, ENGINE_CUES, TAKEOVER_AT)
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == ENGINE_CUES  # control: the Engine's ready/instance row replaced the running one
        taken = _snapshot(path)
        assert write(job) is False  # C1
    finally:
        conn.close()
    assert _snapshot(path) == taken  # C1


def test_ending_ready_from_the_instance_track_while_the_claim_holds_leaves_ready_instance_with_one_timestamp_and_the_job_columns_kept(tmp_path):
    path = tmp_path / "subtitles.db"
    conn, job = _claimed(path)
    try:
        assert job.write_running_cues([{"start": 0.5, "end": 0.9, "text": "partial"}], "fr") is True  # control: a running job with partial cues and a detected language
        assert job.end_ready_from_instance("WEBVTT t", WORKER_CUES, FINISHED_AT) is True  # C1 held-claim control
        assert fetch_ready_subtitles(conn, "v-1", HOST, "en") == WORKER_CUES  # C1 held-claim control
    finally:
        conn.close()
    reader = sqlite3.connect(path)
    reader.row_factory = sqlite3.Row
    try:
        row = dict(reader.execute("SELECT * FROM subtitles").fetchone())
    finally:
        reader.close()
    assert row == {
        "video_id": "v-1",
        "instance_domain": HOST,
        "target_language": "en",
        "state": "ready",
        "source": "instance",
        "fetched_at": FINISHED_AT,
        "track_text": "WEBVTT t",
        "cues_json": '[{"start":1.0,"end":2.0,"text":"Hello"}]',
        "queued_at": QUEUED_AT,
        "started_at": STARTED_AT,
        "finished_at": FINISHED_AT,
        "error": None,
        "detected_language": "fr",
        "attempts": 1,
    }  # C1 held-claim control: one timestamp for fetched_at and finished_at, compact cues, every other job column as the running job had it


def test_an_instance_track_found_after_the_engine_took_the_row_over_writes_nothing_and_logs_the_takeover(rig, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    rig.instance.serve(CAPTIONS_URL, body=EN_LISTING)
    rig.instance.serve(TRACK_URL, body=TRACK.encode("utf-8"))
    real_fetch = rig.worker.fetch_instance_track
    seen: dict = {}

    def engine_takes_over_after_the_fetch(instance: str, video_key: str):  # noqa: ANN202
        fetched = real_fetch(instance, video_key)
        _engine_stores(rig.subtitles, ENGINE_TRACK, ENGINE_CUES, 1_700_000_000_000)
        seen.update(fetched=fetched, row=rig.row(), taken=_snapshot(rig.subtitles), writes=rig.cues_writes())
        return fetched

    monkeypatch.setattr(rig.worker, "fetch_instance_track", engine_takes_over_after_the_fetch)
    runner = StubRunner(rig)
    rig.run(runner)

    assert seen["fetched"] is not None and seen["fetched"][0] == TRACK  # control: the worker found the instance's English track
    assert (seen["row"]["state"], seen["row"]["source"], seen["row"]["track_text"]) == ("ready", "instance", ENGINE_TRACK)  # control: the Engine's store landed on the running row
    assert seen["writes"] == [ENGINE_CUES_JSON]  # control: the trigger records the Engine's upsert, so it would record a worker write too
    assert _snapshot(rig.subtitles) == seen["taken"]  # C2: every column of every row as the Engine left it
    assert rig.cues_writes() == seen["writes"]  # C2: no cues_json write after the takeover
    assert [record.getMessage() for record in caplog.records if record.getMessage().startswith("[translate-worker]")] == [TAKEN_OVER]  # C2: the takeover logged, and no ready, failed or error line
    assert runner.transcribes == 0  # C2
    assert rig.instance.opened == [CAPTIONS_URL, TRACK_URL] and rig.media.opened == []  # C2: nothing fetched past the track

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 1 (Claim handle) - red (audit round 1)

`tests/tmp/test_54_translate_job_handle_phase1.py` exited 1.

```
  tests/tmp/test_54_translate_job_handle_phase1.py  8 failed                               0.0s
  ------------------------------------------------
  total                                             8 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 1 (Claim handle) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
1. The parametrized C1 test errors at line 73, `assert write(job) is False`, with an `AttributeError`. In every case the `CLAIM_WRITES` lambda (lines 40–45) calls a handle method on what `claim_translate_job` still returns: a `sqlite3.Row` (engine/server/data/subtitles.py:139–147), not a `TranslateJob`.
2. The held-claim test errors at line 95, `job.end_ready_from_instance(...)`, the same way.
3. The C2 test fails at line 143, `assert _snapshot(rig.subtitles) == seen["taken"]`. `generate` still calls `store_ready_subtitles` unconditionally (translate-worker.py:407), so the worker writes `TRACK` over the Engine's `ENGINE_TRACK` row, and `track_text`, `cues_json` and `fetched_at` all differ from the snapshot.

NOT ASSESSED
1. `exempted_clauses` was not supplied, so the test was treated as having none.
2. `fixtures_path` was given as "none found". I resolved the fixtures `rig` and `clip` and the helpers `_snapshot`, `_subtitles`, `Rig.row`, `Rig.cues_writes` and `StubRunner` directly in tests/active/test_translate_worker.py and tests/active/test_subtitles.py. No conftest.py was read.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (24 clauses: 4 must_prove, 13 docstring, 7 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | after a `store_ready_subtitles` takeover each of the six methods "returns False" | :73 | a handle that reports True (claim still held) after the Engine's upsert, for any of the six parametrized writes at :39-46 | CARRIED |
| C1b | must_prove | "leaves the row byte-identical" | :76 | any write after the takeover, because `_snapshot` compares rowid and `quote()` of every column; also a write keyed on `started_at` alone, which the takeover leaves intact | CARRIED |
| C2a | must_prove | instance track found after the takeover, "`generate` writes nothing" | :143, :144 | the worker's `store_ready_subtitles` over the Engine row (track_text/cues differ, :31-35), `mark_translate_finished` stamping finished_at on the ready row, or a failed-end write | CARRIED |
| C2b | must_prove | "the takeover is logged" | :145 | no log line, a `job ready from the instance track` line, or any additional failed/error line, because the list must equal exactly `[TAKEN_OVER]` | CARRIED |
| D1 | docstring | "no write through the claim's `TranslateJob` handle changes it" | :76 | a handle write that lands on the Engine's row | CARRIED |
| D2 | docstring | six methods after takeover each return False | :73 | True returned after the takeover | CARRIED |
| D3 | docstring | "every column of every row, rowid included, reads the same" | :76 | a column, type or rowid changed (`_snapshot`, test_subtitles.py:205-211) | CARRIED |
| D4 | docstring | same method on a fresh claim "returns True" | :82 | a method that always returns False | CARRIED |
| D5 | docstring | "and changes the row" | :85 | a method that is a no-op, so an unchanged row would prove nothing | CARRIED |
| D6 | docstring | claim held: end ready from instance "returns True" | :95 | a held-claim end reporting the claim lost | CARRIED |
| D7a | docstring | leaves "ready, instance, the track text" | :105-113 | the wrong state or source left in place (still `whisper`/`running`), or track_text not stored | CARRIED |
| D7b | docstring | "the cues as compact JSON" | :113 | default `json.dumps` separators (spaces), or partial cues left in place | CARRIED |
| D7c | docstring | "fetched_at and finished_at both the one given time" | :111, :116 | fetched_at left at QUEUED_AT (enqueue sets it), finished_at left NULL, or two different clocks | CARRIED |
| D7d | docstring | "detected_language, error, attempts, queued_at and started_at as the running job had them" | :114-119 | detected_language cleared (it was set to "fr" at :94), attempts reset or incremented, queued_at/started_at overwritten, a non-NULL error written; clearing error is indistinguishable because the running row's error is already NULL | CARRIED |
| D8 | docstring | "the ready reader then returns those cues" | :96 | a row `fetch_ready_subtitles` cannot read (wrong state, bad cues_json) | CARRIED |
| D9 | docstring | worker: real fetch found the track, then the Engine stored a different track over the running row | :140, :141, :142 | (controls) a test in which the takeover never happened or the trigger records nothing | CARRIED |
| D10 | docstring | worker: "nothing was transcribed and nothing past the caption list and the track was fetched" | :146, :147 | a worker that falls through to the video JSON, the media download or Whisper after the takeover | CARRIED |
| N1 | name | "every claim write after an instance track takeover reports the claim lost" | :73 | any of the six returning True | CARRIED |
| N2 | name | "and leaves the row byte-identical" | :76 | any byte changed | CARRIED |
| N3 | name | "ending ready from the instance track while the claim holds leaves ready instance" | :109-110 | another state or source | CARRIED |
| N4 | name | "with one timestamp" | :111, :116 | fetched_at ≠ finished_at | CARRIED |
| N5 | name | "and the job columns kept" | :114-119 | queued_at, started_at, attempts or detected_language overwritten | CARRIED |
| N6 | name | "an instance track found after the engine took the row over writes nothing" | :143, :144 | any subtitles write or cues_json write after the takeover | CARRIED |
| N7 | name | "and logs the takeover" | :145 | the takeover line missing, or other worker lines present | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` has no `TranslateJob` handle. engine/server/data/subtitles.py:139 `claim_translate_job` returns `sqlite3.Row | None`, and no file in `code_under_test` defines `write_running_cues`, `end_ready`, `end_already_english`, `end_failed`, `requeue` or `end_ready_from_instance`. A Grep finds them only in the test, plan docs and test-output files. tests/tmp/test_54_translate_job_handle_phase1.py:39-46 calls them on the object `_claimed` returns at :53.
   - So I could not check that the six entries at :39-46 are the handle's complete set of claim-conditional writes, which is what C1's "each of the six" relies on. C1a/C1b are judged against the six the test lists.
   - For the same reason I could not check the methods' accepted inputs, so the bounds principle was judged only from what the test passes.
2. The C2 path goes through `Rig.run` (tests/active/test_translate_worker.py:546-554). It passes the claimed `sqlite3.Row` to `run_job`. Whether `run_job` will receive a handle under this phase cannot be told from the code supplied.

## 2026-10-04 - Step 7 - Phase 1 (Claim handle) - checkpoint outcome (run 1)

`tests/tmp/test_54_translate_job_handle_phase1.py` exited 0 after the phase landed.

<changes>
### engine/server/data/subtitles.py
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
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_54_translate_job_handle_phase1.py  8 passed                               0.0s
  ------------------------------------------------
  total                                             8 passed                               0.4s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
subtitles.db is opened everywhere through `open_subtitles_db`, which creates the directory, connects in WAL and migrates, and crash recovery can run only through `open_translate_worker_store`, which re-asserts the worker's flock before touching the file.

- C1 - `open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode.
- C2 - `open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock.

must_prove:
- C1 - `open_subtitles_db` turns a missing nested path or a B1-era file into the full current schema in WAL mode.
- C2 - `open_translate_worker_store` refuses with BlockingIOError and creates nothing while another open file description holds the flock.

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - self-check (audit round 1, send-back 0)

`tests/tmp/test_54_translate_job_handle_phase2.py`, surface `checkpoint`. Collection exit 2.

- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:71 and :73-76 — on tmp_path/"a"/"b"/"subtitles.db" with no `a` (control :63), after `store.open_subtitles_db(path)` the parent is a directory, and a fresh plain connection reads sorted columns == sorted(ALL_COLUMNS), ["state", "queued_at"] among the index column lists, heartbeat columns ["id", "beat_at", "pid"], journal mode "wal"; :67 the returned connection reads fetch_translate_heartbeat None - expected: Directory exists; columns are the 14 names video_id, instance_domain, target_language, state, source, fetched_at, track_text, cues_json, queued_at, started_at, finished_at, error, detected_language, attempts; index lists [["state", "queued_at"], ["video_id", "instance_domain", "target_language"]]; heartbeat ["id", "beat_at", "pid"]; mode "wal"; heartbeat None. All observed in a probe run on a file opened with connect_subtitles_db + ensure_subtitles_schema, the two functions the plan's opener composes. - excludes: An opener without the `path.parent.mkdir(parents=True, exist_ok=True)` raises at the connect, because a bare sqlite3 connect on the missing nested path gives OperationalError "unable to open database file" (probed), so :65 raises. An opener that connects without ensure_subtitles_schema leaves no subtitles table, so columns read [] at :73 and :67 raises "no such table". One that uses plain sqlite3.connect instead of connect_subtitles_db leaves the mode at "delete" at :76.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:97-100 and :92, :103 — on a _b1_file (controls :85 mode "delete", :86 old cues == B1_CUES), after `store.open_subtitles_db(path)` a plain connection reads sorted columns == sorted(ALL_COLUMNS), the (state, queued_at) index, heartbeat columns ["id", "beat_at", "pid"], mode "wal"; both the returned connection (:92) and a fresh plain one (:103) read _old_cues == B1_CUES - expected: Same 14 columns, index lists, heartbeat columns and "wal" as the fresh case. The old cues equal B1_CUES before and after, through both connections. Observed in the probe after connect_subtitles_db + ensure_subtitles_schema on a _b1_file; the probe also read journal_mode "delete" before. - excludes: An opener that only creates the table when it is missing (CREATE TABLE IF NOT EXISTS without the in-place ALTERs) leaves B1's 8 columns, so :97 is red. One that recreates the table drops the B1 rows, and _old_cues reads None per key at :92 and :103. One that skips the WAL connect leaves "delete" at :100, the mode the control at :85 saw.
- C2 - tests/tmp/test_54_translate_job_handle_phase2.py:116-119 — while a separate os.open description `held` holds LOCK_EX, `store.open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError within the 10 s alarm, and afterwards neither the file nor its `sub` directory exists; armed by the controls at :126-127 (same call on the same `mine` once held is closed returns counts (0, 0) and the file exists) and :130-131 (a third description is then refused, so the opener took and kept the lock on mine) - expected: BlockingIOError; path.exists() False; path.parent.exists() False. With the lock free: (0, 0), file present, and a third description's LOCK_NB raises BlockingIOError. Observed in the probe: a separate description's LOCK_EX|LOCK_NB gets BlockingIOError [Errno 11] while held has the lock; a dup of held acquires instead; after held closes, mine acquires, and re-asserting on mine is a no-op; a third description is then refused; SIGALRM interrupts a blocking flock after 1.0 s. - excludes: An opener with no flock re-assert just opens the store and returns, so no BlockingIOError is raised at :116 and the file and directory exist. One that re-asserts with blocking LOCK_EX, without LOCK_NB, hangs until the alarm, and _bounded fails the test. One that runs open_subtitles_db (mkdir and connect) before the flock raises BlockingIOError but leaves `sub/` and the file behind, so :118 and :119 are red. One that takes the flock on a dup or a fresh open and then releases it leaves the third description free, so the control at :131 is red.

<assertions>
tests/tmp/test_54_translate_job_handle_phase2.py:66 - the connection `open_subtitles_db` returns on a missing nested path reads `fetch_translate_heartbeat` as None, so the migrated heartbeat table is there. Excludes: an opener that returns an unmigrated connection (it would raise "no such table"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:70 - `a/b` exists afterwards, after the line-62 control showed `a` absent. Excludes: no mkdir (probed: a bare connect raises OperationalError "unable to open database file"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:72 - through a plain connection, the nested file's subtitles columns equal ALL_COLUMNS (the fourteen). Excludes: connect without migrate (probed: columns []). C1
tests/tmp/test_54_translate_job_handle_phase2.py:73 - the nested file has an index on exactly (state, queued_at). Excludes: a partial migration. C1
tests/tmp/test_54_translate_job_handle_phase2.py:74 - the nested file's translate_worker_heartbeat columns are ["id", "beat_at", "pid"]. Excludes: an opener that skips the heartbeat table. C1
tests/tmp/test_54_translate_job_handle_phase2.py:75 - the nested file's journal_mode, read through a fresh plain connection, is "wal". Excludes: a plain sqlite3.connect plus migrate (stand-in variant no_wal failed here). C1
tests/tmp/test_54_translate_job_handle_phase2.py:91 - on a B1 file (controls at 85-86: journal "delete", old cues readable), the returned connection reads both old cue lists equal to B1_CUES. Excludes: a migration that drops or rewrites the old rows. C1
tests/tmp/test_54_translate_job_handle_phase2.py:96 - the B1 file's columns equal ALL_COLUMNS. Excludes: no in-place migration of an existing table. C1
tests/tmp/test_54_translate_job_handle_phase2.py:97 - the B1 file gains the (state, queued_at) index. C1
tests/tmp/test_54_translate_job_handle_phase2.py:98 - the B1 file gains translate_worker_heartbeat with id, beat_at, pid. C1
tests/tmp/test_54_translate_job_handle_phase2.py:99 - the B1 file's journal_mode is "wal". Excludes: a migration without the WAL connect (probed: ensure alone leaves "delete"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:102 - a fresh plain connection to the B1 file still reads B1_CUES. C1
tests/tmp/test_54_translate_job_handle_phase2.py:115 - while a separate os.open description `held` holds LOCK_EX, `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError, bounded by a 10 s SIGALRM. Excludes: no flock at all (variant no_lock: "DID NOT RAISE") and a blocking LOCK_EX without NB (variant blocking: fails with "blocked for 10 s" instead of hanging). C2
tests/tmp/test_54_translate_job_handle_phase2.py:117 - after the refusal, subtitles.db does not exist. Excludes: an opener that opens or connects before the flock. C2
tests/tmp/test_54_translate_job_handle_phase2.py:118 - after the refusal, the `sub` directory does not exist. Excludes: mkdir before the flock (variant mkdir_first failed here). C2
tests/tmp/test_54_translate_job_handle_phase2.py:125 - control: once `held` is closed, the same call on `mine` returns counts (0, 0).
tests/tmp/test_54_translate_job_handle_phase2.py:126 - control: subtitles.db then exists, so the absence at 117-118 comes from the refusal and not from a broken opener.
tests/tmp/test_54_translate_job_handle_phase2.py:130 - control: after the successful call, a third description is refused LOCK_EX|LOCK_NB, because the opener took the lock on `mine` and kept it. Excludes: flock then LOCK_UN (variant unlocking failed here).
tests/tmp/test_54_translate_job_handle_phase2.py:158 - control (recovery test, lock_fd held LOCK_EX by the test): after one claim the handle reads video_id "t" and attempts 1, through attributes.
tests/tmp/test_54_translate_job_handle_phase2.py:163 - `open_translate_worker_store(path, lock_fd, 9000)` on the held descriptor returns counts (1, 0). Excludes: an opener that skips recovery (variant no_recover failed here). Phase checkpoint item (Test 4)
tests/tmp/test_54_translate_job_handle_phase2.py:164 - t reads ("queued", 1, None, None) after that recovery. Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:167 - control: three claims read through attributes are [("t", 2), ("o1", 1), ("o2", 1)].
tests/tmp/test_54_translate_job_handle_phase2.py:172 - the second recovery, at 9500, returns (2, 1). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:173 - t reads ("failed", 2, "worker stopped while running twice", 9500). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:174 - o1 reads ("queued", 1, None, None). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:175 - o2 reads ("queued", 1, None, None). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:180 - the queued bystander z and the ready row b1 are byte-identical (_snapshot) before and after both recoveries. Test 4
</assertions>

<probes>
tests/tmp/probe_54_phase2_flock.py, run with ValidateTests ["tests/tmp/probe_54_phase2_flock.py", "-s"], printed:
- two os.open descriptions of one lock file in one process: LOCK_EX|LOCK_NB on the second, while the first holds LOCK_EX, raises exactly BlockingIOError ("[Errno 11] Resource temporarily unavailable"). On an os.dup of the holder, and on the holder itself, the re-assert succeeds. So `mine` must be a separate os.open, never a dup.
- a blocking LOCK_EX on a held lock is interrupted by SIGALRM after 1.0 s when the handler raises. This is the basis for the `_bounded` guard. pytest_timeout is absent.
- once the holder (and its dup) are closed, `mine` takes the lock. A third description is then refused with BlockingIOError.
- O_RDONLY|O_CREAT descriptors flock fine.
- sqlite3.connect on a missing nested dir raises OperationalError "unable to open database file". connect_subtitles_db without ensure gives columns [] and mode wal.
- ensure_subtitles_schema on a plain connection to a B1 file leaves mode "delete", heartbeat columns ['id','beat_at','pid'], and indexes [['state','queued_at'], [video_id, instance_domain, target_language]].
- data.subtitles today exports only `recover_translate_jobs` (no open_* names).

ValidateTests ["tests/tmp/test_54_translate_job_handle_phase2.py"] against today's code: red at collection, "ImportError: cannot import name 'open_subtitles_db' from 'data.subtitles'".

tests/tmp/probe_54_phase2_vs_draft.py, run with ValidateTests ["tests/tmp/probe_54_phase2_vs_draft.py", "-s"], loads the checkpoint with the plan's draft openers (plan lines 999-1008, 1095-1105) injected into data.subtitles, then with wrong variants:
- draft: all 4 pass.
- no_wal: tests 1 and 2 fail.
- no_mkdir: test 1 fails (OperationalError), and so does test 3.
- mkdir_first: test 3 fails (AssertionError, parent exists).
- blocking (LOCK_EX without NB): test 3 fails with "open_translate_worker_store blocked for 10 s instead of refusing the held flock".
- no_lock: test 3 fails ("DID NOT RAISE BlockingIOError").
- unlocking (flock then LOCK_UN): test 3 fails at the third-description control.
- no_recover: test 4 fails.

Probe files left behind: tests/tmp/probe_54_phase2_flock.py, tests/tmp/probe_54_phase2_vs_draft.py and tests/tmp/probe_54_phase2_unlock.py (written but never run; the matrix output above answered its question). I have no delete tool, so they should be removed by hand.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_54_translate_job_handle_phase2.py` - 9636 characters, inlined in full

```
"""Phase 2 checkpoint of plan 54: `open_subtitles_db` is the one store opener and crash recovery runs only through `open_translate_worker_store`, under the worker's flock.

Store openers in `engine/server/data/subtitles.py`, called directly on files under tmp_path; the file's state is read back through a fresh plain connection, since the file and not the opener's connection is what the next opener meets.

- C1, missing nested path: on `a/b/subtitles.db` with neither `a` nor `b` present, `open_subtitles_db` creates both. The file then has the fourteen columns, a `(state, queued_at)` index, `translate_worker_heartbeat` with `id`, `beat_at` and `pid`, and journal mode `wal`. The returned connection reads the empty heartbeat.
- C1, B1-era file: on a rollback-journal file with B1's table and two ready/instance rows, the same four facts hold afterwards, and both the returned connection and the plain one read the two old cue lists unchanged.
- C2: while a separate `os.open` description of the worker lock holds LOCK_EX, `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError, and neither the file nor its `sub` directory exists. Each call is bounded by an alarm, so an opener that blocks on the flock fails instead of hanging. Control: once the holder is closed, the same call on the same descriptor returns (0, 0) and the file exists, and a third description is then refused the lock, because the opener took it on `mine` and kept it.
- Recovery under a held flock: `open_translate_worker_store` returns (1, 0) at 9000, requeuing a running job with attempts 1. Claimed again, that job is failed with "worker stopped while running twice" at 9500 beside two first-time running jobs that are requeued, and the call returns (2, 1). The claims are read through the handle's attributes, and a queued row and a ready row are untouched.
"""
from __future__ import annotations

import fcntl
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import ALL_COLUMNS, B1_CUES, B1_READY_INSTANCE, HOST, RECOVERY_TEXT, _b1_file, _insert, _old_cues, _plain, _snapshot  # noqa: E402

from data.subtitles import claim_translate_job, fetch_translate_heartbeat, open_subtitles_db, open_translate_worker_store  # noqa: E402

# Long enough for a migration on a tmp file; a blocking flock on a held lock never returns at all (probed: SIGALRM interrupts it).
OPENER_SECONDS = 10


@contextmanager
def _bounded() -> Iterator[None]:
    """Fail, rather than hang, when the opener blocks on the flock instead of refusing with LOCK_NB."""

    def ring(signum, frame):  # noqa: ANN001, ANN202
        pytest.fail(f"open_translate_worker_store blocked for {OPENER_SECONDS} s instead of refusing the held flock")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(OPENER_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _schema(path: Path) -> tuple[list[str], list[list[str]], list[str], str]:
    """The file's subtitles columns, index column lists, heartbeat columns and journal mode, through a plain connection."""
    conn = _plain(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        indexed = [[info[2] for info in conn.execute(f"PRAGMA index_info('{index[1]}')")] for index in conn.execute("PRAGMA index_list(subtitles)")]
        heartbeat = [row[1] for row in conn.execute("PRAGMA table_info(translate_worker_heartbeat)")]
        return columns, indexed, heartbeat, conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal(tmp_path):
    path = tmp_path / "a" / "b" / "subtitles.db"
    assert not (tmp_path / "a").exists()  # control: neither directory exists, and a bare sqlite3 connect there fails (probed)

    conn = open_subtitles_db(path)
    try:
        assert fetch_translate_heartbeat(conn) is None  # C1: the returned connection reads the migrated, empty heartbeat table
    finally:
        conn.close()

    assert path.parent.is_dir()  # C1
    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1


def test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues(tmp_path):
    path = tmp_path / "subtitles.db"
    _b1_file(path)
    before = _plain(path)
    try:
        # Controls: a rollback-journal B1 file whose rows B1's reader already returns.
        assert before.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert _old_cues(before) == B1_CUES
    finally:
        before.close()

    conn = open_subtitles_db(path)
    try:
        assert _old_cues(conn) == B1_CUES  # C1: the returned connection reads the old cues unchanged
    finally:
        conn.close()

    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1
    after = _plain(path)
    try:
        assert _old_cues(after) == B1_CUES  # C1: the file itself still holds them
    finally:
        after.close()


def test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing(tmp_path):
    lock = tmp_path / "worker.lock"
    path = tmp_path / "sub" / "subtitles.db"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    # A second open of the file, not os.dup: a dup shares held's description and so its lock (probed), and would never be refused.
    mine = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        with _bounded(), pytest.raises(BlockingIOError):  # C2
            open_translate_worker_store(path, mine, 1)
        assert not path.exists()  # C2: the file was never opened
        assert not path.parent.exists()  # C2: nor its directory created, so the flock came before the mkdir

        os.close(held)
        held = -1
        with _bounded():
            opened, counts = open_translate_worker_store(path, mine, 1)
        opened.close()
        assert tuple(counts) == (0, 0)  # control: with the lock free the same call on the same descriptor succeeds
        assert path.exists()  # control: so the absence above is the refusal's doing
        other = os.open(lock, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # control: the opener took the lock on mine and kept it
        finally:
            os.close(other)
    finally:
        if held != -1:
            os.close(held)
        os.close(mine)


def test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    path = tmp_path / "subtitles.db"
    lock_fd = os.open(tmp_path / "worker.lock", os.O_RDONLY | os.O_CREAT)
    conn = open_subtitles_db(path)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
        _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})
        _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
        # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
        _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})
        _insert(conn, "b1", HOST, B1_READY_INSTANCE)
        _, before = _snapshot(path)
        bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]

        def job(video_id: str) -> tuple:
            return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

        first = claim_translate_job(conn, "en", 5000)
        assert (first.video_id, first.attempts) == ("t", 1)  # control: t is running after one claim

        with _bounded():
            opened, counts = open_translate_worker_store(path, lock_fd, 9000)
        opened.close()
        assert tuple(counts) == (1, 0)
        assert job("t") == ("queued", 1, None, None)  # requeued, its one claim still counted

        second = [claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
        assert [(row.video_id, row.attempts) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

        with _bounded():
            opened, counts = open_translate_worker_store(path, lock_fd, 9500)
        opened.close()
        assert tuple(counts) == (2, 1)
        assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)
        assert job("o1") == ("queued", 1, None, None)
        assert job("o2") == ("queued", 1, None, None)
    finally:
        conn.close()
        os.close(lock_fd)
    _, after = _snapshot(path)
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # recovery touches only running rows

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - does not collect (send-back 1)

`validate_tests.py tests/tmp/test_54_translate_job_handle_phase2.py --collect-only -q` exited 2.

```

==================================== ERRORS ====================================
______ ERROR collecting tests/tmp/test_54_translate_job_handle_phase2.py _______
ImportError while importing test module '/home/enduser/code/PeerTube-browser/tests/tmp/test_54_translate_job_handle_phase2.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.pixi/envs/default/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/tmp/test_54_translate_job_handle_phase2.py:26: in <module>
    from data.subtitles import claim_translate_job, fetch_translate_heartbeat, open_subtitles_db, open_translate_worker_store  # noqa: E402
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ImportError: cannot import name 'open_subtitles_db' from 'data.subtitles' (/home/enduser/code/PeerTube-browser/engine/server/data/subtitles.py)
=========================== short test summary info ============================
ERROR tests/tmp/test_54_translate_job_handle_phase2.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
no tests collected, 1 error in 0.06s

the run produced no per-test results, so there is nothing to bucket or compare — its output above says why

recorded: tests/last_test_validation.json (exit 2)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - self-check (audit round 1, send-back 1)

`tests/tmp/test_54_translate_job_handle_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:67 — on a/b/subtitles.db with neither directory present, `store.fetch_translate_heartbeat(conn)` on the connection `open_subtitles_db` returned is None - expected: None: the heartbeat table exists and is empty (seen: the test passes when the probe draft opener, mkdir + connect_subtitles_db + ensure_subtitles_schema, is put in place) - excludes: An opener that creates the directory and connects but never migrates. Seen in probe_54_phase2_c1_lines.py: OperationalError 'no such table: translate_worker_heartbeat' at line 67.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:71 — `path.parent.is_dir()` after the opener on the missing nested path - expected: True: both a and b exist (seen passing under the draft) - excludes: An opener with no mkdir, i.e. connect_subtitles_db + ensure_subtitles_schema on its own. Seen in the vs_draft probe (no_mkdir): the opener call at line 65 raises OperationalError 'unable to open database file', so the test fails before it gets this far.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:73 and :97 — `sorted(columns) == sorted(ALL_COLUMNS)`, the file's subtitles columns read through a fresh plain connection, for the nested new file and for the B1 file - expected: B1's eight columns plus queued_at, started_at, finished_at, error, detected_language, attempts, fourteen in all (seen passing under the draft for both inputs) - excludes: An opener that connects without migrating. Seen in probe_54_phase2_c1_lines.py: AssertionError at line 97 on the B1 file, which still has only its eight columns. On the nested path that opener already fails at line 67.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:74 and :98 — `["state", "queued_at"] in indexed`, the column lists of the subtitles indexes, for both inputs - expected: An index covering exactly (state, queued_at) is present (seen passing under the draft for both inputs) - excludes: An opener that adds the job columns but not the queue index, or that does not migrate at all. Its index lists hold only the primary key's autoindex [video_id, instance_domain, target_language], so the assertion fails. This is a prediction: the not-migrated mutant failed at an earlier line, and no index-only mutant was run.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:75 and :99 — `heartbeat == ["id", "beat_at", "pid"]`, the translate_worker_heartbeat columns through a plain connection, for both inputs - expected: ["id", "beat_at", "pid"] (seen passing under the draft for both inputs) - excludes: An opener that migrates only the subtitles table, or not at all. table_info on a missing table gives [] and the assertion fails. This is a prediction: that mutant was not run on its own.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:76 and :100 — `mode == "wal"`, PRAGMA journal_mode through a fresh plain connection after the opener closed, for both inputs; for the B1 file, line 85 confirms the file started in "delete" mode - expected: "wal" (seen passing under the draft for both inputs) - excludes: An opener that runs mkdir + a bare sqlite3.connect + ensure_subtitles_schema and never switches to WAL. Seen in probe_54_phase2_c1_lines.py: AssertionError at line 76 and at line 100, where the file still reads as rollback journal.
- C1 - tests/tmp/test_54_translate_job_handle_phase2.py:92 and :103 — `_old_cues(...) == B1_CUES` on the B1 file after the opener, first through the returned connection and then through a fresh plain one; line 86 shows the same reader returns them before - expected: {("v-1","peer.example"): [{start 1.0, end 2.5, "Hello"}], ("v-2","other.example"): [{0.5,1.0,"One"},{3.0,4.25,"Two"}]} (seen passing under the draft) - excludes: An opener that brings a B1 file up to the current schema by dropping and recreating the table. fetch_ready_subtitles then returns None for both keys and the dict comparison fails. This is a prediction: that mutant was not run.
- C2 - tests/tmp/test_54_translate_job_handle_phase2.py:116-117 — while a separate os.open description holds LOCK_EX, `store.open_translate_worker_store(path, mine, 1)` raises BlockingIOError inside a 10 s SIGALRM bound. Controls at 124-131: once the holder is closed, the same call returns (0, 0) and a third description is refused the lock. - expected: BlockingIOError raised at once (seen under the draft, which uses flock LOCK_EX|LOCK_NB) - excludes: Seen in the vs_draft probe. An opener that never locks: 'DID NOT RAISE BlockingIOError'. An opener that locks without LOCK_NB: the alarm fires, 'open_translate_worker_store blocked for 10 s instead of refusing the held flock'. An opener that locks and then unlocks: the line-130 control reads 'DID NOT RAISE BlockingIOError'.
- C2 - tests/tmp/test_54_translate_job_handle_phase2.py:118 — `not path.exists()` after the refusal; armed by line 127, where `path.exists()` holds after the same call succeeds - expected: The file does not exist (seen under the draft; line 127 then reads True) - excludes: An opener that opens the store first and takes the flock afterwards. The database file exists by the time BlockingIOError is raised, so the assertion fails. This is a prediction: the open-then-lock order was not run as a mutant.
- C2 - tests/tmp/test_54_translate_job_handle_phase2.py:119 — `not path.parent.exists()` after the refusal: the sub directory was never created - expected: The directory does not exist (seen under the draft) - excludes: An opener that runs path.parent.mkdir before it flocks. Seen in the vs_draft probe (mkdir_first): an AssertionError in this test. It creates no file, so line 118 passes and this line is the one that fails.

<assertions>
tests/tmp/test_54_translate_job_handle_phase2.py:67 - the connection `open_subtitles_db` returns on a missing nested path reads `fetch_translate_heartbeat` as None, so the migrated heartbeat table is there. Excludes: an opener that returns an unmigrated connection (it would raise "no such table"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:71 - `a/b` exists afterwards. The line-63 control showed `a` absent before the call. Excludes: no mkdir (probed: a bare connect raises OperationalError "unable to open database file"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:73 - read through a plain connection, the nested file's subtitles columns equal ALL_COLUMNS (all fourteen). Excludes: connect without migrate (probed: columns []). C1
tests/tmp/test_54_translate_job_handle_phase2.py:74 - the nested file has an index on exactly (state, queued_at). Excludes: a partial migration. C1
tests/tmp/test_54_translate_job_handle_phase2.py:75 - the nested file's translate_worker_heartbeat columns are ["id", "beat_at", "pid"]. Excludes: an opener that skips the heartbeat table. C1
tests/tmp/test_54_translate_job_handle_phase2.py:76 - the nested file's journal_mode, read through a fresh plain connection, is "wal". Excludes: a plain sqlite3.connect plus migrate (the no_wal stand-in variant failed here). C1
tests/tmp/test_54_translate_job_handle_phase2.py:92 - on a B1 file, the returned connection reads both old cue lists equal to B1_CUES. The controls at 85-86 confirm the file starts with journal "delete" and its old cues readable. Excludes: a migration that drops or rewrites the old rows. C1
tests/tmp/test_54_translate_job_handle_phase2.py:97 - the B1 file's columns equal ALL_COLUMNS. Excludes: no in-place migration of an existing table. C1
tests/tmp/test_54_translate_job_handle_phase2.py:98 - the B1 file gains the (state, queued_at) index. C1
tests/tmp/test_54_translate_job_handle_phase2.py:99 - the B1 file gains translate_worker_heartbeat with id, beat_at, pid. C1
tests/tmp/test_54_translate_job_handle_phase2.py:100 - the B1 file's journal_mode is "wal". Excludes: a migration without the WAL connect (probed: ensure alone leaves "delete"). C1
tests/tmp/test_54_translate_job_handle_phase2.py:103 - a fresh plain connection to the B1 file still reads B1_CUES. C1
tests/tmp/test_54_translate_job_handle_phase2.py:116 - while a separate os.open description `held` holds LOCK_EX, `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError. A 10 s SIGALRM bounds the call. Excludes: no flock at all (no_lock variant: "DID NOT RAISE") and a blocking LOCK_EX without NB (blocking variant: fails with "blocked for 10 s" instead of hanging). C2
tests/tmp/test_54_translate_job_handle_phase2.py:118 - after the refusal, subtitles.db does not exist. Excludes: an opener that opens or connects before the flock. C2
tests/tmp/test_54_translate_job_handle_phase2.py:119 - after the refusal, the `sub` directory does not exist. Excludes: mkdir before the flock (the mkdir_first variant failed here). C2
tests/tmp/test_54_translate_job_handle_phase2.py:126 - control: once `held` is closed, the same call on `mine` returns counts (0, 0).
tests/tmp/test_54_translate_job_handle_phase2.py:127 - control: subtitles.db then exists, so the absence at 118-119 comes from the refusal and not from a broken opener.
tests/tmp/test_54_translate_job_handle_phase2.py:131 - control: after the successful call, a third description is refused LOCK_EX|LOCK_NB, because the opener took the lock on `mine` and kept it. Excludes: flock then LOCK_UN (the unlocking variant failed here).
tests/tmp/test_54_translate_job_handle_phase2.py:160 - control (recovery test, with lock_fd held LOCK_EX by the test): after one claim, the handle's attributes read video_id "t" and attempts 1.
tests/tmp/test_54_translate_job_handle_phase2.py:165 - `open_translate_worker_store(path, lock_fd, 9000)` on the held descriptor returns counts (1, 0). Excludes: an opener that skips recovery (the no_recover variant failed here). Phase checkpoint item (Test 4)
tests/tmp/test_54_translate_job_handle_phase2.py:166 - after that recovery, t reads ("queued", 1, None, None). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:169 - control: three claims, read through their attributes, are [("t", 2), ("o1", 1), ("o2", 1)].
tests/tmp/test_54_translate_job_handle_phase2.py:174 - the second recovery, at 9500, returns (2, 1). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:175 - t reads ("failed", 2, "worker stopped while running twice", 9500). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:176 - o1 reads ("queued", 1, None, None). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:177 - o2 reads ("queued", 1, None, None). Test 4
tests/tmp/test_54_translate_job_handle_phase2.py:182 - the queued bystander z and the ready row b1 are byte-identical (_snapshot) before and after both recoveries. Test 4
</assertions>

<probes>
Collection fix: the previous run's ImportError came from the module-level `from data.subtitles import ... open_subtitles_db ...`. The file now imports the module (`from data import subtitles as store`, line 27) and reaches the phase's names as attributes inside each test. It collects, and each test goes red at its own call to a missing name, after its controls.
ValidateTests ["tests/tmp/test_54_translate_job_handle_phase2.py"] against today's code: 4 collected, 4 failed, exit 1. The failures are AttributeError "module 'data.subtitles' has no attribute 'open_subtitles_db'" at :65 and :90, and AttributeError "... no attribute 'open_translate_worker_store'" at :117 and :163. So the controls at 63, 85-86 and 160 passed before each test went red.
tests/tmp/probe_54_phase2_flock.py, run with ValidateTests ["tests/tmp/probe_54_phase2_flock.py", "-s"], printed:
- two os.open descriptions of one lock file in one process: while the first holds LOCK_EX, LOCK_EX|LOCK_NB on the second raises exactly BlockingIOError ("[Errno 11] Resource temporarily unavailable"). On an os.dup of the holder, and on the holder itself, the re-assert succeeds, so `mine` must be a separate os.open, never a dup.
- a blocking LOCK_EX on a held lock is interrupted by SIGALRM after 1.0 s when the handler raises. This is the basis for `_bounded`. pytest_timeout is absent.
- once the holder (and its dup) are closed, `mine` takes the lock, and a third description is then refused with BlockingIOError. O_RDONLY|O_CREAT descriptors flock fine.
- sqlite3.connect on a missing nested dir raises OperationalError "unable to open database file". connect_subtitles_db without ensure gives columns [] and mode wal.
- ensure_subtitles_schema on a plain connection to a B1 file leaves mode "delete", heartbeat columns ['id','beat_at','pid'], and indexes [['state','queued_at'], [video_id, instance_domain, target_language]].
tests/tmp/probe_54_phase2_vs_draft.py, run with ValidateTests ["tests/tmp/probe_54_phase2_vs_draft.py", "-s"], injects the plan's draft openers (plan lines 999-1008, 1095-1105) into data.subtitles and then wrong variants. Results:
- draft: all 4 pass.
- no_wal: tests 1 and 2 fail.
- no_mkdir: tests 1 and 3 fail.
- mkdir_first: test 3 fails (parent exists).
- blocking: test 3 fails with "blocked for 10 s".
- no_lock: test 3 fails ("DID NOT RAISE").
- unlocking: test 3 fails at the third-description control.
- no_recover: test 4 fails.
Leftover probe files: tests/tmp/probe_54_phase2_flock.py, tests/tmp/probe_54_phase2_vs_draft.py and tests/tmp/probe_54_phase2_unlock.py (never run) still exist. I have no delete tool, so they need removing by hand.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_54_translate_job_handle_phase2.py` - 9896 characters, inlined in full

```
"""Phase 2 checkpoint of plan 54: `open_subtitles_db` is the one store opener and crash recovery runs only through `open_translate_worker_store`, under the worker's flock.

Store openers in `engine/server/data/subtitles.py`, called directly on files under tmp_path; the file's state is read back through a fresh plain connection, since the file and not the opener's connection is what the next opener meets.

- C1, missing nested path: on `a/b/subtitles.db` with neither `a` nor `b` present, `open_subtitles_db` creates both. The file then has the fourteen columns, a `(state, queued_at)` index, `translate_worker_heartbeat` with `id`, `beat_at` and `pid`, and journal mode `wal`. The returned connection reads the empty heartbeat.
- C1, B1-era file: on a rollback-journal file with B1's table and two ready/instance rows, the same four facts hold afterwards, and both the returned connection and the plain one read the two old cue lists unchanged.
- C2: while a separate `os.open` description of the worker lock holds LOCK_EX, `open_translate_worker_store(tmp_path/"sub"/"subtitles.db", mine, 1)` raises BlockingIOError, and neither the file nor its `sub` directory exists. Each call is bounded by an alarm, so an opener that blocks on the flock fails instead of hanging. Control: once the holder is closed, the same call on the same descriptor returns (0, 0) and the file exists, and a third description is then refused the lock, because the opener took it on `mine` and kept it.
- Recovery under a held flock: `open_translate_worker_store` returns (1, 0) at 9000, requeuing a running job with attempts 1. Claimed again, that job is failed with "worker stopped while running twice" at 9500 beside two first-time running jobs that are requeued, and the call returns (2, 1). The claims are read through the handle's attributes, and a queued row and a ready row are untouched.
"""
from __future__ import annotations

import fcntl
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_subtitles import ALL_COLUMNS, B1_CUES, B1_READY_INSTANCE, HOST, RECOVERY_TEXT, _b1_file, _insert, _old_cues, _plain, _snapshot, _subtitles  # noqa: E402

# The module, not its names: the openers are this phase's, so each test fails at its own call, after its controls, instead of the whole file failing to collect.
from data import subtitles as store  # noqa: E402

# Long enough for a migration on a tmp file; a blocking flock on a held lock never returns at all (probed: SIGALRM interrupts it).
OPENER_SECONDS = 10


@contextmanager
def _bounded() -> Iterator[None]:
    """Fail, rather than hang, when the opener blocks on the flock instead of refusing with LOCK_NB."""

    def ring(signum, frame):  # noqa: ANN001, ANN202
        pytest.fail(f"open_translate_worker_store blocked for {OPENER_SECONDS} s instead of refusing the held flock")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(OPENER_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _schema(path: Path) -> tuple[list[str], list[list[str]], list[str], str]:
    """The file's subtitles columns, index column lists, heartbeat columns and journal mode, through a plain connection."""
    conn = _plain(path)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(subtitles)")]
        indexed = [[info[2] for info in conn.execute(f"PRAGMA index_info('{index[1]}')")] for index in conn.execute("PRAGMA index_list(subtitles)")]
        heartbeat = [row[1] for row in conn.execute("PRAGMA table_info(translate_worker_heartbeat)")]
        return columns, indexed, heartbeat, conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()


def test_open_subtitles_db_creates_a_missing_nested_directory_and_the_full_schema_in_wal(tmp_path):
    path = tmp_path / "a" / "b" / "subtitles.db"
    assert not (tmp_path / "a").exists()  # control: neither directory exists, and a bare sqlite3 connect there fails (probed)

    conn = store.open_subtitles_db(path)
    try:
        assert store.fetch_translate_heartbeat(conn) is None  # C1: the returned connection reads the migrated, empty heartbeat table
    finally:
        conn.close()

    assert path.parent.is_dir()  # C1
    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1


def test_open_subtitles_db_turns_a_b1_file_into_the_full_schema_in_wal_and_keeps_its_old_cues(tmp_path):
    path = tmp_path / "subtitles.db"
    _b1_file(path)
    before = _plain(path)
    try:
        # Controls: a rollback-journal B1 file whose rows B1's reader already returns.
        assert before.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert _old_cues(before) == B1_CUES
    finally:
        before.close()

    conn = store.open_subtitles_db(path)
    try:
        assert _old_cues(conn) == B1_CUES  # C1: the returned connection reads the old cues unchanged
    finally:
        conn.close()

    columns, indexed, heartbeat, mode = _schema(path)
    assert sorted(columns) == sorted(ALL_COLUMNS)  # C1
    assert ["state", "queued_at"] in indexed  # C1
    assert heartbeat == ["id", "beat_at", "pid"]  # C1
    assert mode == "wal"  # C1
    after = _plain(path)
    try:
        assert _old_cues(after) == B1_CUES  # C1: the file itself still holds them
    finally:
        after.close()


def test_the_worker_store_opener_refuses_while_another_description_holds_the_flock_and_creates_nothing(tmp_path):
    lock = tmp_path / "worker.lock"
    path = tmp_path / "sub" / "subtitles.db"
    held = os.open(lock, os.O_RDONLY | os.O_CREAT)
    # A second open of the file, not os.dup: a dup shares held's description and so its lock (probed), and would never be refused.
    mine = os.open(lock, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        with _bounded(), pytest.raises(BlockingIOError):  # C2
            store.open_translate_worker_store(path, mine, 1)
        assert not path.exists()  # C2: the file was never opened
        assert not path.parent.exists()  # C2: nor its directory created, so the flock came before the mkdir

        os.close(held)
        held = -1
        with _bounded():
            opened, counts = store.open_translate_worker_store(path, mine, 1)
        opened.close()
        assert tuple(counts) == (0, 0)  # control: with the lock free the same call on the same descriptor succeeds
        assert path.exists()  # control: so the absence above is the refusal's doing
        other = os.open(lock, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # control: the opener took the lock on mine and kept it
        finally:
            os.close(other)
    finally:
        if held != -1:
            os.close(held)
        os.close(mine)


def test_recovery_through_the_worker_store_opener_requeues_a_running_job_once_and_fails_it_when_found_running_a_second_time(tmp_path):
    path = tmp_path / "subtitles.db"
    lock_fd = os.open(tmp_path / "worker.lock", os.O_RDONLY | os.O_CREAT)
    # Set up through the plain connect and migrate, so the claims below run as controls before the phase's opener is reached.
    conn = _subtitles(path)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _insert(conn, "t", HOST, {"state": "queued", "source": "whisper", "fetched_at": 1000, "queued_at": 1000, "attempts": 0})
        _insert(conn, "o1", HOST, {"state": "queued", "source": "whisper", "fetched_at": 2000, "queued_at": 2000, "attempts": 0})
        _insert(conn, "o2", HOST, {"state": "queued", "source": "whisper", "fetched_at": 3000, "queued_at": 3000, "attempts": 0})
        # Bystanders: never claimed here (z is the newest queued job), and recovery must leave both alone.
        _insert(conn, "z", HOST, {"state": "queued", "source": "whisper", "fetched_at": 9999, "queued_at": 9999, "attempts": 0})
        _insert(conn, "b1", HOST, B1_READY_INSTANCE)
        _, before = _snapshot(path)
        bystanders_before = [row for row in before if row[1] in ("'z'", "'b1'")]

        def job(video_id: str) -> tuple:
            return tuple(conn.execute("SELECT state, attempts, error, finished_at FROM subtitles WHERE video_id = ?", (video_id,)).fetchone())

        first = store.claim_translate_job(conn, "en", 5000)
        assert (first.video_id, first.attempts) == ("t", 1)  # control: t is running after one claim

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9000)
        opened.close()
        assert tuple(counts) == (1, 0)
        assert job("t") == ("queued", 1, None, None)  # requeued, its one claim still counted

        second = [store.claim_translate_job(conn, "en", started_at) for started_at in (9100, 9101, 9102)]
        assert [(row.video_id, row.attempts) for row in second] == [("t", 2), ("o1", 1), ("o2", 1)]  # control: t is running for the second time beside two first-time jobs

        with _bounded():
            opened, counts = store.open_translate_worker_store(path, lock_fd, 9500)
        opened.close()
        assert tuple(counts) == (2, 1)
        assert job("t") == ("failed", 2, RECOVERY_TEXT, 9500)
        assert job("o1") == ("queued", 1, None, None)
        assert job("o2") == ("queued", 1, None, None)
    finally:
        conn.close()
        os.close(lock_fd)
    _, after = _snapshot(path)
    assert [row for row in after if row[1] in ("'z'", "'b1'")] == bystanders_before  # recovery touches only running rows

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - red (audit round 1)

`tests/tmp/test_54_translate_job_handle_phase2.py` exited 1.

```
  tests/tmp/test_54_translate_job_handle_phase2.py  4 failed                               0.0s
  ------------------------------------------------
  total                                             4 failed                               0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 2 UNCARRIED clause(s) - D1, D2

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
All four tests should fail with `AttributeError`, because `data.subtitles` defines neither opener yet:
- Line 65, `store.open_subtitles_db(path)`. The precondition at line 63 passes first.
- Line 90, `store.open_subtitles_db(path)`. The B1 controls at lines 85–86 pass first.
- Line 117, `store.open_translate_worker_store(path, mine, 1)`. The `AttributeError` is not a `BlockingIOError`, so it gets past `pytest.raises` at line 116.
- Line 164, `store.open_translate_worker_store(path, lock_fd, 9000)`. The controls at lines 155 and 161 pass first.

NOT ASSESSED
1. `code_under_test` lists engine/server/api/server.py, engine/server/db/jobs/translate-worker.py and tests/active/test_internal_translate.py. All three exist, but I did not read them in full. The test under audit references none of them. A Grep over engine/ found no definition of `open_subtitles_db` or `open_translate_worker_store` anywhere. I answered the stub question from engine/server/data/subtitles.py, from the helpers the test imports from tests/active/test_subtitles.py (lines 41–213), and from the test's assertion form.
2. `fixtures_path` was not supplied. The test uses only pytest's built-in `tmp_path`. Its other helpers are imported explicitly from tests/active/test_subtitles.py, so no conftest was needed.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (24 clauses: 7 must_prove, 13 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | a missing nested path becomes a created directory | :71 | an opener that connects without making `a/b` (the control at :63 says the path is absent first) | CARRIED |
| C1b | must_prove | missing nested path → full current schema | :73, :74, :75 | a job column, the `(state, queued_at)` index or the heartbeat table left out | CARRIED |
| C1c | must_prove | missing nested path → WAL mode | :76 | an opener that leaves the default rollback journal | CARRIED |
| C1d | must_prove | a B1-era file → full current schema | :97, :98, :99 | a B1 file left without the job columns, the index or the heartbeat table | CARRIED |
| C1e | must_prove | a B1-era file → WAL mode | :100 (control :85 = `delete`) | a migration that never switches an existing rollback-journal file | CARRIED |
| C2a | must_prove | refuses with BlockingIOError while another open file description holds the flock | :116 | no flock taken, a blocking flock (stopped by `_bounded`), or a different error raised | CARRIED |
| C2b | must_prove | creates nothing while refused | :118, :119 | the db opened, or its directory made, before the flock is tried | CARRIED |
| D1 | docstring | "`open_subtitles_db` is the one store opener" | none | nothing checks that the Engine or the worker open the store through it | UNCARRIED |
| D2 | docstring | "crash recovery runs only through `open_translate_worker_store`, under the worker's flock" | :116–119 (under-flock half only) | the refusal path runs no recovery; nothing rules out `open_subtitles_db` also recovering (the B1 and nested files hold no running row, so that would not show) | UNCARRIED |
| D3 | docstring | the file's state is read back through a fresh plain connection | :72, :96, :101 | a schema seen only through the opener's own connection | CARRIED |
| D4 | docstring | "creates both" `a` and `b`; fourteen columns, index, heartbeat `id, beat_at, pid`, journal `wal` | :71, :73–76 | each missing piece, as in C1a–C1c | CARRIED |
| D5 | docstring | "The returned connection reads the empty heartbeat" | :67 | returning a connection that was not migrated (raises: no such table) | CARRIED |
| D6 | docstring | B1 file: rollback journal with two ready/instance rows (precondition) | :85, :86 | a fixture that is already WAL or has no rows, which would make C1e/D8 trivially true | CARRIED |
| D7 | docstring | B1 file: "the same four facts hold afterwards" | :97–100 | as C1d/C1e | CARRIED |
| D8 | docstring | both connections read the two old cue lists unchanged | :92, :103 | a migration that recreates the table or loses or rewrites rows | CARRIED |
| D9 | docstring | C2 refusal: BlockingIOError, and neither the file nor `sub` exists | :116, :118, :119 | as C2a/C2b | CARRIED |
| D10 | docstring | "Each call is bounded by an alarm, so an opener that blocks … fails instead of hanging" | :116, :123 (`_bounded`, :38) | an opener without LOCK_NB hangs forever instead of failing | CARRIED |
| D11 | docstring | control: once the holder is closed, the same call returns (0, 0) and the file exists | :126, :127 | a refusal that is unconditional, so the absence at :118 is not caused by the lock | CARRIED |
| D12 | docstring | a third description is refused, because the opener took the lock on `mine` and kept it | :130–131 | an opener that releases the flock after migrating | CARRIED |
| D13 | docstring | recovery returns (1, 0) at 9000 and requeues a running job with attempts 1 | :166, :167 | a recovery that fails on the first find, or that resets or spends attempts | CARRIED |
| D14 | docstring | claimed again: failed with the text at 9500 beside two first-time jobs requeued, returns (2, 1) | :175–178 | failing every running row, or requeuing the twice-run one | CARRIED |
| D15 | docstring | "The claims are read through the handle's attributes" | :161, :170 | a claim that picks the wrong row or attempts value, letting the controls pass for the wrong reason | CARRIED |
| D16 | docstring | "a queued row and a ready row are untouched" | :183 | a recovery UPDATE not limited to `state = 'running'` | CARRIED |
| N1 | name | test 1: "creates a missing nested directory and the full schema in wal" | :71, :73–76 | as C1a–C1c | CARRIED |
| N2 | name | test 2: "turns a b1 file into the full schema in wal and keeps its old cues" | :97–100, :92, :103 | as C1d, C1e, D8 | CARRIED |
| N3 | name | test 3: "refuses while another description holds the flock and creates nothing" | :116, :118, :119 | as C2a/C2b | CARRIED |
| N4 | name | test 4: "requeues a running job once and fails it when found running a second time" | :167, :176 | as D13/D14 | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_54_translate_job_handle_phase2.py:1
   D1 is UNCARRIED. The module docstring says `open_subtitles_db` "is the one store opener". No test opens the store through `engine/server/api/server.py` or `engine/server/db/jobs/translate-worker.py`, though both are listed as edited. Either assert this at a seam those files go through, or narrow the sentence. This is a docstring row, not a `must_prove` row, so it does not block.
2. whole-claim (rules/testing.md) — tests/tmp/test_54_translate_job_handle_phase2.py:1
   D2 is UNCARRIED for its "only through" half. The refusal at :116–119 shows nothing runs without the flock. But no test opens a file holding a `running` row through `open_subtitles_db` and checks that the row stays `running`. So an implementation where the Engine's opener also recovers still passes. This is a docstring row, so it does not block.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_54_translate_job_handle_phase2.py:61
   `open_subtitles_db` is only tested on success, at :61 and :79. Its expected failure mode has no test, for example a parent that is a regular file, or a path that cannot be opened.
4. No rule covers this; noted for the record — tests/tmp/test_54_translate_job_handle_phase2.py:53
   "Full current schema" is checked through column names (:73), index columns (:74) and heartbeat column names (:75). Declarations are not compared: the primary key, `attempts NOT NULL DEFAULT 0`, and the heartbeat's `CHECK (id = 1)`. The test still rules out the clause's main wrong implementations (a missing column, index or table), so C1b and C1d stay CARRIED.

OBSERVATIONS
none

NOT ASSESSED
1. `open_subtitles_db` and `open_translate_worker_store` do not exist in `engine/server/data/subtitles.py` or anywhere else in `engine/server`. The test expects this: line 26 says each test should fail at its own call. Because there is no definition, I could not check the signatures and return shapes the test assumes against the code: `(path)`, `(path, fd, now)`, and `(conn, (requeued, failed))`. Bounds were judged from the test, the existing `recover_translate_jobs` / `ensure_subtitles_schema`, and the flock sequence in `translate-worker.py` `run` (:517–536).
2. The phase's `<checkpoint>` text was not supplied. So I could not tell whether it names a seam above the data layer that this checkpoint should also enter, such as the worker's `run` exiting 6 on a held lock. The surface pass was judged against `must_prove` alone, and its clauses are all about the two openers at the data layer.
3. `tests/active/test_internal_translate.py` is in `code_under_test` but this test never touches it, so I did not read it.

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - self-check (audit round 2, send-back 1)

`tests/tmp/test_54_translate_job_handle_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1a - tests/tmp/test_54_translate_job_handle_phase2.py:71 — `path.parent.is_dir()` after `open_subtitles_db(tmp_path/"a"/"b"/"subtitles.db")`, with the control at :63 showing `a` absent before - expected: True: the opener creates `a/b` - excludes: An opener that connects without mkdir. The no_mkdir variant raises OperationalError "unable to open database file" at the call.
- C1b - tests/tmp/test_54_translate_job_handle_phase2.py:73, :74, :75 — through a fresh plain connection to the nested file: the columns sorted equal ALL_COLUMNS, `["state", "queued_at"]` is among the index column lists, and the heartbeat columns are ["id", "beat_at", "pid"]; plus :67, where the returned connection reads `fetch_translate_heartbeat` as None - expected: All fourteen columns, the (state, queued_at) index, and heartbeat id/beat_at/pid - excludes: Connect without migrating: columns read [] (probed). A partial migration missing the index or the heartbeat table fails :74 or :75.
- C1c - tests/tmp/test_54_translate_job_handle_phase2.py:76 — the nested file's journal_mode, read through a fresh plain connection - expected: "wal" - excludes: A plain sqlite3.connect plus migrate leaves the rollback journal. The no_wal variant fails tests 1 and 2.
- C1d - tests/tmp/test_54_translate_job_handle_phase2.py:97, :98, :99 — the B1 file's columns, index and heartbeat columns after `open_subtitles_db`; plus :92 and :103, where the returned connection and a plain one read B1_CUES - expected: ALL_COLUMNS, the (state, queued_at) index, heartbeat id/beat_at/pid, and old cues equal to B1_CUES - excludes: An opener that leaves an existing B1 table unmigrated fails the column, index and heartbeat checks. One that recreates the table loses the rows and fails :92 and :103.
- C1e - tests/tmp/test_54_translate_job_handle_phase2.py:100 — the B1 file's journal_mode after the opener; the control at :85 shows "delete" before - expected: "wal" - excludes: Migrating without the WAL connect: ensure_subtitles_schema alone leaves "delete" (probed). The no_wal variant fails here.
- C2a - tests/tmp/test_54_translate_job_handle_phase2.py:116 — while a separate os.open description holds LOCK_EX, `open_translate_worker_store(path, mine, 1)`, bounded by `_bounded` - expected: raises BlockingIOError - excludes: No flock: the no_lock variant fails with "DID NOT RAISE BlockingIOError". A blocking LOCK_EX: the blocking variant fails with "blocked for 10 s" instead of hanging.
- C2b - tests/tmp/test_54_translate_job_handle_phase2.py:118, :119 — after the refusal, neither subtitles.db nor `sub` exists. Controls at :126–127: once the holder is closed, the same call returns (0, 0) and the file exists - expected: both absent - excludes: mkdir or connect before the flock. The mkdir_first variant fails at :119.

<exemptions>
none
</exemptions>

<items>
<item id="D1">
<disposition>justified</disposition>
<what>Narrowed the prose. The module docstring's first line said `open_subtitles_db` "is the one store opener", but no test here goes through the Engine or the worker. It now reads: "`open_subtitles_db` opens any path or B1-era file as the full schema in WAL". That is what :71–76 and :92–103 assert.</what>
</item>
<item id="D2">
<disposition>fixed</disposition>
<what>Test 4 now calls `store.open_subtitles_db(path).close()` at :163, after the first claim and before the worker opener. At :164 it asserts `job("t") == ("running", 1, None, None)`. Two lines show the row could have been recovered: the control at :161 (t claimed, attempts 1), and :169, where `open_translate_worker_store` then returns (1, 0) on the same row. So :164 is not an empty absence. This excludes an `open_subtitles_db` that also runs recovery. A `recovering_open` variant added to probe_54_phase2_vs_draft.py, the draft opener plus `recover_translate_jobs`, fails test 4 with an AssertionError; the draft openers still pass all four tests. The "under the worker's flock" half stays where it was, at :116–119. I also added a matching sentence to the recovery bullet of the docstring.</what>
</item>
</items>

<findings_addressed>
There were no CRITICAL findings from either auditor. Of the claim auditor's recommendations, I took 1 by narrowing the D1 sentence in the docstring. I took 2 by adding the `open_subtitles_db` no-recovery assertion at :163–164, armed by :161 and :169. I left 3 (`open_subtitles_db` failure mode) and 4 (comparing column declarations): neither is in this phase's `must_prove`, and adding them would grow the checkpoint past the ledger.
</findings_addressed>

<rows>
<row clause="C1a">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:71 — `path.parent.is_dir()` after `open_subtitles_db(tmp_path/"a"/"b"/"subtitles.db")`, with the control at :63 showing `a` absent before</assertion>
<expected>True: the opener creates `a/b`</expected>
<wrong_implementation>An opener that connects without mkdir. The no_mkdir variant raises OperationalError "unable to open database file" at the call.</wrong_implementation>
</row>
<row clause="C1b">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:73, :74, :75 — through a fresh plain connection to the nested file: the columns sorted equal ALL_COLUMNS, `["state", "queued_at"]` is among the index column lists, and the heartbeat columns are ["id", "beat_at", "pid"]; plus :67, where the returned connection reads `fetch_translate_heartbeat` as None</assertion>
<expected>All fourteen columns, the (state, queued_at) index, and heartbeat id/beat_at/pid</expected>
<wrong_implementation>Connect without migrating: columns read [] (probed). A partial migration missing the index or the heartbeat table fails :74 or :75.</wrong_implementation>
</row>
<row clause="C1c">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:76 — the nested file's journal_mode, read through a fresh plain connection</assertion>
<expected>"wal"</expected>
<wrong_implementation>A plain sqlite3.connect plus migrate leaves the rollback journal. The no_wal variant fails tests 1 and 2.</wrong_implementation>
</row>
<row clause="C1d">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:97, :98, :99 — the B1 file's columns, index and heartbeat columns after `open_subtitles_db`; plus :92 and :103, where the returned connection and a plain one read B1_CUES</assertion>
<expected>ALL_COLUMNS, the (state, queued_at) index, heartbeat id/beat_at/pid, and old cues equal to B1_CUES</expected>
<wrong_implementation>An opener that leaves an existing B1 table unmigrated fails the column, index and heartbeat checks. One that recreates the table loses the rows and fails :92 and :103.</wrong_implementation>
</row>
<row clause="C1e">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:100 — the B1 file's journal_mode after the opener; the control at :85 shows "delete" before</assertion>
<expected>"wal"</expected>
<wrong_implementation>Migrating without the WAL connect: ensure_subtitles_schema alone leaves "delete" (probed). The no_wal variant fails here.</wrong_implementation>
</row>
<row clause="C2a">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:116 — while a separate os.open description holds LOCK_EX, `open_translate_worker_store(path, mine, 1)`, bounded by `_bounded`</assertion>
<expected>raises BlockingIOError</expected>
<wrong_implementation>No flock: the no_lock variant fails with "DID NOT RAISE BlockingIOError". A blocking LOCK_EX: the blocking variant fails with "blocked for 10 s" instead of hanging.</wrong_implementation>
</row>
<row clause="C2b">
<assertion>tests/tmp/test_54_translate_job_handle_phase2.py:118, :119 — after the refusal, neither subtitles.db nor `sub` exists. Controls at :126–127: once the holder is closed, the same call returns (0, 0) and the file exists</assertion>
<expected>both absent</expected>
<wrong_implementation>mkdir or connect before the flock. The mkdir_first variant fails at :119.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The one negative assertion added, :164 (t still running after `open_subtitles_db`), is armed on both sides. Before it, :161 shows t was claimed; after it, :169 shows `open_translate_worker_store` returns (1, 0) on that same row, so the row was recoverable. The existing negatives keep their controls: :118–119 by :126–127, and :186 by :155.
2. No. :164 compares a SELECT on the file against a literal state tuple; the test does not transform anything itself. Adding a recover call to the opener (the probe's recovering_open variant) turns test 4 red.
3. No. The no-recovery observable at :164 is read on a row that the worker opener then recovers at a different input, :169 (1, 0). It is not read at one point in isolation.
4. No. No double stands in for a project module. The probe's variants are injected only by the probe file, never by the checkpoint.
5. Yes, it collects: ValidateTests on the checkpoint collected 4 tests. `store.open_subtitles_db` is reached as a module attribute, and `job` was already defined before :163.
6. Yes. ("running", 1, None, None) was observed: with the plan's draft openers injected (probe_54_phase2_vs_draft.py), test 4 passes, and the recovering_open variant fails test 4 with an AssertionError. I did not see which line raised it. I infer :164, because it is the first point after which recovery could show; a traceback of that variant would confirm it.
7. Yes. Against today's code all 4 tests fail with AttributeError: at :65 and :90 (open_subtitles_db), :117 (open_translate_worker_store) and now :163 (open_subtitles_db), each after its controls. Leftover probe files that need deleting by hand, since I have no delete tool: tests/tmp/probe_54_phase2_flock.py, probe_54_phase2_vs_draft.py, probe_54_phase2_unlock.py and probe_54_phase2_c1_lines.py.
</answers>

Gate: NOT SATISFIED - no assertion carries C1, C2

## 2026-10-04 - Step 7 - stopped

Implement the plan did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.


## 2026-10-04 - Step 7 - continued by hand under dev_flow.md

The workflow stopped at the round-2 self-check gate. The remediation reply labelled its rows with the claim auditor's sub-ids (C1a-C1e, C2a, C2b), and `_check_rows` matches `must_prove` ids exactly (C1, C2). That was its second mechanical send-back (the first was round 1's collection failure), so it asked for a waiver and stopped. At the operator's direction the build continues by hand from 7.4. The rows recorded under the C1 and C2 ids are those of the round-1 self-check (above, "audit round 1, send-back 1"). The round-2 rows are the same assertions split by sub-clause, plus :163-164.

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - red and re-audit (audit round 2)

`validate_tests.py tests/tmp/test_54_translate_job_handle_phase2.py`: exit 1, 4 failed. Each test fails at the phase's own missing opener, after its controls pass: :65 and :90 `AttributeError: module 'data.subtitles' has no attribute 'open_subtitles_db'`, :117 `... 'open_translate_worker_store'`, :163 `... 'open_subtitles_db'`.

- AUDIT: devsecops-test-shape-auditor - PASS. Predicted failure: AttributeError at :65, :90, :117 (passes `pytest.raises(BlockingIOError)`) and :163, each after its controls. This matches the run.
- AUDIT: devsecops-test-claim-auditor - PASS (bounded to the frozen round-1 ledger). D1 CARRIED by narrowing (the docstring no longer claims "the one store opener"). D2 CARRIED by :164 (control :161; the row is recovered at :169). All must_prove rows CARRIED.
- Ledger: D1 justified (sentence narrowed); D2 fixed (:163-164). No UNCARRIED row remains.
- Observations taken: 2, "any path" narrowed to "a missing nested path" in the docstring's first sentence, answering a recorded audit finding before the test gated. Not taken: 1 (record note: D1 is carried by narrowing, as stated above) and 3 (moot: this phase moves server.py onto `open_subtitles_db`).

## 2026-10-04 - Step 7 - Phase 2 (Single opener, flock-tied recovery) - checkpoint outcome (run 1)

`tests/tmp/test_54_translate_job_handle_phase2.py` exited 0 after the phase landed (4 passed). Phase 1's checkpoint still passes (8 passed). Bare suite run over the changed groups: test_internal_events 9, test_internal_translate 115, test_random_cache 28, test_search_fusion 10, test_server_config 33, test_similar 83, test_subtitles 7, test_translate_worker 67. 352 passed, exit 0.

<changes>
### engine/server/data/subtitles.py
- Added `open_subtitles_db(path)`: `path.parent.mkdir(parents=True, exist_ok=True)`, `connect_subtitles_db`, `ensure_subtitles_schema`; it closes the connection and re-raises if the migration raises.
- Added `open_translate_worker_store(path, lock_fd, finished_at)`: imports `fcntl` locally, runs `flock(lock_fd, LOCK_EX | LOCK_NB)` before anything touches the file, then `open_subtitles_db` and `_recover_translate_jobs`; returns `(conn, (requeued, failed))` and closes the connection if recovery raises.
- `recover_translate_jobs` renamed to private `_recover_translate_jobs`. Logic unchanged; docstring names its only caller.
- Module docstring names the two openers.

### engine/server/api/server.py
- Import is now `from data.subtitles import open_subtitles_db`. The two-line open is now `subtitles_db = open_subtitles_db(subtitles_db_path)`, in the same place. The comment now keeps only the `prepare_trending_override` ordering reason.

### engine/server/db/jobs/translate-worker.py
- Import drops `ensure_subtitles_schema` and `recover_translate_jobs` and adds `open_subtitles_db` and `open_translate_worker_store`. `connect_subtitles_db` stays for `heartbeat_loop`.
- `command_enqueue`: mkdir+connect+ensure becomes `open_subtitles_db` inside the existing `sqlite3.Error` handler.
- `command_run`: its own LOCK_NB acquire and exit 6 come first, as before. mkdir+connect+ensure+recover becomes `conn, (requeued, failed) = open_translate_worker_store(args.subtitles_db, lock_fd, now_ms())`, bound before the inner try/finally that closes it. `lock_fd` stays owned and closed here.
- The module docstring and the `command_run` docstring name the opener.

### tests/active/test_subtitles.py
- The recovery test runs through `open_translate_worker_store` under a flock the test holds (imports `fcntl` and `os`). Its assertions are unchanged. The docstring bullet is reworded.

### tests/active/test_internal_translate.py
- `_subtitles_db` opens through `open_subtitles_db`, so "as server.py opens it" is true again. The docstring's Store line is reworded.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

## 2026-10-04 - Step 7 - Phase 3 (Route store helper) - must_prove

- C1 - With the store closed, an instance track is answered ready and one `[translate] cache closed, track not stored` info line is logged.

## 2026-10-04 - Step 7 - Phase 3 (Route store helper) - self-check (audit round 1)

`tests/tmp/test_54_translate_job_handle_phase3.py`, surface `checkpoint`. It collects 2 tests.

- C1 - tests/tmp/test_54_translate_job_handle_phase3.py:47 - with `subtitles_db` None and the request host `PEER.Example.`, the records starting `[translate] cache closed, track not stored` are exactly `[(INFO, "... video_id=v-1 host=peer.example")]`. The answer at :45 is exactly ready/CUES/available false, with the caption list and track fetched (control :46) and nothing stored (control :48). - expected: one INFO record naming the row's canonical key. - excludes: today's route logs nothing (`[]`, observed red). Mutants observed red: logging at WARNING reads levelno 30; also logging on the closed read reads two records here and one in the no-track test (:66); naming the request's host reads `host=PEER.Example.`.

Answers:
1. Whole claim: the answer (:45), the one line (:47), its level and fields (:47), and the closed-store condition (open-store control :52-55) are each asserted.
2. Absence only: the no-line assertions (:55, :66) are armed by :47, which shows the line is emitted, and by the positive answers at :53 and :64.
3. Echoed literal: no. Expected values are literals from the harness (CUES, the message text).
4. One value: no. The host field is now separated from its input (`PEER.Example.` in, `peer.example` out), per the shape auditor's recommendation 1.
5. The double: none. The instance is the adapter's patch point (a system boundary), and the route and store are real.
6. It collects: 2 items.
7. Observed: every wrong-implementation reading above comes from mutation runs (tests/tmp/probe_54_phase3_mutants.py, run through delete_me/harvest_mutate.py). Each restore was exact and green.
8-9. Red, for the right reason: exit 1, test 1 failing at :47 `assert [] == [(20, '[translate] cache closed, track not stored video_id=v-1 host=peer.example')]`, after the controls at :45-46 passed. Test 2 passes today: it is the boundary that the line must not appear without a found track.
10. The expected values match the post-implementation run.

## 2026-10-04 - Step 7 - Phase 3 (Route store helper) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS. Predicted failure: test 1 at the log assertion (`[]`), test 2 passes. This matches the run. Recommendation 1 (host fixed point) taken: the host is sent as `PEER.Example.`. Recommendation 2 (test 2's negative already passes) noted: advisory, armed by test 1.
- AUDIT: devsecops-test-claim-auditor - PASS. CLAUSE MAP: 22 clauses, all CARRIED. No CRITICAL, no recommendations.

## 2026-10-04 - Step 7 - Phase 3 (Route store helper) - checkpoint outcome (run 1)

`tests/tmp/test_54_translate_job_handle_phase3.py`: 2 passed. Bare run over the changed groups: test_internal_translate 115, test_translate_worker 67, test_search_fusion 10. 192 passed, exit 0.

<changes>
### engine/server/api/handlers/internal_translate.py
- Added `_subtitles_store(server)`, a `@contextmanager` that holds `subtitles_db_lock` for the body and yields `subtitles_db` (None when closed). It catches nothing.
- `_read_key`, `_store_cues` and `handle_internal_translate_enqueue` use it. Each keeps its own `sqlite3.Error` handler and its own closed-store answer. The enqueue's beat check and enqueue stay in one hold.
- `_store_cues` on a closed store logs `[translate] cache closed, track not stored video_id=%s host=%s` at INFO and stores nothing. Its docstring says so.
- Imports `contextmanager` and `Iterator`. The module docstring says a closed store answers the track but does not store it.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

## 2026-10-04 - Step 7 - Phase 4 (Shared translatable-video resolve) - must_prove

- C1 - `resolve_translatable_video` returns `missing host`, `not in whitelist` or `host denied` for the matching case, and the row otherwise.

## 2026-10-04 - Step 7 - Phase 4 (Shared translatable-video resolve) - self-check and audit

`tests/tmp/test_54_translate_job_handle_phase4.py`, surface `checkpoint`. It collects 6 tests.

- C1 - :51 and :57: `resolve(v-1, None or "")` is `(None, "missing host")`, on the whitelist and on a closed connection whose lookup raises (control :56). :62, :63 and :67: an unknown id, the uuid on another host, and error_count at the threshold are each `not in whitelist` (controls :65, one error below the threshold, and :68, threshold 0). :74: d-1 with its denylist row active is `host denied`, while :76 (no host) and :77 (unknown id on the denied host) keep their own refusals (control :79, inactive, gives the row). :84: by id and by uuid, the canonical row and no refusal. - expected: as stated. - excludes, each observed red (tests/tmp/probe_54_phase4_mutants.py): host check after the lookup raises ProgrammingError at :57; denylist on the request host first reads `host denied` at :77; threshold dropped answers the row at :67; raw domain against the denylist answers the row at :74.

Red, for the right reason: exit 1, all 6 tests at `_resolve()` :33 with `AttributeError: module 'handlers.internal_translate' has no attribute 'resolve_translatable_video'`, the phase's new symbol. No control can run before it, as with phase 2's openers.

- AUDIT round 1: shape PASS. Claim PASS, with D1/N2 ("before any lookup") and D3 (denylist last) UNCARRIED, plus a one-sided error-count bound.
- Ledger: D1/N2 fixed (closed-connection assertions :55-57); D3 fixed (:76, :77); bound fixed (:64-65). None narrowed.
- AUDIT round 2: shape PASS (predicted AttributeError at :33, matching the run). Claim PASS, bounded: every row CARRIED. Observation 4 (error_threshold None never passed) is recorded and not taken: it is outside the ledger, and `fetch_video_row` treats None and 0 alike.

## 2026-10-04 - Step 7 - Phase 4 (Shared translatable-video resolve) - checkpoint outcome (run 1)

`tests/tmp/test_54_translate_job_handle_phase4.py`: 6 passed. Bare run over the changed groups: test_internal_translate 115 (route 400/404 parity tables unchanged), test_translate_worker 67 (worker refusal texts unchanged), test_search_fusion 10. 192 passed, exit 0.

<changes>
### engine/server/api/handlers/internal_translate.py
- Added `resolve_translatable_video(conn, video_id, host, error_threshold)`. It checks a missing host first, then `fetch_video_row` with the threshold, then the active denylist on the row's normalised domain. It returns `(row, None)` or `(None, refusal)`, takes no lock and writes no response.
- `_resolve_translate_key` keeps its body validation and three 400s. It now calls the shared resolve under one `server.db_lock` hold and answers 404 `VIDEO_NOT_FOUND` for any refusal.
- The `resolve_video_row` import is replaced by `fetch_video_row`. The `VIDEO_NOT_FOUND` comment and the module docstring are updated.

### engine/server/db/jobs/translate-worker.py
- `resolve_video` keeps its signature, `connect_readonly_db`, busy timeout and duration bound. It delegates to `resolve_translatable_video` and maps `missing host` to `not in whitelist`.
- Imports drop `list_active_denied_hosts` and `handlers.video.fetch_video_row` and add `resolve_translatable_video`. The `api/` path comment and the module docstring's enqueue sentence are updated.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
none
</unanticipated>

## 2026-10-04 - Step 8 - close on green

- Refactor pass: none made. Each phase landed the draft's shapes and added no duplication or hard-coding on the way to green. Nothing needed new behaviour.
- Inner unit tests: none written.
- Clause accounting: P1C1 and P1C2 by the phase 1 checkpoint, P2C1 and P2C2 by phase 2's, P3C1 by phase 3's and P4C1 by phase 4's. No exemptions. The four checkpoints run together: 20 passed, exit 0.
- `validate_tests.py --compare`: exit 0, 1 of 65 groups run (64 current and green in the record, each changed group having run green after its phase), "nothing moved against the previous record".

## 2026-10-04 - Step 9 - documentation

- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - update. Enqueue names `resolve_translatable_video`. Start-up step 5 names `open_translate_worker_store` (flock re-assert, mkdir, WAL open, migrate, recover). Pipeline step 2: the instance track is stored only while the claim holds (`end_ready_from_instance`), else the job is taken over. Crash: recovery runs only through the opener. Takeover: names the `TranslateJob` handle and its six methods, and the Engine's store in place of "B1".
- `engine/server/README.md` - update. The /internal/translate check names `resolve_translatable_video` (shared with the worker). The Cache bullet gains the closed-store info line. The store contract gains `open_subtitles_db`, `open_translate_worker_store` and the `TranslateJob` handle, and the instance source reads "while its claim holds". The Notes say the Engine opens through `open_subtitles_db`, creating the file and its parent directory.
- `engine/server/data/subtitles.py`, `engine/server/api/handlers/internal_translate.py`, `engine/server/db/jobs/translate-worker.py`, `engine/server/api/server.py` - updated in phases 1-4 (docstrings and comments recorded per phase).
- `CONTEXT.md` - update. "Instance caption track": the worker stores the track "and its claim still holds".
- `tests/active/test_subtitles.py`, `tests/active/test_translate_worker.py`, `tests/active/test_internal_translate.py` - updated in phases 1-2. Bullets for the new tests come with the harvest.
- `DEPLOYMENT.md` - no update. Line 98 (the Engine creates the file at first start) and line 271 (a refused second run exits 6 without opening `subtitles.db`) still hold, and it names no changed function.
- ADRs (`docs/project/adr/`) - none covers subtitles or translate. `docs/wiki/` does not exist.

## 2026-10-04 - Step 10 - harvest and close

Harvest run by hand under `workflows/harvest.md`; record `docs/project/plans/harvest-54-plan.md`. 11 DURABLE, 1 REPLACES (the active recovery test, archived to `tests/archive/54_translate_job_handle/`), 1 REDUNDANT, 1 SPENT. Each moved test was felled by a mutation of its own rule. `--audit-map` exit 0. `--compare` exit 0: 217 passed, 19 appeared, 1 gone.

Issue 54: `Status: enhancement, ready-for-agent` became `Status: enhancement, complete`, with a delivery line under its Comments. The file moved to `docs/project/issues/archive/` and its index row was deleted. Issue 57 (folded in) carries `wontfix` and is left as it is.
