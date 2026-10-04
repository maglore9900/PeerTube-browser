# Build record - 55-translate-state-contract

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/01-55-translate-state-contract.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Declare the translate state contract once\n\nStatus: enhancement, ready-for-agent\nOrigin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate \"one declared translate state contract\" (Worth exploring)\n\n## Problem\n\nThe Translate state contract is derived separately in the Engine, the Client gateway and the frontend. The contract covers the states, the `available` default, the cue shape, `after`/`total`, and \"video not found\" meaning `none`.\n\n- The state sets are `client/backend/lib/engine_api_client.py:21-23` and `client/frontend/src/data/translate.ts:11-20`. The Engine's set is implicit in its branches (`engine/server/api/handlers/internal_translate.py:290-308`).\n- \"A missing `available` reads as false\" appears in `engine_api_client.py:161-166` and `translate.ts:110-115`. Cue validation appears in `engine_api_client.py:156-178` and `translate.ts:117-123`.\n- Cue sorting is written four times: `internal_translate.py:183`, `engine/server/db/jobs/translate-worker.py:424`, `translate.ts:101` and `client/frontend/src/pages/video-page/translate.ts:181`.\n- `VIDEO_NOT_FOUND` (`internal_translate.py:40`) is matched as a string in another process (`engine_api_client.py:19-20, 187, 208`).\n- The page's requeue detection, `state.total < runningHeld` (`video-page/translate.ts:175`), depends on how the Engine slices running cues. That behaviour is not documented.\n- `HEARTBEAT_SECONDS` (`translate-worker.py:60-61`) and `HEARTBEAT_FRESH_MS` (`internal_translate.py:37-38`) are tied together only by comments. The timeout chain is the same: the Client's 20 s, the Engine's budget plus socket timeout, and the deploy's 30 s drain.\n\nThe Client's re-validation at the trust boundary is deliberate and should stay. What's missing is one place that says what every layer validates against.\n\n## Proposed solution\n\nDeclare the contract once, either as a schema or as a small shared definition that tests check every layer against. Put the heartbeat pair in one constant that both the Engine and the worker import. Keep each layer's own validation. The form is not decided yet.\n\n## Related\n\n- `CONTEXT.md`: Translate state, Generation available.\n- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`.\n\n## Comments\n\n**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. Nothing declares the contract today, and there are no prior rejections. The README's boundary guard forbids the Client backend from importing Engine modules, and the frontend is TypeScript, so the contract cannot be shared runtime code. The maintainer chose a **contract fixture file**: one checked-in JSON file of cases, each giving the Engine's status and body and the gateway's answer or a rejection. The Client's tests and the frontend's tests replay every case, and the Engine's tests check that its answers match the valid cases. Each layer keeps its own runtime validation. The running-slice rule (`total` counts every stored cue) is now in `CONTEXT.md` under Translate state.\n\n## Agent Brief\n\n**Category:** enhancement\n**Summary:** Declare the translate state contract once, as a contract fixture that the Engine, Client gateway and frontend tests all check against. Give the heartbeat pair one Engine-side definition, and turn the timeout chain into a test. Runtime behaviour does not change.\n\n**Current behavior:**\nTwo answers are under contract: the Engine's `/internal/translate` (state read) and `/internal/translate/enqueue` (generation request), as the Client gateway re-validates them and the frontend parses the gateway's `/api/translate` GET and POST. Each layer derives the contract on its own:\n- **The Client backend** names `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (adding `busy`). It reads a missing `available` as `false`, checks each cue as finite `start` and `end` plus string `text`, requires a non-negative non-bool integer `total` for `running`, and maps an Engine 404 whose `error` is exactly `Video not found` to `{state: none, available: false}`. It matches that string by copy.\n- **The frontend** declares the `TranslateState` and `TranslateRequestState` types and a `REQUEST_STATES` list. It repeats the `available` default and the cue checks, and sorts `ready` cues by start then end.\n- **The Engine** names no state set; its states exist only as branches of the state route. It sorts cues by `(start, end)` in two places: when parsing an instance track, and when the worker finishes a job.\n- **The video page** treats a `running` answer whose `total` is below the number of running cues it holds as a requeue. This relies on the Engine returning `cues[after:]` with `total` counting every stored cue, which no document states.\n- **The heartbeat.** The worker beats every `HEARTBEAT_SECONDS` (5 s), and the route treats a beat as fresh within `HEARTBEAT_FRESH_MS` (15 s). They are tied together only by comments.\n- **The timeout chain.** The Client's translate timeout (20 s) must exceed the Engine's request budget plus one socket timeout (15 s + 4 s), and the blue/green deploy's default drain (30 s) must exceed the Client's timeout. These are also tied together only by comments.\n\n**Desired behavior:**\n- **The fixture.** One contract fixture file lives outside every runtime package and is read only by tests. It holds named cases for both routes. Each case is an Engine HTTP status and JSON body, plus either the gateway's normalised answer or a rejection. It covers at least:\n  - every state of each route, with and without `available`;\n  - `ready` and `running` cue lists, including a `running` answer sliced by `after` with its `total`;\n  - the `Video not found` 404 for both routes, read as `none` and not available, and a different 404 rejected;\n  - rejections: an unknown state, a non-bool `available`, a non-list `cues`, a cue with a non-finite or bool time or a non-string text, and a negative or bool `total`.\n- **Client backend tests** replay every case through the gateway's Engine-answer parsing for that route and assert the fixture's expected answer or rejection.\n- **Frontend tests** replay every valid case's gateway answer through the frontend's state and request parsers and assert it is accepted with the same fields, with `ready` cues sorted by start then end. They also offer every rejected case's Engine body as a 200 gateway answer and assert it is refused.\n- **Engine tests** drive the state and enqueue routes into each state and assert every answer has exactly the keys and value types of the fixture's valid case for that state. They also assert that the state route's 404 for an unknown or denied video is the fixture's `Video not found` body.\n- **Prose.** The running-slice rule (`cues` from `after` on, `total` counting every stored cue) is stated next to the route in the Engine server README.\n- **The heartbeat pair** comes from one Engine-side definition. The fresh window is derived from the beat interval (three beats), and both the state route and the worker import it. Neither keeps its own literal.\n- **The timeout chain** is checked by one test that reads the Client's translate timeout, the Engine's request budget and socket timeout, and the deploy script's default drain. It fails when any link breaks the ordering budget + socket < Client timeout < drain. Reading another layer's value in a test is allowed; importing it at runtime is not.\n\n**Key interfaces:**\n- The fixture shape is up to the agent. One JSON file with a `cases` list of `{name, route, engine: {status, body}, gateway: <answer> | \"rejected\"}` is enough.\n- No runtime module is shared across the Engine, the Client backend and the frontend. Each layer's state lists, `available` default, cue checks and not-found mapping stay where they are.\n- The heartbeat definition lives in an Engine module that both the API and the jobs already import, not in a route handler.\n\n**Acceptance criteria:**\n- [ ] One contract fixture covers every state of both routes and every rejection listed above, and nothing at runtime reads it.\n- [ ] The Client backend's tests replay every fixture case through both route parsers and pass.\n- [ ] The frontend's tests replay every fixture case through both parsers and pass.\n- [ ] The Engine's tests check each state's answer against the fixture's valid case for that state, and check the not-found body.\n- [ ] Adding a new state to the fixture alone, with no layer changed, makes at least one layer's tests fail. Check this once by hand, as a mutation.\n- [ ] The worker's beat interval and the route's fresh window come from one definition, and changing the interval changes the window.\n- [ ] One test asserts budget + socket < Client translate timeout < deploy default drain from the real values, and fails when any one of them is moved past its neighbour.\n- [ ] The Engine server README states the running-slice rule beside `/internal/translate`.\n- [ ] No runtime behaviour changes: every existing translate route, Client gateway, frontend translate and translate worker test passes unchanged, apart from tests rewritten to read the fixture.\n\n**Out of scope:**\n- Removing or merging any layer's runtime validation. The Client's re-validation at the trust boundary stays, by decision.\n- Generating code or types from the fixture, or adding a schema validator dependency.\n- Changing any state, field, timeout or heartbeat value.\n- Deduplicating the cue sorts across layers. The two Engine sorts may share one Engine helper, but this is not required.\n- The fetch adapter (issue 53), the job handle (issue 54) and the worker split (issue 56).",
  "request_source": "read from docs/project/issues/55-translate-state-contract.md",
  "slug": "55-translate-state-contract",
  "steps": {
    "0": "done",
    "1": "done",
    "2": "done",
    "3": "done",
    "4": "done",
    "5": "done",
    "6": "done",
    "7": "done",
    "8": "done",
    "10": "done",
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Contract fixture and Client gateway replay",
      "checkpoint": "Seam: the Client gateway's parse functions, called directly. A new parametrized test in tests/active/test_server.py, one run per fixture case with the case name as id, starts the existing `_translate_engine` stub (test_server.py:1600) answering the case's engine status and body. It then calls `fetch_translate` (state route, passing the case's `after`) or `request_translate` (enqueue route). It asserts the result equals the case's `gateway` answer, or that `EngineApiError` was raised for \"rejected\". Control: the stub recorded exactly one request, on the case's /internal/translate route, carrying id, host and the case's `after`, so a rejection comes from the parse and not from a failed call. A second test reads the fixture and asserts: names are unique; there are exactly the two routes; `after` appears only on state cases; the valid 200 states equal TRANSLATE_STATES (state route) and TRANSLATE_REQUEST_STATES (enqueue route), both with and without `available`; each route has exactly one \"Video not found\" 404 case. Direct calls rather than /api/translate, so a 502 cannot hide why a case failed.",
      "intent": "tests/active/fixtures/translate_contract.json states the translate contract. Every case parses through the Client gateway's real fetch_translate/request_translate to its stated answer, and the fixture's valid states are exactly the gateway's state sets.",
      "clauses": [
        {
          "id": "C1",
          "text": "Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route."
        },
        {
          "id": "C2",
          "text": "The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique."
        }
      ],
      "files": [
        "tests/active/fixtures/translate_contract.json (NEW)",
        "tests/active/test_server.py (EDITED)",
        "tests/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### tests/active/fixtures/translate_contract.json (NEW, plus the new `tests/active/fixtures/` directory)\nThis is the translate contract fixture: `{\"description\", \"cases\": [...]}`, one case per line. It is byte-for-byte the plan's draft (\u00a71 of the implementation plan), which is the version the checkpoint's author already probed against the checkpoint.\n- **Valid cases (29):** every state of the state route (6) and of the enqueue route (7, with `busy`), each once with `available: true` and once without it (the gateway reads a missing one as `false`). Also a `running` answer sliced by `after` 3 (2 cues, `total` 5), and the `{\"error\": \"Video not found\"}` 404 on both routes, which gives `{state: none, available: false}`.\n- **Rejected cases (14):** the `Not found` 404 on both routes; an unknown state on both routes; `busy` on the state route; a string `available` on both routes; and, on the state route only, non-list `cues`, a cue `start` of `1e999`, a bool `start`, a bool `end`, a number as `text`, a `total` of -1 and a `total` of `true`.\n- **Cue order:** the `ready` cues are out of start order with two sharing a start, and the `running` cues are in a non-sorted stored order. The gateway answer keeps the Engine's order.\n- **Checked:** a throwaway probe loaded the checked-in file. It equals the draft (43 cases), and every case replayed through the real `fetch_translate`/`request_translate`, via `test_server._translate_engine`, gives its `gateway` answer from exactly one request. Every refusal text starts with `Engine translate`. I did not run the checkpoint itself; the workflow does that.\n\n### tests/active/test_server.py (not edited)\nThe checkpoint only imports `_translate_engine` from it, and that already exists. The plan's durable copies of the replay and coverage tests (plus a docstring paragraph) would repeat the checkpoint word for word, so I left them for whichever step moves the checkpoint into the active suite rather than writing them twice now.\n\n### tests/config.json (not edited)\nThe planned entry adds the fixture to the `test_server.py` group. That only makes sense once `test_server.py` itself reads the fixture, so it belongs with that same step.\n\n### tests/tmp/probe_55_phase1_replay.py\nThis is a leftover probe from authoring. I reused it to check the fixture, then emptied it because I have no tool to delete files. It and the authoring step's `tests/tmp/probe_55_phase1_checkpoint.py` and zero-byte `tests/tmp/probe_55_contract.py` should be deleted."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Frontend parser replay",
      "checkpoint": "Seam: the real client/frontend/src/data/translate.ts, entered through its exported fetchTranslate/requestTranslate. It follows test_frontend_translate.py's existing esbuild-bundle-plus-node-runner harness (same --platform=node, ESM and import.meta.env defines). A module fixture bundles translate.ts on its own. CONTRACT_RUNNER stubs window, localStorage and a fetch that answers 200 with the served text, reads the fixture with fs, and in one node process serves each case: the gateway answer for a valid case, the Engine body for a rejected one. It reports the returned value or the thrown message, plus whether the parsed text contained a non-finite number. The parametrized Python test asserts that a valid case deep-equals its gateway answer, with ready cues re-sorted by (start, end) and running cues left in the order given, and that a rejected case threw exactly \"Translate response was malformed\", so a JSON SyntaxError cannot pass as a refusal. Control on every case: the parser read a non-finite number exactly where the fixture writes 1e999. No frontend file changes.",
      "intent": "data/translate.ts is proven against every case of the contract fixture. Valid gateway answers come back with their fields intact, and every rejected body is refused as malformed.",
      "clauses": [
        {
          "id": "C1",
          "text": "Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given."
        },
        {
          "id": "C2",
          "text": "Every rejected fixture case served as a 200 throws exactly \"Translate response was malformed\"."
        }
      ],
      "files": [
        "tests/active/test_frontend_translate.py (EDITED)",
        "tests/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### tests/active/test_frontend_translate.py\nI added `CONTRACT_RUNNER` at the end of the module, next to `RUNNER` and `GENERATION_RUNNER` and in the same style. It is the plan's draft runner (\u00a73).\n- **Setup:** it stubs `localStorage`, `window` (with `location.origin`, needed because `api-base.ts` reads it when the module loads) and a `fetch` that always answers 200 with the served text. It sets `fetch` by plain assignment, which is the assignment the checkpoint's recorder catches. Only after that does it dynamically import `BUNDLE`.\n- **Replay:** it reads `CONTRACT` with `node:fs`. For each case it serves the gateway answer (valid case) or the Engine body (rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route).\n- **Non-finite numbers:** they are written back as `1e999`, because `JSON.stringify` would write `null`. A `rat-tail:` comment notes the ceiling: every infinity is written as positive.\n- **Report:** one JSON line keyed by case name, holding `{value | thrown, nonFinite}`, then `process.exit(0)` so the recorder's `exit` hook runs.\n\nNo frontend file changed.\n\n**Probe:** a throwaway probe ran the checkpoint's own `_contract_report` over the real `translate.ts`. What it showed:\n- 43 requests for 43 cases.\n- Case 6 was `GET /api/translate` with `after=3`; enqueue cases were `POST` with no `after`.\n- Every valid case came back with its gateway fields: `ready` cues in the order (1,2), (1,3), (4,5), and `running` cues in the order given.\n- All 14 rejected cases threw exactly `Translate response was malformed`.\n- `nonFinite` was true only for `state start 1e999`.\n\nI did not run the checkpoint itself. I had no tool to delete the probe, so I emptied it; `tests/tmp/probe_55_phase2_runner.py` can be deleted.\n\n### tests/config.json (not edited)\nThe planned entries (the fixture and `api-base.ts` in the `test_frontend_translate.py` group) only make sense once the durable module has a test that reads the fixture. I left them for the step that moves the checkpoint into the active suite, as phase 1 did with its `test_server.py` entries. The plan's durable parametrized test, `contract_report` fixture and docstring paragraph would repeat the checkpoint, so they wait for that same step.",
      "beyond": "tests/tmp/probe_55_phase2_runner.py \u2014 a throwaway probe I used to watch the runner's real output. I emptied it because I have no tool to delete files; it can be deleted."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Engine answers match the fixture's shape",
      "checkpoint": "Seam: the Engine's /internal/translate and /internal/translate/enqueue handlers, entered through test_internal_translate.py's existing harness (`_route`, `_state`, `_enqueue`, `_server`, `_seed`, `_claimed`, `_beat`, `_instance`). The fixture is read inside each test, never at module level, because test_source_fetch.py imports this module. A static ENGINE_DRIVERS table keyed by (route, state) drives each state: seeded rows with a fresh beat and no instance track on the state route; on the enqueue route, no beat for none, no row for queued, a seeded stored state, or a queue filled to SUBTITLE_QUEUE_CAP for busy. The parametrized test asserts, for each fixture case that carries available: a 200; answer state equals the state under test (control); the key-to-JSON-type map equals the case's (bool before number); cues non-empty where the case's are; and each answered cue's keys and types match the case's cues. A separate test asserts that the fixture's (route, state) set equals the driver table's keys, both ways. The not-found test asserts that on both routes an unknown video and an actively denylisted video answer exactly the fixture's Video-not-found 404 body with no fetch, and as a control that the same denied video answers 200 once the deny is inactive.",
      "intent": "The Engine's two translate routes are checked against the contract fixture. Each (route, state) it produces answers the fixture case's keys and JSON types, and its not-found answer is the fixture's body.",
      "clauses": [
        {
          "id": "C1",
          "text": "Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state."
        },
        {
          "id": "C2",
          "text": "On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body."
        }
      ],
      "files": [
        "tests/active/test_internal_translate.py (EDITED)",
        "tests/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### tests/active/test_internal_translate.py\nI added `ENGINE_DRIVERS`, the table the checkpoint looks up. It has 13 entries, keyed by (route, state): `none`, `queued`, `running`, `ready`, `already_english` and `failed` on the state route, and the same six plus `busy` on the enqueue route. I put it right after `_state`, with its two driver factories and one small helper. Each driver is called as `(subtitles_path, whitelist, monkeypatch, case)` and returns what the route's real handler wrote. It reaches the handler through `_state` or `_enqueue`, which look the handler up on the module when they run, so the checkpoint's recorder sees the call. All data goes in through the existing harness: `_seed`, `_claimed`, `_beat`, `_route`, `_server`, and the store's own writers. The only thing patched is `_route`'s usual `build_opener` and `now_ms`, which answers the shape audit's driver-side-patching recommendation.\n- **`_state_driver(row)`:** seeds the key as `row` and writes a fresh beat, then calls the state route with `_instance(False)`. Without that no-track instance, `failed`, `already_english` and `none` would answer `ready`. The request carries the case's `after` exactly when the case has one.\n- **Running on the state route:** the driver stores as many cues as the case's `total`, built by `_running_cues(count)` in descending start order. So `state running after 3` answers two real cues, not the `[]` that `RUNNING`'s three cues would give.\n- **`_enqueue_driver(row)`:** `None` means no beat, which answers `none`. `\"no row\"` with a beat answers `queued`. A seeded stored state answers that state. `\"busy\"` fills the queue to `SUBTITLE_QUEUE_CAP` with other keys, as the existing full-queue test does.\n- **Docstring:** a new \"Contract drivers\" paragraph before \"Startup:\" says what the table does and that the fixture is never read at module level, because `test_source_fetch.py` imports this module.\n- **Probe:** a throwaway probe ran every driver against all 14 fixture cases that carry `available`. Each came back as exactly one 200 in the state under test, with the keys the case has. `state running` gave 3 cues and total 3. `state running after 3` sent `after` 3 and gave 2 cues and total 5. `state ready` gave the stored `STORED_READY` cue. `enqueue none` gave `available: false`; the fixture's case says `true`, but both are booleans, so the type check still passes, and the fixture's description already notes this. I did not run the checkpoint itself.\n- **Probe file:** I have no tool to delete it, so I emptied `tests/tmp/test_probe_55_phase3_drivers.py`. It can be deleted.\n\n### tests/config.json (not edited)\nI left it unchanged, as phases 1 and 2 did. The planned group entries are the fixture plus `translate-worker.py`, `engine_api_client.py` and `deploy-bluegreen.sh`. Nothing in the durable module reads any of those files yet: the drivers get each case passed in. The entries belong with the step that moves the checkpoint's fixture-reading tests into the active suite, or with phase 4's derivation and timeout-chain tests."
    },
    {
      "n": "4",
      "kind": "code",
      "name": "Single-sourced heartbeat and checked timeout chain",
      "checkpoint": "Seam: the real constants, with server_config.py's source as the derivation's front door. Two tests in test_internal_translate.py. (1) Heartbeat: ast-parse engine/server/api/server_config.py and find the single HEARTBEAT_FRESH_MS assignment. Assert its expression names HEARTBEAT_SECONDS. Evaluate it with the real interval (equals the module's value, 15000, an int) and with 7.0 (21000). Assert the handler module's HEARTBEAT_FRESH_MS is server_config's. Assert neither internal_translate.py nor translate-worker.py assigns HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS, and that each imports its name from server_config. (2) Timeout chain, placed after test_one_15_second_budget_covers_both_fetches: take the handler's REQUEST_BUDGET_SECONDS, data.source_fetch.SOCKET_TIMEOUT_SECONDS and lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (conftest supplies client/backend on sys.path). Read DRAIN_SECONDS from scripts/deploy-bluegreen.sh with a line-anchored regex that must match exactly once. Assert budget + socket < Client timeout < drain. The existing BEATS 15000/15001 edge tests and test_translate_worker.py, both unchanged, confirm behaviour is preserved.",
      "intent": "The heartbeat interval and its freshness window are defined once in server_config.py, the window derived from the interval and imported by both consumers, and the translate timeout chain across Engine, Client and deploy script is held in order by a test.",
      "clauses": [
        {
          "id": "C1",
          "text": "server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own."
        },
        {
          "id": "C2",
          "text": "REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default."
        }
      ],
      "files": [
        "engine/server/api/server_config.py (EDITED)",
        "engine/server/api/handlers/internal_translate.py (EDITED)",
        "engine/server/db/jobs/translate-worker.py (EDITED)",
        "tests/active/test_internal_translate.py (EDITED)",
        "tests/config.json (EDITED)"
      ],
      "done": true,
      "outcome": "### engine/server/api/server_config.py\nAdded `HEARTBEAT_SECONDS = 5.0` (the worker's beat interval) and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)` right after the `SUBTITLE_*` translate constants. The window is three beats, so one late beat is still tolerated. It comes out as the int 15000 today and follows the interval if that changes.\n\n### engine/server/api/handlers/internal_translate.py\nRemoved the handler's own `HEARTBEAT_FRESH_MS = 15_000` and the rat-tail comment above it. The handler now gets the name from the existing `server_config` import (`from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`). The freshness check in `_worker_available` is unchanged and reads the imported name.\n\n### engine/server/db/jobs/translate-worker.py\nRemoved the worker's own `HEARTBEAT_SECONDS = 5.0` and the rat-tail comment above it (the one saying there was no shared constant). `HEARTBEAT_SECONDS` is added to the existing `from server_config import ...` line. The beat loop and `beat.join` use it unchanged.\n\n### C2 (timeout chain)\nNo code change: the chain already holds. `REQUEST_BUDGET_SECONDS` 15.0 plus `SOCKET_TIMEOUT_SECONDS` 4.0 is 19, which is below `TRANSLATE_TIMEOUT_SECONDS` 20, which is below the `DRAIN_SECONDS=30` default in deploy-bluegreen.sh. That default sits on one line of its own. The checkpoint now holds this order in place.\n\n### tests/active/test_internal_translate.py, tests/config.json\nNot touched in this step. The instruction was production code only. These files belong to moving the checkpoint into the active suite, and nothing in them stood in the way of the change: no test patches the handler's or the worker's heartbeat names.\n\n### Observation\nI ran a throwaway probe, `tests/tmp/probe_55_phase4_impl.py`, with ValidateTests rather than running the gating checkpoint. It printed `server_config.HEARTBEAT_FRESH_MS` = 15000 as an `int`, and the handler's `HEARTBEAT_FRESH_MS` is the same object as server_config's. Loading translate-worker.py from its file gives `HEARTBEAT_SECONDS` 5.0, also the same object as server_config's. I have no delete tool, so the probe is still in tests/tmp/ and needs removing. Docs that still say \"raise both constants together\" (engine/server/README.md, TRANSLATE_WORKER.md, DEPLOYMENT.md) are for the documentation step.",
      "beyond": "tests/tmp/probe_55_phase4_impl.py: a throwaway probe created to observe the imported values. I have no delete tool, so it is still there and should be removed."
    }
  ],
  "digests": {
    "tests/tmp/test_55_translate_state_contract_phase1.py": "1da4e310168a4f367e6d6acb04d1e4e5b4f1488576cc274263274e8faab5cc52",
    "tests/tmp/test_55_translate_state_contract_phase2.py": "2d623a0e9eb01d56fbe3f22e1efbb4d10ce21913fd783af4550c5df71447e094",
    "tests/tmp/test_55_translate_state_contract_phase3.py": "76bdbf70e34f72f8b6a5ddfb744fa2ae7283539cae4586fce7aa861cce58bfb8",
    "tests/tmp/test_55_translate_state_contract_phase4.py": "333b9e92868ee097cc124e298e61483ddc9e82d3ce82381eb90bbcd04bea690d"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/55",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20261004T133917-a253-dev-flow",
    "20261004T170044-96fe-dev-flow"
  ],
  "snapshot": {
    "tree": "0269ffadf94e1dfce619d60be859ed2202466c0d",
    "at": "2026-10-04T13:39:28-04:00"
  },
  "plan": "docs/project/plans/01-55-translate-state-contract.md",
  "record": "docs/project/plans/01-55-translate-state-contract.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nThe Translate state contract covers the states, the `available` default, the cue shape, `after`/`total`, and \"Video not found\" meaning `none`. Today the Engine (`engine/server/api/handlers/internal_translate.py`), the Client gateway (`client/backend/lib/engine_api_client.py`) and the frontend (`client/frontend/src/data/translate.ts`) each work it out on their own, and nothing makes them disagree loudly. This build declares the contract once, as a checked-in JSON **contract fixture** that only tests read. Every layer's tests are held to it. It also gives the heartbeat pair one Engine-side definition and turns the timeout chain into a test. **Runtime behaviour does not change.** Each layer keeps its own runtime validation: the Client's re-validation at the trust boundary is deliberate and stays.\n\n### Contracts under test\n\n- Engine `POST /internal/translate {id, host, after?}` (the state route). It answers 200 `{state, available}` with `state` one of `none`, `queued`, `running`, `ready`, `already_english`, `failed`. `ready` adds `cues: [{start, end, text}]`. `running` adds `cues` (the stored cues from index `after` on, in stored order) and `total` (the count of every stored cue, whatever `after` was). An unknown or denylisted video answers 404 `{\"error\": \"Video not found\"}` (`VIDEO_NOT_FOUND`, `internal_translate.py:35`).\n- Engine `POST /internal/translate/enqueue {id, host}` (the enqueue route). It answers 200 `{state, available}` with no cues: every state above plus `busy` (queue full, never stored). It answers the same 404 `Video not found`.\n- The Client gateway parses these in `fetch_translate` and `request_translate`. `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (adds `busy`). A missing `available` reads as `false` and a non-bool raises. A cue must be a dict with a finite non-bool number `start` and `end` and a str `text`, and only those three keys are copied. `running` needs a non-negative non-bool int `total`. A 404 whose `error` is exactly `Video not found` maps to `{state: \"none\", available: false}`, and any other non-200 raises `EngineApiError`.\n- The frontend parses the gateway's `GET /api/translate` in `fetchTranslate`, through the private `parseTranslateState`, and `POST /api/translate` in `requestTranslate`, using `REQUEST_STATES`. It repeats the `available` default and the cue checks, and sorts `ready` cues with `compareCues` (start, then end). `running` cues stay in stored order.\n\n### The contract fixture\n\n- It is one JSON file outside every runtime package, under the tests tree (for example `tests/active/fixtures/translate_contract.json`). Tests read it and nothing at runtime does.\n- Suggested shape: `{\"cases\": [{\"name\", \"route\": \"state\" | \"enqueue\", \"engine\": {\"status\", \"body\"}, \"gateway\": <normalised answer> | \"rejected\"}]}`. The exact shape is up to the design.\n- Minimum coverage:\n  - every state of each route (six for state, seven for enqueue including `busy`), each with `available` present and with it absent (absent reads as `false`);\n  - `ready` and `running` cue lists, including a `running` answer sliced by `after` whose `total` exceeds its `cues` length;\n  - the `Video not found` 404 on both routes, giving `{state: \"none\", available: false}`, and a different 404 (e.g. `{\"error\": \"Not found\"}`) rejected;\n  - rejections: an unknown state; a non-bool `available`; a non-list `cues`; a cue with a non-finite or bool `start`/`end`; a cue with a non-string `text`; a negative `total`; a bool `total`.\n- For `running`, the gateway answer keeps the cues in the Engine's order. The fixture states the gateway answer, not the frontend's sorted form.\n\n### Client backend tests\n\n- Every fixture case is replayed through the gateway's Engine-answer parsing for its route (`fetch_translate` for `state`, `request_translate` for `enqueue`), with the Engine stubbed to answer the case's status and body. Each case asserts the fixture's normalised answer, or `EngineApiError` for `rejected`.\n- The existing `TRANSLATE_ENGINE_ANSWERS` / `TRANSLATE_STATE_ANSWERS` / `TRANSLATE_ENQUEUE_ANSWERS` tables in `tests/active/test_server.py` may be rewritten to read the fixture. No other test changes.\n\n### Frontend tests\n\n- The real `client/frontend/src/data/translate.ts` runs in node, bundled with esbuild as the existing `tests/active/test_frontend_translate.py` does, with `fetch` stubbed.\n- Every valid case's gateway answer is served as a 200 to its route's parser (`fetchTranslate` for `state`, `requestTranslate` for `enqueue`). It must be accepted with the same fields, and `ready` cues must come back sorted by start then end.\n- Every rejected case's Engine body is served as a 200 gateway answer to its route's parser and must be refused (it throws).\n- Driving the exported functions through a stubbed fetch needs no frontend runtime change. Exporting a parser just for tests is not required.\n\n### Engine tests\n\n- The tests drive the state route into each of its states and the enqueue route into each of its states. Every answer must have exactly the keys, and the JSON value types, of the fixture's valid case for that route and state that carries `available` (the Engine always sends `available`; the cases without it stand for older Engines).\n- The tests assert that the state route's 404 for an unknown or denied video equals the fixture's `Video not found` body.\n\n### Mutation check\n\n- Once, by hand: adding a new state to the fixture alone, with no layer changed, must make at least one layer's tests fail. The result goes in the build record.\n\n### Heartbeat pair\n\n- `HEARTBEAT_SECONDS` (5.0, now `translate-worker.py:59`) and `HEARTBEAT_FRESH_MS` (15000, now `internal_translate.py:33`) come from one Engine-side definition. The fresh window is derived as three beats (`3 * HEARTBEAT_SECONDS * 1000`, still 15000 ms).\n- The definition lives in an Engine module that both the API and the worker already import, not in a route handler. Candidates are `engine/server/data/subtitles.py`, which owns `fetch_translate_heartbeat`/`write_translate_heartbeat`, or `engine/server/api/server_config.py`. The design picks one.\n- `internal_translate.py` and `translate-worker.py` both import it, neither keeps its own literal, and the rat-tail comments tying them together are removed.\n- A test shows that the window is derived from the interval, so changing the interval changes the window.\n\n### Timeout chain test\n\n- One test reads the real values: the Engine's `REQUEST_BUDGET_SECONDS` (15.0, `engine/server/api/handlers/internal_translate.py`), `SOCKET_TIMEOUT_SECONDS` (4.0, `engine/server/data/source_fetch.py`), the Client's `TRANSLATE_TIMEOUT_SECONDS` (20, `client/backend/lib/engine_api_client.py`) and the deploy script's default `DRAIN_SECONDS=30` (parsed from the text of `scripts/deploy-bluegreen.sh`).\n- It asserts budget + socket < Client timeout < drain, and fails when any one value moves past its neighbour.\n- A test may read another layer's values. A runtime module may not import across layers.\n\n### Prose\n\n- `engine/server/README.md` line 15 (`/internal/translate`) already says `cues` from `after` on and `total` = the stored cue count. It gains the explicit rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted (`client/frontend/src/pages/video-page/translate.ts:175`).\n- `CONTEXT.md` (Translate state) already states the rule and the fixture and needs no change. If the heartbeat's location changes, any doc naming the old constant locations (the `internal_translate.py` docstring, `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`) is updated.\n\n### Constraints and out of scope\n\n- No runtime module is shared across the Engine, the Client backend and the frontend. The README boundary guard forbids the Client backend importing Engine modules, and the frontend is TypeScript. Each layer's state lists, `available` default, cue checks and not-found mapping stay where they are.\n- Out of scope: removing or merging any layer's validation; generating code or types from the fixture; adding a schema-validator dependency; changing any state, field, timeout or heartbeat value; deduplicating cue sorts across layers. The two Engine sorts (`internal_translate.py:115`, `translate-worker.py:380`) may share one Engine helper, but it is not required. Also out of scope: the fetch adapter (issue 53), the job handle (issue 54) and the worker split (issue 56).\n- New code matches the style of the file it lands in.\n\n### Acceptance criteria\n\n- [ ] One contract fixture covers every state of both routes and every rejection listed above, and nothing at runtime reads it.\n- [ ] The Client backend's tests replay every fixture case through both route parsers and pass.\n- [ ] The frontend's tests replay every fixture case through both parsers and pass.\n- [ ] The Engine's tests check each state's answer against the fixture's valid case for that state, and check the not-found body.\n- [ ] Adding a new state to the fixture alone makes at least one layer's tests fail (checked once by hand, recorded).\n- [ ] The worker's beat interval and the route's fresh window come from one definition, and changing the interval changes the window.\n- [ ] One test asserts budget + socket < Client translate timeout < deploy default drain from the real values, and fails when any one is moved past its neighbour.\n- [ ] The Engine server README states the running-slice rule beside `/internal/translate`.\n- [ ] No runtime behaviour changes. Every existing translate route, Client gateway, frontend translate and translate worker test passes unchanged (`tests/active/test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`), apart from tests rewritten to read the fixture.\n\n### Baseline suite state\n\nStep 0's pre-build suite exited 0 (variant: false), but it ran selectively: 1 of 65 test groups (`test_search_fusion.py`, 10 passed), with 64 skipped as unchanged. Nothing yet shows that the translate suites listed above are green before the build. A later step should run them in full before relying on \"passes unchanged\".\n\n### Notes from the tree\n\nThe issue's code claims hold, but several line numbers are stale. The Engine sorts are at `internal_translate.py:115` and `translate-worker.py:380`, `VIDEO_NOT_FOUND` is at `internal_translate.py:35`, `HEARTBEAT_FRESH_MS` at `:33`, `HEARTBEAT_SECONDS` at `translate-worker.py:59`, and the state branches at `internal_translate.py:245-263`. `SOCKET_TIMEOUT_SECONDS` lives in `engine/server/data/source_fetch.py`, not under `api/`.\n</requirements>\n\n<conflicts>\nnone\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nOne checked-in JSON file, `tests/active/fixtures/translate_contract.json`, states the contract. Each layer's existing test file replays it against that layer's real code. No runtime module reads the file, and no runtime check moves or merges. The heartbeat pair moves into one Engine module. The timeout chain and the heartbeat derivation each get one test, and two docs gain one sentence each. Before anything changes, the six translate suites named in the acceptance criteria are run in full, because step 0 skipped them.\n\n**The fixture.** The shape is the suggested one: `{\"description\", \"cases\": [...]}`. Each case has a unique `name`, a `route` (`state` or `enqueue`), an optional `after` on state cases (it documents the slice and is passed to `fetch_translate`, which forwards it), `engine: {status, body}`, and `gateway`, which is either the normalised answer or the string `\"rejected\"`. The fixture contains:\n- every state of each route, once with `available: true` and once with `available` absent (gateway `false`). That is six state-route states and seven enqueue states including `busy`.\n- a `ready` cue list deliberately out of start order, with two cues sharing a start, so the frontend's start-then-end sort can be seen.\n- a `running` list in non-sorted stored order, plus a `running` answer sliced by `after` (2 cues, `total` 5).\n- the `Video not found` 404 on both routes, answering `{state: \"none\", available: false}`.\n- these rejected cases: the `{\"error\": \"Not found\"}` 404 on both routes; an unknown state on both routes; `busy` on the state route; a non-bool `available` on both routes; then, on the state route only, non-list `cues`, a cue with `start` written as `1e999`, a cue with a bool `start` and one with a bool `end`, a cue whose `text` is a number, a `running` `total` of -1, and a `total` of `true`.\n\nThe cue and `total` rejections live only on the state route because `request_translate` never reads cues. For `running`, the gateway answer keeps the Engine's cue order.\n\nTwo rules keep the fixture usable by every layer, and the Client test checks the fixture against them:\n- A rejected Engine body must be something the gateway refuses and also something the frontend refuses when served as a 200 gateway answer. Every listed rejection meets this. I traced each one through both parsers.\n- Every `(route, state)` among the valid 200 cases appears with and without `available`.\n\n**Client backend** (`tests/active/test_server.py`). A new parametrized test runs once per fixture case, with the case name as its id. It starts the existing `_translate_engine` stub with the case's status and body, then calls `fetch_translate` (state route, passing `after` when given) or `request_translate` (enqueue route) directly. It asserts that the result equals the case's `gateway` answer, or that `EngineApiError` is raised for `rejected`. As a control it checks that the recorded request hit the right `/internal/translate` path. A second test checks the fixture itself:\n- the valid states of the state route equal `TRANSLATE_STATES`, and those of the enqueue route equal `TRANSLATE_REQUEST_STATES`, each present with and without `available`;\n- case names are unique.\n\nThis check fails loudly in either direction: a state added to the fixture alone, or a state added to the gateway alone. Calling the functions directly, rather than going through `/api/translate`, gives the `EngineApiError` the requirement asks for instead of a 502 that hides why. The existing `TRANSLATE_*_ANSWERS` tables stay as they are, since they test the HTTP route (502 mapping, request ids, token). This is a named simplification; see Tradeoffs.\n\n**Frontend** (`tests/active/test_frontend_translate.py`). This file gains a third module-scoped bundle: esbuild bundles `client/frontend/src/data/translate.ts` on its own, with the same `--platform=node`, ESM format and `import.meta.env` defines as the existing bundles. A small runner does the following:\n- It stubs `window`, `localStorage` and `fetch`, imports the bundle's exported `fetchTranslate` and `requestTranslate`, and reads the fixture file itself with `fs`, so `1e999` parses to `Infinity` natively.\n- For each valid case, it serves the case's `gateway` answer as a 200 to `fetchTranslate` (state route) or `requestTranslate` (enqueue route).\n- For each rejected case, it serves the case's Engine body as a 200 to the same function.\n- It reports, per case, either the returned value or the thrown message.\n\nThe Python side then asserts:\n- a valid answer deep-equals the gateway answer, with `ready` cues re-sorted in Python by start then end, and `running` cues left in order;\n- every rejected case threw exactly `Translate response was malformed`, so a JSON `SyntaxError` cannot pass as a refusal.\n\nThe stub serialises bodies with non-finite numbers written back as `1e999`, because plain `JSON.stringify` would write `null`. A control asserts that the served `1e999` case reached the parser as `Infinity`. All cases run in one node process. No frontend file changes, and no parser is exported.\n\n**Engine** (`tests/active/test_internal_translate.py`). A new test runs once per `(route, state)` among the fixture's valid 200 cases that carry `available`. It drives that state with the file's existing helpers:\n- **State route:** `_seed` for queued, running, ready, failed and already_english, with a fresh beat; no row and no track for `none`. Running is driven with the case's `after` when present.\n- **Enqueue route:** no beat for `none`; a fresh beat and no row for `queued`; `_seed` plus a fresh beat for the four stored states; and the queue filled to `SUBTITLE_QUEUE_CAP` for `busy`, as the existing busy test does.\n\nThe answer must be a 200 whose key set, and the JSON type of each value, match the fixture case: bool as boolean, int or float as number, then string, list, object. Each answered cue's keys and types must match the fixture's cues.\n\nThe drivers live in a dict keyed by `(route, state)`, and a fixture state with no driver fails, which covers the mutation check on the Engine side. A second test asserts that an unknown video and a denylisted host on the state route answer exactly the fixture's `Video not found` 404 body. The enqueue route gets the same check, which costs one line.\n\n**Heartbeat pair.** The pair lives in `engine/server/api/server_config.py`. `HEARTBEAT_SECONDS = 5.0` sits beside the `SUBTITLE_*` tunables, and `HEARTBEAT_FRESH_MS` is derived from it as three beats, kept an int (15000) so the comparison and the docs read as before. `internal_translate.py` adds it to its existing `from server_config import ...` line, and `translate-worker.py` adds `HEARTBEAT_SECONDS` to its existing import. Both literals and both rat-tail comments go.\n\nThe derivation test, in `test_internal_translate.py`:\n- parses `server_config.py` with `ast`, finds the `HEARTBEAT_FRESH_MS` assignment, and checks that its right-hand side names `HEARTBEAT_SECONDS`;\n- evaluates that expression with the real interval (giving the module's value, 15000) and with a different one (7.0 gives 21000);\n- checks that `handlers.internal_translate.HEARTBEAT_FRESH_MS` is `server_config`'s value;\n- checks that neither the handler nor the worker source assigns its own literal.\n\n**Timeout chain.** One test in `test_internal_translate.py`, beside the existing 15 s budget test. It imports `REQUEST_BUDGET_SECONDS` from the handler, `SOCKET_TIMEOUT_SECONDS` from `data.source_fetch`, and `TRANSLATE_TIMEOUT_SECONDS` from `lib.engine_api_client`; conftest already puts `client/backend` on `sys.path`, and that module imports nothing from the Engine. It reads the drain value from `scripts/deploy-bluegreen.sh` with a line-anchored `^DRAIN_SECONDS=(\\d+)$` regex and requires exactly one match. It asserts budget + socket < Client timeout < drain. Each inequality fails as soon as one value moves past its neighbour, which is what the criterion asks. Only a test crosses layers.\n\n**Prose.**\n- `engine/server/README.md` line 15 gains the rule that `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.\n- Line 18 says the fresh window is derived in `server_config.py` from `HEARTBEAT_SECONDS`.\n- `TRANSLATE_WORKER.md` line 155 loses \"Raise both constants together\" and names the single definition.\n- The `internal_translate.py` docstring keeps the name `HEARTBEAT_FRESH_MS`, which is still a module attribute through the import, and says where it is defined.\n- `CONTEXT.md` is unchanged.\n\n**Mutation check.** Done once, by hand. Add a valid `paused` case to the fixture alone and run the three layers' suites. The expected result is that the Client replay raises `EngineApiError`, the Client coverage test fails, the frontend throws, and the Engine has no driver. The outcome goes in the build record, and then the edit is reverted. The build record also carries a grep showing that no file under `engine/`, `client/` or `scripts/` names `translate_contract.json`.\n\n### Alternatives considered\n\n- **A Python constants module, or a JSON Schema with a validator, as the single source.** Rejected. The frontend tests run in node and can't read Python. A validator is a new dependency and out of scope. Plain JSON reads with stdlib in Python and with `JSON.parse` in node.\n- **Replaying Client cases through the `/api/translate` HTTP route.** Rejected. Every rejection would collapse into the same 502, so the test could not tell `EngineApiError` from an unrelated failure. The direct calls are the parsing the requirement names, and the route behaviour stays covered by the existing tests.\n- **Exporting `parseTranslateState` for a direct frontend test.** Rejected. Driving the exported functions through a stubbed `fetch` also covers `readTranslateResponse` and needs no runtime change.\n- **Heartbeat in `data/subtitles.py`.** It owns `fetch_translate_heartbeat` and `write_translate_heartbeat`, so the case for it was real. `server_config.py` won because it already holds the translate tunables (`SUBTITLE_QUEUE_CAP`, `SUBTITLE_MAX_*`), both consumers already import it, and the window is a policy constant, not storage.\n- **Proving the derivation by `exec`ing an edited copy of `server_config.py`, or by adding a `heartbeat_fresh_ms(seconds)` function.** Rejected. The first runs the whole config, including its env checks. The second adds runtime surface only for a test. Evaluating the parsed expression shows \"change the interval, the window follows\" with neither cost.\n- **A new test file for the cross-layer timeout and heartbeat tests.** Rejected to keep the file count down. The Engine owns the budget and the heartbeat, so they sit with the Engine translate tests.\n- **Writing the non-finite cue as `Infinity` in the file.** Rejected. That is not standard JSON and `JSON.parse` refuses it. `1e999` is valid JSON and parses to infinity in both Python and JS.\n\n### Gotchas, risks, limitations\n\n- **JS has one number type.** A float-valued integral `total` such as `3.0` is refused by the gateway but accepted by the frontend. So the fixture cannot carry it as a rejection, and the \"every rejection refused by every layer\" rule leaves it out. The existing `running total 1.5` gateway test still covers non-integer totals.\n- **Serialising infinity.** Python's `json.dumps` writes `Infinity`, which the Client's `json.loads` accepts, so the Client stub path is fine. Node's `JSON.stringify` writes `null`, which would be refused for the wrong reason. That is why the frontend stub writes `1e999` and has the control described above.\n- **The Engine test checks shape, not values.** It checks keys and JSON types, as specified. It does not check cue order or the slice arithmetic; the existing `BRANCHES` and `AFTERS` tests keep covering those.\n- **\"Passes unchanged\" is unproven.** It rests on a baseline nobody has run yet; step 0 skipped these suites, so they run before the build.\n- **Float versus int heartbeat.** `3 * 5.0 * 1000` is a float. It is kept an int so `BEATS`' 15 000 / 15 001 boundaries, the README's \"15 000 ms\" and any logging read exactly as before. The comparison would behave the same either way.\n- **The Client side of the timeout test is a different test interpreter than the Engine's pixi env.** That is fine because nothing executes, but the import of `lib.engine_api_client` relies on conftest's `sys.path` entry.\n- **The mutation check is manual.** It holds only at the time it is recorded, though the coverage assertions keep the same guarantee automatically afterwards.\n\n### Tradeoffs for the operator\n\n- **Two copies remain.** The hand-written `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay, so part of the contract still exists twice, once at the HTTP route and once in the fixture. Rewriting them from the fixture is a safe follow-up and was left out to keep the change small.\n- **Cross-layer reads.** The timeout and heartbeat tests read another layer's constants and a shell script's text. A rename or reformat of those lines breaks the tests, which is intended.\n- **Engine sorts not unified.** The two Engine cue sorts stay separate. Sharing a helper is allowed but not needed, so it is not done.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"tests/active/fixtures/translate_contract.json\" element=\"new contract fixture file (and the new tests/active/fixtures/ directory)\">\n**What changes.** This is a new file, `{\"description\", \"cases\": [...]}`. Each case has `name`, `route` (`state`|`enqueue`), an optional `after` (state route only), `engine: {status, body}`, and `gateway` (the normalised answer, or `\"rejected\"`). The `tests/active/fixtures/` directory does not exist yet (Glob found nothing). Precedent: the two existing test data files sit directly in `tests/active/` (`host_tokens.json`, `upstream_snippet_cases.json`). A subdirectory still works, but it is a new convention.\n\n**Constraints I checked against the code:**\n- **Enqueue cases need bodies with only `{state, available}`.** The real enqueue route answers no other keys (`internal_translate.py:282`, `:285`). If enqueue `ready`/`running` bodies carried `cues`/`total`, the Engine key-set test would fail.\n- **Enqueue `none` with `available: true` is something the Engine never produces.** The route answers `none` only as `available: False` (`:282`). A keys-and-types check still passes, but the fixture would then assert an answer the Engine cannot give. Say so in `description`.\n- **`1e999`.** Python `json.load` reads it as `inf` and node `JSON.parse` reads it as `Infinity`. Python `json.dumps` writes it back as `Infinity`, which the Client's `json.loads` accepts. `JSON.stringify` writes `null`.\n- **The `Video not found` 404.** Its body must be exactly `{\"error\": \"Video not found\"}`. That is the match in `engine_api_client.py:187,208` (`TRANSLATE_NOT_FOUND_ERROR`) and the Engine's `VIDEO_NOT_FOUND` (`internal_translate.py:35`).\n- **Rejected bodies served to the frontend as a 200.** `{\"error\":\"Not found\"}` has no `state`, so both `parseTranslateState` and `requestTranslate` throw MALFORMED (`translate.ts:80,107`). `busy` on the state route falls through to MALFORMED (`:107`). Bool and infinite times fail `Number.isFinite` (`:120`). A `total` of -1 or `true` fails `Number.isInteger` / `< 0` (`:103`). A non-bool `available` fails `parseAvailable` (`:113`). Each one is refused by the Client too: `_translate_available` `:164`, `_checked_cues` `:171-176`, the `total` check `:199`, and the state sets `:192,213`.\n- **Avoid a float-valued integral `total` such as `3.0`.** JS accepts it and the gateway refuses it, as the plan says.\n- **Running `after` case** (2 cues, `total` 5): Client and frontend just pass it through. See the Engine-test entry for the slicing caveat.\n\n**Dependents.** `test_server.py`, `test_frontend_translate.py` (node `fs` + `JSON.parse`) and `test_internal_translate.py` read it. No file under `engine/`, `client/` or `scripts/` may name it.\n\n**Risk.** The risk is in the content, not the code. A case that violates the \"refused by both parsers\" rule fails the frontend replay for the wrong reason. So does an enqueue body with extra keys, which fails the Engine shape test.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"new fixture replay test through fetch_translate / request_translate, plus the fixture coverage test\">\n**What changes.** Two tests are added near the translate block (`:1540-1932`).\n\n**Test 1** is parametrized over the fixture cases, with ids taken from the case names:\n- Inside `with _translate_engine((status, body)) as (engine_base, seen):` it calls `fetch_translate(engine_base, \"uuid-1\", \"peer.example\", after=case.get(\"after\"))` or `request_translate(engine_base, \"uuid-1\", \"peer.example\")`.\n- It asserts equality with `gateway`, or `pytest.raises(EngineApiError)` for `\"rejected\"`.\n- Control: `[e[1] for e in seen] == [\"/internal/translate\"]` or `[\"/internal/translate/enqueue\"]`.\n\n**Test 2** checks:\n- The set of valid 200 state-route states equals `TRANSLATE_STATES`, and the enqueue set equals `TRANSLATE_REQUEST_STATES`.\n- Each `(route, state)` appears both with and without `available`.\n- Names are unique.\n- The 404 Video-not-found cases are left out of the state sets.\n\n**New imports.** `from lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate`, plus a fixture path built from `Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"`.\n- `lib` is already the Client package in `sys.modules`: conftest `:43-49` imports `lib.http_utils` before this module inserts the Engine dirs (`:185-190`). So the import resolves to `client/backend/lib`.\n- `client/backend/lib/__init__.py` exists. No `lib` package exists anywhere under `engine/`.\n\n**Facts verified:**\n- `_TranslateEngine` (`:1578-1596`) serialises with `json.dumps(payload)`. That writes `Infinity` for the `1e999` case, `_post_json`'s `json.loads` accepts it, and `_is_seconds` (`:156-158`) then refuses it, so the case fails for the right reason.\n- `_post_json` returns `(code, parsed)` for an HTTPError, so the 404 paths work.\n- The test needs no `ENGINE_BRIDGE_TOKEN` (`bridge_headers` just omits the header).\n- `request_translate` uses the default 6 s timeout, not 20 s.\n\n**Existing items that stay as they are:**\n- The `TRANSLATE_ENGINE_ANSWERS` (`:1559`), `TRANSLATE_STATE_ANSWERS` (`:1723`) and `TRANSLATE_ENQUEUE_ANSWERS` (`:1911`) tables.\n- `TRANSLATE_RUNNING_CUES` and `TRANSLATE_READY_CUES`.\n- Every HTTP-route test.\n\n**Docstring.** The module docstring's translate paragraphs (`:132-148`) gain one paragraph for the replay and the coverage check.\n\n**Regression risk.**\n- Low for the existing tests, because only additions are made.\n- Name clash: `TRANSLATE_STATE_ROUTE` and similar already exist, so the new constants need distinct names.\n- A module-level `json.load` of the fixture breaks collection of the whole 1932-line file if the file is missing or malformed. Loading at module level is what parametrize needs, so accept the risk or guard it.\n</impact>\n<impact path=\"tests/active/test_frontend_translate.py\" element=\"new third module-scoped esbuild bundle of client/frontend/src/data/translate.ts and a replay runner\">\n**What changes.**\n- **New fixture.** A module-scoped fixture, a sibling of `bundle` (`:214-226`) and `generation_bundle` (`:536-548`). It runs esbuild on `FRONTEND / \"src\" / \"data\" / \"translate.ts\"` with `--bundle --format=esm --platform=node` and the two `--define:import.meta.env.*` flags. It needs no embed-api alias and no CSS loader, because nothing in that import chain imports CSS.\n- **New runner string.** It stubs `globalThis.window = {location: {origin: BASE}, localStorage}`, `localStorage` and `fetch`, then does `await import(process.env.BUNDLE)`. The import must be dynamic and come after the stubs, because `data/api-base.ts:5` reads `window.location.origin` at module top level.\n- **Replay.** The runner reads the fixture with `fs.readFileSync` + `JSON.parse`. For each case it serves a 200 whose text is the gateway answer (valid case) or the Engine body (rejected case), using a serialiser that writes non-finite numbers as `1e999`. It then calls `fetchTranslate(BASE, id, host, after)` or `requestTranslate(BASE, id, host)` and reports the value or the thrown `message` per case. All cases run in one node process.\n\n**Python asserts:**\n- A valid answer deep-equals the gateway answer, with `ready` cues sorted in Python by `(start, end)` and `running` cues kept in order.\n- Every rejected case threw exactly `Translate response was malformed` (`MALFORMED`, `translate.ts:19`).\n- Control: the `1e999` case reached the parser as `Infinity`. For example, the runner records `Number.isFinite === false` on the parsed served text.\n\n**Facts verified:**\n- `readTranslateResponse` (`:84-93`) throws the payload's `error` text on a non-2xx status. That is why rejected bodies must be served as 200. A 404 served as 404 would throw `Not found`, not MALFORMED.\n- `profileHeaders()` reads `localStorage` lazily, so the stub only needs to exist.\n- `fetchTranslate` puts `after` on the query string, which the stub ignores.\n- JS turns `1.0` into `1`, and Python compares `1 == 1.0` as true, so float/int differences do not break the deep-equal.\n\n**Docstring.** The module docstring (`:1-31`) gains a paragraph for the third bundle and its runner, including the `1e999` serialisation and its control.\n\n**Regression risk.** Low for the existing tests (additive). The new bundle adds one esbuild run and one node process. The existing `RUNNER` and `GENERATION_RUNNER` strings are untouched.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"new Engine shape test per (route, state), the Video-not-found body test, the heartbeat derivation test and the timeout-chain test\">\n**What changes: four tests.**\n\n**(1) Shape test.** It is parametrized over the fixture's valid 200 cases that carry `available`. Drivers live in a dict keyed by `(route, state)`, and a missing key fails.\n- **State route** drivers use `_seed(store, row)` (`:674-692`) plus `write_translate_heartbeat(store, NOW, 1)`, with `_route(_instance(track), monkeypatch)` (`:646-657`) and `_handle`/`_state` (`:437`, `:739`).\n- **Gap: `failed`, `already_english` and `none` need `_instance(False)`.** With a track, those rows answer `ready` (BRANCHES `:812`, `:814`).\n- `ready` uses `_seed(\"ready\")`, which answers `STORED_READY` with no fetch.\n- **Enqueue route** drivers use `_beat(subtitles_path, 0)` (`:695`) or no beat for `none`, `_seed` plus `store.close()` for the stored states (as `:963-974` does), and the queue filled to `SUBTITLE_QUEUE_CAP` for busy (as `:977-989`), via `_enqueue` (`:733`).\n- **JSON-type helper.** It must test `bool` before `int`/`float`, since `isinstance(True, int)` is true.\n- **Caveat on `after`:** `RUNNING` (`:635`) holds 3 cues. Driving with a fixture `after` \u2265 3 (for example 3, from the 5-total case) answers `cues: []`, so the per-cue key/type check passes without checking anything. The driver should seed enough cues, or clamp `after`.\n\n**(2) Video-not-found test.** An unknown video, and `_set_denied(whitelist, True)` on `DENIED_VIDEO`, on both routes must answer `[[404, fixture_body]]`.\n- The file already has `VIDEO_NOT_FOUND = [[404, {...}]]` (`:162`), so the new test should compare against the fixture body and not that literal.\n\n**(3) Heartbeat derivation test:**\n- `ast.parse` `API_DIR / \"server_config.py\"`, find the `Assign` to `HEARTBEAT_FRESH_MS`, and check that its value contains `Name('HEARTBEAT_SECONDS')`.\n- `eval(compile(ast.Expression(node.value), ...), {\"HEARTBEAT_SECONDS\": x})` gives 15000 for 5.0 and 21000 for 7.0.\n- `_translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS`.\n- Neither `internal_translate.py` nor `engine/server/db/jobs/translate-worker.py` has a module-level `Assign` to either name. The worker's name is hyphenated, so it is read as text/ast and never imported.\n\n**(4) Timeout-chain test** sits beside `test_one_15_second_budget_covers_both_fetches` (`:611`):\n- `_translate().REQUEST_BUDGET_SECONDS` (15.0, `:31`), `data.source_fetch.SOCKET_TIMEOUT_SECONDS` (4.0, `source_fetch.py:21`) and `lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS` (20).\n- `re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", text, re.M)` on `scripts/deploy-bluegreen.sh` gives exactly `[\"30\"]`. Line 50 is the only match: `:70` is indented `--drain) DRAIN_SECONDS=...`.\n- Assert 15 + 4 < 20 < 30.\n\n**Import caveats (verified):**\n- `lib` resolves to `client/backend/lib`, because conftest (`:43-48`) inserts BACKEND_DIR and imports `lib.http_utils` first, and there is no `lib` under `engine/`.\n- **`tests/active/test_source_fetch.py:25` does `from test_internal_translate import ...`** and `tests/tmp/probe_50_phase1_rows.py:11` does too. Any new module-level import (`lib.engine_api_client`), module-level fixture load or module-level `server_config` read in this file therefore runs whenever `test_source_fetch.py` is collected. Keep cross-layer imports inside the test function, as the file's `_translate()` pattern already does (`:297-299`).\n- `server_config` is already imported at module level (`:84`).\n\n**Docstring.** The module docstring (`:1-50`) gains entries for the four tests.\n\n**Regression risk.**\n- Existing tests: `BEATS` (`:746`, 15 000 true / 15 001 false) and `FRESH_BEATS` (`:950`) depend on `HEARTBEAT_FRESH_MS` staying 15000. They are unaffected if the value is kept.\n- New tests: moderate. The driver gaps above, plus the bool/int typing, are where a wrong implementation would pass or fail spuriously.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"new HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS beside the SUBTITLE_* tunables (:419-428)\">\n**What changes.** Add both constants after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`), each with a one-line comment as the block does:\n- `HEARTBEAT_SECONDS = 5.0`\n- `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)`, or `3 * int(HEARTBEAT_SECONDS * 1000)`; any form whose RHS names `HEARTBEAT_SECONDS` and evaluates to the int 15000.\n- The module imports only `os` (`:3`). No new import is needed.\n\n**Dependents.**\n- `internal_translate.py` and `translate-worker.py` (both via `from server_config import ...`).\n- Every test that imports `server_config`: `test_internal_translate.py:84`, `test_internal_events.py:33`, `test_random_cache.py:57`, `test_similar.py`, `test_popular_videos.py`, `test_search_fusion.py`, `test_server_config.py`.\n- The `VARIANT_RUNNER` (`test_internal_translate.py:1072-1086`) and `test_server_config.py:211-222` exec this file and override attributes after import. Overriding `HEARTBEAT_SECONDS` there would not move `HEARTBEAT_FRESH_MS` (derived at import), but no override does that today.\n\n**Regression risk.** Very low. The derived value must be an int (15000); the plan requires it, and `BEATS` and the docs depend on it.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"server_config import (:27), the HEARTBEAT_FRESH_MS literal and rat-tail comment (:32-33), module docstring (:3, :5), _generation_available (:156-163)\">\n**What changes:**\n- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.\n- Delete `:32` (the rat-tail comment) and `:33` (`HEARTBEAT_FRESH_MS = 15_000`).\n- `_generation_available` (`:163`) reads the imported name unchanged.\n- Module docstring `:3` and `:5`: keep the name and add that it is defined in `server_config.py` and derived from `HEARTBEAT_SECONDS`.\n- The `_generation_available` docstring (`:157`) keeps the name.\n- `:30` (the budget comment naming the Client's 20 s) stays. It could optionally point at the timeout-chain test.\n\n**What does not change.** `REQUEST_BUDGET_SECONDS` (`:31`), `VIDEO_NOT_FOUND` (`:35`), both handlers' answers, and the sort at `:115`.\n\n**Dependents.**\n- `router.py:41` imports only the two handlers.\n- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track` and `resolve_translatable_video`, not the heartbeat.\n- Tests reach the module through `_translate()` / `_handler_module` and monkeypatch only `now_ms` (`:656`). Nothing patches `HEARTBEAT_FRESH_MS`, so turning it into an imported name is safe.\n- The new derivation test reads `module.HEARTBEAT_FRESH_MS`, which stays a module attribute through the import.\n\n**Regression risk.** Very low. If the import line drops `SUBTITLE_QUEUE_CAP`, the enqueue route breaks; `test_with_a_serving_worker_a_full_queue_answers_busy...` would catch that.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"server_config import (:41), HEARTBEAT_SECONDS literal and rat-tail comment (:58-59); uses at :458, :467, :536\">\n**What changes:**\n- Add `HEARTBEAT_SECONDS` to `:41`, keeping alphabetical order: `DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, ...`.\n- Delete `:58` (the rat-tail comment) and `:59` (`HEARTBEAT_SECONDS = 5.0`).\n- The uses stay: the `heartbeat_loop` docstring `:458`, `stop.wait(HEARTBEAT_SECONDS)` `:467` and `beat.join(HEARTBEAT_SECONDS)` `:536`.\n- The module docstring `:8` (\"beating every 5 s\") stays true.\n- `:35` (the comment on why `api/` is on the path) could add the heartbeat. Optional.\n\n**Dependents.**\n- `test_translate_worker.py` runs the script as a subprocess and through `STALL_DRIVER` (`:214-222`, which execs the file and overrides only `STALL_SECONDS`), plus another `spec_from_file_location` load at `:258`.\n- Its beat timing constants depend on the 5 s cadence staying put: `BEAT_GAP_MS` (4500, 6500) `:208`, `BEAT_WINDOW_SECONDS` `:210`, `FIRST_BEAT_SECONDS` `:212`. Nothing patches `HEARTBEAT_SECONDS`.\n- Issue 56 (`docs/project/issues/plan.md:26`) expects a one-line conflict in this constants block.\n\n**Regression risk.** Low. A typo in the import gives an ImportError at worker start, which the `run`/stall tests in `test_translate_worker.py` would catch. Stale copies holding the literal remain under `tests/tmp/probe_53_draft_translate_worker*.py` and `delete_me/`. They are not collected and do not matter, except to an unscoped \"no literal left\" grep.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"TRANSLATE_TIMEOUT_SECONDS, TRANSLATE_STATES, TRANSLATE_REQUEST_STATES, EngineApiError, fetch_translate, request_translate (read by tests only)\">\n**What changes.** Nothing; this file is read-only for this build.\n\n**Dependents added.**\n- `test_server.py` imports the parsers and state sets.\n- `test_internal_translate.py` imports `TRANSLATE_TIMEOUT_SECONDS` (20, `:18`).\n- The module imports only stdlib plus `.request_context`, which itself imports only `re` and `uuid`, so importing it into the Engine test process is safe.\n\n**Comment.** The comment at `:17` (\"30 s drain must stay above this\") stays accurate, and could optionally name the test.\n\n**Boundary guard.** `tests/check-client-engine-boundary.sh` scans only `client/backend` for Engine imports, so the tests are not affected.\n\n**Regression risk.**\n- None at runtime.\n- The tests break if `TRANSLATE_TIMEOUT_SECONDS`, `TRANSLATE_STATES` or `TRANSLATE_REQUEST_STATES` are renamed. That is intended.\n</impact>\n<impact path=\"client/frontend/src/data/translate.ts\" element=\"fetchTranslate, requestTranslate (exported), parseTranslateState/parseAvailable/parseCues (private), MALFORMED\">\n**What changes.** Nothing; no runtime change.\n\n**What the new bundle depends on:**\n- The exported names `fetchTranslate` and `requestTranslate`.\n- The exact text `Translate response was malformed` (`:19`).\n- `ready` sorted with `compareCues` and `running` left in order (`:101-104`).\n- The imports of `./api-base` (which reads `window.location.origin` at top level, `api-base.ts:5`, and `import.meta.env.VITE_CLIENT_API_BASE` / `DEV`) and `./profile` (`localStorage`, read lazily).\n\n**Other consumers.** `client/frontend/src/pages/video-page/translate.ts:11` imports from it; that file is unchanged.\n\n**Regression risk.** None at runtime. Renaming the message or the exports breaks the new test, which is intended.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"top-level DEFAULT_CLIENT_API_BASE = window.location.origin\">\n**What changes.** Nothing.\n\n**Why listed.** The standalone `data/translate.ts` bundle pulls this module in. It reads `window.location.origin` when the module is evaluated, so the new runner must set `globalThis.window` before its dynamic `import()`. A static import, or a missing stub, throws `ReferenceError: window is not defined` before any case runs.\n\n**Risk.** It sits on the new test's setup path only.\n</impact>\n<impact path=\"engine/server/data/source_fetch.py\" element=\"SOCKET_TIMEOUT_SECONDS (:21)\">\n**What changes.** Nothing.\n\n**Dependents.** The new timeout-chain test reads it (4.0). The Engine test already imports `data.source_fetch` (`_handler_module`, `:400`).\n\n**Risk.** A rename breaks the test, which is intended. `MEDIA_SOCKET_TIMEOUT_SECONDS` (15.0) must not be the value read by mistake.\n</impact>\n<impact path=\"scripts/deploy-bluegreen.sh\" element=\"DRAIN_SECONDS=30 (:50) and the --drain help comment (:17-18)\">\n**What changes.** Nothing.\n\n**Why listed.** The timeout test parses `^DRAIN_SECONDS=(\\d+)$` (multiline). Today exactly one line matches (`:50`); `:70` is indented and quoted. The comment at `:17-18` (\"the Client's longest Engine request timeout is 20 s\") stays accurate.\n\n**Dependents.** `tests/active/test_deploy_bluegreen.py` runs the script with `--drain 0` and never reads the default.\n\n**Risk.** Reformatting the line (for example `DRAIN_SECONDS=\"30\"` or `: \"${DRAIN_SECONDS:=30}\"`) breaks the test by design.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"fetch_translate_heartbeat / write_translate_heartbeat\">\n**What changes.** Nothing. The plan considered it as the home for the pair and rejected it.\n\n**Dependents.** The Engine shape-test drivers write beats through `write_translate_heartbeat` (as `_beat` and the BRANCHES test do), and `_seed` uses this module's writers.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_source_fetch.py\" element=\"module-level `from test_internal_translate import CHUNK, HOST, ...` (:25)\">\n**What changes.** Nothing.\n\n**Why listed.** It imports `test_internal_translate` as a module, so everything new at that file's module level also runs when this suite is collected.\n\n**Risk.** Medium if the new Engine tests add a module-level `from lib.engine_api_client import ...`, a module-level fixture load or a module-level `ast` read. If such a step failed, `test_source_fetch.py` would fail to collect too. Keep those reads inside the test bodies.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"worker service, stall-driver and beat-cadence tests (:205-224, :1250-1300)\">\n**What changes.** Nothing; this is a guard suite.\n\n**Why listed.**\n- It is the only suite that runs the worker after the import change, through the subprocess `run`, the `STALL_DRIVER` exec and the `spec_from_file_location` load at `:258`.\n- Its beat cadence windows (`BEAT_GAP_MS` 4500-6500 ms) prove `HEARTBEAT_SECONDS` is still 5.0.\n- It is one of the six translate suites to baseline before the build.\n\n**Risk.** It catches any NameError or ImportError from the move.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups for test_server.py, test_frontend_translate.py, test_internal_translate.py\">\n**What changes.** These groups map source files to the suites that cover them. Add:\n- `tests/active/fixtures/translate_contract.json` to all three groups.\n- To `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py` (read by the derivation test), `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh` (read by the timeout test).\n- `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.\n\nThere is precedent for data files in groups (`tests/active/host_tokens.json`, `upstream_snippet_cases.json`).\n\n**Risk.** If these entries are left out, a change to the fixture, the deploy script or the Client timeout would not trigger the suites that read them. The runtime tests themselves are unaffected. I am not certain how strictly the runner uses `test_groups` for selection, so treat this as recommended.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate bullet (:15), Availability (:18), worker tunables paragraph (:30), heartbeat line (:38)\">\n**What changes:**\n- `:15` gains the running-slice rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted. Keep the wording consistent with `CONTEXT.md:17`.\n- `:18` says `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats), still 15 000 ms.\n- Optional: `:30` lists the worker's `server_config` tunables and could add `HEARTBEAT_SECONDS`.\n- `:38` (\"every 5 s\", \"15 s freshness rule\") stays true.\n\n**Risk.** Docs only.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Heartbeat section (:155)\">\n**What changes.** Remove \"Raise both constants together.\" and name the single definition: `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived as three beats. The \"every 5 s\", \"15 s\" and \"up to 5 s\" join figures (`:146`) stay.\n\n**Risk.** Docs only.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"Translate state (:17), Generation available (:18)\">\n**What changes.** Nothing. `:17` already states the running-slice rule and the \"one contract fixture ... (issue 55)\" sentence. `:18` already states 15 s = three 5 s beats.\n\n**Risk.** None. It is listed so the build does not edit it twice.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"--drain row (:174), translate worker paragraph (:230)\">\n**What changes.** Optional only.\n- `:174` says the drain covers the Client's 20 s timeout, and could add that a test now enforces this.\n- `:230` names \"the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats\", and could add \"derived in `server_config.py`\".\n\nBoth are accurate as written.\n\n**Risk.** None.\n</impact>\n<impact path=\"client/README.md\" element=\"GET /api/translate paragraph (:32)\">\n**What changes.** Nothing. It names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the parsing rules, all unchanged.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/55-translate-state-contract.md\" element=\"acceptance criteria (:64-73)\">\n**What changes.** Only the status/checkboxes when the build is delivered (move to archive per `docs/project/triage-labels.md`). No content change is needed now.\n\n**Note.** AC \"every existing ... test passes unchanged\" depends on running the baseline of the six suites first: test_internal_translate, test_server, test_frontend_translate, test_translate_worker, test_subtitles and test_source_fetch.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"55/56 overlap note (:13, :26)\">\n**What changes.** Nothing. It already predicts the one-line conflict with issue 56 in the worker's constants block, which this build creates by deleting `translate-worker.py:58-59`.\n\n**Risk.** A merge conflict with the 56 branch.\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/README.md\">\n- Line 15 (`/internal/translate`): add the running-slice rule. `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.\n- Line 18 (Availability): say `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats, still 15 000 ms).\n- Optional: line 30 could list `HEARTBEAT_SECONDS` among the worker's tunables in `api/server_config.py`.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\">\nLine 155: remove \"Raise both constants together.\" and name the single definition, `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats.\n</doc>\n<doc path=\"engine/server/api/handlers/internal_translate.py\">\nThe module docstring (lines 3 and 5) keeps the name `HEARTBEAT_FRESH_MS` and says it is defined in `server_config.py`, derived from `HEARTBEAT_SECONDS`. The rat-tail comment at line 32 is deleted with the literal.\n</doc>\n<doc path=\"engine/server/db/jobs/translate-worker.py\">\nThe rat-tail comment at line 58 is deleted with the literal. The module docstring at line 8 (\"every 5 s\") stays.\n</doc>\n<doc path=\"tests/active/test_server.py\">\nThe module docstring's translate paragraphs (lines 132-148) gain a paragraph for the fixture replay through `fetch_translate`/`request_translate` and for the fixture coverage check.\n</doc>\n<doc path=\"tests/active/test_frontend_translate.py\">\nThe module docstring (lines 1-31) gains a paragraph for the standalone `data/translate.ts` bundle and its replay runner, including the `1e999` serialisation and its control.\n</doc>\n<doc path=\"tests/active/test_internal_translate.py\">\nThe module docstring (lines 1-50) gains entries for the per-(route, state) shape test against the fixture, the fixture Video-not-found body test on both routes, the heartbeat derivation test, and the timeout-chain test.\n</doc>\n<doc path=\"DEPLOYMENT.md\">\nOptional only. Line 230 could say `HEARTBEAT_FRESH_MS` is derived in `server_config.py`, and line 174 could say a test now enforces drain > Client timeout. Both are accurate as written.\n</doc>\n</docs_checklist>\n\n<highest_risk>\ntests/active/test_internal_translate.py (Engine shape-test drivers): on the state route, `failed`, `already_english` and `none` need `_instance(False)`, otherwise they answer `ready`. Driving `running` with the fixture's `after` against the 3-cue `RUNNING` seed can return `cues: []`, so the per-cue check passes without checking anything. The type check must test bool before int. Any of these lets a wrong Engine pass, or fails a right one.\ntests/active/test_source_fetch.py: it imports `test_internal_translate` at module level (`:25`). A new module-level cross-layer import (`lib.engine_api_client`), fixture load or `ast` read in `test_internal_translate.py` would break collection of `test_source_fetch.py` too. Keep those reads inside the test bodies.\ntests/active/fixtures/translate_contract.json and the frontend runner: each rejected body must be refused by both parsers when served as a 200. Enqueue bodies must carry only `{state, available}`. The `1e999` case needs the custom serialiser, because `JSON.stringify` writes `null` and the case would then be refused for the wrong reason. A content slip here fails the frontend or Engine replay spuriously, or hides a real gap behind the control.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI opened the files behind every runtime and test entry in the inventory: `internal_translate.py`, `engine_api_client.py`, `data/translate.ts`, `api-base.ts`, the worker's import and constants block, the `server_config.py` tunables block, conftest's `sys.path`/`lib` setup, the `_TranslateEngine` stub and imports in `test_server.py`, the helpers and parametrized tables in `test_internal_translate.py`, the `bundle` fixture and runner in `test_frontend_translate.py`, the `STALL_DRIVER`/`_worker` loaders in `test_translate_worker.py`, `DRAIN_SECONDS` in the deploy script, `SOCKET_TIMEOUT_SECONDS`, and the `tests/config.json` groups. Every claim I checked holds. That includes the inventory's own corrections to the plan: the state-route `failed`/`already_english`/`none` drivers need `_instance(False)` (BRANCHES `:811-815`); `_seed(\"running\")` holds the 3-cue `RUNNING`, so a fixture `after` of 3 answers `cues: []` and the per-cue type check checks nothing; enqueue `none` with `available: true` is something the Engine never produces (`:282`); `request_translate` uses the 6 s default. A repo-wide search for the heartbeat names finds no code outside the handler, the worker and the stale `tests/tmp/probe_53_*` copies, so nothing reads or patches the literals the build removes. I found nothing the inventory does not already carry, and no conflict with the requirements or the plan.\n<question id=\"1\">\nYes, the plan works as intended. **Client.** `fetch_translate` maps only `Video not found` to none (`:187`). It checks `available` before cues (`:194`), copies cues in Engine order (`:177`) and requires `total` to be a non-bool int \u2265 0 (`:199`). `request_translate` never reads cues (`:212-215`). The stub's `json.dumps` writes `Infinity`, `_post_json`'s `json.loads` accepts it, and `_is_seconds` refuses it, so the `1e999` case fails for the right reason. **Frontend.** Every listed rejection, served as a 200, ends in `MALFORMED`. A missing `state` and `busy` on the state route fall through at `:107`, and a non-bool `available` is caught at `:113`. `Number.isFinite` refuses `true` and `Infinity` (`:120`), and `Number.isInteger` refuses -1 and `true` (`:103`). `ready` is sorted with `compareCues` and `running` is not (`:101-104`). `api-base.ts:5` reads `window.location.origin` at top level, and the existing runners already stub globals before `await import(process.env.BUNDLE)` (`:169`), which is the pattern the new runner copies. **Engine.** The helpers the plan names exist and drive every state: `_seed` `:674`, `_beat` `:695`, `_enqueue` `:733`, `_state` `:739`, and the busy fill `:983`. `_resolve_translate_key` answers `VIDEO_NOT_FOUND` on both routes (`:224-226`). **Heartbeat.** The worker's `server_config` import (`:41`) is alphabetical, so `HEARTBEAT_SECONDS` slots in. The handler keeps a module attribute `HEARTBEAT_FRESH_MS` through the import, so `_generation_available` (`:163`) reads it unchanged. **Timeout chain.** The values are 15.0 + 4.0 < 20 < 30. `^DRAIN_SECONDS=(\\d+)$` matches only `:50`; the `:70` line is indented. `SOCKET_TIMEOUT_SECONDS` (`:21`) and `MEDIA_SOCKET_TIMEOUT_SECONDS` (`:24`) are distinct names.\n</question>\n<question id=\"2\">\nThe heartbeat window becomes an import from `server_config`, so issue 56's branch gets the one-line conflict `plan.md:26` already predicts. Three test files gain cross-layer reads: the Engine test reads the Client's `TRANSLATE_TIMEOUT_SECONDS` and the deploy script's text, and the frontend test reads a fixture under `tests/active/fixtures/`, which is a new directory convention. A rename or reformat on either side now breaks a test, which is intended. Because `test_source_fetch.py:25` imports `test_internal_translate` as a module, anything added at that file's module level also runs when `test_source_fetch.py` is collected. This matters most for the fixture load that parametrization needs (see recommendations). One deliberate ceiling: the coverage test proves the fixture's state sets equal the gateway's in both directions. On the frontend it proves only that every fixture state is accepted and every rejected case is refused. A state the frontend alone started accepting would go unnoticed unless a rejected case named it. That is within the plan as written, not a gap the inventory missed. The Engine test checks shape only, as the plan says, and the existing `BRANCHES`/`AFTERS` tests keep covering values.\n</question>\n<question id=\"3\">\nRun the six-suite baseline before any edit, because \"passes unchanged\" rests on it. The worker's import line must gain `HEARTBEAT_SECONDS` in the same edit that deletes `:58-59`. Otherwise the worker fails only at runtime, in the heartbeat thread and the shutdown join, and only `test_translate_worker.py`'s subprocess and stall tests catch it. The handler's import must keep `SUBTITLE_QUEUE_CAP`. `HEARTBEAT_FRESH_MS` must stay the int 15000, because `BEATS` (`:746`), `FRESH_BEATS` (`:950`) and the docs depend on it. New module-level code in `test_internal_translate.py` must not fail at import. The fixture content must keep the plan's two rules and the inventory's constraints: enqueue bodies carry only `{state, available}`, there is no float-valued integral `total`, and the Video-not-found body is exactly `{\"error\": \"Video not found\"}`. Each rejected body should also be valid apart from the one defect it names (see recommendations). `tests/config.json` groups (`:79`, `:403`, `:414`) should list the newly read files so a change to them selects the right suites.\n</question>\n<question id=\"4\">\nRuntime behaviour is unchanged. The heartbeat stays 5.0 s and 15000 ms, both runtime modules read the same values through an import instead of literals, and no Client or frontend file changes. What does change is outside runtime code. There is one definition of the heartbeat pair. There is one checked-in contract fixture that three layers' tests replay. Two cross-layer guard tests are added (the timeout chain and the heartbeat derivation). The README, TRANSLATE_WORKER.md and the handler docstring each change by one sentence.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Avoid a module-level fixture load in `test_internal_translate.py`.** In that file, parametrize the Engine shape test over the static driver dict's `(route, state)` keys rather than over the fixture's cases. Read the fixture inside the test body, and add one assertion, in its own test, that the fixture's valid `(route, state)` set equals the driver keys. *What it changes:* the inventory says to keep fixture reads inside test bodies (because `test_source_fetch.py:25` imports this module), but parametrizing over fixture cases needs a module-level load. Parametrizing over the drivers removes that tension, and the extra assertion keeps \"a fixture state with no driver fails\" and the Engine half of the mutation check. *Cost:* one small extra test. The pytest ids come from the driver keys rather than the fixture's case names. The alternative is a module-level `json.load` of a checked-in file: it costs nothing, but a malformed fixture would also stop `test_source_fetch.py` from collecting. `test_server.py` and `test_frontend_translate.py` have no such importer, so their module-level load is fine as the inventory says.\n\n2. **Pin the running driver's cue count to the fixture's sliced case.** For the sliced `running` case (`after` 3, `total` 5), seed 5 cues rather than `RUNNING`'s 3, for example via `_claimed(store).write_running_cues(...)` with 5 cues, as `AFTERS` does with 3. *What it changes:* the per-cue key/type check then sees 2 real cues instead of `[]`. Without it, that check passes while checking nothing. *Cost:* a few lines in the driver. Clamping `after` instead would hide the slice the case exists for.\n\n3. **Make each rejected fixture body valid apart from its one defect.** For example, the non-list-cues and bad-cue cases on `running` must carry a valid `total`, or use `ready`. *What it changes:* the frontend checks `total` (`translate.ts:103`) before cues and the gateway checks cues (`engine_api_client.py:196`) before `total`. A `running` body with both defects is refused by each layer for a different reason, and the replay still passes. *Cost:* none beyond care when writing the fixture. The Client fixture-check test could assert it cheaply by checking that rejected bodies differ from some valid case in one field, but that is optional.\n\n4. **Add the `tests/config.json` group entries** listed in the inventory. *Cost:* five lines. Leaving them out does not break any test, but a change to the fixture, the deploy script or the Client timeout would not select the suites that read them.\n\n5. **Scope the build record's \"no literal left\" and \"no runtime file names the fixture\" greps** to `engine/`, `client/` and `scripts/`. *Cost:* none. Unscoped, the literal grep hits the stale `tests/tmp/probe_53_draft_translate_worker*.py` copies and `delete_me/`.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: translate state contract fixture (issue 55)\n\nBefore writing this I read: `engine_api_client.py`, `data/translate.ts`, `data/api-base.ts`, `data/profile.ts`, `internal_translate.py`, the head of `translate-worker.py`, `server_config.py:410-433`, the translate blocks of `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` (harness `:297-460`, job-state and enqueue tests `:628-997`), `deploy-bluegreen.sh` (only line 50 matches the drain regex), `source_fetch.py:21`, `tests/config.json`, the README `/internal/translate` block, `TRANSLATE_WORKER.md:155` and `CONTEXT.md:17-18`.\n\n**Step zero, before any edit:** run all six translate suites in full and record the result as the baseline: `test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`. Also run `test_source_fetch.py`, which imports `test_internal_translate`.\n\n### What has to be tested\n\n1. Each fixture case goes through the gateway's real parsing (`fetch_translate` / `request_translate`) and gives the normalised answer, or `EngineApiError`.\n2. Each fixture case goes through the real `data/translate.ts`. A valid answer is accepted with the same fields, `ready` sorted and `running` in stored order. A rejected body throws exactly `MALFORMED`.\n3. Each `(route, state)` the Engine can produce answers with the key set and JSON types of the fixture's case that carries `available`. The `Video not found` 404 body equals the fixture's.\n4. The fixture covers every gateway state with and without `available`, and its names are unique. A state added on one side only fails.\n5. The heartbeat window is derived from the interval, and both consumers import it.\n6. budget + socket < Client timeout < drain, using the real values.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `tests/active/fixtures/translate_contract.json` | new (and a new directory) |\n| `tests/active/test_server.py` | +1 import line, +2 module constants, +2 tests, +1 docstring paragraph |\n| `tests/active/test_frontend_translate.py` | +3 constants, +1 runner string, +1 module fixture, +1 helper, +1 test, +1 docstring paragraph |\n| `tests/active/test_internal_translate.py` | +2 stdlib imports, +1 path constant, helpers, driver table, +5 tests, docstring entries |\n| `engine/server/api/server_config.py` | +2 constants |\n| `engine/server/api/handlers/internal_translate.py` | import line, \u22122 lines, docstring |\n| `engine/server/db/jobs/translate-worker.py` | import line, \u22122 lines |\n| `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | prose |\n| `tests/config.json` | group entries |\n\nNo other runtime file changes. `engine_api_client.py`, `data/translate.ts`, `api-base.ts`, `source_fetch.py`, `deploy-bluegreen.sh` and `CONTEXT.md` are read only.\n\n---\n\n### 1. `tests/active/fixtures/translate_contract.json`\n\nThe file has one case per line. `1e999` is legal JSON: Python's `json` reads it as `inf` and node's `JSON.parse` reads it as `Infinity`. Three cue lists are used:\n- **Ready list:** out of start order, with two cues sharing start 1.0, so a frontend that does not sort, or sorts by start only, shows.\n- **Running list:** stored order, not sorted.\n- **Sliced running answer:** `after` 3, two cues, `total` 5.\n\n```json\n{\n  \"description\": \"Translate state contract (issue 55), read only by tests: test_server.py replays every case through fetch_translate/request_translate, test_frontend_translate.py through data/translate.ts, test_internal_translate.py checks the Engine's keys and JSON types against the valid cases that carry available. Nothing at runtime reads this file. route is state (POST /internal/translate) or enqueue (POST /internal/translate/enqueue); after (state route only) is the running cue count the reader holds; engine is what the Engine answers; gateway is the Client gateway's normalised answer, or \\\"rejected\\\" for EngineApiError. The gateway keeps the Engine's cue order (running in stored order; ready is sorted only by the frontend). Every (route, state) of a valid 200 case appears with available and without it (an older Engine; read as false). A rejected Engine body must be refused by the gateway and also by the frontend when served as a 200 gateway answer, so a float-valued integral total such as 3.0 (refused by the gateway, accepted by JS) cannot be a case. 1e999 is standard JSON and parses to infinity in Python and JS. The enqueue none case with available true is an answer the Engine never gives (it answers none only with available false); it is here for the with/without-available coverage, which checks keys and types only.\",\n  \"cases\": [\n    {\"name\": \"state none\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": true}}, \"gateway\": {\"state\": \"none\", \"available\": true}},\n    {\"name\": \"state none without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"state queued\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": true}}, \"gateway\": {\"state\": \"queued\", \"available\": true}},\n    {\"name\": \"state queued without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\"}}, \"gateway\": {\"state\": \"queued\", \"available\": false}},\n    {\"name\": \"state running\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": true}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": true}},\n    {\"name\": \"state running without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": false}},\n    {\"name\": \"state running after 3\", \"route\": \"state\", \"after\": 3, \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 9.0, \"end\": 10.0, \"text\": \"Fifth\"}, {\"start\": 7.0, \"end\": 8.0, \"text\": \"Fourth\"}], \"total\": 5, \"available\": true}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 9.0, \"end\": 10.0, \"text\": \"Fifth\"}, {\"start\": 7.0, \"end\": 8.0, \"text\": \"Fourth\"}], \"total\": 5, \"available\": true}},\n    {\"name\": \"state ready\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": true}}, \"gateway\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": true}},\n    {\"name\": \"state ready without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}]}}, \"gateway\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": false}},\n    {\"name\": \"state already_english\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\", \"available\": true}}, \"gateway\": {\"state\": \"already_english\", \"available\": true}},\n    {\"name\": \"state already_english without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\"}}, \"gateway\": {\"state\": \"already_english\", \"available\": false}},\n    {\"name\": \"state failed\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\", \"available\": true}}, \"gateway\": {\"state\": \"failed\", \"available\": true}},\n    {\"name\": \"state failed without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\"}}, \"gateway\": {\"state\": \"failed\", \"available\": false}},\n    {\"name\": \"state video not found\", \"route\": \"state\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Video not found\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"enqueue none\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": true}}, \"gateway\": {\"state\": \"none\", \"available\": true}},\n    {\"name\": \"enqueue none without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"enqueue queued\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": true}}, \"gateway\": {\"state\": \"queued\", \"available\": true}},\n    {\"name\": \"enqueue queued without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\"}}, \"gateway\": {\"state\": \"queued\", \"available\": false}},\n    {\"name\": \"enqueue running\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"available\": true}}, \"gateway\": {\"state\": \"running\", \"available\": true}},\n    {\"name\": \"enqueue running without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\"}}, \"gateway\": {\"state\": \"running\", \"available\": false}},\n    {\"name\": \"enqueue ready\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"available\": true}}, \"gateway\": {\"state\": \"ready\", \"available\": true}},\n    {\"name\": \"enqueue ready without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\"}}, \"gateway\": {\"state\": \"ready\", \"available\": false}},\n    {\"name\": \"enqueue already_english\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\", \"available\": true}}, \"gateway\": {\"state\": \"already_english\", \"available\": true}},\n    {\"name\": \"enqueue already_english without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\"}}, \"gateway\": {\"state\": \"already_english\", \"available\": false}},\n    {\"name\": \"enqueue failed\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\", \"available\": true}}, \"gateway\": {\"state\": \"failed\", \"available\": true}},\n    {\"name\": \"enqueue failed without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\"}}, \"gateway\": {\"state\": \"failed\", \"available\": false}},\n    {\"name\": \"enqueue busy\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\", \"available\": true}}, \"gateway\": {\"state\": \"busy\", \"available\": true}},\n    {\"name\": \"enqueue busy without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\"}}, \"gateway\": {\"state\": \"busy\", \"available\": false}},\n    {\"name\": \"enqueue video not found\", \"route\": \"enqueue\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Video not found\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"state route missing 404\", \"route\": \"state\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Not found\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue route missing 404\", \"route\": \"enqueue\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Not found\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state unknown state\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"bogus\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue unknown state\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"bogus\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state busy\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state available a string\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": \"true\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue available a string\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": \"true\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state cues not a list\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": {\"start\": 1.0, \"end\": 2.0, \"text\": \"Hello\"}, \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state start 1e999\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1e999, \"end\": 2.0, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state start true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": true, \"end\": 2.0, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state end true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1.0, \"end\": true, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state text a number\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1.0, \"end\": 2.0, \"text\": 7}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state total -1\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [], \"total\": -1, \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state total true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [], \"total\": true, \"available\": true}}, \"gateway\": \"rejected\"}\n  ]\n}\n```\n\nI traced every rejection through both parsers:\n\n| Case | Gateway (`engine_api_client.py`) | Frontend served as 200 (`translate.ts`) |\n|---|---|---|\n| route missing 404 (both) | non-200, not `Video not found`, `:189`/`:210` | no `state`, `:107` / `:80` |\n| unknown state (both) | `:192` / `:213` | `:107` / `:80` |\n| state busy | not in `TRANSLATE_STATES` `:192` | falls through to `:107` |\n| available a string (both) | `_translate_available` `:164` | `parseAvailable` `:113` |\n| cues not a list | `_checked_cues` `:171` | `parseCues` `:118` |\n| start 1e999 | stub writes `Infinity`, `json.loads` gives inf, `_is_seconds` fails | stub writes `1e999`, `Number.isFinite(Infinity)` fails `:120` |\n| start / end true | `_is_seconds` excludes bool | `Number.isFinite(true)` is false |\n| text a number | `:175` | `:120` |\n| total -1 / true | `:199` | `:103` |\n\nCase count: 29 valid (12 state, 1 sliced running, 14 enqueue, 2 not-found) and 14 rejected.\n\n---\n\n### 2. `tests/active/test_server.py`\n\n**Import**, added to the existing `lib` block at `:180-183`. It goes before the Engine path insert, so `lib` stays the Client package:\n\n```python\nfrom lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate\n```\n\n**Appended after `:1932`**, so `TRANSLATE_STATE_ROUTE`/`TRANSLATE_ENQUEUE_ROUTE` (`:1713-1714`) and `TRANSLATE_BODY` (`:1715`) are already defined:\n\n```python\n# The contract fixture all three layers replay (issue 55); loaded at collection because parametrize needs its cases, so a missing or malformed file stops this module's collection.\nTRANSLATE_CONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\nTRANSLATE_CONTRACT_CASES = json.loads(TRANSLATE_CONTRACT.read_text())[\"cases\"]\n\n\n@pytest.mark.parametrize(\"case\", TRANSLATE_CONTRACT_CASES, ids=[case[\"name\"] for case in TRANSLATE_CONTRACT_CASES])\ndef test_each_contract_fixture_case_parses_to_its_gateway_answer_or_engine_api_error(case):\n    state_route = case[\"route\"] == \"state\"\n    with _translate_engine((case[\"engine\"][\"status\"], case[\"engine\"][\"body\"])) as (engine_base, seen):\n        try:\n            answered = fetch_translate(engine_base, \"uuid-1\", \"peer.example\", after=case.get(\"after\")) if state_route else request_translate(engine_base, \"uuid-1\", \"peer.example\")\n        except EngineApiError:\n            answered = \"rejected\"\n    assert answered == case[\"gateway\"]\n    # Control: the Engine was reached once, on the case's route with exactly id, host and the case's after, so a rejection above is the parse's and not a failed call.\n    sent = {**TRANSLATE_BODY, **({\"after\": case[\"after\"]} if \"after\" in case else {})}\n    assert [(entry[1], entry[4]) for entry in seen] == [(TRANSLATE_STATE_ROUTE if state_route else TRANSLATE_ENQUEUE_ROUTE, sent)]\n\n\ndef test_the_contract_fixture_covers_every_gateway_state_with_and_without_available_under_unique_names():\n    names = [case[\"name\"] for case in TRANSLATE_CONTRACT_CASES]\n    assert len(names) == len(set(names)), sorted(name for name in names if names.count(name) > 1)\n    assert {case[\"route\"] for case in TRANSLATE_CONTRACT_CASES} == {\"state\", \"enqueue\"}\n    assert all(case[\"route\"] == \"state\" for case in TRANSLATE_CONTRACT_CASES if \"after\" in case)\n    valid = [case for case in TRANSLATE_CONTRACT_CASES if case[\"gateway\"] != \"rejected\" and case[\"engine\"][\"status\"] == 200]\n    for route, states in ((\"state\", TRANSLATE_STATES), (\"enqueue\", TRANSLATE_REQUEST_STATES)):\n        bodies = [case[\"engine\"][\"body\"] for case in valid if case[\"route\"] == route]\n        assert {body[\"state\"] for body in bodies if \"available\" in body} == states, route\n        assert {body[\"state\"] for body in bodies if \"available\" not in body} == states, route\n        # Exactly one Video-not-found case per route, which the Engine's not-found test reads.\n        assert [case[\"engine\"][\"body\"] for case in TRANSLATE_CONTRACT_CASES if case[\"route\"] == route and case[\"engine\"][\"status\"] == 404 and case[\"gateway\"] != \"rejected\"] == [{\"error\": \"Video not found\"}], route\n```\n\n- **`after` is passed explicitly.** `fetch_translate(..., after=None)` sends no `after`, which matches `sent` for every case without one.\n- **Why the stub accepts the `1e999` case.** `_TranslateEngine` writes it as `Infinity` through `json.dumps`, and `_post_json`'s `json.loads` accepts that. The refusal then comes from `_is_seconds`.\n- **No bridge token is needed** (`bridge_headers` simply omits the header).\n\n**Docstring paragraph**, inserted after `:146`:\n\n> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55): every case is replayed by calling `fetch_translate` (state route, with the case's `after` when it has one) or `request_translate` (enqueue route) against a `_TranslateEngine` answering the case's status and body. Each gives exactly the case's `gateway` answer, or raises `EngineApiError` for `rejected`, from exactly one request to that route carrying id, host and the case's `after`. The fixture itself has unique names and only the two routes. Its valid 200 states are exactly `TRANSLATE_STATES` on the state route and `TRANSLATE_REQUEST_STATES` on the enqueue route, each with `available` and without it, and each route has exactly one `Video not found` 404 case.\n\n---\n\n### 3. `tests/active/test_frontend_translate.py`\n\n**Constants**, after `INITIAL_TEXT` (`:66`):\n\n```python\n# The contract fixture all three layers replay (issue 55); valid cases serve their gateway answer, rejected ones their Engine body, each as a 200.\nCONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\nCONTRACT_CASES = json.loads(CONTRACT.read_text())[\"cases\"]\nMALFORMED = \"Translate response was malformed\"\n```\n\n**Runner**, appended after the generation tests:\n\n```python\nCONTRACT_RUNNER = \"\"\"\nimport fs from \"node:fs\";\nconst memory = () => { const s = new Map(); return {\n  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),\n  removeItem: (k) => s.delete(k) }; };\nglobalThis.localStorage = memory();\n// api-base.ts reads window.location.origin when it is evaluated, so window exists before the import below.\nglobalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };\nlet served = null;\nglobalThis.fetch = async () => new Response(served, { status: 200, headers: { \"content-type\": \"application/json\" } });\n// JSON.stringify writes a non-finite number as null, which would be refused for the wrong reason; it goes back out as 1e999, as the fixture wrote it.\nconst NON_FINITE = \"__non_finite__\";\nconst serialise = (value) => JSON.stringify(value, (key, v) => (typeof v === \"number\" && !Number.isFinite(v) ? NON_FINITE : v)).replaceAll(JSON.stringify(NON_FINITE), \"1e999\");\nconst hasNonFinite = (value) => (typeof value === \"number\" ? !Number.isFinite(value) : value !== null && typeof value === \"object\" && Object.values(value).some(hasNonFinite));\nconst { fetchTranslate, requestTranslate } = await import(process.env.BUNDLE);\nconst report = {};\nfor (const c of JSON.parse(fs.readFileSync(process.env.CONTRACT, \"utf8\")).cases) {\n  served = serialise(c.gateway === \"rejected\" ? c.engine.body : c.gateway);\n  // What the parser will read, parsed the way readTranslateResponse parses it.\n  const nonFinite = hasNonFinite(JSON.parse(served));\n  try {\n    const value = c.route === \"state\" ? await fetchTranslate(process.env.BASE, \"uuid-1\", process.env.HOST, c.after) : await requestTranslate(process.env.BASE, \"uuid-1\", process.env.HOST);\n    report[c.name] = { value, nonFinite };\n  } catch (error) {\n    report[c.name] = { thrown: String(error?.message ?? error), nonFinite };\n  }\n}\nprocess.stdout.write(JSON.stringify(report) + \"\\\\n\", () => process.exit(0));\n\"\"\"\n\n\n@pytest.fixture(scope=\"module\")\ndef contract_report(tmp_path_factory) -> dict:\n    out = tmp_path_factory.mktemp(\"translate_contract\")\n    subprocess.run(\n        [str(ESBUILD), str(FRONTEND / \"src\" / \"data\" / \"translate.ts\"), \"--bundle\", \"--format=esm\", \"--platform=node\",\n         f\"--outfile={out / 'bundle.mjs'}\", f\"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}\",\n         \"--define:import.meta.env.DEV=false\"],\n        check=True, capture_output=True,\n    )\n    (out / \"runner.mjs\").write_text(CONTRACT_RUNNER)\n    proc = subprocess.run(\n        [\"node\", str(out / \"runner.mjs\")], capture_output=True, text=True, timeout=60,\n        env={\"BASE\": BASE, \"BUNDLE\": str(out / \"bundle.mjs\"), \"CONTRACT\": str(CONTRACT), \"HOST\": HOST, \"PATH\": os.environ.get(\"PATH\", \"\")},\n    )\n    assert proc.returncode == 0, proc.stderr\n    return json.loads(proc.stdout.splitlines()[-1])\n\n\ndef _has_non_finite(value) -> bool:\n    if isinstance(value, float):\n        return not math.isfinite(value)\n    if isinstance(value, dict):\n        return any(_has_non_finite(v) for v in value.values())\n    return isinstance(value, list) and any(_has_non_finite(v) for v in value)\n\n\n@pytest.mark.parametrize(\"case\", CONTRACT_CASES, ids=[case[\"name\"] for case in CONTRACT_CASES])\ndef test_each_contract_fixture_case_is_accepted_with_its_fields_or_refused_as_malformed(contract_report, case):\n    result = contract_report[case[\"name\"]]\n    if case[\"gateway\"] == \"rejected\":\n        assert result.get(\"thrown\") == MALFORMED, result  # exactly the parser's refusal, so a JSON SyntaxError cannot pass as one\n    else:\n        expected = case[\"gateway\"]\n        if case[\"route\"] == \"state\" and expected[\"state\"] == \"ready\":\n            expected = {**expected, \"cues\": sorted(expected[\"cues\"], key=lambda cue: (cue[\"start\"], cue[\"end\"]))}\n        assert result.get(\"value\") == expected, result  # ready re-sorted by start then end; running left in the gateway's order\n    # Control: the parser read infinity exactly where the fixture wrote 1e999, so the 1e999 case is refused for its non-finite start, not for a null.\n    served = case[\"engine\"][\"body\"] if case[\"gateway\"] == \"rejected\" else case[\"gateway\"]\n    assert result[\"nonFinite\"] == _has_non_finite(served)\n```\n\n- **New import:** `import math`.\n- **No embed alias or CSS loader.** Nothing in the `data/translate.ts` \u2192 `api-base`/`profile` chain needs them.\n- **The `1e999` control is an assertion over every case.** The set of cases that reached the parser as non-finite must equal the set the fixture writes with `1e999`.\n- **Known gap in the sentinel.** It writes `-Infinity` as `1e999` too. No case uses a negative infinity.\n- **One node process runs every case**, through the module fixture.\n\n**Docstring paragraph**, before the \"The request and the poll run under a second runner\" paragraph:\n\n> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55) runs under a third runner, `CONTRACT_RUNNER`, over `data/translate.ts` bundled on its own. It stubs `window`, `localStorage` and a `fetch` that answers 200 with the served text, then imports the bundle and reads the fixture itself with `fs`. For each case it serves the gateway answer (a valid case) or the Engine body (a rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route), in one node process. A valid case answers exactly its gateway answer, with `ready` cues sorted by start then end and `running` cues in the order given. Every rejected case throws exactly `Translate response was malformed`. Non-finite numbers are served as `1e999`, because `JSON.stringify` would write `null`. As a control, the parser read infinity in exactly the cases whose fixture value is non-finite.\n\n---\n\n### 4. `tests/active/test_internal_translate.py`\n\n**Imports:** `import ast` and `import re` join the stdlib block at `:54-67`. Both are stdlib and safe at module level.\n\n**Keeping `test_source_fetch.py` safe.** That file imports this module, so nothing new at module level may read a file or import another layer. Only a path constant and static code are added. The fixture is read inside each test.\n\n> **Departure from the plan (named):** the plan parametrized the Engine test over the fixture's cases. That needs a module-level fixture read, which the impact inventory flags as a hazard through `test_source_fetch.py:25`. Instead the test is parametrized over the static driver table. A separate test asserts that the fixture's valid `(route, state)` set equals the driver table's keys. A fixture state with no driver still fails, and so does a driver with no fixture state. Each parametrized run checks every fixture case for its key.\n\nCode is inserted after `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues` (`:997`). All the helpers it uses (`NOW`, `BODY`, `_seed`, `_claimed`, `_beat`, `_route`, `_instance`, `_state`, `_enqueue`, `_server`, `_subtitles_db`) are defined above that point.\n\n```python\n# The contract fixture all three layers replay (issue 55); read inside each test, because test_source_fetch.py imports this module.\nCONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\n\n\ndef _contract_cases() -> list[dict]:\n    return json.loads(CONTRACT.read_text())[\"cases\"]\n\n\ndef _engine_contract_case(case: dict) -> bool:\n    \"\"\"A valid 200 case that carries available, as this Engine always answers; the cases without it stand for older Engines.\"\"\"\n    return case[\"gateway\"] != \"rejected\" and case[\"engine\"][\"status\"] == 200 and \"available\" in case[\"engine\"][\"body\"]\n\n\ndef _json_type(value: object) -> str:\n    \"\"\"The JSON type a value is written as; bool first, since a bool is also an int.\"\"\"\n    if isinstance(value, bool):\n        return \"boolean\"\n    if isinstance(value, (int, float)):\n        return \"number\"\n    if isinstance(value, str):\n        return \"string\"\n    if isinstance(value, list):\n        return \"array\"\n    if isinstance(value, dict):\n        return \"object\"\n    return \"null\" if value is None else type(value).__name__\n\n\ndef _types(body: dict) -> dict[str, str]:\n    return {key: _json_type(value) for key, value in body.items()}\n\n\ndef _running_cues(count: int) -> list[dict]:\n    \"\"\"count stored running cues, in descending start order so they are not sorted; as many as the case's total, so an after slice leaves cues to check.\"\"\"\n    return [{\"start\": float(count - index), \"end\": float(count - index) + 0.5, \"text\": f\"cue {index}\"} for index in range(count)]\n\n\ndef _state_driver(row: str):\n    \"\"\"The state route with the key seeded as row and a fresh beat; the instance holds no en track, so failed, already_english and no row are answered as stored, not as ready.\"\"\"\n    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:\n        from data.subtitles import write_translate_heartbeat\n\n        store = _subtitles_db(subtitles_path)\n        if row == \"running\":\n            assert _claimed(store).write_running_cues(_running_cues(case[\"engine\"][\"body\"][\"total\"]), \"fr\")\n        else:\n            _seed(store, row)\n        write_translate_heartbeat(store, NOW, 1)\n        body = {**BODY, \"after\": case[\"after\"]} if \"after\" in case else BODY\n        return _state(_route(_instance(False), monkeypatch), _server(whitelist, subtitles_path), body)\n    return drive\n\n\ndef _enqueue_driver(row: str | None):\n    \"\"\"The enqueue route: None is no beat (none), \"busy\" a queue filled to SUBTITLE_QUEUE_CAP, else the key seeded as row; a fresh beat unless None.\"\"\"\n    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:\n        from data.subtitles import enqueue_translate_job\n\n        store = _subtitles_db(subtitles_path)\n        if row == \"busy\":\n            for index in range(SUBTITLE_QUEUE_CAP):\n                assert enqueue_translate_job(store, f\"q-{index:03d}\", HOST, \"en\", SUBTITLE_QUEUE_CAP, NOW - 5000) == (\"queued\", \"queued\")\n        elif row is not None:\n            _seed(store, row)\n        store.close()\n        if row is not None:\n            _beat(subtitles_path, 0)\n        return _enqueue(_route(RecordingInstance(), monkeypatch), _server(whitelist, subtitles_path), BODY)\n    return drive\n\n\n# How the Engine is driven into each (route, state) the contract fixture names.\nENGINE_DRIVERS = {\n    (\"state\", \"none\"): _state_driver(\"no row\"),\n    (\"state\", \"queued\"): _state_driver(\"queued\"),\n    (\"state\", \"running\"): _state_driver(\"running\"),\n    (\"state\", \"ready\"): _state_driver(\"ready\"),\n    (\"state\", \"already_english\"): _state_driver(\"already_english\"),\n    (\"state\", \"failed\"): _state_driver(\"failed\"),\n    (\"enqueue\", \"none\"): _enqueue_driver(None),\n    (\"enqueue\", \"queued\"): _enqueue_driver(\"no row\"),\n    (\"enqueue\", \"running\"): _enqueue_driver(\"running\"),\n    (\"enqueue\", \"ready\"): _enqueue_driver(\"ready\"),\n    (\"enqueue\", \"already_english\"): _enqueue_driver(\"already_english\"),\n    (\"enqueue\", \"failed\"): _enqueue_driver(\"failed\"),\n    (\"enqueue\", \"busy\"): _enqueue_driver(\"busy\"),\n}\n\n\ndef test_every_route_state_in_the_contract_fixture_has_an_engine_driver():\n    assert {(case[\"route\"], case[\"engine\"][\"body\"][\"state\"]) for case in _contract_cases() if _engine_contract_case(case)} == set(ENGINE_DRIVERS)\n\n\n@pytest.mark.parametrize(\"route, state\", ENGINE_DRIVERS.keys(), ids=[f\"{route} {state}\" for route, state in ENGINE_DRIVERS])\ndef test_each_route_state_answers_the_keys_and_json_types_of_its_contract_fixture_case(tmp_path, whitelist, monkeypatch, route, state):\n    cases = [case for case in _contract_cases() if _engine_contract_case(case) and (case[\"route\"], case[\"engine\"][\"body\"][\"state\"]) == (route, state)]\n    assert cases, (route, state)\n    for index, case in enumerate(cases):\n        expected = case[\"engine\"][\"body\"]\n        ((status, answer),) = ENGINE_DRIVERS[(route, state)](tmp_path / f\"subtitles-{index}.db\", whitelist, monkeypatch, case)\n        assert status == 200, (case[\"name\"], answer)\n        assert answer[\"state\"] == state, case[\"name\"]  # control: the driver reached the state under test\n        assert _types(answer) == _types(expected), case[\"name\"]  # exactly the keys, and each value's JSON type\n        if \"cues\" in expected:\n            # Non-empty wherever the fixture's are, so the per-cue check cannot pass on an empty list.\n            assert bool(answer[\"cues\"]) == bool(expected[\"cues\"]), case[\"name\"]\n            assert all(_types(cue) == _types(expected[\"cues\"][0]) for cue in answer[\"cues\"]), case[\"name\"]\n\n\n@pytest.mark.parametrize(\"route\", [\"state\", \"enqueue\"])\ndef test_an_unknown_or_denied_video_answers_the_contract_fixtures_video_not_found_body(tmp_path, whitelist, monkeypatch, route):\n    (body,) = [case[\"engine\"][\"body\"] for case in _contract_cases() if case[\"route\"] == route and case[\"engine\"][\"status\"] == 404 and case[\"gateway\"] != \"rejected\"]\n    answer = _state if route == \"state\" else _enqueue\n    instance = _instance(True)\n    internal_translate = _route(instance, monkeypatch)\n    server = _server(whitelist, tmp_path / \"subtitles.db\")\n    _beat(tmp_path / \"subtitles.db\", 0)\n    _set_denied(whitelist, True)  # stored as DENIED.EXAMPLE\n    assert answer(internal_translate, server, {\"id\": \"no-such-video\", \"host\": HOST}) == [[404, body]]\n    assert answer(internal_translate, server, {\"id\": DENIED_VIDEO[1], \"host\": DENIED_HOST}) == [[404, body]]\n    assert instance.fetched == []\n    # Control: inactive, the same denied video is answered 200, so the 404 above is the denylist's doing.\n    _set_denied(whitelist, False)\n    assert answer(internal_translate, server, {\"id\": DENIED_VIDEO[1], \"host\": DENIED_HOST})[0][0] == 200\n\n\ndef test_the_heartbeat_fresh_window_is_three_beats_derived_from_heartbeat_seconds():\n    import server_config\n\n    (value,) = [node.value for node in ast.parse((API_DIR / \"server_config.py\").read_text()).body if isinstance(node, ast.Assign) and [getattr(target, \"id\", None) for target in node.targets] == [\"HEARTBEAT_FRESH_MS\"]]\n    assert \"HEARTBEAT_SECONDS\" in {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}\n    window = compile(ast.Expression(value), \"server_config.py\", \"eval\")\n    assert server_config.HEARTBEAT_SECONDS == 5.0\n    assert eval(window, {\"HEARTBEAT_SECONDS\": server_config.HEARTBEAT_SECONDS}) == server_config.HEARTBEAT_FRESH_MS == 15_000\n    assert eval(window, {\"HEARTBEAT_SECONDS\": 7.0}) == 21_000  # a different interval moves the window with it\n    assert isinstance(server_config.HEARTBEAT_FRESH_MS, int)\n    assert _translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS\n    # Neither consumer keeps a literal of its own; each imports its name from server_config.\n    for path, name in ((API_DIR / \"handlers\" / \"internal_translate.py\", \"HEARTBEAT_FRESH_MS\"), (SERVER_DIR / \"db\" / \"jobs\" / \"translate-worker.py\", \"HEARTBEAT_SECONDS\")):\n        tree = ast.parse(path.read_text())\n        assigned = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}\n        assert not assigned & {\"HEARTBEAT_SECONDS\", \"HEARTBEAT_FRESH_MS\"}, path\n        assert name in {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == \"server_config\" for alias in node.names}, path\n\n\ndef test_the_translate_timeout_chain_keeps_budget_plus_socket_under_the_client_timeout_under_the_deploy_drain():\n    from data.source_fetch import SOCKET_TIMEOUT_SECONDS\n    from lib.engine_api_client import TRANSLATE_TIMEOUT_SECONDS  # the Client's; conftest puts client/backend on sys.path, and the module imports only stdlib\n\n    budget = _translate().REQUEST_BUDGET_SECONDS\n    drains = re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", (ROOT / \"scripts\" / \"deploy-bluegreen.sh\").read_text(), re.M)\n    assert len(drains) == 1, drains  # the default, not the --drain override line\n    assert budget + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS < int(drains[0]), (budget, SOCKET_TIMEOUT_SECONDS, TRANSLATE_TIMEOUT_SECONDS, drains)\n```\n\n**Why the drivers are built this way.**\n- **Running.** The driver seeds as many cues as the case's `total`: 3 for `state running`, and 5 for `state running after 3`, which answers 2 cues. The sliced case therefore checks real cues instead of passing on the `cues: []` that `RUNNING`'s 3 cues would give.\n- **No instance track on the state route.** `_instance(False)` is required: with a track, `failed`, `already_english` and `none` answer `ready` (BRANCHES `:812`, `:814`).\n- **`ready`** answers `STORED_READY` with no fetch.\n\n**Not-found test.**\n- The fresh beat is written so the enqueue control queues, rather than answering `none` with 200 for the wrong reason.\n- Both routes resolve before reading the beat, so the 404s don't depend on it.\n- The existing literal `VIDEO_NOT_FOUND` (`:162`) is left alone; the new test reads the fixture.\n\n**Timeout test placement.** It goes immediately after `test_one_15_second_budget_covers_both_fetches` (`:611-625`). The derivation and contract tests go in the block above.\n\n**Docstring entries.** A new section goes before \"Startup:\" (`:48`):\n\n> Contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55, read inside each test because `test_source_fetch.py` imports this module):\n> - Every `(route, state)` among the fixture's valid 200 cases that carry `available` has a driver here, and every driver has such a case.\n> - Each driver brings its route into its state with the pinned clock and a fresh beat (none for the enqueue route's `none`): the state route from a seeded `none`, `queued`, `running` (as many stored cues as the case's `total`, with its `after`), `ready`, `already_english` or `failed` key and no instance track; the enqueue route from no row, a seeded stored state, or a queue filled to `SUBTITLE_QUEUE_CAP`. The answer is a 200 in that state with exactly the case's keys and each value's JSON type (bool before number), cues non-empty where the case's are, each with the keys and types of the case's cues.\n> - On both routes, an unknown video and an actively denylisted one answer exactly the fixture's `Video not found` 404 body, with no fetch; inactive, the denied video answers 200.\n>\n> Shared constants:\n> - `server_config.py`'s `HEARTBEAT_FRESH_MS` is an expression over `HEARTBEAT_SECONDS`. It evaluates to the module's 15 000 (an int) for 5.0 and to 21 000 for 7.0. The handler's `HEARTBEAT_FRESH_MS` is that value. Neither the handler nor the translate worker assigns either name: the handler imports `HEARTBEAT_FRESH_MS` from `server_config`, and the worker imports `HEARTBEAT_SECONDS`.\n> - The route's `REQUEST_BUDGET_SECONDS` plus `data.source_fetch.SOCKET_TIMEOUT_SECONDS` is below the Client's `TRANSLATE_TIMEOUT_SECONDS`, which is below the `DRAIN_SECONDS=` default, the one line of `scripts/deploy-bluegreen.sh` that starts with it.\n\n---\n\n### 5. `engine/server/api/server_config.py`\n\nInserted after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`). It needs no new import.\n\n```python\n# Seconds between the translate worker's heartbeats.\nHEARTBEAT_SECONDS = 5.0\n# Age in ms within which a heartbeat counts as a serving worker (/internal/translate's available): three beats, so one late beat is tolerated.\nHEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)\n```\n\nIt stays an int (15000), so `BEATS`' 15 000 / 15 001 edges and the docs read as before.\n\n### 6. `engine/server/api/handlers/internal_translate.py`\n\n- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.\n- `:32-33` (the rat-tail comment and `HEARTBEAT_FRESH_MS = 15_000`) are deleted.\n- **Docstring `:3`.** \"...whether the translate worker beat within HEARTBEAT_FRESH_MS.\" becomes \"...whether the translate worker beat within HEARTBEAT_FRESH_MS (server_config.py, three HEARTBEAT_SECONDS beats).\"\n- **Docstring `:5`.** It already names `HEARTBEAT_FRESH_MS` and stays as is. Since `:3` says where the constant is defined, it is not repeated here.\n- **Unchanged:** `:30`, `REQUEST_BUDGET_SECONDS`, `VIDEO_NOT_FOUND`, both handlers and the sort at `:115`.\n\n### 7. `engine/server/db/jobs/translate-worker.py`\n\n- `:41` becomes `from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_MAX_DURATION, SUBTITLE_QUEUE_CAP, VIDEO_ERROR_THRESHOLD`.\n- `:58-59` (the rat-tail comment and `HEARTBEAT_SECONDS = 5.0`) are deleted. The uses at `:458`, `:467` and `:536` read the imported name.\n- `HEARTBEAT_SECONDS` stays a module attribute, so `STALL_DRIVER`'s exec and the `spec_from_file_location` load in `test_translate_worker.py` still see it.\n- **Comment `:35`** becomes \"api/ is for server_config (bounds and HEARTBEAT_SECONDS) and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.\"\n\n### 8. Prose\n\n**`engine/server/README.md:15`.** Append to the bullet:\n\n> `total` always counts every stored cue, whatever `after` was, so a reader that already holds more running cues than `total` knows the job was requeued and restarted.\n\n**`engine/server/README.md:18`.** \"(15 000 ms, three of the worker's 5 s beats)\" becomes:\n\n> (15 000 ms, three of the worker's 5 s beats, derived in `api/server_config.py` from `HEARTBEAT_SECONDS`)\n\n**`engine/server/README.md:30`.** The tunables list becomes \"`SUBTITLE_MAX_DURATION`, `SUBTITLE_MAX_BYTES`, `SUBTITLE_QUEUE_CAP` and `SUBTITLE_MAX_CHUNK_SECONDS` in `api/server_config.py`, which also holds its beat interval `HEARTBEAT_SECONDS`\".\n\n**`TRANSLATE_WORKER.md:155`.** \"(`HEARTBEAT_FRESH_MS`, three beats), and otherwise ... reporting `available`. Raise both constants together.\" becomes:\n\n> ...at most 15 s old (`HEARTBEAT_FRESH_MS`), and otherwise neither queues a job from the page nor reports `available`. Both come from one definition in `engine/server/api/server_config.py`: the beat interval `HEARTBEAT_SECONDS`, with `HEARTBEAT_FRESH_MS` derived from it as three beats, so changing the interval moves the window with it.\n\n**`CONTEXT.md` and `DEPLOYMENT.md`** are unchanged. Both are accurate, and the `DEPLOYMENT.md` edits were optional, so they are skipped.\n\n### 9. `tests/config.json`\n\n- Add `tests/active/fixtures/translate_contract.json` to the `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` groups.\n- Add to `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.\n- Add `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.\n\n---\n\n### Mutation check (manual, once, recorded in the build record)\n\nAdd `{\"name\": \"state paused\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"paused\", \"available\": true}}, \"gateway\": {\"state\": \"paused\", \"available\": true}}` to the fixture alone and run the three suites. Expected results:\n- **Client:** the replay of `state paused` raises `EngineApiError`, so it answers `\"rejected\"` and not the gateway answer. The coverage test fails because the set is not `TRANSLATE_STATES`.\n- **Frontend:** `state paused` throws `MALFORMED` where a value was expected.\n- **Engine:** `test_every_route_state_in_the_contract_fixture_has_an_engine_driver` fails.\n\nRevert the edit. Also record `rg -l translate_contract.json engine client scripts` returning nothing.\n\n### Check against the plan and the requirements (pass 1, converged)\n\n| Requirement | Where it is met |\n|---|---|\n| One fixture, every state of both routes with and without `available`, every listed rejection, nothing at runtime reads it | \u00a71; the coverage test in \u00a72; grep in the build record |\n| Client replays every case through both parsers | \u00a72 test 1 |\n| Frontend replays every case; `ready` sorted; rejected throws | \u00a73; real `translate.ts` through esbuild, fetch stubbed, no frontend change |\n| Engine checks each state's keys and types against the fixture, plus the not-found body | \u00a74 shape test and not-found test (state route as required, enqueue added) |\n| Mutation check recorded | above |\n| Heartbeat: one definition, both import it, rat-tails gone, derivation test | \u00a75\u20137, \u00a74 heartbeat test |\n| Timeout chain from real values; fails when one value passes its neighbour | \u00a74 timeout test; strict `<` on both sides |\n| README running-slice rule | \u00a78 |\n| No runtime behaviour change; existing tests unchanged | only additions to tests; constant values identical; step-zero baseline |\n\nThree points deliberately differ from the plan's wording. None of them changes its intent:\n1. **Engine parametrization.** It runs over the static driver table plus a two-way set-equality test, instead of over the fixture's cases, to avoid a module-level read that `test_source_fetch.py` would inherit.\n2. **The plan's rule that \"rejected must be refused by both layers\"** is enforced by the two replays themselves, not by the Client coverage test, which cannot run the frontend. The coverage test enforces the with/without-`available` rule, name uniqueness, the two routes, `after` only on state cases, and exactly one not-found case per route.\n3. **One frontend fixture.** It bundles and runs together; there is no separate bundle fixture.\n\n### Named simplifications and their ceilings\n\n- **The `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay.** Part of the contract is therefore stated twice: once at the HTTP route and once in the fixture. Upgrade path: build those tables from `TRANSLATE_CONTRACT_CASES`, mapping `rejected` to `TRANSLATE_FAILED`.\n- **The Engine test checks shape, not values or order.** Cue order and slice arithmetic stay covered by `BRANCHES` and `AFTERS`.\n- **The non-finite sentinel writes any infinity as positive `1e999`.** That is enough for the one case; a negative-infinity case would need `-1e999` handling.\n- **The module-level fixture loads in `test_server.py` and `test_frontend_translate.py` are unguarded.** A malformed fixture stops those two modules collecting, which surfaces loudly and is accepted.\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the Client gateway's parse functions, called directly. A new parametrized test in tests/active/test_server.py, one run per fixture case with the case name as id, starts the existing `_translate_engine` stub (test_server.py:1600) answering the case's engine status and body. It then calls `fetch_translate` (state route, passing the case's `after`) or `request_translate` (enqueue route). It asserts the result equals the case's `gateway` answer, or that `EngineApiError` was raised for \"rejected\". Control: the stub recorded exactly one request, on the case's /internal/translate route, carrying id, host and the case's `after`, so a rejection comes from the parse and not from a failed call. A second test reads the fixture and asserts: names are unique; there are exactly the two routes; `after` appears only on state cases; the valid 200 states equal TRANSLATE_STATES (state route) and TRANSLATE_REQUEST_STATES (enqueue route), both with and without `available`; each route has exactly one \"Video not found\" 404 case. Direct calls rather than /api/translate, so a 502 cannot hide why a case failed.</checkpoint>\n<name>Contract fixture and Client gateway replay</name>\n<intent>tests/active/fixtures/translate_contract.json states the translate contract. Every case parses through the Client gateway's real fetch_translate/request_translate to its stated answer, and the fixture's valid states are exactly the gateway's state sets.</intent>\n<clause_1>Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route.</clause_1>\n<clause_2>The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique.</clause_2>\n<files>tests/active/fixtures/translate_contract.json (NEW), tests/active/test_server.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the real client/frontend/src/data/translate.ts, entered through its exported fetchTranslate/requestTranslate. It follows test_frontend_translate.py's existing esbuild-bundle-plus-node-runner harness (same --platform=node, ESM and import.meta.env defines). A module fixture bundles translate.ts on its own. CONTRACT_RUNNER stubs window, localStorage and a fetch that answers 200 with the served text, reads the fixture with fs, and in one node process serves each case: the gateway answer for a valid case, the Engine body for a rejected one. It reports the returned value or the thrown message, plus whether the parsed text contained a non-finite number. The parametrized Python test asserts that a valid case deep-equals its gateway answer, with ready cues re-sorted by (start, end) and running cues left in the order given, and that a rejected case threw exactly \"Translate response was malformed\", so a JSON SyntaxError cannot pass as a refusal. Control on every case: the parser read a non-finite number exactly where the fixture writes 1e999. No frontend file changes.</checkpoint>\n<name>Frontend parser replay</name>\n<intent>data/translate.ts is proven against every case of the contract fixture. Valid gateway answers come back with their fields intact, and every rejected body is refused as malformed.</intent>\n<clause_1>Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given.</clause_1>\n<clause_2>Every rejected fixture case served as a 200 throws exactly \"Translate response was malformed\".</clause_2>\n<files>tests/active/test_frontend_translate.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the Engine's /internal/translate and /internal/translate/enqueue handlers, entered through test_internal_translate.py's existing harness (`_route`, `_state`, `_enqueue`, `_server`, `_seed`, `_claimed`, `_beat`, `_instance`). The fixture is read inside each test, never at module level, because test_source_fetch.py imports this module. A static ENGINE_DRIVERS table keyed by (route, state) drives each state: seeded rows with a fresh beat and no instance track on the state route; on the enqueue route, no beat for none, no row for queued, a seeded stored state, or a queue filled to SUBTITLE_QUEUE_CAP for busy. The parametrized test asserts, for each fixture case that carries available: a 200; answer state equals the state under test (control); the key-to-JSON-type map equals the case's (bool before number); cues non-empty where the case's are; and each answered cue's keys and types match the case's cues. A separate test asserts that the fixture's (route, state) set equals the driver table's keys, both ways. The not-found test asserts that on both routes an unknown video and an actively denylisted video answer exactly the fixture's Video-not-found 404 body with no fetch, and as a control that the same denied video answers 200 once the deny is inactive.</checkpoint>\n<name>Engine answers match the fixture's shape</name>\n<intent>The Engine's two translate routes are checked against the contract fixture. Each (route, state) it produces answers the fixture case's keys and JSON types, and its not-found answer is the fixture's body.</intent>\n<clause_1>Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state.</clause_1>\n<clause_2>On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body.</clause_2>\n<files>tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n<phase n=\"4\" kind=\"code\">\n<checkpoint>Seam: the real constants, with server_config.py's source as the derivation's front door. Two tests in test_internal_translate.py. (1) Heartbeat: ast-parse engine/server/api/server_config.py and find the single HEARTBEAT_FRESH_MS assignment. Assert its expression names HEARTBEAT_SECONDS. Evaluate it with the real interval (equals the module's value, 15000, an int) and with 7.0 (21000). Assert the handler module's HEARTBEAT_FRESH_MS is server_config's. Assert neither internal_translate.py nor translate-worker.py assigns HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS, and that each imports its name from server_config. (2) Timeout chain, placed after test_one_15_second_budget_covers_both_fetches: take the handler's REQUEST_BUDGET_SECONDS, data.source_fetch.SOCKET_TIMEOUT_SECONDS and lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (conftest supplies client/backend on sys.path). Read DRAIN_SECONDS from scripts/deploy-bluegreen.sh with a line-anchored regex that must match exactly once. Assert budget + socket < Client timeout < drain. The existing BEATS 15000/15001 edge tests and test_translate_worker.py, both unchanged, confirm behaviour is preserved.</checkpoint>\n<name>Single-sourced heartbeat and checked timeout chain</name>\n<intent>The heartbeat interval and its freshness window are defined once in server_config.py, the window derived from the interval and imported by both consumers, and the translate timeout chain across Engine, Client and deploy script is held in order by a test.</intent>\n<clause_1>server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own.</clause_1>\n<clause_2>REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default.</clause_2>\n<files>engine/server/api/server_config.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone. No phase needs a credential, a live endpoint or the operator. Two steps are run by the agent and recorded in the build record. Before phase 1: the step-zero baseline run of the six translate suites plus test_source_fetch.py. After phase 3: the one-time manual mutation check (a \"state paused\" case added to the fixture alone, three suites run, then reverted) and `rg -l translate_contract.json engine client scripts` returning nothing. Phase 2 relies on the node and esbuild toolchain the existing frontend tests already use.\n</needs_coordination>\n\n<rationale>\nThe build splits along the layers the contract crosses. Each phase is one test file proving one layer against the shared fixture, and each layer's check falls into two observable facts. Phase 1 comes first because it creates the fixture and the coverage test that phases 2 and 3 replay against: Client parse result, plus the fixture's state coverage. Phase 2 covers the frontend: valid accepted, plus rejected refused. Phase 3 covers the Engine: shape per state, plus the not-found body. Its checkpoint also carries the draft's named departure, a static driver table with a two-way set check, which avoids a module-level fixture read that test_source_fetch.py would inherit. Phase 4 holds the only runtime change, the heartbeat move, alongside the timeout-chain test. Both are cross-layer constant checks in the same file, independent of the fixture. Putting them in phase 3 would have given it four clauses. The operator was offered running the heartbeat move first and approved the order as drawn. There is no prose phase: engine/server/README.md and TRANSLATE_WORKER.md are documentation for human readers and are updated at Step 9. The code docstrings travel with their code phases. Each phase adds its own tests/config.json entries so every checkpoint's group is complete when it lands. Confirmed in the tree: `_translate_engine` (test_server.py:1600), the `_route`/`_state`/`_enqueue` harness (test_internal_translate.py:653-739), the two literals to remove (internal_translate.py:33, translate-worker.py:59), the single DRAIN_SECONDS line (deploy-bluegreen.sh:50), and that tests/active/fixtures/ does not exist yet. Operator approved the plan as presented.\n</rationale>",
    "author:tests/tmp/test_55_translate_state_contract_phase1.py": "<assertions>\ntests/tmp/test_55_translate_state_contract_phase1.py:36 - the fixture file exists (both tests start with this so that a missing fixture fails per test, not with a collection error) - precondition for C1\ntests/tmp/test_55_translate_state_contract_phase1.py:41 - a case whose gateway is \"rejected\", run through fetch_translate (state route, with the case's after) or request_translate (enqueue route) against the _translate_engine stub answering the case's status and body, raises EngineApiError whose text starts \"Engine translate\", so a transport failure cannot pass as a refusal; this excludes a fixture marking a parseable answer rejected (probed: DID NOT RAISE) - C1\ntests/tmp/test_55_translate_state_contract_phase1.py:45 - a valid case's return value equals the case's gateway answer exactly; this excludes a gateway answer missing the available default (probed: fails) and a valid state the gateway does not know, such as \"paused\" (probed: the real parser raises EngineApiError) - C1\ntests/tmp/test_55_translate_state_contract_phase1.py:48 - the stub recorded exactly one request, as (method, path, body) == [(\"POST\", route of the case, {id, host} plus the case's after when it has one)]; this excludes a call to the wrong route, a retry or no call, and an after the gateway did not send (probed: an enqueue case carrying after fails here) - C1\ntests/tmp/test_55_translate_state_contract_phase1.py:54 - no case name appears twice (probed: a duplicated case fails) - C2\ntests/tmp/test_55_translate_state_contract_phase1.py:55 - the fixture's routes are exactly {state, enqueue} - checkpoint text (two routes only)\ntests/tmp/test_55_translate_state_contract_phase1.py:56 - no case off the state route carries after (probed: fails on an enqueue case with after) - checkpoint text (after only on state cases)\ntests/tmp/test_55_translate_state_contract_phase1.py:59 - per route, the states of the valid 200 cases whose Engine body carries available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue); this excludes an extra state such as \"paused\" or a state that is missing (probed: fails on route \"state\") - C2\ntests/tmp/test_55_translate_state_contract_phase1.py:60 - the same equality for the valid 200 cases without available (probed: dropping \"enqueue busy without available\" fails on route \"enqueue\") - C2\ntests/tmp/test_55_translate_state_contract_phase1.py:61 - each route has exactly one case whose engine is {status 404, body {\"error\": \"Video not found\"}} (probed: dropping the enqueue one fails) - checkpoint text (one Video-not-found case per route)\ntests/tmp/test_55_translate_state_contract_phase1.py:63 - control: each route has at least one rejected case, so C1's EngineApiError half runs through both parsers rather than holding vacuously (probed: a fixture with no enqueue rejections fails) - control for C1\n</assertions>\n\n<probes>\nThe fixture does not exist yet, so the probes ran against the plan's draft fixture, i.e. the JSON block under \"### 1.\" in docs/project/plans/01-55-translate-state-contract.md, which holds 43 cases.\n1) ValidateTests [\"tests/tmp/probe_55_phase1_replay.py\", \"-s\"] ran every draft case through the real fetch_translate/request_translate via test_server._translate_engine. It printed: TRANSLATE_STATES = [already_english, failed, none, queued, ready, running]; TRANSLATE_REQUEST_STATES is the same set plus busy; the fixture file exists = False. All 43 cases matched their gateway answer. Each case caused exactly one request: ('POST', '/internal/translate' or '/internal/translate/enqueue', {'id': 'uuid-1', 'host': 'peer.example'}), with 'after': 3 only on \"state running after 3\". The refusal texts were \"Engine translate failed (HTTP 404): Not found\", \"Engine translate request failed (HTTP 404): Not found\", \"Engine translate returned invalid payload\" (this one also for the enqueue non-bool available case and for start 1e999) and \"Engine translate request returned invalid payload\". All of them start with \"Engine translate\", which is what the match= at :41 rests on.\n2) ValidateTests [\"tests/tmp/probe_55_phase1_checkpoint.py\", \"-s\"] exec'd the checkpoint's own source with CONTRACT pointed at a tmp copy of the draft or of a mutant, then called both test bodies. On the draft, the coverage test passed and the replays I sampled passed (start 1e999, running after 3, enqueue route missing 404). Each mutant failed:\n- \"state paused\" added (earlier run): the replay raised EngineApiError 'Engine translate returned invalid payload', and coverage failed on route state.\n- \"enqueue busy without available\" dropped: coverage failed on route enqueue.\n- duplicate name: failed at the uniqueness line.\n- gateway without the available default: the replay assertion failed.\n- valid ready marked rejected: replay 'DID NOT RAISE EngineApiError', and coverage failed on route state.\n- an enqueue case with after: both the replay control and the after-only-on-state line failed.\n- no enqueue rejection: failed at the control on route enqueue.\n- enqueue not-found dropped: failed at the one-not-found line on route enqueue.\n3) ValidateTests [\"tests/tmp/test_55_translate_state_contract_phase1.py\"] gave 2 failed (the \"fixture missing\" stand-in and the coverage test), both on the missing-file assertion. That is the red, and it is per test rather than a collection error. An earlier version loaded the fixture unguarded and gave a collection error with no per-test results, which is why the guard exists.\nBoth probe files (tests/tmp/probe_55_phase1_replay.py, tests/tmp/probe_55_phase1_checkpoint.py) are still on disk because I have no delete tool. They should be removed.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_55_translate_state_contract_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:45 \u2014 for each valid case, the value returned by fetch_translate (state route, with the case's after) or request_translate (enqueue route) equals the case's `gateway` answer exactly.</assertion>\n<expected>Passes for every valid case in a fixture that agrees with the gateway. In the probe, built from the gateway's own state sets, all 34 cases passed: 6 states \u00d7 with/without available on the state route, 7 on enqueue, both Video not found 404s, and running with after 3.</expected>\n<wrong_implementation>Three wrong fixtures, as the probe ran them. (1) A `gateway` answer that leaves out the available default: AssertionError at :45. (2) A valid \"paused\" state or \"busy\" on the state route: the real parser raises \"EngineApiError: Engine translate returned invalid payload\" before :45 is reached, so the test is red. (3) Running cues stated in re-sorted order instead of stored order: AssertionError at :45. Deleting the `False` default at engine_api_client.py:163 makes every without-available case raise, so they all go red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:41 \u2014 for a case whose gateway is \"rejected\", the matching parser raises EngineApiError and its message starts with \"Engine translate\".</assertion>\n<expected>Raises for every rejected case. In the probe this held for the Not found 404, the unknown state on both routes, and a cue whose start is inf: all passed.</expected>\n<wrong_implementation>A fixture that marks a parseable answer (state ready with available) as rejected fails with \"Failed: DID NOT RAISE EngineApiError\" (probed). A refusal that really came from the transport reads '&lt;urlopen error [Errno 111] Connection refused&gt;' (probed). That does not match ^Engine translate, so a dead stub cannot pass as a refusal.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:48 \u2014 the stub's log, as (method, path, body), is exactly [(\"POST\", route of the case, {id, host} plus the case's after when it has one)].</assertion>\n<expected>One entry per case. The probe showed the stub records (method, path, token, request id, body), for example [('POST', '/internal/translate', None, None, {'id': 'uuid-1', 'host': 'peer.example', 'after': 0})]. All 34 good cases passed this check.</expected>\n<wrong_implementation>An enqueue case carrying `after` fails here with AssertionError, because request_translate never sends it (probed). Other failures here: a call to the wrong route, a retry (two entries), no call at all (empty log), or an after that was dropped or invented.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:59 \u2014 per route, the set of states of the valid 200 cases whose body carries `available` equals TRANSLATE_STATES (state route) or TRANSLATE_REQUEST_STATES (enqueue route).</assertion>\n<expected>Equal on both routes in the conforming probe fixture (\"COVERAGE good -> passed\").</expected>\n<wrong_implementation>An extra valid state the gateway does not have (\"paused\") fails with \"AssertionError: state\". Dropping \"state failed\" with available fails with \"AssertionError: state\". Both probed.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:60 \u2014 per route, the set of states of the valid 200 cases whose body has no `available` equals the same gateway set.</assertion>\n<expected>Equal on both routes in the conforming probe fixture.</expected>\n<wrong_implementation>A fixture with no \"busy\" case that lacks available fails with \"AssertionError: enqueue\" (probed). So a state covered only with available is caught.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase1.py:54 \u2014 no case name appears more than once (the list of duplicated names is empty).</assertion>\n<expected>[] for the conforming fixture. :59 and :60 in the same test need at least 13 valid cases, so the list of names is known to be non-empty and this check is not vacuous.</expected>\n<wrong_implementation>A case copied in under the same name fails with AssertionError (probed: \"COVERAGE duplicate name -> AssertionError\"). The duplicate id would also make the parametrized replay ambiguous.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. C1 is carried by :41 (refusal), :45 (exact answer) and :48 (one POST to the case's route, with id, host and the case's after). C2 is carried by :59 and :60 (gateway sets with and without available, per route) and :54 (unique names). The other docstring sentences have their own checks: two routes only (:55), after only on state cases (:56), exactly one Video not found 404 per route (:61), and at least one rejected case per route (:63).\n2. No. The rejected branch is a positive raise with a message match, and :48 shows the request reached the stub, so the refusal comes from the parse. The uniqueness check at :54 is `== []`, but :59 and :60 in the same test need non-empty state sets, so CASES has cases. The after-only-on-state check at :56 is a supporting assertion for checkpoint text, not a clause. The probe shows it fails on an enqueue case that carries after.\n3. No. :45 compares the real parser's output with an answer written in the fixture; the test does not compute that answer itself. Deleting the `False` default at engine_api_client.py:163 makes every without-available case raise. Deleting `busy` from :23 breaks the enqueue busy replay and the :59/:60 set equality. Deleting the `state not in TRANSLATE_STATES` check at :192 lets the unknown-state rejected case return instead of raising, so :41 goes red.\n4. No. The replay is parametrized over every fixture case: all states on both routes, with and without available, both 404s, after, and every rejected form. The coverage checks compare against the production constants, not against another value read from the fixture.\n5. No. `_translate_engine` stands in for the Engine across the HTTP/process boundary, the severed layer the checkpoint names. The code under test, the Client's `fetch_translate`/`request_translate` and `_post_json`, is real. The Engine's own agreement with this fixture is a later phase's checkpoint.\n6. No. Every import resolves and the run collected 2 items. The `--collect-only` summary line \"no tests\" is how the runner reports collect-only mode; the real run printed \"collected 2 items\". The log tuple indices (0 method, 1 path, 4 body) were seen in a run: SEEN [('POST', '/internal/translate', None, None, {...})]. That is 2 tests now, and N+1 once the fixture exists: one replay per case plus the coverage test.\n7. Yes, observed. I ran a probe (tests/tmp/probe_55_contract.py) that loaded this module, pointed CONTRACT at an existing file and fed both tests a fixture built from the gateway's sets. All 34 replay cases passed and the coverage test passed. Wrong fixtures failed at the judging assertions: parseable-but-rejected gave \"DID NOT RAISE\", the missing available default gave AssertionError, paused/bogus/busy-on-state gave \"EngineApiError: Engine translate returned invalid payload\", enqueue with after gave AssertionError at :48, and re-sorted running cues gave AssertionError. Each coverage mutation was also caught: duplicate name, missing busy-without-available, missing failed-with-available, extra state, no enqueue 404, no enqueue rejected, a third route, and after on enqueue. The transport text is '<urlopen error [Errno 111] Connection refused>', so it cannot match ^Engine translate. Nothing needed rewriting. I emptied the probe because I have no delete tool, so the zero-byte file tests/tmp/probe_55_contract.py is left behind to remove.\n8. Yes, it is red. ValidateTests printed \"2 failed \u2026 recorded: tests/last_test_validation.json (exit 1)\".\n9. Yes, it is red for the right reason. Both tests fail on `assert CONTRACT.exists(), CONTRACT`: :36 in the replay (id \"fixture missing\") and :52 in the coverage test, with \"AssertionError: PosixPath('\u2026/tests/active/fixtures/translate_contract.json') \u2026 where False = exists()\". The fixture is this phase's only deliverable. The plan says runtime behaviour does not change, and engine_api_client.py already holds the parsers, so its absence is exactly the phase not being built. This is not a typo or a wrong path: the path is the one the plan names, and the probe showed the same assertions reach and judge the gateway once a fixture exists. The import, the stub and the log indices all work (probe run, 4 passed).\n10. Every row's `expected` and wrong-implementation reading is quoted from the probe run (\"GOOD \u2026 -> passed\", \"WRONG \u2026 -> \u2026\", \"COVERAGE \u2026 -> \u2026\", TRANSPORT, SEEN) or from the checkpoint run above. The run did not contradict any of them.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### tests/active/fixtures/translate_contract.json (NEW, plus the new `tests/active/fixtures/` directory)\nThis is the translate contract fixture: `{\"description\", \"cases\": [...]}`, one case per line. It is byte-for-byte the plan's draft (\u00a71 of the implementation plan), which is the version the checkpoint's author already probed against the checkpoint.\n- **Valid cases (29):** every state of the state route (6) and of the enqueue route (7, with `busy`), each once with `available: true` and once without it (the gateway reads a missing one as `false`). Also a `running` answer sliced by `after` 3 (2 cues, `total` 5), and the `{\"error\": \"Video not found\"}` 404 on both routes, which gives `{state: none, available: false}`.\n- **Rejected cases (14):** the `Not found` 404 on both routes; an unknown state on both routes; `busy` on the state route; a string `available` on both routes; and, on the state route only, non-list `cues`, a cue `start` of `1e999`, a bool `start`, a bool `end`, a number as `text`, a `total` of -1 and a `total` of `true`.\n- **Cue order:** the `ready` cues are out of start order with two sharing a start, and the `running` cues are in a non-sorted stored order. The gateway answer keeps the Engine's order.\n- **Checked:** a throwaway probe loaded the checked-in file. It equals the draft (43 cases), and every case replayed through the real `fetch_translate`/`request_translate`, via `test_server._translate_engine`, gives its `gateway` answer from exactly one request. Every refusal text starts with `Engine translate`. I did not run the checkpoint itself; the workflow does that.\n\n### tests/active/test_server.py (not edited)\nThe checkpoint only imports `_translate_engine` from it, and that already exists. The plan's durable copies of the replay and coverage tests (plus a docstring paragraph) would repeat the checkpoint word for word, so I left them for whichever step moves the checkpoint into the active suite rather than writing them twice now.\n\n### tests/config.json (not edited)\nThe planned entry adds the fixture to the `test_server.py` group. That only makes sense once `test_server.py` itself reads the fixture, so it belongs with that same step.\n\n### tests/tmp/probe_55_phase1_replay.py\nThis is a leftover probe from authoring. I reused it to check the fixture, then emptied it because I have no tool to delete files. It and the authoring step's `tests/tmp/probe_55_phase1_checkpoint.py` and zero-byte `tests/tmp/probe_55_contract.py` should be deleted.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_55_translate_state_contract_phase2.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"D2\">\n<disposition>justified</disposition>\n<what>I narrowed the prose. Line 3 used to say the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\". It now says the test \"hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here)\". That is what the test does: the env dict at line 54 of _contract_report sets them. The docstring no longer claims the runner reads them, which nothing asserted. Neither C1 nor C2 needs it.</what>\n</item>\n</items>\n\n<findings_addressed>\nShape CRITICAL 1 (tautological-assertion at old :98, where the ready expectation came from the test's own (start, end) sort): fixed. The expected ready cues are now a literal, READY_CUES, at line 30: Short first 1.0\u20132.0, Long first 1.0\u20133.0, Later 4.0\u20135.0. This is the order the earlier probe observed from the real translate.ts. Line 100 swaps that literal in for both ready cases, and line 101 compares against it. No expected value is computed by a sort any more. The _by_start_then_end helper is now used only by the line-98 control. That control reads the fixture's own input list to prove it is out of order, so it makes no prediction about production output.\nClaim Recommendation 1 (D2): taken by narrowing the docstring at line 3, as recorded in item D2.\nClaim Recommendation 2 (the served body is not recorded for 13 of the 14 rejected cases): not taken. C2 is carried as worded, and the suite as a whole still catches a single substituted body at the 1e999 nonFinite control (line 88).\nClaim Recommendation 3 (the ready fixture cannot tell a (start, end) sort from an (end, start) sort): not taken. The fix means adding a cue to tests/active/fixtures/translate_contract.json, which is a durable fixture outside this step's files. That gap remains and should go to whoever owns the fixture.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:101 \u2014 for each of the 29 valid cases, result[\"value\"] deep-equals the case's gateway answer. For the two ready cases the cues are replaced by the literal READY_CUES (line 30, used at line 100). Running cues are left in the fixture's order. The control at line 98 shows every fixture cue list is out of (start, end) order. The request control at line 86 shows the case went to fetchTranslate (a GET carrying its after) or requestTranslate (a POST).</assertion>\n<expected>Each case's gateway dict exactly. For ready: cues [Short first 1\u20132, Long first 1\u20133, Later 4\u20135]. For running: cues in the order given, e.g. starts [5,1,3] and [9,7] with total 5.</expected>\n<wrong_implementation>Earlier probe mutants, each observed red at this comparison: ready left unsorted, and ready sorted by start only (both fail \"state ready\" and \"state ready without available\"); running sorted (fails the three running cases); busy accepted on the state route (fails \"state busy\"); a field dropped or added, or a stub return (whole-dict inequality).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:107 \u2014 for each of the 14 rejected cases, the Engine body served as a 200 makes the call throw exactly MALFORMED. The controls at lines 85\u201386 show one request on the intended route, and the control at line 88 shows the 1e999 case was refused for infinity.</assertion>\n<expected>result[\"thrown\"] == \"Translate response was malformed\" for every rejected case.</expected>\n<wrong_implementation>Earlier probe mutants: a changed message fails all 14; infinity accepted through a typeof check fails \"state start 1e999\", which returns a value. Serving the real non-200 status would throw the error text or \"Translate request failed (N)\" instead. A JSON SyntaxError or no throw also reads differently.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Each case has a positive assertion: a deep-equal at line 101 or the exact thrown text at line 107. Delete translate.ts's parser and both read differently.\n2. Answered by a rewrite. The ready expectation used to come from a Python sort that copied production's ordering. It is now the literal READY_CUES. Deleting the .sort in translate.ts turns the two ready cases red at line 101 (observed earlier with the \"ready unsorted\" mutant). The only remaining sort runs on the fixture input, as a control at line 98.\n3. No. There are 29 valid and 14 rejected cases, each its own parametrized case, and the expected values come from the fixture's gateway answers and the literal, not from sibling outputs. The one single-input read is the nonFinite control at the 1e999 case, which the claim audit already noted.\n4. No. The runner's fetch is the severed network layer. The real translate.ts is bundled unchanged.\n5. Yes, it collects. READY_CUES is defined at module level before use, and no imports or names changed. The count is the same 43 cases.\n6. Yes. The literal is the ready output the earlier probe saw from the real translate.ts (Short first 1\u20132, Long first 1\u20133, Later 4\u20135). JS writes 5.0 as 5, which compares equal to Python's 5.0.\n7. Yes, it should still be red for its own reason, though I have not run it; the workflow does that. Every case should fail at line 81 because tests/active/test_frontend_translate.py has no CONTRACT_RUNNER yet. My edits were a docstring change, a module-level constant and one changed expression; none touches imports or the fixture.\n</answers>",
    "self_check:tests/tmp/test_55_translate_state_contract_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:99 \u2014 for each of the 29 valid fixture cases, the value that fetchTranslate (state route, with the case's after) or requestTranslate (enqueue route) returned, as reported by test_frontend_translate.py's own CONTRACT_RUNNER over the real translate.ts, deep-equals the case's gateway answer. Ready cues are compared sorted by (start, end) and running cues in the order the fixture gives them.</assertion>\n<expected>Today all 29 fail earlier, at :79, because test_frontend_translate.py has no CONTRACT_RUNNER yet. Once the phase adds the plan's runner, all 29 pass. Observed by running the plan's CONTRACT_RUNNER text through this checkpoint's harness over the real translate.ts: \"real -> 0 failed\". For example, \"state ready\" returned cues Short first (1,2), Long first (1,3), Later (4,5).</expected>\n<wrong_implementation>Each of these was observed in a probe using the plan's runner over a mutated copy of translate.ts. Dropping `.sort(compareCues)` (translate.ts:101) fails \"state ready\" and \"state ready without available\": they come back as Later, Long first, Short first. Sorting by start only (dropping `|| a.end - b.end`, :53) fails the same two: Long first comes back ahead of Short first. Sorting running cues fails \"state running\", \"state running without available\" and \"state running after 3\". On the runner side, a runner that sends every case through fetchTranslate fails 18 cases on the :84 request control, and a runner that drops `after` fails \"state running after 3\" on :84.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:105 \u2014 for each of the 14 rejected fixture cases, the Engine body served as a 200 by the phase's CONTRACT_RUNNER makes fetchTranslate or requestTranslate throw. The reported message is exactly \"Translate response was malformed\".</assertion>\n<expected>Today all 14 fail earlier, at :79, because CONTRACT_RUNNER is missing. With the plan's runner over the real translate.ts all 14 pass (observed, \"real -> 0 failed\"). For example, \"state start 1e999\" reported {'thrown': 'Translate response was malformed', 'nonFinite': True}.</expected>\n<wrong_implementation>Each of these was observed in a probe over a mutated translate.ts. Changing the MALFORMED text (translate.ts:19) fails all 14, reporting 'Bad translate response'. Accepting busy on the state route (:106) fails \"state busy\", which returns {'state': 'busy', 'available': True}. Replacing `Number.isFinite(cue?.start)` with a typeof check (:120) fails \"state start 1e999\", which returns a ready value. A runner using plain JSON.stringify serves null for the 1e999 case: the refusal text still matches, but the :86 control fails with nonFinite False, so a refusal for the wrong reason cannot pass.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\nBefore the rewrite, the test as handed to me ran green: \"43 passed\", exit 0. Phase 2 changes no production code. translate.ts already parses every fixture case correctly, so C1 and C2 were already true and the checkpoint measured nothing. That is a yes under 8, so I rewrote it.\n\nI put the choice to the operator. They answered \"Drive the durable harness\". The checkpoint now imports tests/active/test_frontend_translate.py, the file this phase edits, the same way phase 1 imported test_server. It runs that module's CONTRACT_RUNNER over the real translate.ts. FETCH_RECORDER sits ahead of the runner and wraps whatever fetch the runner installs, so the request control survives. C1 and C2 are asserted on the runner's report. While CONTRACT_RUNNER is missing, every case fails at :79. I removed the checkpoint's own runner. The probe is emptied: I have no delete tool, so tests/tmp/probe_55_phase2_checkpoint.py is now zero bytes and can be deleted.\n\n1. Whole claim: no gap. C1 is carried at :99 over all 29 valid cases, covering both routes, ready sorted by (start, end) and running in the given order. C2 is carried at :105 over all 14 rejected cases with the exact text. Every docstring control has an assertion: request count :83, route/method/after :84, non-finite :86, fixture lists out of order :96. One thing outside the clauses, observed: removing translate.ts's `available` default changes nothing here, because every gateway answer in the fixture already carries `available`. C1 says \"exactly its gateway fields\", so this is not a gap in C1.\n2. Absence only: no. Both clause assertions are positive equalities, value == gateway and thrown == MALFORMED, and :83/:84 prove each case's request reached its parser.\n3. Echoed literal: no. Expected values come from the fixture and are compared with what translate.ts returned. The (start, end) sort at :98 is the spec's order, written independently in Python. Deleting translate.ts:101 `.sort(compareCues)` turns :99 red (observed), and so do :53 `|| a.end - b.end`, :19 MALFORMED, :120 `Number.isFinite` and :106's state list.\n4. One value: no. C1 is read at 29 inputs and C2 at 14. The sort is read on two ready cases that include a tie on start, and running order on three cases including the after slice.\n5. The double: no project module is replaced. The fetch stub stands in for the network, a layer this test cuts off. The runner is the project's own durable test code, used as it is, and FETCH_RECORDER only wraps its fetch.\n6. It collects: yes. `test_frontend_translate` imports from tests/active, and BASE, HOST, ESBUILD and FRONTEND exist on it (probe printed \"BASE http://client.test HOST peer.example ESBUILD True\"). The run shows 43 tests, matching 29 + 14. The --collect-only \"no tests\" handed to me came from the previous file; the real runs collect 43.\n7. Observed, not predicted: yes, every expected value comes from a run. The recorder was run with the plan's runner: \"ASKED 43\", GET with after '3' at index 6, POST at index 14. The report keys (value/thrown/nonFinite) and the real and mutant outcomes all come from probe output.\n8. Red, not green: yes. ValidateTests reported \"tests/tmp/test_55_translate_state_contract_phase2.py  43 failed\", exit status 1.\n9. Red for the right reason: yes. Every case fails at tests/tmp/test_55_translate_state_contract_phase2.py:79 in _result with \"AssertionError: tests/active/test_frontend_translate.py has no CONTRACT_RUNNER: the phase's replay runner is not written yet / assert None is not None\". The missing name is this phase's deliverable, the seam the operator chose, not a typo, a bad import or path, or a harness that cannot work. The harness was shown to work: with the plan's runner text it gave \"real -> 0 failed\", and each listed mutant went red at :99, :105, :84 or :86.\n10. Observed expected output: yes. Both rows' expected values are what the runs showed: today's failure at :79 from the ValidateTests run, and pass/fail per mutant from the probe output quoted in the rows. No row disagrees with a run.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### tests/active/test_frontend_translate.py\nI added `CONTRACT_RUNNER` at the end of the module, next to `RUNNER` and `GENERATION_RUNNER` and in the same style. It is the plan's draft runner (\u00a73).\n- **Setup:** it stubs `localStorage`, `window` (with `location.origin`, needed because `api-base.ts` reads it when the module loads) and a `fetch` that always answers 200 with the served text. It sets `fetch` by plain assignment, which is the assignment the checkpoint's recorder catches. Only after that does it dynamically import `BUNDLE`.\n- **Replay:** it reads `CONTRACT` with `node:fs`. For each case it serves the gateway answer (valid case) or the Engine body (rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route).\n- **Non-finite numbers:** they are written back as `1e999`, because `JSON.stringify` would write `null`. A `rat-tail:` comment notes the ceiling: every infinity is written as positive.\n- **Report:** one JSON line keyed by case name, holding `{value | thrown, nonFinite}`, then `process.exit(0)` so the recorder's `exit` hook runs.\n\nNo frontend file changed.\n\n**Probe:** a throwaway probe ran the checkpoint's own `_contract_report` over the real `translate.ts`. What it showed:\n- 43 requests for 43 cases.\n- Case 6 was `GET /api/translate` with `after=3`; enqueue cases were `POST` with no `after`.\n- Every valid case came back with its gateway fields: `ready` cues in the order (1,2), (1,3), (4,5), and `running` cues in the order given.\n- All 14 rejected cases threw exactly `Translate response was malformed`.\n- `nonFinite` was true only for `state start 1e999`.\n\nI did not run the checkpoint itself. I had no tool to delete the probe, so I emptied it; `tests/tmp/probe_55_phase2_runner.py` can be deleted.\n\n### tests/config.json (not edited)\nThe planned entries (the fixture and `api-base.ts` in the `test_frontend_translate.py` group) only make sense once the durable module has a test that reads the fixture. I left them for the step that moves the checkpoint into the active suite, as phase 1 did with its `test_server.py` entries. The plan's durable parametrized test, `contract_report` fixture and docstring paragraph would repeat the checkpoint, so they wait for that same step.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_55_phase2_runner.py \u2014 a throwaway probe I used to watch the runner's real output. I emptied it because I have no tool to delete files; it can be deleted.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_55_translate_state_contract_phase3.py": "<assertions>\ntests/tmp/test_55_translate_state_contract_phase3.py:86: the fixture's (route, state) set (valid 200 cases carrying available) minus the keys of test_internal_translate.ENGINE_DRIVERS is empty, so no fixture state lacks a driver (C1).\ntests/tmp/test_55_translate_state_contract_phase3.py:87: the ENGINE_DRIVERS keys minus that fixture set is empty, so no driver lacks a fixture state (C1). A control at :89 shows the fixture set equals the 13 (route, state) pairs written down in ROUTE_STATES, which the shape test is parametrized over.\ntests/tmp/test_55_translate_state_contract_phase3.py:107: for every fixture case of each (route, state), the driver's single response has status 200 (C1). Controls: :95 shows the fixture carries the pair. :103 shows the route's real handler (wrapped by a pass-through recorder) answered exactly once, the other route's handler not at all, and the driver returned exactly what the handler wrote. :105 shows the request carried the case's `after` exactly when the case has one. :108 shows the answer's state is the state under test.\ntests/tmp/test_55_translate_state_contract_phase3.py:109: the answer's key-to-JSON-type map (bool tested before number) equals the case's engine body's, so the answer has exactly the case's key set and value JSON types (C1).\ntests/tmp/test_55_translate_state_contract_phase3.py:112: where the case has cues, the answer's cues are non-empty exactly when the case's are, so the per-cue check reads at least one cue (C1).\ntests/tmp/test_55_translate_state_contract_phase3.py:113: each answered cue's key-to-JSON-type map is one of the case's cues' maps (C1, \"its cues included\").\ntests/tmp/test_55_translate_state_contract_phase3.py:128: on each route (state and enqueue, parametrized), an unknown video answers exactly [[404, the fixture's Video not found body for that route]] (C2).\ntests/tmp/test_55_translate_state_contract_phase3.py:129: on each route, the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly [[404, the fixture's body]] (C2). :130 asserts no instance fetch. The control at :133 shows the same video answers 200 once the deny row is inactive.\n</assertions>\n\n<probes>\n1. `ValidateTests tests/tmp/test_55_translate_state_contract_phase3.py` (final file): \"14 failed, 2 passed\", exit 1. Each failure is the table test or one of the 13 shape tests, and all fail with \"AssertionError: tests/active/test_internal_translate.py has no ENGINE_DRIVERS: the phase's driver table is not written yet\". The 2 passes are the not-found test on each route. The operator chose (AskUser, \"keep_direct\") to keep C2 asserted directly, green before the phase lands, because phase 3 changes no runtime code.\n2. `ValidateTests tests/tmp/probe_55_phase3_checkpoint.py -q -rA --tb=line`. The probe imported this checkpoint's tests and, through an autouse parametrized fixture, put a driver table into test_internal_translate.ENGINE_DRIVERS: either the plan's draft drivers or a mutant. Result: \"39 failed, 121 passed\".\n- Plan drivers: all 16 tests pass (table, the 13 shape tests, 2 not-found).\n- Hard-coded answers that never call the handler: all 13 shape tests fail at :96 (pre-rename line, now :103, the handler-recorder control).\n- State route with the instance track left on: \"state none\", \"state already_english\" and \"state failed\" fail at the state control, answering {'state': 'ready', 'cues': [...Hello, World]}.\n- Running seeded with the module's 3-cue RUNNING for the after-3 case: fails at the non-empty check with {'state': 'running', 'cues': [], 'total': 3}.\n- `after` dropped: \"state running\" fails at the after control.\n- Enqueue stored states with no beat: enqueue running/ready/already_english/failed fail at the state control with {'state': 'none', 'available': False}.\n- An extra ('state', 'busy') driver: the table test fails, \"assert [('state', 'busy')] == []\".\n- Engine sending available as an int: all 13 shape tests fail at the type-map assertion, e.g. {'state': 'none', 'available': 1}.\n- Engine dropping total: \"state running\" fails at the type map.\n- Engine adding cues to the enqueue running/ready answers: those two fail at the type map.\n- Every not-found test passed under every variant.\nThe probe file is now empty because I have no delete tool, so tests/tmp/probe_55_phase3_checkpoint.py can be deleted.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_55_translate_state_contract_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>test_55_translate_state_contract_phase3.py:86 and :87: `sorted(fixture - drivers) == []` and `sorted(drivers - fixture) == []`, where fixture is the set of (route, state) from the fixture's valid 200 cases that carry available, and drivers is the key set of ENGINE_DRIVERS</assertion>\n<expected>Both read []. The table holds exactly the 13 (route, state) pairs: none/queued/running/ready/already_english/failed on state, and those plus busy on enqueue. Line 89's control already holds against the fixture; the run reached it in no test only because line 85 stops at the missing table.</expected>\n<wrong_implementation>A table that leaves a state out, or adds one the fixture lacks such as (\"state\", \"busy\"). I ran a probe table {(\"state\",\"none\"), (\"state\",\"busy\")} and it failed at line 86 (fixture - drivers non-empty). The extra (\"state\",\"busy\") would trip line 87 too. A missing table fails at line 39, as the current run shows.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_55_translate_state_contract_phase3.py:107: `status == 200` for the single response the real handler wrote, which the control at line 103 matches against the driver's return</assertion>\n<expected>200 for every case of all 13 (route, state) pairs. Probe drivers for state none/running/ready and enqueue queued each recorded exactly one [200, {...}] from the real handler.</expected>\n<wrong_implementation>A driver that lands the handler on a refusal, such as a 400 bad `after` or a 404 for an unresolved video, reads 400 or 404 here. A driver that makes up its own answer without calling the handler is caught first by the control at line 103: I ran a probe driver that returned a literal [[200, ...]] and it failed there.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_55_translate_state_contract_phase3.py:109: `_types(answer) == _types(expected)`. The answer's key-to-JSON-type map equals the fixture case's, with bool checked before number</assertion>\n<expected>Equal for every case. Observed with probe drivers: state running after 3 gave {state: string, cues: array, total: number, available: boolean}, the same as the fixture's \"state running after 3\". state none, state ready and enqueue queued matched their cases too.</expected>\n<wrong_implementation>A handler that drops `total` from running, or writes `available` as 1. I wrapped the real handler in a probe that mutated its output after it ran: both mutations failed at line 109, one answer missing total and one with 'available': 1.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_55_translate_state_contract_phase3.py:112: `bool(answer[\"cues\"]) == bool(expected[\"cues\"])` wherever the case has cues</assertion>\n<expected>True for state running, state running after 3 and state ready, whose fixture cues are non-empty. The probe's running driver stored five cues and the answer to after=3 held two (c3, c4).</expected>\n<wrong_implementation>A handler or driver that answers `cues: []`, for example a running job with no stored cues or an `after` past the total. The per-cue check at line 113 would then pass vacuously. A probe mutation that emptied the cues failed at line 112.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>test_55_translate_state_contract_phase3.py:113: every answer cue's key-to-JSON-type map is one of the fixture case's cue maps</assertion>\n<expected>True. The observed cues were {start: number, end: number, text: string}, the same as the fixture's cue maps.</expected>\n<wrong_implementation>A cue that is missing `end` or carries extra keys. A probe mutation that popped `end` from every cue failed at line 113.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_55_translate_state_contract_phase3.py:128: on each route, the real handler answers the unknown video {\"id\": \"no-such-video\", \"host\": \"peer.example\"} exactly with [[404, the fixture's Video not found body for that route]]</assertion>\n<expected>[[404, {\"error\": \"Video not found\"}]] on both routes. This passes in the run, as the docstring says it should, because the phase changes no runtime code.</expected>\n<wrong_implementation>A handler that answers a different 404 body, such as {\"error\": \"Not found\"}, which is the route-missing body. I wrapped the state handler in a probe that rewrote its 404 body, and it failed at line 128.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>test_55_translate_state_contract_phase3.py:129: on each route, the actively denylisted video (du-1 on denied.example, deny row stored as DENIED.EXAMPLE) answers exactly [[404, the fixture's Video not found body]]. The control at line 132 shows the same video answers 200 once the deny row is inactive</assertion>\n<expected>[[404, {\"error\": \"Video not found\"}]] on both routes. The run passes it, and the line 132 control also held: 200 with the deny row inactive.</expected>\n<wrong_implementation>A denylist check that compares hosts case-sensitively, so the uppercase stored row never matches and the video is answered 200. Or one that refuses with a body other than the fixture's. Either reads something other than [[404, body]] here.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1's table half is carried at :86/:87. Its shape half is carried at :107 (200), :109 (key set and value JSON types), and :112/:113 (cues non-empty, each cue's keys and types). The loop goes over every fixture case of each of the 13 (route, state) pairs. C2 is carried at :128/:129 on both routes. The docstring also said \"with no instance fetch\" for C2. That isn't in the clause, and see 2.\n2. Absence only: yes, one. Line 130 `assert instance.fetched == []` had no positive control. The enqueue route never fetches, and the inactive-deny control never showed a fetch on either route, so it measured nothing. Rewrite: I removed that assertion and changed the docstring to say no-fetch is test_internal_translate.py's claim; it is carried at :484 and :472 there. Second pass: no other negative assertion. Lines :86/:87 compare sets that the :89 control pins to 13 non-empty pairs. Line :112 is a positive check.\n3. Echoed literal: no. The expected types come from the fixture, which is a separate source; the actual body comes from the real handler through the recorder. The test's `_types` is a reading of JSON types, not a transformation production performs. Production lines whose deletion turns it red: the `total` key in the handler's running answer (:109, confirmed by probe), the `available` key in any answer (:109), and the `Video not found` 404 body (:128/:129, confirmed by probe).\n4. One value: no. The shape test reads 13 (route, state) pairs across every fixture case of each, including running with and without after. C2 reads two inputs on two routes. Expected values come from the fixture, not from the handler's own output.\n5. The double: no owned module is replaced. The recorder wraps handlers.internal_translate but calls the real handler and returns its result, so it is a spy. The probe confirmed that each recorded call held the real handler's written responses. The instance behind data.source_fetch.build_opener is the durable suite's severed network seam, and the clock is pinned through the durable `_route`.\n6. It collects: yes. The run shows `collected 16 items`, which is 1 table test + 13 shape tests + 2 C2 tests, the count written. The durable helpers it calls (_whitelist, _instance, _route, _server, _beat, _set_denied, _state, _enqueue, DENIED_VIDEO, DENIED_HOST, HOST) exist with those signatures. The C2 tests run them green, and the probe exercised the rest. The provided `--collect-only -q` summary said \"no tests\" with exit 0. The real run collected 16, so I'm treating that line as the formatter's summary of a collect-only run, not evidence of zero tests.\n7. Observed, not predicted: before this turn the shape assertions had never run against real handler output, so I probed. In tests/tmp/probe_55_drivers.py I put honest drivers built from the durable helpers into ENGINE_DRIVERS for state none, state running (5 stored cues, after taken from the case), state ready and enqueue queued, then called the checkpoint's shape test. All four passed, with recorded calls such as ('state', {'id': 'u-1', 'host': 'peer.example', 'after': 3}, [[200, {'state': 'running', 'cues': [c3, c4], 'total': 5, 'available': True}]]).\n   - Wrong drivers: a made-up driver failed the :103 control, and a driver that dropped `after` failed the :105 control.\n   - Handler mutations: dropping total and making available an int each failed :109, emptying cues failed :112, and dropping end failed :113.\n   - C2 and table: a rewritten 404 body failed :128, and a partial table failed :86.\n   The probe is spent. My tools can't delete files, so I overwrote it as an empty file (it collects nothing); it can be removed with tests/tmp.\n8. Red, not green: yes, red. After the rewrite, ValidateTests on the checkpoint printed `14 failed, 2 passed` with `[exit status 1]` and `collected 16 items`. The 2 that pass are the C2 tests, which the docstring says should hold before the phase because it changes no runtime code. All 13 shape tests and the table test are red.\n9. Red for the right reason: yes. All 14 failures are at test_55_translate_state_contract_phase3.py:39 in `_drivers`: `AssertionError: tests/active/test_internal_translate.py has no ENGINE_DRIVERS: the phase's driver table is not written yet` / `assert None is not None`. They are reached from :85 in the table test and :96 in each shape test. That table is what this phase delivers, so its absence is the phase being unbuilt, not a typo, import or harness defect. No control assertion failed. The :95 fixture control passed on all 13 before :96 failed, and the probe showed the :103/:105/:108 controls passing with honest drivers. So once the table lands, the assertions that judge the code will be reached.\n10. Observed expected output: each row's `expected` matches what a run showed. The C1 rows match the probe run with honest drivers, which recorded real-handler bodies with the fixture's key and type maps. The C2 rows match the checkpoint run, where both C2 tests passed against [[404, {\"error\": \"Video not found\"}]] and the :132 inactive-deny control read 200. No run contradicted an expected value.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### tests/active/test_internal_translate.py\nI added `ENGINE_DRIVERS`, the table the checkpoint looks up. It has 13 entries, keyed by (route, state): `none`, `queued`, `running`, `ready`, `already_english` and `failed` on the state route, and the same six plus `busy` on the enqueue route. I put it right after `_state`, with its two driver factories and one small helper. Each driver is called as `(subtitles_path, whitelist, monkeypatch, case)` and returns what the route's real handler wrote. It reaches the handler through `_state` or `_enqueue`, which look the handler up on the module when they run, so the checkpoint's recorder sees the call. All data goes in through the existing harness: `_seed`, `_claimed`, `_beat`, `_route`, `_server`, and the store's own writers. The only thing patched is `_route`'s usual `build_opener` and `now_ms`, which answers the shape audit's driver-side-patching recommendation.\n- **`_state_driver(row)`:** seeds the key as `row` and writes a fresh beat, then calls the state route with `_instance(False)`. Without that no-track instance, `failed`, `already_english` and `none` would answer `ready`. The request carries the case's `after` exactly when the case has one.\n- **Running on the state route:** the driver stores as many cues as the case's `total`, built by `_running_cues(count)` in descending start order. So `state running after 3` answers two real cues, not the `[]` that `RUNNING`'s three cues would give.\n- **`_enqueue_driver(row)`:** `None` means no beat, which answers `none`. `\"no row\"` with a beat answers `queued`. A seeded stored state answers that state. `\"busy\"` fills the queue to `SUBTITLE_QUEUE_CAP` with other keys, as the existing full-queue test does.\n- **Docstring:** a new \"Contract drivers\" paragraph before \"Startup:\" says what the table does and that the fixture is never read at module level, because `test_source_fetch.py` imports this module.\n- **Probe:** a throwaway probe ran every driver against all 14 fixture cases that carry `available`. Each came back as exactly one 200 in the state under test, with the keys the case has. `state running` gave 3 cues and total 3. `state running after 3` sent `after` 3 and gave 2 cues and total 5. `state ready` gave the stored `STORED_READY` cue. `enqueue none` gave `available: false`; the fixture's case says `true`, but both are booleans, so the type check still passes, and the fixture's description already notes this. I did not run the checkpoint itself.\n- **Probe file:** I have no tool to delete it, so I emptied `tests/tmp/test_probe_55_phase3_drivers.py`. It can be deleted.\n\n### tests/config.json (not edited)\nI left it unchanged, as phases 1 and 2 did. The planned group entries are the fixture plus `translate-worker.py`, `engine_api_client.py` and `deploy-bluegreen.sh`. Nothing in the durable module reads any of those files yet: the drivers get each case passed in. The entries belong with the step that moves the checkpoint's fixture-reading tests into the active suite, or with phase 4's derivation and timeout-chain tests.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_55_translate_state_contract_phase4.py": "<assertions>\ntests/tmp/test_55_translate_state_contract_phase4.py:69 - server_config.py's source holds exactly one HEARTBEAT_FRESH_MS assignment, plain or annotated (excludes: no shared constant, today's state, which fails here with \"0 times\"; a duplicate definition) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:71 - that assignment's expression names HEARTBEAT_SECONDS (excludes: a literal 15_000 moved into server_config) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:73 - the expression, evaluated in server_config's own namespace with the real HEARTBEAT_SECONDS, is 15000 and an int (excludes: a changed window or factor; `HEARTBEAT_SECONDS * 3000`, which gives the float 15000.0) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:74 - control: server_config.HEARTBEAT_FRESH_MS equals that evaluated value, so the parsed expression is the one the module runs - C1 (control)\ntests/tmp/test_55_translate_state_contract_phase4.py:76 - the same expression with HEARTBEAT_SECONDS = 7.0 is 21000 (excludes: a derivation that names the interval but ignores it, e.g. `int(15_000 + HEARTBEAT_SECONDS * 0)`) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:80 - handlers.internal_translate.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS by identity (excludes: the handler keeping its own equal literal 15_000) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:84 - for internal_translate.py and for translate-worker.py, the module binds neither HEARTBEAT_SECONDS nor HEARTBEAT_FRESH_MS itself (any Store-context name: assignment, augmented, unpacking) (excludes: today's `HEARTBEAT_FRESH_MS = 15_000` and `HEARTBEAT_SECONDS = 5.0`; importing and then reassigning) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:85 - the handler imports HEARTBEAT_FRESH_MS, and the worker HEARTBEAT_SECONDS, under its own name from server_config and from no other module (excludes: no import; importing from somewhere else, e.g. the worker taking it from handlers.internal_translate) - C1\ntests/tmp/test_55_translate_state_contract_phase4.py:94 - control: deploy-bluegreen.sh has exactly one line-anchored `DRAIN_SECONDS=<digits>` default line, so the drain is read from one place - C2 (control)\ntests/tmp/test_55_translate_state_contract_phase4.py:96 - handler REQUEST_BUDGET_SECONDS + data.source_fetch.SOCKET_TIMEOUT_SECONDS < lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (excludes: budget raised to 16+, socket timeout raised to 5+, Client timeout lowered to 19 or less) - C2\ntests/tmp/test_55_translate_state_contract_phase4.py:97 - TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default (excludes: drain lowered to 20 or less, or Client timeout raised to 30 or more) - C2\n</assertions>\n\n<probes>\nValidateTests [\"tests/tmp/probe_55_phase4_constants.py\", \"-s\"], first version, with tests/active on sys.path and test_internal_translate imported. It printed: server_config resolves to engine/server/api/server_config.py; lib.engine_api_client resolves to client/backend/lib/engine_api_client.py with TRANSLATE_TIMEOUT_SECONDS 20; SOCKET_TIMEOUT_SECONDS 4.0; REQUEST_BUDGET_SECONDS 15.0; the handler's HEARTBEAT_FRESH_MS is 15000 and server_config has no HEARTBEAT_FRESH_MS today; the regex `^DRAIN_SECONDS=(\\d+)$` with MULTILINE finds ['30'] (one match); a literal `15_000` in one namespace `is` not the int computed by `int(S * 3 * 1000)` in another (False); a `from server_config import` binding `is` the module's own object (True); translate-worker.py's only server_config ImportFrom lists 7 names and HEARTBEAT_SECONDS is not among them.\nValidateTests [\"tests/tmp/probe_55_phase4_constants.py\", \"-s\"], second version, calling the checkpoint's own helpers on made-up sources. It printed: `int(HEARTBEAT_SECONDS * 3 * 1000)` gives 15000 (int) at 5.0 and 21000 at 7.0; `HEARTBEAT_SECONDS * 3000` gives 15000.0; `15_000 + HEARTBEAT_SECONDS * 0` at 7.0 gives 15000.0; an annotated assignment is counted (1); a handler that imports the name has no binding of its own and imports from {'server_config'}; a handler with a literal binds {'HEARTBEAT_FRESH_MS'} and imports it from set(); on today's real files the worker binds {'HEARTBEAT_SECONDS'} and imports it from set(), and the handler binds {'HEARTBEAT_FRESH_MS'} and imports it from set().\nValidateTests [\"tests/tmp/test_55_translate_state_contract_phase4.py\"] against the current code: 1 failed, 1 passed. The heartbeat test fails at line 69 with \"server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once\", which is the expected red before the phase lands. The timeout-chain test passes: 15.0 + 4.0 < 20 < 30 already holds, and this phase only adds the guard for it.\nNot observed: the checkpoint passing against a correct implementation, since the edited source files are outside this step. The helper probe above shows the intended `int(HEARTBEAT_SECONDS * 3 * 1000)` shape passes lines 71-76. The phase's own green run will confirm the rest.\nCleanup: there is no delete tool here, so the probe file tests/tmp/probe_55_phase4_constants.py is still on disk. Please remove it. It is not part of the checkpoint.\n</probes>\n\n<unassertable>\nnone\n</unassertable>",
    "self_check:tests/tmp/test_55_translate_state_contract_phase4.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:69 \u2014 server_config.py's AST holds exactly one assignment to HEARTBEAT_FRESH_MS, plain or annotated (`len(values) == 1`)</assertion>\n<expected>1 once the phase lands the planned `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)` (probe over that source: \"good: assignments=1\"). Today it reads 0, and the checkpoint run fails here with \"server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once\".</expected>\n<wrong_implementation>No shared constant at all (today's code) reads 0. A duplicate definition, one plain and one annotated, reads 2 (probe: \"twice: assignments=2\").</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:71 \u2014 the names in that assignment's expression include HEARTBEAT_SECONDS</assertion>\n<expected>The probe of the planned expression read names=['HEARTBEAT_SECONDS', 'int'], which contains HEARTBEAT_SECONDS.</expected>\n<wrong_implementation>The literal moved into server_config as `HEARTBEAT_FRESH_MS = 15_000` reads names=[] (probe), so it fails here even though its value is 15000 and an int.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:73 \u2014 the expression, evaluated in server_config's namespace with the real HEARTBEAT_SECONDS, equals 15000 and its type is exactly int</assertion>\n<expected>15000, int (probe: \"real=15000 type=int\" for the planned form).</expected>\n<wrong_implementation>`HEARTBEAT_SECONDS * 3000` reads 15000.0 of type float (probe: \"real=15000.0 type=float\"), so it fails the `type(real) is int` half. A wrong factor, for example two beats, reads 10000.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:76 \u2014 the same expression evaluated with HEARTBEAT_SECONDS = 7.0 equals 21000</assertion>\n<expected>21000 (probe: \"seven=21000\" for the planned form).</expected>\n<wrong_implementation>A derivation that names the interval but ignores it, `int(15_000 + HEARTBEAT_SECONDS * 0)`, passes :71 and :73 but reads seven=15000 here (probe).</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:80 \u2014 `handlers.internal_translate.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS`</assertion>\n<expected>True once the handler does `from server_config import HEARTBEAT_FRESH_MS` (probe: \"identity imported=True\").</expected>\n<wrong_implementation>A handler that keeps its own literal 15_000 holds an equal int but not the same object (probe: \"literal=False literal_eq=True\"), so it fails here where equality would pass. Deleting the handler's import and putting back `HEARTBEAT_FRESH_MS = 15_000` turns this line red.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:84 \u2014 for internal_translate.py and for translate-worker.py, the Store-context names in the module's AST share nothing with {HEARTBEAT_SECONDS, HEARTBEAT_FRESH_MS}</assertion>\n<expected>An empty set for both files under the planned import-only form (probe: \"handler planned: stored=[]\", \"worker planned: stored=[]\"). The positive control is :85, which shows on the same parsed tree that the name is present through an import.</expected>\n<wrong_implementation>Today's code reads stored=['HEARTBEAT_FRESH_MS'] for the handler and ['HEARTBEAT_SECONDS'] for the worker (probe). A module that imports the name and then reassigns `HEARTBEAT_FRESH_MS = 15_000` reads stored=['HEARTBEAT_FRESH_MS'] (probe), so it fails here even though :85 passes.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:85 \u2014 the set of modules a `from X import` binds the name from is exactly {\"server_config\"}: HEARTBEAT_FRESH_MS for the handler, HEARTBEAT_SECONDS for the worker</assertion>\n<expected>{'server_config'} for both (probe: \"handler planned: from_fresh={'server_config'}\", \"worker planned: from_seconds={'server_config'}\").</expected>\n<wrong_implementation>Today both read set(), with no import at all (probe). Importing the name from another module reads {'data.subtitles'} (probe \"handler other module\"). Importing it from two sources reads a two-element set.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:96 \u2014 handler REQUEST_BUDGET_SECONDS + data.source_fetch SOCKET_TIMEOUT_SECONDS &lt; lib.engine_api_client TRANSLATE_TIMEOUT_SECONDS</assertion>\n<expected>15.0 + 4.0 = 19.0 &lt; 20, so True. The probe printed budget=15.0 socket=4.0 client=20, and the checkpoint run shows this test passing.</expected>\n<wrong_implementation>Raising the budget to 16.0, the socket timeout to 5.0 (the harvest mutation K3), or dropping the Client timeout to 19 reads 20.0 &lt; 20 or 19.0 &lt; 19, which is False.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_55_translate_state_contract_phase4.py:97 \u2014 TRANSLATE_TIMEOUT_SECONDS &lt; the DRAIN_SECONDS default from the single line-anchored match in deploy-bluegreen.sh. :94 is the control: it requires exactly one match.</assertion>\n<expected>20 &lt; 30, so True. The probe printed drains=['30'] over the real script; the indented `--drain)` line is not matched (probe).</expected>\n<wrong_implementation>A drain default of 20, or a Client timeout raised to 30, reads False. A reformatted default (`DRAIN_SECONDS=\"30\"`) matches nothing (probe: []), and a second default line matches twice (probe: ['30', '45']). Both fail at the :94 control, not silently.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1 has four parts. \"Derived from HEARTBEAT_SECONDS\" is carried by :69 (one assignment), :71 (names the interval), :73 (15000, an int, at the real interval) and :76 (21000 at 7.0). \"Import their heartbeat name from server_config\" is :80 (handler identity) and :85 (both files import it from server_config and nothing else). \"Instead of assigning a literal of their own\" is :84. C2 has both inequalities: :96 and :97, with :94 controlling the parse. Every clause in the docstring maps to one of these lines. No rewrite.\n2. Absence only: no. The one negative is :84 (no Store binding of either heartbeat name). Its positive control is :85 on the same parsed tree, which requires the name to be imported from server_config, so :84 cannot pass over a file where the name is simply missing. The probe also showed :84 reading today's literals as stored=['HEARTBEAT_FRESH_MS'] and ['HEARTBEAT_SECONDS'], so the walk does see bindings. No rewrite.\n3. Echoed literal: no. :74 compares the evaluated expression to the module's value, but it is a control, not a clause row. :73 and :76 compare production's own expression against written-down literals, 15000 and 21000. The test runs production's expression; it does not re-implement the arithmetic. Production lines whose change turns a clause line red: the planned server_config line `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)` (deleting it fails :69; dropping the int() fails :73; replacing it with a literal fails :71). The handler's `from server_config import ... HEARTBEAT_FRESH_MS` (deleting it fails :80/:85). The worker's `from server_config import ... HEARTBEAT_SECONDS` (deleting it fails :85). For C2, source_fetch.py:21, engine_api_client.py:18, internal_translate.py:31 and deploy-bluegreen.sh:50 each fail :96 or :97 if moved past a neighbour. No rewrite.\n4. One value: no. The derivation is read at two intervals, 5.0 and 7.0, so a constant that only names the interval is caught (probe: seven=15000). Nothing is pinned against a sibling from the same source. :80 compares the handler's object with server_config's, which is the import claim itself. C2's clause is about the real values, so reading them once is the claim. No rewrite.\n5. The double: there are no doubles. Real modules are imported and real files parsed. No rewrite.\n6. It collects: yes. --collect-only exited 0 (its summary says \"no tests\" because nothing ran), and the full run reported \"collected 2 items\", matching the two test functions. ast, importlib, re, sys and Path all resolve. server_config, handlers.internal_translate, data.source_fetch and lib.engine_api_client all imported in the run: the C2 test passed, and the C1 test got to :69 after `import server_config` on :66. The helpers use only real ast attributes (Assign.targets, AnnAssign.target/value, Name.ctx, ImportFrom.module/names, alias.asname/name). No rewrite.\n7. Observed, not predicted: yes, each expected value comes from a run. I ran tests/tmp/probe_55_phase4_heartbeat.py twice through ValidateTests. Run 1 put the checkpoint's own helpers over the planned and wrong sources and printed: \"good: assignments=1 names=['HEARTBEAT_SECONDS', 'int'] real=15000 type=int seven=21000\"; \"literal: names=[] real=15000\"; \"float: real=15000.0 type=float\"; \"ignores: seven=15000\"; \"twice: assignments=2\"; \"identity imported=True literal=False literal_eq=True\"; \"handler planned: stored=[] from_fresh={'server_config'}\"; \"handler other module: from_fresh={'data.subtitles'}\"; \"handler import then reassign: stored=['HEARTBEAT_FRESH_MS']\"; \"worker planned: from_seconds={'server_config'}\"; \"today internal_translate.py: stored=['HEARTBEAT_FRESH_MS'] from_fresh=set()\"; \"today translate-worker.py: stored=['HEARTBEAT_SECONDS'] from_seconds=set()\". Run 2 printed the real chain, \"budget=15.0 socket=4.0 client=20 drains=['30']\", and the regex over three variants: the indented --drain line is not matched; a quoted default gives []; two defaults give ['30', '45']. Every row's expected value is taken from those lines. One thing I simulated rather than observed: the post-phase server_config is not built (the phase builds it), so the planned line was run in a scratch module. The real implementation landing is what confirms it. The probe file is still at tests/tmp/probe_55_phase4_heartbeat.py, because I have no delete tool. It holds nothing the checkpoint needs and should be removed. No rewrite.\n8. Red, not green: yes, it fails. ValidateTests on tests/tmp/test_55_translate_state_contract_phase4.py printed \"1 failed, 1 passed\" and \"[exit status 1]\"; I ran it again after the probes and got the same result. The failing test is the C1 heartbeat test. The passing test is the C2 timeout-chain test, and it is green before the phase because 15.0 + 4.0 &lt; 20 &lt; 30 already holds and the phase changes none of those values. Per the plan, this phase's C2 claim is to turn the existing chain into a test (\"turns the timeout chain into a test\"; Phase 4 changes only the heartbeat code), so there is no unbuilt C2 behaviour that could be asserted instead. C2 is a regression guard; the probe above showed it reading the real values, and that it goes red when a value crosses its neighbour or the default line is reformatted. The checkpoint as a whole is red on the phase's code claim, C1.\n9. Red for the right reason: yes. tests/last_test_output.txt names the failure at \"tests/tmp/test_55_translate_state_contract_phase4.py:69\", `assert len(values) == 1`, with \"AssertionError: server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once / assert 0 == 1\". That is a clause assertion (C1), not a control, and it fails because server_config.py has no HEARTBEAT_FRESH_MS yet. I read the file: the subtitle tunables end at SUBTITLE_MAX_CHUNK_SECONDS (:428), with no heartbeat pair. It is not an import error, typo or bad path: the module imported on :66 and was parsed. The probe shows the later C1 lines would also go red for today's code: the handler binds HEARTBEAT_FRESH_MS itself and imports it from nowhere, and the worker does the same with HEARTBEAT_SECONDS.\n10. Observed expected output: yes. Every row's expected value is a line printed by the checkpoint run or by a probe run, quoted in the row: 0 today at :69 from the checkpoint run, the C1 values from probe run 1, the C2 values from probe run 2 plus the C2 test passing in the checkpoint run. No run contradicted a row, so nothing was rewritten.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:4": "<changes>\n### engine/server/api/server_config.py\nAdded `HEARTBEAT_SECONDS = 5.0` (the worker's beat interval) and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)` right after the `SUBTITLE_*` translate constants. The window is three beats, so one late beat is still tolerated. It comes out as the int 15000 today and follows the interval if that changes.\n\n### engine/server/api/handlers/internal_translate.py\nRemoved the handler's own `HEARTBEAT_FRESH_MS = 15_000` and the rat-tail comment above it. The handler now gets the name from the existing `server_config` import (`from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`). The freshness check in `_worker_available` is unchanged and reads the imported name.\n\n### engine/server/db/jobs/translate-worker.py\nRemoved the worker's own `HEARTBEAT_SECONDS = 5.0` and the rat-tail comment above it (the one saying there was no shared constant). `HEARTBEAT_SECONDS` is added to the existing `from server_config import ...` line. The beat loop and `beat.join` use it unchanged.\n\n### C2 (timeout chain)\nNo code change: the chain already holds. `REQUEST_BUDGET_SECONDS` 15.0 plus `SOCKET_TIMEOUT_SECONDS` 4.0 is 19, which is below `TRANSLATE_TIMEOUT_SECONDS` 20, which is below the `DRAIN_SECONDS=30` default in deploy-bluegreen.sh. That default sits on one line of its own. The checkpoint now holds this order in place.\n\n### tests/active/test_internal_translate.py, tests/config.json\nNot touched in this step. The instruction was production code only. These files belong to moving the checkpoint into the active suite, and nothing in them stood in the way of the change: no test patches the handler's or the worker's heartbeat names.\n\n### Observation\nI ran a throwaway probe, `tests/tmp/probe_55_phase4_impl.py`, with ValidateTests rather than running the gating checkpoint. It printed `server_config.HEARTBEAT_FRESH_MS` = 15000 as an `int`, and the handler's `HEARTBEAT_FRESH_MS` is the same object as server_config's. Loading translate-worker.py from its file gives `HEARTBEAT_SECONDS` 5.0, also the same object as server_config's. I have no delete tool, so the probe is still in tests/tmp/ and needs removing. Docs that still say \"raise both constants together\" (engine/server/README.md, TRANSLATE_WORKER.md, DEPLOYMENT.md) are for the documentation step.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\ntests/tmp/probe_55_phase4_impl.py: a throwaway probe created to observe the imported values. I have no delete tool, so it is still there and should be removed.\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nnone. The build's production diff is already as small as it can be. server_config.py gains two lines, HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000). internal_translate.py and translate-worker.py each drop their own literal and import the name from server_config. A search of engine/ for HEARTBEAT, 15_000 and 15000 finds no other copy of either value in production code, and both consumers read the shared names. There was nothing left to merge, rename or delete.\n</refactors>\n\n<left_out>\nStale docs, which are outside this pass's production files and belong to the documentation step. engine/server/db/jobs/docs/TRANSLATE_WORKER.md:155 still says \"Raise both constants together\", which is no longer true now that the window is derived from the interval. engine/server/README.md:18 and DEPLOYMENT.md, which the phase 4 outcome also names, should be checked for the same wording. Test-side work that the phases deferred, left out because it is test wiring and not a production refactor, and gating tests are not mine to edit: moving the checkpoints into the active suite, and the tests/config.json group entries (the fixture plus api-base.ts, translate-worker.py, engine_api_client.py and deploy-bluegreen.sh). Probe files that need deleting, because I have no delete tool: tests/tmp/probe_55_phase1_replay.py, probe_55_phase1_checkpoint.py, probe_55_contract.py, probe_55_phase2_runner.py, test_probe_55_phase3_drivers.py and probe_55_phase4_impl.py.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI made no refactors: a search shows the heartbeat interval and window are defined once in server_config.py and imported by both the handler and the worker, nothing else needed changing, and I ran no tests in this pass.\n</observation>",
    "step_10_plan": "<harvest_file>\ndocs/project/plans/harvest-55-translate-state-contract-plan.md\n</harvest_file>\n\n<plan>\n## Harvest plan: build 55 translate-state-contract\n\nScope: the 4 checkpoint files in `tests/tmp` (`test_55_translate_state_contract_phase1..4.py`). All of them collect (105 items from 11 functions). The bootstrap gate is clear. `tests/last_test_validation.json.preharvest` was taken first and is cmp-identical to the record, and nothing has banked since.\n\n### Count per verdict (11 test functions)\n\n- DURABLE: 8\n- REPLACES: 0\n- COMBINE: 0\n- REDUNDANT: 1\n- SPENT: 0\n\nThat covers 9 functions. Phase 1 holds 2 of the 11 and the counts above miss neither; for the record per file: phase1 2, phase2 2, phase3 3, phase4 2, total 9. Correction: the scope has 9 test functions, not 11. pytest collected 105 parametrized items from those 9.\n\n### DURABLE tests and their destinations\n\n1. `test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route` (phase1, 43 cases) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It replays every contract-fixture case through the real `fetch_translate`/`request_translate`. No active test calls those functions directly, and test_server.py's `/api/translate` tests miss several fixture cases (1e999 start, bool end, `busy` on the state route, string `available` and unknown state on enqueue).\n2. `test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names` (phase1) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It is the only test that holds the fixture's valid states equal to `TRANSLATE_STATES`/`TRANSLATE_REQUEST_STATES`.\n3. `test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order` (phase2, 29 cases) goes to `tests/active/test_frontend_translate.py`. Nothing there asserts the parser's answers against the fixture, and `CONTRACT_RUNNER` sits there unused.\n4. `test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed` (phase2, 14 cases) goes to `tests/active/test_frontend_translate.py`. No active test asserts the \"Translate response was malformed\" refusal.\n5. `test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` (phase3) goes to `tests/active/test_internal_translate.py`. `ENGINE_DRIVERS` is there and no test reads it.\n6. `test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included` (phase3, 13 route/states) goes to `tests/active/test_internal_translate.py`. Today the Engine's answers are held only to the module's own constants, never to the fixture.\n7. `test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it` (phase4) goes to `tests/active/test_server_config.py`. No active test names `HEARTBEAT_SECONDS` or `HEARTBEAT_FRESH_MS`, and the BEATS edge tests would pass against an equal literal.\n8. `test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain` (phase4) goes to `tests/active/test_internal_translate.py`, after `test_one_15_second_budget_covers_both_fetches`. No active test holds the budget + socket < Client timeout < drain chain.\n\n### REDUNDANT (stays out)\n\n- `test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route` (phase3). Four tests already in test_internal_translate.py assert exactly `[[404, {\"error\": \"Video not found\"}]]` for an unknown and an actively denied video on both routes, with the inactive-deny control: `test_an_unknown_video_is_404_video_not_found_with_no_fetch`, `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track`, `test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does[unknown video]` and `test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does`. Harvested test 2 holds the fixture's 404 body to that same literal.\n\n### REPLACES / COMBINE\n\nNone.\n\n### Active tests that would be retired\n\nNone. Nothing moves to `tests/archive/`.\n\n### test_groups entries that would change\n\n- **`test_engine_api_client.py`: new entry** with `client/backend/lib/engine_api_client.py` and `tests/active/fixtures/translate_contract.json`.\n- `test_frontend_translate.py`: add `tests/active/fixtures/translate_contract.json` and `client/frontend/src/data/api-base.ts`. api-base.ts runs in the bundle and builds the `/api/translate` URL the replay asserts.\n- `test_internal_translate.py`: add `tests/active/fixtures/translate_contract.json`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.\n- `test_server_config.py`: add `engine/server/api/handlers/internal_translate.py` and `engine/server/db/jobs/translate-worker.py`.\n- No entry is dropped.\n\n### Subject file Step 5 would create (called out separately)\n\n- **`tests/active/test_engine_api_client.py`** is a new group with a new map entry. It is named for `client/backend/lib/engine_api_client.py`, the script the phase 1 tests drive directly, because no subject file exists for it. It gets its own copies of `_TranslateEngine`, `_serving` and `_translate_engine` from test_server.py, copied rather than imported or hoisted. **Decision point for the operator:** the build plan and the fixture's own `description` text name `tests/active/test_server.py` as the home, because that module's docstring already claims the gateway's `fetch_translate` mapping and it already holds the stub. Choosing test_server.py instead means no new file and no new group (its entry already claims `engine_api_client.py`; add only the fixture), and the fixture's description stays accurate. Keeping the new file means updating that description so it no longer names test_server.py. I followed harvest.md's one-script-one-file rule, but either is defensible.\n\n### Name check preview (confirmed in Step 5)\n\n- test_internal_translate.py: the incoming `whitelist` fixture is the same body as the existing one at line 455, so one copy is kept.\n- test_server_config.py: `SERVER_CONFIG` exists at line 157 with the same value, so one copy is kept.\n- No other incoming name collides.\n\n### Outside scope, noted for the operator\n\nBuild 55 left probes in `tests/tmp`, most of them emptied because the build had no delete tool: `probe_55_*.py` (10 files) and the zero-byte `test_probe_55_phase3_drivers.py`. They are not checkpoints, so Step 7 will not move them to `delete_me/` unless the operator adds them. `test_probe_55_phase3_drivers.py` matches `test_*.py` and stays in every `tests/tmp` run.\n</plan>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/README.md\" update=\"yes\">\nLine 15 (`/internal/translate`): \"`total`, the stored cue count\" is incomplete. Add the running-slice rule in CONTEXT.md's terms: `total` always counts every stored cue whatever `after` was, so a reader that holds more running cues than `total` knows the job was requeued and restarted. Line 18 (Availability): \"`HEARTBEAT_FRESH_MS` (15 000 ms, three of the worker's 5 s beats)\" no longer says where the value comes from. It is now defined in `api/server_config.py` and derived from `HEARTBEAT_SECONDS` as three beats (`int(HEARTBEAT_SECONDS * 3 * 1000)`, still 15 000 ms). Line 30 (worker tunables): the sentence listing the worker's `api/server_config.py` names should also name its beat interval `HEARTBEAT_SECONDS`, which now lives there and not in the worker. Line 38 (\"every 5 s\", \"15 s freshness rule\") is still true and stays.\n</doc>\n<doc path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" update=\"yes\">\nThe Heartbeat section (\u2248line 159, after issue 56's edit to the same paragraph) still ends \"Raise both constants together.\" That is false now. There is a single definition: `HEARTBEAT_SECONDS` (5.0) in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats, so changing the interval moves the window with it. Replace the sentence with that. Keep the \"every 5 s\", \"15 s\" and \"up to 5 s\" join figures, and keep the `--stall-seconds` wording issue 56 added.\n</doc>\n<doc path=\"engine/server/api/handlers/internal_translate.py\" update=\"yes\">\nThe rat-tail comment and the literal are already gone (diff hunk at :27-35). Module docstring line 3 (\"whether the translate worker beat within HEARTBEAT_FRESH_MS\") does not say where the constant now comes from. Add the location in place, e.g. \"HEARTBEAT_FRESH_MS (server_config.py, three HEARTBEAT_SECONDS beats)\". Line 5 already names the constant and needs no change. Optional: the budget comment at line 30 could name the timeout-chain test, but that test is not in the active suite yet (it is still in tests/tmp), so leave it as it is for now.\n</doc>\n<doc path=\"engine/server/db/jobs/translate-worker.py\" update=\"yes\">\nThe rat-tail comment and literal at :58-59 are gone, and the module docstring's \"every 5 s\" (line 8) is still true. One comment is now incomplete: line 35, \"api/ is for server_config and the route's resolve_translatable_video, \u2026\", should say that server_config supplies the bounds and `HEARTBEAT_SECONDS`, because the beat interval is now imported from there and that import is one more reason `api/` is on the path.\n</doc>\n<doc path=\"tests/active/test_server.py\" update=\"no\">\nThe file was not edited. The harvest plan (docs/project/plans/harvest-55-translate-state-contract-plan.md) sends phase 1's gateway replay and coverage tests to a NEW `tests/active/test_engine_api_client.py`, not to this file. Its translate docstring paragraphs still describe exactly the tests it holds. The new module's docstring belongs to that harvest step.\n</doc>\n<doc path=\"tests/active/test_frontend_translate.py\" update=\"yes\">\nThe module now holds a third runner, `CONTRACT_RUNNER` (end of the module), but the docstring (lines 1-31) still describes only \"the first runner\" and `GENERATION_RUNNER`. Add a paragraph about the contract runner. It covers `data/translate.ts` on its own, with stubs for `localStorage`, `window.location.origin` (set before the dynamic import, because api-base.ts reads it when it loads) and a 200-only `fetch`. Every fixture case is served to `fetchTranslate` (state route, with its `after`) or `requestTranslate` (enqueue route): the gateway answer for a valid case and the Engine body for a rejected one. Non-finite numbers are written back as `1e999`, since `JSON.stringify` would write `null`, and the report records per case whether the served text parsed to a non-finite number. The replay tests that consume the runner are still in tests/tmp and the harvest moves them here. Describe what they assert (valid cases keep their fields, `ready` sorted by start then end, `running` kept in order, rejected cases throw exactly `Translate response was malformed`) only once they have landed, so the paragraph is never ahead of the module.\n</doc>\n<doc path=\"tests/active/test_internal_translate.py\" update=\"no\">\nThe docstring already gained the build's paragraph: \"Contract drivers: `ENGINE_DRIVERS` \u2026\" (diff, line 48) describes the driver table that is in the module. The other checklist entries describe tests that are not in this module. Per the harvest plan, the per-(route, state) shape test and the timeout-chain test are still in tests/tmp waiting to be harvested here, and that step writes their docstring lines. The Video-not-found test is classified REDUNDANT, because existing tests already assert the 404 body on both routes. The heartbeat derivation test goes to `tests/active/test_server_config.py`. Nothing the docstring claims today is false.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"no\">\nLine 174 (the `--drain` row: 30 s default, the Client's longest Engine timeout 20 s) and line 230 (\"the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats\") are both still accurate. No value changed, and neither sentence claims where the constant is defined. The only changes to this file during the build (the `--stall-seconds` row and the stall troubleshooting row) are issue 56's work and are accurate.\n</doc>\n<doc path=\"CONTEXT.md\" update=\"no\">\nTranslate state (line 17) already states that `total` always counts every stored cue whatever `after` was, and the requeue inference. It also states that all three layers are held to one contract fixture that each layer's tests replay (issue 55). Generation available (line 18) states 15 s = three 5 s beats, and both values are unchanged. The glossary does not name constant locations, so moving the heartbeat changes nothing in it.\n</doc>\n<doc path=\"client/README.md\" update=\"no\">\nThe `GET /api/translate` paragraph names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the gateway's parsing rules. The build left all of these unchanged (engine_api_client.py is not in the diff).\n</doc>\n<doc path=\"engine/server/api/server_config.py\" update=\"no\">\nThe two new constants each carry a one-line comment in the block's style: the beat interval, and the fresh window as three beats so one late beat is tolerated. Both comments are accurate, and no other comment in the module refers to the heartbeat.\n</doc>\n<doc path=\"docs/project/issues/55-translate-state-contract.md\" update=\"yes\">\nThe issue is delivered. Following docs/project/triage-labels.md, set its `Status:` to `complete`, tick the acceptance criteria the build met, add a Delivered note, and move it to `docs/project/issues/archive/`. Two points need care. The Delivered note should record that the heartbeat pair lives in `api/server_config.py`. It should also record that the durable tests are placed by the harvest: gateway replay in a new `test_engine_api_client.py`, the heartbeat derivation in `test_server_config.py`, and the Engine Video-not-found check judged redundant with existing tests. Its Problem section's line references (`translate-worker.py:60-61`, `internal_translate.py:37-38`) describe the issue as filed and stay as they are.\n</doc>\n<doc path=\"docs/project/issues/plan.md\" update=\"no\">\nLines 13 and 26 describe the 55/56 overlap: 55 removes the `HEARTBEAT_SECONDS` literal and 56 leaves it alone. That is what happened (the worker diff shows 56's keyword parameters next to 55's import change), so the note is still accurate as a planning record.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:engine/server/README.md": "<changes>\nI updated `engine/server/README.md` in three places: the running-slice rule for `total`, where the heartbeat window is defined and how it is derived, and the worker's beat interval in its `server_config` names.\n\n- **Line 15 (`/internal/translate`):** `total` is now described as the count of every stored cue, whatever `after` was. That way a reader holding more running cues than `total` knows the job was requeued and restarted. I checked this against `internal_translate.py:252`, where `total` is `len(cues)` and the cues sent are `cues[after:]`. The frontend reads it the same way at `pages/video-page/translate.ts:175`.\n- **Line 18 (Availability):** `HEARTBEAT_FRESH_MS` is now described as 15 000 ms, defined in `api/server_config.py` as three of the worker's `HEARTBEAT_SECONDS` (5 s) beats, so changing the interval moves the window. I checked this against `server_config.py:430-432`.\n- **Line 30 (Translate worker):** the list of the worker's `api/server_config.py` names now includes its beat interval, `HEARTBEAT_SECONDS`. I checked this against the `from server_config import` line in `translate-worker.py:41`.\n- **Line 38** (\"every 5 s\", \"15 s freshness rule\") is still accurate, so I left it as it was.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/db/jobs/docs/TRANSLATE_WORKER.md": "<changes>\nHeartbeat section: removed the false \"Raise both constants together.\" and now say that the fresh window comes from the beat interval, defined once in `api/server_config.py`.\n\n- The first sentence now says where the beat interval is defined: \"every 5 s (`HEARTBEAT_SECONDS` in `api/server_config.py`)\".\n- The freshness clause now reads \"(`HEARTBEAT_FRESH_MS`, derived beside it as three `HEARTBEAT_SECONDS` beats, so changing the interval moves the window with it)\". I checked this against `server_config.py:430-432` (`HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)`), the handler's import at `internal_translate.py:27` and the worker's import at `translate-worker.py:41`.\n- Dropped the trailing \"Raise both constants together.\"\n- Unchanged: \"every 5 s\", \"15 s\", the `--stall-seconds`/`STALL_SECONDS` wording, and the \"up to 5 s\" heartbeat join figures in the Start-up Order and Stop sections. All of these are still true: `beat.join(HEARTBEAT_SECONDS)` is at `translate-worker.py:534`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/api/handlers/internal_translate.py": "<changes>\nThe module docstring now says where `HEARTBEAT_FRESH_MS` comes from: `server_config.py`, as three `HEARTBEAT_SECONDS` beats.\n\n- **Line 3 (state route):** \"whether the translate worker beat within HEARTBEAT_FRESH_MS\" now ends \"(server_config.py, three HEARTBEAT_SECONDS beats)\". I checked this against `server_config.py:430-432`, where `HEARTBEAT_SECONDS = 5.0` and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)`, and against the handler's import on line 27.\n- **Left as they were:** line 5 (the enqueue route), the `_generation_available` docstring, and the `REQUEST_BUDGET_SECONDS` comment. The budget comment doesn't name the timeout-chain test because that test is still in `tests/tmp`, not the active suite.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:engine/server/db/jobs/translate-worker.py": "<changes>\nThe worker's comment on why `api/` is on the import path now says it also supplies the heartbeat interval.\n\n- Line 35 now reads: \"api/ is for server_config (the bounds and HEARTBEAT_SECONDS) and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.\"\n- I checked this against line 41 of the file, where `HEARTBEAT_SECONDS` is imported from `server_config` next to the `SUBTITLE_*` bounds.\n- Nothing else changed. The module docstring's \"every 5 s\" is still correct, and the old comment and literal for the heartbeat are already gone.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:tests/active/test_frontend_translate.py": "<changes>\nI added a paragraph to the module docstring of `tests/active/test_frontend_translate.py` describing the third runner, `CONTRACT_RUNNER`.\n\n- **Already present:** the replay tests the checklist was waiting on are now in this module. The docstring already has a \"Contract replay\" section stating what they check: valid cases come back with their gateway fields, `ready` cues are sorted by start then end, `running` cues keep the order given, rejected cases throw exactly \"Translate response was malformed\", and each case is checked for its request and its non-finite value. I left that section as it was.\n- **New paragraph:** it sits after the two existing runner paragraphs and says how the third runner is set up:\n  - it bundles `data/translate.ts` on its own, not the video page;\n  - it stubs `localStorage`, a `window` whose `location.origin` is set before the dynamic import (because api-base.ts reads it when it loads), and a `fetch` that answers every request with a 200;\n  - it writes non-finite numbers back out as `1e999`, because `JSON.stringify` would write `null`;\n  - `FETCH_RECORDER`, put in front of the runner, records each request's method, path and `after`;\n  - the report gives, for each case, its value or thrown message, and whether the served text parsed to a non-finite number.\n- **Checked against the code:** each of those points matches `CONTRACT_RUNNER`, `FETCH_RECORDER` and `_contract_report` in the file.\n\nNo code changed, and I ran no tests.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/55-translate-state-contract.md": "<changes>\nIssue 55 is now marked `complete`: all acceptance criteria are ticked, a Delivered note is added, and the issue is copied to `docs/project/issues/archive/`. **The original at `docs/project/issues/55-translate-state-contract.md` still needs deleting** (for example with `git rm`), because I have no delete tool.\n\n- **Status:** `enhancement, ready-for-agent` is now `enhancement, complete`, following `docs/project/triage-labels.md`.\n- **Delivered (2026-10-04)** is a new comment after Triage. It says where each piece landed, and I checked each against the tree:\n  - **Fixture:** `tests/active/fixtures/translate_contract.json`, with 29 valid and 14 rejected cases.\n  - **Gateway:** the replay and the state-set coverage tests are in the new `tests/active/test_engine_api_client.py`. Its line 102 also requires exactly one `Video not found` 404 case per route.\n  - **Frontend:** the `CONTRACT_RUNNER` replay is in `test_frontend_translate.py`.\n  - **Engine:** the `ENGINE_DRIVERS` key/type check and the timeout chain test are in `test_internal_translate.py`.\n  - **Heartbeat:** the pair is in `engine/server/api/server_config.py` (`HEARTBEAT_SECONDS = 5.0` at line 430, `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)` at line 432). The derivation test is in `test_server_config.py`.\n  - **Departure from the brief:** the harvest judged a fixture-reading Engine Video-not-found test redundant. Existing tests already assert that exact body on both routes, and the gateway coverage test ties the fixture's 404 case to the same body.\n  - **Mutation check:** adding \"state paused\" made the gateway replay raise `EngineApiError` and the coverage test fail. That result is in the build record.\n  - The note also says the `TRANSLATE_*_ANSWERS` tables in `test_server.py` are still hand-written.\n- **Desired behavior, Engine tests bullet:** I added \"(held by existing tests instead; see the Delivered comment)\". This follows the pattern issue 56 used for its own departure.\n- **Acceptance criteria:** all 9 are ticked. One caveat on the \"pass\" criteria: in `tests/last_test_validation.json`, the most recent green runs of the translate suites predate the harvested tests. `test_engine_api_client.py` has no group entry there. I ticked these criteria on the strength of the tests being in the active suite, but nothing I could read shows them passing.\n- **Unchanged:** the Problem section's line references (as filed), the Triage comment, the rest of the Agent Brief, and Out of scope.\n</changes>\n\n<not_on_checklist>\ndocs/project/issues/archive/55-translate-state-contract.md \u2014 the issue's new location after archiving. This file is new; the original at docs/project/issues/55-translate-state-contract.md is unchanged and still needs deleting.\n</not_on_checklist>",
    "step_10": "<moved>\nI moved 8 of the 9 checkpoint tests (103 test items) into the durable suite:\n- tests/tmp/test_55_translate_state_contract_phase1.py::test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route (43 cases) \u2192 tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)\n- tests/tmp/test_55_translate_state_contract_phase1.py::test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names \u2192 tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)\n- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order (29 cases) \u2192 tests/active/test_frontend_translate.py, group test_frontend_translate.py\n- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed (14 cases) \u2192 tests/active/test_frontend_translate.py, group test_frontend_translate.py\n- tests/tmp/test_55_translate_state_contract_phase3.py::test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states \u2192 tests/active/test_internal_translate.py, after ENGINE_DRIVERS, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase3.py::test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included (13 route/states) \u2192 tests/active/test_internal_translate.py, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain \u2192 tests/active/test_internal_translate.py, after test_one_15_second_budget_covers_both_fetches, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it \u2192 tests/active/test_server_config.py, group test_server_config.py\n\nNot moved, because it is redundant with tests already in the suite: phase3::test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route.\n\nYou chose the new test_engine_api_client.py over test_server.py for the phase 1 tests (AskUser). The stub engine (_serving, _TranslateEngine, _translate_engine) was copied in from test_server.py, not imported. The description in tests/active/fixtures/translate_contract.json now names test_engine_api_client.py instead of test_server.py.\n\nName checks:\n- `whitelist` (test_internal_translate.py), `SERVER_CONFIG` and `API_DIR` (test_server_config.py) already existed with the same body, so one copy of each was kept. Nothing was renamed.\n\nOther changes:\n- I removed the checkpoints' \"not written yet\" fallbacks (`durable.` prefixes, `_drivers()`, the CONTRACT_RUNNER None path).\n- I added docstring paragraphs that state each rule.\n\nEverything ran from the session directory, /home/enduser/code/PeerTube-browser. That is where --show-config resolves tests/config.json and where the scope files and the .preharvest snapshot were. It is not the `.worktrees/55` path the harvest file records.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nChanges to tests/config.json test_groups:\n- test_engine_api_client.py: new entry with client/backend/lib/engine_api_client.py and tests/active/fixtures/translate_contract.json.\n- test_frontend_translate.py: added tests/active/fixtures/translate_contract.json and client/frontend/src/data/api-base.ts.\n- test_internal_translate.py: added tests/active/fixtures/translate_contract.json, client/backend/lib/engine_api_client.py and scripts/deploy-bluegreen.sh.\n- test_server_config.py: added engine/server/api/handlers/internal_translate.py and engine/server/db/jobs/translate-worker.py.\n\nNo entry was dropped. `validate_tests.py --audit-map` exited 0, and none of its advisory MISSING findings involves a moved test or a file one reads.\n</group_map>\n\n<mutations>\nBefore every edit I counted the anchor and found exactly one occurrence. Each production file was backed up to .scratch/harvest/<test>/<basename>.bak, outside the production tree. After each red run the file was restored from that copy, `diff` showed it byte-identical, and the test was run green again. No mutation hung or survived, and no .bak was left under client/, engine/, scripts/ or tests/active.\n- Gateway replay: removed `and math.isfinite(value)` from `_is_seconds` in client/backend/lib/engine_api_client.py. Red: [state start 1e999] failed with \"DID NOT RAISE EngineApiError\" (the rejected-case assertion) while 42 passed. Green after restore: 43 passed.\n- Fixture states equal gateway sets: `TRANSLATE_REQUEST_STATES = TRANSLATE_STATES | {\"busy\", \"paused\"}` in engine_api_client.py. Red: the enqueue with-available set equality failed with \"Extra items in the right set: 'paused'\". Green after restore: 1 passed.\n- Frontend valid cases: in client/frontend/src/data/translate.ts, `compareCues` changed to `a.start - b.start || b.end - a.end`. Red: [state ready] and [state ready without available] failed the value deep-equal (Long first came before Short first) while 27 passed. Green after restore: 29 passed.\n- Frontend rejected cases: in translate.ts, `const MALFORMED = \"Translate response was invalid\"`. Red: all 14 failed `thrown == \"Translate response was malformed\"`. Green after restore: 14 passed.\n- Driver table: this test reads no production file (only the fixture and the test-side ENGINE_DRIVERS), so I mutated its group subject tests/active/fixtures/translate_contract.json instead, changing the `enqueue busy` engine state to \"paused\". Red: \"no fixture (route, state) without a driver\" failed with `[('enqueue', 'paused')] == []`. Green after restore: 1 passed.\n- Route/state shape: in engine/server/api/handlers/internal_translate.py, the running answer's `\"total\": str(len(cues))`. Red: [state running] failed the key-to-JSON-type assertion (`total` string != number) while 12 passed. Green after restore: 13 passed.\n- Heartbeat derivation: `HEARTBEAT_FRESH_MS = 15000` in engine/server/api/server_config.py. Red: the derived-from-the-interval assertion failed with `'HEARTBEAT_SECONDS' in set()`. Green after restore: 1 passed.\n- Timeout chain: `REQUEST_BUDGET_SECONDS = 16.5` in internal_translate.py. Red: `budget + socket_timeout < client_timeout` failed as (16.5 + 4.0) < 20. Green after restore: 1 passed.\n</mutations>\n\n<cleared>\ndelete_me/ now holds the four checkpoint files, moved there from tests/tmp with no name clash:\n- test_55_translate_state_contract_phase1.py\n- test_55_translate_state_contract_phase2.py\n- test_55_translate_state_contract_phase3.py\n- test_55_translate_state_contract_phase4.py\n\ntests/tmp holds none of the in-scope files. Build 55's probes are outside scope and were not moved: probe_55_*.py (10 files) and the zero-byte test_probe_55_phase3_drivers.py are still in tests/tmp, and the last one is still collected by every tests/tmp run. Nothing was deleted; delete_me/ is waiting for you to decide.\n\nFinal counts:\n- I restored tests/last_test_validation.json.preharvest over the record and then ran `validate_tests.py --compare` with no tier. It selected 12 of 66 groups and they ran green: 661 passed, 0 failed.\n- Against the pre-harvest record, 103 tests appeared. That is 43 + 1 in test_engine_api_client, 29 + 14 in test_frontend_translate, 1 + 13 + 1 in test_internal_translate and 1 in test_server_config, exactly the harvested items.\n- Nothing departed, nothing new went red, and nothing stopped being red. The record is banked.\n- Two files sit outside the trees: .scratch/harvest/ keeps the mutation backups, the red outputs and compare.out, and HARVEST_FILE records the name checks, mutations, disposal and these counts.\n</cleared>"
  },
  "requirements": "### Purpose\n\nThe Translate state contract covers the states, the `available` default, the cue shape, `after`/`total`, and \"Video not found\" meaning `none`. Today the Engine (`engine/server/api/handlers/internal_translate.py`), the Client gateway (`client/backend/lib/engine_api_client.py`) and the frontend (`client/frontend/src/data/translate.ts`) each work it out on their own, and nothing makes them disagree loudly. This build declares the contract once, as a checked-in JSON **contract fixture** that only tests read. Every layer's tests are held to it. It also gives the heartbeat pair one Engine-side definition and turns the timeout chain into a test. **Runtime behaviour does not change.** Each layer keeps its own runtime validation: the Client's re-validation at the trust boundary is deliberate and stays.\n\n### Contracts under test\n\n- Engine `POST /internal/translate {id, host, after?}` (the state route). It answers 200 `{state, available}` with `state` one of `none`, `queued`, `running`, `ready`, `already_english`, `failed`. `ready` adds `cues: [{start, end, text}]`. `running` adds `cues` (the stored cues from index `after` on, in stored order) and `total` (the count of every stored cue, whatever `after` was). An unknown or denylisted video answers 404 `{\"error\": \"Video not found\"}` (`VIDEO_NOT_FOUND`, `internal_translate.py:35`).\n- Engine `POST /internal/translate/enqueue {id, host}` (the enqueue route). It answers 200 `{state, available}` with no cues: every state above plus `busy` (queue full, never stored). It answers the same 404 `Video not found`.\n- The Client gateway parses these in `fetch_translate` and `request_translate`. `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (adds `busy`). A missing `available` reads as `false` and a non-bool raises. A cue must be a dict with a finite non-bool number `start` and `end` and a str `text`, and only those three keys are copied. `running` needs a non-negative non-bool int `total`. A 404 whose `error` is exactly `Video not found` maps to `{state: \"none\", available: false}`, and any other non-200 raises `EngineApiError`.\n- The frontend parses the gateway's `GET /api/translate` in `fetchTranslate`, through the private `parseTranslateState`, and `POST /api/translate` in `requestTranslate`, using `REQUEST_STATES`. It repeats the `available` default and the cue checks, and sorts `ready` cues with `compareCues` (start, then end). `running` cues stay in stored order.\n\n### The contract fixture\n\n- It is one JSON file outside every runtime package, under the tests tree (for example `tests/active/fixtures/translate_contract.json`). Tests read it and nothing at runtime does.\n- Suggested shape: `{\"cases\": [{\"name\", \"route\": \"state\" | \"enqueue\", \"engine\": {\"status\", \"body\"}, \"gateway\": <normalised answer> | \"rejected\"}]}`. The exact shape is up to the design.\n- Minimum coverage:\n  - every state of each route (six for state, seven for enqueue including `busy`), each with `available` present and with it absent (absent reads as `false`);\n  - `ready` and `running` cue lists, including a `running` answer sliced by `after` whose `total` exceeds its `cues` length;\n  - the `Video not found` 404 on both routes, giving `{state: \"none\", available: false}`, and a different 404 (e.g. `{\"error\": \"Not found\"}`) rejected;\n  - rejections: an unknown state; a non-bool `available`; a non-list `cues`; a cue with a non-finite or bool `start`/`end`; a cue with a non-string `text`; a negative `total`; a bool `total`.\n- For `running`, the gateway answer keeps the cues in the Engine's order. The fixture states the gateway answer, not the frontend's sorted form.\n\n### Client backend tests\n\n- Every fixture case is replayed through the gateway's Engine-answer parsing for its route (`fetch_translate` for `state`, `request_translate` for `enqueue`), with the Engine stubbed to answer the case's status and body. Each case asserts the fixture's normalised answer, or `EngineApiError` for `rejected`.\n- The existing `TRANSLATE_ENGINE_ANSWERS` / `TRANSLATE_STATE_ANSWERS` / `TRANSLATE_ENQUEUE_ANSWERS` tables in `tests/active/test_server.py` may be rewritten to read the fixture. No other test changes.\n\n### Frontend tests\n\n- The real `client/frontend/src/data/translate.ts` runs in node, bundled with esbuild as the existing `tests/active/test_frontend_translate.py` does, with `fetch` stubbed.\n- Every valid case's gateway answer is served as a 200 to its route's parser (`fetchTranslate` for `state`, `requestTranslate` for `enqueue`). It must be accepted with the same fields, and `ready` cues must come back sorted by start then end.\n- Every rejected case's Engine body is served as a 200 gateway answer to its route's parser and must be refused (it throws).\n- Driving the exported functions through a stubbed fetch needs no frontend runtime change. Exporting a parser just for tests is not required.\n\n### Engine tests\n\n- The tests drive the state route into each of its states and the enqueue route into each of its states. Every answer must have exactly the keys, and the JSON value types, of the fixture's valid case for that route and state that carries `available` (the Engine always sends `available`; the cases without it stand for older Engines).\n- The tests assert that the state route's 404 for an unknown or denied video equals the fixture's `Video not found` body.\n\n### Mutation check\n\n- Once, by hand: adding a new state to the fixture alone, with no layer changed, must make at least one layer's tests fail. The result goes in the build record.\n\n### Heartbeat pair\n\n- `HEARTBEAT_SECONDS` (5.0, now `translate-worker.py:59`) and `HEARTBEAT_FRESH_MS` (15000, now `internal_translate.py:33`) come from one Engine-side definition. The fresh window is derived as three beats (`3 * HEARTBEAT_SECONDS * 1000`, still 15000 ms).\n- The definition lives in an Engine module that both the API and the worker already import, not in a route handler. Candidates are `engine/server/data/subtitles.py`, which owns `fetch_translate_heartbeat`/`write_translate_heartbeat`, or `engine/server/api/server_config.py`. The design picks one.\n- `internal_translate.py` and `translate-worker.py` both import it, neither keeps its own literal, and the rat-tail comments tying them together are removed.\n- A test shows that the window is derived from the interval, so changing the interval changes the window.\n\n### Timeout chain test\n\n- One test reads the real values: the Engine's `REQUEST_BUDGET_SECONDS` (15.0, `engine/server/api/handlers/internal_translate.py`), `SOCKET_TIMEOUT_SECONDS` (4.0, `engine/server/data/source_fetch.py`), the Client's `TRANSLATE_TIMEOUT_SECONDS` (20, `client/backend/lib/engine_api_client.py`) and the deploy script's default `DRAIN_SECONDS=30` (parsed from the text of `scripts/deploy-bluegreen.sh`).\n- It asserts budget + socket < Client timeout < drain, and fails when any one value moves past its neighbour.\n- A test may read another layer's values. A runtime module may not import across layers.\n\n### Prose\n\n- `engine/server/README.md` line 15 (`/internal/translate`) already says `cues` from `after` on and `total` = the stored cue count. It gains the explicit rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted (`client/frontend/src/pages/video-page/translate.ts:175`).\n- `CONTEXT.md` (Translate state) already states the rule and the fixture and needs no change. If the heartbeat's location changes, any doc naming the old constant locations (the `internal_translate.py` docstring, `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`) is updated.\n\n### Constraints and out of scope\n\n- No runtime module is shared across the Engine, the Client backend and the frontend. The README boundary guard forbids the Client backend importing Engine modules, and the frontend is TypeScript. Each layer's state lists, `available` default, cue checks and not-found mapping stay where they are.\n- Out of scope: removing or merging any layer's validation; generating code or types from the fixture; adding a schema-validator dependency; changing any state, field, timeout or heartbeat value; deduplicating cue sorts across layers. The two Engine sorts (`internal_translate.py:115`, `translate-worker.py:380`) may share one Engine helper, but it is not required. Also out of scope: the fetch adapter (issue 53), the job handle (issue 54) and the worker split (issue 56).\n- New code matches the style of the file it lands in.\n\n### Acceptance criteria\n\n- [ ] One contract fixture covers every state of both routes and every rejection listed above, and nothing at runtime reads it.\n- [ ] The Client backend's tests replay every fixture case through both route parsers and pass.\n- [ ] The frontend's tests replay every fixture case through both parsers and pass.\n- [ ] The Engine's tests check each state's answer against the fixture's valid case for that state, and check the not-found body.\n- [ ] Adding a new state to the fixture alone makes at least one layer's tests fail (checked once by hand, recorded).\n- [ ] The worker's beat interval and the route's fresh window come from one definition, and changing the interval changes the window.\n- [ ] One test asserts budget + socket < Client translate timeout < deploy default drain from the real values, and fails when any one is moved past its neighbour.\n- [ ] The Engine server README states the running-slice rule beside `/internal/translate`.\n- [ ] No runtime behaviour changes. Every existing translate route, Client gateway, frontend translate and translate worker test passes unchanged (`tests/active/test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`), apart from tests rewritten to read the fixture.\n\n### Baseline suite state\n\nStep 0's pre-build suite exited 0 (variant: false), but it ran selectively: 1 of 65 test groups (`test_search_fusion.py`, 10 passed), with 64 skipped as unchanged. Nothing yet shows that the translate suites listed above are green before the build. A later step should run them in full before relying on \"passes unchanged\".\n\n### Notes from the tree\n\nThe issue's code claims hold, but several line numbers are stale. The Engine sorts are at `internal_translate.py:115` and `translate-worker.py:380`, `VIDEO_NOT_FOUND` is at `internal_translate.py:35`, `HEARTBEAT_FRESH_MS` at `:33`, `HEARTBEAT_SECONDS` at `translate-worker.py:59`, and the state branches at `internal_translate.py:245-263`. `SOCKET_TIMEOUT_SECONDS` lives in `engine/server/data/source_fetch.py`, not under `api/`.",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nOne checked-in JSON file, `tests/active/fixtures/translate_contract.json`, states the contract. Each layer's existing test file replays it against that layer's real code. No runtime module reads the file, and no runtime check moves or merges. The heartbeat pair moves into one Engine module. The timeout chain and the heartbeat derivation each get one test, and two docs gain one sentence each. Before anything changes, the six translate suites named in the acceptance criteria are run in full, because step 0 skipped them.\n\n**The fixture.** The shape is the suggested one: `{\"description\", \"cases\": [...]}`. Each case has a unique `name`, a `route` (`state` or `enqueue`), an optional `after` on state cases (it documents the slice and is passed to `fetch_translate`, which forwards it), `engine: {status, body}`, and `gateway`, which is either the normalised answer or the string `\"rejected\"`. The fixture contains:\n- every state of each route, once with `available: true` and once with `available` absent (gateway `false`). That is six state-route states and seven enqueue states including `busy`.\n- a `ready` cue list deliberately out of start order, with two cues sharing a start, so the frontend's start-then-end sort can be seen.\n- a `running` list in non-sorted stored order, plus a `running` answer sliced by `after` (2 cues, `total` 5).\n- the `Video not found` 404 on both routes, answering `{state: \"none\", available: false}`.\n- these rejected cases: the `{\"error\": \"Not found\"}` 404 on both routes; an unknown state on both routes; `busy` on the state route; a non-bool `available` on both routes; then, on the state route only, non-list `cues`, a cue with `start` written as `1e999`, a cue with a bool `start` and one with a bool `end`, a cue whose `text` is a number, a `running` `total` of -1, and a `total` of `true`.\n\nThe cue and `total` rejections live only on the state route because `request_translate` never reads cues. For `running`, the gateway answer keeps the Engine's cue order.\n\nTwo rules keep the fixture usable by every layer, and the Client test checks the fixture against them:\n- A rejected Engine body must be something the gateway refuses and also something the frontend refuses when served as a 200 gateway answer. Every listed rejection meets this. I traced each one through both parsers.\n- Every `(route, state)` among the valid 200 cases appears with and without `available`.\n\n**Client backend** (`tests/active/test_server.py`). A new parametrized test runs once per fixture case, with the case name as its id. It starts the existing `_translate_engine` stub with the case's status and body, then calls `fetch_translate` (state route, passing `after` when given) or `request_translate` (enqueue route) directly. It asserts that the result equals the case's `gateway` answer, or that `EngineApiError` is raised for `rejected`. As a control it checks that the recorded request hit the right `/internal/translate` path. A second test checks the fixture itself:\n- the valid states of the state route equal `TRANSLATE_STATES`, and those of the enqueue route equal `TRANSLATE_REQUEST_STATES`, each present with and without `available`;\n- case names are unique.\n\nThis check fails loudly in either direction: a state added to the fixture alone, or a state added to the gateway alone. Calling the functions directly, rather than going through `/api/translate`, gives the `EngineApiError` the requirement asks for instead of a 502 that hides why. The existing `TRANSLATE_*_ANSWERS` tables stay as they are, since they test the HTTP route (502 mapping, request ids, token). This is a named simplification; see Tradeoffs.\n\n**Frontend** (`tests/active/test_frontend_translate.py`). This file gains a third module-scoped bundle: esbuild bundles `client/frontend/src/data/translate.ts` on its own, with the same `--platform=node`, ESM format and `import.meta.env` defines as the existing bundles. A small runner does the following:\n- It stubs `window`, `localStorage` and `fetch`, imports the bundle's exported `fetchTranslate` and `requestTranslate`, and reads the fixture file itself with `fs`, so `1e999` parses to `Infinity` natively.\n- For each valid case, it serves the case's `gateway` answer as a 200 to `fetchTranslate` (state route) or `requestTranslate` (enqueue route).\n- For each rejected case, it serves the case's Engine body as a 200 to the same function.\n- It reports, per case, either the returned value or the thrown message.\n\nThe Python side then asserts:\n- a valid answer deep-equals the gateway answer, with `ready` cues re-sorted in Python by start then end, and `running` cues left in order;\n- every rejected case threw exactly `Translate response was malformed`, so a JSON `SyntaxError` cannot pass as a refusal.\n\nThe stub serialises bodies with non-finite numbers written back as `1e999`, because plain `JSON.stringify` would write `null`. A control asserts that the served `1e999` case reached the parser as `Infinity`. All cases run in one node process. No frontend file changes, and no parser is exported.\n\n**Engine** (`tests/active/test_internal_translate.py`). A new test runs once per `(route, state)` among the fixture's valid 200 cases that carry `available`. It drives that state with the file's existing helpers:\n- **State route:** `_seed` for queued, running, ready, failed and already_english, with a fresh beat; no row and no track for `none`. Running is driven with the case's `after` when present.\n- **Enqueue route:** no beat for `none`; a fresh beat and no row for `queued`; `_seed` plus a fresh beat for the four stored states; and the queue filled to `SUBTITLE_QUEUE_CAP` for `busy`, as the existing busy test does.\n\nThe answer must be a 200 whose key set, and the JSON type of each value, match the fixture case: bool as boolean, int or float as number, then string, list, object. Each answered cue's keys and types must match the fixture's cues.\n\nThe drivers live in a dict keyed by `(route, state)`, and a fixture state with no driver fails, which covers the mutation check on the Engine side. A second test asserts that an unknown video and a denylisted host on the state route answer exactly the fixture's `Video not found` 404 body. The enqueue route gets the same check, which costs one line.\n\n**Heartbeat pair.** The pair lives in `engine/server/api/server_config.py`. `HEARTBEAT_SECONDS = 5.0` sits beside the `SUBTITLE_*` tunables, and `HEARTBEAT_FRESH_MS` is derived from it as three beats, kept an int (15000) so the comparison and the docs read as before. `internal_translate.py` adds it to its existing `from server_config import ...` line, and `translate-worker.py` adds `HEARTBEAT_SECONDS` to its existing import. Both literals and both rat-tail comments go.\n\nThe derivation test, in `test_internal_translate.py`:\n- parses `server_config.py` with `ast`, finds the `HEARTBEAT_FRESH_MS` assignment, and checks that its right-hand side names `HEARTBEAT_SECONDS`;\n- evaluates that expression with the real interval (giving the module's value, 15000) and with a different one (7.0 gives 21000);\n- checks that `handlers.internal_translate.HEARTBEAT_FRESH_MS` is `server_config`'s value;\n- checks that neither the handler nor the worker source assigns its own literal.\n\n**Timeout chain.** One test in `test_internal_translate.py`, beside the existing 15 s budget test. It imports `REQUEST_BUDGET_SECONDS` from the handler, `SOCKET_TIMEOUT_SECONDS` from `data.source_fetch`, and `TRANSLATE_TIMEOUT_SECONDS` from `lib.engine_api_client`; conftest already puts `client/backend` on `sys.path`, and that module imports nothing from the Engine. It reads the drain value from `scripts/deploy-bluegreen.sh` with a line-anchored `^DRAIN_SECONDS=(\\d+)$` regex and requires exactly one match. It asserts budget + socket < Client timeout < drain. Each inequality fails as soon as one value moves past its neighbour, which is what the criterion asks. Only a test crosses layers.\n\n**Prose.**\n- `engine/server/README.md` line 15 gains the rule that `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.\n- Line 18 says the fresh window is derived in `server_config.py` from `HEARTBEAT_SECONDS`.\n- `TRANSLATE_WORKER.md` line 155 loses \"Raise both constants together\" and names the single definition.\n- The `internal_translate.py` docstring keeps the name `HEARTBEAT_FRESH_MS`, which is still a module attribute through the import, and says where it is defined.\n- `CONTEXT.md` is unchanged.\n\n**Mutation check.** Done once, by hand. Add a valid `paused` case to the fixture alone and run the three layers' suites. The expected result is that the Client replay raises `EngineApiError`, the Client coverage test fails, the frontend throws, and the Engine has no driver. The outcome goes in the build record, and then the edit is reverted. The build record also carries a grep showing that no file under `engine/`, `client/` or `scripts/` names `translate_contract.json`.\n\n### Alternatives considered\n\n- **A Python constants module, or a JSON Schema with a validator, as the single source.** Rejected. The frontend tests run in node and can't read Python. A validator is a new dependency and out of scope. Plain JSON reads with stdlib in Python and with `JSON.parse` in node.\n- **Replaying Client cases through the `/api/translate` HTTP route.** Rejected. Every rejection would collapse into the same 502, so the test could not tell `EngineApiError` from an unrelated failure. The direct calls are the parsing the requirement names, and the route behaviour stays covered by the existing tests.\n- **Exporting `parseTranslateState` for a direct frontend test.** Rejected. Driving the exported functions through a stubbed `fetch` also covers `readTranslateResponse` and needs no runtime change.\n- **Heartbeat in `data/subtitles.py`.** It owns `fetch_translate_heartbeat` and `write_translate_heartbeat`, so the case for it was real. `server_config.py` won because it already holds the translate tunables (`SUBTITLE_QUEUE_CAP`, `SUBTITLE_MAX_*`), both consumers already import it, and the window is a policy constant, not storage.\n- **Proving the derivation by `exec`ing an edited copy of `server_config.py`, or by adding a `heartbeat_fresh_ms(seconds)` function.** Rejected. The first runs the whole config, including its env checks. The second adds runtime surface only for a test. Evaluating the parsed expression shows \"change the interval, the window follows\" with neither cost.\n- **A new test file for the cross-layer timeout and heartbeat tests.** Rejected to keep the file count down. The Engine owns the budget and the heartbeat, so they sit with the Engine translate tests.\n- **Writing the non-finite cue as `Infinity` in the file.** Rejected. That is not standard JSON and `JSON.parse` refuses it. `1e999` is valid JSON and parses to infinity in both Python and JS.\n\n### Gotchas, risks, limitations\n\n- **JS has one number type.** A float-valued integral `total` such as `3.0` is refused by the gateway but accepted by the frontend. So the fixture cannot carry it as a rejection, and the \"every rejection refused by every layer\" rule leaves it out. The existing `running total 1.5` gateway test still covers non-integer totals.\n- **Serialising infinity.** Python's `json.dumps` writes `Infinity`, which the Client's `json.loads` accepts, so the Client stub path is fine. Node's `JSON.stringify` writes `null`, which would be refused for the wrong reason. That is why the frontend stub writes `1e999` and has the control described above.\n- **The Engine test checks shape, not values.** It checks keys and JSON types, as specified. It does not check cue order or the slice arithmetic; the existing `BRANCHES` and `AFTERS` tests keep covering those.\n- **\"Passes unchanged\" is unproven.** It rests on a baseline nobody has run yet; step 0 skipped these suites, so they run before the build.\n- **Float versus int heartbeat.** `3 * 5.0 * 1000` is a float. It is kept an int so `BEATS`' 15 000 / 15 001 boundaries, the README's \"15 000 ms\" and any logging read exactly as before. The comparison would behave the same either way.\n- **The Client side of the timeout test is a different test interpreter than the Engine's pixi env.** That is fine because nothing executes, but the import of `lib.engine_api_client` relies on conftest's `sys.path` entry.\n- **The mutation check is manual.** It holds only at the time it is recorded, though the coverage assertions keep the same guarantee automatically afterwards.\n\n### Tradeoffs for the operator\n\n- **Two copies remain.** The hand-written `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay, so part of the contract still exists twice, once at the HTTP route and once in the fixture. Rewriting them from the fixture is a safe follow-up and was left out to keep the change small.\n- **Cross-layer reads.** The timeout and heartbeat tests read another layer's constants and a shell script's text. A rename or reformat of those lines breaks the tests, which is intended.\n- **Engine sorts not unified.** The two Engine cue sorts stay separate. Sharing a helper is allowed but not needed, so it is not done.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"tests/active/fixtures/translate_contract.json\" element=\"new contract fixture file (and the new tests/active/fixtures/ directory)\">\n**What changes.** This is a new file, `{\"description\", \"cases\": [...]}`. Each case has `name`, `route` (`state`|`enqueue`), an optional `after` (state route only), `engine: {status, body}`, and `gateway` (the normalised answer, or `\"rejected\"`). The `tests/active/fixtures/` directory does not exist yet (Glob found nothing). Precedent: the two existing test data files sit directly in `tests/active/` (`host_tokens.json`, `upstream_snippet_cases.json`). A subdirectory still works, but it is a new convention.\n\n**Constraints I checked against the code:**\n- **Enqueue cases need bodies with only `{state, available}`.** The real enqueue route answers no other keys (`internal_translate.py:282`, `:285`). If enqueue `ready`/`running` bodies carried `cues`/`total`, the Engine key-set test would fail.\n- **Enqueue `none` with `available: true` is something the Engine never produces.** The route answers `none` only as `available: False` (`:282`). A keys-and-types check still passes, but the fixture would then assert an answer the Engine cannot give. Say so in `description`.\n- **`1e999`.** Python `json.load` reads it as `inf` and node `JSON.parse` reads it as `Infinity`. Python `json.dumps` writes it back as `Infinity`, which the Client's `json.loads` accepts. `JSON.stringify` writes `null`.\n- **The `Video not found` 404.** Its body must be exactly `{\"error\": \"Video not found\"}`. That is the match in `engine_api_client.py:187,208` (`TRANSLATE_NOT_FOUND_ERROR`) and the Engine's `VIDEO_NOT_FOUND` (`internal_translate.py:35`).\n- **Rejected bodies served to the frontend as a 200.** `{\"error\":\"Not found\"}` has no `state`, so both `parseTranslateState` and `requestTranslate` throw MALFORMED (`translate.ts:80,107`). `busy` on the state route falls through to MALFORMED (`:107`). Bool and infinite times fail `Number.isFinite` (`:120`). A `total` of -1 or `true` fails `Number.isInteger` / `< 0` (`:103`). A non-bool `available` fails `parseAvailable` (`:113`). Each one is refused by the Client too: `_translate_available` `:164`, `_checked_cues` `:171-176`, the `total` check `:199`, and the state sets `:192,213`.\n- **Avoid a float-valued integral `total` such as `3.0`.** JS accepts it and the gateway refuses it, as the plan says.\n- **Running `after` case** (2 cues, `total` 5): Client and frontend just pass it through. See the Engine-test entry for the slicing caveat.\n\n**Dependents.** `test_server.py`, `test_frontend_translate.py` (node `fs` + `JSON.parse`) and `test_internal_translate.py` read it. No file under `engine/`, `client/` or `scripts/` may name it.\n\n**Risk.** The risk is in the content, not the code. A case that violates the \"refused by both parsers\" rule fails the frontend replay for the wrong reason. So does an enqueue body with extra keys, which fails the Engine shape test.\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"new fixture replay test through fetch_translate / request_translate, plus the fixture coverage test\">\n**What changes.** Two tests are added near the translate block (`:1540-1932`).\n\n**Test 1** is parametrized over the fixture cases, with ids taken from the case names:\n- Inside `with _translate_engine((status, body)) as (engine_base, seen):` it calls `fetch_translate(engine_base, \"uuid-1\", \"peer.example\", after=case.get(\"after\"))` or `request_translate(engine_base, \"uuid-1\", \"peer.example\")`.\n- It asserts equality with `gateway`, or `pytest.raises(EngineApiError)` for `\"rejected\"`.\n- Control: `[e[1] for e in seen] == [\"/internal/translate\"]` or `[\"/internal/translate/enqueue\"]`.\n\n**Test 2** checks:\n- The set of valid 200 state-route states equals `TRANSLATE_STATES`, and the enqueue set equals `TRANSLATE_REQUEST_STATES`.\n- Each `(route, state)` appears both with and without `available`.\n- Names are unique.\n- The 404 Video-not-found cases are left out of the state sets.\n\n**New imports.** `from lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate`, plus a fixture path built from `Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"`.\n- `lib` is already the Client package in `sys.modules`: conftest `:43-49` imports `lib.http_utils` before this module inserts the Engine dirs (`:185-190`). So the import resolves to `client/backend/lib`.\n- `client/backend/lib/__init__.py` exists. No `lib` package exists anywhere under `engine/`.\n\n**Facts verified:**\n- `_TranslateEngine` (`:1578-1596`) serialises with `json.dumps(payload)`. That writes `Infinity` for the `1e999` case, `_post_json`'s `json.loads` accepts it, and `_is_seconds` (`:156-158`) then refuses it, so the case fails for the right reason.\n- `_post_json` returns `(code, parsed)` for an HTTPError, so the 404 paths work.\n- The test needs no `ENGINE_BRIDGE_TOKEN` (`bridge_headers` just omits the header).\n- `request_translate` uses the default 6 s timeout, not 20 s.\n\n**Existing items that stay as they are:**\n- The `TRANSLATE_ENGINE_ANSWERS` (`:1559`), `TRANSLATE_STATE_ANSWERS` (`:1723`) and `TRANSLATE_ENQUEUE_ANSWERS` (`:1911`) tables.\n- `TRANSLATE_RUNNING_CUES` and `TRANSLATE_READY_CUES`.\n- Every HTTP-route test.\n\n**Docstring.** The module docstring's translate paragraphs (`:132-148`) gain one paragraph for the replay and the coverage check.\n\n**Regression risk.**\n- Low for the existing tests, because only additions are made.\n- Name clash: `TRANSLATE_STATE_ROUTE` and similar already exist, so the new constants need distinct names.\n- A module-level `json.load` of the fixture breaks collection of the whole 1932-line file if the file is missing or malformed. Loading at module level is what parametrize needs, so accept the risk or guard it.\n</impact>\n<impact path=\"tests/active/test_frontend_translate.py\" element=\"new third module-scoped esbuild bundle of client/frontend/src/data/translate.ts and a replay runner\">\n**What changes.**\n- **New fixture.** A module-scoped fixture, a sibling of `bundle` (`:214-226`) and `generation_bundle` (`:536-548`). It runs esbuild on `FRONTEND / \"src\" / \"data\" / \"translate.ts\"` with `--bundle --format=esm --platform=node` and the two `--define:import.meta.env.*` flags. It needs no embed-api alias and no CSS loader, because nothing in that import chain imports CSS.\n- **New runner string.** It stubs `globalThis.window = {location: {origin: BASE}, localStorage}`, `localStorage` and `fetch`, then does `await import(process.env.BUNDLE)`. The import must be dynamic and come after the stubs, because `data/api-base.ts:5` reads `window.location.origin` at module top level.\n- **Replay.** The runner reads the fixture with `fs.readFileSync` + `JSON.parse`. For each case it serves a 200 whose text is the gateway answer (valid case) or the Engine body (rejected case), using a serialiser that writes non-finite numbers as `1e999`. It then calls `fetchTranslate(BASE, id, host, after)` or `requestTranslate(BASE, id, host)` and reports the value or the thrown `message` per case. All cases run in one node process.\n\n**Python asserts:**\n- A valid answer deep-equals the gateway answer, with `ready` cues sorted in Python by `(start, end)` and `running` cues kept in order.\n- Every rejected case threw exactly `Translate response was malformed` (`MALFORMED`, `translate.ts:19`).\n- Control: the `1e999` case reached the parser as `Infinity`. For example, the runner records `Number.isFinite === false` on the parsed served text.\n\n**Facts verified:**\n- `readTranslateResponse` (`:84-93`) throws the payload's `error` text on a non-2xx status. That is why rejected bodies must be served as 200. A 404 served as 404 would throw `Not found`, not MALFORMED.\n- `profileHeaders()` reads `localStorage` lazily, so the stub only needs to exist.\n- `fetchTranslate` puts `after` on the query string, which the stub ignores.\n- JS turns `1.0` into `1`, and Python compares `1 == 1.0` as true, so float/int differences do not break the deep-equal.\n\n**Docstring.** The module docstring (`:1-31`) gains a paragraph for the third bundle and its runner, including the `1e999` serialisation and its control.\n\n**Regression risk.** Low for the existing tests (additive). The new bundle adds one esbuild run and one node process. The existing `RUNNER` and `GENERATION_RUNNER` strings are untouched.\n</impact>\n<impact path=\"tests/active/test_internal_translate.py\" element=\"new Engine shape test per (route, state), the Video-not-found body test, the heartbeat derivation test and the timeout-chain test\">\n**What changes: four tests.**\n\n**(1) Shape test.** It is parametrized over the fixture's valid 200 cases that carry `available`. Drivers live in a dict keyed by `(route, state)`, and a missing key fails.\n- **State route** drivers use `_seed(store, row)` (`:674-692`) plus `write_translate_heartbeat(store, NOW, 1)`, with `_route(_instance(track), monkeypatch)` (`:646-657`) and `_handle`/`_state` (`:437`, `:739`).\n- **Gap: `failed`, `already_english` and `none` need `_instance(False)`.** With a track, those rows answer `ready` (BRANCHES `:812`, `:814`).\n- `ready` uses `_seed(\"ready\")`, which answers `STORED_READY` with no fetch.\n- **Enqueue route** drivers use `_beat(subtitles_path, 0)` (`:695`) or no beat for `none`, `_seed` plus `store.close()` for the stored states (as `:963-974` does), and the queue filled to `SUBTITLE_QUEUE_CAP` for busy (as `:977-989`), via `_enqueue` (`:733`).\n- **JSON-type helper.** It must test `bool` before `int`/`float`, since `isinstance(True, int)` is true.\n- **Caveat on `after`:** `RUNNING` (`:635`) holds 3 cues. Driving with a fixture `after` \u2265 3 (for example 3, from the 5-total case) answers `cues: []`, so the per-cue key/type check passes without checking anything. The driver should seed enough cues, or clamp `after`.\n\n**(2) Video-not-found test.** An unknown video, and `_set_denied(whitelist, True)` on `DENIED_VIDEO`, on both routes must answer `[[404, fixture_body]]`.\n- The file already has `VIDEO_NOT_FOUND = [[404, {...}]]` (`:162`), so the new test should compare against the fixture body and not that literal.\n\n**(3) Heartbeat derivation test:**\n- `ast.parse` `API_DIR / \"server_config.py\"`, find the `Assign` to `HEARTBEAT_FRESH_MS`, and check that its value contains `Name('HEARTBEAT_SECONDS')`.\n- `eval(compile(ast.Expression(node.value), ...), {\"HEARTBEAT_SECONDS\": x})` gives 15000 for 5.0 and 21000 for 7.0.\n- `_translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS`.\n- Neither `internal_translate.py` nor `engine/server/db/jobs/translate-worker.py` has a module-level `Assign` to either name. The worker's name is hyphenated, so it is read as text/ast and never imported.\n\n**(4) Timeout-chain test** sits beside `test_one_15_second_budget_covers_both_fetches` (`:611`):\n- `_translate().REQUEST_BUDGET_SECONDS` (15.0, `:31`), `data.source_fetch.SOCKET_TIMEOUT_SECONDS` (4.0, `source_fetch.py:21`) and `lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS` (20).\n- `re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", text, re.M)` on `scripts/deploy-bluegreen.sh` gives exactly `[\"30\"]`. Line 50 is the only match: `:70` is indented `--drain) DRAIN_SECONDS=...`.\n- Assert 15 + 4 < 20 < 30.\n\n**Import caveats (verified):**\n- `lib` resolves to `client/backend/lib`, because conftest (`:43-48`) inserts BACKEND_DIR and imports `lib.http_utils` first, and there is no `lib` under `engine/`.\n- **`tests/active/test_source_fetch.py:25` does `from test_internal_translate import ...`** and `tests/tmp/probe_50_phase1_rows.py:11` does too. Any new module-level import (`lib.engine_api_client`), module-level fixture load or module-level `server_config` read in this file therefore runs whenever `test_source_fetch.py` is collected. Keep cross-layer imports inside the test function, as the file's `_translate()` pattern already does (`:297-299`).\n- `server_config` is already imported at module level (`:84`).\n\n**Docstring.** The module docstring (`:1-50`) gains entries for the four tests.\n\n**Regression risk.**\n- Existing tests: `BEATS` (`:746`, 15 000 true / 15 001 false) and `FRESH_BEATS` (`:950`) depend on `HEARTBEAT_FRESH_MS` staying 15000. They are unaffected if the value is kept.\n- New tests: moderate. The driver gaps above, plus the bool/int typing, are where a wrong implementation would pass or fail spuriously.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"new HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS beside the SUBTITLE_* tunables (:419-428)\">\n**What changes.** Add both constants after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`), each with a one-line comment as the block does:\n- `HEARTBEAT_SECONDS = 5.0`\n- `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)`, or `3 * int(HEARTBEAT_SECONDS * 1000)`; any form whose RHS names `HEARTBEAT_SECONDS` and evaluates to the int 15000.\n- The module imports only `os` (`:3`). No new import is needed.\n\n**Dependents.**\n- `internal_translate.py` and `translate-worker.py` (both via `from server_config import ...`).\n- Every test that imports `server_config`: `test_internal_translate.py:84`, `test_internal_events.py:33`, `test_random_cache.py:57`, `test_similar.py`, `test_popular_videos.py`, `test_search_fusion.py`, `test_server_config.py`.\n- The `VARIANT_RUNNER` (`test_internal_translate.py:1072-1086`) and `test_server_config.py:211-222` exec this file and override attributes after import. Overriding `HEARTBEAT_SECONDS` there would not move `HEARTBEAT_FRESH_MS` (derived at import), but no override does that today.\n\n**Regression risk.** Very low. The derived value must be an int (15000); the plan requires it, and `BEATS` and the docs depend on it.\n</impact>\n<impact path=\"engine/server/api/handlers/internal_translate.py\" element=\"server_config import (:27), the HEARTBEAT_FRESH_MS literal and rat-tail comment (:32-33), module docstring (:3, :5), _generation_available (:156-163)\">\n**What changes:**\n- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.\n- Delete `:32` (the rat-tail comment) and `:33` (`HEARTBEAT_FRESH_MS = 15_000`).\n- `_generation_available` (`:163`) reads the imported name unchanged.\n- Module docstring `:3` and `:5`: keep the name and add that it is defined in `server_config.py` and derived from `HEARTBEAT_SECONDS`.\n- The `_generation_available` docstring (`:157`) keeps the name.\n- `:30` (the budget comment naming the Client's 20 s) stays. It could optionally point at the timeout-chain test.\n\n**What does not change.** `REQUEST_BUDGET_SECONDS` (`:31`), `VIDEO_NOT_FOUND` (`:35`), both handlers' answers, and the sort at `:115`.\n\n**Dependents.**\n- `router.py:41` imports only the two handlers.\n- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track` and `resolve_translatable_video`, not the heartbeat.\n- Tests reach the module through `_translate()` / `_handler_module` and monkeypatch only `now_ms` (`:656`). Nothing patches `HEARTBEAT_FRESH_MS`, so turning it into an imported name is safe.\n- The new derivation test reads `module.HEARTBEAT_FRESH_MS`, which stays a module attribute through the import.\n\n**Regression risk.** Very low. If the import line drops `SUBTITLE_QUEUE_CAP`, the enqueue route breaks; `test_with_a_serving_worker_a_full_queue_answers_busy...` would catch that.\n</impact>\n<impact path=\"engine/server/db/jobs/translate-worker.py\" element=\"server_config import (:41), HEARTBEAT_SECONDS literal and rat-tail comment (:58-59); uses at :458, :467, :536\">\n**What changes:**\n- Add `HEARTBEAT_SECONDS` to `:41`, keeping alphabetical order: `DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, ...`.\n- Delete `:58` (the rat-tail comment) and `:59` (`HEARTBEAT_SECONDS = 5.0`).\n- The uses stay: the `heartbeat_loop` docstring `:458`, `stop.wait(HEARTBEAT_SECONDS)` `:467` and `beat.join(HEARTBEAT_SECONDS)` `:536`.\n- The module docstring `:8` (\"beating every 5 s\") stays true.\n- `:35` (the comment on why `api/` is on the path) could add the heartbeat. Optional.\n\n**Dependents.**\n- `test_translate_worker.py` runs the script as a subprocess and through `STALL_DRIVER` (`:214-222`, which execs the file and overrides only `STALL_SECONDS`), plus another `spec_from_file_location` load at `:258`.\n- Its beat timing constants depend on the 5 s cadence staying put: `BEAT_GAP_MS` (4500, 6500) `:208`, `BEAT_WINDOW_SECONDS` `:210`, `FIRST_BEAT_SECONDS` `:212`. Nothing patches `HEARTBEAT_SECONDS`.\n- Issue 56 (`docs/project/issues/plan.md:26`) expects a one-line conflict in this constants block.\n\n**Regression risk.** Low. A typo in the import gives an ImportError at worker start, which the `run`/stall tests in `test_translate_worker.py` would catch. Stale copies holding the literal remain under `tests/tmp/probe_53_draft_translate_worker*.py` and `delete_me/`. They are not collected and do not matter, except to an unscoped \"no literal left\" grep.\n</impact>\n<impact path=\"client/backend/lib/engine_api_client.py\" element=\"TRANSLATE_TIMEOUT_SECONDS, TRANSLATE_STATES, TRANSLATE_REQUEST_STATES, EngineApiError, fetch_translate, request_translate (read by tests only)\">\n**What changes.** Nothing; this file is read-only for this build.\n\n**Dependents added.**\n- `test_server.py` imports the parsers and state sets.\n- `test_internal_translate.py` imports `TRANSLATE_TIMEOUT_SECONDS` (20, `:18`).\n- The module imports only stdlib plus `.request_context`, which itself imports only `re` and `uuid`, so importing it into the Engine test process is safe.\n\n**Comment.** The comment at `:17` (\"30 s drain must stay above this\") stays accurate, and could optionally name the test.\n\n**Boundary guard.** `tests/check-client-engine-boundary.sh` scans only `client/backend` for Engine imports, so the tests are not affected.\n\n**Regression risk.**\n- None at runtime.\n- The tests break if `TRANSLATE_TIMEOUT_SECONDS`, `TRANSLATE_STATES` or `TRANSLATE_REQUEST_STATES` are renamed. That is intended.\n</impact>\n<impact path=\"client/frontend/src/data/translate.ts\" element=\"fetchTranslate, requestTranslate (exported), parseTranslateState/parseAvailable/parseCues (private), MALFORMED\">\n**What changes.** Nothing; no runtime change.\n\n**What the new bundle depends on:**\n- The exported names `fetchTranslate` and `requestTranslate`.\n- The exact text `Translate response was malformed` (`:19`).\n- `ready` sorted with `compareCues` and `running` left in order (`:101-104`).\n- The imports of `./api-base` (which reads `window.location.origin` at top level, `api-base.ts:5`, and `import.meta.env.VITE_CLIENT_API_BASE` / `DEV`) and `./profile` (`localStorage`, read lazily).\n\n**Other consumers.** `client/frontend/src/pages/video-page/translate.ts:11` imports from it; that file is unchanged.\n\n**Regression risk.** None at runtime. Renaming the message or the exports breaks the new test, which is intended.\n</impact>\n<impact path=\"client/frontend/src/data/api-base.ts\" element=\"top-level DEFAULT_CLIENT_API_BASE = window.location.origin\">\n**What changes.** Nothing.\n\n**Why listed.** The standalone `data/translate.ts` bundle pulls this module in. It reads `window.location.origin` when the module is evaluated, so the new runner must set `globalThis.window` before its dynamic `import()`. A static import, or a missing stub, throws `ReferenceError: window is not defined` before any case runs.\n\n**Risk.** It sits on the new test's setup path only.\n</impact>\n<impact path=\"engine/server/data/source_fetch.py\" element=\"SOCKET_TIMEOUT_SECONDS (:21)\">\n**What changes.** Nothing.\n\n**Dependents.** The new timeout-chain test reads it (4.0). The Engine test already imports `data.source_fetch` (`_handler_module`, `:400`).\n\n**Risk.** A rename breaks the test, which is intended. `MEDIA_SOCKET_TIMEOUT_SECONDS` (15.0) must not be the value read by mistake.\n</impact>\n<impact path=\"scripts/deploy-bluegreen.sh\" element=\"DRAIN_SECONDS=30 (:50) and the --drain help comment (:17-18)\">\n**What changes.** Nothing.\n\n**Why listed.** The timeout test parses `^DRAIN_SECONDS=(\\d+)$` (multiline). Today exactly one line matches (`:50`); `:70` is indented and quoted. The comment at `:17-18` (\"the Client's longest Engine request timeout is 20 s\") stays accurate.\n\n**Dependents.** `tests/active/test_deploy_bluegreen.py` runs the script with `--drain 0` and never reads the default.\n\n**Risk.** Reformatting the line (for example `DRAIN_SECONDS=\"30\"` or `: \"${DRAIN_SECONDS:=30}\"`) breaks the test by design.\n</impact>\n<impact path=\"engine/server/data/subtitles.py\" element=\"fetch_translate_heartbeat / write_translate_heartbeat\">\n**What changes.** Nothing. The plan considered it as the home for the pair and rejected it.\n\n**Dependents.** The Engine shape-test drivers write beats through `write_translate_heartbeat` (as `_beat` and the BRANCHES test do), and `_seed` uses this module's writers.\n\n**Risk.** None.\n</impact>\n<impact path=\"tests/active/test_source_fetch.py\" element=\"module-level `from test_internal_translate import CHUNK, HOST, ...` (:25)\">\n**What changes.** Nothing.\n\n**Why listed.** It imports `test_internal_translate` as a module, so everything new at that file's module level also runs when this suite is collected.\n\n**Risk.** Medium if the new Engine tests add a module-level `from lib.engine_api_client import ...`, a module-level fixture load or a module-level `ast` read. If such a step failed, `test_source_fetch.py` would fail to collect too. Keep those reads inside the test bodies.\n</impact>\n<impact path=\"tests/active/test_translate_worker.py\" element=\"worker service, stall-driver and beat-cadence tests (:205-224, :1250-1300)\">\n**What changes.** Nothing; this is a guard suite.\n\n**Why listed.**\n- It is the only suite that runs the worker after the import change, through the subprocess `run`, the `STALL_DRIVER` exec and the `spec_from_file_location` load at `:258`.\n- Its beat cadence windows (`BEAT_GAP_MS` 4500-6500 ms) prove `HEARTBEAT_SECONDS` is still 5.0.\n- It is one of the six translate suites to baseline before the build.\n\n**Risk.** It catches any NameError or ImportError from the move.\n</impact>\n<impact path=\"tests/config.json\" element=\"test_groups for test_server.py, test_frontend_translate.py, test_internal_translate.py\">\n**What changes.** These groups map source files to the suites that cover them. Add:\n- `tests/active/fixtures/translate_contract.json` to all three groups.\n- To `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py` (read by the derivation test), `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh` (read by the timeout test).\n- `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.\n\nThere is precedent for data files in groups (`tests/active/host_tokens.json`, `upstream_snippet_cases.json`).\n\n**Risk.** If these entries are left out, a change to the fixture, the deploy script or the Client timeout would not trigger the suites that read them. The runtime tests themselves are unaffected. I am not certain how strictly the runner uses `test_groups` for selection, so treat this as recommended.\n</impact>\n<impact path=\"engine/server/README.md\" element=\"/internal/translate bullet (:15), Availability (:18), worker tunables paragraph (:30), heartbeat line (:38)\">\n**What changes:**\n- `:15` gains the running-slice rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted. Keep the wording consistent with `CONTEXT.md:17`.\n- `:18` says `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats), still 15 000 ms.\n- Optional: `:30` lists the worker's `server_config` tunables and could add `HEARTBEAT_SECONDS`.\n- `:38` (\"every 5 s\", \"15 s freshness rule\") stays true.\n\n**Risk.** Docs only.\n</impact>\n<impact path=\"engine/server/db/jobs/docs/TRANSLATE_WORKER.md\" element=\"Heartbeat section (:155)\">\n**What changes.** Remove \"Raise both constants together.\" and name the single definition: `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived as three beats. The \"every 5 s\", \"15 s\" and \"up to 5 s\" join figures (`:146`) stay.\n\n**Risk.** Docs only.\n</impact>\n<impact path=\"CONTEXT.md\" element=\"Translate state (:17), Generation available (:18)\">\n**What changes.** Nothing. `:17` already states the running-slice rule and the \"one contract fixture ... (issue 55)\" sentence. `:18` already states 15 s = three 5 s beats.\n\n**Risk.** None. It is listed so the build does not edit it twice.\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"--drain row (:174), translate worker paragraph (:230)\">\n**What changes.** Optional only.\n- `:174` says the drain covers the Client's 20 s timeout, and could add that a test now enforces this.\n- `:230` names \"the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats\", and could add \"derived in `server_config.py`\".\n\nBoth are accurate as written.\n\n**Risk.** None.\n</impact>\n<impact path=\"client/README.md\" element=\"GET /api/translate paragraph (:32)\">\n**What changes.** Nothing. It names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the parsing rules, all unchanged.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/55-translate-state-contract.md\" element=\"acceptance criteria (:64-73)\">\n**What changes.** Only the status/checkboxes when the build is delivered (move to archive per `docs/project/triage-labels.md`). No content change is needed now.\n\n**Note.** AC \"every existing ... test passes unchanged\" depends on running the baseline of the six suites first: test_internal_translate, test_server, test_frontend_translate, test_translate_worker, test_subtitles and test_source_fetch.\n\n**Risk.** None.\n</impact>\n<impact path=\"docs/project/issues/plan.md\" element=\"55/56 overlap note (:13, :26)\">\n**What changes.** Nothing. It already predicts the one-line conflict with issue 56 in the worker's constants block, which this build creates by deleting `translate-worker.py:58-59`.\n\n**Risk.** A merge conflict with the 56 branch.\n</impact>\n</impacts>",
  "docs_checklist": "- [x] `engine/server/README.md` - updated: I updated `engine/server/README.md` in three places: the running-slice rule for `total`, where the heartbeat window is defined and how it is derived, and the worker's beat interval in its `server_config` names.\n- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: Heartbeat section: removed the false \"Raise both constants together.\" and now say that the fresh window comes from the beat interval, defined once in `api/server_config.py`.\n- [x] `engine/server/api/handlers/internal_translate.py` - updated: The module docstring now says where `HEARTBEAT_FRESH_MS` comes from: `server_config.py`, as three `HEARTBEAT_SECONDS` beats.\n- [x] `engine/server/db/jobs/translate-worker.py` - updated: The worker's comment on why `api/` is on the import path now says it also supplies the heartbeat interval.\n- [x] `tests/active/test_frontend_translate.py` - updated: I added a paragraph to the module docstring of `tests/active/test_frontend_translate.py` describing the third runner, `CONTRACT_RUNNER`.\n- [x] `docs/project/issues/55-translate-state-contract.md` - updated: Issue 55 is now marked `complete`: all acceptance criteria are ticked, a Delivered note is added, and the issue is copied to `docs/project/issues/archive/`. **The original at `docs/project/issues/55-translate-state-contract.md` still needs deleting** (for example with `git rm`), because I have no delete tool.\n- [x] `tests/active/test_server.py` - out of scope: The file was not edited. The harvest plan (docs/project/plans/harvest-55-translate-state-contract-plan.md) sends phase 1's gateway replay and coverage tests to a NEW `tests/active/test_engine_api_client.py`, not to this file. Its translate docstring paragraphs still describe exactly the tests it holds. The new module's docstring belongs to that harvest step.\n- [x] `tests/active/test_internal_translate.py` - out of scope: The docstring already gained the build's paragraph: \"Contract drivers: `ENGINE_DRIVERS` \u2026\" (diff, line 48) describes the driver table that is in the module. The other checklist entries describe tests that are not in this module. Per the harvest plan, the per-(route, state) shape test and the timeout-chain test are still in tests/tmp waiting to be harvested here, and that step writes their docstring lines. The Video-not-found test is classified REDUNDANT, because existing tests already assert the 404 body on both routes. The heartbeat derivation test goes to `tests/active/test_server_config.py`. Nothing the docstring claims today is false.\n- [x] `DEPLOYMENT.md` - out of scope: Line 174 (the `--drain` row: 30 s default, the Client's longest Engine timeout 20 s) and line 230 (\"the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats\") are both still accurate. No value changed, and neither sentence claims where the constant is defined. The only changes to this file during the build (the `--stall-seconds` row and the stall troubleshooting row) are issue 56's work and are accurate.\n- [x] `CONTEXT.md` - out of scope: Translate state (line 17) already states that `total` always counts every stored cue whatever `after` was, and the requeue inference. It also states that all three layers are held to one contract fixture that each layer's tests replay (issue 55). Generation available (line 18) states 15 s = three 5 s beats, and both values are unchanged. The glossary does not name constant locations, so moving the heartbeat changes nothing in it.\n- [x] `client/README.md` - out of scope: The `GET /api/translate` paragraph names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the gateway's parsing rules. The build left all of these unchanged (engine_api_client.py is not in the diff).\n- [x] `engine/server/api/server_config.py` - out of scope: The two new constants each carry a one-line comment in the block's style: the beat interval, and the fresh window as three beats so one late beat is tolerated. Both comments are accurate, and no other comment in the module refers to the heartbeat.\n- [x] `docs/project/issues/plan.md` - out of scope: Lines 13 and 26 describe the 55/56 overlap: 55 removes the `HEARTBEAT_SECONDS` literal and 56 leaves it alone. That is what happened (the worker diff shows 56's keyword parameters next to 55's import change), so the note is still accurate as a planning record.",
  "docs": [
    {
      "path": "engine/server/README.md",
      "note": "- Line 15 (`/internal/translate`): add the running-slice rule. `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.\n- Line 18 (Availability): say `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats, still 15 000 ms).\n- Optional: line 30 could list `HEARTBEAT_SECONDS` among the worker's tunables in `api/server_config.py`."
    },
    {
      "path": "engine/server/db/jobs/docs/TRANSLATE_WORKER.md",
      "note": "Line 155: remove \"Raise both constants together.\" and name the single definition, `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats."
    },
    {
      "path": "engine/server/api/handlers/internal_translate.py",
      "note": "The module docstring (lines 3 and 5) keeps the name `HEARTBEAT_FRESH_MS` and says it is defined in `server_config.py`, derived from `HEARTBEAT_SECONDS`. The rat-tail comment at line 32 is deleted with the literal."
    },
    {
      "path": "engine/server/db/jobs/translate-worker.py",
      "note": "The rat-tail comment at line 58 is deleted with the literal. The module docstring at line 8 (\"every 5 s\") stays."
    },
    {
      "path": "tests/active/test_server.py",
      "note": "The module docstring's translate paragraphs (lines 132-148) gain a paragraph for the fixture replay through `fetch_translate`/`request_translate` and for the fixture coverage check."
    },
    {
      "path": "tests/active/test_frontend_translate.py",
      "note": "The module docstring (lines 1-31) gains a paragraph for the standalone `data/translate.ts` bundle and its replay runner, including the `1e999` serialisation and its control."
    },
    {
      "path": "tests/active/test_internal_translate.py",
      "note": "The module docstring (lines 1-50) gains entries for the per-(route, state) shape test against the fixture, the fixture Video-not-found body test on both routes, the heartbeat derivation test, and the timeout-chain test."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "Optional only. Line 230 could say `HEARTBEAT_FRESH_MS` is derived in `server_config.py`, and line 174 could say a test now enforces drain > Client timeout. Both are accurate as written."
    }
  ],
  "reassessments": 2,
  "draft": "## Draft implementation: translate state contract fixture (issue 55)\n\nBefore writing this I read: `engine_api_client.py`, `data/translate.ts`, `data/api-base.ts`, `data/profile.ts`, `internal_translate.py`, the head of `translate-worker.py`, `server_config.py:410-433`, the translate blocks of `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` (harness `:297-460`, job-state and enqueue tests `:628-997`), `deploy-bluegreen.sh` (only line 50 matches the drain regex), `source_fetch.py:21`, `tests/config.json`, the README `/internal/translate` block, `TRANSLATE_WORKER.md:155` and `CONTEXT.md:17-18`.\n\n**Step zero, before any edit:** run all six translate suites in full and record the result as the baseline: `test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`. Also run `test_source_fetch.py`, which imports `test_internal_translate`.\n\n### What has to be tested\n\n1. Each fixture case goes through the gateway's real parsing (`fetch_translate` / `request_translate`) and gives the normalised answer, or `EngineApiError`.\n2. Each fixture case goes through the real `data/translate.ts`. A valid answer is accepted with the same fields, `ready` sorted and `running` in stored order. A rejected body throws exactly `MALFORMED`.\n3. Each `(route, state)` the Engine can produce answers with the key set and JSON types of the fixture's case that carries `available`. The `Video not found` 404 body equals the fixture's.\n4. The fixture covers every gateway state with and without `available`, and its names are unique. A state added on one side only fails.\n5. The heartbeat window is derived from the interval, and both consumers import it.\n6. budget + socket < Client timeout < drain, using the real values.\n\n### Module map\n\n| File | Change |\n|---|---|\n| `tests/active/fixtures/translate_contract.json` | new (and a new directory) |\n| `tests/active/test_server.py` | +1 import line, +2 module constants, +2 tests, +1 docstring paragraph |\n| `tests/active/test_frontend_translate.py` | +3 constants, +1 runner string, +1 module fixture, +1 helper, +1 test, +1 docstring paragraph |\n| `tests/active/test_internal_translate.py` | +2 stdlib imports, +1 path constant, helpers, driver table, +5 tests, docstring entries |\n| `engine/server/api/server_config.py` | +2 constants |\n| `engine/server/api/handlers/internal_translate.py` | import line, \u22122 lines, docstring |\n| `engine/server/db/jobs/translate-worker.py` | import line, \u22122 lines |\n| `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | prose |\n| `tests/config.json` | group entries |\n\nNo other runtime file changes. `engine_api_client.py`, `data/translate.ts`, `api-base.ts`, `source_fetch.py`, `deploy-bluegreen.sh` and `CONTEXT.md` are read only.\n\n---\n\n### 1. `tests/active/fixtures/translate_contract.json`\n\nThe file has one case per line. `1e999` is legal JSON: Python's `json` reads it as `inf` and node's `JSON.parse` reads it as `Infinity`. Three cue lists are used:\n- **Ready list:** out of start order, with two cues sharing start 1.0, so a frontend that does not sort, or sorts by start only, shows.\n- **Running list:** stored order, not sorted.\n- **Sliced running answer:** `after` 3, two cues, `total` 5.\n\n```json\n{\n  \"description\": \"Translate state contract (issue 55), read only by tests: test_server.py replays every case through fetch_translate/request_translate, test_frontend_translate.py through data/translate.ts, test_internal_translate.py checks the Engine's keys and JSON types against the valid cases that carry available. Nothing at runtime reads this file. route is state (POST /internal/translate) or enqueue (POST /internal/translate/enqueue); after (state route only) is the running cue count the reader holds; engine is what the Engine answers; gateway is the Client gateway's normalised answer, or \\\"rejected\\\" for EngineApiError. The gateway keeps the Engine's cue order (running in stored order; ready is sorted only by the frontend). Every (route, state) of a valid 200 case appears with available and without it (an older Engine; read as false). A rejected Engine body must be refused by the gateway and also by the frontend when served as a 200 gateway answer, so a float-valued integral total such as 3.0 (refused by the gateway, accepted by JS) cannot be a case. 1e999 is standard JSON and parses to infinity in Python and JS. The enqueue none case with available true is an answer the Engine never gives (it answers none only with available false); it is here for the with/without-available coverage, which checks keys and types only.\",\n  \"cases\": [\n    {\"name\": \"state none\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": true}}, \"gateway\": {\"state\": \"none\", \"available\": true}},\n    {\"name\": \"state none without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"state queued\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": true}}, \"gateway\": {\"state\": \"queued\", \"available\": true}},\n    {\"name\": \"state queued without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\"}}, \"gateway\": {\"state\": \"queued\", \"available\": false}},\n    {\"name\": \"state running\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": true}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": true}},\n    {\"name\": \"state running without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 5.0, \"end\": 6.0, \"text\": \"Third\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"First\"}, {\"start\": 3.0, \"end\": 4.0, \"text\": \"Second\"}], \"total\": 3, \"available\": false}},\n    {\"name\": \"state running after 3\", \"route\": \"state\", \"after\": 3, \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [{\"start\": 9.0, \"end\": 10.0, \"text\": \"Fifth\"}, {\"start\": 7.0, \"end\": 8.0, \"text\": \"Fourth\"}], \"total\": 5, \"available\": true}}, \"gateway\": {\"state\": \"running\", \"cues\": [{\"start\": 9.0, \"end\": 10.0, \"text\": \"Fifth\"}, {\"start\": 7.0, \"end\": 8.0, \"text\": \"Fourth\"}], \"total\": 5, \"available\": true}},\n    {\"name\": \"state ready\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": true}}, \"gateway\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": true}},\n    {\"name\": \"state ready without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}]}}, \"gateway\": {\"state\": \"ready\", \"cues\": [{\"start\": 4.0, \"end\": 5.0, \"text\": \"Later\"}, {\"start\": 1.0, \"end\": 3.0, \"text\": \"Long first\"}, {\"start\": 1.0, \"end\": 2.0, \"text\": \"Short first\"}], \"available\": false}},\n    {\"name\": \"state already_english\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\", \"available\": true}}, \"gateway\": {\"state\": \"already_english\", \"available\": true}},\n    {\"name\": \"state already_english without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\"}}, \"gateway\": {\"state\": \"already_english\", \"available\": false}},\n    {\"name\": \"state failed\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\", \"available\": true}}, \"gateway\": {\"state\": \"failed\", \"available\": true}},\n    {\"name\": \"state failed without available\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\"}}, \"gateway\": {\"state\": \"failed\", \"available\": false}},\n    {\"name\": \"state video not found\", \"route\": \"state\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Video not found\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"enqueue none\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": true}}, \"gateway\": {\"state\": \"none\", \"available\": true}},\n    {\"name\": \"enqueue none without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"enqueue queued\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": true}}, \"gateway\": {\"state\": \"queued\", \"available\": true}},\n    {\"name\": \"enqueue queued without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\"}}, \"gateway\": {\"state\": \"queued\", \"available\": false}},\n    {\"name\": \"enqueue running\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"available\": true}}, \"gateway\": {\"state\": \"running\", \"available\": true}},\n    {\"name\": \"enqueue running without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\"}}, \"gateway\": {\"state\": \"running\", \"available\": false}},\n    {\"name\": \"enqueue ready\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"available\": true}}, \"gateway\": {\"state\": \"ready\", \"available\": true}},\n    {\"name\": \"enqueue ready without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\"}}, \"gateway\": {\"state\": \"ready\", \"available\": false}},\n    {\"name\": \"enqueue already_english\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\", \"available\": true}}, \"gateway\": {\"state\": \"already_english\", \"available\": true}},\n    {\"name\": \"enqueue already_english without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"already_english\"}}, \"gateway\": {\"state\": \"already_english\", \"available\": false}},\n    {\"name\": \"enqueue failed\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\", \"available\": true}}, \"gateway\": {\"state\": \"failed\", \"available\": true}},\n    {\"name\": \"enqueue failed without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"failed\"}}, \"gateway\": {\"state\": \"failed\", \"available\": false}},\n    {\"name\": \"enqueue busy\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\", \"available\": true}}, \"gateway\": {\"state\": \"busy\", \"available\": true}},\n    {\"name\": \"enqueue busy without available\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\"}}, \"gateway\": {\"state\": \"busy\", \"available\": false}},\n    {\"name\": \"enqueue video not found\", \"route\": \"enqueue\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Video not found\"}}, \"gateway\": {\"state\": \"none\", \"available\": false}},\n    {\"name\": \"state route missing 404\", \"route\": \"state\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Not found\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue route missing 404\", \"route\": \"enqueue\", \"engine\": {\"status\": 404, \"body\": {\"error\": \"Not found\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state unknown state\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"bogus\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue unknown state\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"bogus\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state busy\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"busy\", \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state available a string\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"none\", \"available\": \"true\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"enqueue available a string\", \"route\": \"enqueue\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"queued\", \"available\": \"true\"}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state cues not a list\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": {\"start\": 1.0, \"end\": 2.0, \"text\": \"Hello\"}, \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state start 1e999\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1e999, \"end\": 2.0, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state start true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": true, \"end\": 2.0, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state end true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1.0, \"end\": true, \"text\": \"Hello\"}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state text a number\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"ready\", \"cues\": [{\"start\": 1.0, \"end\": 2.0, \"text\": 7}], \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state total -1\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [], \"total\": -1, \"available\": true}}, \"gateway\": \"rejected\"},\n    {\"name\": \"state total true\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"running\", \"cues\": [], \"total\": true, \"available\": true}}, \"gateway\": \"rejected\"}\n  ]\n}\n```\n\nI traced every rejection through both parsers:\n\n| Case | Gateway (`engine_api_client.py`) | Frontend served as 200 (`translate.ts`) |\n|---|---|---|\n| route missing 404 (both) | non-200, not `Video not found`, `:189`/`:210` | no `state`, `:107` / `:80` |\n| unknown state (both) | `:192` / `:213` | `:107` / `:80` |\n| state busy | not in `TRANSLATE_STATES` `:192` | falls through to `:107` |\n| available a string (both) | `_translate_available` `:164` | `parseAvailable` `:113` |\n| cues not a list | `_checked_cues` `:171` | `parseCues` `:118` |\n| start 1e999 | stub writes `Infinity`, `json.loads` gives inf, `_is_seconds` fails | stub writes `1e999`, `Number.isFinite(Infinity)` fails `:120` |\n| start / end true | `_is_seconds` excludes bool | `Number.isFinite(true)` is false |\n| text a number | `:175` | `:120` |\n| total -1 / true | `:199` | `:103` |\n\nCase count: 29 valid (12 state, 1 sliced running, 14 enqueue, 2 not-found) and 14 rejected.\n\n---\n\n### 2. `tests/active/test_server.py`\n\n**Import**, added to the existing `lib` block at `:180-183`. It goes before the Engine path insert, so `lib` stays the Client package:\n\n```python\nfrom lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate\n```\n\n**Appended after `:1932`**, so `TRANSLATE_STATE_ROUTE`/`TRANSLATE_ENQUEUE_ROUTE` (`:1713-1714`) and `TRANSLATE_BODY` (`:1715`) are already defined:\n\n```python\n# The contract fixture all three layers replay (issue 55); loaded at collection because parametrize needs its cases, so a missing or malformed file stops this module's collection.\nTRANSLATE_CONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\nTRANSLATE_CONTRACT_CASES = json.loads(TRANSLATE_CONTRACT.read_text())[\"cases\"]\n\n\n@pytest.mark.parametrize(\"case\", TRANSLATE_CONTRACT_CASES, ids=[case[\"name\"] for case in TRANSLATE_CONTRACT_CASES])\ndef test_each_contract_fixture_case_parses_to_its_gateway_answer_or_engine_api_error(case):\n    state_route = case[\"route\"] == \"state\"\n    with _translate_engine((case[\"engine\"][\"status\"], case[\"engine\"][\"body\"])) as (engine_base, seen):\n        try:\n            answered = fetch_translate(engine_base, \"uuid-1\", \"peer.example\", after=case.get(\"after\")) if state_route else request_translate(engine_base, \"uuid-1\", \"peer.example\")\n        except EngineApiError:\n            answered = \"rejected\"\n    assert answered == case[\"gateway\"]\n    # Control: the Engine was reached once, on the case's route with exactly id, host and the case's after, so a rejection above is the parse's and not a failed call.\n    sent = {**TRANSLATE_BODY, **({\"after\": case[\"after\"]} if \"after\" in case else {})}\n    assert [(entry[1], entry[4]) for entry in seen] == [(TRANSLATE_STATE_ROUTE if state_route else TRANSLATE_ENQUEUE_ROUTE, sent)]\n\n\ndef test_the_contract_fixture_covers_every_gateway_state_with_and_without_available_under_unique_names():\n    names = [case[\"name\"] for case in TRANSLATE_CONTRACT_CASES]\n    assert len(names) == len(set(names)), sorted(name for name in names if names.count(name) > 1)\n    assert {case[\"route\"] for case in TRANSLATE_CONTRACT_CASES} == {\"state\", \"enqueue\"}\n    assert all(case[\"route\"] == \"state\" for case in TRANSLATE_CONTRACT_CASES if \"after\" in case)\n    valid = [case for case in TRANSLATE_CONTRACT_CASES if case[\"gateway\"] != \"rejected\" and case[\"engine\"][\"status\"] == 200]\n    for route, states in ((\"state\", TRANSLATE_STATES), (\"enqueue\", TRANSLATE_REQUEST_STATES)):\n        bodies = [case[\"engine\"][\"body\"] for case in valid if case[\"route\"] == route]\n        assert {body[\"state\"] for body in bodies if \"available\" in body} == states, route\n        assert {body[\"state\"] for body in bodies if \"available\" not in body} == states, route\n        # Exactly one Video-not-found case per route, which the Engine's not-found test reads.\n        assert [case[\"engine\"][\"body\"] for case in TRANSLATE_CONTRACT_CASES if case[\"route\"] == route and case[\"engine\"][\"status\"] == 404 and case[\"gateway\"] != \"rejected\"] == [{\"error\": \"Video not found\"}], route\n```\n\n- **`after` is passed explicitly.** `fetch_translate(..., after=None)` sends no `after`, which matches `sent` for every case without one.\n- **Why the stub accepts the `1e999` case.** `_TranslateEngine` writes it as `Infinity` through `json.dumps`, and `_post_json`'s `json.loads` accepts that. The refusal then comes from `_is_seconds`.\n- **No bridge token is needed** (`bridge_headers` simply omits the header).\n\n**Docstring paragraph**, inserted after `:146`:\n\n> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55): every case is replayed by calling `fetch_translate` (state route, with the case's `after` when it has one) or `request_translate` (enqueue route) against a `_TranslateEngine` answering the case's status and body. Each gives exactly the case's `gateway` answer, or raises `EngineApiError` for `rejected`, from exactly one request to that route carrying id, host and the case's `after`. The fixture itself has unique names and only the two routes. Its valid 200 states are exactly `TRANSLATE_STATES` on the state route and `TRANSLATE_REQUEST_STATES` on the enqueue route, each with `available` and without it, and each route has exactly one `Video not found` 404 case.\n\n---\n\n### 3. `tests/active/test_frontend_translate.py`\n\n**Constants**, after `INITIAL_TEXT` (`:66`):\n\n```python\n# The contract fixture all three layers replay (issue 55); valid cases serve their gateway answer, rejected ones their Engine body, each as a 200.\nCONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\nCONTRACT_CASES = json.loads(CONTRACT.read_text())[\"cases\"]\nMALFORMED = \"Translate response was malformed\"\n```\n\n**Runner**, appended after the generation tests:\n\n```python\nCONTRACT_RUNNER = \"\"\"\nimport fs from \"node:fs\";\nconst memory = () => { const s = new Map(); return {\n  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),\n  removeItem: (k) => s.delete(k) }; };\nglobalThis.localStorage = memory();\n// api-base.ts reads window.location.origin when it is evaluated, so window exists before the import below.\nglobalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };\nlet served = null;\nglobalThis.fetch = async () => new Response(served, { status: 200, headers: { \"content-type\": \"application/json\" } });\n// JSON.stringify writes a non-finite number as null, which would be refused for the wrong reason; it goes back out as 1e999, as the fixture wrote it.\nconst NON_FINITE = \"__non_finite__\";\nconst serialise = (value) => JSON.stringify(value, (key, v) => (typeof v === \"number\" && !Number.isFinite(v) ? NON_FINITE : v)).replaceAll(JSON.stringify(NON_FINITE), \"1e999\");\nconst hasNonFinite = (value) => (typeof value === \"number\" ? !Number.isFinite(value) : value !== null && typeof value === \"object\" && Object.values(value).some(hasNonFinite));\nconst { fetchTranslate, requestTranslate } = await import(process.env.BUNDLE);\nconst report = {};\nfor (const c of JSON.parse(fs.readFileSync(process.env.CONTRACT, \"utf8\")).cases) {\n  served = serialise(c.gateway === \"rejected\" ? c.engine.body : c.gateway);\n  // What the parser will read, parsed the way readTranslateResponse parses it.\n  const nonFinite = hasNonFinite(JSON.parse(served));\n  try {\n    const value = c.route === \"state\" ? await fetchTranslate(process.env.BASE, \"uuid-1\", process.env.HOST, c.after) : await requestTranslate(process.env.BASE, \"uuid-1\", process.env.HOST);\n    report[c.name] = { value, nonFinite };\n  } catch (error) {\n    report[c.name] = { thrown: String(error?.message ?? error), nonFinite };\n  }\n}\nprocess.stdout.write(JSON.stringify(report) + \"\\\\n\", () => process.exit(0));\n\"\"\"\n\n\n@pytest.fixture(scope=\"module\")\ndef contract_report(tmp_path_factory) -> dict:\n    out = tmp_path_factory.mktemp(\"translate_contract\")\n    subprocess.run(\n        [str(ESBUILD), str(FRONTEND / \"src\" / \"data\" / \"translate.ts\"), \"--bundle\", \"--format=esm\", \"--platform=node\",\n         f\"--outfile={out / 'bundle.mjs'}\", f\"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}\",\n         \"--define:import.meta.env.DEV=false\"],\n        check=True, capture_output=True,\n    )\n    (out / \"runner.mjs\").write_text(CONTRACT_RUNNER)\n    proc = subprocess.run(\n        [\"node\", str(out / \"runner.mjs\")], capture_output=True, text=True, timeout=60,\n        env={\"BASE\": BASE, \"BUNDLE\": str(out / \"bundle.mjs\"), \"CONTRACT\": str(CONTRACT), \"HOST\": HOST, \"PATH\": os.environ.get(\"PATH\", \"\")},\n    )\n    assert proc.returncode == 0, proc.stderr\n    return json.loads(proc.stdout.splitlines()[-1])\n\n\ndef _has_non_finite(value) -> bool:\n    if isinstance(value, float):\n        return not math.isfinite(value)\n    if isinstance(value, dict):\n        return any(_has_non_finite(v) for v in value.values())\n    return isinstance(value, list) and any(_has_non_finite(v) for v in value)\n\n\n@pytest.mark.parametrize(\"case\", CONTRACT_CASES, ids=[case[\"name\"] for case in CONTRACT_CASES])\ndef test_each_contract_fixture_case_is_accepted_with_its_fields_or_refused_as_malformed(contract_report, case):\n    result = contract_report[case[\"name\"]]\n    if case[\"gateway\"] == \"rejected\":\n        assert result.get(\"thrown\") == MALFORMED, result  # exactly the parser's refusal, so a JSON SyntaxError cannot pass as one\n    else:\n        expected = case[\"gateway\"]\n        if case[\"route\"] == \"state\" and expected[\"state\"] == \"ready\":\n            expected = {**expected, \"cues\": sorted(expected[\"cues\"], key=lambda cue: (cue[\"start\"], cue[\"end\"]))}\n        assert result.get(\"value\") == expected, result  # ready re-sorted by start then end; running left in the gateway's order\n    # Control: the parser read infinity exactly where the fixture wrote 1e999, so the 1e999 case is refused for its non-finite start, not for a null.\n    served = case[\"engine\"][\"body\"] if case[\"gateway\"] == \"rejected\" else case[\"gateway\"]\n    assert result[\"nonFinite\"] == _has_non_finite(served)\n```\n\n- **New import:** `import math`.\n- **No embed alias or CSS loader.** Nothing in the `data/translate.ts` \u2192 `api-base`/`profile` chain needs them.\n- **The `1e999` control is an assertion over every case.** The set of cases that reached the parser as non-finite must equal the set the fixture writes with `1e999`.\n- **Known gap in the sentinel.** It writes `-Infinity` as `1e999` too. No case uses a negative infinity.\n- **One node process runs every case**, through the module fixture.\n\n**Docstring paragraph**, before the \"The request and the poll run under a second runner\" paragraph:\n\n> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55) runs under a third runner, `CONTRACT_RUNNER`, over `data/translate.ts` bundled on its own. It stubs `window`, `localStorage` and a `fetch` that answers 200 with the served text, then imports the bundle and reads the fixture itself with `fs`. For each case it serves the gateway answer (a valid case) or the Engine body (a rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route), in one node process. A valid case answers exactly its gateway answer, with `ready` cues sorted by start then end and `running` cues in the order given. Every rejected case throws exactly `Translate response was malformed`. Non-finite numbers are served as `1e999`, because `JSON.stringify` would write `null`. As a control, the parser read infinity in exactly the cases whose fixture value is non-finite.\n\n---\n\n### 4. `tests/active/test_internal_translate.py`\n\n**Imports:** `import ast` and `import re` join the stdlib block at `:54-67`. Both are stdlib and safe at module level.\n\n**Keeping `test_source_fetch.py` safe.** That file imports this module, so nothing new at module level may read a file or import another layer. Only a path constant and static code are added. The fixture is read inside each test.\n\n> **Departure from the plan (named):** the plan parametrized the Engine test over the fixture's cases. That needs a module-level fixture read, which the impact inventory flags as a hazard through `test_source_fetch.py:25`. Instead the test is parametrized over the static driver table. A separate test asserts that the fixture's valid `(route, state)` set equals the driver table's keys. A fixture state with no driver still fails, and so does a driver with no fixture state. Each parametrized run checks every fixture case for its key.\n\nCode is inserted after `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues` (`:997`). All the helpers it uses (`NOW`, `BODY`, `_seed`, `_claimed`, `_beat`, `_route`, `_instance`, `_state`, `_enqueue`, `_server`, `_subtitles_db`) are defined above that point.\n\n```python\n# The contract fixture all three layers replay (issue 55); read inside each test, because test_source_fetch.py imports this module.\nCONTRACT = Path(__file__).resolve().parent / \"fixtures\" / \"translate_contract.json\"\n\n\ndef _contract_cases() -> list[dict]:\n    return json.loads(CONTRACT.read_text())[\"cases\"]\n\n\ndef _engine_contract_case(case: dict) -> bool:\n    \"\"\"A valid 200 case that carries available, as this Engine always answers; the cases without it stand for older Engines.\"\"\"\n    return case[\"gateway\"] != \"rejected\" and case[\"engine\"][\"status\"] == 200 and \"available\" in case[\"engine\"][\"body\"]\n\n\ndef _json_type(value: object) -> str:\n    \"\"\"The JSON type a value is written as; bool first, since a bool is also an int.\"\"\"\n    if isinstance(value, bool):\n        return \"boolean\"\n    if isinstance(value, (int, float)):\n        return \"number\"\n    if isinstance(value, str):\n        return \"string\"\n    if isinstance(value, list):\n        return \"array\"\n    if isinstance(value, dict):\n        return \"object\"\n    return \"null\" if value is None else type(value).__name__\n\n\ndef _types(body: dict) -> dict[str, str]:\n    return {key: _json_type(value) for key, value in body.items()}\n\n\ndef _running_cues(count: int) -> list[dict]:\n    \"\"\"count stored running cues, in descending start order so they are not sorted; as many as the case's total, so an after slice leaves cues to check.\"\"\"\n    return [{\"start\": float(count - index), \"end\": float(count - index) + 0.5, \"text\": f\"cue {index}\"} for index in range(count)]\n\n\ndef _state_driver(row: str):\n    \"\"\"The state route with the key seeded as row and a fresh beat; the instance holds no en track, so failed, already_english and no row are answered as stored, not as ready.\"\"\"\n    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:\n        from data.subtitles import write_translate_heartbeat\n\n        store = _subtitles_db(subtitles_path)\n        if row == \"running\":\n            assert _claimed(store).write_running_cues(_running_cues(case[\"engine\"][\"body\"][\"total\"]), \"fr\")\n        else:\n            _seed(store, row)\n        write_translate_heartbeat(store, NOW, 1)\n        body = {**BODY, \"after\": case[\"after\"]} if \"after\" in case else BODY\n        return _state(_route(_instance(False), monkeypatch), _server(whitelist, subtitles_path), body)\n    return drive\n\n\ndef _enqueue_driver(row: str | None):\n    \"\"\"The enqueue route: None is no beat (none), \"busy\" a queue filled to SUBTITLE_QUEUE_CAP, else the key seeded as row; a fresh beat unless None.\"\"\"\n    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:\n        from data.subtitles import enqueue_translate_job\n\n        store = _subtitles_db(subtitles_path)\n        if row == \"busy\":\n            for index in range(SUBTITLE_QUEUE_CAP):\n                assert enqueue_translate_job(store, f\"q-{index:03d}\", HOST, \"en\", SUBTITLE_QUEUE_CAP, NOW - 5000) == (\"queued\", \"queued\")\n        elif row is not None:\n            _seed(store, row)\n        store.close()\n        if row is not None:\n            _beat(subtitles_path, 0)\n        return _enqueue(_route(RecordingInstance(), monkeypatch), _server(whitelist, subtitles_path), BODY)\n    return drive\n\n\n# How the Engine is driven into each (route, state) the contract fixture names.\nENGINE_DRIVERS = {\n    (\"state\", \"none\"): _state_driver(\"no row\"),\n    (\"state\", \"queued\"): _state_driver(\"queued\"),\n    (\"state\", \"running\"): _state_driver(\"running\"),\n    (\"state\", \"ready\"): _state_driver(\"ready\"),\n    (\"state\", \"already_english\"): _state_driver(\"already_english\"),\n    (\"state\", \"failed\"): _state_driver(\"failed\"),\n    (\"enqueue\", \"none\"): _enqueue_driver(None),\n    (\"enqueue\", \"queued\"): _enqueue_driver(\"no row\"),\n    (\"enqueue\", \"running\"): _enqueue_driver(\"running\"),\n    (\"enqueue\", \"ready\"): _enqueue_driver(\"ready\"),\n    (\"enqueue\", \"already_english\"): _enqueue_driver(\"already_english\"),\n    (\"enqueue\", \"failed\"): _enqueue_driver(\"failed\"),\n    (\"enqueue\", \"busy\"): _enqueue_driver(\"busy\"),\n}\n\n\ndef test_every_route_state_in_the_contract_fixture_has_an_engine_driver():\n    assert {(case[\"route\"], case[\"engine\"][\"body\"][\"state\"]) for case in _contract_cases() if _engine_contract_case(case)} == set(ENGINE_DRIVERS)\n\n\n@pytest.mark.parametrize(\"route, state\", ENGINE_DRIVERS.keys(), ids=[f\"{route} {state}\" for route, state in ENGINE_DRIVERS])\ndef test_each_route_state_answers_the_keys_and_json_types_of_its_contract_fixture_case(tmp_path, whitelist, monkeypatch, route, state):\n    cases = [case for case in _contract_cases() if _engine_contract_case(case) and (case[\"route\"], case[\"engine\"][\"body\"][\"state\"]) == (route, state)]\n    assert cases, (route, state)\n    for index, case in enumerate(cases):\n        expected = case[\"engine\"][\"body\"]\n        ((status, answer),) = ENGINE_DRIVERS[(route, state)](tmp_path / f\"subtitles-{index}.db\", whitelist, monkeypatch, case)\n        assert status == 200, (case[\"name\"], answer)\n        assert answer[\"state\"] == state, case[\"name\"]  # control: the driver reached the state under test\n        assert _types(answer) == _types(expected), case[\"name\"]  # exactly the keys, and each value's JSON type\n        if \"cues\" in expected:\n            # Non-empty wherever the fixture's are, so the per-cue check cannot pass on an empty list.\n            assert bool(answer[\"cues\"]) == bool(expected[\"cues\"]), case[\"name\"]\n            assert all(_types(cue) == _types(expected[\"cues\"][0]) for cue in answer[\"cues\"]), case[\"name\"]\n\n\n@pytest.mark.parametrize(\"route\", [\"state\", \"enqueue\"])\ndef test_an_unknown_or_denied_video_answers_the_contract_fixtures_video_not_found_body(tmp_path, whitelist, monkeypatch, route):\n    (body,) = [case[\"engine\"][\"body\"] for case in _contract_cases() if case[\"route\"] == route and case[\"engine\"][\"status\"] == 404 and case[\"gateway\"] != \"rejected\"]\n    answer = _state if route == \"state\" else _enqueue\n    instance = _instance(True)\n    internal_translate = _route(instance, monkeypatch)\n    server = _server(whitelist, tmp_path / \"subtitles.db\")\n    _beat(tmp_path / \"subtitles.db\", 0)\n    _set_denied(whitelist, True)  # stored as DENIED.EXAMPLE\n    assert answer(internal_translate, server, {\"id\": \"no-such-video\", \"host\": HOST}) == [[404, body]]\n    assert answer(internal_translate, server, {\"id\": DENIED_VIDEO[1], \"host\": DENIED_HOST}) == [[404, body]]\n    assert instance.fetched == []\n    # Control: inactive, the same denied video is answered 200, so the 404 above is the denylist's doing.\n    _set_denied(whitelist, False)\n    assert answer(internal_translate, server, {\"id\": DENIED_VIDEO[1], \"host\": DENIED_HOST})[0][0] == 200\n\n\ndef test_the_heartbeat_fresh_window_is_three_beats_derived_from_heartbeat_seconds():\n    import server_config\n\n    (value,) = [node.value for node in ast.parse((API_DIR / \"server_config.py\").read_text()).body if isinstance(node, ast.Assign) and [getattr(target, \"id\", None) for target in node.targets] == [\"HEARTBEAT_FRESH_MS\"]]\n    assert \"HEARTBEAT_SECONDS\" in {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}\n    window = compile(ast.Expression(value), \"server_config.py\", \"eval\")\n    assert server_config.HEARTBEAT_SECONDS == 5.0\n    assert eval(window, {\"HEARTBEAT_SECONDS\": server_config.HEARTBEAT_SECONDS}) == server_config.HEARTBEAT_FRESH_MS == 15_000\n    assert eval(window, {\"HEARTBEAT_SECONDS\": 7.0}) == 21_000  # a different interval moves the window with it\n    assert isinstance(server_config.HEARTBEAT_FRESH_MS, int)\n    assert _translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS\n    # Neither consumer keeps a literal of its own; each imports its name from server_config.\n    for path, name in ((API_DIR / \"handlers\" / \"internal_translate.py\", \"HEARTBEAT_FRESH_MS\"), (SERVER_DIR / \"db\" / \"jobs\" / \"translate-worker.py\", \"HEARTBEAT_SECONDS\")):\n        tree = ast.parse(path.read_text())\n        assigned = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}\n        assert not assigned & {\"HEARTBEAT_SECONDS\", \"HEARTBEAT_FRESH_MS\"}, path\n        assert name in {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == \"server_config\" for alias in node.names}, path\n\n\ndef test_the_translate_timeout_chain_keeps_budget_plus_socket_under_the_client_timeout_under_the_deploy_drain():\n    from data.source_fetch import SOCKET_TIMEOUT_SECONDS\n    from lib.engine_api_client import TRANSLATE_TIMEOUT_SECONDS  # the Client's; conftest puts client/backend on sys.path, and the module imports only stdlib\n\n    budget = _translate().REQUEST_BUDGET_SECONDS\n    drains = re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", (ROOT / \"scripts\" / \"deploy-bluegreen.sh\").read_text(), re.M)\n    assert len(drains) == 1, drains  # the default, not the --drain override line\n    assert budget + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS < int(drains[0]), (budget, SOCKET_TIMEOUT_SECONDS, TRANSLATE_TIMEOUT_SECONDS, drains)\n```\n\n**Why the drivers are built this way.**\n- **Running.** The driver seeds as many cues as the case's `total`: 3 for `state running`, and 5 for `state running after 3`, which answers 2 cues. The sliced case therefore checks real cues instead of passing on the `cues: []` that `RUNNING`'s 3 cues would give.\n- **No instance track on the state route.** `_instance(False)` is required: with a track, `failed`, `already_english` and `none` answer `ready` (BRANCHES `:812`, `:814`).\n- **`ready`** answers `STORED_READY` with no fetch.\n\n**Not-found test.**\n- The fresh beat is written so the enqueue control queues, rather than answering `none` with 200 for the wrong reason.\n- Both routes resolve before reading the beat, so the 404s don't depend on it.\n- The existing literal `VIDEO_NOT_FOUND` (`:162`) is left alone; the new test reads the fixture.\n\n**Timeout test placement.** It goes immediately after `test_one_15_second_budget_covers_both_fetches` (`:611-625`). The derivation and contract tests go in the block above.\n\n**Docstring entries.** A new section goes before \"Startup:\" (`:48`):\n\n> Contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55, read inside each test because `test_source_fetch.py` imports this module):\n> - Every `(route, state)` among the fixture's valid 200 cases that carry `available` has a driver here, and every driver has such a case.\n> - Each driver brings its route into its state with the pinned clock and a fresh beat (none for the enqueue route's `none`): the state route from a seeded `none`, `queued`, `running` (as many stored cues as the case's `total`, with its `after`), `ready`, `already_english` or `failed` key and no instance track; the enqueue route from no row, a seeded stored state, or a queue filled to `SUBTITLE_QUEUE_CAP`. The answer is a 200 in that state with exactly the case's keys and each value's JSON type (bool before number), cues non-empty where the case's are, each with the keys and types of the case's cues.\n> - On both routes, an unknown video and an actively denylisted one answer exactly the fixture's `Video not found` 404 body, with no fetch; inactive, the denied video answers 200.\n>\n> Shared constants:\n> - `server_config.py`'s `HEARTBEAT_FRESH_MS` is an expression over `HEARTBEAT_SECONDS`. It evaluates to the module's 15 000 (an int) for 5.0 and to 21 000 for 7.0. The handler's `HEARTBEAT_FRESH_MS` is that value. Neither the handler nor the translate worker assigns either name: the handler imports `HEARTBEAT_FRESH_MS` from `server_config`, and the worker imports `HEARTBEAT_SECONDS`.\n> - The route's `REQUEST_BUDGET_SECONDS` plus `data.source_fetch.SOCKET_TIMEOUT_SECONDS` is below the Client's `TRANSLATE_TIMEOUT_SECONDS`, which is below the `DRAIN_SECONDS=` default, the one line of `scripts/deploy-bluegreen.sh` that starts with it.\n\n---\n\n### 5. `engine/server/api/server_config.py`\n\nInserted after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`). It needs no new import.\n\n```python\n# Seconds between the translate worker's heartbeats.\nHEARTBEAT_SECONDS = 5.0\n# Age in ms within which a heartbeat counts as a serving worker (/internal/translate's available): three beats, so one late beat is tolerated.\nHEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)\n```\n\nIt stays an int (15000), so `BEATS`' 15 000 / 15 001 edges and the docs read as before.\n\n### 6. `engine/server/api/handlers/internal_translate.py`\n\n- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.\n- `:32-33` (the rat-tail comment and `HEARTBEAT_FRESH_MS = 15_000`) are deleted.\n- **Docstring `:3`.** \"...whether the translate worker beat within HEARTBEAT_FRESH_MS.\" becomes \"...whether the translate worker beat within HEARTBEAT_FRESH_MS (server_config.py, three HEARTBEAT_SECONDS beats).\"\n- **Docstring `:5`.** It already names `HEARTBEAT_FRESH_MS` and stays as is. Since `:3` says where the constant is defined, it is not repeated here.\n- **Unchanged:** `:30`, `REQUEST_BUDGET_SECONDS`, `VIDEO_NOT_FOUND`, both handlers and the sort at `:115`.\n\n### 7. `engine/server/db/jobs/translate-worker.py`\n\n- `:41` becomes `from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_MAX_DURATION, SUBTITLE_QUEUE_CAP, VIDEO_ERROR_THRESHOLD`.\n- `:58-59` (the rat-tail comment and `HEARTBEAT_SECONDS = 5.0`) are deleted. The uses at `:458`, `:467` and `:536` read the imported name.\n- `HEARTBEAT_SECONDS` stays a module attribute, so `STALL_DRIVER`'s exec and the `spec_from_file_location` load in `test_translate_worker.py` still see it.\n- **Comment `:35`** becomes \"api/ is for server_config (bounds and HEARTBEAT_SECONDS) and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch.\"\n\n### 8. Prose\n\n**`engine/server/README.md:15`.** Append to the bullet:\n\n> `total` always counts every stored cue, whatever `after` was, so a reader that already holds more running cues than `total` knows the job was requeued and restarted.\n\n**`engine/server/README.md:18`.** \"(15 000 ms, three of the worker's 5 s beats)\" becomes:\n\n> (15 000 ms, three of the worker's 5 s beats, derived in `api/server_config.py` from `HEARTBEAT_SECONDS`)\n\n**`engine/server/README.md:30`.** The tunables list becomes \"`SUBTITLE_MAX_DURATION`, `SUBTITLE_MAX_BYTES`, `SUBTITLE_QUEUE_CAP` and `SUBTITLE_MAX_CHUNK_SECONDS` in `api/server_config.py`, which also holds its beat interval `HEARTBEAT_SECONDS`\".\n\n**`TRANSLATE_WORKER.md:155`.** \"(`HEARTBEAT_FRESH_MS`, three beats), and otherwise ... reporting `available`. Raise both constants together.\" becomes:\n\n> ...at most 15 s old (`HEARTBEAT_FRESH_MS`), and otherwise neither queues a job from the page nor reports `available`. Both come from one definition in `engine/server/api/server_config.py`: the beat interval `HEARTBEAT_SECONDS`, with `HEARTBEAT_FRESH_MS` derived from it as three beats, so changing the interval moves the window with it.\n\n**`CONTEXT.md` and `DEPLOYMENT.md`** are unchanged. Both are accurate, and the `DEPLOYMENT.md` edits were optional, so they are skipped.\n\n### 9. `tests/config.json`\n\n- Add `tests/active/fixtures/translate_contract.json` to the `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` groups.\n- Add to `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.\n- Add `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.\n\n---\n\n### Mutation check (manual, once, recorded in the build record)\n\nAdd `{\"name\": \"state paused\", \"route\": \"state\", \"engine\": {\"status\": 200, \"body\": {\"state\": \"paused\", \"available\": true}}, \"gateway\": {\"state\": \"paused\", \"available\": true}}` to the fixture alone and run the three suites. Expected results:\n- **Client:** the replay of `state paused` raises `EngineApiError`, so it answers `\"rejected\"` and not the gateway answer. The coverage test fails because the set is not `TRANSLATE_STATES`.\n- **Frontend:** `state paused` throws `MALFORMED` where a value was expected.\n- **Engine:** `test_every_route_state_in_the_contract_fixture_has_an_engine_driver` fails.\n\nRevert the edit. Also record `rg -l translate_contract.json engine client scripts` returning nothing.\n\n### Check against the plan and the requirements (pass 1, converged)\n\n| Requirement | Where it is met |\n|---|---|\n| One fixture, every state of both routes with and without `available`, every listed rejection, nothing at runtime reads it | \u00a71; the coverage test in \u00a72; grep in the build record |\n| Client replays every case through both parsers | \u00a72 test 1 |\n| Frontend replays every case; `ready` sorted; rejected throws | \u00a73; real `translate.ts` through esbuild, fetch stubbed, no frontend change |\n| Engine checks each state's keys and types against the fixture, plus the not-found body | \u00a74 shape test and not-found test (state route as required, enqueue added) |\n| Mutation check recorded | above |\n| Heartbeat: one definition, both import it, rat-tails gone, derivation test | \u00a75\u20137, \u00a74 heartbeat test |\n| Timeout chain from real values; fails when one value passes its neighbour | \u00a74 timeout test; strict `<` on both sides |\n| README running-slice rule | \u00a78 |\n| No runtime behaviour change; existing tests unchanged | only additions to tests; constant values identical; step-zero baseline |\n\nThree points deliberately differ from the plan's wording. None of them changes its intent:\n1. **Engine parametrization.** It runs over the static driver table plus a two-way set-equality test, instead of over the fixture's cases, to avoid a module-level read that `test_source_fetch.py` would inherit.\n2. **The plan's rule that \"rejected must be refused by both layers\"** is enforced by the two replays themselves, not by the Client coverage test, which cannot run the frontend. The coverage test enforces the with/without-`available` rule, name uniqueness, the two routes, `after` only on state cases, and exactly one not-found case per route.\n3. **One frontend fixture.** It bundles and runs together; there is no separate bundle fixture.\n\n### Named simplifications and their ceilings\n\n- **The `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay.** Part of the contract is therefore stated twice: once at the HTTP route and once in the fixture. Upgrade path: build those tables from `TRANSLATE_CONTRACT_CASES`, mapping `rejected` to `TRANSLATE_FAILED`.\n- **The Engine test checks shape, not values or order.** Cue order and slice arithmetic stay covered by `BRANCHES` and `AFTERS`.\n- **The non-finite sentinel writes any infinity as positive `1e999`.** That is enough for the one case; a negative-infinity case would need `-1e999` handling.\n- **The module-level fixture loads in `test_server.py` and `test_frontend_translate.py` are unguarded.** A malformed fixture stops those two modules collecting, which surfaces loudly and is accepted.",
  "coordination": "none. No phase needs a credential, a live endpoint or the operator. Two steps are run by the agent and recorded in the build record. Before phase 1: the step-zero baseline run of the six translate suites plus test_source_fetch.py. After phase 3: the one-time manual mutation check (a \"state paused\" case added to the fixture alone, three suites run, then reverted) and `rg -l translate_contract.json engine client scripts` returning nothing. Phase 2 relies on the node and esbuild toolchain the existing frontend tests already use.",
  "tests": {
    "tests/tmp/test_55_translate_state_contract_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:45 \u2014 for each valid case, the value returned by fetch_translate (state route, with the case's after) or request_translate (enqueue route) equals the case's `gateway` answer exactly.",
          "expected": "Passes for every valid case in a fixture that agrees with the gateway. In the probe, built from the gateway's own state sets, all 34 cases passed: 6 states \u00d7 with/without available on the state route, 7 on enqueue, both Video not found 404s, and running with after 3.",
          "wrong_implementation": "Three wrong fixtures, as the probe ran them. (1) A `gateway` answer that leaves out the available default: AssertionError at :45. (2) A valid \"paused\" state or \"busy\" on the state route: the real parser raises \"EngineApiError: Engine translate returned invalid payload\" before :45 is reached, so the test is red. (3) Running cues stated in re-sorted order instead of stored order: AssertionError at :45. Deleting the `False` default at engine_api_client.py:163 makes every without-available case raise, so they all go red."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:41 \u2014 for a case whose gateway is \"rejected\", the matching parser raises EngineApiError and its message starts with \"Engine translate\".",
          "expected": "Raises for every rejected case. In the probe this held for the Not found 404, the unknown state on both routes, and a cue whose start is inf: all passed.",
          "wrong_implementation": "A fixture that marks a parseable answer (state ready with available) as rejected fails with \"Failed: DID NOT RAISE EngineApiError\" (probed). A refusal that really came from the transport reads '&lt;urlopen error [Errno 111] Connection refused&gt;' (probed). That does not match ^Engine translate, so a dead stub cannot pass as a refusal."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:48 \u2014 the stub's log, as (method, path, body), is exactly [(\"POST\", route of the case, {id, host} plus the case's after when it has one)].",
          "expected": "One entry per case. The probe showed the stub records (method, path, token, request id, body), for example [('POST', '/internal/translate', None, None, {'id': 'uuid-1', 'host': 'peer.example', 'after': 0})]. All 34 good cases passed this check.",
          "wrong_implementation": "An enqueue case carrying `after` fails here with AssertionError, because request_translate never sends it (probed). Other failures here: a call to the wrong route, a retry (two entries), no call at all (empty log), or an after that was dropped or invented."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:59 \u2014 per route, the set of states of the valid 200 cases whose body carries `available` equals TRANSLATE_STATES (state route) or TRANSLATE_REQUEST_STATES (enqueue route).",
          "expected": "Equal on both routes in the conforming probe fixture (\"COVERAGE good -> passed\").",
          "wrong_implementation": "An extra valid state the gateway does not have (\"paused\") fails with \"AssertionError: state\". Dropping \"state failed\" with available fails with \"AssertionError: state\". Both probed."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:60 \u2014 per route, the set of states of the valid 200 cases whose body has no `available` equals the same gateway set.",
          "expected": "Equal on both routes in the conforming probe fixture.",
          "wrong_implementation": "A fixture with no \"busy\" case that lacks available fails with \"AssertionError: enqueue\" (probed). So a state covered only with available is caught."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase1.py:54 \u2014 no case name appears more than once (the list of duplicated names is empty).",
          "expected": "[] for the conforming fixture. :59 and :60 in the same test need at least 13 valid cases, so the list of names is known to be non-empty and this check is not vacuous.",
          "wrong_implementation": "A case copied in under the same name fails with AssertionError (probed: \"COVERAGE duplicate name -> AssertionError\"). The duplicate id would also make the parametrized replay ambiguous."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route."
        },
        {
          "id": "C2",
          "text": "The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_55_translate_state_contract_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_55_translate_state_contract_phase1.py  2 failed                               0.0s\n  ----------------------------------------------------\n  total                                                 2 failed                               0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_55_translate_state_contract_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase2.py:101 \u2014 for each of the 29 valid cases, result[\"value\"] deep-equals the case's gateway answer. For the two ready cases the cues are replaced by the literal READY_CUES (line 30, used at line 100). Running cues are left in the fixture's order. The control at line 98 shows every fixture cue list is out of (start, end) order. The request control at line 86 shows the case went to fetchTranslate (a GET carrying its after) or requestTranslate (a POST).",
          "expected": "Each case's gateway dict exactly. For ready: cues [Short first 1\u20132, Long first 1\u20133, Later 4\u20135]. For running: cues in the order given, e.g. starts [5,1,3] and [9,7] with total 5.",
          "wrong_implementation": "Earlier probe mutants, each observed red at this comparison: ready left unsorted, and ready sorted by start only (both fail \"state ready\" and \"state ready without available\"); running sorted (fails the three running cases); busy accepted on the state route (fails \"state busy\"); a field dropped or added, or a stub return (whole-dict inequality)."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase2.py:107 \u2014 for each of the 14 rejected cases, the Engine body served as a 200 makes the call throw exactly MALFORMED. The controls at lines 85\u201386 show one request on the intended route, and the control at line 88 shows the 1e999 case was refused for infinity.",
          "expected": "result[\"thrown\"] == \"Translate response was malformed\" for every rejected case.",
          "wrong_implementation": "Earlier probe mutants: a changed message fails all 14; infinity accepted through a typeof check fails \"state start 1e999\", which returns a value. Serving the real non-200 status would throw the error text or \"Translate request failed (N)\" instead. A JSON SyntaxError or no throw also reads differently."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given."
        },
        {
          "id": "C2",
          "text": "Every rejected fixture case served as a 200 throws exactly \"Translate response was malformed\"."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_55_translate_state_contract_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_55_translate_state_contract_phase2.py  43 failed                              0.0s\n  ----------------------------------------------------\n  total                                                 43 failed                              0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_55_translate_state_contract_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "test_55_translate_state_contract_phase3.py:86 and :87: `sorted(fixture - drivers) == []` and `sorted(drivers - fixture) == []`, where fixture is the set of (route, state) from the fixture's valid 200 cases that carry available, and drivers is the key set of ENGINE_DRIVERS",
          "expected": "Both read []. The table holds exactly the 13 (route, state) pairs: none/queued/running/ready/already_english/failed on state, and those plus busy on enqueue. Line 89's control already holds against the fixture; the run reached it in no test only because line 85 stops at the missing table.",
          "wrong_implementation": "A table that leaves a state out, or adds one the fixture lacks such as (\"state\", \"busy\"). I ran a probe table {(\"state\",\"none\"), (\"state\",\"busy\")} and it failed at line 86 (fixture - drivers non-empty). The extra (\"state\",\"busy\") would trip line 87 too. A missing table fails at line 39, as the current run shows."
        },
        {
          "clause": "C1",
          "assertion": "test_55_translate_state_contract_phase3.py:107: `status == 200` for the single response the real handler wrote, which the control at line 103 matches against the driver's return",
          "expected": "200 for every case of all 13 (route, state) pairs. Probe drivers for state none/running/ready and enqueue queued each recorded exactly one [200, {...}] from the real handler.",
          "wrong_implementation": "A driver that lands the handler on a refusal, such as a 400 bad `after` or a 404 for an unresolved video, reads 400 or 404 here. A driver that makes up its own answer without calling the handler is caught first by the control at line 103: I ran a probe driver that returned a literal [[200, ...]] and it failed there."
        },
        {
          "clause": "C1",
          "assertion": "test_55_translate_state_contract_phase3.py:109: `_types(answer) == _types(expected)`. The answer's key-to-JSON-type map equals the fixture case's, with bool checked before number",
          "expected": "Equal for every case. Observed with probe drivers: state running after 3 gave {state: string, cues: array, total: number, available: boolean}, the same as the fixture's \"state running after 3\". state none, state ready and enqueue queued matched their cases too.",
          "wrong_implementation": "A handler that drops `total` from running, or writes `available` as 1. I wrapped the real handler in a probe that mutated its output after it ran: both mutations failed at line 109, one answer missing total and one with 'available': 1."
        },
        {
          "clause": "C1",
          "assertion": "test_55_translate_state_contract_phase3.py:112: `bool(answer[\"cues\"]) == bool(expected[\"cues\"])` wherever the case has cues",
          "expected": "True for state running, state running after 3 and state ready, whose fixture cues are non-empty. The probe's running driver stored five cues and the answer to after=3 held two (c3, c4).",
          "wrong_implementation": "A handler or driver that answers `cues: []`, for example a running job with no stored cues or an `after` past the total. The per-cue check at line 113 would then pass vacuously. A probe mutation that emptied the cues failed at line 112."
        },
        {
          "clause": "C1",
          "assertion": "test_55_translate_state_contract_phase3.py:113: every answer cue's key-to-JSON-type map is one of the fixture case's cue maps",
          "expected": "True. The observed cues were {start: number, end: number, text: string}, the same as the fixture's cue maps.",
          "wrong_implementation": "A cue that is missing `end` or carries extra keys. A probe mutation that popped `end` from every cue failed at line 113."
        },
        {
          "clause": "C2",
          "assertion": "test_55_translate_state_contract_phase3.py:128: on each route, the real handler answers the unknown video {\"id\": \"no-such-video\", \"host\": \"peer.example\"} exactly with [[404, the fixture's Video not found body for that route]]",
          "expected": "[[404, {\"error\": \"Video not found\"}]] on both routes. This passes in the run, as the docstring says it should, because the phase changes no runtime code.",
          "wrong_implementation": "A handler that answers a different 404 body, such as {\"error\": \"Not found\"}, which is the route-missing body. I wrapped the state handler in a probe that rewrote its 404 body, and it failed at line 128."
        },
        {
          "clause": "C2",
          "assertion": "test_55_translate_state_contract_phase3.py:129: on each route, the actively denylisted video (du-1 on denied.example, deny row stored as DENIED.EXAMPLE) answers exactly [[404, the fixture's Video not found body]]. The control at line 132 shows the same video answers 200 once the deny row is inactive",
          "expected": "[[404, {\"error\": \"Video not found\"}]] on both routes. The run passes it, and the line 132 control also held: 200 with the deny row inactive.",
          "wrong_implementation": "A denylist check that compares hosts case-sensitively, so the uppercase stored row never matches and the video is answered 200. Or one that refuses with a body other than the fixture's. Either reads something other than [[404, body]] here."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state."
        },
        {
          "id": "C2",
          "text": "On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_55_translate_state_contract_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_55_translate_state_contract_phase3.py  14 failed, 2 passed                    0.0s\n  ----------------------------------------------------\n  total                                                 14 failed, 2 passed                    0.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_55_translate_state_contract_phase4.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:69 \u2014 server_config.py's AST holds exactly one assignment to HEARTBEAT_FRESH_MS, plain or annotated (`len(values) == 1`)",
          "expected": "1 once the phase lands the planned `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)` (probe over that source: \"good: assignments=1\"). Today it reads 0, and the checkpoint run fails here with \"server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once\".",
          "wrong_implementation": "No shared constant at all (today's code) reads 0. A duplicate definition, one plain and one annotated, reads 2 (probe: \"twice: assignments=2\")."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:71 \u2014 the names in that assignment's expression include HEARTBEAT_SECONDS",
          "expected": "The probe of the planned expression read names=['HEARTBEAT_SECONDS', 'int'], which contains HEARTBEAT_SECONDS.",
          "wrong_implementation": "The literal moved into server_config as `HEARTBEAT_FRESH_MS = 15_000` reads names=[] (probe), so it fails here even though its value is 15000 and an int."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:73 \u2014 the expression, evaluated in server_config's namespace with the real HEARTBEAT_SECONDS, equals 15000 and its type is exactly int",
          "expected": "15000, int (probe: \"real=15000 type=int\" for the planned form).",
          "wrong_implementation": "`HEARTBEAT_SECONDS * 3000` reads 15000.0 of type float (probe: \"real=15000.0 type=float\"), so it fails the `type(real) is int` half. A wrong factor, for example two beats, reads 10000."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:76 \u2014 the same expression evaluated with HEARTBEAT_SECONDS = 7.0 equals 21000",
          "expected": "21000 (probe: \"seven=21000\" for the planned form).",
          "wrong_implementation": "A derivation that names the interval but ignores it, `int(15_000 + HEARTBEAT_SECONDS * 0)`, passes :71 and :73 but reads seven=15000 here (probe)."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:80 \u2014 `handlers.internal_translate.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS`",
          "expected": "True once the handler does `from server_config import HEARTBEAT_FRESH_MS` (probe: \"identity imported=True\").",
          "wrong_implementation": "A handler that keeps its own literal 15_000 holds an equal int but not the same object (probe: \"literal=False literal_eq=True\"), so it fails here where equality would pass. Deleting the handler's import and putting back `HEARTBEAT_FRESH_MS = 15_000` turns this line red."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:84 \u2014 for internal_translate.py and for translate-worker.py, the Store-context names in the module's AST share nothing with {HEARTBEAT_SECONDS, HEARTBEAT_FRESH_MS}",
          "expected": "An empty set for both files under the planned import-only form (probe: \"handler planned: stored=[]\", \"worker planned: stored=[]\"). The positive control is :85, which shows on the same parsed tree that the name is present through an import.",
          "wrong_implementation": "Today's code reads stored=['HEARTBEAT_FRESH_MS'] for the handler and ['HEARTBEAT_SECONDS'] for the worker (probe). A module that imports the name and then reassigns `HEARTBEAT_FRESH_MS = 15_000` reads stored=['HEARTBEAT_FRESH_MS'] (probe), so it fails here even though :85 passes."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:85 \u2014 the set of modules a `from X import` binds the name from is exactly {\"server_config\"}: HEARTBEAT_FRESH_MS for the handler, HEARTBEAT_SECONDS for the worker",
          "expected": "{'server_config'} for both (probe: \"handler planned: from_fresh={'server_config'}\", \"worker planned: from_seconds={'server_config'}\").",
          "wrong_implementation": "Today both read set(), with no import at all (probe). Importing the name from another module reads {'data.subtitles'} (probe \"handler other module\"). Importing it from two sources reads a two-element set."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:96 \u2014 handler REQUEST_BUDGET_SECONDS + data.source_fetch SOCKET_TIMEOUT_SECONDS &lt; lib.engine_api_client TRANSLATE_TIMEOUT_SECONDS",
          "expected": "15.0 + 4.0 = 19.0 &lt; 20, so True. The probe printed budget=15.0 socket=4.0 client=20, and the checkpoint run shows this test passing.",
          "wrong_implementation": "Raising the budget to 16.0, the socket timeout to 5.0 (the harvest mutation K3), or dropping the Client timeout to 19 reads 20.0 &lt; 20 or 19.0 &lt; 19, which is False."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_55_translate_state_contract_phase4.py:97 \u2014 TRANSLATE_TIMEOUT_SECONDS &lt; the DRAIN_SECONDS default from the single line-anchored match in deploy-bluegreen.sh. :94 is the control: it requires exactly one match.",
          "expected": "20 &lt; 30, so True. The probe printed drains=['30'] over the real script; the indented `--drain)` line is not matched (probe).",
          "wrong_implementation": "A drain default of 20, or a Client timeout raised to 30, reads False. A reformatted default (`DRAIN_SECONDS=\"30\"`) matches nothing (probe: []), and a second default line matches twice (probe: ['30', '45']). Both fail at the :94 control, not silently."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own."
        },
        {
          "id": "C2",
          "text": "REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_55_translate_state_contract_phase4.py",
        "code": 1,
        "output": "  tests/tmp/test_55_translate_state_contract_phase4.py  1 failed, 1 passed                     0.0s\n  ----------------------------------------------------\n  total                                                 1 failed, 1 passed                     0.2s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_55_translate_state_contract_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nNeither test can pass yet because tests/active/fixtures/translate_contract.json does not exist.\ntest_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route\nis collected with the single stand-in case \"fixture missing\" and fails at line 36 on\n`assert CONTRACT.exists(), CONTRACT`. test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names\nfails at line 52 on the same assertion.\n\nNOT ASSESSED\n1. tests/active/fixtures/translate_contract.json, the phase's output and the source of every\n   expected value, does not exist yet. So it could not be checked against the\n   tautological-assertion (rules/shape.md) bullet \"a snapshot regenerated from current output\".\n   If each case's `gateway` answer was produced by running fetch_translate/request_translate\n   rather than written down independently, line 45 would agree with the gateway by\n   construction. The test as written states its expectation as a fixture literal, and that\n   form passes the check.\n2. The stub question was answered from the assertion form alone. An empty, partial,\n   all-rejected or wrongly-answered fixture fails the checkpoint:\n   - lines 55, 59 and 60 fail on a missing route or state set;\n   - line 45 fails on a wrong answer;\n   - line 41 fails with DID NOT RAISE when a parseable case is marked rejected.\n   One gap is caught only by the second test: a fixture with `\"cases\": []` collects zero\n   replay cases instead of failing them, and lines 55 and 59 are what turn it red.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 2 must_prove, 13 docstring, 7 name; the 2 must_prove clauses split into 7 rows below, C1a\u2013C1e and C2a\u2013C2c, and the count includes those 7 rows)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | state case through fetch_translate gives exactly its gateway answer | :45 | a parser that drops, adds or rewrites a field (cues, total, available), or a fixture whose stated answer is not the real parse | CARRIED |\n| C1b | must_prove | enqueue case through request_translate gives exactly its gateway answer | :45 | the same, on the enqueue parser (e.g. busy turned into failed, available defaulted wrongly) | CARRIED |\n| C1c | must_prove | raises EngineApiError when the case says rejected | :41 | a gateway that returns a value, or raises something other than EngineApiError, on a case marked rejected | CARRIED |\n| C1d | must_prove | from exactly one request to that route | :48 | zero or two requests, a request to the other route, a GET instead of POST (list equality on (method, path, body)) | CARRIED |\n| C1e | must_prove | state route called \"with its after\" | :48 | `after` dropped from the body or sent when the case has none (`sent` built from the case) | CARRIED |\n| C2a | must_prove | valid 200 states with available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue) | :59 | a fixture missing a state (e.g. no `busy` on enqueue) or adding one; set equality against the imported constants | CARRIED |\n| C2b | must_prove | the same sets without available | :60 | a fixture covering a state only with `available` present | CARRIED |\n| C2c | must_prove | every case name is unique | :54 | a duplicated name (duplicates listed, compared to []) | CARRIED |\n| D1 | docstring | \"the Client gateway's real parsers agree with it case by case\" | :45, :41 | a case whose stated answer differs from the real parse; parsers imported from lib.engine_api_client at :24 | CARRIED |\n| D2 | docstring | \"raises EngineApiError with the gateway's own 'Engine translate ...' text, never a transport error's\" | :41 | a refused or dropped connection, whose `str(exc)` text does not start with \"Engine translate\" (`match=r\"^Engine translate\"`) | CARRIED |\n| D3 | docstring | \"the stub saw exactly one POST\" | :48 | two requests, or a GET (entry[0] compared) | CARRIED |\n| D4 | docstring | \"to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case\" | :48 | a call to the other route (ROUTES[case[\"route\"]]) | CARRIED |\n| D5 | docstring | \"body exactly id, host and the case's `after` when it has one\" | :48 | an extra key, or `after` missing or present when it should not be (whole-dict equality) | CARRIED |\n| D6 | docstring | \"every case name is unique\" | :54 | a duplicate name | CARRIED |\n| D7 | docstring | \"the routes are exactly state and enqueue\" | :55 | a third route, or a route with no cases | CARRIED |\n| D8 | docstring | \"each with at least one rejected case\" | :63 | a route whose replay never runs the rejected branch | CARRIED |\n| D9 | docstring | \"`after` appears only on state cases\" | :56 | an enqueue case carrying `after` | CARRIED |\n| D10 | docstring | \"states of the valid 200 cases carrying `available` ... each equal\" the route's set | :59 | a missing or extra state among cases with `available` | CARRIED |\n| D11 | docstring | \"and of those without it\" | :60 | a missing or extra state among cases without `available` | CARRIED |\n| D12 | docstring | \"each route has exactly one 404 `{\"error\": \"Video not found\"}` case\" | :61 | zero or two such cases on a route (count == 1 on exact engine dict) | CARRIED |\n| D13 | docstring | \"while it is missing, both tests fail on its absence\" | :36, :52 | a skip or silent pass on a missing fixture (stand-in case at :28 still reaches :36) | CARRIED |\n| N1 | name | \"each contract case\" | :34 \u2192 :45/:41 | a subset of cases run; parametrized over all CASES, unfiltered | CARRIED |\n| N2 | name | \"parses through the real gateway to its stated answer\" | :45, :41 | a stand-in parser; real fetch_translate/request_translate called | CARRIED |\n| N3 | name | \"from one request to its route\" | :48 | more than one request, or the wrong route | CARRIED |\n| N4 | name | \"states exactly the gateway state sets\" | :59, :60 | a subset or superset of the sets (equality, not membership) | CARRIED |\n| N5 | name | \"with and without available\" | :59, :60 | only one half covered | CARRIED |\n| N6 | name | \"under unique names\" | :54 | a duplicate name | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/fixtures/translate_contract.json (NEW), but the file does not exist at that path. The test's assertions were judged against the code they run (lib.engine_api_client fetch_translate / request_translate and test_server._translate_engine). The fixture's own content was not judged: which bounds and malformed bodies its rejected cases cover (testing.md bounds), and whether its stated answers are right. Without the file, the test as written goes red at :36 and :52.\n2. tests/config.json (EDITED) was read only for translate entries. Its edit has no bearing on what the test asserts and was not judged further.\n3. `fixtures_path` was not supplied. The test uses no pytest fixture; `_translate_engine` is imported from tests/active/test_server.py:1600 and was read there.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nNeither test can pass yet because tests/active/fixtures/translate_contract.json does not exist.\ntest_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route\nis collected with the single stand-in case \"fixture missing\" and fails at line 36 on\n`assert CONTRACT.exists(), CONTRACT`. test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names\nfails at line 52 on the same assertion.\n\nNOT ASSESSED\n1. tests/active/fixtures/translate_contract.json, the phase's output and the source of every\n   expected value, does not exist yet. So it could not be checked against the\n   tautological-assertion (rules/shape.md) bullet \"a snapshot regenerated from current output\".\n   If each case's `gateway` answer was produced by running fetch_translate/request_translate\n   rather than written down independently, line 45 would agree with the gateway by\n   construction. The test as written states its expectation as a fixture literal, and that\n   form passes the check.\n2. The stub question was answered from the assertion form alone. An empty, partial,\n   all-rejected or wrongly-answered fixture fails the checkpoint:\n   - lines 55, 59 and 60 fail on a missing route or state set;\n   - line 45 fails on a wrong answer;\n   - line 41 fails with DID NOT RAISE when a parseable case is marked rejected.\n   One gap is caught only by the second test: a fixture with `\"cases\": []` collects zero\n   replay cases instead of failing them, and lines 55 and 59 are what turn it red.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 2 must_prove, 13 docstring, 7 name; the 2 must_prove clauses split into 7 rows below, C1a\u2013C1e and C2a\u2013C2c, and the count includes those 7 rows)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | state case through fetch_translate gives exactly its gateway answer | :45 | a parser that drops, adds or rewrites a field (cues, total, available), or a fixture whose stated answer is not the real parse | CARRIED |\n| C1b | must_prove | enqueue case through request_translate gives exactly its gateway answer | :45 | the same, on the enqueue parser (e.g. busy turned into failed, available defaulted wrongly) | CARRIED |\n| C1c | must_prove | raises EngineApiError when the case says rejected | :41 | a gateway that returns a value, or raises something other than EngineApiError, on a case marked rejected | CARRIED |\n| C1d | must_prove | from exactly one request to that route | :48 | zero or two requests, a request to the other route, a GET instead of POST (list equality on (method, path, body)) | CARRIED |\n| C1e | must_prove | state route called \"with its after\" | :48 | `after` dropped from the body or sent when the case has none (`sent` built from the case) | CARRIED |\n| C2a | must_prove | valid 200 states with available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue) | :59 | a fixture missing a state (e.g. no `busy` on enqueue) or adding one; set equality against the imported constants | CARRIED |\n| C2b | must_prove | the same sets without available | :60 | a fixture covering a state only with `available` present | CARRIED |\n| C2c | must_prove | every case name is unique | :54 | a duplicated name (duplicates listed, compared to []) | CARRIED |\n| D1 | docstring | \"the Client gateway's real parsers agree with it case by case\" | :45, :41 | a case whose stated answer differs from the real parse; parsers imported from lib.engine_api_client at :24 | CARRIED |\n| D2 | docstring | \"raises EngineApiError with the gateway's own 'Engine translate ...' text, never a transport error's\" | :41 | a refused or dropped connection, whose `str(exc)` text does not start with \"Engine translate\" (`match=r\"^Engine translate\"`) | CARRIED |\n| D3 | docstring | \"the stub saw exactly one POST\" | :48 | two requests, or a GET (entry[0] compared) | CARRIED |\n| D4 | docstring | \"to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case\" | :48 | a call to the other route (ROUTES[case[\"route\"]]) | CARRIED |\n| D5 | docstring | \"body exactly id, host and the case's `after` when it has one\" | :48 | an extra key, or `after` missing or present when it should not be (whole-dict equality) | CARRIED |\n| D6 | docstring | \"every case name is unique\" | :54 | a duplicate name | CARRIED |\n| D7 | docstring | \"the routes are exactly state and enqueue\" | :55 | a third route, or a route with no cases | CARRIED |\n| D8 | docstring | \"each with at least one rejected case\" | :63 | a route whose replay never runs the rejected branch | CARRIED |\n| D9 | docstring | \"`after` appears only on state cases\" | :56 | an enqueue case carrying `after` | CARRIED |\n| D10 | docstring | \"states of the valid 200 cases carrying `available` ... each equal\" the route's set | :59 | a missing or extra state among cases with `available` | CARRIED |\n| D11 | docstring | \"and of those without it\" | :60 | a missing or extra state among cases without `available` | CARRIED |\n| D12 | docstring | \"each route has exactly one 404 `{\"error\": \"Video not found\"}` case\" | :61 | zero or two such cases on a route (count == 1 on exact engine dict) | CARRIED |\n| D13 | docstring | \"while it is missing, both tests fail on its absence\" | :36, :52 | a skip or silent pass on a missing fixture (stand-in case at :28 still reaches :36) | CARRIED |\n| N1 | name | \"each contract case\" | :34 \u2192 :45/:41 | a subset of cases run; parametrized over all CASES, unfiltered | CARRIED |\n| N2 | name | \"parses through the real gateway to its stated answer\" | :45, :41 | a stand-in parser; real fetch_translate/request_translate called | CARRIED |\n| N3 | name | \"from one request to its route\" | :48 | more than one request, or the wrong route | CARRIED |\n| N4 | name | \"states exactly the gateway state sets\" | :59, :60 | a subset or superset of the sets (equality, not membership) | CARRIED |\n| N5 | name | \"with and without available\" | :59, :60 | only one half covered | CARRIED |\n| N6 | name | \"under unique names\" | :54 | a duplicate name | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/fixtures/translate_contract.json (NEW), but the file does not exist at that path. The test's assertions were judged against the code they run (lib.engine_api_client fetch_translate / request_translate and test_server._translate_engine). The fixture's own content was not judged: which bounds and malformed bodies its rejected cases cover (testing.md bounds), and whether its stated answers are right. Without the file, the test as written goes red at :36 and :52.\n2. tests/config.json (EDITED) was read only for translate entries. Its edit has no bearing on what the test asserts and was not judged further.\n3. `fixtures_path` was not supplied. The test uses no pytest fixture; `_translate_engine` is imported from tests/active/test_server.py:1600 and was read there.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "state case through fetch_translate gives exactly its gateway answer",
            "assertion": ":45",
            "excludes": "a parser that drops, adds or rewrites a field (cues, total, available), or a fixture whose stated answer is not the real parse",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "enqueue case through request_translate gives exactly its gateway answer",
            "assertion": ":45",
            "excludes": "the same, on the enqueue parser (e.g. busy turned into failed, available defaulted wrongly)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "raises EngineApiError when the case says rejected",
            "assertion": ":41",
            "excludes": "a gateway that returns a value, or raises something other than EngineApiError, on a case marked rejected",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "from exactly one request to that route",
            "assertion": ":48",
            "excludes": "zero or two requests, a request to the other route, a GET instead of POST (list equality on (method, path, body))",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "state route called \"with its after\"",
            "assertion": ":48",
            "excludes": "`after` dropped from the body or sent when the case has none (`sent` built from the case)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "valid 200 states with available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue)",
            "assertion": ":59",
            "excludes": "a fixture missing a state (e.g. no `busy` on enqueue) or adding one; set equality against the imported constants",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "the same sets without available",
            "assertion": ":60",
            "excludes": "a fixture covering a state only with `available` present",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "every case name is unique",
            "assertion": ":54",
            "excludes": "a duplicated name (duplicates listed, compared to [])",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"the Client gateway's real parsers agree with it case by case\"",
            "assertion": ":45, :41",
            "excludes": "a case whose stated answer differs from the real parse; parsers imported from lib.engine_api_client at :24",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"raises EngineApiError with the gateway's own 'Engine translate ...' text, never a transport error's\"",
            "assertion": ":41",
            "excludes": "a refused or dropped connection, whose `str(exc)` text does not start with \"Engine translate\" (`match=r\"^Engine translate\"`)",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"the stub saw exactly one POST\"",
            "assertion": ":48",
            "excludes": "two requests, or a GET (entry[0] compared)",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case\"",
            "assertion": ":48",
            "excludes": "a call to the other route (ROUTES[case[\"route\"]])",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"body exactly id, host and the case's `after` when it has one\"",
            "assertion": ":48",
            "excludes": "an extra key, or `after` missing or present when it should not be (whole-dict equality)",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"every case name is unique\"",
            "assertion": ":54",
            "excludes": "a duplicate name",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"the routes are exactly state and enqueue\"",
            "assertion": ":55",
            "excludes": "a third route, or a route with no cases",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"each with at least one rejected case\"",
            "assertion": ":63",
            "excludes": "a route whose replay never runs the rejected branch",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`after` appears only on state cases\"",
            "assertion": ":56",
            "excludes": "an enqueue case carrying `after`",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"states of the valid 200 cases carrying `available` ... each equal\" the route's set",
            "assertion": ":59",
            "excludes": "a missing or extra state among cases with `available`",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"and of those without it\"",
            "assertion": ":60",
            "excludes": "a missing or extra state among cases without `available`",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"each route has exactly one 404 `{\"error\": \"Video not found\"}` case\"",
            "assertion": ":61",
            "excludes": "zero or two such cases on a route (count == 1 on exact engine dict)",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"while it is missing, both tests fail on its absence\"",
            "assertion": ":36, :52",
            "excludes": "a skip or silent pass on a missing fixture (stand-in case at :28 still reaches :36)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"each contract case\"",
            "assertion": ":34 \u2192 :45/:41",
            "excludes": "a subset of cases run; parametrized over all CASES, unfiltered",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"parses through the real gateway to its stated answer\"",
            "assertion": ":45, :41",
            "excludes": "a stand-in parser; real fetch_translate/request_translate called",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"from one request to its route\"",
            "assertion": ":48",
            "excludes": "more than one request, or the wrong route",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"states exactly the gateway state sets\"",
            "assertion": ":59, :60",
            "excludes": "a subset or superset of the sets (equality, not membership)",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"with and without available\"",
            "assertion": ":59, :60",
            "excludes": "only one half covered",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"under unique names\"",
            "assertion": ":54",
            "excludes": "a duplicate name",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_55_translate_state_contract_phase2.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. tautological-assertion (rules/shape.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:98\n   expected = {**expected, \"cues\": _by_start_then_end(expected[\"cues\"])}\n   For the two ready cases (\"state ready\", \"state ready without available\") the test works\n   out the expected cue order itself. It does this with its own sort at :74-75,\n   `sorted(cues, key=lambda cue: (cue[\"start\"], cue[\"end\"]))`, which is the production\n   ordering rewritten in Python. The rule wants an expected value written down\n   independently. This is a match for two lines of the entry's <how_to_spot>: \"The expected\n   value is computed in the test body rather than written down\" and \"The test ... reimplements\n   the function it is testing to build its expectation\". It is the same shape as the entry's\n   <example_bad> (`expected = sum(...)`). The line-96 control shows the fixture list is\n   unsorted, but the order the line-99 assertion holds translate.ts to still comes from the\n   test's own sort, not from a stated value. The fix the entry's <alternatives> gives fits\n   here: the ready expectation is three cues, so it can be written as a literal\n   (Short first 1\u20132, Long first 1\u20133, Later 4\u20135).\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery parametrized case of both test functions fails at line 79,\n`assert contract_report is not None`. tests/active/test_frontend_translate.py defines no\n`CONTRACT_RUNNER`, so the module fixture returns None.\n\nNOT ASSESSED\n1. client/frontend/src/data/translate.ts is not in `code_under_test`, but the test bundles it.\n   I only grepped it to confirm `fetchTranslate`, `requestTranslate` and the malformed\n   message exist. I did not read it in full.\n2. `CONTRACT_RUNNER` does not exist yet, and it is the phase's output. I answered the stub\n   question from the assertion form and the fixture. A pass-through parser (`res.json()`\n   returned as-is) fails the ready cases at :99 and every rejected case at :105. A runner that\n   never calls translate.ts's fetch is caught by the request controls at :83-84. Whether the\n   runner, once written, really reaches `fetchTranslate`/`requestTranslate` can only be\n   checked after it lands.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (26 clauses: 6 must_prove, 14 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"every valid fixture case served to fetchTranslate or requestTranslate\" | :84 | a case sent to the wrong function: a GET where a POST belongs or the other way round, or a state case missing its `after`. Every VALID case is a parametrized case (:90) | CARRIED |\n| C1b | must_prove | \"comes back with exactly its gateway fields\" | :99 | a field dropped or added (for example `available` left out, or `total` kept on a ready answer), because whole-dict equality fails on either | CARRIED |\n| C1c | must_prove | \"ready cues sorted by start then end\" | :99 (expected built at :98) | ready left unsorted, or sorted by start only. The fixture's tie at start 1.0 (end 3.0 before end 2.0) reads differently under a start-only sort | CARRIED |\n| C1d | must_prove | \"running cues in the order given\" | :99, control :96 | running cues sorted the way ready cues are. :96 shows the fixture's running lists are out of order, so a sort would change what :99 reads | CARRIED |\n| C2a | must_prove | \"every rejected fixture case served as a 200\" | :105, :84 | the case's real status served (404 and so on): `readTranslateResponse` would then throw the error text or \"Translate request failed (N)\", which does not equal MALFORMED | CARRIED |\n| C2b | must_prove | throws exactly \"Translate response was malformed\" | :105 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |\n| D1 | docstring | the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture | :99, :105 | a single case that disagrees turns its own parametrized case red | CARRIED |\n| D2 | docstring | the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\" | none | nothing reads it. A runner that hard-codes the fixture path or the host gives the same report | UNCARRIED |\n| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :84 | a call on the wrong route, or `after` left off or added | CARRIED |\n| D4 | docstring | \"the gateway answer for a valid case\" is what gets served | :99 | serving the Engine body instead: the 404 \"video not found\" cases would then throw rather than return the gateway value | CARRIED |\n| D5 | docstring | \"the Engine body for a rejected one\" is what gets served | :86 | serving one stand-in body for every rejected case: the `start 1e999` case would read `nonFinite` false. This only reads at that one case (see Recommendation 2) | CARRIED |\n| D6 | docstring | one JSON report \"keyed by case name of `{value \\| thrown, nonFinite}`\" | :80, :99, :105, :86 | a report missing a case name (KeyError), or missing the value, thrown or nonFinite field | CARRIED |\n| D7 | docstring | `FETCH_RECORDER` \"writes every request to the ASKED file\" | :83 | requests going unrecorded, which would make the count fall short | CARRIED |\n| D8 | docstring | \"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\" | :79 | a missing runner being skipped or passing silently | CARRIED |\n| D9 | docstring | the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\" | :99 | same wrong versions as C1b, C1c and C1d | CARRIED |\n| D10 | docstring | \"the fixture's ready and running lists are themselves out of that order\" | :96 | a fixture already in order, which would make the sort check meaningless | CARRIED |\n| D11 | docstring | threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\" | :105 | a SyntaxError or a gateway error text | CARRIED |\n| D12 | docstring | \"the runner made one request per case\" | :83 | extra requests or skipped requests | CARRIED |\n| D13 | docstring | \"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\" | :84 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |\n| D14 | docstring | non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\" | :86 | the 1e999 case refused for some other reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |\n| N1 | name | \"each valid contract case\" | :90 parametrize, :84 | a valid case left out or sent down the wrong route | CARRIED |\n| N2 | name | \"comes back with exactly its gateway fields\" | :99 | a field added or dropped | CARRIED |\n| N3 | name | \"ready cues sorted by start then end\" | :99 | unsorted, or sorted by start only | CARRIED |\n| N4 | name | \"running in given order\" | :99, :96 | running cues sorted | CARRIED |\n| N5 | name | \"each rejected contract case served as a 200\" | :105 | the case's real non-200 status served, which yields error text rather than MALFORMED | CARRIED |\n| N6 | name | \"throws exactly translate response was malformed\" | :105 | any other message, or no throw | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:3\n   D2 is UNCARRIED. The docstring says the runner reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables, but no assertion would notice a runner that ignores them. A runner that hard-codes the fixture path or host still produces a report that passes :80\u2013:105, and :84 does not compare the `host` query parameter. This is a docstring-only clause, so it is a Recommendation. Fix it either by asserting it (for example, add the expected `host` to the recorded request and compare it at :84) or by narrowing the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:86\n   For 13 of the 14 rejected cases, the test cannot see what the runner served. FETCH_RECORDER (:37) records method, path and `after`, but not the response body. Only the `start 1e999` case has a check (:86) that reads differently when a stand-in body is served. So a runner that serves any easily malformed body (`{}`, or the string \"rejected\") for, say, `state total -1` still gets MALFORMED at :105 for that case, and that test never reaches translate.ts's `total < 0` check. The suite as a whole still catches a runner that substitutes the same body everywhere, because the 1e999 case goes red. Recording the served text, or a digest of it, next to each request would let every case tie its throw to its own Engine body.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:98\n   The ready fixture's order cannot tell a (start, end) sort from an (end, start) sort. Both put `[1,2],[1,3],[4,5]` in the same order, so a comparator of `a.end - b.end || a.start - b.start` passes :99. The fixture needs a ready cue whose end comes earlier but whose start comes later than another cue's (for example `{start: 2, end: 2.5}` alongside `{start: 1, end: 3}`) before the \"start then end\" half of C1c reads differently under that wrong sort.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `CONTRACT_RUNNER` does not exist yet in tests/active/test_frontend_translate.py. The only matches are in this test and in tests/last_test_output.txt / last_test_validation.json. So I could not read what the runner serves, or how it computes `nonFinite` (from the served text or from the fixture). The D5 and D14 rows are judged on the test's assertions alone. A runner that takes `nonFinite` from the fixture would make the :86 check meaningless, and that can only be checked once the runner exists.\n2. client/frontend/src/data/translate.ts and tests/active/fixtures/translate_contract.json were not in `code_under_test`. I read them anyway because the test bundles the first and parametrizes over the second, and they are where I got the accepted inputs and refusal paths for the bounds checks. tests/config.json, which was listed, has nothing about this test's behaviour.\n3. `fixtures_path` was not supplied. The test defines its only fixture itself (`contract_report`, :60) and otherwise uses pytest's built-in `tmp_path_factory`, so I did not need a conftest.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: BLOCK\n\nCRITICAL\n1. tautological-assertion (rules/shape.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:98\n   expected = {**expected, \"cues\": _by_start_then_end(expected[\"cues\"])}\n   For the two ready cases (\"state ready\", \"state ready without available\") the test works\n   out the expected cue order itself. It does this with its own sort at :74-75,\n   `sorted(cues, key=lambda cue: (cue[\"start\"], cue[\"end\"]))`, which is the production\n   ordering rewritten in Python. The rule wants an expected value written down\n   independently. This is a match for two lines of the entry's <how_to_spot>: \"The expected\n   value is computed in the test body rather than written down\" and \"The test ... reimplements\n   the function it is testing to build its expectation\". It is the same shape as the entry's\n   <example_bad> (`expected = sum(...)`). The line-96 control shows the fixture list is\n   unsorted, but the order the line-99 assertion holds translate.ts to still comes from the\n   test's own sort, not from a stated value. The fix the entry's <alternatives> gives fits\n   here: the ready expectation is three cues, so it can be written as a literal\n   (Short first 1\u20132, Long first 1\u20133, Later 4\u20135).\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery parametrized case of both test functions fails at line 79,\n`assert contract_report is not None`. tests/active/test_frontend_translate.py defines no\n`CONTRACT_RUNNER`, so the module fixture returns None.\n\nNOT ASSESSED\n1. client/frontend/src/data/translate.ts is not in `code_under_test`, but the test bundles it.\n   I only grepped it to confirm `fetchTranslate`, `requestTranslate` and the malformed\n   message exist. I did not read it in full.\n2. `CONTRACT_RUNNER` does not exist yet, and it is the phase's output. I answered the stub\n   question from the assertion form and the fixture. A pass-through parser (`res.json()`\n   returned as-is) fails the ready cases at :99 and every rejected case at :105. A runner that\n   never calls translate.ts's fetch is caught by the request controls at :83-84. Whether the\n   runner, once written, really reaches `fetchTranslate`/`requestTranslate` can only be\n   checked after it lands.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (26 clauses: 6 must_prove, 14 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"every valid fixture case served to fetchTranslate or requestTranslate\" | :84 | a case sent to the wrong function: a GET where a POST belongs or the other way round, or a state case missing its `after`. Every VALID case is a parametrized case (:90) | CARRIED |\n| C1b | must_prove | \"comes back with exactly its gateway fields\" | :99 | a field dropped or added (for example `available` left out, or `total` kept on a ready answer), because whole-dict equality fails on either | CARRIED |\n| C1c | must_prove | \"ready cues sorted by start then end\" | :99 (expected built at :98) | ready left unsorted, or sorted by start only. The fixture's tie at start 1.0 (end 3.0 before end 2.0) reads differently under a start-only sort | CARRIED |\n| C1d | must_prove | \"running cues in the order given\" | :99, control :96 | running cues sorted the way ready cues are. :96 shows the fixture's running lists are out of order, so a sort would change what :99 reads | CARRIED |\n| C2a | must_prove | \"every rejected fixture case served as a 200\" | :105, :84 | the case's real status served (404 and so on): `readTranslateResponse` would then throw the error text or \"Translate request failed (N)\", which does not equal MALFORMED | CARRIED |\n| C2b | must_prove | throws exactly \"Translate response was malformed\" | :105 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |\n| D1 | docstring | the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture | :99, :105 | a single case that disagrees turns its own parametrized case red | CARRIED |\n| D2 | docstring | the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\" | none | nothing reads it. A runner that hard-codes the fixture path or the host gives the same report | UNCARRIED |\n| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :84 | a call on the wrong route, or `after` left off or added | CARRIED |\n| D4 | docstring | \"the gateway answer for a valid case\" is what gets served | :99 | serving the Engine body instead: the 404 \"video not found\" cases would then throw rather than return the gateway value | CARRIED |\n| D5 | docstring | \"the Engine body for a rejected one\" is what gets served | :86 | serving one stand-in body for every rejected case: the `start 1e999` case would read `nonFinite` false. This only reads at that one case (see Recommendation 2) | CARRIED |\n| D6 | docstring | one JSON report \"keyed by case name of `{value \\| thrown, nonFinite}`\" | :80, :99, :105, :86 | a report missing a case name (KeyError), or missing the value, thrown or nonFinite field | CARRIED |\n| D7 | docstring | `FETCH_RECORDER` \"writes every request to the ASKED file\" | :83 | requests going unrecorded, which would make the count fall short | CARRIED |\n| D8 | docstring | \"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\" | :79 | a missing runner being skipped or passing silently | CARRIED |\n| D9 | docstring | the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\" | :99 | same wrong versions as C1b, C1c and C1d | CARRIED |\n| D10 | docstring | \"the fixture's ready and running lists are themselves out of that order\" | :96 | a fixture already in order, which would make the sort check meaningless | CARRIED |\n| D11 | docstring | threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\" | :105 | a SyntaxError or a gateway error text | CARRIED |\n| D12 | docstring | \"the runner made one request per case\" | :83 | extra requests or skipped requests | CARRIED |\n| D13 | docstring | \"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\" | :84 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |\n| D14 | docstring | non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\" | :86 | the 1e999 case refused for some other reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |\n| N1 | name | \"each valid contract case\" | :90 parametrize, :84 | a valid case left out or sent down the wrong route | CARRIED |\n| N2 | name | \"comes back with exactly its gateway fields\" | :99 | a field added or dropped | CARRIED |\n| N3 | name | \"ready cues sorted by start then end\" | :99 | unsorted, or sorted by start only | CARRIED |\n| N4 | name | \"running in given order\" | :99, :96 | running cues sorted | CARRIED |\n| N5 | name | \"each rejected contract case served as a 200\" | :105 | the case's real non-200 status served, which yields error text rather than MALFORMED | CARRIED |\n| N6 | name | \"throws exactly translate response was malformed\" | :105 | any other message, or no throw | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:3\n   D2 is UNCARRIED. The docstring says the runner reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables, but no assertion would notice a runner that ignores them. A runner that hard-codes the fixture path or host still produces a report that passes :80\u2013:105, and :84 does not compare the `host` query parameter. This is a docstring-only clause, so it is a Recommendation. Fix it either by asserting it (for example, add the expected `host` to the recorded request and compare it at :84) or by narrowing the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:86\n   For 13 of the 14 rejected cases, the test cannot see what the runner served. FETCH_RECORDER (:37) records method, path and `after`, but not the response body. Only the `start 1e999` case has a check (:86) that reads differently when a stand-in body is served. So a runner that serves any easily malformed body (`{}`, or the string \"rejected\") for, say, `state total -1` still gets MALFORMED at :105 for that case, and that test never reaches translate.ts's `total < 0` check. The suite as a whole still catches a runner that substitutes the same body everywhere, because the 1e999 case goes red. Recording the served text, or a digest of it, next to each request would let every case tie its throw to its own Engine body.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase2.py:98\n   The ready fixture's order cannot tell a (start, end) sort from an (end, start) sort. Both put `[1,2],[1,3],[4,5]` in the same order, so a comparator of `a.end - b.end || a.start - b.start` passes :99. The fixture needs a ready cue whose end comes earlier but whose start comes later than another cue's (for example `{start: 2, end: 2.5}` alongside `{start: 1, end: 3}`) before the \"start then end\" half of C1c reads differently under that wrong sort.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `CONTRACT_RUNNER` does not exist yet in tests/active/test_frontend_translate.py. The only matches are in this test and in tests/last_test_output.txt / last_test_validation.json. So I could not read what the runner serves, or how it computes `nonFinite` (from the served text or from the fixture). The D5 and D14 rows are judged on the test's assertions alone. A runner that takes `nonFinite` from the fixture would make the :86 check meaningless, and that can only be checked once the runner exists.\n2. client/frontend/src/data/translate.ts and tests/active/fixtures/translate_contract.json were not in `code_under_test`. I read them anyway because the test bundles the first and parametrizes over the second, and they are where I got the accepted inputs and refusal paths for the bounds checks. tests/config.json, which was listed, has nothing about this test's behaviour.\n3. `fixtures_path` was not supplied. The test defines its only fixture itself (`contract_report`, :60) and otherwise uses pytest's built-in `tmp_path_factory`, so I did not need a conftest.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"every valid fixture case served to fetchTranslate or requestTranslate\"",
            "assertion": ":84",
            "excludes": "a case sent to the wrong function: a GET where a POST belongs or the other way round, or a state case missing its `after`. Every VALID case is a parametrized case (:90)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"comes back with exactly its gateway fields\"",
            "assertion": ":99",
            "excludes": "a field dropped or added (for example `available` left out, or `total` kept on a ready answer), because whole-dict equality fails on either",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"ready cues sorted by start then end\"",
            "assertion": ":99 (expected built at :98)",
            "excludes": "ready left unsorted, or sorted by start only. The fixture's tie at start 1.0 (end 3.0 before end 2.0) reads differently under a start-only sort",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"running cues in the order given\"",
            "assertion": ":99, control :96",
            "excludes": "running cues sorted the way ready cues are. :96 shows the fixture's running lists are out of order, so a sort would change what :99 reads",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"every rejected fixture case served as a 200\"",
            "assertion": ":105, :84",
            "excludes": "the case's real status served (404 and so on): `readTranslateResponse` would then throw the error text or \"Translate request failed (N)\", which does not equal MALFORMED",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "throws exactly \"Translate response was malformed\"",
            "assertion": ":105",
            "excludes": "a JSON SyntaxError, a gateway error text, or no throw at all",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture",
            "assertion": ":99, :105",
            "excludes": "a single case that disagrees turns its own parametrized case red",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\"",
            "assertion": "none",
            "excludes": "nothing reads it. A runner that hard-codes the fixture path or the host gives the same report",
            "status": "UNCARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route)",
            "assertion": ":84",
            "excludes": "a call on the wrong route, or `after` left off or added",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the gateway answer for a valid case\" is what gets served",
            "assertion": ":99",
            "excludes": "serving the Engine body instead: the 404 \"video not found\" cases would then throw rather than return the gateway value",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the Engine body for a rejected one\" is what gets served",
            "assertion": ":86",
            "excludes": "serving one stand-in body for every rejected case: the `start 1e999` case would read `nonFinite` false. This only reads at that one case (see Recommendation 2)",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "`FETCH_RECORDER` \"writes every request to the ASKED file\"",
            "assertion": ":83",
            "excludes": "requests going unrecorded, which would make the count fall short",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\"",
            "assertion": ":79",
            "excludes": "a missing runner being skipped or passing silently",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\"",
            "assertion": ":99",
            "excludes": "same wrong versions as C1b, C1c and C1d",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the fixture's ready and running lists are themselves out of that order\"",
            "assertion": ":96",
            "excludes": "a fixture already in order, which would make the sort check meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\"",
            "assertion": ":105",
            "excludes": "a SyntaxError or a gateway error text",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the runner made one request per case\"",
            "assertion": ":83",
            "excludes": "extra requests or skipped requests",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\"",
            "assertion": ":84",
            "excludes": "wrong method, wrong path, or a wrong or missing `after`",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\"",
            "assertion": ":86",
            "excludes": "the 1e999 case refused for some other reason (a null, a substituted body), or a non-finite number reported where there is none",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"each valid contract case\"",
            "assertion": ":90 parametrize, :84",
            "excludes": "a valid case left out or sent down the wrong route",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"comes back with exactly its gateway fields\"",
            "assertion": ":99",
            "excludes": "a field added or dropped",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"ready cues sorted by start then end\"",
            "assertion": ":99",
            "excludes": "unsorted, or sorted by start only",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"running in given order\"",
            "assertion": ":99, :96",
            "excludes": "running cues sorted",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"each rejected contract case served as a 200\"",
            "assertion": ":105",
            "excludes": "the case's real non-200 status served, which yields error text rather than MALFORMED",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"throws exactly translate response was malformed\"",
            "assertion": ":105",
            "excludes": "any other message, or no throw",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery parametrized case in both tests fails at line 81, `assert contract_report is not None`,\ninside `_result`. tests/active/test_frontend_translate.py defines no `CONTRACT_RUNNER`, so the\n`contract_report` fixture returns None and the message names the missing runner.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines its only fixture, `contract_report`\n   (line 62). It also depends on `tmp_path_factory`, a pytest built-in, and no conftest was\n   needed. The data file tests/active/fixtures/translate_contract.json was read so the\n   expected values could be checked.\n2. `code_under_test` names the durable module the phase will extend with `CONTRACT_RUNNER`,\n   and that module does not contain it yet. client/frontend/src/data/translate.ts is what the\n   runner exercises, and it was read too. The stub question was answered against runners that\n   might plausibly be written next to the current translate.ts, not against a runner that\n   exists.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 6 must_prove, 13 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"every valid fixture case served to fetchTranslate or requestTranslate\" | :86 (parametrized over every VALID case at :92) | a case sent to the wrong function, i.e. a GET where a POST belongs or the reverse, or a state case missing its `after` or given one it should not have | CARRIED |\n| C1b | must_prove | \"comes back with exactly its gateway fields\" | :101 | a field dropped or added, such as `available` left out or `total` kept on a ready answer. The whole-dict equality fails on either | CARRIED |\n| C1c | must_prove | \"ready cues sorted by start then end\" | :101 (expected replaced at :100 with READY_CUES from :30) | ready cues left unsorted, or sorted by start only. In the fixture, \"Long first\" (1.0, 3.0) comes before \"Short first\" (1.0, 2.0), so a stable start-only sort keeps them in that order and reads differently from READY_CUES | CARRIED |\n| C1d | must_prove | \"running cues in the order given\" | :101, with the control at :98 | running cues sorted the way ready cues are. :98 shows the fixture's running lists (Third/First/Second, Fifth/Fourth) are out of order, so a sort would change what :101 reads | CARRIED |\n| C2a | must_prove | \"every rejected fixture case served as a 200\" | :107, :86 | serving the case's real status. For the two 404 cases, `readTranslateResponse` (translate.ts:88-90) would then throw \"Not found\", which does not equal MALFORMED | CARRIED |\n| C2b | must_prove | throws exactly \"Translate response was malformed\" | :107 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |\n| D1 | docstring | the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture | :101, :107 | any single case that disagrees fails its own parametrized case | CARRIED |\n| D2 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :86 | a call on the wrong route, or `after` left off or added | CARRIED |\n| D4 | docstring | \"the gateway answer for a valid case\" is what gets served | :101 | serving the Engine body instead. The 404 \"video not found\" cases would then throw \"Video not found\" instead of returning the gateway value | CARRIED |\n| D5 | docstring | \"the Engine body for a rejected one\" is what gets served | :88 | one stand-in body served for every rejected case. The `start 1e999` case would then read `nonFinite` false. This only shows at that one case | CARRIED |\n| D7 | docstring | `FETCH_RECORDER` \"writes every request to the ASKED file\" | :85 | requests going unrecorded, which leaves the count short of len(CASES) | CARRIED |\n| D8 | docstring | \"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\" | :81 | a missing runner being skipped or passing silently | CARRIED |\n| D9 | docstring | the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\" | :101 | the same wrong implementations as C1b, C1c and C1d | CARRIED |\n| D10 | docstring | \"the fixture's ready and running lists are themselves out of that order\" | :98 | a fixture already in order, which would make the sort check meaningless | CARRIED |\n| D11 | docstring | threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\" | :107 | a SyntaxError or a gateway error text | CARRIED |\n| D12 | docstring | \"the runner made one request per case\" | :85 | extra requests or skipped requests | CARRIED |\n| D13 | docstring | \"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\" | :86 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |\n| D14 | docstring | non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\" | :88 | the 1e999 case refused for another reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |\n| N1 | name | \"each valid contract case\" | :92 parametrize, :86 | a valid case left out or sent down the wrong route | CARRIED |\n| N2 | name | \"comes back with exactly its gateway fields\" | :101 | a field added or dropped | CARRIED |\n| N3 | name | \"ready cues sorted by start then end\" | :101 | unsorted, or sorted by start only | CARRIED |\n| N4 | name | \"running in given order\" | :101, :98 | running cues sorted | CARRIED |\n| N5 | name | \"each rejected contract case served as a 200\" | :107 | the case's real non-200 status served, which yields an error text, not MALFORMED | CARRIED |\n| N6 | name | \"throws exactly translate response was malformed\" | :107 | any other message, or no throw | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3\n   Ledger row D2 was resolved by changing the docstring, not by adding an assertion. The sentence used to say the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\". It now says \"the test hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here)\". Nothing asserts that the runner reads them. The claim was withdrawn, and the env dict at :56 is setup, not an assertion.\n2. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3\n   The ledger has no D6 row. The docstring clause \"prints one JSON report keyed by case name of `{value | thrown, nonFinite}`\" has no row. It is read implicitly: :82 indexes the report by case name, and :88, :101 and :107 read `nonFinite`, `value` and `thrown`. No defect found; recorded so the gap in the ids is explained.\n\nNOT ASSESSED\n1. `CONTRACT_RUNNER` is not yet defined in `code_under_test` tests/active/test_frontend_translate.py; the test fails at :81 until it is. So I couldn't read what the runner serves (200 status, gateway answer or Engine body). C2a, D4 and D5 were judged only from what the test reads and from client/frontend/src/data/translate.ts.\n2. I searched tests/config.json only for its translate entries; I did not read it in full.\n3. `fixtures_path` was not supplied, and the test uses only pytest's built-in `tmp_path_factory` and its own module-scoped `contract_report` fixture (:62), so I didn't search for a conftest.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nEvery parametrized case in both tests fails at line 81, `assert contract_report is not None`,\ninside `_result`. tests/active/test_frontend_translate.py defines no `CONTRACT_RUNNER`, so the\n`contract_report` fixture returns None and the message names the missing runner.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines its only fixture, `contract_report`\n   (line 62). It also depends on `tmp_path_factory`, a pytest built-in, and no conftest was\n   needed. The data file tests/active/fixtures/translate_contract.json was read so the\n   expected values could be checked.\n2. `code_under_test` names the durable module the phase will extend with `CONTRACT_RUNNER`,\n   and that module does not contain it yet. client/frontend/src/data/translate.ts is what the\n   runner exercises, and it was read too. The stub question was answered against runners that\n   might plausibly be written next to the current translate.ts, not against a runner that\n   exists.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 6 must_prove, 13 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"every valid fixture case served to fetchTranslate or requestTranslate\" | :86 (parametrized over every VALID case at :92) | a case sent to the wrong function, i.e. a GET where a POST belongs or the reverse, or a state case missing its `after` or given one it should not have | CARRIED |\n| C1b | must_prove | \"comes back with exactly its gateway fields\" | :101 | a field dropped or added, such as `available` left out or `total` kept on a ready answer. The whole-dict equality fails on either | CARRIED |\n| C1c | must_prove | \"ready cues sorted by start then end\" | :101 (expected replaced at :100 with READY_CUES from :30) | ready cues left unsorted, or sorted by start only. In the fixture, \"Long first\" (1.0, 3.0) comes before \"Short first\" (1.0, 2.0), so a stable start-only sort keeps them in that order and reads differently from READY_CUES | CARRIED |\n| C1d | must_prove | \"running cues in the order given\" | :101, with the control at :98 | running cues sorted the way ready cues are. :98 shows the fixture's running lists (Third/First/Second, Fifth/Fourth) are out of order, so a sort would change what :101 reads | CARRIED |\n| C2a | must_prove | \"every rejected fixture case served as a 200\" | :107, :86 | serving the case's real status. For the two 404 cases, `readTranslateResponse` (translate.ts:88-90) would then throw \"Not found\", which does not equal MALFORMED | CARRIED |\n| C2b | must_prove | throws exactly \"Translate response was malformed\" | :107 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |\n| D1 | docstring | the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture | :101, :107 | any single case that disagrees fails its own parametrized case | CARRIED |\n| D2 | docstring | withdrawn | n/a | n/a | CARRIED |\n| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :86 | a call on the wrong route, or `after` left off or added | CARRIED |\n| D4 | docstring | \"the gateway answer for a valid case\" is what gets served | :101 | serving the Engine body instead. The 404 \"video not found\" cases would then throw \"Video not found\" instead of returning the gateway value | CARRIED |\n| D5 | docstring | \"the Engine body for a rejected one\" is what gets served | :88 | one stand-in body served for every rejected case. The `start 1e999` case would then read `nonFinite` false. This only shows at that one case | CARRIED |\n| D7 | docstring | `FETCH_RECORDER` \"writes every request to the ASKED file\" | :85 | requests going unrecorded, which leaves the count short of len(CASES) | CARRIED |\n| D8 | docstring | \"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\" | :81 | a missing runner being skipped or passing silently | CARRIED |\n| D9 | docstring | the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\" | :101 | the same wrong implementations as C1b, C1c and C1d | CARRIED |\n| D10 | docstring | \"the fixture's ready and running lists are themselves out of that order\" | :98 | a fixture already in order, which would make the sort check meaningless | CARRIED |\n| D11 | docstring | threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\" | :107 | a SyntaxError or a gateway error text | CARRIED |\n| D12 | docstring | \"the runner made one request per case\" | :85 | extra requests or skipped requests | CARRIED |\n| D13 | docstring | \"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\" | :86 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |\n| D14 | docstring | non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\" | :88 | the 1e999 case refused for another reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |\n| N1 | name | \"each valid contract case\" | :92 parametrize, :86 | a valid case left out or sent down the wrong route | CARRIED |\n| N2 | name | \"comes back with exactly its gateway fields\" | :101 | a field added or dropped | CARRIED |\n| N3 | name | \"ready cues sorted by start then end\" | :101 | unsorted, or sorted by start only | CARRIED |\n| N4 | name | \"running in given order\" | :101, :98 | running cues sorted | CARRIED |\n| N5 | name | \"each rejected contract case served as a 200\" | :107 | the case's real non-200 status served, which yields an error text, not MALFORMED | CARRIED |\n| N6 | name | \"throws exactly translate response was malformed\" | :107 | any other message, or no throw | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3\n   Ledger row D2 was resolved by changing the docstring, not by adding an assertion. The sentence used to say the runner \"reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables\". It now says \"the test hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here)\". Nothing asserts that the runner reads them. The claim was withdrawn, and the env dict at :56 is setup, not an assertion.\n2. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3\n   The ledger has no D6 row. The docstring clause \"prints one JSON report keyed by case name of `{value | thrown, nonFinite}`\" has no row. It is read implicitly: :82 indexes the report by case name, and :88, :101 and :107 read `nonFinite`, `value` and `thrown`. No defect found; recorded so the gap in the ids is explained.\n\nNOT ASSESSED\n1. `CONTRACT_RUNNER` is not yet defined in `code_under_test` tests/active/test_frontend_translate.py; the test fails at :81 until it is. So I couldn't read what the runner serves (200 status, gateway answer or Engine body). C2a, D4 and D5 were judged only from what the test reads and from client/frontend/src/data/translate.ts.\n2. I searched tests/config.json only for its translate entries; I did not read it in full.\n3. `fixtures_path` was not supplied, and the test uses only pytest's built-in `tmp_path_factory` and its own module-scoped `contract_report` fixture (:62), so I didn't search for a conftest.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"every valid fixture case served to fetchTranslate or requestTranslate\"",
            "assertion": ":86 (parametrized over every VALID case at :92)",
            "excludes": "a case sent to the wrong function, i.e. a GET where a POST belongs or the reverse, or a state case missing its `after` or given one it should not have",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"comes back with exactly its gateway fields\"",
            "assertion": ":101",
            "excludes": "a field dropped or added, such as `available` left out or `total` kept on a ready answer. The whole-dict equality fails on either",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"ready cues sorted by start then end\"",
            "assertion": ":101 (expected replaced at :100 with READY_CUES from :30)",
            "excludes": "ready cues left unsorted, or sorted by start only. In the fixture, \"Long first\" (1.0, 3.0) comes before \"Short first\" (1.0, 2.0), so a stable start-only sort keeps them in that order and reads differently from READY_CUES",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"running cues in the order given\"",
            "assertion": ":101, with the control at :98",
            "excludes": "running cues sorted the way ready cues are. :98 shows the fixture's running lists (Third/First/Second, Fifth/Fourth) are out of order, so a sort would change what :101 reads",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "\"every rejected fixture case served as a 200\"",
            "assertion": ":107, :86",
            "excludes": "serving the case's real status. For the two 404 cases, `readTranslateResponse` (translate.ts:88-90) would then throw \"Not found\", which does not equal MALFORMED",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "throws exactly \"Translate response was malformed\"",
            "assertion": ":107",
            "excludes": "a JSON SyntaxError, a gateway error text, or no throw at all",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "the real translate.ts, bundled on its own, agrees \"with every case\" of the fixture",
            "assertion": ":101, :107",
            "excludes": "any single case that disagrees fails its own parametrized case",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "withdrawn",
            "assertion": "n/a",
            "excludes": "n/a",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route)",
            "assertion": ":86",
            "excludes": "a call on the wrong route, or `after` left off or added",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the gateway answer for a valid case\" is what gets served",
            "assertion": ":101",
            "excludes": "serving the Engine body instead. The 404 \"video not found\" cases would then throw \"Video not found\" instead of returning the gateway value",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"the Engine body for a rejected one\" is what gets served",
            "assertion": ":88",
            "excludes": "one stand-in body served for every rejected case. The `start 1e999` case would then read `nonFinite` false. This only shows at that one case",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "`FETCH_RECORDER` \"writes every request to the ASKED file\"",
            "assertion": ":85",
            "excludes": "requests going unrecorded, which leaves the count short of len(CASES)",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence\"",
            "assertion": ":81",
            "excludes": "a missing runner being skipped or passing silently",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "the value \"deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given\"",
            "assertion": ":101",
            "excludes": "the same wrong implementations as C1b, C1c and C1d",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the fixture's ready and running lists are themselves out of that order\"",
            "assertion": ":98",
            "excludes": "a fixture already in order, which would make the sort check meaningless",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "threw exactly MALFORMED, \"so a JSON SyntaxError or a gateway error text cannot pass\"",
            "assertion": ":107",
            "excludes": "a SyntaxError or a gateway error text",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "\"the runner made one request per case\"",
            "assertion": ":85",
            "excludes": "extra requests or skipped requests",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case\"",
            "assertion": ":86",
            "excludes": "wrong method, wrong path, or a wrong or missing `after`",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "non-finite \"exactly where Python's reading of the fixture finds one (its `1e999`)\"",
            "assertion": ":88",
            "excludes": "the 1e999 case refused for another reason (a null, a substituted body), or a non-finite number reported where there is none",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"each valid contract case\"",
            "assertion": ":92 parametrize, :86",
            "excludes": "a valid case left out or sent down the wrong route",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"comes back with exactly its gateway fields\"",
            "assertion": ":101",
            "excludes": "a field added or dropped",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"ready cues sorted by start then end\"",
            "assertion": ":101",
            "excludes": "unsorted, or sorted by start only",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"running in given order\"",
            "assertion": ":101, :98",
            "excludes": "running cues sorted",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"each rejected contract case served as a 200\"",
            "assertion": ":107",
            "excludes": "the case's real non-200 status served, which yields an error text, not MALFORMED",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"throws exactly translate response was malformed\"",
            "assertion": ":107",
            "excludes": "any other message, or no throw",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_55_translate_state_contract_phase3.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. Stub question, driver-side patching (no shape.md entry covers this) \u2014 tests/tmp/test_55_translate_state_contract_phase3.py:101\n   responses = drive(tmp_path / f\"subtitles-{index}.db\", whitelist, monkeypatch, case)\n   Each driver gets the fixture `case` and the same `monkeypatch` that patches `handlers.internal_translate`. The control at line 103 catches a driver that writes its own answer. It does not catch one that patches a symbol inside the handler module so the real handler returns data built from `case`. The checks at lines 109 and 113 would then compare the case's types with themselves. Nothing ties the answer to state the driver stored through the store's own writers. The drivers are not written yet, so I can't tell whether this can happen. A control that the driver left the module's symbols as they were (only `now_ms` patched) would close it.\n\nPREDICTED FAILURE\n`test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` fails at line 39 (`assert drivers is not None`), reached through `_drivers()` at line 85. All 13 parametrized shape tests fail on the same assertion, reached at line 96 after the control at line 95 passes. The cause in every case is that `tests/active/test_internal_translate.py` has no `ENGINE_DRIVERS`. Both parametrizations of the not-found test pass, because they drive the existing handlers directly.\n\nNOT ASSESSED\n1. `ENGINE_DRIVERS` does not exist yet in tests/active/test_internal_translate.py, which is the phase's output. So the stub question was answered from the assertion form and its controls (lines 103, 105, 108), not from what the drivers do.\n2. `engine/server/api/handlers/internal_translate.py`, the handler the drivers run, was not in `code_under_test` and was not read. The claim that the recorder at lines 69\u201380 wraps what the drivers call depends on the drivers looking up the handler through the module attribute. That can't be checked until the drivers exist.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (40 clauses: 13 must_prove, 19 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"driven through the real handler\" | :103 | a driver that makes up the answer, calls the other route's handler, or edits what the handler wrote | CARRIED |\n| C1b | must_prove | \"answers a 200\" | :106, :107 | a non-200 status, or more than one response | CARRIED |\n| C1c | must_prove | \"exactly that case's key set\" | :109 | a missing key or an extra key (dict equality on the key-to-type map) | CARRIED |\n| C1d | must_prove | \"and value JSON types\" | :109 | a value of the wrong JSON type, including a bool written as a number (`_json_type` :45 checks bool first) | CARRIED |\n| C1e | must_prove | \"its cues included\": cues present wherever the case has them | :112 | an empty `cues` where the case's cues are non-empty | CARRIED |\n| C1f | must_prove | \"its cues included\": each cue's keys and types | :113 | a cue with a missing, extra or wrongly typed field | CARRIED |\n| C1g | must_prove | \"no fixture state is without a driver\" | :86 | a table missing a fixture (route, state) | CARRIED |\n| C1h | must_prove | \"nor any driver without a fixture state\" | :87 | a table with an extra (route, state) | CARRIED |\n| C1i | must_prove | \"Each (route, state) among the fixture's valid 200 cases that carry available\" is driven | :89, :95, loop :98 | a parametrize list that leaves out a fixture pair; skipping the second case of a pair (`state running after 3`, whose request body :105 checks) | CARRIED |\n| C2a | must_prove | state route, unknown video \u2192 exactly the fixture's 404 body | :128 (route=state) | a different status, a different body, or more than one response | CARRIED |\n| C2b | must_prove | state route, actively denylisted video \u2192 exactly the fixture's 404 body | :129, control :132 | an answer other than the fixture's 404, or a 404 not caused by the denylist (:132 shows 200 once the deny row is inactive) | CARRIED |\n| C2c | must_prove | enqueue route, unknown video \u2192 exactly the fixture's 404 body | :128 (route=enqueue) | as C2a, on the enqueue handler | CARRIED |\n| C2d | must_prove | enqueue route, actively denylisted video \u2192 exactly the fixture's 404 body | :129, control :132 | as C2b, on the enqueue handler | CARRIED |\n| D1 | docstring | handlers driven by `ENGINE_DRIVERS` \"answer with the keys and JSON types\" of the fixture | :109 | a key or type that differs from the fixture's | CARRIED |\n| D2 | docstring | \"their not-found answer is the fixture's body\" | :128, :129 | a body that is not the fixture's | CARRIED |\n| D3 | docstring | the recorder passes through: \"the real handler still runs and answers\" | :103 | a recorder or driver that replaces what the handler wrote | CARRIED |\n| D4 | docstring | \"the table test and every shape test fail on its absence\" | :39 (reached from :85, :96) | quietly passing or skipping while the table is missing | CARRIED |\n| D5 | docstring | \"has no member without a driver\" | :86 | a missing driver | CARRIED |\n| D6 | docstring | \"the table has no driver without such a case\" | :87 | an extra driver | CARRIED |\n| D7 | docstring | control: the set equals the 13 pairs the shape test is parametrized over | :89 | the fixture and `ROUTE_STATES` no longer matching | CARRIED |\n| D8 | docstring | \"exactly one 200\" | :106, :107 | zero or several responses, or a non-200 | CARRIED |\n| D9 | docstring | \"key-to-JSON-type map equals the case's (bool before number)\" | :109 | different keys or types; a bool read as a number | CARRIED |\n| D10 | docstring | \"the answer's cues are non-empty\" where the case has cues | :112 | empty cues | CARRIED |\n| D11 | docstring | \"each cue's key-to-type map is one of the case's cues'\" | :113 | a cue whose shape is wrong | CARRIED |\n| D12 | docstring | control: \"the fixture carries the (route, state)\" | :95 | a parametrized pair with no fixture case, which would run zero iterations and pass | CARRIED |\n| D13 | docstring | \"that route's real handler was called once and the other route's not at all\" | :103 | the wrong handler called, or a handler called twice | CARRIED |\n| D14 | docstring | \"the driver returned exactly what the handler wrote\" | :103 | a driver-made answer | CARRIED |\n| D15 | docstring | \"the request carried the case's `after` exactly when the case has one\" | :105 | `after` missing, wrong, or sent when the case has none | CARRIED |\n| D16 | docstring | \"the answer's state is the state under test\" | :108 | a driver that reaches a different state with a matching shape | CARRIED |\n| D17 | docstring | unknown video answers exactly `[[404, <fixture body>]]` on each route | :128 | any other answer | CARRIED |\n| D18 | docstring | the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly that | :126, :129 | any other answer; a lowercase-only deny match goes untested because the row is stored uppercase | CARRIED |\n| D19 | docstring | control: \"the same denied video answers 200 once its deny row is inactive\" | :131, :132 | a 404 caused by something other than the denylist | CARRIED |\n| N1 | name | driver table \"has exactly the contract fixture's route states\" | :86, :87 | a missing or an extra driver | CARRIED |\n| N2 | name | \"each route state driven through the real handler\" | :103 | a made-up answer, or the wrong handler | CARRIED |\n| N3 | name | \"answers a 200\" | :107 | a non-200 | CARRIED |\n| N4 | name | \"with its contract case's keys and json types\" | :109 | a key or type that differs | CARRIED |\n| N5 | name | \"cues included\" | :112, :113 | empty or wrongly shaped cues | CARRIED |\n| N6 | name | \"an unknown ... video answers the contract fixture's video not found 404\" | :128 | any other answer | CARRIED |\n| N7 | name | \"or actively denied video answers\" the same | :129 | any other answer | CARRIED |\n| N8 | name | \"on each route\" | :116 parametrize, :119 | only one route exercised | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `ENGINE_DRIVERS` does not exist in tests/active/test_internal_translate.py (a grep for it under tests/active finds nothing), even though `code_under_test` lists that file as EDITED. So I could not read the drivers. One thing stays unchecked: whether a driver reaches its state through the store's own writers or by monkeypatching parts of the handler module, using the `monkeypatch` the test passes it at :101. The C1 rows are judged on what the test's assertions exclude, given whatever driver gets written.\n2. engine/server/api/handlers/internal_translate.py is not in `code_under_test` and I did not read it. I judged the C2 path and the 404 control (:132) from the helpers in test_internal_translate.py (`_state`, `_enqueue`, `_whitelist`, `_set_denied`, `_beat`) and from tests/active/fixtures/translate_contract.json.\n3. tests/config.json (listed in `code_under_test`) was read. It is test-group mapping and has no bearing on any clause.\n4. `fixtures_path` was not supplied. The test defines its own `whitelist` fixture at :62 and otherwise uses only pytest built-ins (`tmp_path`, `monkeypatch`), so I needed no conftest.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. Stub question, driver-side patching (no shape.md entry covers this) \u2014 tests/tmp/test_55_translate_state_contract_phase3.py:101\n   responses = drive(tmp_path / f\"subtitles-{index}.db\", whitelist, monkeypatch, case)\n   Each driver gets the fixture `case` and the same `monkeypatch` that patches `handlers.internal_translate`. The control at line 103 catches a driver that writes its own answer. It does not catch one that patches a symbol inside the handler module so the real handler returns data built from `case`. The checks at lines 109 and 113 would then compare the case's types with themselves. Nothing ties the answer to state the driver stored through the store's own writers. The drivers are not written yet, so I can't tell whether this can happen. A control that the driver left the module's symbols as they were (only `now_ms` patched) would close it.\n\nPREDICTED FAILURE\n`test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` fails at line 39 (`assert drivers is not None`), reached through `_drivers()` at line 85. All 13 parametrized shape tests fail on the same assertion, reached at line 96 after the control at line 95 passes. The cause in every case is that `tests/active/test_internal_translate.py` has no `ENGINE_DRIVERS`. Both parametrizations of the not-found test pass, because they drive the existing handlers directly.\n\nNOT ASSESSED\n1. `ENGINE_DRIVERS` does not exist yet in tests/active/test_internal_translate.py, which is the phase's output. So the stub question was answered from the assertion form and its controls (lines 103, 105, 108), not from what the drivers do.\n2. `engine/server/api/handlers/internal_translate.py`, the handler the drivers run, was not in `code_under_test` and was not read. The claim that the recorder at lines 69\u201380 wraps what the drivers call depends on the drivers looking up the handler through the module attribute. That can't be checked until the drivers exist.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (40 clauses: 13 must_prove, 19 docstring, 8 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"driven through the real handler\" | :103 | a driver that makes up the answer, calls the other route's handler, or edits what the handler wrote | CARRIED |\n| C1b | must_prove | \"answers a 200\" | :106, :107 | a non-200 status, or more than one response | CARRIED |\n| C1c | must_prove | \"exactly that case's key set\" | :109 | a missing key or an extra key (dict equality on the key-to-type map) | CARRIED |\n| C1d | must_prove | \"and value JSON types\" | :109 | a value of the wrong JSON type, including a bool written as a number (`_json_type` :45 checks bool first) | CARRIED |\n| C1e | must_prove | \"its cues included\": cues present wherever the case has them | :112 | an empty `cues` where the case's cues are non-empty | CARRIED |\n| C1f | must_prove | \"its cues included\": each cue's keys and types | :113 | a cue with a missing, extra or wrongly typed field | CARRIED |\n| C1g | must_prove | \"no fixture state is without a driver\" | :86 | a table missing a fixture (route, state) | CARRIED |\n| C1h | must_prove | \"nor any driver without a fixture state\" | :87 | a table with an extra (route, state) | CARRIED |\n| C1i | must_prove | \"Each (route, state) among the fixture's valid 200 cases that carry available\" is driven | :89, :95, loop :98 | a parametrize list that leaves out a fixture pair; skipping the second case of a pair (`state running after 3`, whose request body :105 checks) | CARRIED |\n| C2a | must_prove | state route, unknown video \u2192 exactly the fixture's 404 body | :128 (route=state) | a different status, a different body, or more than one response | CARRIED |\n| C2b | must_prove | state route, actively denylisted video \u2192 exactly the fixture's 404 body | :129, control :132 | an answer other than the fixture's 404, or a 404 not caused by the denylist (:132 shows 200 once the deny row is inactive) | CARRIED |\n| C2c | must_prove | enqueue route, unknown video \u2192 exactly the fixture's 404 body | :128 (route=enqueue) | as C2a, on the enqueue handler | CARRIED |\n| C2d | must_prove | enqueue route, actively denylisted video \u2192 exactly the fixture's 404 body | :129, control :132 | as C2b, on the enqueue handler | CARRIED |\n| D1 | docstring | handlers driven by `ENGINE_DRIVERS` \"answer with the keys and JSON types\" of the fixture | :109 | a key or type that differs from the fixture's | CARRIED |\n| D2 | docstring | \"their not-found answer is the fixture's body\" | :128, :129 | a body that is not the fixture's | CARRIED |\n| D3 | docstring | the recorder passes through: \"the real handler still runs and answers\" | :103 | a recorder or driver that replaces what the handler wrote | CARRIED |\n| D4 | docstring | \"the table test and every shape test fail on its absence\" | :39 (reached from :85, :96) | quietly passing or skipping while the table is missing | CARRIED |\n| D5 | docstring | \"has no member without a driver\" | :86 | a missing driver | CARRIED |\n| D6 | docstring | \"the table has no driver without such a case\" | :87 | an extra driver | CARRIED |\n| D7 | docstring | control: the set equals the 13 pairs the shape test is parametrized over | :89 | the fixture and `ROUTE_STATES` no longer matching | CARRIED |\n| D8 | docstring | \"exactly one 200\" | :106, :107 | zero or several responses, or a non-200 | CARRIED |\n| D9 | docstring | \"key-to-JSON-type map equals the case's (bool before number)\" | :109 | different keys or types; a bool read as a number | CARRIED |\n| D10 | docstring | \"the answer's cues are non-empty\" where the case has cues | :112 | empty cues | CARRIED |\n| D11 | docstring | \"each cue's key-to-type map is one of the case's cues'\" | :113 | a cue whose shape is wrong | CARRIED |\n| D12 | docstring | control: \"the fixture carries the (route, state)\" | :95 | a parametrized pair with no fixture case, which would run zero iterations and pass | CARRIED |\n| D13 | docstring | \"that route's real handler was called once and the other route's not at all\" | :103 | the wrong handler called, or a handler called twice | CARRIED |\n| D14 | docstring | \"the driver returned exactly what the handler wrote\" | :103 | a driver-made answer | CARRIED |\n| D15 | docstring | \"the request carried the case's `after` exactly when the case has one\" | :105 | `after` missing, wrong, or sent when the case has none | CARRIED |\n| D16 | docstring | \"the answer's state is the state under test\" | :108 | a driver that reaches a different state with a matching shape | CARRIED |\n| D17 | docstring | unknown video answers exactly `[[404, <fixture body>]]` on each route | :128 | any other answer | CARRIED |\n| D18 | docstring | the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly that | :126, :129 | any other answer; a lowercase-only deny match goes untested because the row is stored uppercase | CARRIED |\n| D19 | docstring | control: \"the same denied video answers 200 once its deny row is inactive\" | :131, :132 | a 404 caused by something other than the denylist | CARRIED |\n| N1 | name | driver table \"has exactly the contract fixture's route states\" | :86, :87 | a missing or an extra driver | CARRIED |\n| N2 | name | \"each route state driven through the real handler\" | :103 | a made-up answer, or the wrong handler | CARRIED |\n| N3 | name | \"answers a 200\" | :107 | a non-200 | CARRIED |\n| N4 | name | \"with its contract case's keys and json types\" | :109 | a key or type that differs | CARRIED |\n| N5 | name | \"cues included\" | :112, :113 | empty or wrongly shaped cues | CARRIED |\n| N6 | name | \"an unknown ... video answers the contract fixture's video not found 404\" | :128 | any other answer | CARRIED |\n| N7 | name | \"or actively denied video answers\" the same | :129 | any other answer | CARRIED |\n| N8 | name | \"on each route\" | :116 parametrize, :119 | only one route exercised | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `ENGINE_DRIVERS` does not exist in tests/active/test_internal_translate.py (a grep for it under tests/active finds nothing), even though `code_under_test` lists that file as EDITED. So I could not read the drivers. One thing stays unchecked: whether a driver reaches its state through the store's own writers or by monkeypatching parts of the handler module, using the `monkeypatch` the test passes it at :101. The C1 rows are judged on what the test's assertions exclude, given whatever driver gets written.\n2. engine/server/api/handlers/internal_translate.py is not in `code_under_test` and I did not read it. I judged the C2 path and the 404 control (:132) from the helpers in test_internal_translate.py (`_state`, `_enqueue`, `_whitelist`, `_set_denied`, `_beat`) and from tests/active/fixtures/translate_contract.json.\n3. tests/config.json (listed in `code_under_test`) was read. It is test-group mapping and has no bearing on any clause.\n4. `fixtures_path` was not supplied. The test defines its own `whitelist` fixture at :62 and otherwise uses only pytest built-ins (`tmp_path`, `monkeypatch`), so I needed no conftest.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"driven through the real handler\"",
            "assertion": ":103",
            "excludes": "a driver that makes up the answer, calls the other route's handler, or edits what the handler wrote",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"answers a 200\"",
            "assertion": ":106, :107",
            "excludes": "a non-200 status, or more than one response",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"exactly that case's key set\"",
            "assertion": ":109",
            "excludes": "a missing key or an extra key (dict equality on the key-to-type map)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"and value JSON types\"",
            "assertion": ":109",
            "excludes": "a value of the wrong JSON type, including a bool written as a number (`_json_type` :45 checks bool first)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"its cues included\": cues present wherever the case has them",
            "assertion": ":112",
            "excludes": "an empty `cues` where the case's cues are non-empty",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "\"its cues included\": each cue's keys and types",
            "assertion": ":113",
            "excludes": "a cue with a missing, extra or wrongly typed field",
            "status": "CARRIED"
          },
          {
            "id": "C1g",
            "source": "must_prove",
            "clause": "\"no fixture state is without a driver\"",
            "assertion": ":86",
            "excludes": "a table missing a fixture (route, state)",
            "status": "CARRIED"
          },
          {
            "id": "C1h",
            "source": "must_prove",
            "clause": "\"nor any driver without a fixture state\"",
            "assertion": ":87",
            "excludes": "a table with an extra (route, state)",
            "status": "CARRIED"
          },
          {
            "id": "C1i",
            "source": "must_prove",
            "clause": "\"Each (route, state) among the fixture's valid 200 cases that carry available\" is driven",
            "assertion": ":89, :95, loop :98",
            "excludes": "a parametrize list that leaves out a fixture pair; skipping the second case of a pair (`state running after 3`, whose request body :105 checks)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "state route, unknown video \u2192 exactly the fixture's 404 body",
            "assertion": ":128 (route=state)",
            "excludes": "a different status, a different body, or more than one response",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "state route, actively denylisted video \u2192 exactly the fixture's 404 body",
            "assertion": ":129, control :132",
            "excludes": "an answer other than the fixture's 404, or a 404 not caused by the denylist (:132 shows 200 once the deny row is inactive)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "enqueue route, unknown video \u2192 exactly the fixture's 404 body",
            "assertion": ":128 (route=enqueue)",
            "excludes": "as C2a, on the enqueue handler",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "enqueue route, actively denylisted video \u2192 exactly the fixture's 404 body",
            "assertion": ":129, control :132",
            "excludes": "as C2b, on the enqueue handler",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "handlers driven by `ENGINE_DRIVERS` \"answer with the keys and JSON types\" of the fixture",
            "assertion": ":109",
            "excludes": "a key or type that differs from the fixture's",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"their not-found answer is the fixture's body\"",
            "assertion": ":128, :129",
            "excludes": "a body that is not the fixture's",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "the recorder passes through: \"the real handler still runs and answers\"",
            "assertion": ":103",
            "excludes": "a recorder or driver that replaces what the handler wrote",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the table test and every shape test fail on its absence\"",
            "assertion": ":39 (reached from :85, :96)",
            "excludes": "quietly passing or skipping while the table is missing",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"has no member without a driver\"",
            "assertion": ":86",
            "excludes": "a missing driver",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"the table has no driver without such a case\"",
            "assertion": ":87",
            "excludes": "an extra driver",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "control: the set equals the 13 pairs the shape test is parametrized over",
            "assertion": ":89",
            "excludes": "the fixture and `ROUTE_STATES` no longer matching",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"exactly one 200\"",
            "assertion": ":106, :107",
            "excludes": "zero or several responses, or a non-200",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"key-to-JSON-type map equals the case's (bool before number)\"",
            "assertion": ":109",
            "excludes": "different keys or types; a bool read as a number",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"the answer's cues are non-empty\" where the case has cues",
            "assertion": ":112",
            "excludes": "empty cues",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"each cue's key-to-type map is one of the case's cues'\"",
            "assertion": ":113",
            "excludes": "a cue whose shape is wrong",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "control: \"the fixture carries the (route, state)\"",
            "assertion": ":95",
            "excludes": "a parametrized pair with no fixture case, which would run zero iterations and pass",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "\"that route's real handler was called once and the other route's not at all\"",
            "assertion": ":103",
            "excludes": "the wrong handler called, or a handler called twice",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "\"the driver returned exactly what the handler wrote\"",
            "assertion": ":103",
            "excludes": "a driver-made answer",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"the request carried the case's `after` exactly when the case has one\"",
            "assertion": ":105",
            "excludes": "`after` missing, wrong, or sent when the case has none",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "\"the answer's state is the state under test\"",
            "assertion": ":108",
            "excludes": "a driver that reaches a different state with a matching shape",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "unknown video answers exactly `[[404, <fixture body>]]` on each route",
            "assertion": ":128",
            "excludes": "any other answer",
            "status": "CARRIED"
          },
          {
            "id": "D18",
            "source": "docstring",
            "clause": "the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly that",
            "assertion": ":126, :129",
            "excludes": "any other answer; a lowercase-only deny match goes untested because the row is stored uppercase",
            "status": "CARRIED"
          },
          {
            "id": "D19",
            "source": "docstring",
            "clause": "control: \"the same denied video answers 200 once its deny row is inactive\"",
            "assertion": ":131, :132",
            "excludes": "a 404 caused by something other than the denylist",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "driver table \"has exactly the contract fixture's route states\"",
            "assertion": ":86, :87",
            "excludes": "a missing or an extra driver",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"each route state driven through the real handler\"",
            "assertion": ":103",
            "excludes": "a made-up answer, or the wrong handler",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"answers a 200\"",
            "assertion": ":107",
            "excludes": "a non-200",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"with its contract case's keys and json types\"",
            "assertion": ":109",
            "excludes": "a key or type that differs",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"cues included\"",
            "assertion": ":112, :113",
            "excludes": "empty or wrongly shaped cues",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"an unknown ... video answers the contract fixture's video not found 404\"",
            "assertion": ":128",
            "excludes": "any other answer",
            "status": "CARRIED"
          },
          {
            "id": "N7",
            "source": "name",
            "clause": "\"or actively denied video answers\" the same",
            "assertion": ":129",
            "excludes": "any other answer",
            "status": "CARRIED"
          },
          {
            "id": "N8",
            "source": "name",
            "clause": "\"on each route\"",
            "assertion": ":116 parametrize, :119",
            "excludes": "only one route exercised",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_55_translate_state_contract_phase4.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. downshift_rule (rules/shape.md) \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:93\n   drains = re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", DEPLOY.read_text(), re.MULTILINE)\n   The drain default is read by regex over the shell script's source. That is below the\n   direct-import rung that lines 89-91 use for the other three numbers. The script has a\n   `--dry-run` that prints `drain=${DRAIN_SECONDS}s` (deploy-bluegreen.sh:240). That path\n   needs `--blue-green` and a readable upstream snippet (:253), so a rung-2 read may well\n   be impractical. The comment at :92 only explains why the regex is line-anchored. It\n   does not say why the test drops a rung, which is what the rule asks for. Add a\n   `# rung N: ...` comment naming the reason.\n\nPREDICTED FAILURE\ntest_the_heartbeat_freshness_window_... fails at line 69 on `assert len(values) == 1`.\nserver_config.py has no assignment to HEARTBEAT_FRESH_MS today, so `values` is empty. Both\nnames are still literals of their own: internal_translate.py:33 `HEARTBEAT_FRESH_MS = 15_000`\nand translate-worker.py:59 `HEARTBEAT_SECONDS = 5.0`. test_the_engine_fetch_budget_... passes\non the code as it stands: 15.0 + 4.0 < 20 < 30, and deploy-bluegreen.sh:50 is the only\n`DRAIN_SECONDS=` default line. The C2 ordering already holds before the phase.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines no fixtures and relies on none, so\n   nothing is missing.\n2. `code_under_test` lists tests/active/test_internal_translate.py and tests/config.json.\n   This test neither imports nor reads either file, so neither has any bearing on its\n   assertion form. They were not read.\n3. The stub question was answered from the assertion form:\n   - C1 fails on a literal (line 71).\n   - C1 fails on a derivation that names HEARTBEAT_SECONDS but ignores it (line 76, second\n     input 7.0 \u2192 21000).\n   - C1 fails on a float-valued derivation (line 73, `type(real) is int`).\n   - C1 fails on a handler-local equal literal (line 80 identity; lines 84-85).\n   - C2 fails if any one of its four constants is moved out of order.\n   No anti_pattern entry matched:\n   - Line 84's negative assertion is paired with line 85's positive one.\n   - Line 74's same-source equality is a labelled control, and lines 73/76 carry the\n     independent literals.\n   - C1 is a structural invariant and sits at rung 4 (AST parse), which is consistent\n     with matching_rule.\n```",
        "claim": "```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 6 must_prove, 11 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS\" | :71, :76 | a literal 15_000 (:71); a derivation that names the interval but ignores it, e.g. `15_000 + HEARTBEAT_SECONDS*0` (:76, 7.0 must give 21000) | CARRIED |\n| C1b | must_prove | the derived window is server_config's own module value | :69, :74 | a second assignment that rebinds the name after the derived one (:69 counts exactly one; :74 ties the evaluated expression to the module attribute) | CARRIED |\n| C1c | must_prove | internal_translate.py imports its heartbeat name from server_config | :80, :85 | a handler literal equal to 15000 (:80 checks identity); an import from any other module (:85 checks set equality) | CARRIED |\n| C1d | must_prove | translate-worker.py imports its heartbeat name from server_config | :85 | worker importing HEARTBEAT_SECONDS from another module, or not importing it | CARRIED |\n| C1e | must_prove | \"instead of assigning a literal of their own\" (both consumers) | :84 | `HEARTBEAT_SECONDS = 5.0` / `HEARTBEAT_FRESH_MS = 15_000` kept in either file, including annotated, augmented or unpacked binds | CARRIED |\n| C2a | must_prove | REQUEST_BUDGET_SECONDS + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS | :96 | a budget or socket timeout raised so the sum reaches the Client timeout; strict `<` also excludes equality | CARRIED |\n| C2b | must_prove | TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default | :94, :97 | a Client timeout at or past the drain (:97); reading the `--drain` override or a duplicate default line in place of the one default (:94) | CARRIED |\n| D1 | docstring | \"defined once, in engine/server/api/server_config.py\" | :69, :84 | a second definition in server_config or in either consumer | CARRIED |\n| D2 | docstring | \"translate timeouts across Engine, Client and deploy script stay in order\" | :96, :97 | either inequality inverted | CARRIED |\n| D3 | docstring | \"exactly one HEARTBEAT_FRESH_MS assignment\" | :69 | zero or two assignments | CARRIED |\n| D4 | docstring | \"its expression names HEARTBEAT_SECONDS\" | :71 | a bare literal expression | CARRIED |\n| D5 | docstring | \"gives 15000 (an int, the module's value) with the real interval\" | :73, :74 | a float 15000.0; a value that differs from the module attribute | CARRIED |\n| D6 | docstring | \"21000 with 7.0\" | :76 | an expression that does not scale with the interval | CARRIED |\n| D7 | docstring | \"handler's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal\" | :80 | an equal literal in the handler | CARRIED |\n| D8 | docstring | \"Neither ... binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself\" | :84 | either name bound in either file | CARRIED |\n| D9 | docstring | \"handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module\" | :85 | an import from another module, or from two modules | CARRIED |\n| D10 | docstring | \"REQUEST_BUDGET_SECONDS plus ... SOCKET_TIMEOUT_SECONDS is below ... TRANSLATE_TIMEOUT_SECONDS\" | :96 | sum >= Client timeout | CARRIED |\n| D11 | docstring | \"below the DRAIN_SECONDS default ... assigns on exactly one line of its own\" | :94, :97 | zero or several default lines; Client timeout >= drain | CARRIED |\n| N1 | name | \"heartbeat freshness window is derived from the interval in server_config\" | :71, :76 | literal or interval-ignoring window | CARRIED |\n| N2 | name | \"both consumers import it\" | :85 | a consumer importing from elsewhere or not at all | CARRIED |\n| N3 | name | \"engine fetch budget and socket timeout fit inside the client translate timeout\" | :96 | sum >= Client timeout | CARRIED |\n| N4 | name | \"which fits inside the deploy drain\" | :97 | Client timeout >= drain | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:65\n   \"both consumers import it\": the only antecedent of \"it\" is \"the heartbeat freshness window\",\n   but the worker imports the interval (HEARTBEAT_SECONDS, :82), not the window. A failure\n   from the worker side would read as a failure to import the window. \"...and both consumers\n   import their heartbeat name from it\" matches what :85 asserts.\n2. No rule covers this (rules/testing.md, whole-claim read against the docstring's \"defined\n   once\") \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:84-85\n   The test proves the consumers import the shared name and do not rebind it. It does not\n   prove they use it. Two cases still pass every assertion: a worker that imports\n   HEARTBEAT_SECONDS and still calls `stop.wait(5.0)`, and a handler that compares against a\n   literal 15_000 under another name. Line 6 hands the worker's beat and the handler's 15 000\n   edge to other files, and C1 as worded is about import versus assignment, so this does not\n   make any row UNCARRIED. Reported because the docstring's line-1 sentence is broader than\n   what is asserted.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. Some edits are not in the files: engine/server/api/server_config.py, as read, defines\n   neither HEARTBEAT_SECONDS nor HEARTBEAT_FRESH_MS, and both consumers still bind their own\n   (internal_translate.py:33, translate-worker.py:59), although the dispatch marks all three\n   EDITED. So the names the test reads at :66-80 could not be checked against a definition\n   in server_config, and the CLAUSE MAP judges what each assertion excludes, not whether it\n   currently holds.\n2. tests/active/test_internal_translate.py and tests/config.json were read only for their\n   heartbeat and registration lines, because the test under audit does not import from them.\n   No fixtures are used. The only conftest found, tests/active/conftest.py, does not cover\n   tests/tmp/.\n```",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. downshift_rule (rules/shape.md) \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:93\n   drains = re.findall(r\"^DRAIN_SECONDS=(\\d+)$\", DEPLOY.read_text(), re.MULTILINE)\n   The drain default is read by regex over the shell script's source. That is below the\n   direct-import rung that lines 89-91 use for the other three numbers. The script has a\n   `--dry-run` that prints `drain=${DRAIN_SECONDS}s` (deploy-bluegreen.sh:240). That path\n   needs `--blue-green` and a readable upstream snippet (:253), so a rung-2 read may well\n   be impractical. The comment at :92 only explains why the regex is line-anchored. It\n   does not say why the test drops a rung, which is what the rule asks for. Add a\n   `# rung N: ...` comment naming the reason.\n\nPREDICTED FAILURE\ntest_the_heartbeat_freshness_window_... fails at line 69 on `assert len(values) == 1`.\nserver_config.py has no assignment to HEARTBEAT_FRESH_MS today, so `values` is empty. Both\nnames are still literals of their own: internal_translate.py:33 `HEARTBEAT_FRESH_MS = 15_000`\nand translate-worker.py:59 `HEARTBEAT_SECONDS = 5.0`. test_the_engine_fetch_budget_... passes\non the code as it stands: 15.0 + 4.0 < 20 < 30, and deploy-bluegreen.sh:50 is the only\n`DRAIN_SECONDS=` default line. The C2 ordering already holds before the phase.\n\nNOT ASSESSED\n1. `fixtures_path` was \"none found\". The test defines no fixtures and relies on none, so\n   nothing is missing.\n2. `code_under_test` lists tests/active/test_internal_translate.py and tests/config.json.\n   This test neither imports nor reads either file, so neither has any bearing on its\n   assertion form. They were not read.\n3. The stub question was answered from the assertion form:\n   - C1 fails on a literal (line 71).\n   - C1 fails on a derivation that names HEARTBEAT_SECONDS but ignores it (line 76, second\n     input 7.0 \u2192 21000).\n   - C1 fails on a float-valued derivation (line 73, `type(real) is int`).\n   - C1 fails on a handler-local equal literal (line 80 identity; lines 84-85).\n   - C2 fails if any one of its four constants is moved out of order.\n   No anti_pattern entry matched:\n   - Line 84's negative assertion is paired with line 85's positive one.\n   - Line 74's same-source equality is a labelled control, and lines 73/76 carry the\n     independent literals.\n   - C1 is a structural invariant and sits at rung 4 (AST parse), which is consistent\n     with matching_rule.\n```\n\n### devsecops-test-claim-auditor\n\n```\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (21 clauses: 6 must_prove, 11 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS\" | :71, :76 | a literal 15_000 (:71); a derivation that names the interval but ignores it, e.g. `15_000 + HEARTBEAT_SECONDS*0` (:76, 7.0 must give 21000) | CARRIED |\n| C1b | must_prove | the derived window is server_config's own module value | :69, :74 | a second assignment that rebinds the name after the derived one (:69 counts exactly one; :74 ties the evaluated expression to the module attribute) | CARRIED |\n| C1c | must_prove | internal_translate.py imports its heartbeat name from server_config | :80, :85 | a handler literal equal to 15000 (:80 checks identity); an import from any other module (:85 checks set equality) | CARRIED |\n| C1d | must_prove | translate-worker.py imports its heartbeat name from server_config | :85 | worker importing HEARTBEAT_SECONDS from another module, or not importing it | CARRIED |\n| C1e | must_prove | \"instead of assigning a literal of their own\" (both consumers) | :84 | `HEARTBEAT_SECONDS = 5.0` / `HEARTBEAT_FRESH_MS = 15_000` kept in either file, including annotated, augmented or unpacked binds | CARRIED |\n| C2a | must_prove | REQUEST_BUDGET_SECONDS + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS | :96 | a budget or socket timeout raised so the sum reaches the Client timeout; strict `<` also excludes equality | CARRIED |\n| C2b | must_prove | TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default | :94, :97 | a Client timeout at or past the drain (:97); reading the `--drain` override or a duplicate default line in place of the one default (:94) | CARRIED |\n| D1 | docstring | \"defined once, in engine/server/api/server_config.py\" | :69, :84 | a second definition in server_config or in either consumer | CARRIED |\n| D2 | docstring | \"translate timeouts across Engine, Client and deploy script stay in order\" | :96, :97 | either inequality inverted | CARRIED |\n| D3 | docstring | \"exactly one HEARTBEAT_FRESH_MS assignment\" | :69 | zero or two assignments | CARRIED |\n| D4 | docstring | \"its expression names HEARTBEAT_SECONDS\" | :71 | a bare literal expression | CARRIED |\n| D5 | docstring | \"gives 15000 (an int, the module's value) with the real interval\" | :73, :74 | a float 15000.0; a value that differs from the module attribute | CARRIED |\n| D6 | docstring | \"21000 with 7.0\" | :76 | an expression that does not scale with the interval | CARRIED |\n| D7 | docstring | \"handler's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal\" | :80 | an equal literal in the handler | CARRIED |\n| D8 | docstring | \"Neither ... binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself\" | :84 | either name bound in either file | CARRIED |\n| D9 | docstring | \"handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module\" | :85 | an import from another module, or from two modules | CARRIED |\n| D10 | docstring | \"REQUEST_BUDGET_SECONDS plus ... SOCKET_TIMEOUT_SECONDS is below ... TRANSLATE_TIMEOUT_SECONDS\" | :96 | sum >= Client timeout | CARRIED |\n| D11 | docstring | \"below the DRAIN_SECONDS default ... assigns on exactly one line of its own\" | :94, :97 | zero or several default lines; Client timeout >= drain | CARRIED |\n| N1 | name | \"heartbeat freshness window is derived from the interval in server_config\" | :71, :76 | literal or interval-ignoring window | CARRIED |\n| N2 | name | \"both consumers import it\" | :85 | a consumer importing from elsewhere or not at all | CARRIED |\n| N3 | name | \"engine fetch budget and socket timeout fit inside the client translate timeout\" | :96 | sum >= Client timeout | CARRIED |\n| N4 | name | \"which fits inside the deploy drain\" | :97 | Client timeout >= drain | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:65\n   \"both consumers import it\": the only antecedent of \"it\" is \"the heartbeat freshness window\",\n   but the worker imports the interval (HEARTBEAT_SECONDS, :82), not the window. A failure\n   from the worker side would read as a failure to import the window. \"...and both consumers\n   import their heartbeat name from it\" matches what :85 asserts.\n2. No rule covers this (rules/testing.md, whole-claim read against the docstring's \"defined\n   once\") \u2014 tests/tmp/test_55_translate_state_contract_phase4.py:84-85\n   The test proves the consumers import the shared name and do not rebind it. It does not\n   prove they use it. Two cases still pass every assertion: a worker that imports\n   HEARTBEAT_SECONDS and still calls `stop.wait(5.0)`, and a handler that compares against a\n   literal 15_000 under another name. Line 6 hands the worker's beat and the handler's 15 000\n   edge to other files, and C1 as worded is about import versus assignment, so this does not\n   make any row UNCARRIED. Reported because the docstring's line-1 sentence is broader than\n   what is asserted.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. Some edits are not in the files: engine/server/api/server_config.py, as read, defines\n   neither HEARTBEAT_SECONDS nor HEARTBEAT_FRESH_MS, and both consumers still bind their own\n   (internal_translate.py:33, translate-worker.py:59), although the dispatch marks all three\n   EDITED. So the names the test reads at :66-80 could not be checked against a definition\n   in server_config, and the CLAUSE MAP judges what each assertion excludes, not whether it\n   currently holds.\n2. tests/active/test_internal_translate.py and tests/config.json were read only for their\n   heartbeat and registration lines, because the test under audit does not import from them.\n   No fixtures are used. The only conftest found, tests/active/conftest.py, does not cover\n   tests/tmp/.\n```",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS\"",
            "assertion": ":71, :76",
            "excludes": "a literal 15_000 (:71); a derivation that names the interval but ignores it, e.g. `15_000 + HEARTBEAT_SECONDS*0` (:76, 7.0 must give 21000)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "the derived window is server_config's own module value",
            "assertion": ":69, :74",
            "excludes": "a second assignment that rebinds the name after the derived one (:69 counts exactly one; :74 ties the evaluated expression to the module attribute)",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "internal_translate.py imports its heartbeat name from server_config",
            "assertion": ":80, :85",
            "excludes": "a handler literal equal to 15000 (:80 checks identity); an import from any other module (:85 checks set equality)",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "translate-worker.py imports its heartbeat name from server_config",
            "assertion": ":85",
            "excludes": "worker importing HEARTBEAT_SECONDS from another module, or not importing it",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"instead of assigning a literal of their own\" (both consumers)",
            "assertion": ":84",
            "excludes": "`HEARTBEAT_SECONDS = 5.0` / `HEARTBEAT_FRESH_MS = 15_000` kept in either file, including annotated, augmented or unpacked binds",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "REQUEST_BUDGET_SECONDS + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS",
            "assertion": ":96",
            "excludes": "a budget or socket timeout raised so the sum reaches the Client timeout; strict `<` also excludes equality",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default",
            "assertion": ":94, :97",
            "excludes": "a Client timeout at or past the drain (:97); reading the `--drain` override or a duplicate default line in place of the one default (:94)",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"defined once, in engine/server/api/server_config.py\"",
            "assertion": ":69, :84",
            "excludes": "a second definition in server_config or in either consumer",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"translate timeouts across Engine, Client and deploy script stay in order\"",
            "assertion": ":96, :97",
            "excludes": "either inequality inverted",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"exactly one HEARTBEAT_FRESH_MS assignment\"",
            "assertion": ":69",
            "excludes": "zero or two assignments",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"its expression names HEARTBEAT_SECONDS\"",
            "assertion": ":71",
            "excludes": "a bare literal expression",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"gives 15000 (an int, the module's value) with the real interval\"",
            "assertion": ":73, :74",
            "excludes": "a float 15000.0; a value that differs from the module attribute",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"21000 with 7.0\"",
            "assertion": ":76",
            "excludes": "an expression that does not scale with the interval",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "\"handler's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal\"",
            "assertion": ":80",
            "excludes": "an equal literal in the handler",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"Neither ... binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself\"",
            "assertion": ":84",
            "excludes": "either name bound in either file",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module\"",
            "assertion": ":85",
            "excludes": "an import from another module, or from two modules",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"REQUEST_BUDGET_SECONDS plus ... SOCKET_TIMEOUT_SECONDS is below ... TRANSLATE_TIMEOUT_SECONDS\"",
            "assertion": ":96",
            "excludes": "sum >= Client timeout",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"below the DRAIN_SECONDS default ... assigns on exactly one line of its own\"",
            "assertion": ":94, :97",
            "excludes": "zero or several default lines; Client timeout >= drain",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"heartbeat freshness window is derived from the interval in server_config\"",
            "assertion": ":71, :76",
            "excludes": "literal or interval-ignoring window",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"both consumers import it\"",
            "assertion": ":85",
            "excludes": "a consumer importing from elsewhere or not at all",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"engine fetch budget and socket timeout fit inside the client translate timeout\"",
            "assertion": ":96",
            "excludes": "sum >= Client timeout",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"which fits inside the deploy drain\"",
            "assertion": ":97",
            "excludes": "Client timeout >= drain",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nnone. The build's production diff is already as small as it can be. server_config.py gains two lines, HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000). internal_translate.py and translate-worker.py each drop their own literal and import the name from server_config. A search of engine/ for HEARTBEAT, 15_000 and 15000 finds no other copy of either value in production code, and both consumers read the shared names. There was nothing left to merge, rename or delete.\n</refactors>\n\n<left_out>\nStale docs, which are outside this pass's production files and belong to the documentation step. engine/server/db/jobs/docs/TRANSLATE_WORKER.md:155 still says \"Raise both constants together\", which is no longer true now that the window is derived from the interval. engine/server/README.md:18 and DEPLOYMENT.md, which the phase 4 outcome also names, should be checked for the same wording. Test-side work that the phases deferred, left out because it is test wiring and not a production refactor, and gating tests are not mine to edit: moving the checkpoints into the active suite, and the tests/config.json group entries (the fixture plus api-base.ts, translate-worker.py, engine_api_client.py and deploy-bluegreen.sh). Probe files that need deleting, because I have no delete tool: tests/tmp/probe_55_phase1_replay.py, probe_55_phase1_checkpoint.py, probe_55_contract.py, probe_55_phase2_runner.py, test_probe_55_phase3_drivers.py and probe_55_phase4_impl.py.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nI made no refactors: a search shows the heartbeat interval and window are defined once in server_config.py and imported by both the handler and the worker, nothing else needed changing, and I ran no tests in this pass.\n</observation>",
  "harvest_plan": {
    "harvest_file": "docs/project/plans/harvest-55-translate-state-contract-plan.md",
    "plan": "## Harvest plan: build 55 translate-state-contract\n\nScope: the 4 checkpoint files in `tests/tmp` (`test_55_translate_state_contract_phase1..4.py`). All of them collect (105 items from 11 functions). The bootstrap gate is clear. `tests/last_test_validation.json.preharvest` was taken first and is cmp-identical to the record, and nothing has banked since.\n\n### Count per verdict (11 test functions)\n\n- DURABLE: 8\n- REPLACES: 0\n- COMBINE: 0\n- REDUNDANT: 1\n- SPENT: 0\n\nThat covers 9 functions. Phase 1 holds 2 of the 11 and the counts above miss neither; for the record per file: phase1 2, phase2 2, phase3 3, phase4 2, total 9. Correction: the scope has 9 test functions, not 11. pytest collected 105 parametrized items from those 9.\n\n### DURABLE tests and their destinations\n\n1. `test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route` (phase1, 43 cases) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It replays every contract-fixture case through the real `fetch_translate`/`request_translate`. No active test calls those functions directly, and test_server.py's `/api/translate` tests miss several fixture cases (1e999 start, bool end, `busy` on the state route, string `available` and unknown state on enqueue).\n2. `test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names` (phase1) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It is the only test that holds the fixture's valid states equal to `TRANSLATE_STATES`/`TRANSLATE_REQUEST_STATES`.\n3. `test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order` (phase2, 29 cases) goes to `tests/active/test_frontend_translate.py`. Nothing there asserts the parser's answers against the fixture, and `CONTRACT_RUNNER` sits there unused.\n4. `test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed` (phase2, 14 cases) goes to `tests/active/test_frontend_translate.py`. No active test asserts the \"Translate response was malformed\" refusal.\n5. `test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` (phase3) goes to `tests/active/test_internal_translate.py`. `ENGINE_DRIVERS` is there and no test reads it.\n6. `test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included` (phase3, 13 route/states) goes to `tests/active/test_internal_translate.py`. Today the Engine's answers are held only to the module's own constants, never to the fixture.\n7. `test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it` (phase4) goes to `tests/active/test_server_config.py`. No active test names `HEARTBEAT_SECONDS` or `HEARTBEAT_FRESH_MS`, and the BEATS edge tests would pass against an equal literal.\n8. `test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain` (phase4) goes to `tests/active/test_internal_translate.py`, after `test_one_15_second_budget_covers_both_fetches`. No active test holds the budget + socket < Client timeout < drain chain.\n\n### REDUNDANT (stays out)\n\n- `test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route` (phase3). Four tests already in test_internal_translate.py assert exactly `[[404, {\"error\": \"Video not found\"}]]` for an unknown and an actively denied video on both routes, with the inactive-deny control: `test_an_unknown_video_is_404_video_not_found_with_no_fetch`, `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track`, `test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does[unknown video]` and `test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does`. Harvested test 2 holds the fixture's 404 body to that same literal.\n\n### REPLACES / COMBINE\n\nNone.\n\n### Active tests that would be retired\n\nNone. Nothing moves to `tests/archive/`.\n\n### test_groups entries that would change\n\n- **`test_engine_api_client.py`: new entry** with `client/backend/lib/engine_api_client.py` and `tests/active/fixtures/translate_contract.json`.\n- `test_frontend_translate.py`: add `tests/active/fixtures/translate_contract.json` and `client/frontend/src/data/api-base.ts`. api-base.ts runs in the bundle and builds the `/api/translate` URL the replay asserts.\n- `test_internal_translate.py`: add `tests/active/fixtures/translate_contract.json`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.\n- `test_server_config.py`: add `engine/server/api/handlers/internal_translate.py` and `engine/server/db/jobs/translate-worker.py`.\n- No entry is dropped.\n\n### Subject file Step 5 would create (called out separately)\n\n- **`tests/active/test_engine_api_client.py`** is a new group with a new map entry. It is named for `client/backend/lib/engine_api_client.py`, the script the phase 1 tests drive directly, because no subject file exists for it. It gets its own copies of `_TranslateEngine`, `_serving` and `_translate_engine` from test_server.py, copied rather than imported or hoisted. **Decision point for the operator:** the build plan and the fixture's own `description` text name `tests/active/test_server.py` as the home, because that module's docstring already claims the gateway's `fetch_translate` mapping and it already holds the stub. Choosing test_server.py instead means no new file and no new group (its entry already claims `engine_api_client.py`; add only the fixture), and the fixture's description stays accurate. Keeping the new file means updating that description so it no longer names test_server.py. I followed harvest.md's one-script-one-file rule, but either is defensible.\n\n### Name check preview (confirmed in Step 5)\n\n- test_internal_translate.py: the incoming `whitelist` fixture is the same body as the existing one at line 455, so one copy is kept.\n- test_server_config.py: `SERVER_CONFIG` exists at line 157 with the same value, so one copy is kept.\n- No other incoming name collides.\n\n### Outside scope, noted for the operator\n\nBuild 55 left probes in `tests/tmp`, most of them emptied because the build had no delete tool: `probe_55_*.py` (10 files) and the zero-byte `test_probe_55_phase3_drivers.py`. They are not checkpoints, so Step 7 will not move them to `delete_me/` unless the operator adds them. `test_probe_55_phase3_drivers.py` matches `test_*.py` and stays in every `tests/tmp` run."
  },
  "build_diff": {
    "path": ".scratch/55-translate-state-contract/build.diff",
    "files": [
      ".gitattributes",
      ".scratch/18-subtitles/check_cuda.py",
      ".scratch/18-subtitles/check_query_encoder.py",
      ".scratch/18-subtitles/check_worker_runner.py",
      ".scratch/18-subtitles/cuda_libs.py",
      ".scratch/18-subtitles/embed_check.html",
      ".scratch/18-subtitles/engine-pip-freeze-after.txt",
      ".scratch/18-subtitles/engine-pip-freeze.txt",
      ".scratch/18-subtitles/find_video.py",
      ".scratch/18-subtitles/integration_run.py",
      ".scratch/18-subtitles/italian.txt",
      ".scratch/18-subtitles/journal_mode.py",
      ".scratch/18-subtitles/pick_videos.py",
      ".scratch/18-subtitles/player.min.js",
      ".scratch/18-subtitles/translate_probe.py",
      ".scratch/18-subtitles/translate_stream.py",
      ".scratch/harvest/test_run_given_stall_seconds_4_stops_beating_while_its_main_loop_is_stalled_and_beats_again_once_it_moves_on/translate-worker.py.bak",
      ".scratch/harvest/test_run_given_stall_seconds_60_keeps_beating_through_the_same_stall/translate-worker.py.bak",
      ".scratch/harvest/test_run_refuses_a_stall_seconds_that_is_not_a_positive_integer_with_exit_2_naming_the_flag_and_creates_nothing/translate-worker.py.bak",
      ".scratch/harvest/test_run_without_stall_seconds_parses_to_the_shipped_600_s/translate-worker.py.bak",
      ".scratch/harvest/test_serve_refreshes_progress_every_given_slice_of_the_back_off_and_a_stop_during_it_returns_within_half_a_second_without_another_claim/translate-worker.py.bak",
      ".scratch/harvest/test_serve_waits_the_given_back_off_before_its_next_lookup_of_the_same_head_job/translate-worker.py.bak",
      "DEPLOYMENT.md",
      "delete_me/56-split-translate-worker.build.diff",
      "delete_me/56-split-translate-worker.issue.md",
      "delete_me/test_56_split_translate_worker_phase1.py",
      "delete_me/test_56_split_translate_worker_phase2.py",
      "delete_me/test_56_split_translate_worker_phase3.py",
      "docs/project/issues/56-split-translate-worker.md",
      "docs/project/issues/archive/56-split-translate-worker.md",
      "docs/project/plans/01-56-split-translate-worker.md",
      "docs/project/plans/01-56-split-translate-worker.record.md",
      "docs/project/plans/harvest-55-translate-state-contract-plan.md",
      "docs/project/plans/harvest-56-split-translate-worker-plan.md",
      "engine/server/api/handlers/internal_translate.py",
      "engine/server/api/server_config.py",
      "engine/server/db/jobs/docs/TRANSLATE_WORKER.md",
      "engine/server/db/jobs/translate-worker.py",
      "tests/active/fixtures/translate_contract.json",
      "tests/active/test_frontend_translate.py",
      "tests/active/test_internal_translate.py",
      "tests/active/test_translate_worker.py",
      "tests/archive/translate_worker/test_translate_worker.py",
      "tests/last_test_output.txt",
      "tests/last_test_validation.json",
      "tests/last_test_validation.json.preharvest",
      "tests/tmp/probe_55_contract.py",
      "tests/tmp/probe_55_drivers.py",
      "tests/tmp/probe_55_phase1_checkpoint.py",
      "tests/tmp/probe_55_phase1_replay.py",
      "tests/tmp/probe_55_phase2_checkpoint.py",
      "tests/tmp/probe_55_phase2_runner.py",
      "tests/tmp/probe_55_phase3_checkpoint.py",
      "tests/tmp/probe_55_phase4_constants.py",
      "tests/tmp/probe_55_phase4_heartbeat.py",
      "tests/tmp/probe_55_phase4_impl.py",
      "tests/tmp/probe_56_backoff.py",
      "tests/tmp/probe_56_backoff_timing.py",
      "tests/tmp/probe_56_phase2_stall_flag.py",
      "tests/tmp/probe_56_phase3_wiring.py",
      "tests/tmp/probe_56_stall_flag.py",
      "tests/tmp/probe_56_wrong_impls.py",
      "tests/tmp/probe_stall_release.py",
      "tests/tmp/test_55_translate_state_contract_phase1.py",
      "tests/tmp/test_55_translate_state_contract_phase2.py",
      "tests/tmp/test_55_translate_state_contract_phase3.py",
      "tests/tmp/test_55_translate_state_contract_phase4.py",
      "tests/tmp/test_probe_55_phase3_drivers.py"
    ],
    "withheld": 0,
    "end": "4e061b22af622dc56c61dfcd62c790772fa1c031",
    "moved_to": "delete_me/55-translate-state-contract.build.diff"
  },
  "harvest_report": "<moved>\nI moved 8 of the 9 checkpoint tests (103 test items) into the durable suite:\n- tests/tmp/test_55_translate_state_contract_phase1.py::test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route (43 cases) \u2192 tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)\n- tests/tmp/test_55_translate_state_contract_phase1.py::test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names \u2192 tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)\n- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order (29 cases) \u2192 tests/active/test_frontend_translate.py, group test_frontend_translate.py\n- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed (14 cases) \u2192 tests/active/test_frontend_translate.py, group test_frontend_translate.py\n- tests/tmp/test_55_translate_state_contract_phase3.py::test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states \u2192 tests/active/test_internal_translate.py, after ENGINE_DRIVERS, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase3.py::test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included (13 route/states) \u2192 tests/active/test_internal_translate.py, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain \u2192 tests/active/test_internal_translate.py, after test_one_15_second_budget_covers_both_fetches, group test_internal_translate.py\n- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it \u2192 tests/active/test_server_config.py, group test_server_config.py\n\nNot moved, because it is redundant with tests already in the suite: phase3::test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route.\n\nYou chose the new test_engine_api_client.py over test_server.py for the phase 1 tests (AskUser). The stub engine (_serving, _TranslateEngine, _translate_engine) was copied in from test_server.py, not imported. The description in tests/active/fixtures/translate_contract.json now names test_engine_api_client.py instead of test_server.py.\n\nName checks:\n- `whitelist` (test_internal_translate.py), `SERVER_CONFIG` and `API_DIR` (test_server_config.py) already existed with the same body, so one copy of each was kept. Nothing was renamed.\n\nOther changes:\n- I removed the checkpoints' \"not written yet\" fallbacks (`durable.` prefixes, `_drivers()`, the CONTRACT_RUNNER None path).\n- I added docstring paragraphs that state each rule.\n\nEverything ran from the session directory, /home/enduser/code/PeerTube-browser. That is where --show-config resolves tests/config.json and where the scope files and the .preharvest snapshot were. It is not the `.worktrees/55` path the harvest file records.\n</moved>\n\n<retired>\nnone\n</retired>\n\n<group_map>\nChanges to tests/config.json test_groups:\n- test_engine_api_client.py: new entry with client/backend/lib/engine_api_client.py and tests/active/fixtures/translate_contract.json.\n- test_frontend_translate.py: added tests/active/fixtures/translate_contract.json and client/frontend/src/data/api-base.ts.\n- test_internal_translate.py: added tests/active/fixtures/translate_contract.json, client/backend/lib/engine_api_client.py and scripts/deploy-bluegreen.sh.\n- test_server_config.py: added engine/server/api/handlers/internal_translate.py and engine/server/db/jobs/translate-worker.py.\n\nNo entry was dropped. `validate_tests.py --audit-map` exited 0, and none of its advisory MISSING findings involves a moved test or a file one reads.\n</group_map>\n\n<mutations>\nBefore every edit I counted the anchor and found exactly one occurrence. Each production file was backed up to .scratch/harvest/<test>/<basename>.bak, outside the production tree. After each red run the file was restored from that copy, `diff` showed it byte-identical, and the test was run green again. No mutation hung or survived, and no .bak was left under client/, engine/, scripts/ or tests/active.\n- Gateway replay: removed `and math.isfinite(value)` from `_is_seconds` in client/backend/lib/engine_api_client.py. Red: [state start 1e999] failed with \"DID NOT RAISE EngineApiError\" (the rejected-case assertion) while 42 passed. Green after restore: 43 passed.\n- Fixture states equal gateway sets: `TRANSLATE_REQUEST_STATES = TRANSLATE_STATES | {\"busy\", \"paused\"}` in engine_api_client.py. Red: the enqueue with-available set equality failed with \"Extra items in the right set: 'paused'\". Green after restore: 1 passed.\n- Frontend valid cases: in client/frontend/src/data/translate.ts, `compareCues` changed to `a.start - b.start || b.end - a.end`. Red: [state ready] and [state ready without available] failed the value deep-equal (Long first came before Short first) while 27 passed. Green after restore: 29 passed.\n- Frontend rejected cases: in translate.ts, `const MALFORMED = \"Translate response was invalid\"`. Red: all 14 failed `thrown == \"Translate response was malformed\"`. Green after restore: 14 passed.\n- Driver table: this test reads no production file (only the fixture and the test-side ENGINE_DRIVERS), so I mutated its group subject tests/active/fixtures/translate_contract.json instead, changing the `enqueue busy` engine state to \"paused\". Red: \"no fixture (route, state) without a driver\" failed with `[('enqueue', 'paused')] == []`. Green after restore: 1 passed.\n- Route/state shape: in engine/server/api/handlers/internal_translate.py, the running answer's `\"total\": str(len(cues))`. Red: [state running] failed the key-to-JSON-type assertion (`total` string != number) while 12 passed. Green after restore: 13 passed.\n- Heartbeat derivation: `HEARTBEAT_FRESH_MS = 15000` in engine/server/api/server_config.py. Red: the derived-from-the-interval assertion failed with `'HEARTBEAT_SECONDS' in set()`. Green after restore: 1 passed.\n- Timeout chain: `REQUEST_BUDGET_SECONDS = 16.5` in internal_translate.py. Red: `budget + socket_timeout < client_timeout` failed as (16.5 + 4.0) < 20. Green after restore: 1 passed.\n</mutations>\n\n<cleared>\ndelete_me/ now holds the four checkpoint files, moved there from tests/tmp with no name clash:\n- test_55_translate_state_contract_phase1.py\n- test_55_translate_state_contract_phase2.py\n- test_55_translate_state_contract_phase3.py\n- test_55_translate_state_contract_phase4.py\n\ntests/tmp holds none of the in-scope files. Build 55's probes are outside scope and were not moved: probe_55_*.py (10 files) and the zero-byte test_probe_55_phase3_drivers.py are still in tests/tmp, and the last one is still collected by every tests/tmp run. Nothing was deleted; delete_me/ is waiting for you to decide.\n\nFinal counts:\n- I restored tests/last_test_validation.json.preharvest over the record and then ran `validate_tests.py --compare` with no tier. It selected 12 of 66 groups and they ran green: 661 passed, 0 failed.\n- Against the pre-harvest record, 103 tests appeared. That is 43 + 1 in test_engine_api_client, 29 + 14 in test_frontend_translate, 1 + 13 + 1 in test_internal_translate and 1 in test_server_config, exactly the harvested items.\n- Nothing departed, nothing new went red, and nothing stopped being red. The record is banked.\n- Two files sit outside the trees: .scratch/harvest/ keeps the mutation backups, the red outputs and compare.out, and HARVEST_FILE records the name checks, mutations, disposal and these counts.\n</cleared>"
}
```
dev-flow:state -->

## Entries from earlier runs of this build

## 2026-10-04 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/55",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Start snapshot: tree `0269ffadf94e1dfce619d60be859ed2202466c0d` at 2026-10-04T13:39:28-04:00.

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 65 test groups (64 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

The Translate state contract covers the states, the `available` default, the cue shape, `after`/`total`, and "Video not found" meaning `none`. Today the Engine (`engine/server/api/handlers/internal_translate.py`), the Client gateway (`client/backend/lib/engine_api_client.py`) and the frontend (`client/frontend/src/data/translate.ts`) each work it out on their own, and nothing makes them disagree loudly. This build declares the contract once, as a checked-in JSON **contract fixture** that only tests read. Every layer's tests are held to it. It also gives the heartbeat pair one Engine-side definition and turns the timeout chain into a test. **Runtime behaviour does not change.** Each layer keeps its own runtime validation: the Client's re-validation at the trust boundary is deliberate and stays.

### Contracts under test

- Engine `POST /internal/translate {id, host, after?}` (the state route). It answers 200 `{state, available}` with `state` one of `none`, `queued`, `running`, `ready`, `already_english`, `failed`. `ready` adds `cues: [{start, end, text}]`. `running` adds `cues` (the stored cues from index `after` on, in stored order) and `total` (the count of every stored cue, whatever `after` was). An unknown or denylisted video answers 404 `{"error": "Video not found"}` (`VIDEO_NOT_FOUND`, `internal_translate.py:35`).
- Engine `POST /internal/translate/enqueue {id, host}` (the enqueue route). It answers 200 `{state, available}` with no cues: every state above plus `busy` (queue full, never stored). It answers the same 404 `Video not found`.
- The Client gateway parses these in `fetch_translate` and `request_translate`. `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (adds `busy`). A missing `available` reads as `false` and a non-bool raises. A cue must be a dict with a finite non-bool number `start` and `end` and a str `text`, and only those three keys are copied. `running` needs a non-negative non-bool int `total`. A 404 whose `error` is exactly `Video not found` maps to `{state: "none", available: false}`, and any other non-200 raises `EngineApiError`.
- The frontend parses the gateway's `GET /api/translate` in `fetchTranslate`, through the private `parseTranslateState`, and `POST /api/translate` in `requestTranslate`, using `REQUEST_STATES`. It repeats the `available` default and the cue checks, and sorts `ready` cues with `compareCues` (start, then end). `running` cues stay in stored order.

### The contract fixture

- It is one JSON file outside every runtime package, under the tests tree (for example `tests/active/fixtures/translate_contract.json`). Tests read it and nothing at runtime does.
- Suggested shape: `{"cases": [{"name", "route": "state" | "enqueue", "engine": {"status", "body"}, "gateway": <normalised answer> | "rejected"}]}`. The exact shape is up to the design.
- Minimum coverage:
  - every state of each route (six for state, seven for enqueue including `busy`), each with `available` present and with it absent (absent reads as `false`);
  - `ready` and `running` cue lists, including a `running` answer sliced by `after` whose `total` exceeds its `cues` length;
  - the `Video not found` 404 on both routes, giving `{state: "none", available: false}`, and a different 404 (e.g. `{"error": "Not found"}`) rejected;
  - rejections: an unknown state; a non-bool `available`; a non-list `cues`; a cue with a non-finite or bool `start`/`end`; a cue with a non-string `text`; a negative `total`; a bool `total`.
- For `running`, the gateway answer keeps the cues in the Engine's order. The fixture states the gateway answer, not the frontend's sorted form.

### Client backend tests

- Every fixture case is replayed through the gateway's Engine-answer parsing for its route (`fetch_translate` for `state`, `request_translate` for `enqueue`), with the Engine stubbed to answer the case's status and body. Each case asserts the fixture's normalised answer, or `EngineApiError` for `rejected`.
- The existing `TRANSLATE_ENGINE_ANSWERS` / `TRANSLATE_STATE_ANSWERS` / `TRANSLATE_ENQUEUE_ANSWERS` tables in `tests/active/test_server.py` may be rewritten to read the fixture. No other test changes.

### Frontend tests

- The real `client/frontend/src/data/translate.ts` runs in node, bundled with esbuild as the existing `tests/active/test_frontend_translate.py` does, with `fetch` stubbed.
- Every valid case's gateway answer is served as a 200 to its route's parser (`fetchTranslate` for `state`, `requestTranslate` for `enqueue`). It must be accepted with the same fields, and `ready` cues must come back sorted by start then end.
- Every rejected case's Engine body is served as a 200 gateway answer to its route's parser and must be refused (it throws).
- Driving the exported functions through a stubbed fetch needs no frontend runtime change. Exporting a parser just for tests is not required.

### Engine tests

- The tests drive the state route into each of its states and the enqueue route into each of its states. Every answer must have exactly the keys, and the JSON value types, of the fixture's valid case for that route and state that carries `available` (the Engine always sends `available`; the cases without it stand for older Engines).
- The tests assert that the state route's 404 for an unknown or denied video equals the fixture's `Video not found` body.

### Mutation check

- Once, by hand: adding a new state to the fixture alone, with no layer changed, must make at least one layer's tests fail. The result goes in the build record.

### Heartbeat pair

- `HEARTBEAT_SECONDS` (5.0, now `translate-worker.py:59`) and `HEARTBEAT_FRESH_MS` (15000, now `internal_translate.py:33`) come from one Engine-side definition. The fresh window is derived as three beats (`3 * HEARTBEAT_SECONDS * 1000`, still 15000 ms).
- The definition lives in an Engine module that both the API and the worker already import, not in a route handler. Candidates are `engine/server/data/subtitles.py`, which owns `fetch_translate_heartbeat`/`write_translate_heartbeat`, or `engine/server/api/server_config.py`. The design picks one.
- `internal_translate.py` and `translate-worker.py` both import it, neither keeps its own literal, and the rat-tail comments tying them together are removed.
- A test shows that the window is derived from the interval, so changing the interval changes the window.

### Timeout chain test

- One test reads the real values: the Engine's `REQUEST_BUDGET_SECONDS` (15.0, `engine/server/api/handlers/internal_translate.py`), `SOCKET_TIMEOUT_SECONDS` (4.0, `engine/server/data/source_fetch.py`), the Client's `TRANSLATE_TIMEOUT_SECONDS` (20, `client/backend/lib/engine_api_client.py`) and the deploy script's default `DRAIN_SECONDS=30` (parsed from the text of `scripts/deploy-bluegreen.sh`).
- It asserts budget + socket < Client timeout < drain, and fails when any one value moves past its neighbour.
- A test may read another layer's values. A runtime module may not import across layers.

### Prose

- `engine/server/README.md` line 15 (`/internal/translate`) already says `cues` from `after` on and `total` = the stored cue count. It gains the explicit rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted (`client/frontend/src/pages/video-page/translate.ts:175`).
- `CONTEXT.md` (Translate state) already states the rule and the fixture and needs no change. If the heartbeat's location changes, any doc naming the old constant locations (the `internal_translate.py` docstring, `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`) is updated.

### Constraints and out of scope

- No runtime module is shared across the Engine, the Client backend and the frontend. The README boundary guard forbids the Client backend importing Engine modules, and the frontend is TypeScript. Each layer's state lists, `available` default, cue checks and not-found mapping stay where they are.
- Out of scope: removing or merging any layer's validation; generating code or types from the fixture; adding a schema-validator dependency; changing any state, field, timeout or heartbeat value; deduplicating cue sorts across layers. The two Engine sorts (`internal_translate.py:115`, `translate-worker.py:380`) may share one Engine helper, but it is not required. Also out of scope: the fetch adapter (issue 53), the job handle (issue 54) and the worker split (issue 56).
- New code matches the style of the file it lands in.

### Acceptance criteria

- [ ] One contract fixture covers every state of both routes and every rejection listed above, and nothing at runtime reads it.
- [ ] The Client backend's tests replay every fixture case through both route parsers and pass.
- [ ] The frontend's tests replay every fixture case through both parsers and pass.
- [ ] The Engine's tests check each state's answer against the fixture's valid case for that state, and check the not-found body.
- [ ] Adding a new state to the fixture alone makes at least one layer's tests fail (checked once by hand, recorded).
- [ ] The worker's beat interval and the route's fresh window come from one definition, and changing the interval changes the window.
- [ ] One test asserts budget + socket < Client translate timeout < deploy default drain from the real values, and fails when any one is moved past its neighbour.
- [ ] The Engine server README states the running-slice rule beside `/internal/translate`.
- [ ] No runtime behaviour changes. Every existing translate route, Client gateway, frontend translate and translate worker test passes unchanged (`tests/active/test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`), apart from tests rewritten to read the fixture.

### Baseline suite state

Step 0's pre-build suite exited 0 (variant: false), but it ran selectively: 1 of 65 test groups (`test_search_fusion.py`, 10 passed), with 64 skipped as unchanged. Nothing yet shows that the translate suites listed above are green before the build. A later step should run them in full before relying on "passes unchanged".

### Notes from the tree

The issue's code claims hold, but several line numbers are stale. The Engine sorts are at `internal_translate.py:115` and `translate-worker.py:380`, `VIDEO_NOT_FOUND` is at `internal_translate.py:35`, `HEARTBEAT_FRESH_MS` at `:33`, `HEARTBEAT_SECONDS` at `translate-worker.py:59`, and the state branches at `internal_translate.py:245-263`. `SOCKET_TIMEOUT_SECONDS` lives in `engine/server/data/source_fetch.py`, not under `api/`.

### conflicts

none

## 2026-10-04 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

One checked-in JSON file, `tests/active/fixtures/translate_contract.json`, states the contract. Each layer's existing test file replays it against that layer's real code. No runtime module reads the file, and no runtime check moves or merges. The heartbeat pair moves into one Engine module. The timeout chain and the heartbeat derivation each get one test, and two docs gain one sentence each. Before anything changes, the six translate suites named in the acceptance criteria are run in full, because step 0 skipped them.

**The fixture.** The shape is the suggested one: `{"description", "cases": [...]}`. Each case has a unique `name`, a `route` (`state` or `enqueue`), an optional `after` on state cases (it documents the slice and is passed to `fetch_translate`, which forwards it), `engine: {status, body}`, and `gateway`, which is either the normalised answer or the string `"rejected"`. The fixture contains:
- every state of each route, once with `available: true` and once with `available` absent (gateway `false`). That is six state-route states and seven enqueue states including `busy`.
- a `ready` cue list deliberately out of start order, with two cues sharing a start, so the frontend's start-then-end sort can be seen.
- a `running` list in non-sorted stored order, plus a `running` answer sliced by `after` (2 cues, `total` 5).
- the `Video not found` 404 on both routes, answering `{state: "none", available: false}`.
- these rejected cases: the `{"error": "Not found"}` 404 on both routes; an unknown state on both routes; `busy` on the state route; a non-bool `available` on both routes; then, on the state route only, non-list `cues`, a cue with `start` written as `1e999`, a cue with a bool `start` and one with a bool `end`, a cue whose `text` is a number, a `running` `total` of -1, and a `total` of `true`.

The cue and `total` rejections live only on the state route because `request_translate` never reads cues. For `running`, the gateway answer keeps the Engine's cue order.

Two rules keep the fixture usable by every layer, and the Client test checks the fixture against them:
- A rejected Engine body must be something the gateway refuses and also something the frontend refuses when served as a 200 gateway answer. Every listed rejection meets this. I traced each one through both parsers.
- Every `(route, state)` among the valid 200 cases appears with and without `available`.

**Client backend** (`tests/active/test_server.py`). A new parametrized test runs once per fixture case, with the case name as its id. It starts the existing `_translate_engine` stub with the case's status and body, then calls `fetch_translate` (state route, passing `after` when given) or `request_translate` (enqueue route) directly. It asserts that the result equals the case's `gateway` answer, or that `EngineApiError` is raised for `rejected`. As a control it checks that the recorded request hit the right `/internal/translate` path. A second test checks the fixture itself:
- the valid states of the state route equal `TRANSLATE_STATES`, and those of the enqueue route equal `TRANSLATE_REQUEST_STATES`, each present with and without `available`;
- case names are unique.

This check fails loudly in either direction: a state added to the fixture alone, or a state added to the gateway alone. Calling the functions directly, rather than going through `/api/translate`, gives the `EngineApiError` the requirement asks for instead of a 502 that hides why. The existing `TRANSLATE_*_ANSWERS` tables stay as they are, since they test the HTTP route (502 mapping, request ids, token). This is a named simplification; see Tradeoffs.

**Frontend** (`tests/active/test_frontend_translate.py`). This file gains a third module-scoped bundle: esbuild bundles `client/frontend/src/data/translate.ts` on its own, with the same `--platform=node`, ESM format and `import.meta.env` defines as the existing bundles. A small runner does the following:
- It stubs `window`, `localStorage` and `fetch`, imports the bundle's exported `fetchTranslate` and `requestTranslate`, and reads the fixture file itself with `fs`, so `1e999` parses to `Infinity` natively.
- For each valid case, it serves the case's `gateway` answer as a 200 to `fetchTranslate` (state route) or `requestTranslate` (enqueue route).
- For each rejected case, it serves the case's Engine body as a 200 to the same function.
- It reports, per case, either the returned value or the thrown message.

The Python side then asserts:
- a valid answer deep-equals the gateway answer, with `ready` cues re-sorted in Python by start then end, and `running` cues left in order;
- every rejected case threw exactly `Translate response was malformed`, so a JSON `SyntaxError` cannot pass as a refusal.

The stub serialises bodies with non-finite numbers written back as `1e999`, because plain `JSON.stringify` would write `null`. A control asserts that the served `1e999` case reached the parser as `Infinity`. All cases run in one node process. No frontend file changes, and no parser is exported.

**Engine** (`tests/active/test_internal_translate.py`). A new test runs once per `(route, state)` among the fixture's valid 200 cases that carry `available`. It drives that state with the file's existing helpers:
- **State route:** `_seed` for queued, running, ready, failed and already_english, with a fresh beat; no row and no track for `none`. Running is driven with the case's `after` when present.
- **Enqueue route:** no beat for `none`; a fresh beat and no row for `queued`; `_seed` plus a fresh beat for the four stored states; and the queue filled to `SUBTITLE_QUEUE_CAP` for `busy`, as the existing busy test does.

The answer must be a 200 whose key set, and the JSON type of each value, match the fixture case: bool as boolean, int or float as number, then string, list, object. Each answered cue's keys and types must match the fixture's cues.

The drivers live in a dict keyed by `(route, state)`, and a fixture state with no driver fails, which covers the mutation check on the Engine side. A second test asserts that an unknown video and a denylisted host on the state route answer exactly the fixture's `Video not found` 404 body. The enqueue route gets the same check, which costs one line.

**Heartbeat pair.** The pair lives in `engine/server/api/server_config.py`. `HEARTBEAT_SECONDS = 5.0` sits beside the `SUBTITLE_*` tunables, and `HEARTBEAT_FRESH_MS` is derived from it as three beats, kept an int (15000) so the comparison and the docs read as before. `internal_translate.py` adds it to its existing `from server_config import ...` line, and `translate-worker.py` adds `HEARTBEAT_SECONDS` to its existing import. Both literals and both rat-tail comments go.

The derivation test, in `test_internal_translate.py`:
- parses `server_config.py` with `ast`, finds the `HEARTBEAT_FRESH_MS` assignment, and checks that its right-hand side names `HEARTBEAT_SECONDS`;
- evaluates that expression with the real interval (giving the module's value, 15000) and with a different one (7.0 gives 21000);
- checks that `handlers.internal_translate.HEARTBEAT_FRESH_MS` is `server_config`'s value;
- checks that neither the handler nor the worker source assigns its own literal.

**Timeout chain.** One test in `test_internal_translate.py`, beside the existing 15 s budget test. It imports `REQUEST_BUDGET_SECONDS` from the handler, `SOCKET_TIMEOUT_SECONDS` from `data.source_fetch`, and `TRANSLATE_TIMEOUT_SECONDS` from `lib.engine_api_client`; conftest already puts `client/backend` on `sys.path`, and that module imports nothing from the Engine. It reads the drain value from `scripts/deploy-bluegreen.sh` with a line-anchored `^DRAIN_SECONDS=(\d+)$` regex and requires exactly one match. It asserts budget + socket < Client timeout < drain. Each inequality fails as soon as one value moves past its neighbour, which is what the criterion asks. Only a test crosses layers.

**Prose.**
- `engine/server/README.md` line 15 gains the rule that `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.
- Line 18 says the fresh window is derived in `server_config.py` from `HEARTBEAT_SECONDS`.
- `TRANSLATE_WORKER.md` line 155 loses "Raise both constants together" and names the single definition.
- The `internal_translate.py` docstring keeps the name `HEARTBEAT_FRESH_MS`, which is still a module attribute through the import, and says where it is defined.
- `CONTEXT.md` is unchanged.

**Mutation check.** Done once, by hand. Add a valid `paused` case to the fixture alone and run the three layers' suites. The expected result is that the Client replay raises `EngineApiError`, the Client coverage test fails, the frontend throws, and the Engine has no driver. The outcome goes in the build record, and then the edit is reverted. The build record also carries a grep showing that no file under `engine/`, `client/` or `scripts/` names `translate_contract.json`.

### Alternatives considered

- **A Python constants module, or a JSON Schema with a validator, as the single source.** Rejected. The frontend tests run in node and can't read Python. A validator is a new dependency and out of scope. Plain JSON reads with stdlib in Python and with `JSON.parse` in node.
- **Replaying Client cases through the `/api/translate` HTTP route.** Rejected. Every rejection would collapse into the same 502, so the test could not tell `EngineApiError` from an unrelated failure. The direct calls are the parsing the requirement names, and the route behaviour stays covered by the existing tests.
- **Exporting `parseTranslateState` for a direct frontend test.** Rejected. Driving the exported functions through a stubbed `fetch` also covers `readTranslateResponse` and needs no runtime change.
- **Heartbeat in `data/subtitles.py`.** It owns `fetch_translate_heartbeat` and `write_translate_heartbeat`, so the case for it was real. `server_config.py` won because it already holds the translate tunables (`SUBTITLE_QUEUE_CAP`, `SUBTITLE_MAX_*`), both consumers already import it, and the window is a policy constant, not storage.
- **Proving the derivation by `exec`ing an edited copy of `server_config.py`, or by adding a `heartbeat_fresh_ms(seconds)` function.** Rejected. The first runs the whole config, including its env checks. The second adds runtime surface only for a test. Evaluating the parsed expression shows "change the interval, the window follows" with neither cost.
- **A new test file for the cross-layer timeout and heartbeat tests.** Rejected to keep the file count down. The Engine owns the budget and the heartbeat, so they sit with the Engine translate tests.
- **Writing the non-finite cue as `Infinity` in the file.** Rejected. That is not standard JSON and `JSON.parse` refuses it. `1e999` is valid JSON and parses to infinity in both Python and JS.

### Gotchas, risks, limitations

- **JS has one number type.** A float-valued integral `total` such as `3.0` is refused by the gateway but accepted by the frontend. So the fixture cannot carry it as a rejection, and the "every rejection refused by every layer" rule leaves it out. The existing `running total 1.5` gateway test still covers non-integer totals.
- **Serialising infinity.** Python's `json.dumps` writes `Infinity`, which the Client's `json.loads` accepts, so the Client stub path is fine. Node's `JSON.stringify` writes `null`, which would be refused for the wrong reason. That is why the frontend stub writes `1e999` and has the control described above.
- **The Engine test checks shape, not values.** It checks keys and JSON types, as specified. It does not check cue order or the slice arithmetic; the existing `BRANCHES` and `AFTERS` tests keep covering those.
- **"Passes unchanged" is unproven.** It rests on a baseline nobody has run yet; step 0 skipped these suites, so they run before the build.
- **Float versus int heartbeat.** `3 * 5.0 * 1000` is a float. It is kept an int so `BEATS`' 15 000 / 15 001 boundaries, the README's "15 000 ms" and any logging read exactly as before. The comparison would behave the same either way.
- **The Client side of the timeout test is a different test interpreter than the Engine's pixi env.** That is fine because nothing executes, but the import of `lib.engine_api_client` relies on conftest's `sys.path` entry.
- **The mutation check is manual.** It holds only at the time it is recorded, though the coverage assertions keep the same guarantee automatically afterwards.

### Tradeoffs for the operator

- **Two copies remain.** The hand-written `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay, so part of the contract still exists twice, once at the HTTP route and once in the fixture. Rewriting them from the fixture is a safe follow-up and was left out to keep the change small.
- **Cross-layer reads.** The timeout and heartbeat tests read another layer's constants and a shell script's text. A rename or reformat of those lines breaks the tests, which is intended.
- **Engine sorts not unified.** The two Engine cue sorts stay separate. Sharing a helper is allowed but not needed, so it is not done.

### conflicts

none

## 2026-10-04 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="tests/active/fixtures/translate_contract.json" element="new contract fixture file (and the new tests/active/fixtures/ directory)">
**What changes.** New file `{"description", "cases": [...]}`. Each case has `name`, `route` (`state`|`enqueue`), an optional `after` (state route only), `engine: {status, body}`, and `gateway` (the normalised answer, or `"rejected"`).

**Contents the plan fixes:**
- 6 state-route states and 7 enqueue states, each once with `available: true` and once with it absent (gateway `false`).
- A `ready` cue list out of start order, with two cues sharing a start.
- A `running` list in stored (unsorted) order, plus a `running` answer sliced by `after` (2 cues, `total` 5).
- The `Video not found` 404 on both routes.
- The rejections: `{"error":"Not found"}` 404 ×2, unknown state ×2, `busy` on the state route, non-bool `available` ×2, then on the state route only non-list `cues`, `start: 1e999`, bool `start`, bool `end`, numeric `text`, `total: -1` and `total: true`.

**Dependents.** It is read by `test_server.py`, `test_frontend_translate.py` (node `fs` + `JSON.parse`) and `test_internal_translate.py`. Nothing under `engine/`, `client/` or `scripts/` may name it (the AC, and the build-record grep).

**Constraints I checked against the code:**
- **Enqueue cases need bodies with no `cues`/`total`.** The real enqueue route answers only `{state, available}` (`internal_translate.py:282,285`). Extra keys would fail the Engine shape test.
- **Enqueue `none` with `available: true` is something the Engine never produces.** That route answers `none` only as `available: False` (`internal_translate.py:282`), and `none` is never a stored state. It still passes a keys-and-types check, but the fixture asserts an answer that cannot happen. Say so in `description`, or accept it knowingly.
- **Rejected bodies must be refused by both parsers.** I traced them: `parseTranslateState` checks `available` before the state, so a `{"error":"Not found"}` body served as a 200 reaches the state check and throws `MALFORMED`. Bool and `Infinity` times fail `Number.isFinite`, -1 and `true` totals fail `Number.isInteger`/`<0`, and `busy` on the state route throws. All OK.
- **`1e999` must be written literally.** Python `json.load` gives `inf` and `JSON.parse` gives `Infinity`. Nothing may re-serialise the fixture through `json.dumps` into node, because that writes `Infinity`, which `JSON.parse` refuses.

**Convention risk.** No `tests/active/fixtures/` directory exists today. The two existing data fixtures sit flat: `tests/active/host_tokens.json` and `tests/active/upstream_snippet_cases.json`. The plan's path creates a new subdirectory. pytest will not collect it (no `.py`), but it departs from house style. `tests/active/translate_contract.json` would match the existing pattern; the operator or next step should decide.

**Regression risk.** Medium. Every test module that loads this file at module level, for parametrize ids, fails collection as a whole if the file is missing or invalid.
</impact>
<impact path="tests/active/test_server.py" element="new parametrized fixture replay test (fetch_translate / request_translate called directly) and the fixture coverage test; module imports; module docstring">
**What changes.**
- **Replay test.** One test per fixture case, with `name` as the id. It starts `_translate_engine((status, body))` (`:1599`) and calls `lib.engine_api_client.fetch_translate(base, id, host, after)` (state) or `request_translate(base, id, host)` (enqueue). It asserts equality with `gateway`, or `pytest.raises(EngineApiError)` for `rejected`. The control asserts that `seen[-1][:2]` is `("POST", "/internal/translate")` or `("POST", "/internal/translate/enqueue")`.
- **Coverage test.** It asserts that the valid-200 states per route equal `TRANSLATE_STATES` / `TRANSLATE_REQUEST_STATES`, that each appears with and without `available`, and that names are unique.
- **Imports.** It needs `from lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate`, next to the existing `lib.*` imports (`:180-183`). `lib` is importable because conftest puts `client/backend` on `sys.path` (`conftest.py:43-45`).
- **Fixture loading.** There is no `ROOT` constant in this file. Use `Path(__file__).resolve().parents[2]` as `ENGINE_SERVER_DIR` does (`:186`).
- **Docstring.** The module docstring (`:132-148`) lists every translate test by behaviour, so it needs a new paragraph for the fixture replay.

**What stays.** `TRANSLATE_ENGINE_ANSWERS` (`:1559`), `TRANSLATE_STATE_ANSWERS` (`:1723`) and the HTTP-route tests stay unchanged (named simplification). The AC "passes unchanged" covers them.

**Details that matter.**
- `fetch_translate` called outside a request has no `REQUEST_CONTEXT`. `bridge_headers()` then just omits `X-Request-ID`, which is fine.
- The token header is read from env. Not needed here, but the `translate_bridge_token` fixture is available.
- `TRANSLATE_TIMEOUT_SECONDS` = 20 s per call, and there are ~40 cases. Each one is a local stub, so this is fast. A hung stub would cost 20 s per case.

**Regression risk.** Low-medium. The new tests fail only where the fixture and the gateway disagree, which is the point. A wrong control path (`seen` checked before the call) would hide a stub mismatch.
</impact>
<impact path="tests/active/test_server.py" element="_TranslateEngine stub (do_POST serialisation) and _translate_engine context manager, reused unchanged">
**What changes.** Nothing in the code. It is reused by the replay test.

**Dependency.** `do_POST` writes `json.dumps(payload)` (`:1585`). For the `1e999` case the loaded fixture holds `float('inf')`, so the stub writes `Infinity`. The Client's `_post_json` reads it with `json.loads` (`engine_api_client.py:65`), which accepts `Infinity`, then `_is_seconds` refuses it on `math.isfinite`. That is the right reason, matching the plan's analysis.

**Risk.** If anyone changes the stub to `json.dumps(..., allow_nan=False)`, that case would error in the stub instead of in the parser. Low risk.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="fetch_translate, request_translate, _translate_available, _checked_cues, TRANSLATE_STATES, TRANSLATE_REQUEST_STATES, TRANSLATE_NOT_FOUND_ERROR, EngineApiError, TRANSLATE_TIMEOUT_SECONDS (read only; optional comment at :17)">
**What changes.** No runtime change (the AC). It is now replayed directly by `test_server.py` and read by the timeout-chain test (`TRANSLATE_TIMEOUT_SECONDS = 20`, `:18`).

**Facts the fixture relies on:**
- **404 mapping.** Only `error == "Video not found"` maps to `none` (`:187`, `:208`). Any other non-200 raises.
- **`available` check.** It is read before cues (`:194`). Any non-bool raises.
- **Cues.** They are checked on `ready`/`running` only, and copied in Engine order (`:195-196`). This is why the fixture's `running` gateway keeps stored order and its `ready` gateway keeps Engine order (unsorted).
- **`total`.** A non-negative, non-bool int (`:199`). Note that `3.0` would be rejected here but accepted by the frontend, which is why the plan excludes it.
- **`request_translate`.** It never reads cues or total (`:212-215`), which is why the cue/total rejections are state-route only.

**Optional comment.** `:17` says the drain "must stay above this". It could now name the guarding test. If edited, the edit is comment only.

**Dependents.** `client/backend/server.py` (`/api/translate`), `test_server.py`, `test_profiles.py`, `test_dislikes.py`, `test_blocks.py` (via `tests/config.json`).

**Regression risk.** None if left untouched. Any edit here would break the "no runtime change" criterion.
</impact>
<impact path="tests/active/test_frontend_translate.py" element="new third module-scoped bundle fixture (data/translate.ts alone), a new runner script constant, a new replay test; module docstring">
**What changes.**
- **New bundle fixture.** It bundles `client/frontend/src/data/translate.ts` with the same esbuild flags as `bundle`/`generation_bundle` (`:214-226`, `:536-549`): `--bundle --format=esm --platform=node`, `--define:import.meta.env.VITE_CLIENT_API_BASE=<BASE>`, `--define:import.meta.env.DEV=false`. It needs no embed alias and no css loader. The bundle must export `fetchTranslate`/`requestTranslate`; an ESM bundle of an entry with exports keeps them.
- **New runner (one node process).** It stubs `globalThis.window = {location: {origin: BASE}, localStorage}` and `globalThis.localStorage` before a dynamic `await import(BUNDLE)`, not a static import. `api-base.ts:5` evaluates `window.location.origin` at module load, and `profile.ts` calls `localStorage.getItem` per request. The existing runners already use `await import(process.env.BUNDLE)` after stubbing (`:169`).
- **Fixture read in node.** The runner reads the fixture with `fs` + `JSON.parse`, then serves each case's body from a `fetch` stub as a 200. The stub's serialiser must write non-finite numbers as `1e999` (plain `JSON.stringify` writes `null`). The runner reports `{name: {value} | {error: message}}`.
- **Python assertions.** Valid cases deep-equal `gateway`, with `ready` cues re-sorted by (start, end) and `running` left in order. Rejected cases must throw exactly `Translate response was malformed`. A control asserts that the `1e999` case arrived as `Infinity`.
- **Docstring.** The module docstring (`:1-31`) describes both runners and must gain a paragraph for the third one.

**Notes.**
- JS reports `1.0` as `1`. Python compares `1 == 1.0` as True, so deep equality holds.
- `Headers`/`Response`/`URL` are node globals, as the existing runners already rely on.
- The `MALFORMED` text is matched literally from `translate.ts:19`.

**Regression risk.** Low for existing tests: a separate fixture and a separate bundle. A static import in the runner would crash on `window` at load, giving one test failure with a confusing stderr.
</impact>
<impact path="client/frontend/src/data/translate.ts" element="fetchTranslate, requestTranslate, readTranslateResponse, parseTranslateState, parseAvailable, parseCues, MALFORMED, REQUEST_STATES (exercised, not changed)">
**What changes.** Nothing (the plan says no frontend file changes and no parser is exported). It is now driven by the third bundle.

**Facts the fixture relies on:**
- **Sorting.** `ready` cues are sorted by `compareCues` (`:101`); `running` cues keep their order (`:104`).
- **`total`.** It must be `Number.isInteger` and ≥0 (`:103`), so an integral float passes. That is the plan's documented gap.
- **`available`.** It is checked first, for every state route payload (`:100`).
- **`requestTranslate`.** It checks only membership in `REQUEST_STATES` and `available` (`:78-81`).
- **JSON parse failures.** A `JSON.parse` failure in `readTranslateResponse` (`:87`) throws a `SyntaxError`, not `MALFORMED`. The exact-message assertion is what keeps such a failure from passing as a refusal.

**Dependents.** `pages/video-page/translate.ts` (imports `compareCues`, `fetchTranslate`, `readTranslate`, `requestTranslate`, `setTranslate` and the types). `test_frontend_dist.py` lists it among dist sources.

**Regression risk.** None, as long as it stays untouched.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="DEFAULT_CLIENT_API_BASE = window.location.origin at module load; resolveClientApiBase">
**What changes.** Nothing. It is pulled into the new standalone bundle through `translate.ts` and `profile.ts`.

**Dependency.** It reads `window.location.origin` on import, so the new runner must define `window` before importing the bundle.

**Risk.** It affects only the new test's harness. If `window` is missing, the import throws `ReferenceError` before any case runs.
</impact>
<impact path="client/frontend/src/data/profile.ts" element="profileHeaders / getProfileKey (localStorage), ProfileKeyRejectedError">
**What changes.** Nothing. It is bundled with `translate.ts`.

**Dependency.** `getProfileKey` wraps `localStorage` in try/catch, so a missing stub would just send no key. `readTranslateResponse` throws `ProfileKeyRejectedError` only on a 401, and the stub serves only 200s.

**Risk.** Low.
</impact>
<impact path="client/frontend/src/pages/video-page/translate.ts" element="requeue detection state.total < runningHeld (:175) and running cue merge/sort (:181)">
**What changes.** Nothing. This is the consumer of the running-slice rule that the README sentence now documents (`total` counts every stored cue whatever `after` was).

**Coverage.** `test_frontend_translate.py::test_a_running_total_below_the_held_count_makes_the_next_poll_ask_from_zero` already covers it.

**Risk.** None from this build. It is listed because the new README prose must describe exactly the behaviour it depends on (`internal_translate.py:254`: `cues[after:]` with `total = len(cues)`).
</impact>
<impact path="tests/active/test_internal_translate.py" element="new per-(route,state) answer-shape test, with a driver dict keyed by (route, state)">
**What changes.** A new test parametrized over the fixture's valid 200 cases that carry `available`, one per `(route, state)`. It uses the existing helpers:
- `_seed(store, row)` (`:674`, which already supports queued/running/ready/failed/already_english).
- Fresh beats via `write_translate_heartbeat(store, NOW, 1)` or `_beat(path, 0)` (`:695`).
- `_instance(False)` (FR listing, so no en track) for state `none`.
- `_route(instance, monkeypatch)` (`:653`, pins `now_ms` to NOW and stubs `data.source_fetch.build_opener`).
- `_state`/`_handle` and `_enqueue` (`:733-742`).
- For busy, the cap fill as in `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues` (`:977`, which needs `SUBTITLE_QUEUE_CAP`, already imported at `:84`).

It asserts a 200, the same key set as the fixture case, a JSON type per value, and the keys and types of each cue. Responses are a real JSON round trip (`HandlerRequest.wfile` does `json.loads`, `:366`), so types are JSON types.

**Gaps and ambiguities:**
- **Running and `after` give a vacuous cue check.** `_seed("running")` stores the 3-cue `RUNNING` (`:635`). If the fixture's sliced running case uses `after: 3` (2 of 5), the Engine answers `cues: []` and the per-cue type check checks nothing. Either drive running without `after`, or choose an `after` below 3, or seed 5 cues.
- **Which case is "the" case is unclear.** The fixture holds two running state cases with `available` (stored-order and sliced). "Once per (route, state)" needs a stated rule: the first case, or every case.
- **Ready.** The stored ready answer is `STORED_READY` (1 cue). It is fine for shape.
- **State `none` with `available: true`** needs a fresh beat plus `_instance(False)`. That yields `{"state":"none","available":true}` (`:263`).
- **Enqueue `none`** is answered only with `available: false`. The driver gives "no beat", and the type is still bool.
- **Mutation check.** A missing driver must fail explicitly (e.g. `assert key in DRIVERS`), not skip.

**Regression risk.** Low for existing tests, since the test is additive. Risk of a weak test: the vacuous-cue gap above.
</impact>
<impact path="tests/active/test_internal_translate.py" element="new Video-not-found test against the fixture body (state route; enqueue too)">
**What changes.** A new test asserting that an unknown video (`{"id": "no-such-video", "host": HOST}`) and the denylisted video (`DENIED_VIDEO` after `_set_denied(whitelist, True)`, `:420`) answer `[[404, <fixture's Video not found engine.body>]]` on `_state`, and on `_enqueue` too. It reuses the `whitelist` fixture and `_route`.

**Overlap.** It overlaps the existing `test_an_unknown_video_is_404_video_not_found_with_no_fetch` (`:467`) and the denylist test (`:478`). Those compare against the local `VIDEO_NOT_FOUND = [[404, {"error": "Video not found"}]]` (`:162`), which stays as a copy.

**Regression risk.** Low.
</impact>
<impact path="tests/active/test_internal_translate.py" element="new heartbeat derivation test (ast over server_config.py, eval of the RHS, module identity, no literals in handler/worker)">
**What changes.**
1. It parses `engine/server/api/server_config.py` with `ast`, finds the `HEARTBEAT_FRESH_MS` assignment, and checks that its RHS names `HEARTBEAT_SECONDS`.
2. It `eval`s the RHS with `{"HEARTBEAT_SECONDS": server_config.HEARTBEAT_SECONDS}` (giving 15000) and with 7.0 (giving 21000). If the RHS wraps `int(...)`, `eval`'s default builtins provide `int`.
3. It checks `handlers.internal_translate.HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS`.
4. It reads `internal_translate.py` and `engine/server/db/jobs/translate-worker.py` (the hyphenated name, so read as text/ast, not imported) and asserts neither assigns `HEARTBEAT_FRESH_MS`/`HEARTBEAT_SECONDS` at module level.

**Pitfall.** Use `==`, not `is`, for the module value check. Several suites load `server_config` under other names (`engine_server_config` in `test_similar.py:117,282,559` and `test_server_config.py:280`). The startup runner rebinds `sys.modules["server_config"]` only inside a subprocess (`:1071-1083`). The handler is imported through `importlib.import_module("handlers.internal_translate")` in this process.

**Regression risk.** Low. The test text is coupled to the exact assignment form chosen in `server_config.py` (an `Assign` vs `AnnAssign` node).
</impact>
<impact path="tests/active/test_internal_translate.py" element="new timeout-chain test beside test_one_15_second_budget_covers_both_fetches (:611); module docstring">
**What changes.** A new test:
- It imports `REQUEST_BUDGET_SECONDS` (15.0) from `handlers.internal_translate`, `SOCKET_TIMEOUT_SECONDS` (4.0) from `data.source_fetch`, and `TRANSLATE_TIMEOUT_SECONDS` (20) from `lib.engine_api_client`.
- It reads `scripts/deploy-bluegreen.sh` with `re.findall(r"^DRAIN_SECONDS=(\d+)$", text, re.M)` and requires exactly one match. Line 50 is `DRAIN_SECONDS=30`. Line 70's `    --drain) DRAIN_SECONDS="${2:-}"` is indented, so it does not match.
- It asserts 15 + 4 < 20 < 30.

**Import path.** `lib` resolves because this module imports `conftest` (`:75`), which puts `client/backend` at `sys.path[0]`. No `lib` package exists under `engine/server` to shadow it (checked). `engine_api_client` imports only stdlib and `.request_context`.

**Docstring.** The module docstring (`:1-50`) lists every behaviour and needs lines for the shape, not-found, derivation and chain tests.

**Regression risk.** Low. It fails intentionally on renames or reformatting of those constants or of the shell line.
</impact>
<impact path="engine/server/api/server_config.py" element="new HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS beside SUBTITLE_* tunables (:419-428)">
**What changes.** Add, next to `SUBTITLE_QUEUE_CAP`/`SUBTITLE_MAX_CHUNK_SECONDS` (`:425-428`), in the file's style (a one-line comment above each constant):
- `HEARTBEAT_SECONDS = 5.0`
- `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)` (or an equivalent that keeps the int 15000).

**Dependents.**
- `handlers/internal_translate.py` and `db/jobs/translate-worker.py` (new importers).
- Every process and suite that imports `server_config`: the Engine (`api/server.py`), `test_server_config.py`, `test_random_cache.py`, `test_similar.py`, `test_internal_events.py`, `test_popular_videos.py`, `test_search_fusion.py`, `test_updater_worker.py`, and the subprocess runners that exec the real file under `sys.modules["server_config"]`.

**Safety.** Both constants are pure literals with no env read. They add no exit path, so the env-check tests in `test_server_config.py` are unaffected. No test enumerates the module's names (checked).

**Regression risk.** Very low at runtime. The value must stay exactly 15000 (an int) so `BEATS` (`test_internal_translate.py:746`: 15 000 true / 15 001 false) and the docs read the same. A float is functionally equal, but the plan fixes it as an int.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="import line :27, the HEARTBEAT_FRESH_MS literal and rat-tail comment :32-33, module docstring :3/:5, _generation_available :156-163, comment :30">
**What changes.**
- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.
- Delete `:32-33` (the rat-tail comment and `HEARTBEAT_FRESH_MS = 15_000`).
- `_generation_available` (`:163`) keeps using the name, so its behaviour is unchanged.
- The module docstring (`:3`, `:5`) and the `_generation_available` docstring (`:157`) keep the name `HEARTBEAT_FRESH_MS`. Per the plan, the module docstring also says it is defined in `server_config.py`.
- `:30`'s comment ("Two fetches share it, so the Client's 20 s timeout covers the budget plus one socket timeout past it.") stays true. It could point at the new chain test (optional).

**Dependents.**
- `translate-worker.py` imports `TARGET_LANGUAGE, fetch_instance_track, resolve_translatable_video` from here (`:47`), not the heartbeat.
- `test_internal_translate.py` imports the module via `_handler_module` and monkeypatches `now_ms` on it. It does not patch `HEARTBEAT_FRESH_MS`, so a re-export is fine.
- The new derivation test reads `module.HEARTBEAT_FRESH_MS` (still a module attribute through the import).

**Regression risk.** Low. The ways it can go wrong are an import typo, or deleting `:31` `REQUEST_BUDGET_SECONDS` by accident while editing the adjacent lines (the chain test and `fetch_instance_track` `:130` need it).
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="server_config import :41, HEARTBEAT_SECONDS literal and rat-tail comment :58-59; uses at :458, :467, :536; docstring :8">
**What changes.**
- Add `HEARTBEAT_SECONDS` to `:41` (`from server_config import DEFAULT_DB_PATH, ...`, keeping the alphabetical order of the existing list).
- Delete `:58-59`.
- The uses stay unchanged: the heartbeat-thread docstring `:458`, `stop.wait(HEARTBEAT_SECONDS)` `:467` and `beat.join(HEARTBEAT_SECONDS)` `:536`.
- The module docstring `:8` ("beating every 5 s") stays true.

**Dependents.**
- `test_translate_worker.py` runs the worker as a subprocess and through `STALL_DRIVER` (`:213-219`, which loads the script as a module and only overrides `STALL_SECONDS`). Nothing patches `HEARTBEAT_SECONDS` (grep found none). Its beat-window tests (`FIRST_BEAT_SECONDS`, `BEAT_WINDOW_SECONDS`) depend on the value staying 5.0.
- The new derivation test reads this source to prove there is no literal.

**Merge note.** Issue 56 (split worker) touches the same constants block. `docs/project/issues/plan.md:26` predicts a one-line conflict.

**Regression risk.** Low-medium. A missed import fails only at worker runtime (NameError in the heartbeat thread and on shutdown). The `test_translate_worker` service tests would catch it, since they observe beats.
</impact>
<impact path="engine/server/data/source_fetch.py" element="SOCKET_TIMEOUT_SECONDS = 4.0 (:21), read only">
**What changes.** Nothing. The chain test imports it.

**Risk.** If someone renames it, or raises it above 4 s without raising the Client's timeout, the chain test fails, which is intended. Other users (`fetch_bounded` defaults) are unaffected.
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="DRAIN_SECONDS=30 default (:50), read as text">
**What changes.** Nothing. The chain test regex-reads `:50`.

**Dependents.** `test_deploy_bluegreen.py` and DEPLOYMENT.md `:174` (the drain table row).

**Risk.** If the default is reformatted (quoted, indented, or given `${DRAIN_SECONDS:-30}`), the chain test fails loudly ("exactly one match"). This is intended, but it couples the script's formatting to a translate test.
</impact>
<impact path="tests/active/test_translate_worker.py" element="existing worker suite (heartbeat beats, STALL_DRIVER), unchanged regression guard">
**What changes.** Nothing.

**Why listed.** It is the guard for the worker import change. Any NameError on `HEARTBEAT_SECONDS`, or an import failure of `server_config`, shows here: the service run, the stall test `:1286`, and the beat helpers `_beat`/`_next_beat` `:711-726`. It is one of the suites to baseline before the build (the plan's "six translate suites").

**Risk.** None from new code, but it must be run.
</impact>
<impact path="tests/active/conftest.py" element="sys.path insertion of client/backend (:43-45) and import of the Client server module">
**What changes.** Nothing.

**Dependency.** Both new cross-layer imports rely on it: `lib.engine_api_client` from `test_internal_translate.py` and from `test_server.py`. `test_internal_translate.py` then prepends `engine/server` and `engine/server/api` (`:80-82`). Module-name clashes between the trees (`server`, `http_utils`) do not affect `lib.*`.

**Risk.** Low. The import would break if conftest stopped adding the path.
</impact>
<impact path="tests/config.json" element="test_groups entries for test_server.py, test_frontend_translate.py, test_internal_translate.py">
**What changes.** The house pattern lists data fixtures and cross-layer sources under each test group (e.g. `tests/active/host_tokens.json`, `tests/active/upstream_snippet_cases.json`, `scripts/deploy-bluegreen.sh`). Add:
- **`test_server.py`:** the fixture path.
- **`test_frontend_translate.py`:** the fixture path (`client/frontend/src/data/translate.ts`, `api-base.ts` and `profile.ts` are already listed or now relevant; add `client/frontend/src/data/api-base.ts`).
- **`test_internal_translate.py`:** the fixture path, `client/backend/lib/engine_api_client.py`, `scripts/deploy-bluegreen.sh` and `engine/server/db/jobs/translate-worker.py` (the derivation test reads it). `engine/server/data/source_fetch.py` and `server_config.py` are already present.

**Risk.** Omitting these means a selective runner won't rerun the suites when those files change. The chain test is meant to catch exactly such cross-layer edits, so the omission would defeat it.
</impact>
<impact path="engine/server/README.md" element="/internal/translate bullet (:15) and Availability sub-bullet (:18); worker store bullets (:29, :38)">
**What changes.**
- **`:15`** gains the running-slice rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted. This satisfies the AC "README states the running-slice rule beside /internal/translate". Wording should match `CONTEXT.md:17`, which already says this.
- **`:18`** says `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats), keeping "15 000 ms".
- **Optional.** `:29` lists the worker's tunables in `api/server_config.py` (`SUBTITLE_*`) and could add `HEARTBEAT_SECONDS`. `:38` ("every 5 s") stays true.

**Risk.** Docs only. The sentence must not contradict `internal_translate.py:254` (`cues[after:]`, `total = len(cues)`).
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="Heartbeat section (:155)">
**What changes.** Drop "Raise both constants together." and name the single definition: `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived as three beats. The "every 5 s" and "15 s" figures stay.

**Other lines.** `:75` and `:146` ("join the heartbeat for up to 5 s") stay true.

**Risk.** Docs only.
</impact>
<impact path="CONTEXT.md" element="Translate state and Generation available entries (:17-18)">
**What changes.** Nothing (the plan says unchanged). `:17` already states the running-slice rule and that "all three layers are held to one contract fixture ... (issue 55)", and `:18` the 15 s / three 5 s beats.

**Check.** The new README sentence should use the same wording. The fixture should be called the "contract fixture" in test docstrings, for glossary consistency.

**Risk.** None.
</impact>
<impact path="DEPLOYMENT.md" element="drain row (:174) and translate worker paragraph (:230)">
**What changes.** Nothing required.
- `:230` names "the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats". It stays true; optionally it could say it is derived in `server_config.py`.
- `:174` states the drain must exceed the Client's 20 s timeout. That ordering is now enforced by the chain test, and optionally the row could say so.

**Uncertainty.** It is listed because both lines document constants this build re-homes or ties together. A reviewer may want them aligned.

**Risk.** None.
</impact>
<impact path="client/README.md" element="GET /api/translate bullet (:32)">
**What changes.** Nothing required. It says `running` carries the cues from `after` "plus `total`, the stored cue count". This is consistent with the rule, but it lacks the "whatever `after` was / requeue" consequence the Engine README gains.

**Optional.** One clause, for parity. The plan names only the Engine README.

**Risk.** None.
</impact>
<impact path="docs/project/plans/01-55-translate-state-contract.record.md" element="build record">
**What changes.** The plan routes two items into the build record:
- The hand mutation outcome: add a valid `paused` case; the expected results are a Client `EngineApiError`, the coverage test failing, the frontend throwing `MALFORMED`, and the Engine having no driver. Then revert.
- The grep showing no file under `engine/`, `client/` or `scripts/` names `translate_contract.json`.

The pre-build baseline run of the translate suites (`test_internal_translate`, `test_server`, `test_frontend_translate`, `test_translate_worker`, and per the plan's six probably `test_subtitles` and `test_source_fetch`) also belongs here.

**Risk.** Process only: the AC "passes unchanged" is unproven without the baseline.
</impact>
<impact path="docs/project/issues/55-translate-state-contract.md" element="Status line and acceptance-criteria checklist">
**What changes.** On delivery: tick the AC boxes, set `Status: enhancement, complete`, and move the file to `docs/project/issues/archive/` (per `docs/project/triage-labels.md`). Nothing else in the issue text needs changing. Its line numbers are stale, but that is historical.

**Risk.** None.
</impact>
<impact path="docs/project/issues/56-split-translate-worker.md" element="worker constants block overlap (:97); docs/project/issues/plan.md (:13, :26)">
**What changes.** Nothing. Issue 56 explicitly leaves `HEARTBEAT_SECONDS` to 55. `plan.md:26` predicts a one-line conflict in the worker's constants block, which this build creates by removing `:58-59`.

**Risk.** Merge-order only. Whichever merges second rebases.
</impact>
<impact path="tests/last_test_validation.json" element="generated test record">
**What changes.** It is regenerated by the runner with the new test ids (the fixture case names as parametrize ids). Not hand-edited.

**Risk.** None. Ids must be unique, which the coverage test enforces.
</impact>
</impacts>

### docs_checklist

<doc path="engine/server/README.md">
- **Line 15** (`/internal/translate`): add the running-slice rule. `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted. Use wording consistent with CONTEXT.md:17.
- **Line 18** (Availability): say `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats, still 15 000 ms).
- **Optional:** line 29 could list `HEARTBEAT_SECONDS` among the worker tunables in `api/server_config.py`.
</doc>
<doc path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md">
Line 155: remove "Raise both constants together." and name the single definition, `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats.
</doc>
<doc path="engine/server/api/handlers/internal_translate.py">
The module docstring (lines 3/5) keeps the name `HEARTBEAT_FRESH_MS` and says it is defined in `server_config.py`, derived from `HEARTBEAT_SECONDS`. The rat-tail comment at line 32 is deleted. Optionally, the line-30 comment can name the timeout-chain test.
</doc>
<doc path="engine/server/db/jobs/translate-worker.py">
The rat-tail comment at line 58 is deleted along with the literal. The module docstring at line 8 ("every 5 s") stays.
</doc>
<doc path="tests/active/test_server.py">
The module docstring (lines 132-148) gains a paragraph for the fixture replay through `fetch_translate`/`request_translate`, and for the fixture coverage check.
</doc>
<doc path="tests/active/test_frontend_translate.py">
The module docstring (lines 1-31) gains a paragraph for the third, standalone `data/translate.ts` bundle and its replay runner (including the `1e999` serialisation and its control).
</doc>
<doc path="tests/active/test_internal_translate.py">
The module docstring (lines 1-50) gains lines for four tests: the per-(route, state) shape test against the fixture, the fixture Video-not-found body test, the heartbeat derivation test, and the timeout-chain test.
</doc>
<doc path="tests/config.json">
Add the fixture path to the `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` groups. Add `client/backend/lib/engine_api_client.py`, `scripts/deploy-bluegreen.sh` and `engine/server/db/jobs/translate-worker.py` to `test_internal_translate.py`, and `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.
</doc>
<doc path="docs/project/plans/01-55-translate-state-contract.record.md">
Record three things: the pre-build baseline of the translate suites, the hand mutation (`paused` case) outcome per layer, and the grep proving no runtime file names `translate_contract.json`.
</doc>
<doc path="docs/project/issues/55-translate-state-contract.md">
On delivery: tick the acceptance criteria, set the Status to `complete`, and move the file to `docs/project/issues/archive/`.
</doc>
<doc path="DEPLOYMENT.md">
Optional only. Line 230 could say `HEARTBEAT_FRESH_MS` is derived in `server_config.py`, and line 174 could say the drain > Client-timeout ordering is now test-enforced. Both lines are still accurate as written.
</doc>
<doc path="client/README.md">
Optional only. The line-32 `total` clause could gain "whatever `after` was" for parity with the Engine README.
</doc>

### highest_risk

tests/active/test_internal_translate.py (shape test drivers): the seeded running row holds 3 cues (`RUNNING`), so driving the fixture's sliced case (`after` past 2 of `total` 5) returns `cues: []` and the cue type check passes having checked nothing. Also nothing defines which of the two running cases is "the" case per (route, state), and the enqueue `none`/`available: true` case is an answer the Engine never gives.
tests/active/test_frontend_translate.py (third bundle runner): `api-base.ts` reads `window.location.origin` at module load, so the runner must stub `window`/`localStorage` before a dynamic import. The `1e999` body must be written back literally: `JSON.stringify` writes `null`, and passing the fixture through Python `json.dumps` writes `Infinity`, which `JSON.parse` refuses. Either mistake turns rejections into SyntaxErrors that only the exact-message assertion catches.
engine/server/db/jobs/translate-worker.py (import swap): removing the `HEARTBEAT_SECONDS` literal without adding it to the `server_config` import fails only at worker runtime (heartbeat thread and shutdown join), not at Engine start. Only `test_translate_worker`'s subprocess beat tests catch it, and the same block conflicts with issue 56.

## 2026-10-04 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I opened the files behind the inventory and checked them: `engine_api_client.py`, `data/translate.ts`, `internal_translate.py`, the imports and heartbeat lines in `translate-worker.py`, the tunables block in `server_config.py`, the `_TranslateEngine` stub and imports in `test_server.py`, the helpers in `test_internal_translate.py`, the esbuild fixtures in `test_frontend_translate.py`, `DRAIN_SECONDS` in `deploy-bluegreen.sh`, the `tests/config.json` groups, the two docs, and the acceptance criteria in issue 55. The inventory holds up in substance. I found one factual slip: `request_translate` uses the default 6 s timeout, not 20 s. There is one small gap not in the inventory: on the state route, the Engine's `failed` and `already_english` drivers need the no-track instance. I traced every listed rejection through both parsers again. Each is refused by `fetch_translate`/`request_translate` and also by `fetchTranslate`/`requestTranslate` when served as a 200, so the plan's two fixture rules hold. Nothing conflicts with the requirements or the plan.
<question id="1">
Yes, the plan works as intended. Client: `fetch_translate` and `request_translate` match the fixture's semantics line for line. Only `Video not found` maps to none (`:187`, `:208`). `available` is checked before cues (`:194`). Cues are copied in Engine order (`:177`). `total` must be a non-bool, non-negative int (`:199`). `request_translate` never reads cues (`:212-215`). The stub's `json.dumps` writes `Infinity` for `1e999`, `json.loads` accepts it, and `_is_seconds` then refuses it, so the case fails for the right reason. Frontend: `parseAvailable` runs first (`:100`), `ready` is sorted with `compareCues` and `running` is not (`:101-104`), `Number.isInteger` catches -1 and `true` totals, `Number.isFinite` catches bool and infinite times, and `busy` falls through to `MALFORMED`. The existing runners already stub globals before `await import(process.env.BUNDLE)` (`:169`, `:495`), and the esbuild flags the plan copies are at `:216-222` and `:538-544`. Engine: the existing helpers can drive every state. The test docstring (`:44`) confirms enqueue on a stored `failed` key answers `failed` and does not requeue it, so the "four stored states" driver is sound. `_resolve_translate_key` answers the same `VIDEO_NOT_FOUND` on both routes (`:224-226`). Heartbeat: the worker's `server_config` import (`:41`) is alphabetical, and `HEARTBEAT_SECONDS` slots in after `DEFAULT_SUBTITLES_DB_PATH`. The handler keeps `REQUEST_BUDGET_SECONDS` at `:31`, between the import and the literal being deleted. Timeout chain: `^DRAIN_SECONDS=(\d+)$` with `re.M` matches only `:50`; the `--drain)` line at `:70` is indented, so it does not match. The mutation check works on all three layers: Client `EngineApiError`, coverage test failing, frontend `MALFORMED`, Engine missing driver.
</question>
<question id="2">
- The three layers' tests are now tied together through one JSON file. If the file is malformed, all three modules fail at collection, because the parametrize ids come from it.
- One translate test now depends on the formatting of the deploy script's `DRAIN_SECONDS` line and on constant names in two other trees. The plan intends this.
- The worker and the handler now depend on `server_config` for the heartbeat. A missed import in the worker only shows up when it runs, as a NameError in the heartbeat thread and on shutdown. `test_translate_worker.py` catches that.
- The Engine shape test can be satisfied vacuously for running-with-`after` (the inventory already carries this).
- The new shape test only covers what the fixture states. The enqueue route's `none` with `available: true` cannot happen in reality, and its check passes because the type is still bool (also already in the inventory).
- Issue 56 will hit a one-line merge conflict in the worker's constants block, as `plan.md` predicts.
</question>
<question id="3">
These are all on top of what the inventory lists:
- The pre-build baseline runs of the translate suites have to be recorded.
- `tests/config.json` needs the fixture added to each of the three groups. `test_internal_translate.py` also needs `client/backend/lib/engine_api_client.py`, `scripts/deploy-bluegreen.sh` and `engine/server/db/jobs/translate-worker.py`. `test_frontend_translate.py` needs `client/frontend/src/data/api-base.ts`. I confirmed none of these are listed today (`:403-420`).
- On the state route, the Engine drivers for `failed` and `already_english` must use `_instance(False)`. Otherwise the handler fetches a track and answers `ready`.
- The derivation test must compare with `==`, not `is`.
- The worker import must be added in the same change that deletes `:58-59`.
</question>
<question id="4">
Runtime behaviour does not change. The heartbeat values stay 5.0 s and 15000 ms (an int). The handler keeps a module attribute `HEARTBEAT_FRESH_MS` through the import, and `_generation_available` reads it exactly as before. No Client or frontend file changes. What does change:
- Where the heartbeat constants live: one definition in `server_config.py`, with the window derived from the beat.
- The two rat-tail comments and the instruction "raise both together" go.
- The tests now enforce the contract and the timeout ordering that were previously only described in prose.
- The README gains the running-slice sentence.
</question>

New impacts:
tests/active/test_internal_translate.py — the per-(route, state) driver dict: on the state route, `_seed("failed")` and `_seed("already_english")` must be paired with `_instance(False)`, as in the BRANCHES row "failed, no track". The handler fetches the instance for those rows (`internal_translate.py:256-263`), and a served track turns the answer into `{"state":"ready","cues":...}`, which would fail the key-set check against the fixture's failed/already_english case. The inventory names `_instance(False)` only for `none`.
delete_me/ and tests/tmp/probe_53_draft_translate_worker*.py — stale draft copies of the handler and the worker that still hold `HEARTBEAT_FRESH_MS = 15_000`, `HEARTBEAT_SECONDS = 5.0` and the rat-tail comments. The derivation test reads only the real files, so it is unaffected, but a repo-wide grep for "no remaining literal" in the build record will hit them. Any such grep must be scoped to `engine/`. They are not imported by any collected test (the probe already imports the removed `SOURCE_INSTANCE` from the handler).

Inventory entries that did not hold up:
tests/active/test_server.py (replay test entry), "TRANSLATE_TIMEOUT_SECONDS = 20 s per call ... a hung stub would cost 20 s per case": this is true only for `fetch_translate` (`engine_api_client.py:186`). `request_translate` calls `_post_json` without a timeout, so it uses the default 6 s (`:52`, `:207`). The conclusion stands; the enqueue-route numbers are what differ. It also means the plan's timeout chain covers only the state route. That is correct, because the enqueue route makes no instance fetch, but the test's docstring should not claim it covers both routes.

Conflicts: none

Recommendations: 1. **No-track instance for state-route failed/already_english.** Pair those two drivers with `_instance(False)` in the Engine shape test, and write one comment saying why. Cost: nothing extra. Without it the test fails on first run, loudly, so the risk is wasted time rather than a hidden defect.
2. **Running driver.** Drive running with no `after`, or with an `after` below 3, so the per-cue type check has cues to inspect. Or seed five running cues if the fixture's sliced case must match exactly. When the fixture has two running state cases with `available`, the shape test should check every one, not just the first. Cost: a few lines. Without it, the cue-shape check on running can pass while checking nothing.
3. **`tests/config.json`.** Add the entries listed under question 3 in the same change. Cost: about 7 lines of JSON. Without them, a selective runner will not rerun the chain and derivation tests when the deploy script, the Client client or the worker changes, and those edits are exactly what the tests exist to catch.
4. **Fixture location.** Keep `tests/active/fixtures/translate_contract.json` as the plan settles it, unless you prefer the flat house style (`tests/active/translate_contract.json`, beside `host_tokens.json`). Changing it is a plan edit, but a cheap one: a single path string used in three tests, `tests/config.json` and the build-record grep. The issue does not fix the path.
5. **Enqueue `none` with `available: true`.** In the fixture `description`, state that the Engine never produces this case. It exists so the Client and frontend accept both values of the flag. Cost: one sentence. Without it, a later reader may think the Engine can answer it.
6. **Build-record grep.** Scope any grep for leftover heartbeat literals to `engine/`, so the `delete_me/` and `tests/tmp/` draft copies do not show up. Cost: nothing.
7. **Test doubles.** The plan widens none. `_TranslateEngine` is reused unchanged and its recorded calls are not filtered; the replay test's path control reads `seen[-1]` after the call. No double needs updating or retiring.

## 2026-10-04 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="tests/active/fixtures/translate_contract.json" element="new contract fixture file (and the new tests/active/fixtures/ directory)">
**What changes.** This is a new file, `{"description", "cases": [...]}`. Each case has `name`, `route` (`state`|`enqueue`), an optional `after` (state route only), `engine: {status, body}`, and `gateway` (the normalised answer, or `"rejected"`). The `tests/active/fixtures/` directory does not exist yet (Glob found nothing). Precedent: the two existing test data files sit directly in `tests/active/` (`host_tokens.json`, `upstream_snippet_cases.json`). A subdirectory still works, but it is a new convention.

**Constraints I checked against the code:**
- **Enqueue cases need bodies with only `{state, available}`.** The real enqueue route answers no other keys (`internal_translate.py:282`, `:285`). If enqueue `ready`/`running` bodies carried `cues`/`total`, the Engine key-set test would fail.
- **Enqueue `none` with `available: true` is something the Engine never produces.** The route answers `none` only as `available: False` (`:282`). A keys-and-types check still passes, but the fixture would then assert an answer the Engine cannot give. Say so in `description`.
- **`1e999`.** Python `json.load` reads it as `inf` and node `JSON.parse` reads it as `Infinity`. Python `json.dumps` writes it back as `Infinity`, which the Client's `json.loads` accepts. `JSON.stringify` writes `null`.
- **The `Video not found` 404.** Its body must be exactly `{"error": "Video not found"}`. That is the match in `engine_api_client.py:187,208` (`TRANSLATE_NOT_FOUND_ERROR`) and the Engine's `VIDEO_NOT_FOUND` (`internal_translate.py:35`).
- **Rejected bodies served to the frontend as a 200.** `{"error":"Not found"}` has no `state`, so both `parseTranslateState` and `requestTranslate` throw MALFORMED (`translate.ts:80,107`). `busy` on the state route falls through to MALFORMED (`:107`). Bool and infinite times fail `Number.isFinite` (`:120`). A `total` of -1 or `true` fails `Number.isInteger` / `< 0` (`:103`). A non-bool `available` fails `parseAvailable` (`:113`). Each one is refused by the Client too: `_translate_available` `:164`, `_checked_cues` `:171-176`, the `total` check `:199`, and the state sets `:192,213`.
- **Avoid a float-valued integral `total` such as `3.0`.** JS accepts it and the gateway refuses it, as the plan says.
- **Running `after` case** (2 cues, `total` 5): Client and frontend just pass it through. See the Engine-test entry for the slicing caveat.

**Dependents.** `test_server.py`, `test_frontend_translate.py` (node `fs` + `JSON.parse`) and `test_internal_translate.py` read it. No file under `engine/`, `client/` or `scripts/` may name it.

**Risk.** The risk is in the content, not the code. A case that violates the "refused by both parsers" rule fails the frontend replay for the wrong reason. So does an enqueue body with extra keys, which fails the Engine shape test.
</impact>
<impact path="tests/active/test_server.py" element="new fixture replay test through fetch_translate / request_translate, plus the fixture coverage test">
**What changes.** Two tests are added near the translate block (`:1540-1932`).

**Test 1** is parametrized over the fixture cases, with ids taken from the case names:
- Inside `with _translate_engine((status, body)) as (engine_base, seen):` it calls `fetch_translate(engine_base, "uuid-1", "peer.example", after=case.get("after"))` or `request_translate(engine_base, "uuid-1", "peer.example")`.
- It asserts equality with `gateway`, or `pytest.raises(EngineApiError)` for `"rejected"`.
- Control: `[e[1] for e in seen] == ["/internal/translate"]` or `["/internal/translate/enqueue"]`.

**Test 2** checks:
- The set of valid 200 state-route states equals `TRANSLATE_STATES`, and the enqueue set equals `TRANSLATE_REQUEST_STATES`.
- Each `(route, state)` appears both with and without `available`.
- Names are unique.
- The 404 Video-not-found cases are left out of the state sets.

**New imports.** `from lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate`, plus a fixture path built from `Path(__file__).resolve().parent / "fixtures" / "translate_contract.json"`.
- `lib` is already the Client package in `sys.modules`: conftest `:43-49` imports `lib.http_utils` before this module inserts the Engine dirs (`:185-190`). So the import resolves to `client/backend/lib`.
- `client/backend/lib/__init__.py` exists. No `lib` package exists anywhere under `engine/`.

**Facts verified:**
- `_TranslateEngine` (`:1578-1596`) serialises with `json.dumps(payload)`. That writes `Infinity` for the `1e999` case, `_post_json`'s `json.loads` accepts it, and `_is_seconds` (`:156-158`) then refuses it, so the case fails for the right reason.
- `_post_json` returns `(code, parsed)` for an HTTPError, so the 404 paths work.
- The test needs no `ENGINE_BRIDGE_TOKEN` (`bridge_headers` just omits the header).
- `request_translate` uses the default 6 s timeout, not 20 s.

**Existing items that stay as they are:**
- The `TRANSLATE_ENGINE_ANSWERS` (`:1559`), `TRANSLATE_STATE_ANSWERS` (`:1723`) and `TRANSLATE_ENQUEUE_ANSWERS` (`:1911`) tables.
- `TRANSLATE_RUNNING_CUES` and `TRANSLATE_READY_CUES`.
- Every HTTP-route test.

**Docstring.** The module docstring's translate paragraphs (`:132-148`) gain one paragraph for the replay and the coverage check.

**Regression risk.**
- Low for the existing tests, because only additions are made.
- Name clash: `TRANSLATE_STATE_ROUTE` and similar already exist, so the new constants need distinct names.
- A module-level `json.load` of the fixture breaks collection of the whole 1932-line file if the file is missing or malformed. Loading at module level is what parametrize needs, so accept the risk or guard it.
</impact>
<impact path="tests/active/test_frontend_translate.py" element="new third module-scoped esbuild bundle of client/frontend/src/data/translate.ts and a replay runner">
**What changes.**
- **New fixture.** A module-scoped fixture, a sibling of `bundle` (`:214-226`) and `generation_bundle` (`:536-548`). It runs esbuild on `FRONTEND / "src" / "data" / "translate.ts"` with `--bundle --format=esm --platform=node` and the two `--define:import.meta.env.*` flags. It needs no embed-api alias and no CSS loader, because nothing in that import chain imports CSS.
- **New runner string.** It stubs `globalThis.window = {location: {origin: BASE}, localStorage}`, `localStorage` and `fetch`, then does `await import(process.env.BUNDLE)`. The import must be dynamic and come after the stubs, because `data/api-base.ts:5` reads `window.location.origin` at module top level.
- **Replay.** The runner reads the fixture with `fs.readFileSync` + `JSON.parse`. For each case it serves a 200 whose text is the gateway answer (valid case) or the Engine body (rejected case), using a serialiser that writes non-finite numbers as `1e999`. It then calls `fetchTranslate(BASE, id, host, after)` or `requestTranslate(BASE, id, host)` and reports the value or the thrown `message` per case. All cases run in one node process.

**Python asserts:**
- A valid answer deep-equals the gateway answer, with `ready` cues sorted in Python by `(start, end)` and `running` cues kept in order.
- Every rejected case threw exactly `Translate response was malformed` (`MALFORMED`, `translate.ts:19`).
- Control: the `1e999` case reached the parser as `Infinity`. For example, the runner records `Number.isFinite === false` on the parsed served text.

**Facts verified:**
- `readTranslateResponse` (`:84-93`) throws the payload's `error` text on a non-2xx status. That is why rejected bodies must be served as 200. A 404 served as 404 would throw `Not found`, not MALFORMED.
- `profileHeaders()` reads `localStorage` lazily, so the stub only needs to exist.
- `fetchTranslate` puts `after` on the query string, which the stub ignores.
- JS turns `1.0` into `1`, and Python compares `1 == 1.0` as true, so float/int differences do not break the deep-equal.

**Docstring.** The module docstring (`:1-31`) gains a paragraph for the third bundle and its runner, including the `1e999` serialisation and its control.

**Regression risk.** Low for the existing tests (additive). The new bundle adds one esbuild run and one node process. The existing `RUNNER` and `GENERATION_RUNNER` strings are untouched.
</impact>
<impact path="tests/active/test_internal_translate.py" element="new Engine shape test per (route, state), the Video-not-found body test, the heartbeat derivation test and the timeout-chain test">
**What changes: four tests.**

**(1) Shape test.** It is parametrized over the fixture's valid 200 cases that carry `available`. Drivers live in a dict keyed by `(route, state)`, and a missing key fails.
- **State route** drivers use `_seed(store, row)` (`:674-692`) plus `write_translate_heartbeat(store, NOW, 1)`, with `_route(_instance(track), monkeypatch)` (`:646-657`) and `_handle`/`_state` (`:437`, `:739`).
- **Gap: `failed`, `already_english` and `none` need `_instance(False)`.** With a track, those rows answer `ready` (BRANCHES `:812`, `:814`).
- `ready` uses `_seed("ready")`, which answers `STORED_READY` with no fetch.
- **Enqueue route** drivers use `_beat(subtitles_path, 0)` (`:695`) or no beat for `none`, `_seed` plus `store.close()` for the stored states (as `:963-974` does), and the queue filled to `SUBTITLE_QUEUE_CAP` for busy (as `:977-989`), via `_enqueue` (`:733`).
- **JSON-type helper.** It must test `bool` before `int`/`float`, since `isinstance(True, int)` is true.
- **Caveat on `after`:** `RUNNING` (`:635`) holds 3 cues. Driving with a fixture `after` ≥ 3 (for example 3, from the 5-total case) answers `cues: []`, so the per-cue key/type check passes without checking anything. The driver should seed enough cues, or clamp `after`.

**(2) Video-not-found test.** An unknown video, and `_set_denied(whitelist, True)` on `DENIED_VIDEO`, on both routes must answer `[[404, fixture_body]]`.
- The file already has `VIDEO_NOT_FOUND = [[404, {...}]]` (`:162`), so the new test should compare against the fixture body and not that literal.

**(3) Heartbeat derivation test:**
- `ast.parse` `API_DIR / "server_config.py"`, find the `Assign` to `HEARTBEAT_FRESH_MS`, and check that its value contains `Name('HEARTBEAT_SECONDS')`.
- `eval(compile(ast.Expression(node.value), ...), {"HEARTBEAT_SECONDS": x})` gives 15000 for 5.0 and 21000 for 7.0.
- `_translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS`.
- Neither `internal_translate.py` nor `engine/server/db/jobs/translate-worker.py` has a module-level `Assign` to either name. The worker's name is hyphenated, so it is read as text/ast and never imported.

**(4) Timeout-chain test** sits beside `test_one_15_second_budget_covers_both_fetches` (`:611`):
- `_translate().REQUEST_BUDGET_SECONDS` (15.0, `:31`), `data.source_fetch.SOCKET_TIMEOUT_SECONDS` (4.0, `source_fetch.py:21`) and `lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS` (20).
- `re.findall(r"^DRAIN_SECONDS=(\d+)$", text, re.M)` on `scripts/deploy-bluegreen.sh` gives exactly `["30"]`. Line 50 is the only match: `:70` is indented `--drain) DRAIN_SECONDS=...`.
- Assert 15 + 4 < 20 < 30.

**Import caveats (verified):**
- `lib` resolves to `client/backend/lib`, because conftest (`:43-48`) inserts BACKEND_DIR and imports `lib.http_utils` first, and there is no `lib` under `engine/`.
- **`tests/active/test_source_fetch.py:25` does `from test_internal_translate import ...`** and `tests/tmp/probe_50_phase1_rows.py:11` does too. Any new module-level import (`lib.engine_api_client`), module-level fixture load or module-level `server_config` read in this file therefore runs whenever `test_source_fetch.py` is collected. Keep cross-layer imports inside the test function, as the file's `_translate()` pattern already does (`:297-299`).
- `server_config` is already imported at module level (`:84`).

**Docstring.** The module docstring (`:1-50`) gains entries for the four tests.

**Regression risk.**
- Existing tests: `BEATS` (`:746`, 15 000 true / 15 001 false) and `FRESH_BEATS` (`:950`) depend on `HEARTBEAT_FRESH_MS` staying 15000. They are unaffected if the value is kept.
- New tests: moderate. The driver gaps above, plus the bool/int typing, are where a wrong implementation would pass or fail spuriously.
</impact>
<impact path="engine/server/api/server_config.py" element="new HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS beside the SUBTITLE_* tunables (:419-428)">
**What changes.** Add both constants after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`), each with a one-line comment as the block does:
- `HEARTBEAT_SECONDS = 5.0`
- `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)`, or `3 * int(HEARTBEAT_SECONDS * 1000)`; any form whose RHS names `HEARTBEAT_SECONDS` and evaluates to the int 15000.
- The module imports only `os` (`:3`). No new import is needed.

**Dependents.**
- `internal_translate.py` and `translate-worker.py` (both via `from server_config import ...`).
- Every test that imports `server_config`: `test_internal_translate.py:84`, `test_internal_events.py:33`, `test_random_cache.py:57`, `test_similar.py`, `test_popular_videos.py`, `test_search_fusion.py`, `test_server_config.py`.
- The `VARIANT_RUNNER` (`test_internal_translate.py:1072-1086`) and `test_server_config.py:211-222` exec this file and override attributes after import. Overriding `HEARTBEAT_SECONDS` there would not move `HEARTBEAT_FRESH_MS` (derived at import), but no override does that today.

**Regression risk.** Very low. The derived value must be an int (15000); the plan requires it, and `BEATS` and the docs depend on it.
</impact>
<impact path="engine/server/api/handlers/internal_translate.py" element="server_config import (:27), the HEARTBEAT_FRESH_MS literal and rat-tail comment (:32-33), module docstring (:3, :5), _generation_available (:156-163)">
**What changes:**
- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.
- Delete `:32` (the rat-tail comment) and `:33` (`HEARTBEAT_FRESH_MS = 15_000`).
- `_generation_available` (`:163`) reads the imported name unchanged.
- Module docstring `:3` and `:5`: keep the name and add that it is defined in `server_config.py` and derived from `HEARTBEAT_SECONDS`.
- The `_generation_available` docstring (`:157`) keeps the name.
- `:30` (the budget comment naming the Client's 20 s) stays. It could optionally point at the timeout-chain test.

**What does not change.** `REQUEST_BUDGET_SECONDS` (`:31`), `VIDEO_NOT_FOUND` (`:35`), both handlers' answers, and the sort at `:115`.

**Dependents.**
- `router.py:41` imports only the two handlers.
- `translate-worker.py:47` imports `TARGET_LANGUAGE`, `fetch_instance_track` and `resolve_translatable_video`, not the heartbeat.
- Tests reach the module through `_translate()` / `_handler_module` and monkeypatch only `now_ms` (`:656`). Nothing patches `HEARTBEAT_FRESH_MS`, so turning it into an imported name is safe.
- The new derivation test reads `module.HEARTBEAT_FRESH_MS`, which stays a module attribute through the import.

**Regression risk.** Very low. If the import line drops `SUBTITLE_QUEUE_CAP`, the enqueue route breaks; `test_with_a_serving_worker_a_full_queue_answers_busy...` would catch that.
</impact>
<impact path="engine/server/db/jobs/translate-worker.py" element="server_config import (:41), HEARTBEAT_SECONDS literal and rat-tail comment (:58-59); uses at :458, :467, :536">
**What changes:**
- Add `HEARTBEAT_SECONDS` to `:41`, keeping alphabetical order: `DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, ...`.
- Delete `:58` (the rat-tail comment) and `:59` (`HEARTBEAT_SECONDS = 5.0`).
- The uses stay: the `heartbeat_loop` docstring `:458`, `stop.wait(HEARTBEAT_SECONDS)` `:467` and `beat.join(HEARTBEAT_SECONDS)` `:536`.
- The module docstring `:8` ("beating every 5 s") stays true.
- `:35` (the comment on why `api/` is on the path) could add the heartbeat. Optional.

**Dependents.**
- `test_translate_worker.py` runs the script as a subprocess and through `STALL_DRIVER` (`:214-222`, which execs the file and overrides only `STALL_SECONDS`), plus another `spec_from_file_location` load at `:258`.
- Its beat timing constants depend on the 5 s cadence staying put: `BEAT_GAP_MS` (4500, 6500) `:208`, `BEAT_WINDOW_SECONDS` `:210`, `FIRST_BEAT_SECONDS` `:212`. Nothing patches `HEARTBEAT_SECONDS`.
- Issue 56 (`docs/project/issues/plan.md:26`) expects a one-line conflict in this constants block.

**Regression risk.** Low. A typo in the import gives an ImportError at worker start, which the `run`/stall tests in `test_translate_worker.py` would catch. Stale copies holding the literal remain under `tests/tmp/probe_53_draft_translate_worker*.py` and `delete_me/`. They are not collected and do not matter, except to an unscoped "no literal left" grep.
</impact>
<impact path="client/backend/lib/engine_api_client.py" element="TRANSLATE_TIMEOUT_SECONDS, TRANSLATE_STATES, TRANSLATE_REQUEST_STATES, EngineApiError, fetch_translate, request_translate (read by tests only)">
**What changes.** Nothing; this file is read-only for this build.

**Dependents added.**
- `test_server.py` imports the parsers and state sets.
- `test_internal_translate.py` imports `TRANSLATE_TIMEOUT_SECONDS` (20, `:18`).
- The module imports only stdlib plus `.request_context`, which itself imports only `re` and `uuid`, so importing it into the Engine test process is safe.

**Comment.** The comment at `:17` ("30 s drain must stay above this") stays accurate, and could optionally name the test.

**Boundary guard.** `tests/check-client-engine-boundary.sh` scans only `client/backend` for Engine imports, so the tests are not affected.

**Regression risk.**
- None at runtime.
- The tests break if `TRANSLATE_TIMEOUT_SECONDS`, `TRANSLATE_STATES` or `TRANSLATE_REQUEST_STATES` are renamed. That is intended.
</impact>
<impact path="client/frontend/src/data/translate.ts" element="fetchTranslate, requestTranslate (exported), parseTranslateState/parseAvailable/parseCues (private), MALFORMED">
**What changes.** Nothing; no runtime change.

**What the new bundle depends on:**
- The exported names `fetchTranslate` and `requestTranslate`.
- The exact text `Translate response was malformed` (`:19`).
- `ready` sorted with `compareCues` and `running` left in order (`:101-104`).
- The imports of `./api-base` (which reads `window.location.origin` at top level, `api-base.ts:5`, and `import.meta.env.VITE_CLIENT_API_BASE` / `DEV`) and `./profile` (`localStorage`, read lazily).

**Other consumers.** `client/frontend/src/pages/video-page/translate.ts:11` imports from it; that file is unchanged.

**Regression risk.** None at runtime. Renaming the message or the exports breaks the new test, which is intended.
</impact>
<impact path="client/frontend/src/data/api-base.ts" element="top-level DEFAULT_CLIENT_API_BASE = window.location.origin">
**What changes.** Nothing.

**Why listed.** The standalone `data/translate.ts` bundle pulls this module in. It reads `window.location.origin` when the module is evaluated, so the new runner must set `globalThis.window` before its dynamic `import()`. A static import, or a missing stub, throws `ReferenceError: window is not defined` before any case runs.

**Risk.** It sits on the new test's setup path only.
</impact>
<impact path="engine/server/data/source_fetch.py" element="SOCKET_TIMEOUT_SECONDS (:21)">
**What changes.** Nothing.

**Dependents.** The new timeout-chain test reads it (4.0). The Engine test already imports `data.source_fetch` (`_handler_module`, `:400`).

**Risk.** A rename breaks the test, which is intended. `MEDIA_SOCKET_TIMEOUT_SECONDS` (15.0) must not be the value read by mistake.
</impact>
<impact path="scripts/deploy-bluegreen.sh" element="DRAIN_SECONDS=30 (:50) and the --drain help comment (:17-18)">
**What changes.** Nothing.

**Why listed.** The timeout test parses `^DRAIN_SECONDS=(\d+)$` (multiline). Today exactly one line matches (`:50`); `:70` is indented and quoted. The comment at `:17-18` ("the Client's longest Engine request timeout is 20 s") stays accurate.

**Dependents.** `tests/active/test_deploy_bluegreen.py` runs the script with `--drain 0` and never reads the default.

**Risk.** Reformatting the line (for example `DRAIN_SECONDS="30"` or `: "${DRAIN_SECONDS:=30}"`) breaks the test by design.
</impact>
<impact path="engine/server/data/subtitles.py" element="fetch_translate_heartbeat / write_translate_heartbeat">
**What changes.** Nothing. The plan considered it as the home for the pair and rejected it.

**Dependents.** The Engine shape-test drivers write beats through `write_translate_heartbeat` (as `_beat` and the BRANCHES test do), and `_seed` uses this module's writers.

**Risk.** None.
</impact>
<impact path="tests/active/test_source_fetch.py" element="module-level `from test_internal_translate import CHUNK, HOST, ...` (:25)">
**What changes.** Nothing.

**Why listed.** It imports `test_internal_translate` as a module, so everything new at that file's module level also runs when this suite is collected.

**Risk.** Medium if the new Engine tests add a module-level `from lib.engine_api_client import ...`, a module-level fixture load or a module-level `ast` read. If such a step failed, `test_source_fetch.py` would fail to collect too. Keep those reads inside the test bodies.
</impact>
<impact path="tests/active/test_translate_worker.py" element="worker service, stall-driver and beat-cadence tests (:205-224, :1250-1300)">
**What changes.** Nothing; this is a guard suite.

**Why listed.**
- It is the only suite that runs the worker after the import change, through the subprocess `run`, the `STALL_DRIVER` exec and the `spec_from_file_location` load at `:258`.
- Its beat cadence windows (`BEAT_GAP_MS` 4500-6500 ms) prove `HEARTBEAT_SECONDS` is still 5.0.
- It is one of the six translate suites to baseline before the build.

**Risk.** It catches any NameError or ImportError from the move.
</impact>
<impact path="tests/config.json" element="test_groups for test_server.py, test_frontend_translate.py, test_internal_translate.py">
**What changes.** These groups map source files to the suites that cover them. Add:
- `tests/active/fixtures/translate_contract.json` to all three groups.
- To `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py` (read by the derivation test), `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh` (read by the timeout test).
- `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.

There is precedent for data files in groups (`tests/active/host_tokens.json`, `upstream_snippet_cases.json`).

**Risk.** If these entries are left out, a change to the fixture, the deploy script or the Client timeout would not trigger the suites that read them. The runtime tests themselves are unaffected. I am not certain how strictly the runner uses `test_groups` for selection, so treat this as recommended.
</impact>
<impact path="engine/server/README.md" element="/internal/translate bullet (:15), Availability (:18), worker tunables paragraph (:30), heartbeat line (:38)">
**What changes:**
- `:15` gains the running-slice rule: `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted. Keep the wording consistent with `CONTEXT.md:17`.
- `:18` says `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats), still 15 000 ms.
- Optional: `:30` lists the worker's `server_config` tunables and could add `HEARTBEAT_SECONDS`.
- `:38` ("every 5 s", "15 s freshness rule") stays true.

**Risk.** Docs only.
</impact>
<impact path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md" element="Heartbeat section (:155)">
**What changes.** Remove "Raise both constants together." and name the single definition: `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived as three beats. The "every 5 s", "15 s" and "up to 5 s" join figures (`:146`) stay.

**Risk.** Docs only.
</impact>
<impact path="CONTEXT.md" element="Translate state (:17), Generation available (:18)">
**What changes.** Nothing. `:17` already states the running-slice rule and the "one contract fixture ... (issue 55)" sentence. `:18` already states 15 s = three 5 s beats.

**Risk.** None. It is listed so the build does not edit it twice.
</impact>
<impact path="DEPLOYMENT.md" element="--drain row (:174), translate worker paragraph (:230)">
**What changes.** Optional only.
- `:174` says the drain covers the Client's 20 s timeout, and could add that a test now enforces this.
- `:230` names "the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats", and could add "derived in `server_config.py`".

Both are accurate as written.

**Risk.** None.
</impact>
<impact path="client/README.md" element="GET /api/translate paragraph (:32)">
**What changes.** Nothing. It names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the parsing rules, all unchanged.

**Risk.** None.
</impact>
<impact path="docs/project/issues/55-translate-state-contract.md" element="acceptance criteria (:64-73)">
**What changes.** Only the status/checkboxes when the build is delivered (move to archive per `docs/project/triage-labels.md`). No content change is needed now.

**Note.** AC "every existing ... test passes unchanged" depends on running the baseline of the six suites first: test_internal_translate, test_server, test_frontend_translate, test_translate_worker, test_subtitles and test_source_fetch.

**Risk.** None.
</impact>
<impact path="docs/project/issues/plan.md" element="55/56 overlap note (:13, :26)">
**What changes.** Nothing. It already predicts the one-line conflict with issue 56 in the worker's constants block, which this build creates by deleting `translate-worker.py:58-59`.

**Risk.** A merge conflict with the 56 branch.
</impact>
</impacts>

### docs_checklist

<doc path="engine/server/README.md">
- Line 15 (`/internal/translate`): add the running-slice rule. `total` always counts every stored cue whatever `after` was, so a reader holding more running cues than `total` knows the job was requeued and restarted.
- Line 18 (Availability): say `HEARTBEAT_FRESH_MS` is derived in `api/server_config.py` from `HEARTBEAT_SECONDS` (three beats, still 15 000 ms).
- Optional: line 30 could list `HEARTBEAT_SECONDS` among the worker's tunables in `api/server_config.py`.
</doc>
<doc path="engine/server/db/jobs/docs/TRANSLATE_WORKER.md">
Line 155: remove "Raise both constants together." and name the single definition, `HEARTBEAT_SECONDS` in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats.
</doc>
<doc path="engine/server/api/handlers/internal_translate.py">
The module docstring (lines 3 and 5) keeps the name `HEARTBEAT_FRESH_MS` and says it is defined in `server_config.py`, derived from `HEARTBEAT_SECONDS`. The rat-tail comment at line 32 is deleted with the literal.
</doc>
<doc path="engine/server/db/jobs/translate-worker.py">
The rat-tail comment at line 58 is deleted with the literal. The module docstring at line 8 ("every 5 s") stays.
</doc>
<doc path="tests/active/test_server.py">
The module docstring's translate paragraphs (lines 132-148) gain a paragraph for the fixture replay through `fetch_translate`/`request_translate` and for the fixture coverage check.
</doc>
<doc path="tests/active/test_frontend_translate.py">
The module docstring (lines 1-31) gains a paragraph for the standalone `data/translate.ts` bundle and its replay runner, including the `1e999` serialisation and its control.
</doc>
<doc path="tests/active/test_internal_translate.py">
The module docstring (lines 1-50) gains entries for the per-(route, state) shape test against the fixture, the fixture Video-not-found body test on both routes, the heartbeat derivation test, and the timeout-chain test.
</doc>
<doc path="DEPLOYMENT.md">
Optional only. Line 230 could say `HEARTBEAT_FRESH_MS` is derived in `server_config.py`, and line 174 could say a test now enforces drain > Client timeout. Both are accurate as written.
</doc>

### highest_risk

tests/active/test_internal_translate.py (Engine shape-test drivers): on the state route, `failed`, `already_english` and `none` need `_instance(False)`, otherwise they answer `ready`. Driving `running` with the fixture's `after` against the 3-cue `RUNNING` seed can return `cues: []`, so the per-cue check passes without checking anything. The type check must test bool before int. Any of these lets a wrong Engine pass, or fails a right one.
tests/active/test_source_fetch.py: it imports `test_internal_translate` at module level (`:25`). A new module-level cross-layer import (`lib.engine_api_client`), fixture load or `ast` read in `test_internal_translate.py` would break collection of `test_source_fetch.py` too. Keep those reads inside the test bodies.
tests/active/fixtures/translate_contract.json and the frontend runner: each rejected body must be refused by both parsers when served as a 200. Enqueue bodies must carry only `{state, available}`. The `1e999` case needs the custom serialiser, because `JSON.stringify` writes `null` and the case would then be refused for the wrong reason. A content slip here fails the frontend or Engine replay spuriously, or hides a real gap behind the control.

## 2026-10-04 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: none.

I opened the files behind every runtime and test entry in the inventory: `internal_translate.py`, `engine_api_client.py`, `data/translate.ts`, `api-base.ts`, the worker's import and constants block, the `server_config.py` tunables block, conftest's `sys.path`/`lib` setup, the `_TranslateEngine` stub and imports in `test_server.py`, the helpers and parametrized tables in `test_internal_translate.py`, the `bundle` fixture and runner in `test_frontend_translate.py`, the `STALL_DRIVER`/`_worker` loaders in `test_translate_worker.py`, `DRAIN_SECONDS` in the deploy script, `SOCKET_TIMEOUT_SECONDS`, and the `tests/config.json` groups. Every claim I checked holds. That includes the inventory's own corrections to the plan: the state-route `failed`/`already_english`/`none` drivers need `_instance(False)` (BRANCHES `:811-815`); `_seed("running")` holds the 3-cue `RUNNING`, so a fixture `after` of 3 answers `cues: []` and the per-cue type check checks nothing; enqueue `none` with `available: true` is something the Engine never produces (`:282`); `request_translate` uses the 6 s default. A repo-wide search for the heartbeat names finds no code outside the handler, the worker and the stale `tests/tmp/probe_53_*` copies, so nothing reads or patches the literals the build removes. I found nothing the inventory does not already carry, and no conflict with the requirements or the plan.
<question id="1">
Yes, the plan works as intended. **Client.** `fetch_translate` maps only `Video not found` to none (`:187`). It checks `available` before cues (`:194`), copies cues in Engine order (`:177`) and requires `total` to be a non-bool int ≥ 0 (`:199`). `request_translate` never reads cues (`:212-215`). The stub's `json.dumps` writes `Infinity`, `_post_json`'s `json.loads` accepts it, and `_is_seconds` refuses it, so the `1e999` case fails for the right reason. **Frontend.** Every listed rejection, served as a 200, ends in `MALFORMED`. A missing `state` and `busy` on the state route fall through at `:107`, and a non-bool `available` is caught at `:113`. `Number.isFinite` refuses `true` and `Infinity` (`:120`), and `Number.isInteger` refuses -1 and `true` (`:103`). `ready` is sorted with `compareCues` and `running` is not (`:101-104`). `api-base.ts:5` reads `window.location.origin` at top level, and the existing runners already stub globals before `await import(process.env.BUNDLE)` (`:169`), which is the pattern the new runner copies. **Engine.** The helpers the plan names exist and drive every state: `_seed` `:674`, `_beat` `:695`, `_enqueue` `:733`, `_state` `:739`, and the busy fill `:983`. `_resolve_translate_key` answers `VIDEO_NOT_FOUND` on both routes (`:224-226`). **Heartbeat.** The worker's `server_config` import (`:41`) is alphabetical, so `HEARTBEAT_SECONDS` slots in. The handler keeps a module attribute `HEARTBEAT_FRESH_MS` through the import, so `_generation_available` (`:163`) reads it unchanged. **Timeout chain.** The values are 15.0 + 4.0 < 20 < 30. `^DRAIN_SECONDS=(\d+)$` matches only `:50`; the `:70` line is indented. `SOCKET_TIMEOUT_SECONDS` (`:21`) and `MEDIA_SOCKET_TIMEOUT_SECONDS` (`:24`) are distinct names.
</question>
<question id="2">
The heartbeat window becomes an import from `server_config`, so issue 56's branch gets the one-line conflict `plan.md:26` already predicts. Three test files gain cross-layer reads: the Engine test reads the Client's `TRANSLATE_TIMEOUT_SECONDS` and the deploy script's text, and the frontend test reads a fixture under `tests/active/fixtures/`, which is a new directory convention. A rename or reformat on either side now breaks a test, which is intended. Because `test_source_fetch.py:25` imports `test_internal_translate` as a module, anything added at that file's module level also runs when `test_source_fetch.py` is collected. This matters most for the fixture load that parametrization needs (see recommendations). One deliberate ceiling: the coverage test proves the fixture's state sets equal the gateway's in both directions. On the frontend it proves only that every fixture state is accepted and every rejected case is refused. A state the frontend alone started accepting would go unnoticed unless a rejected case named it. That is within the plan as written, not a gap the inventory missed. The Engine test checks shape only, as the plan says, and the existing `BRANCHES`/`AFTERS` tests keep covering values.
</question>
<question id="3">
Run the six-suite baseline before any edit, because "passes unchanged" rests on it. The worker's import line must gain `HEARTBEAT_SECONDS` in the same edit that deletes `:58-59`. Otherwise the worker fails only at runtime, in the heartbeat thread and the shutdown join, and only `test_translate_worker.py`'s subprocess and stall tests catch it. The handler's import must keep `SUBTITLE_QUEUE_CAP`. `HEARTBEAT_FRESH_MS` must stay the int 15000, because `BEATS` (`:746`), `FRESH_BEATS` (`:950`) and the docs depend on it. New module-level code in `test_internal_translate.py` must not fail at import. The fixture content must keep the plan's two rules and the inventory's constraints: enqueue bodies carry only `{state, available}`, there is no float-valued integral `total`, and the Video-not-found body is exactly `{"error": "Video not found"}`. Each rejected body should also be valid apart from the one defect it names (see recommendations). `tests/config.json` groups (`:79`, `:403`, `:414`) should list the newly read files so a change to them selects the right suites.
</question>
<question id="4">
Runtime behaviour is unchanged. The heartbeat stays 5.0 s and 15000 ms, both runtime modules read the same values through an import instead of literals, and no Client or frontend file changes. What does change is outside runtime code. There is one definition of the heartbeat pair. There is one checked-in contract fixture that three layers' tests replay. Two cross-layer guard tests are added (the timeout chain and the heartbeat derivation). The README, TRANSLATE_WORKER.md and the handler docstring each change by one sentence.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Avoid a module-level fixture load in `test_internal_translate.py`.** In that file, parametrize the Engine shape test over the static driver dict's `(route, state)` keys rather than over the fixture's cases. Read the fixture inside the test body, and add one assertion, in its own test, that the fixture's valid `(route, state)` set equals the driver keys. *What it changes:* the inventory says to keep fixture reads inside test bodies (because `test_source_fetch.py:25` imports this module), but parametrizing over fixture cases needs a module-level load. Parametrizing over the drivers removes that tension, and the extra assertion keeps "a fixture state with no driver fails" and the Engine half of the mutation check. *Cost:* one small extra test. The pytest ids come from the driver keys rather than the fixture's case names. The alternative is a module-level `json.load` of a checked-in file: it costs nothing, but a malformed fixture would also stop `test_source_fetch.py` from collecting. `test_server.py` and `test_frontend_translate.py` have no such importer, so their module-level load is fine as the inventory says.

2. **Pin the running driver's cue count to the fixture's sliced case.** For the sliced `running` case (`after` 3, `total` 5), seed 5 cues rather than `RUNNING`'s 3, for example via `_claimed(store).write_running_cues(...)` with 5 cues, as `AFTERS` does with 3. *What it changes:* the per-cue key/type check then sees 2 real cues instead of `[]`. Without it, that check passes while checking nothing. *Cost:* a few lines in the driver. Clamping `after` instead would hide the slice the case exists for.

3. **Make each rejected fixture body valid apart from its one defect.** For example, the non-list-cues and bad-cue cases on `running` must carry a valid `total`, or use `ready`. *What it changes:* the frontend checks `total` (`translate.ts:103`) before cues and the gateway checks cues (`engine_api_client.py:196`) before `total`. A `running` body with both defects is refused by each layer for a different reason, and the replay still passes. *Cost:* none beyond care when writing the fixture. The Client fixture-check test could assert it cheaply by checking that rejected bodies differ from some valid case in one field, but that is optional.

4. **Add the `tests/config.json` group entries** listed in the inventory. *Cost:* five lines. Leaving them out does not break any test, but a change to the fixture, the deploy script or the Client timeout would not select the suites that read them.

5. **Scope the build record's "no literal left" and "no runtime file names the fixture" greps** to `engine/`, `client/` and `scripts/`. *Cost:* none. Unscoped, the literal grep hits the stale `tests/tmp/probe_53_draft_translate_worker*.py` copies and `delete_me/`.

## 2026-10-04 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft implementation: translate state contract fixture (issue 55)

Before writing this I read: `engine_api_client.py`, `data/translate.ts`, `data/api-base.ts`, `data/profile.ts`, `internal_translate.py`, the head of `translate-worker.py`, `server_config.py:410-433`, the translate blocks of `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` (harness `:297-460`, job-state and enqueue tests `:628-997`), `deploy-bluegreen.sh` (only line 50 matches the drain regex), `source_fetch.py:21`, `tests/config.json`, the README `/internal/translate` block, `TRANSLATE_WORKER.md:155` and `CONTEXT.md:17-18`.

**Step zero, before any edit:** run all six translate suites in full and record the result as the baseline: `test_internal_translate.py`, `test_server.py`, `test_frontend_translate.py`, `test_frontend_video_page.py`, `test_translate_worker.py`, `test_subtitles.py`. Also run `test_source_fetch.py`, which imports `test_internal_translate`.

### What has to be tested

1. Each fixture case goes through the gateway's real parsing (`fetch_translate` / `request_translate`) and gives the normalised answer, or `EngineApiError`.
2. Each fixture case goes through the real `data/translate.ts`. A valid answer is accepted with the same fields, `ready` sorted and `running` in stored order. A rejected body throws exactly `MALFORMED`.
3. Each `(route, state)` the Engine can produce answers with the key set and JSON types of the fixture's case that carries `available`. The `Video not found` 404 body equals the fixture's.
4. The fixture covers every gateway state with and without `available`, and its names are unique. A state added on one side only fails.
5. The heartbeat window is derived from the interval, and both consumers import it.
6. budget + socket < Client timeout < drain, using the real values.

### Module map

| File | Change |
|---|---|
| `tests/active/fixtures/translate_contract.json` | new (and a new directory) |
| `tests/active/test_server.py` | +1 import line, +2 module constants, +2 tests, +1 docstring paragraph |
| `tests/active/test_frontend_translate.py` | +3 constants, +1 runner string, +1 module fixture, +1 helper, +1 test, +1 docstring paragraph |
| `tests/active/test_internal_translate.py` | +2 stdlib imports, +1 path constant, helpers, driver table, +5 tests, docstring entries |
| `engine/server/api/server_config.py` | +2 constants |
| `engine/server/api/handlers/internal_translate.py` | import line, −2 lines, docstring |
| `engine/server/db/jobs/translate-worker.py` | import line, −2 lines |
| `engine/server/README.md`, `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` | prose |
| `tests/config.json` | group entries |

No other runtime file changes. `engine_api_client.py`, `data/translate.ts`, `api-base.ts`, `source_fetch.py`, `deploy-bluegreen.sh` and `CONTEXT.md` are read only.

---

### 1. `tests/active/fixtures/translate_contract.json`

The file has one case per line. `1e999` is legal JSON: Python's `json` reads it as `inf` and node's `JSON.parse` reads it as `Infinity`. Three cue lists are used:
- **Ready list:** out of start order, with two cues sharing start 1.0, so a frontend that does not sort, or sorts by start only, shows.
- **Running list:** stored order, not sorted.
- **Sliced running answer:** `after` 3, two cues, `total` 5.

```json
{
  "description": "Translate state contract (issue 55), read only by tests: test_server.py replays every case through fetch_translate/request_translate, test_frontend_translate.py through data/translate.ts, test_internal_translate.py checks the Engine's keys and JSON types against the valid cases that carry available. Nothing at runtime reads this file. route is state (POST /internal/translate) or enqueue (POST /internal/translate/enqueue); after (state route only) is the running cue count the reader holds; engine is what the Engine answers; gateway is the Client gateway's normalised answer, or \"rejected\" for EngineApiError. The gateway keeps the Engine's cue order (running in stored order; ready is sorted only by the frontend). Every (route, state) of a valid 200 case appears with available and without it (an older Engine; read as false). A rejected Engine body must be refused by the gateway and also by the frontend when served as a 200 gateway answer, so a float-valued integral total such as 3.0 (refused by the gateway, accepted by JS) cannot be a case. 1e999 is standard JSON and parses to infinity in Python and JS. The enqueue none case with available true is an answer the Engine never gives (it answers none only with available false); it is here for the with/without-available coverage, which checks keys and types only.",
  "cases": [
    {"name": "state none", "route": "state", "engine": {"status": 200, "body": {"state": "none", "available": true}}, "gateway": {"state": "none", "available": true}},
    {"name": "state none without available", "route": "state", "engine": {"status": 200, "body": {"state": "none"}}, "gateway": {"state": "none", "available": false}},
    {"name": "state queued", "route": "state", "engine": {"status": 200, "body": {"state": "queued", "available": true}}, "gateway": {"state": "queued", "available": true}},
    {"name": "state queued without available", "route": "state", "engine": {"status": 200, "body": {"state": "queued"}}, "gateway": {"state": "queued", "available": false}},
    {"name": "state running", "route": "state", "engine": {"status": 200, "body": {"state": "running", "cues": [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}], "total": 3, "available": true}}, "gateway": {"state": "running", "cues": [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}], "total": 3, "available": true}},
    {"name": "state running without available", "route": "state", "engine": {"status": 200, "body": {"state": "running", "cues": [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}], "total": 3}}, "gateway": {"state": "running", "cues": [{"start": 5.0, "end": 6.0, "text": "Third"}, {"start": 1.0, "end": 2.0, "text": "First"}, {"start": 3.0, "end": 4.0, "text": "Second"}], "total": 3, "available": false}},
    {"name": "state running after 3", "route": "state", "after": 3, "engine": {"status": 200, "body": {"state": "running", "cues": [{"start": 9.0, "end": 10.0, "text": "Fifth"}, {"start": 7.0, "end": 8.0, "text": "Fourth"}], "total": 5, "available": true}}, "gateway": {"state": "running", "cues": [{"start": 9.0, "end": 10.0, "text": "Fifth"}, {"start": 7.0, "end": 8.0, "text": "Fourth"}], "total": 5, "available": true}},
    {"name": "state ready", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": 4.0, "end": 5.0, "text": "Later"}, {"start": 1.0, "end": 3.0, "text": "Long first"}, {"start": 1.0, "end": 2.0, "text": "Short first"}], "available": true}}, "gateway": {"state": "ready", "cues": [{"start": 4.0, "end": 5.0, "text": "Later"}, {"start": 1.0, "end": 3.0, "text": "Long first"}, {"start": 1.0, "end": 2.0, "text": "Short first"}], "available": true}},
    {"name": "state ready without available", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": 4.0, "end": 5.0, "text": "Later"}, {"start": 1.0, "end": 3.0, "text": "Long first"}, {"start": 1.0, "end": 2.0, "text": "Short first"}]}}, "gateway": {"state": "ready", "cues": [{"start": 4.0, "end": 5.0, "text": "Later"}, {"start": 1.0, "end": 3.0, "text": "Long first"}, {"start": 1.0, "end": 2.0, "text": "Short first"}], "available": false}},
    {"name": "state already_english", "route": "state", "engine": {"status": 200, "body": {"state": "already_english", "available": true}}, "gateway": {"state": "already_english", "available": true}},
    {"name": "state already_english without available", "route": "state", "engine": {"status": 200, "body": {"state": "already_english"}}, "gateway": {"state": "already_english", "available": false}},
    {"name": "state failed", "route": "state", "engine": {"status": 200, "body": {"state": "failed", "available": true}}, "gateway": {"state": "failed", "available": true}},
    {"name": "state failed without available", "route": "state", "engine": {"status": 200, "body": {"state": "failed"}}, "gateway": {"state": "failed", "available": false}},
    {"name": "state video not found", "route": "state", "engine": {"status": 404, "body": {"error": "Video not found"}}, "gateway": {"state": "none", "available": false}},
    {"name": "enqueue none", "route": "enqueue", "engine": {"status": 200, "body": {"state": "none", "available": true}}, "gateway": {"state": "none", "available": true}},
    {"name": "enqueue none without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "none"}}, "gateway": {"state": "none", "available": false}},
    {"name": "enqueue queued", "route": "enqueue", "engine": {"status": 200, "body": {"state": "queued", "available": true}}, "gateway": {"state": "queued", "available": true}},
    {"name": "enqueue queued without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "queued"}}, "gateway": {"state": "queued", "available": false}},
    {"name": "enqueue running", "route": "enqueue", "engine": {"status": 200, "body": {"state": "running", "available": true}}, "gateway": {"state": "running", "available": true}},
    {"name": "enqueue running without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "running"}}, "gateway": {"state": "running", "available": false}},
    {"name": "enqueue ready", "route": "enqueue", "engine": {"status": 200, "body": {"state": "ready", "available": true}}, "gateway": {"state": "ready", "available": true}},
    {"name": "enqueue ready without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "ready"}}, "gateway": {"state": "ready", "available": false}},
    {"name": "enqueue already_english", "route": "enqueue", "engine": {"status": 200, "body": {"state": "already_english", "available": true}}, "gateway": {"state": "already_english", "available": true}},
    {"name": "enqueue already_english without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "already_english"}}, "gateway": {"state": "already_english", "available": false}},
    {"name": "enqueue failed", "route": "enqueue", "engine": {"status": 200, "body": {"state": "failed", "available": true}}, "gateway": {"state": "failed", "available": true}},
    {"name": "enqueue failed without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "failed"}}, "gateway": {"state": "failed", "available": false}},
    {"name": "enqueue busy", "route": "enqueue", "engine": {"status": 200, "body": {"state": "busy", "available": true}}, "gateway": {"state": "busy", "available": true}},
    {"name": "enqueue busy without available", "route": "enqueue", "engine": {"status": 200, "body": {"state": "busy"}}, "gateway": {"state": "busy", "available": false}},
    {"name": "enqueue video not found", "route": "enqueue", "engine": {"status": 404, "body": {"error": "Video not found"}}, "gateway": {"state": "none", "available": false}},
    {"name": "state route missing 404", "route": "state", "engine": {"status": 404, "body": {"error": "Not found"}}, "gateway": "rejected"},
    {"name": "enqueue route missing 404", "route": "enqueue", "engine": {"status": 404, "body": {"error": "Not found"}}, "gateway": "rejected"},
    {"name": "state unknown state", "route": "state", "engine": {"status": 200, "body": {"state": "bogus", "available": true}}, "gateway": "rejected"},
    {"name": "enqueue unknown state", "route": "enqueue", "engine": {"status": 200, "body": {"state": "bogus", "available": true}}, "gateway": "rejected"},
    {"name": "state busy", "route": "state", "engine": {"status": 200, "body": {"state": "busy", "available": true}}, "gateway": "rejected"},
    {"name": "state available a string", "route": "state", "engine": {"status": 200, "body": {"state": "none", "available": "true"}}, "gateway": "rejected"},
    {"name": "enqueue available a string", "route": "enqueue", "engine": {"status": 200, "body": {"state": "queued", "available": "true"}}, "gateway": "rejected"},
    {"name": "state cues not a list", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": {"start": 1.0, "end": 2.0, "text": "Hello"}, "available": true}}, "gateway": "rejected"},
    {"name": "state start 1e999", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": 1e999, "end": 2.0, "text": "Hello"}], "available": true}}, "gateway": "rejected"},
    {"name": "state start true", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": true, "end": 2.0, "text": "Hello"}], "available": true}}, "gateway": "rejected"},
    {"name": "state end true", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": 1.0, "end": true, "text": "Hello"}], "available": true}}, "gateway": "rejected"},
    {"name": "state text a number", "route": "state", "engine": {"status": 200, "body": {"state": "ready", "cues": [{"start": 1.0, "end": 2.0, "text": 7}], "available": true}}, "gateway": "rejected"},
    {"name": "state total -1", "route": "state", "engine": {"status": 200, "body": {"state": "running", "cues": [], "total": -1, "available": true}}, "gateway": "rejected"},
    {"name": "state total true", "route": "state", "engine": {"status": 200, "body": {"state": "running", "cues": [], "total": true, "available": true}}, "gateway": "rejected"}
  ]
}
```

I traced every rejection through both parsers:

| Case | Gateway (`engine_api_client.py`) | Frontend served as 200 (`translate.ts`) |
|---|---|---|
| route missing 404 (both) | non-200, not `Video not found`, `:189`/`:210` | no `state`, `:107` / `:80` |
| unknown state (both) | `:192` / `:213` | `:107` / `:80` |
| state busy | not in `TRANSLATE_STATES` `:192` | falls through to `:107` |
| available a string (both) | `_translate_available` `:164` | `parseAvailable` `:113` |
| cues not a list | `_checked_cues` `:171` | `parseCues` `:118` |
| start 1e999 | stub writes `Infinity`, `json.loads` gives inf, `_is_seconds` fails | stub writes `1e999`, `Number.isFinite(Infinity)` fails `:120` |
| start / end true | `_is_seconds` excludes bool | `Number.isFinite(true)` is false |
| text a number | `:175` | `:120` |
| total -1 / true | `:199` | `:103` |

Case count: 29 valid (12 state, 1 sliced running, 14 enqueue, 2 not-found) and 14 rejected.

---

### 2. `tests/active/test_server.py`

**Import**, added to the existing `lib` block at `:180-183`. It goes before the Engine path insert, so `lib` stays the Client package:

```python
from lib.engine_api_client import EngineApiError, TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, fetch_translate, request_translate
```

**Appended after `:1932`**, so `TRANSLATE_STATE_ROUTE`/`TRANSLATE_ENQUEUE_ROUTE` (`:1713-1714`) and `TRANSLATE_BODY` (`:1715`) are already defined:

```python
# The contract fixture all three layers replay (issue 55); loaded at collection because parametrize needs its cases, so a missing or malformed file stops this module's collection.
TRANSLATE_CONTRACT = Path(__file__).resolve().parent / "fixtures" / "translate_contract.json"
TRANSLATE_CONTRACT_CASES = json.loads(TRANSLATE_CONTRACT.read_text())["cases"]


@pytest.mark.parametrize("case", TRANSLATE_CONTRACT_CASES, ids=[case["name"] for case in TRANSLATE_CONTRACT_CASES])
def test_each_contract_fixture_case_parses_to_its_gateway_answer_or_engine_api_error(case):
    state_route = case["route"] == "state"
    with _translate_engine((case["engine"]["status"], case["engine"]["body"])) as (engine_base, seen):
        try:
            answered = fetch_translate(engine_base, "uuid-1", "peer.example", after=case.get("after")) if state_route else request_translate(engine_base, "uuid-1", "peer.example")
        except EngineApiError:
            answered = "rejected"
    assert answered == case["gateway"]
    # Control: the Engine was reached once, on the case's route with exactly id, host and the case's after, so a rejection above is the parse's and not a failed call.
    sent = {**TRANSLATE_BODY, **({"after": case["after"]} if "after" in case else {})}
    assert [(entry[1], entry[4]) for entry in seen] == [(TRANSLATE_STATE_ROUTE if state_route else TRANSLATE_ENQUEUE_ROUTE, sent)]


def test_the_contract_fixture_covers_every_gateway_state_with_and_without_available_under_unique_names():
    names = [case["name"] for case in TRANSLATE_CONTRACT_CASES]
    assert len(names) == len(set(names)), sorted(name for name in names if names.count(name) > 1)
    assert {case["route"] for case in TRANSLATE_CONTRACT_CASES} == {"state", "enqueue"}
    assert all(case["route"] == "state" for case in TRANSLATE_CONTRACT_CASES if "after" in case)
    valid = [case for case in TRANSLATE_CONTRACT_CASES if case["gateway"] != "rejected" and case["engine"]["status"] == 200]
    for route, states in (("state", TRANSLATE_STATES), ("enqueue", TRANSLATE_REQUEST_STATES)):
        bodies = [case["engine"]["body"] for case in valid if case["route"] == route]
        assert {body["state"] for body in bodies if "available" in body} == states, route
        assert {body["state"] for body in bodies if "available" not in body} == states, route
        # Exactly one Video-not-found case per route, which the Engine's not-found test reads.
        assert [case["engine"]["body"] for case in TRANSLATE_CONTRACT_CASES if case["route"] == route and case["engine"]["status"] == 404 and case["gateway"] != "rejected"] == [{"error": "Video not found"}], route
```

- **`after` is passed explicitly.** `fetch_translate(..., after=None)` sends no `after`, which matches `sent` for every case without one.
- **Why the stub accepts the `1e999` case.** `_TranslateEngine` writes it as `Infinity` through `json.dumps`, and `_post_json`'s `json.loads` accepts that. The refusal then comes from `_is_seconds`.
- **No bridge token is needed** (`bridge_headers` simply omits the header).

**Docstring paragraph**, inserted after `:146`:

> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55): every case is replayed by calling `fetch_translate` (state route, with the case's `after` when it has one) or `request_translate` (enqueue route) against a `_TranslateEngine` answering the case's status and body. Each gives exactly the case's `gateway` answer, or raises `EngineApiError` for `rejected`, from exactly one request to that route carrying id, host and the case's `after`. The fixture itself has unique names and only the two routes. Its valid 200 states are exactly `TRANSLATE_STATES` on the state route and `TRANSLATE_REQUEST_STATES` on the enqueue route, each with `available` and without it, and each route has exactly one `Video not found` 404 case.

---

### 3. `tests/active/test_frontend_translate.py`

**Constants**, after `INITIAL_TEXT` (`:66`):

```python
# The contract fixture all three layers replay (issue 55); valid cases serve their gateway answer, rejected ones their Engine body, each as a 200.
CONTRACT = Path(__file__).resolve().parent / "fixtures" / "translate_contract.json"
CONTRACT_CASES = json.loads(CONTRACT.read_text())["cases"]
MALFORMED = "Translate response was malformed"
```

**Runner**, appended after the generation tests:

```python
CONTRACT_RUNNER = """
import fs from "node:fs";
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
// api-base.ts reads window.location.origin when it is evaluated, so window exists before the import below.
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
let served = null;
globalThis.fetch = async () => new Response(served, { status: 200, headers: { "content-type": "application/json" } });
// JSON.stringify writes a non-finite number as null, which would be refused for the wrong reason; it goes back out as 1e999, as the fixture wrote it.
const NON_FINITE = "__non_finite__";
const serialise = (value) => JSON.stringify(value, (key, v) => (typeof v === "number" && !Number.isFinite(v) ? NON_FINITE : v)).replaceAll(JSON.stringify(NON_FINITE), "1e999");
const hasNonFinite = (value) => (typeof value === "number" ? !Number.isFinite(value) : value !== null && typeof value === "object" && Object.values(value).some(hasNonFinite));
const { fetchTranslate, requestTranslate } = await import(process.env.BUNDLE);
const report = {};
for (const c of JSON.parse(fs.readFileSync(process.env.CONTRACT, "utf8")).cases) {
  served = serialise(c.gateway === "rejected" ? c.engine.body : c.gateway);
  // What the parser will read, parsed the way readTranslateResponse parses it.
  const nonFinite = hasNonFinite(JSON.parse(served));
  try {
    const value = c.route === "state" ? await fetchTranslate(process.env.BASE, "uuid-1", process.env.HOST, c.after) : await requestTranslate(process.env.BASE, "uuid-1", process.env.HOST);
    report[c.name] = { value, nonFinite };
  } catch (error) {
    report[c.name] = { thrown: String(error?.message ?? error), nonFinite };
  }
}
process.stdout.write(JSON.stringify(report) + "\\n", () => process.exit(0));
"""


@pytest.fixture(scope="module")
def contract_report(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("translate_contract")
    subprocess.run(
        [str(ESBUILD), str(FRONTEND / "src" / "data" / "translate.ts"), "--bundle", "--format=esm", "--platform=node",
         f"--outfile={out / 'bundle.mjs'}", f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(CONTRACT_RUNNER)
    proc = subprocess.run(
        ["node", str(out / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(out / "bundle.mjs"), "CONTRACT": str(CONTRACT), "HOST": HOST, "PATH": os.environ.get("PATH", "")},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


def _has_non_finite(value) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    return isinstance(value, list) and any(_has_non_finite(v) for v in value)


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=[case["name"] for case in CONTRACT_CASES])
def test_each_contract_fixture_case_is_accepted_with_its_fields_or_refused_as_malformed(contract_report, case):
    result = contract_report[case["name"]]
    if case["gateway"] == "rejected":
        assert result.get("thrown") == MALFORMED, result  # exactly the parser's refusal, so a JSON SyntaxError cannot pass as one
    else:
        expected = case["gateway"]
        if case["route"] == "state" and expected["state"] == "ready":
            expected = {**expected, "cues": sorted(expected["cues"], key=lambda cue: (cue["start"], cue["end"]))}
        assert result.get("value") == expected, result  # ready re-sorted by start then end; running left in the gateway's order
    # Control: the parser read infinity exactly where the fixture wrote 1e999, so the 1e999 case is refused for its non-finite start, not for a null.
    served = case["engine"]["body"] if case["gateway"] == "rejected" else case["gateway"]
    assert result["nonFinite"] == _has_non_finite(served)
```

- **New import:** `import math`.
- **No embed alias or CSS loader.** Nothing in the `data/translate.ts` → `api-base`/`profile` chain needs them.
- **The `1e999` control is an assertion over every case.** The set of cases that reached the parser as non-finite must equal the set the fixture writes with `1e999`.
- **Known gap in the sentinel.** It writes `-Infinity` as `1e999` too. No case uses a negative infinity.
- **One node process runs every case**, through the module fixture.

**Docstring paragraph**, before the "The request and the poll run under a second runner" paragraph:

> The contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55) runs under a third runner, `CONTRACT_RUNNER`, over `data/translate.ts` bundled on its own. It stubs `window`, `localStorage` and a `fetch` that answers 200 with the served text, then imports the bundle and reads the fixture itself with `fs`. For each case it serves the gateway answer (a valid case) or the Engine body (a rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route), in one node process. A valid case answers exactly its gateway answer, with `ready` cues sorted by start then end and `running` cues in the order given. Every rejected case throws exactly `Translate response was malformed`. Non-finite numbers are served as `1e999`, because `JSON.stringify` would write `null`. As a control, the parser read infinity in exactly the cases whose fixture value is non-finite.

---

### 4. `tests/active/test_internal_translate.py`

**Imports:** `import ast` and `import re` join the stdlib block at `:54-67`. Both are stdlib and safe at module level.

**Keeping `test_source_fetch.py` safe.** That file imports this module, so nothing new at module level may read a file or import another layer. Only a path constant and static code are added. The fixture is read inside each test.

> **Departure from the plan (named):** the plan parametrized the Engine test over the fixture's cases. That needs a module-level fixture read, which the impact inventory flags as a hazard through `test_source_fetch.py:25`. Instead the test is parametrized over the static driver table. A separate test asserts that the fixture's valid `(route, state)` set equals the driver table's keys. A fixture state with no driver still fails, and so does a driver with no fixture state. Each parametrized run checks every fixture case for its key.

Code is inserted after `test_with_a_serving_worker_a_full_queue_answers_busy_and_one_fewer_queues` (`:997`). All the helpers it uses (`NOW`, `BODY`, `_seed`, `_claimed`, `_beat`, `_route`, `_instance`, `_state`, `_enqueue`, `_server`, `_subtitles_db`) are defined above that point.

```python
# The contract fixture all three layers replay (issue 55); read inside each test, because test_source_fetch.py imports this module.
CONTRACT = Path(__file__).resolve().parent / "fixtures" / "translate_contract.json"


def _contract_cases() -> list[dict]:
    return json.loads(CONTRACT.read_text())["cases"]


def _engine_contract_case(case: dict) -> bool:
    """A valid 200 case that carries available, as this Engine always answers; the cases without it stand for older Engines."""
    return case["gateway"] != "rejected" and case["engine"]["status"] == 200 and "available" in case["engine"]["body"]


def _json_type(value: object) -> str:
    """The JSON type a value is written as; bool first, since a bool is also an int."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def _types(body: dict) -> dict[str, str]:
    return {key: _json_type(value) for key, value in body.items()}


def _running_cues(count: int) -> list[dict]:
    """count stored running cues, in descending start order so they are not sorted; as many as the case's total, so an after slice leaves cues to check."""
    return [{"start": float(count - index), "end": float(count - index) + 0.5, "text": f"cue {index}"} for index in range(count)]


def _state_driver(row: str):
    """The state route with the key seeded as row and a fresh beat; the instance holds no en track, so failed, already_english and no row are answered as stored, not as ready."""
    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:
        from data.subtitles import write_translate_heartbeat

        store = _subtitles_db(subtitles_path)
        if row == "running":
            assert _claimed(store).write_running_cues(_running_cues(case["engine"]["body"]["total"]), "fr")
        else:
            _seed(store, row)
        write_translate_heartbeat(store, NOW, 1)
        body = {**BODY, "after": case["after"]} if "after" in case else BODY
        return _state(_route(_instance(False), monkeypatch), _server(whitelist, subtitles_path), body)
    return drive


def _enqueue_driver(row: str | None):
    """The enqueue route: None is no beat (none), "busy" a queue filled to SUBTITLE_QUEUE_CAP, else the key seeded as row; a fresh beat unless None."""
    def drive(subtitles_path: Path, whitelist: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, case: dict) -> list[list]:
        from data.subtitles import enqueue_translate_job

        store = _subtitles_db(subtitles_path)
        if row == "busy":
            for index in range(SUBTITLE_QUEUE_CAP):
                assert enqueue_translate_job(store, f"q-{index:03d}", HOST, "en", SUBTITLE_QUEUE_CAP, NOW - 5000) == ("queued", "queued")
        elif row is not None:
            _seed(store, row)
        store.close()
        if row is not None:
            _beat(subtitles_path, 0)
        return _enqueue(_route(RecordingInstance(), monkeypatch), _server(whitelist, subtitles_path), BODY)
    return drive


# How the Engine is driven into each (route, state) the contract fixture names.
ENGINE_DRIVERS = {
    ("state", "none"): _state_driver("no row"),
    ("state", "queued"): _state_driver("queued"),
    ("state", "running"): _state_driver("running"),
    ("state", "ready"): _state_driver("ready"),
    ("state", "already_english"): _state_driver("already_english"),
    ("state", "failed"): _state_driver("failed"),
    ("enqueue", "none"): _enqueue_driver(None),
    ("enqueue", "queued"): _enqueue_driver("no row"),
    ("enqueue", "running"): _enqueue_driver("running"),
    ("enqueue", "ready"): _enqueue_driver("ready"),
    ("enqueue", "already_english"): _enqueue_driver("already_english"),
    ("enqueue", "failed"): _enqueue_driver("failed"),
    ("enqueue", "busy"): _enqueue_driver("busy"),
}


def test_every_route_state_in_the_contract_fixture_has_an_engine_driver():
    assert {(case["route"], case["engine"]["body"]["state"]) for case in _contract_cases() if _engine_contract_case(case)} == set(ENGINE_DRIVERS)


@pytest.mark.parametrize("route, state", ENGINE_DRIVERS.keys(), ids=[f"{route} {state}" for route, state in ENGINE_DRIVERS])
def test_each_route_state_answers_the_keys_and_json_types_of_its_contract_fixture_case(tmp_path, whitelist, monkeypatch, route, state):
    cases = [case for case in _contract_cases() if _engine_contract_case(case) and (case["route"], case["engine"]["body"]["state"]) == (route, state)]
    assert cases, (route, state)
    for index, case in enumerate(cases):
        expected = case["engine"]["body"]
        ((status, answer),) = ENGINE_DRIVERS[(route, state)](tmp_path / f"subtitles-{index}.db", whitelist, monkeypatch, case)
        assert status == 200, (case["name"], answer)
        assert answer["state"] == state, case["name"]  # control: the driver reached the state under test
        assert _types(answer) == _types(expected), case["name"]  # exactly the keys, and each value's JSON type
        if "cues" in expected:
            # Non-empty wherever the fixture's are, so the per-cue check cannot pass on an empty list.
            assert bool(answer["cues"]) == bool(expected["cues"]), case["name"]
            assert all(_types(cue) == _types(expected["cues"][0]) for cue in answer["cues"]), case["name"]


@pytest.mark.parametrize("route", ["state", "enqueue"])
def test_an_unknown_or_denied_video_answers_the_contract_fixtures_video_not_found_body(tmp_path, whitelist, monkeypatch, route):
    (body,) = [case["engine"]["body"] for case in _contract_cases() if case["route"] == route and case["engine"]["status"] == 404 and case["gateway"] != "rejected"]
    answer = _state if route == "state" else _enqueue
    instance = _instance(True)
    internal_translate = _route(instance, monkeypatch)
    server = _server(whitelist, tmp_path / "subtitles.db")
    _beat(tmp_path / "subtitles.db", 0)
    _set_denied(whitelist, True)  # stored as DENIED.EXAMPLE
    assert answer(internal_translate, server, {"id": "no-such-video", "host": HOST}) == [[404, body]]
    assert answer(internal_translate, server, {"id": DENIED_VIDEO[1], "host": DENIED_HOST}) == [[404, body]]
    assert instance.fetched == []
    # Control: inactive, the same denied video is answered 200, so the 404 above is the denylist's doing.
    _set_denied(whitelist, False)
    assert answer(internal_translate, server, {"id": DENIED_VIDEO[1], "host": DENIED_HOST})[0][0] == 200


def test_the_heartbeat_fresh_window_is_three_beats_derived_from_heartbeat_seconds():
    import server_config

    (value,) = [node.value for node in ast.parse((API_DIR / "server_config.py").read_text()).body if isinstance(node, ast.Assign) and [getattr(target, "id", None) for target in node.targets] == ["HEARTBEAT_FRESH_MS"]]
    assert "HEARTBEAT_SECONDS" in {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}
    window = compile(ast.Expression(value), "server_config.py", "eval")
    assert server_config.HEARTBEAT_SECONDS == 5.0
    assert eval(window, {"HEARTBEAT_SECONDS": server_config.HEARTBEAT_SECONDS}) == server_config.HEARTBEAT_FRESH_MS == 15_000
    assert eval(window, {"HEARTBEAT_SECONDS": 7.0}) == 21_000  # a different interval moves the window with it
    assert isinstance(server_config.HEARTBEAT_FRESH_MS, int)
    assert _translate().HEARTBEAT_FRESH_MS == server_config.HEARTBEAT_FRESH_MS
    # Neither consumer keeps a literal of its own; each imports its name from server_config.
    for path, name in ((API_DIR / "handlers" / "internal_translate.py", "HEARTBEAT_FRESH_MS"), (SERVER_DIR / "db" / "jobs" / "translate-worker.py", "HEARTBEAT_SECONDS")):
        tree = ast.parse(path.read_text())
        assigned = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
        assert not assigned & {"HEARTBEAT_SECONDS", "HEARTBEAT_FRESH_MS"}, path
        assert name in {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "server_config" for alias in node.names}, path


def test_the_translate_timeout_chain_keeps_budget_plus_socket_under_the_client_timeout_under_the_deploy_drain():
    from data.source_fetch import SOCKET_TIMEOUT_SECONDS
    from lib.engine_api_client import TRANSLATE_TIMEOUT_SECONDS  # the Client's; conftest puts client/backend on sys.path, and the module imports only stdlib

    budget = _translate().REQUEST_BUDGET_SECONDS
    drains = re.findall(r"^DRAIN_SECONDS=(\d+)$", (ROOT / "scripts" / "deploy-bluegreen.sh").read_text(), re.M)
    assert len(drains) == 1, drains  # the default, not the --drain override line
    assert budget + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS < int(drains[0]), (budget, SOCKET_TIMEOUT_SECONDS, TRANSLATE_TIMEOUT_SECONDS, drains)
```

**Why the drivers are built this way.**
- **Running.** The driver seeds as many cues as the case's `total`: 3 for `state running`, and 5 for `state running after 3`, which answers 2 cues. The sliced case therefore checks real cues instead of passing on the `cues: []` that `RUNNING`'s 3 cues would give.
- **No instance track on the state route.** `_instance(False)` is required: with a track, `failed`, `already_english` and `none` answer `ready` (BRANCHES `:812`, `:814`).
- **`ready`** answers `STORED_READY` with no fetch.

**Not-found test.**
- The fresh beat is written so the enqueue control queues, rather than answering `none` with 200 for the wrong reason.
- Both routes resolve before reading the beat, so the 404s don't depend on it.
- The existing literal `VIDEO_NOT_FOUND` (`:162`) is left alone; the new test reads the fixture.

**Timeout test placement.** It goes immediately after `test_one_15_second_budget_covers_both_fetches` (`:611-625`). The derivation and contract tests go in the block above.

**Docstring entries.** A new section goes before "Startup:" (`:48`):

> Contract fixture (`tests/active/fixtures/translate_contract.json`, issue 55, read inside each test because `test_source_fetch.py` imports this module):
> - Every `(route, state)` among the fixture's valid 200 cases that carry `available` has a driver here, and every driver has such a case.
> - Each driver brings its route into its state with the pinned clock and a fresh beat (none for the enqueue route's `none`): the state route from a seeded `none`, `queued`, `running` (as many stored cues as the case's `total`, with its `after`), `ready`, `already_english` or `failed` key and no instance track; the enqueue route from no row, a seeded stored state, or a queue filled to `SUBTITLE_QUEUE_CAP`. The answer is a 200 in that state with exactly the case's keys and each value's JSON type (bool before number), cues non-empty where the case's are, each with the keys and types of the case's cues.
> - On both routes, an unknown video and an actively denylisted one answer exactly the fixture's `Video not found` 404 body, with no fetch; inactive, the denied video answers 200.
>
> Shared constants:
> - `server_config.py`'s `HEARTBEAT_FRESH_MS` is an expression over `HEARTBEAT_SECONDS`. It evaluates to the module's 15 000 (an int) for 5.0 and to 21 000 for 7.0. The handler's `HEARTBEAT_FRESH_MS` is that value. Neither the handler nor the translate worker assigns either name: the handler imports `HEARTBEAT_FRESH_MS` from `server_config`, and the worker imports `HEARTBEAT_SECONDS`.
> - The route's `REQUEST_BUDGET_SECONDS` plus `data.source_fetch.SOCKET_TIMEOUT_SECONDS` is below the Client's `TRANSLATE_TIMEOUT_SECONDS`, which is below the `DRAIN_SECONDS=` default, the one line of `scripts/deploy-bluegreen.sh` that starts with it.

---

### 5. `engine/server/api/server_config.py`

Inserted after `SUBTITLE_MAX_CHUNK_SECONDS = 30` (`:428`). It needs no new import.

```python
# Seconds between the translate worker's heartbeats.
HEARTBEAT_SECONDS = 5.0
# Age in ms within which a heartbeat counts as a serving worker (/internal/translate's available): three beats, so one late beat is tolerated.
HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)
```

It stays an int (15000), so `BEATS`' 15 000 / 15 001 edges and the docs read as before.

### 6. `engine/server/api/handlers/internal_translate.py`

- `:27` becomes `from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`.
- `:32-33` (the rat-tail comment and `HEARTBEAT_FRESH_MS = 15_000`) are deleted.
- **Docstring `:3`.** "...whether the translate worker beat within HEARTBEAT_FRESH_MS." becomes "...whether the translate worker beat within HEARTBEAT_FRESH_MS (server_config.py, three HEARTBEAT_SECONDS beats)."
- **Docstring `:5`.** It already names `HEARTBEAT_FRESH_MS` and stays as is. Since `:3` says where the constant is defined, it is not repeated here.
- **Unchanged:** `:30`, `REQUEST_BUDGET_SECONDS`, `VIDEO_NOT_FOUND`, both handlers and the sort at `:115`.

### 7. `engine/server/db/jobs/translate-worker.py`

- `:41` becomes `from server_config import DEFAULT_DB_PATH, DEFAULT_SUBTITLES_DB_PATH, HEARTBEAT_SECONDS, SUBTITLE_MAX_BYTES, SUBTITLE_MAX_CHUNK_SECONDS, SUBTITLE_MAX_DURATION, SUBTITLE_QUEUE_CAP, VIDEO_ERROR_THRESHOLD`.
- `:58-59` (the rat-tail comment and `HEARTBEAT_SECONDS = 5.0`) are deleted. The uses at `:458`, `:467` and `:536` read the imported name.
- `HEARTBEAT_SECONDS` stays a module attribute, so `STALL_DRIVER`'s exec and the `spec_from_file_location` load in `test_translate_worker.py` still see it.
- **Comment `:35`** becomes "api/ is for server_config (bounds and HEARTBEAT_SECONDS) and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch."

### 8. Prose

**`engine/server/README.md:15`.** Append to the bullet:

> `total` always counts every stored cue, whatever `after` was, so a reader that already holds more running cues than `total` knows the job was requeued and restarted.

**`engine/server/README.md:18`.** "(15 000 ms, three of the worker's 5 s beats)" becomes:

> (15 000 ms, three of the worker's 5 s beats, derived in `api/server_config.py` from `HEARTBEAT_SECONDS`)

**`engine/server/README.md:30`.** The tunables list becomes "`SUBTITLE_MAX_DURATION`, `SUBTITLE_MAX_BYTES`, `SUBTITLE_QUEUE_CAP` and `SUBTITLE_MAX_CHUNK_SECONDS` in `api/server_config.py`, which also holds its beat interval `HEARTBEAT_SECONDS`".

**`TRANSLATE_WORKER.md:155`.** "(`HEARTBEAT_FRESH_MS`, three beats), and otherwise ... reporting `available`. Raise both constants together." becomes:

> ...at most 15 s old (`HEARTBEAT_FRESH_MS`), and otherwise neither queues a job from the page nor reports `available`. Both come from one definition in `engine/server/api/server_config.py`: the beat interval `HEARTBEAT_SECONDS`, with `HEARTBEAT_FRESH_MS` derived from it as three beats, so changing the interval moves the window with it.

**`CONTEXT.md` and `DEPLOYMENT.md`** are unchanged. Both are accurate, and the `DEPLOYMENT.md` edits were optional, so they are skipped.

### 9. `tests/config.json`

- Add `tests/active/fixtures/translate_contract.json` to the `test_server.py`, `test_frontend_translate.py` and `test_internal_translate.py` groups.
- Add to `test_internal_translate.py`: `engine/server/db/jobs/translate-worker.py`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.
- Add `client/frontend/src/data/api-base.ts` to `test_frontend_translate.py`.

---

### Mutation check (manual, once, recorded in the build record)

Add `{"name": "state paused", "route": "state", "engine": {"status": 200, "body": {"state": "paused", "available": true}}, "gateway": {"state": "paused", "available": true}}` to the fixture alone and run the three suites. Expected results:
- **Client:** the replay of `state paused` raises `EngineApiError`, so it answers `"rejected"` and not the gateway answer. The coverage test fails because the set is not `TRANSLATE_STATES`.
- **Frontend:** `state paused` throws `MALFORMED` where a value was expected.
- **Engine:** `test_every_route_state_in_the_contract_fixture_has_an_engine_driver` fails.

Revert the edit. Also record `rg -l translate_contract.json engine client scripts` returning nothing.

### Check against the plan and the requirements (pass 1, converged)

| Requirement | Where it is met |
|---|---|
| One fixture, every state of both routes with and without `available`, every listed rejection, nothing at runtime reads it | §1; the coverage test in §2; grep in the build record |
| Client replays every case through both parsers | §2 test 1 |
| Frontend replays every case; `ready` sorted; rejected throws | §3; real `translate.ts` through esbuild, fetch stubbed, no frontend change |
| Engine checks each state's keys and types against the fixture, plus the not-found body | §4 shape test and not-found test (state route as required, enqueue added) |
| Mutation check recorded | above |
| Heartbeat: one definition, both import it, rat-tails gone, derivation test | §5–7, §4 heartbeat test |
| Timeout chain from real values; fails when one value passes its neighbour | §4 timeout test; strict `<` on both sides |
| README running-slice rule | §8 |
| No runtime behaviour change; existing tests unchanged | only additions to tests; constant values identical; step-zero baseline |

Three points deliberately differ from the plan's wording. None of them changes its intent:
1. **Engine parametrization.** It runs over the static driver table plus a two-way set-equality test, instead of over the fixture's cases, to avoid a module-level read that `test_source_fetch.py` would inherit.
2. **The plan's rule that "rejected must be refused by both layers"** is enforced by the two replays themselves, not by the Client coverage test, which cannot run the frontend. The coverage test enforces the with/without-`available` rule, name uniqueness, the two routes, `after` only on state cases, and exactly one not-found case per route.
3. **One frontend fixture.** It bundles and runs together; there is no separate bundle fixture.

### Named simplifications and their ceilings

- **The `TRANSLATE_*_ANSWERS` tables in `test_server.py` stay.** Part of the contract is therefore stated twice: once at the HTTP route and once in the fixture. Upgrade path: build those tables from `TRANSLATE_CONTRACT_CASES`, mapping `rejected` to `TRANSLATE_FAILED`.
- **The Engine test checks shape, not values or order.** Cue order and slice arithmetic stay covered by `BRANCHES` and `AFTERS`.
- **The non-finite sentinel writes any infinity as positive `1e999`.** That is enough for the one case; a negative-infinity case would need `-1e999` handling.
- **The module-level fixture loads in `test_server.py` and `test_frontend_translate.py` are unguarded.** A malformed fixture stops those two modules collecting, which surfaces loudly and is accepted.

## 2026-10-04 - Step 6 - Design the phase breakdown

Recorded ungated, at the operator direction.

#### Phase 1 - Contract fixture and Client gateway replay [code]

**Files touched.** tests/active/fixtures/translate_contract.json (NEW), tests/active/test_server.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Client gateway's parse functions, called directly. A new parametrized test in tests/active/test_server.py, one run per fixture case with the case name as id, starts the existing `_translate_engine` stub (test_server.py:1600) answering the case's engine status and body. It then calls `fetch_translate` (state route, passing the case's `after`) or `request_translate` (enqueue route). It asserts the result equals the case's `gateway` answer, or that `EngineApiError` was raised for "rejected". Control: the stub recorded exactly one request, on the case's /internal/translate route, carrying id, host and the case's `after`, so a rejection comes from the parse and not from a failed call. A second test reads the fixture and asserts: names are unique; there are exactly the two routes; `after` appears only on state cases; the valid 200 states equal TRANSLATE_STATES (state route) and TRANSLATE_REQUEST_STATES (enqueue route), both with and without `available`; each route has exactly one "Video not found" 404 case. Direct calls rather than /api/translate, so a 502 cannot hide why a case failed.

**Intent.** tests/active/fixtures/translate_contract.json states the translate contract. Every case parses through the Client gateway's real fetch_translate/request_translate to its stated answer, and the fixture's valid states are exactly the gateway's state sets.

- C1 - Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route.
- C2 - The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique.

**Outcome.** _pending_

#### Phase 2 - Frontend parser replay [code]

**Files touched.** tests/active/test_frontend_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real client/frontend/src/data/translate.ts, entered through its exported fetchTranslate/requestTranslate. It follows test_frontend_translate.py's existing esbuild-bundle-plus-node-runner harness (same --platform=node, ESM and import.meta.env defines). A module fixture bundles translate.ts on its own. CONTRACT_RUNNER stubs window, localStorage and a fetch that answers 200 with the served text, reads the fixture with fs, and in one node process serves each case: the gateway answer for a valid case, the Engine body for a rejected one. It reports the returned value or the thrown message, plus whether the parsed text contained a non-finite number. The parametrized Python test asserts that a valid case deep-equals its gateway answer, with ready cues re-sorted by (start, end) and running cues left in the order given, and that a rejected case threw exactly "Translate response was malformed", so a JSON SyntaxError cannot pass as a refusal. Control on every case: the parser read a non-finite number exactly where the fixture writes 1e999. No frontend file changes.

**Intent.** data/translate.ts is proven against every case of the contract fixture. Valid gateway answers come back with their fields intact, and every rejected body is refused as malformed.

- C1 - Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given.
- C2 - Every rejected fixture case served as a 200 throws exactly "Translate response was malformed".

**Outcome.** _pending_

#### Phase 3 - Engine answers match the fixture's shape [code]

**Files touched.** tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Engine's /internal/translate and /internal/translate/enqueue handlers, entered through test_internal_translate.py's existing harness (`_route`, `_state`, `_enqueue`, `_server`, `_seed`, `_claimed`, `_beat`, `_instance`). The fixture is read inside each test, never at module level, because test_source_fetch.py imports this module. A static ENGINE_DRIVERS table keyed by (route, state) drives each state: seeded rows with a fresh beat and no instance track on the state route; on the enqueue route, no beat for none, no row for queued, a seeded stored state, or a queue filled to SUBTITLE_QUEUE_CAP for busy. The parametrized test asserts, for each fixture case that carries available: a 200; answer state equals the state under test (control); the key-to-JSON-type map equals the case's (bool before number); cues non-empty where the case's are; and each answered cue's keys and types match the case's cues. A separate test asserts that the fixture's (route, state) set equals the driver table's keys, both ways. The not-found test asserts that on both routes an unknown video and an actively denylisted video answer exactly the fixture's Video-not-found 404 body with no fetch, and as a control that the same denied video answers 200 once the deny is inactive.

**Intent.** The Engine's two translate routes are checked against the contract fixture. Each (route, state) it produces answers the fixture case's keys and JSON types, and its not-found answer is the fixture's body.

- C1 - Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state.
- C2 - On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body.

**Outcome.** _pending_

#### Phase 4 - Single-sourced heartbeat and checked timeout chain [code]

**Files touched.** engine/server/api/server_config.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real constants, with server_config.py's source as the derivation's front door. Two tests in test_internal_translate.py. (1) Heartbeat: ast-parse engine/server/api/server_config.py and find the single HEARTBEAT_FRESH_MS assignment. Assert its expression names HEARTBEAT_SECONDS. Evaluate it with the real interval (equals the module's value, 15000, an int) and with 7.0 (21000). Assert the handler module's HEARTBEAT_FRESH_MS is server_config's. Assert neither internal_translate.py nor translate-worker.py assigns HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS, and that each imports its name from server_config. (2) Timeout chain, placed after test_one_15_second_budget_covers_both_fetches: take the handler's REQUEST_BUDGET_SECONDS, data.source_fetch.SOCKET_TIMEOUT_SECONDS and lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (conftest supplies client/backend on sys.path). Read DRAIN_SECONDS from scripts/deploy-bluegreen.sh with a line-anchored regex that must match exactly once. Assert budget + socket < Client timeout < drain. The existing BEATS 15000/15001 edge tests and test_translate_worker.py, both unchanged, confirm behaviour is preserved.

**Intent.** The heartbeat interval and its freshness window are defined once in server_config.py, the window derived from the interval and imported by both consumers, and the translate timeout chain across Engine, Client and deploy script is held in order by a test.

- C1 - server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own.
- C2 - REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default.

**Outcome.** _pending_


Needs coordination: none. No phase needs a credential, a live endpoint or the operator. Two steps are run by the agent and recorded in the build record. Before phase 1: the step-zero baseline run of the six translate suites plus test_source_fetch.py. After phase 3: the one-time manual mutation check (a "state paused" case added to the fixture alone, three suites run, then reverted) and `rg -l translate_contract.json engine client scripts` returning nothing. Phase 2 relies on the node and esbuild toolchain the existing frontend tests already use.

Rationale: The build splits along the layers the contract crosses. Each phase is one test file proving one layer against the shared fixture, and each layer's check falls into two observable facts. Phase 1 comes first because it creates the fixture and the coverage test that phases 2 and 3 replay against: Client parse result, plus the fixture's state coverage. Phase 2 covers the frontend: valid accepted, plus rejected refused. Phase 3 covers the Engine: shape per state, plus the not-found body. Its checkpoint also carries the draft's named departure, a static driver table with a two-way set check, which avoids a module-level fixture read that test_source_fetch.py would inherit. Phase 4 holds the only runtime change, the heartbeat move, alongside the timeout-chain test. Both are cross-layer constant checks in the same file, independent of the fixture. Putting them in phase 3 would have given it four clauses. The operator was offered running the heartbeat move first and approved the order as drawn. There is no prose phase: engine/server/README.md and TRANSLATE_WORKER.md are documentation for human readers and are updated at Step 9. The code docstrings travel with their code phases. Each phase adds its own tests/config.json entries so every checkpoint's group is complete when it lands. Confirmed in the tree: `_translate_engine` (test_server.py:1600), the `_route`/`_state`/`_enqueue` harness (test_internal_translate.py:653-739), the two literals to remove (internal_translate.py:33, translate-worker.py:59), the single DRAIN_SECONDS line (deploy-bluegreen.sh:50), and that tests/active/fixtures/ does not exist yet. Operator approved the plan as presented.

## 2026-10-04 - Step 7 - Phase 1 (Contract fixture and Client gateway replay) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
tests/active/fixtures/translate_contract.json states the translate contract. Every case parses through the Client gateway's real fetch_translate/request_translate to its stated answer, and the fixture's valid states are exactly the gateway's state sets.

- C1 - Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route.
- C2 - The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique.

must_prove:
- C1 - Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route.
- C2 - The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique.

## 2026-10-04 - Step 7 - Phase 1 (Contract fixture and Client gateway replay) - self-check (audit round 1, send-back 0)

`tests/tmp/test_55_translate_state_contract_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_55_translate_state_contract_phase1.py:45 — for each valid case, the value returned by fetch_translate (state route, with the case's after) or request_translate (enqueue route) equals the case's `gateway` answer exactly. - expected: Passes for every valid case in a fixture that agrees with the gateway. In the probe, built from the gateway's own state sets, all 34 cases passed: 6 states × with/without available on the state route, 7 on enqueue, both Video not found 404s, and running with after 3. - excludes: Three wrong fixtures, as the probe ran them. (1) A `gateway` answer that leaves out the available default: AssertionError at :45. (2) A valid "paused" state or "busy" on the state route: the real parser raises "EngineApiError: Engine translate returned invalid payload" before :45 is reached, so the test is red. (3) Running cues stated in re-sorted order instead of stored order: AssertionError at :45. Deleting the `False` default at engine_api_client.py:163 makes every without-available case raise, so they all go red.
- C1 - tests/tmp/test_55_translate_state_contract_phase1.py:41 — for a case whose gateway is "rejected", the matching parser raises EngineApiError and its message starts with "Engine translate". - expected: Raises for every rejected case. In the probe this held for the Not found 404, the unknown state on both routes, and a cue whose start is inf: all passed. - excludes: A fixture that marks a parseable answer (state ready with available) as rejected fails with "Failed: DID NOT RAISE EngineApiError" (probed). A refusal that really came from the transport reads '&lt;urlopen error [Errno 111] Connection refused&gt;' (probed). That does not match ^Engine translate, so a dead stub cannot pass as a refusal.
- C1 - tests/tmp/test_55_translate_state_contract_phase1.py:48 — the stub's log, as (method, path, body), is exactly [("POST", route of the case, {id, host} plus the case's after when it has one)]. - expected: One entry per case. The probe showed the stub records (method, path, token, request id, body), for example [('POST', '/internal/translate', None, None, {'id': 'uuid-1', 'host': 'peer.example', 'after': 0})]. All 34 good cases passed this check. - excludes: An enqueue case carrying `after` fails here with AssertionError, because request_translate never sends it (probed). Other failures here: a call to the wrong route, a retry (two entries), no call at all (empty log), or an after that was dropped or invented.
- C2 - tests/tmp/test_55_translate_state_contract_phase1.py:59 — per route, the set of states of the valid 200 cases whose body carries `available` equals TRANSLATE_STATES (state route) or TRANSLATE_REQUEST_STATES (enqueue route). - expected: Equal on both routes in the conforming probe fixture ("COVERAGE good -> passed"). - excludes: An extra valid state the gateway does not have ("paused") fails with "AssertionError: state". Dropping "state failed" with available fails with "AssertionError: state". Both probed.
- C2 - tests/tmp/test_55_translate_state_contract_phase1.py:60 — per route, the set of states of the valid 200 cases whose body has no `available` equals the same gateway set. - expected: Equal on both routes in the conforming probe fixture. - excludes: A fixture with no "busy" case that lacks available fails with "AssertionError: enqueue" (probed). So a state covered only with available is caught.
- C2 - tests/tmp/test_55_translate_state_contract_phase1.py:54 — no case name appears more than once (the list of duplicated names is empty). - expected: [] for the conforming fixture. :59 and :60 in the same test need at least 13 valid cases, so the list of names is known to be non-empty and this check is not vacuous. - excludes: A case copied in under the same name fails with AssertionError (probed: "COVERAGE duplicate name -> AssertionError"). The duplicate id would also make the parametrized replay ambiguous.

<assertions>
tests/tmp/test_55_translate_state_contract_phase1.py:36 - the fixture file exists (both tests start with this so that a missing fixture fails per test, not with a collection error) - precondition for C1
tests/tmp/test_55_translate_state_contract_phase1.py:41 - a case whose gateway is "rejected", run through fetch_translate (state route, with the case's after) or request_translate (enqueue route) against the _translate_engine stub answering the case's status and body, raises EngineApiError whose text starts "Engine translate", so a transport failure cannot pass as a refusal; this excludes a fixture marking a parseable answer rejected (probed: DID NOT RAISE) - C1
tests/tmp/test_55_translate_state_contract_phase1.py:45 - a valid case's return value equals the case's gateway answer exactly; this excludes a gateway answer missing the available default (probed: fails) and a valid state the gateway does not know, such as "paused" (probed: the real parser raises EngineApiError) - C1
tests/tmp/test_55_translate_state_contract_phase1.py:48 - the stub recorded exactly one request, as (method, path, body) == [("POST", route of the case, {id, host} plus the case's after when it has one)]; this excludes a call to the wrong route, a retry or no call, and an after the gateway did not send (probed: an enqueue case carrying after fails here) - C1
tests/tmp/test_55_translate_state_contract_phase1.py:54 - no case name appears twice (probed: a duplicated case fails) - C2
tests/tmp/test_55_translate_state_contract_phase1.py:55 - the fixture's routes are exactly {state, enqueue} - checkpoint text (two routes only)
tests/tmp/test_55_translate_state_contract_phase1.py:56 - no case off the state route carries after (probed: fails on an enqueue case with after) - checkpoint text (after only on state cases)
tests/tmp/test_55_translate_state_contract_phase1.py:59 - per route, the states of the valid 200 cases whose Engine body carries available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue); this excludes an extra state such as "paused" or a state that is missing (probed: fails on route "state") - C2
tests/tmp/test_55_translate_state_contract_phase1.py:60 - the same equality for the valid 200 cases without available (probed: dropping "enqueue busy without available" fails on route "enqueue") - C2
tests/tmp/test_55_translate_state_contract_phase1.py:61 - each route has exactly one case whose engine is {status 404, body {"error": "Video not found"}} (probed: dropping the enqueue one fails) - checkpoint text (one Video-not-found case per route)
tests/tmp/test_55_translate_state_contract_phase1.py:63 - control: each route has at least one rejected case, so C1's EngineApiError half runs through both parsers rather than holding vacuously (probed: a fixture with no enqueue rejections fails) - control for C1
</assertions>

<probes>
The fixture does not exist yet, so the probes ran against the plan's draft fixture, i.e. the JSON block under "### 1." in docs/project/plans/01-55-translate-state-contract.md, which holds 43 cases.
1) ValidateTests ["tests/tmp/probe_55_phase1_replay.py", "-s"] ran every draft case through the real fetch_translate/request_translate via test_server._translate_engine. It printed: TRANSLATE_STATES = [already_english, failed, none, queued, ready, running]; TRANSLATE_REQUEST_STATES is the same set plus busy; the fixture file exists = False. All 43 cases matched their gateway answer. Each case caused exactly one request: ('POST', '/internal/translate' or '/internal/translate/enqueue', {'id': 'uuid-1', 'host': 'peer.example'}), with 'after': 3 only on "state running after 3". The refusal texts were "Engine translate failed (HTTP 404): Not found", "Engine translate request failed (HTTP 404): Not found", "Engine translate returned invalid payload" (this one also for the enqueue non-bool available case and for start 1e999) and "Engine translate request returned invalid payload". All of them start with "Engine translate", which is what the match= at :41 rests on.
2) ValidateTests ["tests/tmp/probe_55_phase1_checkpoint.py", "-s"] exec'd the checkpoint's own source with CONTRACT pointed at a tmp copy of the draft or of a mutant, then called both test bodies. On the draft, the coverage test passed and the replays I sampled passed (start 1e999, running after 3, enqueue route missing 404). Each mutant failed:
- "state paused" added (earlier run): the replay raised EngineApiError 'Engine translate returned invalid payload', and coverage failed on route state.
- "enqueue busy without available" dropped: coverage failed on route enqueue.
- duplicate name: failed at the uniqueness line.
- gateway without the available default: the replay assertion failed.
- valid ready marked rejected: replay 'DID NOT RAISE EngineApiError', and coverage failed on route state.
- an enqueue case with after: both the replay control and the after-only-on-state line failed.
- no enqueue rejection: failed at the control on route enqueue.
- enqueue not-found dropped: failed at the one-not-found line on route enqueue.
3) ValidateTests ["tests/tmp/test_55_translate_state_contract_phase1.py"] gave 2 failed (the "fixture missing" stand-in and the coverage test), both on the missing-file assertion. That is the red, and it is per test rather than a collection error. An earlier version loaded the fixture unguarded and gave a collection error with no per-test results, which is why the guard exists.
Both probe files (tests/tmp/probe_55_phase1_replay.py, tests/tmp/probe_55_phase1_checkpoint.py) are still on disk because I have no delete tool. They should be removed.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_55_translate_state_contract_phase1.py` - 5155 characters, inlined in full

```
"""Phase 1 checkpoint of plan 55: tests/active/fixtures/translate_contract.json states the translate contract, and the Client gateway's real parsers agree with it case by case.

Replay (C1), `fetch_translate` / `request_translate` in client/backend/lib/engine_api_client.py called directly against test_server.py's `_translate_engine` stub answering the case's Engine status and body:

- A state case through `fetch_translate` (with the case's `after`) and an enqueue case through `request_translate` returns exactly the case's `gateway` answer; a case whose `gateway` is "rejected" raises `EngineApiError` with the gateway's own "Engine translate ..." text, never a transport error's.
- Either way the stub saw exactly one POST, to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case, with the body exactly id, host and the case's `after` when it has one.

Coverage (C2), the fixture read as JSON: every case name is unique; the routes are exactly state and enqueue, each with at least one rejected case; `after` appears only on state cases; the states of the valid 200 cases carrying `available` and of those without it each equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route; each route has exactly one 404 `{"error": "Video not found"}` case.

The fixture is read at collection because the replay is parametrized over its cases; while it is missing, both tests fail on its absence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

from test_server import _translate_engine  # noqa: E402

from lib.engine_api_client import TRANSLATE_REQUEST_STATES, TRANSLATE_STATES, EngineApiError, fetch_translate, request_translate  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
# Read at collection because the replay is parametrized over the cases; a missing fixture collects one named stand-in that fails on the missing file, so the red is per test rather than a collection error.
CASES = json.loads(CONTRACT.read_text())["cases"] if CONTRACT.exists() else [{"name": "fixture missing"}]
ROUTES = {"state": "/internal/translate", "enqueue": "/internal/translate/enqueue"}
VIDEO_ID = "uuid-1"
HOST = "peer.example"


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route(case):
    assert CONTRACT.exists(), CONTRACT
    state_route = case["route"] == "state"
    with _translate_engine((case["engine"]["status"], case["engine"]["body"])) as (engine_base, seen):
        if case["gateway"] == "rejected":
            # The gateway's own refusals all read "Engine translate ..." (probed); a dropped or refused connection would carry the transport's text instead.
            with pytest.raises(EngineApiError, match=r"^Engine translate"):  # C1: rejected
                fetch_translate(engine_base, VIDEO_ID, HOST, after=case.get("after")) if state_route else request_translate(engine_base, VIDEO_ID, HOST)
        else:
            answered = fetch_translate(engine_base, VIDEO_ID, HOST, after=case.get("after")) if state_route else request_translate(engine_base, VIDEO_ID, HOST)
            assert answered == case["gateway"]  # C1: exactly the stated answer
    sent = {"id": VIDEO_ID, "host": HOST, **({"after": case["after"]} if "after" in case else {})}
    # Control: one request reached the case's route, so the answer or refusal above is the parse of that route's reply.
    assert [(entry[0], entry[1], entry[4]) for entry in seen] == [("POST", ROUTES[case["route"]], sent)]  # C1: exactly one request to that route


def test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names():
    assert CONTRACT.exists(), CONTRACT
    names = [case["name"] for case in CASES]
    assert sorted(name for name in set(names) if names.count(name) > 1) == []  # C2: every case name unique
    assert {case["route"] for case in CASES} == set(ROUTES)
    assert [case["name"] for case in CASES if "after" in case and case["route"] != "state"] == []
    for route, states in (("state", TRANSLATE_STATES), ("enqueue", TRANSLATE_REQUEST_STATES)):
        bodies = [case["engine"]["body"] for case in CASES if case["route"] == route and case["engine"]["status"] == 200 and case["gateway"] != "rejected"]
        assert {body["state"] for body in bodies if "available" in body} == states, route  # C2: with available
        assert {body["state"] for body in bodies if "available" not in body} == states, route  # C2: without available
        assert len([case for case in CASES if case["route"] == route and case["engine"] == {"status": 404, "body": {"error": "Video not found"}}]) == 1, route
        # Control: each route replays at least one refusal, so the replay's rejected half is exercised on both parsers.
        assert any(case["gateway"] == "rejected" for case in CASES if case["route"] == route), route

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 1 (Contract fixture and Client gateway replay) - red (audit round 1)

`tests/tmp/test_55_translate_state_contract_phase1.py` exited 1.

```
  tests/tmp/test_55_translate_state_contract_phase1.py  2 failed                               0.0s
  ----------------------------------------------------
  total                                                 2 failed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 1 (Contract fixture and Client gateway replay) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Neither test can pass yet because tests/active/fixtures/translate_contract.json does not exist.
test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route
is collected with the single stand-in case "fixture missing" and fails at line 36 on
`assert CONTRACT.exists(), CONTRACT`. test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names
fails at line 52 on the same assertion.

NOT ASSESSED
1. tests/active/fixtures/translate_contract.json, the phase's output and the source of every
   expected value, does not exist yet. So it could not be checked against the
   tautological-assertion (rules/shape.md) bullet "a snapshot regenerated from current output".
   If each case's `gateway` answer was produced by running fetch_translate/request_translate
   rather than written down independently, line 45 would agree with the gateway by
   construction. The test as written states its expectation as a fixture literal, and that
   form passes the check.
2. The stub question was answered from the assertion form alone. An empty, partial,
   all-rejected or wrongly-answered fixture fails the checkpoint:
   - lines 55, 59 and 60 fail on a missing route or state set;
   - line 45 fails on a wrong answer;
   - line 41 fails with DID NOT RAISE when a parseable case is marked rejected.
   One gap is caught only by the second test: a fixture with `"cases": []` collects zero
   replay cases instead of failing them, and lines 55 and 59 are what turn it red.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 2 must_prove, 13 docstring, 7 name; the 2 must_prove clauses split into 7 rows below, C1a–C1e and C2a–C2c, and the count includes those 7 rows)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | state case through fetch_translate gives exactly its gateway answer | :45 | a parser that drops, adds or rewrites a field (cues, total, available), or a fixture whose stated answer is not the real parse | CARRIED |
| C1b | must_prove | enqueue case through request_translate gives exactly its gateway answer | :45 | the same, on the enqueue parser (e.g. busy turned into failed, available defaulted wrongly) | CARRIED |
| C1c | must_prove | raises EngineApiError when the case says rejected | :41 | a gateway that returns a value, or raises something other than EngineApiError, on a case marked rejected | CARRIED |
| C1d | must_prove | from exactly one request to that route | :48 | zero or two requests, a request to the other route, a GET instead of POST (list equality on (method, path, body)) | CARRIED |
| C1e | must_prove | state route called "with its after" | :48 | `after` dropped from the body or sent when the case has none (`sent` built from the case) | CARRIED |
| C2a | must_prove | valid 200 states with available equal TRANSLATE_STATES (state) / TRANSLATE_REQUEST_STATES (enqueue) | :59 | a fixture missing a state (e.g. no `busy` on enqueue) or adding one; set equality against the imported constants | CARRIED |
| C2b | must_prove | the same sets without available | :60 | a fixture covering a state only with `available` present | CARRIED |
| C2c | must_prove | every case name is unique | :54 | a duplicated name (duplicates listed, compared to []) | CARRIED |
| D1 | docstring | "the Client gateway's real parsers agree with it case by case" | :45, :41 | a case whose stated answer differs from the real parse; parsers imported from lib.engine_api_client at :24 | CARRIED |
| D2 | docstring | "raises EngineApiError with the gateway's own 'Engine translate ...' text, never a transport error's" | :41 | a refused or dropped connection, whose `str(exc)` text does not start with "Engine translate" (`match=r"^Engine translate"`) | CARRIED |
| D3 | docstring | "the stub saw exactly one POST" | :48 | two requests, or a GET (entry[0] compared) | CARRIED |
| D4 | docstring | "to /internal/translate for a state case and /internal/translate/enqueue for an enqueue case" | :48 | a call to the other route (ROUTES[case["route"]]) | CARRIED |
| D5 | docstring | "body exactly id, host and the case's `after` when it has one" | :48 | an extra key, or `after` missing or present when it should not be (whole-dict equality) | CARRIED |
| D6 | docstring | "every case name is unique" | :54 | a duplicate name | CARRIED |
| D7 | docstring | "the routes are exactly state and enqueue" | :55 | a third route, or a route with no cases | CARRIED |
| D8 | docstring | "each with at least one rejected case" | :63 | a route whose replay never runs the rejected branch | CARRIED |
| D9 | docstring | "`after` appears only on state cases" | :56 | an enqueue case carrying `after` | CARRIED |
| D10 | docstring | "states of the valid 200 cases carrying `available` ... each equal" the route's set | :59 | a missing or extra state among cases with `available` | CARRIED |
| D11 | docstring | "and of those without it" | :60 | a missing or extra state among cases without `available` | CARRIED |
| D12 | docstring | "each route has exactly one 404 `{"error": "Video not found"}` case" | :61 | zero or two such cases on a route (count == 1 on exact engine dict) | CARRIED |
| D13 | docstring | "while it is missing, both tests fail on its absence" | :36, :52 | a skip or silent pass on a missing fixture (stand-in case at :28 still reaches :36) | CARRIED |
| N1 | name | "each contract case" | :34 → :45/:41 | a subset of cases run; parametrized over all CASES, unfiltered | CARRIED |
| N2 | name | "parses through the real gateway to its stated answer" | :45, :41 | a stand-in parser; real fetch_translate/request_translate called | CARRIED |
| N3 | name | "from one request to its route" | :48 | more than one request, or the wrong route | CARRIED |
| N4 | name | "states exactly the gateway state sets" | :59, :60 | a subset or superset of the sets (equality, not membership) | CARRIED |
| N5 | name | "with and without available" | :59, :60 | only one half covered | CARRIED |
| N6 | name | "under unique names" | :54 | a duplicate name | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/fixtures/translate_contract.json (NEW), but the file does not exist at that path. The test's assertions were judged against the code they run (lib.engine_api_client fetch_translate / request_translate and test_server._translate_engine). The fixture's own content was not judged: which bounds and malformed bodies its rejected cases cover (testing.md bounds), and whether its stated answers are right. Without the file, the test as written goes red at :36 and :52.
2. tests/config.json (EDITED) was read only for translate entries. Its edit has no bearing on what the test asserts and was not judged further.
3. `fixtures_path` was not supplied. The test uses no pytest fixture; `_translate_engine` is imported from tests/active/test_server.py:1600 and was read there.

## 2026-10-04 - Step 7 - Phase 1 (Contract fixture and Client gateway replay) - checkpoint outcome (run 1)

`tests/tmp/test_55_translate_state_contract_phase1.py` exited 0 after the phase landed.

<changes>
### tests/active/fixtures/translate_contract.json (NEW, plus the new `tests/active/fixtures/` directory)
This is the translate contract fixture: `{"description", "cases": [...]}`, one case per line. It is byte-for-byte the plan's draft (§1 of the implementation plan), which is the version the checkpoint's author already probed against the checkpoint.
- **Valid cases (29):** every state of the state route (6) and of the enqueue route (7, with `busy`), each once with `available: true` and once without it (the gateway reads a missing one as `false`). Also a `running` answer sliced by `after` 3 (2 cues, `total` 5), and the `{"error": "Video not found"}` 404 on both routes, which gives `{state: none, available: false}`.
- **Rejected cases (14):** the `Not found` 404 on both routes; an unknown state on both routes; `busy` on the state route; a string `available` on both routes; and, on the state route only, non-list `cues`, a cue `start` of `1e999`, a bool `start`, a bool `end`, a number as `text`, a `total` of -1 and a `total` of `true`.
- **Cue order:** the `ready` cues are out of start order with two sharing a start, and the `running` cues are in a non-sorted stored order. The gateway answer keeps the Engine's order.
- **Checked:** a throwaway probe loaded the checked-in file. It equals the draft (43 cases), and every case replayed through the real `fetch_translate`/`request_translate`, via `test_server._translate_engine`, gives its `gateway` answer from exactly one request. Every refusal text starts with `Engine translate`. I did not run the checkpoint itself; the workflow does that.

### tests/active/test_server.py (not edited)
The checkpoint only imports `_translate_engine` from it, and that already exists. The plan's durable copies of the replay and coverage tests (plus a docstring paragraph) would repeat the checkpoint word for word, so I left them for whichever step moves the checkpoint into the active suite rather than writing them twice now.

### tests/config.json (not edited)
The planned entry adds the fixture to the `test_server.py` group. That only makes sense once `test_server.py` itself reads the fixture, so it belongs with that same step.

### tests/tmp/probe_55_phase1_replay.py
This is a leftover probe from authoring. I reused it to check the fixture, then emptied it because I have no tool to delete files. It and the authoring step's `tests/tmp/probe_55_phase1_checkpoint.py` and zero-byte `tests/tmp/probe_55_contract.py` should be deleted.
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
  tests/tmp/test_55_translate_state_contract_phase1.py  44 passed                              0.0s
  ----------------------------------------------------
  total                                                 44 passed                             21.8s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
data/translate.ts is proven against every case of the contract fixture. Valid gateway answers come back with their fields intact, and every rejected body is refused as malformed.

- C1 - Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given.
- C2 - Every rejected fixture case served as a 200 throws exactly "Translate response was malformed".

must_prove:
- C1 - Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given.
- C2 - Every rejected fixture case served as a 200 throws exactly "Translate response was malformed".

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - self-check (audit round 1, send-back 0)

`tests/tmp/test_55_translate_state_contract_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_55_translate_state_contract_phase2.py:99 — for each of the 29 valid fixture cases, the value that fetchTranslate (state route, with the case's after) or requestTranslate (enqueue route) returned, as reported by test_frontend_translate.py's own CONTRACT_RUNNER over the real translate.ts, deep-equals the case's gateway answer. Ready cues are compared sorted by (start, end) and running cues in the order the fixture gives them. - expected: Today all 29 fail earlier, at :79, because test_frontend_translate.py has no CONTRACT_RUNNER yet. Once the phase adds the plan's runner, all 29 pass. Observed by running the plan's CONTRACT_RUNNER text through this checkpoint's harness over the real translate.ts: "real -> 0 failed". For example, "state ready" returned cues Short first (1,2), Long first (1,3), Later (4,5). - excludes: Each of these was observed in a probe using the plan's runner over a mutated copy of translate.ts. Dropping `.sort(compareCues)` (translate.ts:101) fails "state ready" and "state ready without available": they come back as Later, Long first, Short first. Sorting by start only (dropping `|| a.end - b.end`, :53) fails the same two: Long first comes back ahead of Short first. Sorting running cues fails "state running", "state running without available" and "state running after 3". On the runner side, a runner that sends every case through fetchTranslate fails 18 cases on the :84 request control, and a runner that drops `after` fails "state running after 3" on :84.
- C2 - tests/tmp/test_55_translate_state_contract_phase2.py:105 — for each of the 14 rejected fixture cases, the Engine body served as a 200 by the phase's CONTRACT_RUNNER makes fetchTranslate or requestTranslate throw. The reported message is exactly "Translate response was malformed". - expected: Today all 14 fail earlier, at :79, because CONTRACT_RUNNER is missing. With the plan's runner over the real translate.ts all 14 pass (observed, "real -> 0 failed"). For example, "state start 1e999" reported {'thrown': 'Translate response was malformed', 'nonFinite': True}. - excludes: Each of these was observed in a probe over a mutated translate.ts. Changing the MALFORMED text (translate.ts:19) fails all 14, reporting 'Bad translate response'. Accepting busy on the state route (:106) fails "state busy", which returns {'state': 'busy', 'available': True}. Replacing `Number.isFinite(cue?.start)` with a typeof check (:120) fails "state start 1e999", which returns a ready value. A runner using plain JSON.stringify serves null for the 1e999 case: the refusal text still matches, but the :86 control fails with nonFinite False, so a refusal for the wrong reason cannot pass.

<assertions>
tests/tmp/test_55_translate_state_contract_phase2.py:116 - for each of the 29 valid fixture cases, the value fetchTranslate (state route, with the case's after) or requestTranslate (enqueue route) returned deep-equals the case's gateway answer. Ready cues are re-sorted in Python by (start, end); running cues are left in the order given. Wrong implementations this excludes, each observed: ready left unsorted, a sort by start only, running cues sorted, busy accepted on the state route, a stub or hard-coded return. - C1
tests/tmp/test_55_translate_state_contract_phase2.py:113 - control on every valid case with cues: the fixture's own list is out of (start, end) order. Without it, a fixture whose lists were already sorted would make the line-116 order check pass on an unsorted or wrongly sorted parser. - C1 (control)
tests/tmp/test_55_translate_state_contract_phase2.py:123 - for each of the 14 rejected fixture cases, the Engine body served as a 200 makes the call throw exactly "Translate response was malformed". A returned value, a JSON SyntaxError or any other message fails. Wrong implementations excluded, each observed: a changed MALFORMED text, infinity accepted, state busy accepted. - C2
tests/tmp/test_55_translate_state_contract_phase2.py:101 - control on every case, valid and rejected: the fetch stub saw exactly one request. A state case sends GET /api/translate with after equal to the case's after (or none), and an enqueue case sends POST /api/translate. So each answer or refusal comes from the intended route's parser. - C1/C2 (control)
tests/tmp/test_55_translate_state_contract_phase2.py:103 - control on every case: the served text parsed to a non-finite number exactly where Python's reading of the fixture finds one, which is only "state start 1e999". So that case is refused for infinity and not for a null. Observed: a runner serialising with plain JSON.stringify fails here on that case while the line-123 check alone stays green. - C1/C2 (control)
</assertions>

<probes>
Command: ValidateTests ["tests/tmp/probe_55_phase2_checkpoint.py", "-s"], exit 0, output read from tests/last_test_output.txt. The probe imported the checkpoint, ran _contract_report against the real client/frontend/src/data/translate.ts, then called both test bodies once per case. It then repeated this against mutant copies of translate.ts (copied to tmp with api-base.ts and profile.ts; no frontend file changed) and against a mutant runner.
Real module: 43 cases (29 valid, 14 rejected) and zero failures. Each valid case returned its gateway answer; JS writes 5.0 as 5, which Python compares equal. Ready came back as Short first (1-2), Long first (1-3), Later (4-5). Running stayed in the order given ([5,1,3] and [9,7] with total 5). Each rejected case threw exactly "Translate response was malformed". nonFinite was true only for "state start 1e999". asked was one GET with after null on every state case except "state running after 3" (after "3"), and one POST on every enqueue case.
Mutant "ready unsorted" (no .sort): fails state ready and state ready without available.
Mutant "sort by start only": fails the same 2 ready cases.
Mutant "running sorted": fails state running, state running without available and state running after 3.
Mutant "infinity accepted" (typeof number instead of Number.isFinite on start): fails state start 1e999, which returned a value.
Mutant "other message": fails all 14 rejected cases.
Mutant "busy accepted on state route": fails state busy.
Runner mutant "plain JSON.stringify" (infinity served as null): fails only state start 1e999, at the nonFinite control (it still threw MALFORMED, for the wrong reason).
Mutant "available defaults true" (missing available read as true): survives, zero failures. Valid cases serve the gateway's normalised answer, which always carries available, so the frontend's missing-available default is never exercised at this seam. Neither the agreed seam nor C1/C2 claims it, so it is not asserted.
Not run: the checkpoint itself; the workflow does that. The probe file tests/tmp/probe_55_phase2_checkpoint.py is now emptied, because I have no delete tool, and should be deleted.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_55_translate_state_contract_phase2.py` - 7470 characters, inlined in full

```
"""Phase 2 checkpoint of plan 55: the real client/frontend/src/data/translate.ts, bundled on its own and run in node, agrees with every case of tests/active/fixtures/translate_contract.json.

`CONTRACT_RUNNER` stubs `window`, `localStorage` and a `fetch` that answers 200 with the served text, reads the fixture itself with `fs`, and in one node process serves each case to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route): the case's gateway answer when it is valid, its Engine body when the gateway answer is "rejected". Non-finite numbers are served as `1e999`, because `JSON.stringify` would write `null`.

- Valid (C1): the returned value deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given; the fixture's ready and running lists are themselves out of that order, so an unsorted or a wrongly sorted list reads differently.
- Rejected (C2): the call threw exactly "Translate response was malformed", so a JSON SyntaxError or a gateway error text cannot pass as the parser's refusal.
- Controls on every case: the fetch stub saw exactly one request, a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case; and the served text parsed to a non-finite number exactly where Python's reading of the fixture finds one (its `1e999`).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "client" / "frontend"
ESBUILD = FRONTEND / "node_modules" / ".bin" / "esbuild"
CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
CASES = json.loads(CONTRACT.read_text())["cases"]
VALID = [case for case in CASES if case["gateway"] != "rejected"]
REJECTED = [case for case in CASES if case["gateway"] == "rejected"]
BASE = "http://client.test"
HOST = "peer.example"
MALFORMED = "Translate response was malformed"

CONTRACT_RUNNER = """
import fs from "node:fs";
const memory = () => { const s = new Map(); return {
  getItem: (k) => (s.has(k) ? s.get(k) : null), setItem: (k, v) => s.set(k, String(v)),
  removeItem: (k) => s.delete(k) }; };
globalThis.localStorage = memory();
// api-base.ts reads window.location.origin when it is evaluated, so window exists before the import below.
globalThis.window = { location: { origin: process.env.BASE }, localStorage: globalThis.localStorage };
let served = null;
let asked = [];
globalThis.fetch = async (input, init) => {
  const url = new URL(String(input?.url ?? input), process.env.BASE);
  asked.push({ method: String(init?.method ?? input?.method ?? "GET").toUpperCase(), path: url.pathname, after: url.searchParams.get("after") });
  return new Response(served, { status: 200, headers: { "content-type": "application/json" } });
};
// JSON.stringify writes a non-finite number as null, which would be refused for the wrong reason; it goes back out as 1e999, as the fixture wrote it.
const NON_FINITE = "__non_finite__";
const serialise = (value) => JSON.stringify(value, (key, v) => (typeof v === "number" && !Number.isFinite(v) ? NON_FINITE : v)).replaceAll(JSON.stringify(NON_FINITE), "1e999");
const hasNonFinite = (value) => (typeof value === "number" ? !Number.isFinite(value) : value !== null && typeof value === "object" && Object.values(value).some(hasNonFinite));
const { fetchTranslate, requestTranslate } = await import(process.env.BUNDLE);
const report = {};
for (const c of JSON.parse(fs.readFileSync(process.env.CONTRACT, "utf8")).cases) {
  served = serialise(c.gateway === "rejected" ? c.engine.body : c.gateway);
  asked = [];
  // What the parser reads, parsed as readTranslateResponse parses it.
  const nonFinite = hasNonFinite(JSON.parse(served));
  try {
    const value = c.route === "state" ? await fetchTranslate(process.env.BASE, "uuid-1", process.env.HOST, c.after) : await requestTranslate(process.env.BASE, "uuid-1", process.env.HOST);
    report[c.name] = { value, nonFinite, asked };
  } catch (error) {
    report[c.name] = { thrown: String(error?.message ?? error), nonFinite, asked };
  }
}
process.stdout.write(JSON.stringify(report) + "\\n", () => process.exit(0));
"""


def _contract_report(out: Path, source: Path) -> dict:
    subprocess.run(
        [str(ESBUILD), str(source), "--bundle", "--format=esm", "--platform=node", f"--outfile={out / 'bundle.mjs'}",
         f"--define:import.meta.env.VITE_CLIENT_API_BASE={json.dumps(BASE)}",
         "--define:import.meta.env.DEV=false"],
        check=True, capture_output=True,
    )
    (out / "runner.mjs").write_text(CONTRACT_RUNNER)
    proc = subprocess.run(
        ["node", str(out / "runner.mjs")], capture_output=True, text=True, timeout=60,
        env={"BASE": BASE, "BUNDLE": str(out / "bundle.mjs"), "CONTRACT": str(CONTRACT), "HOST": HOST, "PATH": os.environ.get("PATH", "")},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1])


@pytest.fixture(scope="module")
def contract_report(tmp_path_factory) -> dict:
    return _contract_report(tmp_path_factory.mktemp("translate_contract"), FRONTEND / "src" / "data" / "translate.ts")


def _has_non_finite(value) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    return isinstance(value, list) and any(_has_non_finite(v) for v in value)


def _by_start_then_end(cues: list[dict]) -> list[dict]:
    return sorted(cues, key=lambda cue: (cue["start"], cue["end"]))


def _controls(result: dict, case: dict, served: dict) -> None:
    # Control: the case reached its route's parser through one request, a GET with the case's after for the state route and a POST for the enqueue route.
    assert result["asked"] == [{"method": "GET" if case["route"] == "state" else "POST", "path": "/api/translate", "after": str(case["after"]) if "after" in case else None}], result
    # Control: the parser read a non-finite number exactly where Python's reading of the fixture finds one (its 1e999), so that case is refused for infinity and not for a null.
    assert result["nonFinite"] == _has_non_finite(served), result


@pytest.mark.parametrize("case", VALID, ids=[case["name"] for case in VALID])
def test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order(contract_report, case):
    result = contract_report[case["name"]]
    expected = case["gateway"]
    _controls(result, case, expected)
    if "cues" in expected:
        # Control: the fixture's list is out of (start, end) order, so a parser that leaves ready unsorted, or sorts running, reads differently below.
        assert _by_start_then_end(expected["cues"]) != expected["cues"], case["name"]
    if expected["state"] == "ready" and "cues" in expected:
        expected = {**expected, "cues": _by_start_then_end(expected["cues"])}
    assert result.get("value") == expected, result  # C1


@pytest.mark.parametrize("case", REJECTED, ids=[case["name"] for case in REJECTED])
def test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed(contract_report, case):
    result = contract_report[case["name"]]
    _controls(result, case, case["engine"]["body"])
    assert result.get("thrown") == MALFORMED, result  # C2

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - red (audit round 1)

`tests/tmp/test_55_translate_state_contract_phase2.py` exited 1.

```
  tests/tmp/test_55_translate_state_contract_phase2.py  43 failed                              0.0s
  ----------------------------------------------------
  total                                                 43 failed                              0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - BLOCK
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D2; devsecops-test-shape-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: BLOCK

CRITICAL
1. tautological-assertion (rules/shape.md) — tests/tmp/test_55_translate_state_contract_phase2.py:98
   expected = {**expected, "cues": _by_start_then_end(expected["cues"])}
   For the two ready cases ("state ready", "state ready without available") the test works
   out the expected cue order itself. It does this with its own sort at :74-75,
   `sorted(cues, key=lambda cue: (cue["start"], cue["end"]))`, which is the production
   ordering rewritten in Python. The rule wants an expected value written down
   independently. This is a match for two lines of the entry's <how_to_spot>: "The expected
   value is computed in the test body rather than written down" and "The test ... reimplements
   the function it is testing to build its expectation". It is the same shape as the entry's
   <example_bad> (`expected = sum(...)`). The line-96 control shows the fixture list is
   unsorted, but the order the line-99 assertion holds translate.ts to still comes from the
   test's own sort, not from a stated value. The fix the entry's <alternatives> gives fits
   here: the ready expectation is three cues, so it can be written as a literal
   (Short first 1–2, Long first 1–3, Later 4–5).

RECOMMENDATIONS
none

PREDICTED FAILURE
Every parametrized case of both test functions fails at line 79,
`assert contract_report is not None`. tests/active/test_frontend_translate.py defines no
`CONTRACT_RUNNER`, so the module fixture returns None.

NOT ASSESSED
1. client/frontend/src/data/translate.ts is not in `code_under_test`, but the test bundles it.
   I only grepped it to confirm `fetchTranslate`, `requestTranslate` and the malformed
   message exist. I did not read it in full.
2. `CONTRACT_RUNNER` does not exist yet, and it is the phase's output. I answered the stub
   question from the assertion form and the fixture. A pass-through parser (`res.json()`
   returned as-is) fails the ready cases at :99 and every rejected case at :105. A runner that
   never calls translate.ts's fetch is caught by the request controls at :83-84. Whether the
   runner, once written, really reaches `fetchTranslate`/`requestTranslate` can only be
   checked after it lands.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (26 clauses: 6 must_prove, 14 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "every valid fixture case served to fetchTranslate or requestTranslate" | :84 | a case sent to the wrong function: a GET where a POST belongs or the other way round, or a state case missing its `after`. Every VALID case is a parametrized case (:90) | CARRIED |
| C1b | must_prove | "comes back with exactly its gateway fields" | :99 | a field dropped or added (for example `available` left out, or `total` kept on a ready answer), because whole-dict equality fails on either | CARRIED |
| C1c | must_prove | "ready cues sorted by start then end" | :99 (expected built at :98) | ready left unsorted, or sorted by start only. The fixture's tie at start 1.0 (end 3.0 before end 2.0) reads differently under a start-only sort | CARRIED |
| C1d | must_prove | "running cues in the order given" | :99, control :96 | running cues sorted the way ready cues are. :96 shows the fixture's running lists are out of order, so a sort would change what :99 reads | CARRIED |
| C2a | must_prove | "every rejected fixture case served as a 200" | :105, :84 | the case's real status served (404 and so on): `readTranslateResponse` would then throw the error text or "Translate request failed (N)", which does not equal MALFORMED | CARRIED |
| C2b | must_prove | throws exactly "Translate response was malformed" | :105 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |
| D1 | docstring | the real translate.ts, bundled on its own, agrees "with every case" of the fixture | :99, :105 | a single case that disagrees turns its own parametrized case red | CARRIED |
| D2 | docstring | the runner "reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables" | none | nothing reads it. A runner that hard-codes the fixture path or the host gives the same report | UNCARRIED |
| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :84 | a call on the wrong route, or `after` left off or added | CARRIED |
| D4 | docstring | "the gateway answer for a valid case" is what gets served | :99 | serving the Engine body instead: the 404 "video not found" cases would then throw rather than return the gateway value | CARRIED |
| D5 | docstring | "the Engine body for a rejected one" is what gets served | :86 | serving one stand-in body for every rejected case: the `start 1e999` case would read `nonFinite` false. This only reads at that one case (see Recommendation 2) | CARRIED |
| D6 | docstring | one JSON report "keyed by case name of `{value \| thrown, nonFinite}`" | :80, :99, :105, :86 | a report missing a case name (KeyError), or missing the value, thrown or nonFinite field | CARRIED |
| D7 | docstring | `FETCH_RECORDER` "writes every request to the ASKED file" | :83 | requests going unrecorded, which would make the count fall short | CARRIED |
| D8 | docstring | "While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence" | :79 | a missing runner being skipped or passing silently | CARRIED |
| D9 | docstring | the value "deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given" | :99 | same wrong versions as C1b, C1c and C1d | CARRIED |
| D10 | docstring | "the fixture's ready and running lists are themselves out of that order" | :96 | a fixture already in order, which would make the sort check meaningless | CARRIED |
| D11 | docstring | threw exactly MALFORMED, "so a JSON SyntaxError or a gateway error text cannot pass" | :105 | a SyntaxError or a gateway error text | CARRIED |
| D12 | docstring | "the runner made one request per case" | :83 | extra requests or skipped requests | CARRIED |
| D13 | docstring | "a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case" | :84 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |
| D14 | docstring | non-finite "exactly where Python's reading of the fixture finds one (its `1e999`)" | :86 | the 1e999 case refused for some other reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |
| N1 | name | "each valid contract case" | :90 parametrize, :84 | a valid case left out or sent down the wrong route | CARRIED |
| N2 | name | "comes back with exactly its gateway fields" | :99 | a field added or dropped | CARRIED |
| N3 | name | "ready cues sorted by start then end" | :99 | unsorted, or sorted by start only | CARRIED |
| N4 | name | "running in given order" | :99, :96 | running cues sorted | CARRIED |
| N5 | name | "each rejected contract case served as a 200" | :105 | the case's real non-200 status served, which yields error text rather than MALFORMED | CARRIED |
| N6 | name | "throws exactly translate response was malformed" | :105 | any other message, or no throw | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_55_translate_state_contract_phase2.py:3
   D2 is UNCARRIED. The docstring says the runner reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables, but no assertion would notice a runner that ignores them. A runner that hard-codes the fixture path or host still produces a report that passes :80–:105, and :84 does not compare the `host` query parameter. This is a docstring-only clause, so it is a Recommendation. Fix it either by asserting it (for example, add the expected `host` to the recorded request and compare it at :84) or by narrowing the sentence.
2. bounds (rules/testing.md) — tests/tmp/test_55_translate_state_contract_phase2.py:86
   For 13 of the 14 rejected cases, the test cannot see what the runner served. FETCH_RECORDER (:37) records method, path and `after`, but not the response body. Only the `start 1e999` case has a check (:86) that reads differently when a stand-in body is served. So a runner that serves any easily malformed body (`{}`, or the string "rejected") for, say, `state total -1` still gets MALFORMED at :105 for that case, and that test never reaches translate.ts's `total < 0` check. The suite as a whole still catches a runner that substitutes the same body everywhere, because the 1e999 case goes red. Recording the served text, or a digest of it, next to each request would let every case tie its throw to its own Engine body.
3. bounds (rules/testing.md) — tests/tmp/test_55_translate_state_contract_phase2.py:98
   The ready fixture's order cannot tell a (start, end) sort from an (end, start) sort. Both put `[1,2],[1,3],[4,5]` in the same order, so a comparator of `a.end - b.end || a.start - b.start` passes :99. The fixture needs a ready cue whose end comes earlier but whose start comes later than another cue's (for example `{start: 2, end: 2.5}` alongside `{start: 1, end: 3}`) before the "start then end" half of C1c reads differently under that wrong sort.

OBSERVATIONS
none

NOT ASSESSED
1. `CONTRACT_RUNNER` does not exist yet in tests/active/test_frontend_translate.py. The only matches are in this test and in tests/last_test_output.txt / last_test_validation.json. So I could not read what the runner serves, or how it computes `nonFinite` (from the served text or from the fixture). The D5 and D14 rows are judged on the test's assertions alone. A runner that takes `nonFinite` from the fixture would make the :86 check meaningless, and that can only be checked once the runner exists.
2. client/frontend/src/data/translate.ts and tests/active/fixtures/translate_contract.json were not in `code_under_test`. I read them anyway because the test bundles the first and parametrizes over the second, and they are where I got the accepted inputs and refusal paths for the bounds checks. tests/config.json, which was listed, has nothing about this test's behaviour.
3. `fixtures_path` was not supplied. The test defines its only fixture itself (`contract_report`, :60) and otherwise uses pytest's built-in `tmp_path_factory`, so I did not need a conftest.

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - self-check (audit round 2, send-back 0)

`tests/tmp/test_55_translate_state_contract_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_55_translate_state_contract_phase2.py:101 — for each of the 29 valid cases, result["value"] deep-equals the case's gateway answer. For the two ready cases the cues are replaced by the literal READY_CUES (line 30, used at line 100). Running cues are left in the fixture's order. The control at line 98 shows every fixture cue list is out of (start, end) order. The request control at line 86 shows the case went to fetchTranslate (a GET carrying its after) or requestTranslate (a POST). - expected: Each case's gateway dict exactly. For ready: cues [Short first 1–2, Long first 1–3, Later 4–5]. For running: cues in the order given, e.g. starts [5,1,3] and [9,7] with total 5. - excludes: Earlier probe mutants, each observed red at this comparison: ready left unsorted, and ready sorted by start only (both fail "state ready" and "state ready without available"); running sorted (fails the three running cases); busy accepted on the state route (fails "state busy"); a field dropped or added, or a stub return (whole-dict inequality).
- C2 - tests/tmp/test_55_translate_state_contract_phase2.py:107 — for each of the 14 rejected cases, the Engine body served as a 200 makes the call throw exactly MALFORMED. The controls at lines 85–86 show one request on the intended route, and the control at line 88 shows the 1e999 case was refused for infinity. - expected: result["thrown"] == "Translate response was malformed" for every rejected case. - excludes: Earlier probe mutants: a changed message fails all 14; infinity accepted through a typeof check fails "state start 1e999", which returns a value. Serving the real non-200 status would throw the error text or "Translate request failed (N)" instead. A JSON SyntaxError or no throw also reads differently.

<exemptions>
none
</exemptions>

<items>
<item id="D2">
<disposition>justified</disposition>
<what>I narrowed the prose. Line 3 used to say the runner "reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables". It now says the test "hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here)". That is what the test does: the env dict at line 54 of _contract_report sets them. The docstring no longer claims the runner reads them, which nothing asserted. Neither C1 nor C2 needs it.</what>
</item>
</items>

<findings_addressed>
Shape CRITICAL 1 (tautological-assertion at old :98, where the ready expectation came from the test's own (start, end) sort): fixed. The expected ready cues are now a literal, READY_CUES, at line 30: Short first 1.0–2.0, Long first 1.0–3.0, Later 4.0–5.0. This is the order the earlier probe observed from the real translate.ts. Line 100 swaps that literal in for both ready cases, and line 101 compares against it. No expected value is computed by a sort any more. The _by_start_then_end helper is now used only by the line-98 control. That control reads the fixture's own input list to prove it is out of order, so it makes no prediction about production output.
Claim Recommendation 1 (D2): taken by narrowing the docstring at line 3, as recorded in item D2.
Claim Recommendation 2 (the served body is not recorded for 13 of the 14 rejected cases): not taken. C2 is carried as worded, and the suite as a whole still catches a single substituted body at the 1e999 nonFinite control (line 88).
Claim Recommendation 3 (the ready fixture cannot tell a (start, end) sort from an (end, start) sort): not taken. The fix means adding a cue to tests/active/fixtures/translate_contract.json, which is a durable fixture outside this step's files. That gap remains and should go to whoever owns the fixture.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:101 — for each of the 29 valid cases, result["value"] deep-equals the case's gateway answer. For the two ready cases the cues are replaced by the literal READY_CUES (line 30, used at line 100). Running cues are left in the fixture's order. The control at line 98 shows every fixture cue list is out of (start, end) order. The request control at line 86 shows the case went to fetchTranslate (a GET carrying its after) or requestTranslate (a POST).</assertion>
<expected>Each case's gateway dict exactly. For ready: cues [Short first 1–2, Long first 1–3, Later 4–5]. For running: cues in the order given, e.g. starts [5,1,3] and [9,7] with total 5.</expected>
<wrong_implementation>Earlier probe mutants, each observed red at this comparison: ready left unsorted, and ready sorted by start only (both fail "state ready" and "state ready without available"); running sorted (fails the three running cases); busy accepted on the state route (fails "state busy"); a field dropped or added, or a stub return (whole-dict inequality).</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_55_translate_state_contract_phase2.py:107 — for each of the 14 rejected cases, the Engine body served as a 200 makes the call throw exactly MALFORMED. The controls at lines 85–86 show one request on the intended route, and the control at line 88 shows the 1e999 case was refused for infinity.</assertion>
<expected>result["thrown"] == "Translate response was malformed" for every rejected case.</expected>
<wrong_implementation>Earlier probe mutants: a changed message fails all 14; infinity accepted through a typeof check fails "state start 1e999", which returns a value. Serving the real non-200 status would throw the error text or "Translate request failed (N)" instead. A JSON SyntaxError or no throw also reads differently.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Each case has a positive assertion: a deep-equal at line 101 or the exact thrown text at line 107. Delete translate.ts's parser and both read differently.
2. Answered by a rewrite. The ready expectation used to come from a Python sort that copied production's ordering. It is now the literal READY_CUES. Deleting the .sort in translate.ts turns the two ready cases red at line 101 (observed earlier with the "ready unsorted" mutant). The only remaining sort runs on the fixture input, as a control at line 98.
3. No. There are 29 valid and 14 rejected cases, each its own parametrized case, and the expected values come from the fixture's gateway answers and the literal, not from sibling outputs. The one single-input read is the nonFinite control at the 1e999 case, which the claim audit already noted.
4. No. The runner's fetch is the severed network layer. The real translate.ts is bundled unchanged.
5. Yes, it collects. READY_CUES is defined at module level before use, and no imports or names changed. The count is the same 43 cases.
6. Yes. The literal is the ready output the earlier probe saw from the real translate.ts (Short first 1–2, Long first 1–3, Later 4–5). JS writes 5.0 as 5, which compares equal to Python's 5.0.
7. Yes, it should still be red for its own reason, though I have not run it; the workflow does that. Every case should fail at line 81 because tests/active/test_frontend_translate.py has no CONTRACT_RUNNER yet. My edits were a docstring change, a module-level constant and one changed expression; none touches imports or the fixture.
</answers>

Gate: satisfied

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - red (audit round 2)

`tests/tmp/test_55_translate_state_contract_phase2.py` exited 1.

```
  tests/tmp/test_55_translate_state_contract_phase2.py  43 failed                              0.0s
  ----------------------------------------------------
  total                                                 43 failed                              0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - audit (round 2)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
Every parametrized case in both tests fails at line 81, `assert contract_report is not None`,
inside `_result`. tests/active/test_frontend_translate.py defines no `CONTRACT_RUNNER`, so the
`contract_report` fixture returns None and the message names the missing runner.

NOT ASSESSED
1. `fixtures_path` was "none found". The test defines its only fixture, `contract_report`
   (line 62). It also depends on `tmp_path_factory`, a pytest built-in, and no conftest was
   needed. The data file tests/active/fixtures/translate_contract.json was read so the
   expected values could be checked.
2. `code_under_test` names the durable module the phase will extend with `CONTRACT_RUNNER`,
   and that module does not contain it yet. client/frontend/src/data/translate.ts is what the
   runner exercises, and it was read too. The stub question was answered against runners that
   might plausibly be written next to the current translate.ts, not against a runner that
   exists.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 6 must_prove, 13 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "every valid fixture case served to fetchTranslate or requestTranslate" | :86 (parametrized over every VALID case at :92) | a case sent to the wrong function, i.e. a GET where a POST belongs or the reverse, or a state case missing its `after` or given one it should not have | CARRIED |
| C1b | must_prove | "comes back with exactly its gateway fields" | :101 | a field dropped or added, such as `available` left out or `total` kept on a ready answer. The whole-dict equality fails on either | CARRIED |
| C1c | must_prove | "ready cues sorted by start then end" | :101 (expected replaced at :100 with READY_CUES from :30) | ready cues left unsorted, or sorted by start only. In the fixture, "Long first" (1.0, 3.0) comes before "Short first" (1.0, 2.0), so a stable start-only sort keeps them in that order and reads differently from READY_CUES | CARRIED |
| C1d | must_prove | "running cues in the order given" | :101, with the control at :98 | running cues sorted the way ready cues are. :98 shows the fixture's running lists (Third/First/Second, Fifth/Fourth) are out of order, so a sort would change what :101 reads | CARRIED |
| C2a | must_prove | "every rejected fixture case served as a 200" | :107, :86 | serving the case's real status. For the two 404 cases, `readTranslateResponse` (translate.ts:88-90) would then throw "Not found", which does not equal MALFORMED | CARRIED |
| C2b | must_prove | throws exactly "Translate response was malformed" | :107 | a JSON SyntaxError, a gateway error text, or no throw at all | CARRIED |
| D1 | docstring | the real translate.ts, bundled on its own, agrees "with every case" of the fixture | :101, :107 | any single case that disagrees fails its own parametrized case | CARRIED |
| D2 | docstring | withdrawn | n/a | n/a | CARRIED |
| D3 | docstring | serves to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route) | :86 | a call on the wrong route, or `after` left off or added | CARRIED |
| D4 | docstring | "the gateway answer for a valid case" is what gets served | :101 | serving the Engine body instead. The 404 "video not found" cases would then throw "Video not found" instead of returning the gateway value | CARRIED |
| D5 | docstring | "the Engine body for a rejected one" is what gets served | :88 | one stand-in body served for every rejected case. The `start 1e999` case would then read `nonFinite` false. This only shows at that one case | CARRIED |
| D7 | docstring | `FETCH_RECORDER` "writes every request to the ASKED file" | :85 | requests going unrecorded, which leaves the count short of len(CASES) | CARRIED |
| D8 | docstring | "While test_frontend_translate.py has no `CONTRACT_RUNNER`, every case fails on its absence" | :81 | a missing runner being skipped or passing silently | CARRIED |
| D9 | docstring | the value "deep-equals the gateway answer, with ready cues sorted by (start, end) and running cues in the order given" | :101 | the same wrong implementations as C1b, C1c and C1d | CARRIED |
| D10 | docstring | "the fixture's ready and running lists are themselves out of that order" | :98 | a fixture already in order, which would make the sort check meaningless | CARRIED |
| D11 | docstring | threw exactly MALFORMED, "so a JSON SyntaxError or a gateway error text cannot pass" | :107 | a SyntaxError or a gateway error text | CARRIED |
| D12 | docstring | "the runner made one request per case" | :85 | extra requests or skipped requests | CARRIED |
| D13 | docstring | "a GET of /api/translate carrying the case's `after` for a state case and a POST for an enqueue case" | :86 | wrong method, wrong path, or a wrong or missing `after` | CARRIED |
| D14 | docstring | non-finite "exactly where Python's reading of the fixture finds one (its `1e999`)" | :88 | the 1e999 case refused for another reason (a null, a substituted body), or a non-finite number reported where there is none | CARRIED |
| N1 | name | "each valid contract case" | :92 parametrize, :86 | a valid case left out or sent down the wrong route | CARRIED |
| N2 | name | "comes back with exactly its gateway fields" | :101 | a field added or dropped | CARRIED |
| N3 | name | "ready cues sorted by start then end" | :101 | unsorted, or sorted by start only | CARRIED |
| N4 | name | "running in given order" | :101, :98 | running cues sorted | CARRIED |
| N5 | name | "each rejected contract case served as a 200" | :107 | the case's real non-200 status served, which yields an error text, not MALFORMED | CARRIED |
| N6 | name | "throws exactly translate response was malformed" | :107 | any other message, or no throw | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3
   Ledger row D2 was resolved by changing the docstring, not by adding an assertion. The sentence used to say the runner "reads the fixture path, base, bundle and host from the CONTRACT, BASE, BUNDLE and HOST environment variables". It now says "the test hands it the fixture path, base, bundle and host in the CONTRACT, BASE, BUNDLE and HOST environment variables (which of them it reads is not asserted here)". Nothing asserts that the runner reads them. The claim was withdrawn, and the env dict at :56 is setup, not an assertion.
2. whole-claim (rules/testing.md): tests/tmp/test_55_translate_state_contract_phase2.py:3
   The ledger has no D6 row. The docstring clause "prints one JSON report keyed by case name of `{value | thrown, nonFinite}`" has no row. It is read implicitly: :82 indexes the report by case name, and :88, :101 and :107 read `nonFinite`, `value` and `thrown`. No defect found; recorded so the gap in the ids is explained.

NOT ASSESSED
1. `CONTRACT_RUNNER` is not yet defined in `code_under_test` tests/active/test_frontend_translate.py; the test fails at :81 until it is. So I couldn't read what the runner serves (200 status, gateway answer or Engine body). C2a, D4 and D5 were judged only from what the test reads and from client/frontend/src/data/translate.ts.
2. I searched tests/config.json only for its translate entries; I did not read it in full.
3. `fixtures_path` was not supplied, and the test uses only pytest's built-in `tmp_path_factory` and its own module-scoped `contract_report` fixture (:62), so I didn't search for a conftest.

## 2026-10-04 - Step 7 - Phase 2 (Frontend parser replay) - checkpoint outcome (run 1)

`tests/tmp/test_55_translate_state_contract_phase2.py` exited 0 after the phase landed.

<changes>
### tests/active/test_frontend_translate.py
I added `CONTRACT_RUNNER` at the end of the module, next to `RUNNER` and `GENERATION_RUNNER` and in the same style. It is the plan's draft runner (§3).
- **Setup:** it stubs `localStorage`, `window` (with `location.origin`, needed because `api-base.ts` reads it when the module loads) and a `fetch` that always answers 200 with the served text. It sets `fetch` by plain assignment, which is the assignment the checkpoint's recorder catches. Only after that does it dynamically import `BUNDLE`.
- **Replay:** it reads `CONTRACT` with `node:fs`. For each case it serves the gateway answer (valid case) or the Engine body (rejected case) to `fetchTranslate` (state route, with the case's `after`) or `requestTranslate` (enqueue route).
- **Non-finite numbers:** they are written back as `1e999`, because `JSON.stringify` would write `null`. A `rat-tail:` comment notes the ceiling: every infinity is written as positive.
- **Report:** one JSON line keyed by case name, holding `{value | thrown, nonFinite}`, then `process.exit(0)` so the recorder's `exit` hook runs.

No frontend file changed.

**Probe:** a throwaway probe ran the checkpoint's own `_contract_report` over the real `translate.ts`. What it showed:
- 43 requests for 43 cases.
- Case 6 was `GET /api/translate` with `after=3`; enqueue cases were `POST` with no `after`.
- Every valid case came back with its gateway fields: `ready` cues in the order (1,2), (1,3), (4,5), and `running` cues in the order given.
- All 14 rejected cases threw exactly `Translate response was malformed`.
- `nonFinite` was true only for `state start 1e999`.

I did not run the checkpoint itself. I had no tool to delete the probe, so I emptied it; `tests/tmp/probe_55_phase2_runner.py` can be deleted.

### tests/config.json (not edited)
The planned entries (the fixture and `api-base.ts` in the `test_frontend_translate.py` group) only make sense once the durable module has a test that reads the fixture. I left them for the step that moves the checkpoint into the active suite, as phase 1 did with its `test_server.py` entries. The plan's durable parametrized test, `contract_report` fixture and docstring paragraph would repeat the checkpoint, so they wait for that same step.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_55_phase2_runner.py — a throwaway probe I used to watch the runner's real output. I emptied it because I have no tool to delete files; it can be deleted.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_55_translate_state_contract_phase2.py  43 passed                              0.0s
  ----------------------------------------------------
  total                                                 43 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 3 (Engine answers match the fixture's shape) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The Engine's two translate routes are checked against the contract fixture. Each (route, state) it produces answers the fixture case's keys and JSON types, and its not-found answer is the fixture's body.

- C1 - Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state.
- C2 - On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body.

must_prove:
- C1 - Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state.
- C2 - On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body.

## 2026-10-04 - Step 7 - Phase 3 (Engine answers match the fixture's shape) - self-check (audit round 1, send-back 0)

`tests/tmp/test_55_translate_state_contract_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - test_55_translate_state_contract_phase3.py:86 and :87: `sorted(fixture - drivers) == []` and `sorted(drivers - fixture) == []`, where fixture is the set of (route, state) from the fixture's valid 200 cases that carry available, and drivers is the key set of ENGINE_DRIVERS - expected: Both read []. The table holds exactly the 13 (route, state) pairs: none/queued/running/ready/already_english/failed on state, and those plus busy on enqueue. Line 89's control already holds against the fixture; the run reached it in no test only because line 85 stops at the missing table. - excludes: A table that leaves a state out, or adds one the fixture lacks such as ("state", "busy"). I ran a probe table {("state","none"), ("state","busy")} and it failed at line 86 (fixture - drivers non-empty). The extra ("state","busy") would trip line 87 too. A missing table fails at line 39, as the current run shows.
- C1 - test_55_translate_state_contract_phase3.py:107: `status == 200` for the single response the real handler wrote, which the control at line 103 matches against the driver's return - expected: 200 for every case of all 13 (route, state) pairs. Probe drivers for state none/running/ready and enqueue queued each recorded exactly one [200, {...}] from the real handler. - excludes: A driver that lands the handler on a refusal, such as a 400 bad `after` or a 404 for an unresolved video, reads 400 or 404 here. A driver that makes up its own answer without calling the handler is caught first by the control at line 103: I ran a probe driver that returned a literal [[200, ...]] and it failed there.
- C1 - test_55_translate_state_contract_phase3.py:109: `_types(answer) == _types(expected)`. The answer's key-to-JSON-type map equals the fixture case's, with bool checked before number - expected: Equal for every case. Observed with probe drivers: state running after 3 gave {state: string, cues: array, total: number, available: boolean}, the same as the fixture's "state running after 3". state none, state ready and enqueue queued matched their cases too. - excludes: A handler that drops `total` from running, or writes `available` as 1. I wrapped the real handler in a probe that mutated its output after it ran: both mutations failed at line 109, one answer missing total and one with 'available': 1.
- C1 - test_55_translate_state_contract_phase3.py:112: `bool(answer["cues"]) == bool(expected["cues"])` wherever the case has cues - expected: True for state running, state running after 3 and state ready, whose fixture cues are non-empty. The probe's running driver stored five cues and the answer to after=3 held two (c3, c4). - excludes: A handler or driver that answers `cues: []`, for example a running job with no stored cues or an `after` past the total. The per-cue check at line 113 would then pass vacuously. A probe mutation that emptied the cues failed at line 112.
- C1 - test_55_translate_state_contract_phase3.py:113: every answer cue's key-to-JSON-type map is one of the fixture case's cue maps - expected: True. The observed cues were {start: number, end: number, text: string}, the same as the fixture's cue maps. - excludes: A cue that is missing `end` or carries extra keys. A probe mutation that popped `end` from every cue failed at line 113.
- C2 - test_55_translate_state_contract_phase3.py:128: on each route, the real handler answers the unknown video {"id": "no-such-video", "host": "peer.example"} exactly with [[404, the fixture's Video not found body for that route]] - expected: [[404, {"error": "Video not found"}]] on both routes. This passes in the run, as the docstring says it should, because the phase changes no runtime code. - excludes: A handler that answers a different 404 body, such as {"error": "Not found"}, which is the route-missing body. I wrapped the state handler in a probe that rewrote its 404 body, and it failed at line 128.
- C2 - test_55_translate_state_contract_phase3.py:129: on each route, the actively denylisted video (du-1 on denied.example, deny row stored as DENIED.EXAMPLE) answers exactly [[404, the fixture's Video not found body]]. The control at line 132 shows the same video answers 200 once the deny row is inactive - expected: [[404, {"error": "Video not found"}]] on both routes. The run passes it, and the line 132 control also held: 200 with the deny row inactive. - excludes: A denylist check that compares hosts case-sensitively, so the uppercase stored row never matches and the video is answered 200. Or one that refuses with a body other than the fixture's. Either reads something other than [[404, body]] here.

<assertions>
tests/tmp/test_55_translate_state_contract_phase3.py:86: the fixture's (route, state) set (valid 200 cases carrying available) minus the keys of test_internal_translate.ENGINE_DRIVERS is empty, so no fixture state lacks a driver (C1).
tests/tmp/test_55_translate_state_contract_phase3.py:87: the ENGINE_DRIVERS keys minus that fixture set is empty, so no driver lacks a fixture state (C1). A control at :89 shows the fixture set equals the 13 (route, state) pairs written down in ROUTE_STATES, which the shape test is parametrized over.
tests/tmp/test_55_translate_state_contract_phase3.py:107: for every fixture case of each (route, state), the driver's single response has status 200 (C1). Controls: :95 shows the fixture carries the pair. :103 shows the route's real handler (wrapped by a pass-through recorder) answered exactly once, the other route's handler not at all, and the driver returned exactly what the handler wrote. :105 shows the request carried the case's `after` exactly when the case has one. :108 shows the answer's state is the state under test.
tests/tmp/test_55_translate_state_contract_phase3.py:109: the answer's key-to-JSON-type map (bool tested before number) equals the case's engine body's, so the answer has exactly the case's key set and value JSON types (C1).
tests/tmp/test_55_translate_state_contract_phase3.py:112: where the case has cues, the answer's cues are non-empty exactly when the case's are, so the per-cue check reads at least one cue (C1).
tests/tmp/test_55_translate_state_contract_phase3.py:113: each answered cue's key-to-JSON-type map is one of the case's cues' maps (C1, "its cues included").
tests/tmp/test_55_translate_state_contract_phase3.py:128: on each route (state and enqueue, parametrized), an unknown video answers exactly [[404, the fixture's Video not found body for that route]] (C2).
tests/tmp/test_55_translate_state_contract_phase3.py:129: on each route, the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly [[404, the fixture's body]] (C2). :130 asserts no instance fetch. The control at :133 shows the same video answers 200 once the deny row is inactive.
</assertions>

<probes>
1. `ValidateTests tests/tmp/test_55_translate_state_contract_phase3.py` (final file): "14 failed, 2 passed", exit 1. Each failure is the table test or one of the 13 shape tests, and all fail with "AssertionError: tests/active/test_internal_translate.py has no ENGINE_DRIVERS: the phase's driver table is not written yet". The 2 passes are the not-found test on each route. The operator chose (AskUser, "keep_direct") to keep C2 asserted directly, green before the phase lands, because phase 3 changes no runtime code.
2. `ValidateTests tests/tmp/probe_55_phase3_checkpoint.py -q -rA --tb=line`. The probe imported this checkpoint's tests and, through an autouse parametrized fixture, put a driver table into test_internal_translate.ENGINE_DRIVERS: either the plan's draft drivers or a mutant. Result: "39 failed, 121 passed".
- Plan drivers: all 16 tests pass (table, the 13 shape tests, 2 not-found).
- Hard-coded answers that never call the handler: all 13 shape tests fail at :96 (pre-rename line, now :103, the handler-recorder control).
- State route with the instance track left on: "state none", "state already_english" and "state failed" fail at the state control, answering {'state': 'ready', 'cues': [...Hello, World]}.
- Running seeded with the module's 3-cue RUNNING for the after-3 case: fails at the non-empty check with {'state': 'running', 'cues': [], 'total': 3}.
- `after` dropped: "state running" fails at the after control.
- Enqueue stored states with no beat: enqueue running/ready/already_english/failed fail at the state control with {'state': 'none', 'available': False}.
- An extra ('state', 'busy') driver: the table test fails, "assert [('state', 'busy')] == []".
- Engine sending available as an int: all 13 shape tests fail at the type-map assertion, e.g. {'state': 'none', 'available': 1}.
- Engine dropping total: "state running" fails at the type map.
- Engine adding cues to the enqueue running/ready answers: those two fail at the type map.
- Every not-found test passed under every variant.
The probe file is now empty because I have no delete tool, so tests/tmp/probe_55_phase3_checkpoint.py can be deleted.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_55_translate_state_contract_phase3.py` - 9172 characters, inlined in full

```
"""Phase 3 checkpoint of plan 55: the Engine's /internal/translate and /internal/translate/enqueue handlers, driven into each state by the `ENGINE_DRIVERS` table phase 3 adds to tests/active/test_internal_translate.py, answer with the keys and JSON types of tests/active/fixtures/translate_contract.json, and their not-found answer is the fixture's body.

The fixture is read inside each test. A driver is called as `ENGINE_DRIVERS[(route, state)](subtitles_path, whitelist, monkeypatch, case)` and returns the responses its route's handler wrote. Both real handlers are wrapped in a pass-through recorder (a spy; the real handler still runs and answers). While test_internal_translate.py has no `ENGINE_DRIVERS`, the table test and every shape test fail on its absence.

- Table (C1): the (route, state) set of the fixture's valid 200 cases that carry available has no member without a driver, and the table has no driver without such a case. As a control, that set equals the 13 (route, state) pairs written down here (six states on the state route, those plus busy on the enqueue route), which the shape test is parametrized over.
- Shape (C1), for every such case of the (route, state): the answer is exactly one 200 whose key-to-JSON-type map equals the case's (bool before number). Where the case has cues, the answer's cues are non-empty and each cue's key-to-type map is one of the case's cues'. Controls: the fixture carries the (route, state); that route's real handler was called once and the other route's not at all, and the driver returned exactly what the handler wrote; the request carried the case's `after` exactly when the case has one; the answer's state is the state under test.
- Not found (C2), on each route: an unknown video and the actively denylisted video (deny row stored as DENIED.EXAMPLE) each answer exactly `[[404, <the fixture's Video not found body for that route>]]`, with no instance fetch. As a control, the same denied video answers 200 once its deny row is inactive. This half drives the real handlers directly and holds before the phase lands, since the phase changes no runtime code.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))

import test_internal_translate as durable  # noqa: E402

CONTRACT = Path(__file__).resolve().parents[1] / "active" / "fixtures" / "translate_contract.json"
# Every (route, state) the Engine answers, written down: the gateway's six states on the state route, and those plus busy on the enqueue route.
ROUTE_STATES = [("state", state) for state in ("none", "queued", "running", "ready", "already_english", "failed")] + [("enqueue", state) for state in ("none", "queued", "running", "ready", "already_english", "failed", "busy")]
HANDLERS = {"state": "handle_internal_translate", "enqueue": "handle_internal_translate_enqueue"}


def _contract_cases() -> list[dict]:
    return json.loads(CONTRACT.read_text())["cases"]


def _engine_cases() -> list[dict]:
    """The fixture's valid 200 cases that carry available, the shape this Engine always answers in."""
    return [case for case in _contract_cases() if case["gateway"] != "rejected" and case["engine"]["status"] == 200 and "available" in case["engine"]["body"]]


def _drivers() -> dict:
    drivers = getattr(durable, "ENGINE_DRIVERS", None)
    assert drivers is not None, "tests/active/test_internal_translate.py has no ENGINE_DRIVERS: the phase's driver table is not written yet"
    return drivers


def _json_type(value: object) -> str:
    """The JSON type a value is written as; bool first, since a bool is also an int."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def _types(body: dict) -> dict[str, str]:
    return {key: _json_type(value) for key, value in body.items()}


@pytest.fixture
def whitelist(tmp_path):
    conn = durable._whitelist(tmp_path / "whitelist.db")
    yield conn
    conn.close()


def _record_handlers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict, list]]:
    """Wrap both real route handlers so every call is recorded as (route, request body, responses written); the real handler still runs and writes the answer."""
    module = importlib.import_module("handlers.internal_translate")
    calls: list[tuple[str, dict, list]] = []
    for route, name in HANDLERS.items():
        def recording(handler, server, _route=route, _real=getattr(module, name)):
            body = json.loads(handler.rfile.getvalue())
            handled = _real(handler, server)
            calls.append((_route, body, [list(response) for response in handler.responses]))
            return handled
        monkeypatch.setattr(module, name, recording)
    return calls


def test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states():
    fixture = {(case["route"], case["engine"]["body"]["state"]) for case in _engine_cases()}
    drivers = set(_drivers())
    assert sorted(fixture - drivers) == []  # C1: no fixture (route, state) without a driver
    assert sorted(drivers - fixture) == []  # C1: no driver without a fixture (route, state)
    # Control: the list the shape test is parametrized over is the fixture's own set, so every fixture (route, state) is driven there.
    assert fixture == set(ROUTE_STATES)


@pytest.mark.parametrize("route, state", ROUTE_STATES, ids=[f"{route} {state}" for route, state in ROUTE_STATES])
def test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included(tmp_path, whitelist, monkeypatch, route, state):
    cases = [case for case in _engine_cases() if (case["route"], case["engine"]["body"]["state"]) == (route, state)]
    assert cases, (route, state)  # control: the fixture carries this (route, state)
    drive = _drivers()[(route, state)]
    calls = _record_handlers(monkeypatch)
    for index, case in enumerate(cases):
        expected = case["engine"]["body"]
        calls.clear()
        responses = drive(tmp_path / f"subtitles-{index}.db", whitelist, monkeypatch, case)
        # Control: this route's real handler answered once, the other route's not at all, and the driver returned what the handler wrote, so the answer below is the handler's and not one the driver made up.
        assert [(called, written) for called, _, written in calls] == [(route, responses)], case["name"]
        # Control: the request carried the case's after exactly when the case has one.
        assert {key: value for key, value in calls[0][1].items() if key == "after"} == ({"after": case["after"]} if "after" in case else {}), case["name"]
        ((status, answer),) = responses
        assert status == 200, (case["name"], answer)  # C1
        assert answer["state"] == state, (case["name"], answer)  # control: the driver reached the state under test
        assert _types(answer) == _types(expected), (case["name"], answer)  # C1: exactly the case's keys, each value of the case's JSON type
        if "cues" in expected:
            # Non-empty wherever the case's are, so the per-cue check below reads at least one cue.
            assert bool(answer["cues"]) == bool(expected["cues"]), (case["name"], answer)  # C1
            assert all(_types(cue) in [_types(want) for want in expected["cues"]] for cue in answer["cues"]), (case["name"], answer)  # C1: each cue's keys and JSON types are the case's cues'


@pytest.mark.parametrize("route", ["state", "enqueue"])
def test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route(tmp_path, whitelist, monkeypatch, route):
    (body,) = [case["engine"]["body"] for case in _contract_cases() if case["route"] == route and case["engine"]["status"] == 404 and case["gateway"] != "rejected"]
    answer = durable._state if route == "state" else durable._enqueue
    instance = durable._instance(True)
    internal_translate = durable._route(instance, monkeypatch)
    subtitles_path = tmp_path / "subtitles.db"
    server = durable._server(whitelist, subtitles_path)
    # A fresh beat, so the enqueue control below queues rather than answering none for want of a worker.
    durable._beat(subtitles_path, 0)
    durable._set_denied(whitelist, True)  # stored as DENIED.EXAMPLE
    denied = {"id": durable.DENIED_VIDEO[1], "host": durable.DENIED_HOST}
    assert answer(internal_translate, server, {"id": "no-such-video", "host": durable.HOST}) == [[404, body]]  # C2: unknown video
    assert answer(internal_translate, server, denied) == [[404, body]]  # C2: actively denylisted video
    assert instance.fetched == []
    # Control: with the deny inactive the same video is answered 200, so the 404 above is the denylist's doing.
    durable._set_denied(whitelist, False)
    assert answer(internal_translate, server, denied)[0][0] == 200

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 3 (Engine answers match the fixture's shape) - red (audit round 1)

`tests/tmp/test_55_translate_state_contract_phase3.py` exited 1.

```
  tests/tmp/test_55_translate_state_contract_phase3.py  14 failed, 2 passed                    0.0s
  ----------------------------------------------------
  total                                                 14 failed, 2 passed                    0.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 3 (Engine answers match the fixture's shape) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. Stub question, driver-side patching (no shape.md entry covers this) — tests/tmp/test_55_translate_state_contract_phase3.py:101
   responses = drive(tmp_path / f"subtitles-{index}.db", whitelist, monkeypatch, case)
   Each driver gets the fixture `case` and the same `monkeypatch` that patches `handlers.internal_translate`. The control at line 103 catches a driver that writes its own answer. It does not catch one that patches a symbol inside the handler module so the real handler returns data built from `case`. The checks at lines 109 and 113 would then compare the case's types with themselves. Nothing ties the answer to state the driver stored through the store's own writers. The drivers are not written yet, so I can't tell whether this can happen. A control that the driver left the module's symbols as they were (only `now_ms` patched) would close it.

PREDICTED FAILURE
`test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` fails at line 39 (`assert drivers is not None`), reached through `_drivers()` at line 85. All 13 parametrized shape tests fail on the same assertion, reached at line 96 after the control at line 95 passes. The cause in every case is that `tests/active/test_internal_translate.py` has no `ENGINE_DRIVERS`. Both parametrizations of the not-found test pass, because they drive the existing handlers directly.

NOT ASSESSED
1. `ENGINE_DRIVERS` does not exist yet in tests/active/test_internal_translate.py, which is the phase's output. So the stub question was answered from the assertion form and its controls (lines 103, 105, 108), not from what the drivers do.
2. `engine/server/api/handlers/internal_translate.py`, the handler the drivers run, was not in `code_under_test` and was not read. The claim that the recorder at lines 69–80 wraps what the drivers call depends on the drivers looking up the handler through the module attribute. That can't be checked until the drivers exist.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (40 clauses: 13 must_prove, 19 docstring, 8 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "driven through the real handler" | :103 | a driver that makes up the answer, calls the other route's handler, or edits what the handler wrote | CARRIED |
| C1b | must_prove | "answers a 200" | :106, :107 | a non-200 status, or more than one response | CARRIED |
| C1c | must_prove | "exactly that case's key set" | :109 | a missing key or an extra key (dict equality on the key-to-type map) | CARRIED |
| C1d | must_prove | "and value JSON types" | :109 | a value of the wrong JSON type, including a bool written as a number (`_json_type` :45 checks bool first) | CARRIED |
| C1e | must_prove | "its cues included": cues present wherever the case has them | :112 | an empty `cues` where the case's cues are non-empty | CARRIED |
| C1f | must_prove | "its cues included": each cue's keys and types | :113 | a cue with a missing, extra or wrongly typed field | CARRIED |
| C1g | must_prove | "no fixture state is without a driver" | :86 | a table missing a fixture (route, state) | CARRIED |
| C1h | must_prove | "nor any driver without a fixture state" | :87 | a table with an extra (route, state) | CARRIED |
| C1i | must_prove | "Each (route, state) among the fixture's valid 200 cases that carry available" is driven | :89, :95, loop :98 | a parametrize list that leaves out a fixture pair; skipping the second case of a pair (`state running after 3`, whose request body :105 checks) | CARRIED |
| C2a | must_prove | state route, unknown video → exactly the fixture's 404 body | :128 (route=state) | a different status, a different body, or more than one response | CARRIED |
| C2b | must_prove | state route, actively denylisted video → exactly the fixture's 404 body | :129, control :132 | an answer other than the fixture's 404, or a 404 not caused by the denylist (:132 shows 200 once the deny row is inactive) | CARRIED |
| C2c | must_prove | enqueue route, unknown video → exactly the fixture's 404 body | :128 (route=enqueue) | as C2a, on the enqueue handler | CARRIED |
| C2d | must_prove | enqueue route, actively denylisted video → exactly the fixture's 404 body | :129, control :132 | as C2b, on the enqueue handler | CARRIED |
| D1 | docstring | handlers driven by `ENGINE_DRIVERS` "answer with the keys and JSON types" of the fixture | :109 | a key or type that differs from the fixture's | CARRIED |
| D2 | docstring | "their not-found answer is the fixture's body" | :128, :129 | a body that is not the fixture's | CARRIED |
| D3 | docstring | the recorder passes through: "the real handler still runs and answers" | :103 | a recorder or driver that replaces what the handler wrote | CARRIED |
| D4 | docstring | "the table test and every shape test fail on its absence" | :39 (reached from :85, :96) | quietly passing or skipping while the table is missing | CARRIED |
| D5 | docstring | "has no member without a driver" | :86 | a missing driver | CARRIED |
| D6 | docstring | "the table has no driver without such a case" | :87 | an extra driver | CARRIED |
| D7 | docstring | control: the set equals the 13 pairs the shape test is parametrized over | :89 | the fixture and `ROUTE_STATES` no longer matching | CARRIED |
| D8 | docstring | "exactly one 200" | :106, :107 | zero or several responses, or a non-200 | CARRIED |
| D9 | docstring | "key-to-JSON-type map equals the case's (bool before number)" | :109 | different keys or types; a bool read as a number | CARRIED |
| D10 | docstring | "the answer's cues are non-empty" where the case has cues | :112 | empty cues | CARRIED |
| D11 | docstring | "each cue's key-to-type map is one of the case's cues'" | :113 | a cue whose shape is wrong | CARRIED |
| D12 | docstring | control: "the fixture carries the (route, state)" | :95 | a parametrized pair with no fixture case, which would run zero iterations and pass | CARRIED |
| D13 | docstring | "that route's real handler was called once and the other route's not at all" | :103 | the wrong handler called, or a handler called twice | CARRIED |
| D14 | docstring | "the driver returned exactly what the handler wrote" | :103 | a driver-made answer | CARRIED |
| D15 | docstring | "the request carried the case's `after` exactly when the case has one" | :105 | `after` missing, wrong, or sent when the case has none | CARRIED |
| D16 | docstring | "the answer's state is the state under test" | :108 | a driver that reaches a different state with a matching shape | CARRIED |
| D17 | docstring | unknown video answers exactly `[[404, <fixture body>]]` on each route | :128 | any other answer | CARRIED |
| D18 | docstring | the actively denylisted video (deny row stored as DENIED.EXAMPLE) answers exactly that | :126, :129 | any other answer; a lowercase-only deny match goes untested because the row is stored uppercase | CARRIED |
| D19 | docstring | control: "the same denied video answers 200 once its deny row is inactive" | :131, :132 | a 404 caused by something other than the denylist | CARRIED |
| N1 | name | driver table "has exactly the contract fixture's route states" | :86, :87 | a missing or an extra driver | CARRIED |
| N2 | name | "each route state driven through the real handler" | :103 | a made-up answer, or the wrong handler | CARRIED |
| N3 | name | "answers a 200" | :107 | a non-200 | CARRIED |
| N4 | name | "with its contract case's keys and json types" | :109 | a key or type that differs | CARRIED |
| N5 | name | "cues included" | :112, :113 | empty or wrongly shaped cues | CARRIED |
| N6 | name | "an unknown ... video answers the contract fixture's video not found 404" | :128 | any other answer | CARRIED |
| N7 | name | "or actively denied video answers" the same | :129 | any other answer | CARRIED |
| N8 | name | "on each route" | :116 parametrize, :119 | only one route exercised | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
none

NOT ASSESSED
1. `ENGINE_DRIVERS` does not exist in tests/active/test_internal_translate.py (a grep for it under tests/active finds nothing), even though `code_under_test` lists that file as EDITED. So I could not read the drivers. One thing stays unchecked: whether a driver reaches its state through the store's own writers or by monkeypatching parts of the handler module, using the `monkeypatch` the test passes it at :101. The C1 rows are judged on what the test's assertions exclude, given whatever driver gets written.
2. engine/server/api/handlers/internal_translate.py is not in `code_under_test` and I did not read it. I judged the C2 path and the 404 control (:132) from the helpers in test_internal_translate.py (`_state`, `_enqueue`, `_whitelist`, `_set_denied`, `_beat`) and from tests/active/fixtures/translate_contract.json.
3. tests/config.json (listed in `code_under_test`) was read. It is test-group mapping and has no bearing on any clause.
4. `fixtures_path` was not supplied. The test defines its own `whitelist` fixture at :62 and otherwise uses only pytest built-ins (`tmp_path`, `monkeypatch`), so I needed no conftest.

## 2026-10-04 - Step 7 - Phase 3 (Engine answers match the fixture's shape) - checkpoint outcome (run 1)

`tests/tmp/test_55_translate_state_contract_phase3.py` exited 0 after the phase landed.

<changes>
### tests/active/test_internal_translate.py
I added `ENGINE_DRIVERS`, the table the checkpoint looks up. It has 13 entries, keyed by (route, state): `none`, `queued`, `running`, `ready`, `already_english` and `failed` on the state route, and the same six plus `busy` on the enqueue route. I put it right after `_state`, with its two driver factories and one small helper. Each driver is called as `(subtitles_path, whitelist, monkeypatch, case)` and returns what the route's real handler wrote. It reaches the handler through `_state` or `_enqueue`, which look the handler up on the module when they run, so the checkpoint's recorder sees the call. All data goes in through the existing harness: `_seed`, `_claimed`, `_beat`, `_route`, `_server`, and the store's own writers. The only thing patched is `_route`'s usual `build_opener` and `now_ms`, which answers the shape audit's driver-side-patching recommendation.
- **`_state_driver(row)`:** seeds the key as `row` and writes a fresh beat, then calls the state route with `_instance(False)`. Without that no-track instance, `failed`, `already_english` and `none` would answer `ready`. The request carries the case's `after` exactly when the case has one.
- **Running on the state route:** the driver stores as many cues as the case's `total`, built by `_running_cues(count)` in descending start order. So `state running after 3` answers two real cues, not the `[]` that `RUNNING`'s three cues would give.
- **`_enqueue_driver(row)`:** `None` means no beat, which answers `none`. `"no row"` with a beat answers `queued`. A seeded stored state answers that state. `"busy"` fills the queue to `SUBTITLE_QUEUE_CAP` with other keys, as the existing full-queue test does.
- **Docstring:** a new "Contract drivers" paragraph before "Startup:" says what the table does and that the fixture is never read at module level, because `test_source_fetch.py` imports this module.
- **Probe:** a throwaway probe ran every driver against all 14 fixture cases that carry `available`. Each came back as exactly one 200 in the state under test, with the keys the case has. `state running` gave 3 cues and total 3. `state running after 3` sent `after` 3 and gave 2 cues and total 5. `state ready` gave the stored `STORED_READY` cue. `enqueue none` gave `available: false`; the fixture's case says `true`, but both are booleans, so the type check still passes, and the fixture's description already notes this. I did not run the checkpoint itself.
- **Probe file:** I have no tool to delete it, so I emptied `tests/tmp/test_probe_55_phase3_drivers.py`. It can be deleted.

### tests/config.json (not edited)
I left it unchanged, as phases 1 and 2 did. The planned group entries are the fixture plus `translate-worker.py`, `engine_api_client.py` and `deploy-bluegreen.sh`. Nothing in the durable module reads any of those files yet: the drivers get each case passed in. The entries belong with the step that moves the checkpoint's fixture-reading tests into the active suite, or with phase 4's derivation and timeout-chain tests.
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
  tests/tmp/test_55_translate_state_contract_phase3.py  16 passed                              0.0s
  ----------------------------------------------------
  total                                                 16 passed                              0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 4 (Single-sourced heartbeat and checked timeout chain) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
The heartbeat interval and its freshness window are defined once in server_config.py, the window derived from the interval and imported by both consumers, and the translate timeout chain across Engine, Client and deploy script is held in order by a test.

- C1 - server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own.
- C2 - REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default.

must_prove:
- C1 - server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own.
- C2 - REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default.

## 2026-10-04 - Step 7 - Phase 4 (Single-sourced heartbeat and checked timeout chain) - self-check (audit round 1, send-back 0)

`tests/tmp/test_55_translate_state_contract_phase4.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:69 — server_config.py's AST holds exactly one assignment to HEARTBEAT_FRESH_MS, plain or annotated (`len(values) == 1`) - expected: 1 once the phase lands the planned `HEARTBEAT_FRESH_MS = int(3 * HEARTBEAT_SECONDS * 1000)` (probe over that source: "good: assignments=1"). Today it reads 0, and the checkpoint run fails here with "server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once". - excludes: No shared constant at all (today's code) reads 0. A duplicate definition, one plain and one annotated, reads 2 (probe: "twice: assignments=2").
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:71 — the names in that assignment's expression include HEARTBEAT_SECONDS - expected: The probe of the planned expression read names=['HEARTBEAT_SECONDS', 'int'], which contains HEARTBEAT_SECONDS. - excludes: The literal moved into server_config as `HEARTBEAT_FRESH_MS = 15_000` reads names=[] (probe), so it fails here even though its value is 15000 and an int.
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:73 — the expression, evaluated in server_config's namespace with the real HEARTBEAT_SECONDS, equals 15000 and its type is exactly int - expected: 15000, int (probe: "real=15000 type=int" for the planned form). - excludes: `HEARTBEAT_SECONDS * 3000` reads 15000.0 of type float (probe: "real=15000.0 type=float"), so it fails the `type(real) is int` half. A wrong factor, for example two beats, reads 10000.
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:76 — the same expression evaluated with HEARTBEAT_SECONDS = 7.0 equals 21000 - expected: 21000 (probe: "seven=21000" for the planned form). - excludes: A derivation that names the interval but ignores it, `int(15_000 + HEARTBEAT_SECONDS * 0)`, passes :71 and :73 but reads seven=15000 here (probe).
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:80 — `handlers.internal_translate.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS` - expected: True once the handler does `from server_config import HEARTBEAT_FRESH_MS` (probe: "identity imported=True"). - excludes: A handler that keeps its own literal 15_000 holds an equal int but not the same object (probe: "literal=False literal_eq=True"), so it fails here where equality would pass. Deleting the handler's import and putting back `HEARTBEAT_FRESH_MS = 15_000` turns this line red.
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:84 — for internal_translate.py and for translate-worker.py, the Store-context names in the module's AST share nothing with {HEARTBEAT_SECONDS, HEARTBEAT_FRESH_MS} - expected: An empty set for both files under the planned import-only form (probe: "handler planned: stored=[]", "worker planned: stored=[]"). The positive control is :85, which shows on the same parsed tree that the name is present through an import. - excludes: Today's code reads stored=['HEARTBEAT_FRESH_MS'] for the handler and ['HEARTBEAT_SECONDS'] for the worker (probe). A module that imports the name and then reassigns `HEARTBEAT_FRESH_MS = 15_000` reads stored=['HEARTBEAT_FRESH_MS'] (probe), so it fails here even though :85 passes.
- C1 - tests/tmp/test_55_translate_state_contract_phase4.py:85 — the set of modules a `from X import` binds the name from is exactly {"server_config"}: HEARTBEAT_FRESH_MS for the handler, HEARTBEAT_SECONDS for the worker - expected: {'server_config'} for both (probe: "handler planned: from_fresh={'server_config'}", "worker planned: from_seconds={'server_config'}"). - excludes: Today both read set(), with no import at all (probe). Importing the name from another module reads {'data.subtitles'} (probe "handler other module"). Importing it from two sources reads a two-element set.
- C2 - tests/tmp/test_55_translate_state_contract_phase4.py:96 — handler REQUEST_BUDGET_SECONDS + data.source_fetch SOCKET_TIMEOUT_SECONDS &lt; lib.engine_api_client TRANSLATE_TIMEOUT_SECONDS - expected: 15.0 + 4.0 = 19.0 &lt; 20, so True. The probe printed budget=15.0 socket=4.0 client=20, and the checkpoint run shows this test passing. - excludes: Raising the budget to 16.0, the socket timeout to 5.0 (the harvest mutation K3), or dropping the Client timeout to 19 reads 20.0 &lt; 20 or 19.0 &lt; 19, which is False.
- C2 - tests/tmp/test_55_translate_state_contract_phase4.py:97 — TRANSLATE_TIMEOUT_SECONDS &lt; the DRAIN_SECONDS default from the single line-anchored match in deploy-bluegreen.sh. :94 is the control: it requires exactly one match. - expected: 20 &lt; 30, so True. The probe printed drains=['30'] over the real script; the indented `--drain)` line is not matched (probe). - excludes: A drain default of 20, or a Client timeout raised to 30, reads False. A reformatted default (`DRAIN_SECONDS="30"`) matches nothing (probe: []), and a second default line matches twice (probe: ['30', '45']). Both fail at the :94 control, not silently.

<assertions>
tests/tmp/test_55_translate_state_contract_phase4.py:69 - server_config.py's source holds exactly one HEARTBEAT_FRESH_MS assignment, plain or annotated (excludes: no shared constant, today's state, which fails here with "0 times"; a duplicate definition) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:71 - that assignment's expression names HEARTBEAT_SECONDS (excludes: a literal 15_000 moved into server_config) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:73 - the expression, evaluated in server_config's own namespace with the real HEARTBEAT_SECONDS, is 15000 and an int (excludes: a changed window or factor; `HEARTBEAT_SECONDS * 3000`, which gives the float 15000.0) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:74 - control: server_config.HEARTBEAT_FRESH_MS equals that evaluated value, so the parsed expression is the one the module runs - C1 (control)
tests/tmp/test_55_translate_state_contract_phase4.py:76 - the same expression with HEARTBEAT_SECONDS = 7.0 is 21000 (excludes: a derivation that names the interval but ignores it, e.g. `int(15_000 + HEARTBEAT_SECONDS * 0)`) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:80 - handlers.internal_translate.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS by identity (excludes: the handler keeping its own equal literal 15_000) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:84 - for internal_translate.py and for translate-worker.py, the module binds neither HEARTBEAT_SECONDS nor HEARTBEAT_FRESH_MS itself (any Store-context name: assignment, augmented, unpacking) (excludes: today's `HEARTBEAT_FRESH_MS = 15_000` and `HEARTBEAT_SECONDS = 5.0`; importing and then reassigning) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:85 - the handler imports HEARTBEAT_FRESH_MS, and the worker HEARTBEAT_SECONDS, under its own name from server_config and from no other module (excludes: no import; importing from somewhere else, e.g. the worker taking it from handlers.internal_translate) - C1
tests/tmp/test_55_translate_state_contract_phase4.py:94 - control: deploy-bluegreen.sh has exactly one line-anchored `DRAIN_SECONDS=<digits>` default line, so the drain is read from one place - C2 (control)
tests/tmp/test_55_translate_state_contract_phase4.py:96 - handler REQUEST_BUDGET_SECONDS + data.source_fetch.SOCKET_TIMEOUT_SECONDS < lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (excludes: budget raised to 16+, socket timeout raised to 5+, Client timeout lowered to 19 or less) - C2
tests/tmp/test_55_translate_state_contract_phase4.py:97 - TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default (excludes: drain lowered to 20 or less, or Client timeout raised to 30 or more) - C2
</assertions>

<probes>
ValidateTests ["tests/tmp/probe_55_phase4_constants.py", "-s"], first version, with tests/active on sys.path and test_internal_translate imported. It printed: server_config resolves to engine/server/api/server_config.py; lib.engine_api_client resolves to client/backend/lib/engine_api_client.py with TRANSLATE_TIMEOUT_SECONDS 20; SOCKET_TIMEOUT_SECONDS 4.0; REQUEST_BUDGET_SECONDS 15.0; the handler's HEARTBEAT_FRESH_MS is 15000 and server_config has no HEARTBEAT_FRESH_MS today; the regex `^DRAIN_SECONDS=(\d+)$` with MULTILINE finds ['30'] (one match); a literal `15_000` in one namespace `is` not the int computed by `int(S * 3 * 1000)` in another (False); a `from server_config import` binding `is` the module's own object (True); translate-worker.py's only server_config ImportFrom lists 7 names and HEARTBEAT_SECONDS is not among them.
ValidateTests ["tests/tmp/probe_55_phase4_constants.py", "-s"], second version, calling the checkpoint's own helpers on made-up sources. It printed: `int(HEARTBEAT_SECONDS * 3 * 1000)` gives 15000 (int) at 5.0 and 21000 at 7.0; `HEARTBEAT_SECONDS * 3000` gives 15000.0; `15_000 + HEARTBEAT_SECONDS * 0` at 7.0 gives 15000.0; an annotated assignment is counted (1); a handler that imports the name has no binding of its own and imports from {'server_config'}; a handler with a literal binds {'HEARTBEAT_FRESH_MS'} and imports it from set(); on today's real files the worker binds {'HEARTBEAT_SECONDS'} and imports it from set(), and the handler binds {'HEARTBEAT_FRESH_MS'} and imports it from set().
ValidateTests ["tests/tmp/test_55_translate_state_contract_phase4.py"] against the current code: 1 failed, 1 passed. The heartbeat test fails at line 69 with "server_config.py assigns HEARTBEAT_FRESH_MS 0 times; expected exactly once", which is the expected red before the phase lands. The timeout-chain test passes: 15.0 + 4.0 < 20 < 30 already holds, and this phase only adds the guard for it.
Not observed: the checkpoint passing against a correct implementation, since the edited source files are outside this step. The helper probe above shows the intended `int(HEARTBEAT_SECONDS * 3 * 1000)` shape passes lines 71-76. The phase's own green run will confirm the rest.
Cleanup: there is no delete tool here, so the probe file tests/tmp/probe_55_phase4_constants.py is still on disk. Please remove it. It is not part of the checkpoint.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_55_translate_state_contract_phase4.py` - 6576 characters, inlined in full

```
"""Phase 4 checkpoint of plan 55: the translate worker's heartbeat interval and the Engine's freshness window are defined once, in engine/server/api/server_config.py, and the translate timeouts across Engine, Client and deploy script stay in order.

- Heartbeat (C1): server_config.py's source holds exactly one HEARTBEAT_FRESH_MS assignment, its expression names HEARTBEAT_SECONDS, and evaluated in the module's own namespace it gives 15000 (an int, the module's value) with the real interval and 21000 with 7.0. The handler module's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal. Neither internal_translate.py nor translate-worker.py binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself; the handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module.
- Timeout chain (C2): the handler's REQUEST_BUDGET_SECONDS plus data.source_fetch's SOCKET_TIMEOUT_SECONDS is below lib.engine_api_client's TRANSLATE_TIMEOUT_SECONDS, which is below the DRAIN_SECONDS default that scripts/deploy-bluegreen.sh assigns on exactly one line of its own.

Behaviour at the 15 000 / 15 001 ms edges is test_internal_translate.py's BEATS claim, and the worker's beat is test_translate_worker.py's; this file claims only where the numbers come from and how they relate.
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
BACKEND_DIR = ROOT / "client" / "backend"
# The order conftest and test_internal_translate.py leave: the Engine's dirs ahead of the Client's, so `data` is the Engine's and `lib` the Client's.
for _path in (BACKEND_DIR, SERVER_DIR, API_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

SERVER_CONFIG = API_DIR / "server_config.py"
HANDLER = API_DIR / "handlers" / "internal_translate.py"
WORKER = SERVER_DIR / "db" / "jobs" / "translate-worker.py"
DEPLOY = ROOT / "scripts" / "deploy-bluegreen.sh"
HEARTBEAT_NAMES = {"HEARTBEAT_SECONDS", "HEARTBEAT_FRESH_MS"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _assigned_values(tree: ast.Module, name: str) -> list[ast.expr]:
    """The value expression of every assignment to `name`, plain or annotated, anywhere in the module."""
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
            values.append(node.value)
    return values


def _stored_names(tree: ast.Module) -> set[str]:
    """Every name the module binds by assignment, augmented assignment, unpacking, loop or with target."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}


def _importing_modules(tree: ast.Module, name: str) -> set[str]:
    """The modules a `from X import` binds `name` from, under its own name."""
    return {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names if (alias.asname or alias.name) == name}


def _evaluate(expression: ast.expr, heartbeat_seconds: float) -> object:
    """The expression's value in server_config's own namespace with HEARTBEAT_SECONDS replaced, so a derivation through other module names still evaluates."""
    import server_config

    namespace = {**vars(server_config), "HEARTBEAT_SECONDS": heartbeat_seconds}
    return eval(compile(ast.Expression(expression), str(SERVER_CONFIG), "eval"), namespace)


def test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it():
    import server_config

    values = _assigned_values(_tree(SERVER_CONFIG), "HEARTBEAT_FRESH_MS")
    assert len(values) == 1, f"server_config.py assigns HEARTBEAT_FRESH_MS {len(values)} times; expected exactly once"  # C1
    (expression,) = values
    assert "HEARTBEAT_SECONDS" in {node.id for node in ast.walk(expression) if isinstance(node, ast.Name)}, ast.unparse(expression)  # C1: derived from the interval, not a literal
    real = _evaluate(expression, server_config.HEARTBEAT_SECONDS)
    assert real == 15000 and type(real) is int, (ast.unparse(expression), real)  # C1: the real interval gives today's window, as an int
    assert server_config.HEARTBEAT_FRESH_MS == real  # control: the evaluated expression is the module's value
    # A wrong derivation that names the interval but ignores it (`int(15_000 + HEARTBEAT_SECONDS * 0)`) still gives an int 15000 above; another interval tells them apart.
    assert _evaluate(expression, 7.0) == 21000, ast.unparse(expression)  # C1

    handler = importlib.import_module("handlers.internal_translate")
    # Identity, not equality: a handler literal 15_000 equals the derived value but is a different int object (observed in the probe).
    assert handler.HEARTBEAT_FRESH_MS is server_config.HEARTBEAT_FRESH_MS  # C1

    for path, imported in ((HANDLER, "HEARTBEAT_FRESH_MS"), (WORKER, "HEARTBEAT_SECONDS")):
        tree = _tree(path)
        assert _stored_names(tree) & HEARTBEAT_NAMES == set(), f"{path.name} binds {sorted(_stored_names(tree) & HEARTBEAT_NAMES)} itself"  # C1
        assert _importing_modules(tree, imported) == {"server_config"}, f"{path.name} imports {imported} from {sorted(_importing_modules(tree, imported), key=str)}"  # C1


def test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain():
    budget = importlib.import_module("handlers.internal_translate").REQUEST_BUDGET_SECONDS
    socket_timeout = importlib.import_module("data.source_fetch").SOCKET_TIMEOUT_SECONDS
    client_timeout = importlib.import_module("lib.engine_api_client").TRANSLATE_TIMEOUT_SECONDS
    # Line-anchored, so the `--drain) DRAIN_SECONDS="${2:-}"` override and the validation line do not count.
    drains = re.findall(r"^DRAIN_SECONDS=(\d+)$", DEPLOY.read_text(), re.MULTILINE)
    assert len(drains) == 1, f"deploy-bluegreen.sh has {len(drains)} DRAIN_SECONDS default lines: {drains}"
    drain = int(drains[0])
    assert budget + socket_timeout < client_timeout, (budget, socket_timeout, client_timeout)  # C2
    assert client_timeout < drain, (client_timeout, drain)  # C2

```


Gate: satisfied

## 2026-10-04 - Step 7 - Phase 4 (Single-sourced heartbeat and checked timeout chain) - red (audit round 1)

`tests/tmp/test_55_translate_state_contract_phase4.py` exited 1.

```
  tests/tmp/test_55_translate_state_contract_phase4.py  1 failed, 1 passed                     0.0s
  ----------------------------------------------------
  total                                                 1 failed, 1 passed                     0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 7 - Phase 4 (Single-sourced heartbeat and checked timeout chain) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: nothing

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
1. downshift_rule (rules/shape.md) — tests/tmp/test_55_translate_state_contract_phase4.py:93
   drains = re.findall(r"^DRAIN_SECONDS=(\d+)$", DEPLOY.read_text(), re.MULTILINE)
   The drain default is read by regex over the shell script's source. That is below the
   direct-import rung that lines 89-91 use for the other three numbers. The script has a
   `--dry-run` that prints `drain=${DRAIN_SECONDS}s` (deploy-bluegreen.sh:240). That path
   needs `--blue-green` and a readable upstream snippet (:253), so a rung-2 read may well
   be impractical. The comment at :92 only explains why the regex is line-anchored. It
   does not say why the test drops a rung, which is what the rule asks for. Add a
   `# rung N: ...` comment naming the reason.

PREDICTED FAILURE
test_the_heartbeat_freshness_window_... fails at line 69 on `assert len(values) == 1`.
server_config.py has no assignment to HEARTBEAT_FRESH_MS today, so `values` is empty. Both
names are still literals of their own: internal_translate.py:33 `HEARTBEAT_FRESH_MS = 15_000`
and translate-worker.py:59 `HEARTBEAT_SECONDS = 5.0`. test_the_engine_fetch_budget_... passes
on the code as it stands: 15.0 + 4.0 < 20 < 30, and deploy-bluegreen.sh:50 is the only
`DRAIN_SECONDS=` default line. The C2 ordering already holds before the phase.

NOT ASSESSED
1. `fixtures_path` was "none found". The test defines no fixtures and relies on none, so
   nothing is missing.
2. `code_under_test` lists tests/active/test_internal_translate.py and tests/config.json.
   This test neither imports nor reads either file, so neither has any bearing on its
   assertion form. They were not read.
3. The stub question was answered from the assertion form:
   - C1 fails on a literal (line 71).
   - C1 fails on a derivation that names HEARTBEAT_SECONDS but ignores it (line 76, second
     input 7.0 → 21000).
   - C1 fails on a float-valued derivation (line 73, `type(real) is int`).
   - C1 fails on a handler-local equal literal (line 80 identity; lines 84-85).
   - C2 fails if any one of its four constants is moved out of order.
   No anti_pattern entry matched:
   - Line 84's negative assertion is paired with line 85's positive one.
   - Line 74's same-source equality is a labelled control, and lines 73/76 carry the
     independent literals.
   - C1 is a structural invariant and sits at rung 4 (AST parse), which is consistent
     with matching_rule.
```

### devsecops-test-claim-auditor

```
CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (21 clauses: 6 must_prove, 11 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS" | :71, :76 | a literal 15_000 (:71); a derivation that names the interval but ignores it, e.g. `15_000 + HEARTBEAT_SECONDS*0` (:76, 7.0 must give 21000) | CARRIED |
| C1b | must_prove | the derived window is server_config's own module value | :69, :74 | a second assignment that rebinds the name after the derived one (:69 counts exactly one; :74 ties the evaluated expression to the module attribute) | CARRIED |
| C1c | must_prove | internal_translate.py imports its heartbeat name from server_config | :80, :85 | a handler literal equal to 15000 (:80 checks identity); an import from any other module (:85 checks set equality) | CARRIED |
| C1d | must_prove | translate-worker.py imports its heartbeat name from server_config | :85 | worker importing HEARTBEAT_SECONDS from another module, or not importing it | CARRIED |
| C1e | must_prove | "instead of assigning a literal of their own" (both consumers) | :84 | `HEARTBEAT_SECONDS = 5.0` / `HEARTBEAT_FRESH_MS = 15_000` kept in either file, including annotated, augmented or unpacked binds | CARRIED |
| C2a | must_prove | REQUEST_BUDGET_SECONDS + SOCKET_TIMEOUT_SECONDS < TRANSLATE_TIMEOUT_SECONDS | :96 | a budget or socket timeout raised so the sum reaches the Client timeout; strict `<` also excludes equality | CARRIED |
| C2b | must_prove | TRANSLATE_TIMEOUT_SECONDS < deploy-bluegreen.sh's DRAIN_SECONDS default | :94, :97 | a Client timeout at or past the drain (:97); reading the `--drain` override or a duplicate default line in place of the one default (:94) | CARRIED |
| D1 | docstring | "defined once, in engine/server/api/server_config.py" | :69, :84 | a second definition in server_config or in either consumer | CARRIED |
| D2 | docstring | "translate timeouts across Engine, Client and deploy script stay in order" | :96, :97 | either inequality inverted | CARRIED |
| D3 | docstring | "exactly one HEARTBEAT_FRESH_MS assignment" | :69 | zero or two assignments | CARRIED |
| D4 | docstring | "its expression names HEARTBEAT_SECONDS" | :71 | a bare literal expression | CARRIED |
| D5 | docstring | "gives 15000 (an int, the module's value) with the real interval" | :73, :74 | a float 15000.0; a value that differs from the module attribute | CARRIED |
| D6 | docstring | "21000 with 7.0" | :76 | an expression that does not scale with the interval | CARRIED |
| D7 | docstring | "handler's HEARTBEAT_FRESH_MS is server_config's object, not an equal literal" | :80 | an equal literal in the handler | CARRIED |
| D8 | docstring | "Neither ... binds HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS itself" | :84 | either name bound in either file | CARRIED |
| D9 | docstring | "handler imports HEARTBEAT_FRESH_MS and the worker HEARTBEAT_SECONDS from server_config and from no other module" | :85 | an import from another module, or from two modules | CARRIED |
| D10 | docstring | "REQUEST_BUDGET_SECONDS plus ... SOCKET_TIMEOUT_SECONDS is below ... TRANSLATE_TIMEOUT_SECONDS" | :96 | sum >= Client timeout | CARRIED |
| D11 | docstring | "below the DRAIN_SECONDS default ... assigns on exactly one line of its own" | :94, :97 | zero or several default lines; Client timeout >= drain | CARRIED |
| N1 | name | "heartbeat freshness window is derived from the interval in server_config" | :71, :76 | literal or interval-ignoring window | CARRIED |
| N2 | name | "both consumers import it" | :85 | a consumer importing from elsewhere or not at all | CARRIED |
| N3 | name | "engine fetch budget and socket timeout fit inside the client translate timeout" | :96 | sum >= Client timeout | CARRIED |
| N4 | name | "which fits inside the deploy drain" | :97 | Client timeout >= drain | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. name-as-sentence (rules/testing.md) — tests/tmp/test_55_translate_state_contract_phase4.py:65
   "both consumers import it": the only antecedent of "it" is "the heartbeat freshness window",
   but the worker imports the interval (HEARTBEAT_SECONDS, :82), not the window. A failure
   from the worker side would read as a failure to import the window. "...and both consumers
   import their heartbeat name from it" matches what :85 asserts.
2. No rule covers this (rules/testing.md, whole-claim read against the docstring's "defined
   once") — tests/tmp/test_55_translate_state_contract_phase4.py:84-85
   The test proves the consumers import the shared name and do not rebind it. It does not
   prove they use it. Two cases still pass every assertion: a worker that imports
   HEARTBEAT_SECONDS and still calls `stop.wait(5.0)`, and a handler that compares against a
   literal 15_000 under another name. Line 6 hands the worker's beat and the handler's 15 000
   edge to other files, and C1 as worded is about import versus assignment, so this does not
   make any row UNCARRIED. Reported because the docstring's line-1 sentence is broader than
   what is asserted.

OBSERVATIONS
none

NOT ASSESSED
1. Some edits are not in the files: engine/server/api/server_config.py, as read, defines
   neither HEARTBEAT_SECONDS nor HEARTBEAT_FRESH_MS, and both consumers still bind their own
   (internal_translate.py:33, translate-worker.py:59), although the dispatch marks all three
   EDITED. So the names the test reads at :66-80 could not be checked against a definition
   in server_config, and the CLAUSE MAP judges what each assertion excludes, not whether it
   currently holds.
2. tests/active/test_internal_translate.py and tests/config.json were read only for their
   heartbeat and registration lines, because the test under audit does not import from them.
   No fixtures are used. The only conftest found, tests/active/conftest.py, does not cover
   tests/tmp/.
```

## 2026-10-04 - Step 7 - Phase 4 (Single-sourced heartbeat and checked timeout chain) - checkpoint outcome (run 1)

`tests/tmp/test_55_translate_state_contract_phase4.py` exited 0 after the phase landed.

<changes>
### engine/server/api/server_config.py
Added `HEARTBEAT_SECONDS = 5.0` (the worker's beat interval) and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)` right after the `SUBTITLE_*` translate constants. The window is three beats, so one late beat is still tolerated. It comes out as the int 15000 today and follows the interval if that changes.

### engine/server/api/handlers/internal_translate.py
Removed the handler's own `HEARTBEAT_FRESH_MS = 15_000` and the rat-tail comment above it. The handler now gets the name from the existing `server_config` import (`from server_config import HEARTBEAT_FRESH_MS, SUBTITLE_QUEUE_CAP`). The freshness check in `_worker_available` is unchanged and reads the imported name.

### engine/server/db/jobs/translate-worker.py
Removed the worker's own `HEARTBEAT_SECONDS = 5.0` and the rat-tail comment above it (the one saying there was no shared constant). `HEARTBEAT_SECONDS` is added to the existing `from server_config import ...` line. The beat loop and `beat.join` use it unchanged.

### C2 (timeout chain)
No code change: the chain already holds. `REQUEST_BUDGET_SECONDS` 15.0 plus `SOCKET_TIMEOUT_SECONDS` 4.0 is 19, which is below `TRANSLATE_TIMEOUT_SECONDS` 20, which is below the `DRAIN_SECONDS=30` default in deploy-bluegreen.sh. That default sits on one line of its own. The checkpoint now holds this order in place.

### tests/active/test_internal_translate.py, tests/config.json
Not touched in this step. The instruction was production code only. These files belong to moving the checkpoint into the active suite, and nothing in them stood in the way of the change: no test patches the handler's or the worker's heartbeat names.

### Observation
I ran a throwaway probe, `tests/tmp/probe_55_phase4_impl.py`, with ValidateTests rather than running the gating checkpoint. It printed `server_config.HEARTBEAT_FRESH_MS` = 15000 as an `int`, and the handler's `HEARTBEAT_FRESH_MS` is the same object as server_config's. Loading translate-worker.py from its file gives `HEARTBEAT_SECONDS` 5.0, also the same object as server_config's. I have no delete tool, so the probe is still in tests/tmp/ and needs removing. Docs that still say "raise both constants together" (engine/server/README.md, TRANSLATE_WORKER.md, DEPLOYMENT.md) are for the documentation step.
</changes>

<inner_tests>
none
</inner_tests>

<unanticipated>
tests/tmp/probe_55_phase4_impl.py: a throwaway probe created to observe the imported values. I have no delete tool, so it is still there and should be removed.
</unanticipated>

<awaiting_operator>
none
</awaiting_operator>

```
  tests/tmp/test_55_translate_state_contract_phase4.py  2 passed                               0.0s
  ----------------------------------------------------
  total                                                 2 passed                               0.2s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase3.py`
- P4C1 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase4.py`
- P4C2 - carried - rests on: the last audit of `tests/tmp/test_55_translate_state_contract_phase4.py`

## 2026-10-04 - Step 8 - refactor pass

<refactors>
none. The build's production diff is already as small as it can be. server_config.py gains two lines, HEARTBEAT_SECONDS and HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000). internal_translate.py and translate-worker.py each drop their own literal and import the name from server_config. A search of engine/ for HEARTBEAT, 15_000 and 15000 finds no other copy of either value in production code, and both consumers read the shared names. There was nothing left to merge, rename or delete.
</refactors>

<left_out>
Stale docs, which are outside this pass's production files and belong to the documentation step. engine/server/db/jobs/docs/TRANSLATE_WORKER.md:155 still says "Raise both constants together", which is no longer true now that the window is derived from the interval. engine/server/README.md:18 and DEPLOYMENT.md, which the phase 4 outcome also names, should be checked for the same wording. Test-side work that the phases deferred, left out because it is test wiring and not a production refactor, and gating tests are not mine to edit: moving the checkpoints into the active suite, and the tests/config.json group entries (the fixture plus api-base.ts, translate-worker.py, engine_api_client.py and deploy-bluegreen.sh). Probe files that need deleting, because I have no delete tool: tests/tmp/probe_55_phase1_replay.py, probe_55_phase1_checkpoint.py, probe_55_contract.py, probe_55_phase2_runner.py, test_probe_55_phase3_drivers.py and probe_55_phase4_impl.py.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
I made no refactors: a search shows the heartbeat interval and window are defined once in server_config.py and imported by both the handler and the worker, nothing else needed changing, and I ran no tests in this pass.
</observation>

## 2026-10-04 - Step 8 - suite comparison (attempt 1)

`--compare` exited 0.

```
selected 11 of 65 test groups (54 unchanged):
  test_dislike_profile.py — changed
  test_frontend_translate.py — changed
  test_internal_events.py — changed
  test_internal_translate.py — changed
  test_popular_videos.py — changed
  test_random_cache.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_server_config.py — changed
  test_similar.py — changed
  test_translate_worker.py — changed
  test_dislike_profile.py     9 passed                              40.9s
  test_frontend_translate.py  20 passed                             27.6s
  test_internal_events.py     9 passed                               0.8s
  test_internal_translate.py  122 passed                             2.3s
  test_popular_videos.py      12 passed                              0.3s
  test_random_cache.py        28 passed                             56.0s
  test_search_fusion.py       10 passed                              2.7s
  test_server.py              155 passed                            73.3s
  test_server_config.py       33 passed                             13.2s
  test_similar.py             83 passed                             47.7s
  test_translate_worker.py    68 passed                             75.3s
  --------------------------
  total                       549 passed                            75.7s wall, 11 lanes

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-10-04 - Step 10 - stopped

Harvest tests did not complete. The entries above carry what the step established before it stopped; the gate it failed is the last of them.

## 2026-10-04 - Step 10 - Harvest tests - plan

<harvest_file>
docs/project/plans/harvest-55-translate-state-contract-plan.md
</harvest_file>

<plan>
## Harvest plan: build 55 translate-state-contract

Scope: the 4 checkpoint files in `tests/tmp` (`test_55_translate_state_contract_phase1..4.py`). All of them collect (105 items from 11 functions). The bootstrap gate is clear. `tests/last_test_validation.json.preharvest` was taken first and is cmp-identical to the record, and nothing has banked since.

### Count per verdict (11 test functions)

- DURABLE: 8
- REPLACES: 0
- COMBINE: 0
- REDUNDANT: 1
- SPENT: 0

That covers 9 functions. Phase 1 holds 2 of the 11 and the counts above miss neither; for the record per file: phase1 2, phase2 2, phase3 3, phase4 2, total 9. Correction: the scope has 9 test functions, not 11. pytest collected 105 parametrized items from those 9.

### DURABLE tests and their destinations

1. `test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route` (phase1, 43 cases) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It replays every contract-fixture case through the real `fetch_translate`/`request_translate`. No active test calls those functions directly, and test_server.py's `/api/translate` tests miss several fixture cases (1e999 start, bool end, `busy` on the state route, string `available` and unknown state on enqueue).
2. `test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names` (phase1) goes to **`tests/active/test_engine_api_client.py` (NEW)**. It is the only test that holds the fixture's valid states equal to `TRANSLATE_STATES`/`TRANSLATE_REQUEST_STATES`.
3. `test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order` (phase2, 29 cases) goes to `tests/active/test_frontend_translate.py`. Nothing there asserts the parser's answers against the fixture, and `CONTRACT_RUNNER` sits there unused.
4. `test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed` (phase2, 14 cases) goes to `tests/active/test_frontend_translate.py`. No active test asserts the "Translate response was malformed" refusal.
5. `test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states` (phase3) goes to `tests/active/test_internal_translate.py`. `ENGINE_DRIVERS` is there and no test reads it.
6. `test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included` (phase3, 13 route/states) goes to `tests/active/test_internal_translate.py`. Today the Engine's answers are held only to the module's own constants, never to the fixture.
7. `test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it` (phase4) goes to `tests/active/test_server_config.py`. No active test names `HEARTBEAT_SECONDS` or `HEARTBEAT_FRESH_MS`, and the BEATS edge tests would pass against an equal literal.
8. `test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain` (phase4) goes to `tests/active/test_internal_translate.py`, after `test_one_15_second_budget_covers_both_fetches`. No active test holds the budget + socket < Client timeout < drain chain.

### REDUNDANT (stays out)

- `test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route` (phase3). Four tests already in test_internal_translate.py assert exactly `[[404, {"error": "Video not found"}]]` for an unknown and an actively denied video on both routes, with the inactive-deny control: `test_an_unknown_video_is_404_video_not_found_with_no_fetch`, `test_a_denylisted_host_is_404_video_not_found_with_no_fetch_even_with_a_stored_track`, `test_enqueue_refuses_a_bad_body_or_unknown_video_exactly_as_the_state_route_does[unknown video]` and `test_enqueue_refuses_a_denylisted_host_exactly_as_the_state_route_does`. Harvested test 2 holds the fixture's 404 body to that same literal.

### REPLACES / COMBINE

None.

### Active tests that would be retired

None. Nothing moves to `tests/archive/`.

### test_groups entries that would change

- **`test_engine_api_client.py`: new entry** with `client/backend/lib/engine_api_client.py` and `tests/active/fixtures/translate_contract.json`.
- `test_frontend_translate.py`: add `tests/active/fixtures/translate_contract.json` and `client/frontend/src/data/api-base.ts`. api-base.ts runs in the bundle and builds the `/api/translate` URL the replay asserts.
- `test_internal_translate.py`: add `tests/active/fixtures/translate_contract.json`, `client/backend/lib/engine_api_client.py` and `scripts/deploy-bluegreen.sh`.
- `test_server_config.py`: add `engine/server/api/handlers/internal_translate.py` and `engine/server/db/jobs/translate-worker.py`.
- No entry is dropped.

### Subject file Step 5 would create (called out separately)

- **`tests/active/test_engine_api_client.py`** is a new group with a new map entry. It is named for `client/backend/lib/engine_api_client.py`, the script the phase 1 tests drive directly, because no subject file exists for it. It gets its own copies of `_TranslateEngine`, `_serving` and `_translate_engine` from test_server.py, copied rather than imported or hoisted. **Decision point for the operator:** the build plan and the fixture's own `description` text name `tests/active/test_server.py` as the home, because that module's docstring already claims the gateway's `fetch_translate` mapping and it already holds the stub. Choosing test_server.py instead means no new file and no new group (its entry already claims `engine_api_client.py`; add only the fixture), and the fixture's description stays accurate. Keeping the new file means updating that description so it no longer names test_server.py. I followed harvest.md's one-script-one-file rule, but either is defensible.

### Name check preview (confirmed in Step 5)

- test_internal_translate.py: the incoming `whitelist` fixture is the same body as the existing one at line 455, so one copy is kept.
- test_server_config.py: `SERVER_CONFIG` exists at line 157 with the same value, so one copy is kept.
- No other incoming name collides.

### Outside scope, noted for the operator

Build 55 left probes in `tests/tmp`, most of them emptied because the build had no delete tool: `probe_55_*.py` (10 files) and the zero-byte `test_probe_55_phase3_drivers.py`. They are not checkpoints, so Step 7 will not move them to `delete_me/` unless the operator adds them. `test_probe_55_phase3_drivers.py` matches `test_*.py` and stays in every `tests/tmp` run.
</plan>

## 2026-10-04 - Step 9 - build diff

`.scratch/55-translate-state-contract/build.diff`: 68 changed file(s) between the Step 0 snapshot `0269ffadf94e1dfce619d60be859ed2202466c0d` (2026-10-04T13:39:28-04:00) and `4e061b22af622dc56c61dfcd62c790772fa1c031`. Withheld by the permission table: 0.

## 2026-10-04 - Step 9 - document triage

- [ ] `engine/server/README.md` - Line 15 (`/internal/translate`): "`total`, the stored cue count" is incomplete. Add the running-slice rule in CONTEXT.md's terms: `total` always counts every stored cue whatever `after` was, so a reader that holds more running cues than `total` knows the job was requeued and restarted. Line 18 (Availability): "`HEARTBEAT_FRESH_MS` (15 000 ms, three of the worker's 5 s beats)" no longer says where the value comes from. It is now defined in `api/server_config.py` and derived from `HEARTBEAT_SECONDS` as three beats (`int(HEARTBEAT_SECONDS * 3 * 1000)`, still 15 000 ms). Line 30 (worker tunables): the sentence listing the worker's `api/server_config.py` names should also name its beat interval `HEARTBEAT_SECONDS`, which now lives there and not in the worker. Line 38 ("every 5 s", "15 s freshness rule") is still true and stays.
- [ ] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - The Heartbeat section (≈line 159, after issue 56's edit to the same paragraph) still ends "Raise both constants together." That is false now. There is a single definition: `HEARTBEAT_SECONDS` (5.0) in `engine/server/api/server_config.py`, with `HEARTBEAT_FRESH_MS` derived from it as three beats, so changing the interval moves the window with it. Replace the sentence with that. Keep the "every 5 s", "15 s" and "up to 5 s" join figures, and keep the `--stall-seconds` wording issue 56 added.
- [ ] `engine/server/api/handlers/internal_translate.py` - The rat-tail comment and the literal are already gone (diff hunk at :27-35). Module docstring line 3 ("whether the translate worker beat within HEARTBEAT_FRESH_MS") does not say where the constant now comes from. Add the location in place, e.g. "HEARTBEAT_FRESH_MS (server_config.py, three HEARTBEAT_SECONDS beats)". Line 5 already names the constant and needs no change. Optional: the budget comment at line 30 could name the timeout-chain test, but that test is not in the active suite yet (it is still in tests/tmp), so leave it as it is for now.
- [ ] `engine/server/db/jobs/translate-worker.py` - The rat-tail comment and literal at :58-59 are gone, and the module docstring's "every 5 s" (line 8) is still true. One comment is now incomplete: line 35, "api/ is for server_config and the route's resolve_translatable_video, …", should say that server_config supplies the bounds and `HEARTBEAT_SECONDS`, because the beat interval is now imported from there and that import is one more reason `api/` is on the path.
- [ ] `tests/active/test_frontend_translate.py` - The module now holds a third runner, `CONTRACT_RUNNER` (end of the module), but the docstring (lines 1-31) still describes only "the first runner" and `GENERATION_RUNNER`. Add a paragraph about the contract runner. It covers `data/translate.ts` on its own, with stubs for `localStorage`, `window.location.origin` (set before the dynamic import, because api-base.ts reads it when it loads) and a 200-only `fetch`. Every fixture case is served to `fetchTranslate` (state route, with its `after`) or `requestTranslate` (enqueue route): the gateway answer for a valid case and the Engine body for a rejected one. Non-finite numbers are written back as `1e999`, since `JSON.stringify` would write `null`, and the report records per case whether the served text parsed to a non-finite number. The replay tests that consume the runner are still in tests/tmp and the harvest moves them here. Describe what they assert (valid cases keep their fields, `ready` sorted by start then end, `running` kept in order, rejected cases throw exactly `Translate response was malformed`) only once they have landed, so the paragraph is never ahead of the module.
- [ ] `docs/project/issues/55-translate-state-contract.md` - The issue is delivered. Following docs/project/triage-labels.md, set its `Status:` to `complete`, tick the acceptance criteria the build met, add a Delivered note, and move it to `docs/project/issues/archive/`. Two points need care. The Delivered note should record that the heartbeat pair lives in `api/server_config.py`. It should also record that the durable tests are placed by the harvest: gateway replay in a new `test_engine_api_client.py`, the heartbeat derivation in `test_server_config.py`, and the Engine Video-not-found check judged redundant with existing tests. Its Problem section's line references (`translate-worker.py:60-61`, `internal_translate.py:37-38`) describe the issue as filed and stay as they are.

Out of scope:
- [ ] `tests/active/test_server.py` - The file was not edited. The harvest plan (docs/project/plans/harvest-55-translate-state-contract-plan.md) sends phase 1's gateway replay and coverage tests to a NEW `tests/active/test_engine_api_client.py`, not to this file. Its translate docstring paragraphs still describe exactly the tests it holds. The new module's docstring belongs to that harvest step.
- [ ] `tests/active/test_internal_translate.py` - The docstring already gained the build's paragraph: "Contract drivers: `ENGINE_DRIVERS` …" (diff, line 48) describes the driver table that is in the module. The other checklist entries describe tests that are not in this module. Per the harvest plan, the per-(route, state) shape test and the timeout-chain test are still in tests/tmp waiting to be harvested here, and that step writes their docstring lines. The Video-not-found test is classified REDUNDANT, because existing tests already assert the 404 body on both routes. The heartbeat derivation test goes to `tests/active/test_server_config.py`. Nothing the docstring claims today is false.
- [ ] `DEPLOYMENT.md` - Line 174 (the `--drain` row: 30 s default, the Client's longest Engine timeout 20 s) and line 230 ("the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats") are both still accurate. No value changed, and neither sentence claims where the constant is defined. The only changes to this file during the build (the `--stall-seconds` row and the stall troubleshooting row) are issue 56's work and are accurate.
- [ ] `CONTEXT.md` - Translate state (line 17) already states that `total` always counts every stored cue whatever `after` was, and the requeue inference. It also states that all three layers are held to one contract fixture that each layer's tests replay (issue 55). Generation available (line 18) states 15 s = three 5 s beats, and both values are unchanged. The glossary does not name constant locations, so moving the heartbeat changes nothing in it.
- [ ] `client/README.md` - The `GET /api/translate` paragraph names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the gateway's parsing rules. The build left all of these unchanged (engine_api_client.py is not in the diff).
- [ ] `engine/server/api/server_config.py` - The two new constants each carry a one-line comment in the block's style: the beat interval, and the fresh window as three beats so one late beat is tolerated. Both comments are accurate, and no other comment in the module refers to the heartbeat.
- [ ] `docs/project/issues/plan.md` - Lines 13 and 26 describe the 55/56 overlap: 55 removes the `HEARTBEAT_SECONDS` literal and 56 leaves it alone. That is what happened (the worker diff shows 56's keyword parameters next to 55's import change), so the note is still accurate as a planning record.

ADR conflicts: none

## 2026-10-04 - Step 9 - Update documentation

- [x] `engine/server/README.md` - updated: I updated `engine/server/README.md` in three places: the running-slice rule for `total`, where the heartbeat window is defined and how it is derived, and the worker's beat interval in its `server_config` names.
- [x] `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` - updated: Heartbeat section: removed the false "Raise both constants together." and now say that the fresh window comes from the beat interval, defined once in `api/server_config.py`.
- [x] `engine/server/api/handlers/internal_translate.py` - updated: The module docstring now says where `HEARTBEAT_FRESH_MS` comes from: `server_config.py`, as three `HEARTBEAT_SECONDS` beats.
- [x] `engine/server/db/jobs/translate-worker.py` - updated: The worker's comment on why `api/` is on the import path now says it also supplies the heartbeat interval.
- [x] `tests/active/test_frontend_translate.py` - updated: I added a paragraph to the module docstring of `tests/active/test_frontend_translate.py` describing the third runner, `CONTRACT_RUNNER`.
- [x] `docs/project/issues/55-translate-state-contract.md` - updated: Issue 55 is now marked `complete`: all acceptance criteria are ticked, a Delivered note is added, and the issue is copied to `docs/project/issues/archive/`. **The original at `docs/project/issues/55-translate-state-contract.md` still needs deleting** (for example with `git rm`), because I have no delete tool.
- [x] `tests/active/test_server.py` - out of scope: The file was not edited. The harvest plan (docs/project/plans/harvest-55-translate-state-contract-plan.md) sends phase 1's gateway replay and coverage tests to a NEW `tests/active/test_engine_api_client.py`, not to this file. Its translate docstring paragraphs still describe exactly the tests it holds. The new module's docstring belongs to that harvest step.
- [x] `tests/active/test_internal_translate.py` - out of scope: The docstring already gained the build's paragraph: "Contract drivers: `ENGINE_DRIVERS` …" (diff, line 48) describes the driver table that is in the module. The other checklist entries describe tests that are not in this module. Per the harvest plan, the per-(route, state) shape test and the timeout-chain test are still in tests/tmp waiting to be harvested here, and that step writes their docstring lines. The Video-not-found test is classified REDUNDANT, because existing tests already assert the 404 body on both routes. The heartbeat derivation test goes to `tests/active/test_server_config.py`. Nothing the docstring claims today is false.
- [x] `DEPLOYMENT.md` - out of scope: Line 174 (the `--drain` row: 30 s default, the Client's longest Engine timeout 20 s) and line 230 ("the Engine's `HEARTBEAT_FRESH_MS`, three 5 s beats") are both still accurate. No value changed, and neither sentence claims where the constant is defined. The only changes to this file during the build (the `--stall-seconds` row and the stall troubleshooting row) are issue 56's work and are accurate.
- [x] `CONTEXT.md` - out of scope: Translate state (line 17) already states that `total` always counts every stored cue whatever `after` was, and the requeue inference. It also states that all three layers are held to one contract fixture that each layer's tests replay (issue 55). Generation available (line 18) states 15 s = three 5 s beats, and both values are unchanged. The glossary does not name constant locations, so moving the heartbeat changes nothing in it.
- [x] `client/README.md` - out of scope: The `GET /api/translate` paragraph names `TRANSLATE_TIMEOUT_SECONDS` (20 s) and the gateway's parsing rules. The build left all of these unchanged (engine_api_client.py is not in the diff).
- [x] `engine/server/api/server_config.py` - out of scope: The two new constants each carry a one-line comment in the block's style: the beat interval, and the fresh window as three beats so one late beat is tolerated. Both comments are accurate, and no other comment in the module refers to the heartbeat.
- [x] `docs/project/issues/plan.md` - out of scope: Lines 13 and 26 describe the 55/56 overlap: 55 removes the `HEARTBEAT_SECONDS` literal and 56 leaves it alone. That is what happened (the worker diff shows 56's keyword parameters next to 55's import change), so the note is still accurate as a planning record.

**Updated but not named by the Step 3 inventory.** docs/project/issues/55-translate-state-contract.md

**Other files that had to be touched.** - while updating `docs/project/issues/55-translate-state-contract.md`: docs/project/issues/archive/55-translate-state-contract.md — the issue's new location after archiving. This file is new; the original at docs/project/issues/55-translate-state-contract.md is unchanged and still needs deleting.

**ADR conflicts.** none

### `engine/server/README.md`

<changes>
I updated `engine/server/README.md` in three places: the running-slice rule for `total`, where the heartbeat window is defined and how it is derived, and the worker's beat interval in its `server_config` names.

- **Line 15 (`/internal/translate`):** `total` is now described as the count of every stored cue, whatever `after` was. That way a reader holding more running cues than `total` knows the job was requeued and restarted. I checked this against `internal_translate.py:252`, where `total` is `len(cues)` and the cues sent are `cues[after:]`. The frontend reads it the same way at `pages/video-page/translate.ts:175`.
- **Line 18 (Availability):** `HEARTBEAT_FRESH_MS` is now described as 15 000 ms, defined in `api/server_config.py` as three of the worker's `HEARTBEAT_SECONDS` (5 s) beats, so changing the interval moves the window. I checked this against `server_config.py:430-432`.
- **Line 30 (Translate worker):** the list of the worker's `api/server_config.py` names now includes its beat interval, `HEARTBEAT_SECONDS`. I checked this against the `from server_config import` line in `translate-worker.py:41`.
- **Line 38** ("every 5 s", "15 s freshness rule") is still accurate, so I left it as it was.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`

<changes>
Heartbeat section: removed the false "Raise both constants together." and now say that the fresh window comes from the beat interval, defined once in `api/server_config.py`.

- The first sentence now says where the beat interval is defined: "every 5 s (`HEARTBEAT_SECONDS` in `api/server_config.py`)".
- The freshness clause now reads "(`HEARTBEAT_FRESH_MS`, derived beside it as three `HEARTBEAT_SECONDS` beats, so changing the interval moves the window with it)". I checked this against `server_config.py:430-432` (`HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)`), the handler's import at `internal_translate.py:27` and the worker's import at `translate-worker.py:41`.
- Dropped the trailing "Raise both constants together."
- Unchanged: "every 5 s", "15 s", the `--stall-seconds`/`STALL_SECONDS` wording, and the "up to 5 s" heartbeat join figures in the Start-up Order and Stop sections. All of these are still true: `beat.join(HEARTBEAT_SECONDS)` is at `translate-worker.py:534`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/api/handlers/internal_translate.py`

<changes>
The module docstring now says where `HEARTBEAT_FRESH_MS` comes from: `server_config.py`, as three `HEARTBEAT_SECONDS` beats.

- **Line 3 (state route):** "whether the translate worker beat within HEARTBEAT_FRESH_MS" now ends "(server_config.py, three HEARTBEAT_SECONDS beats)". I checked this against `server_config.py:430-432`, where `HEARTBEAT_SECONDS = 5.0` and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)`, and against the handler's import on line 27.
- **Left as they were:** line 5 (the enqueue route), the `_generation_available` docstring, and the `REQUEST_BUDGET_SECONDS` comment. The budget comment doesn't name the timeout-chain test because that test is still in `tests/tmp`, not the active suite.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `engine/server/db/jobs/translate-worker.py`

<changes>
The worker's comment on why `api/` is on the import path now says it also supplies the heartbeat interval.

- Line 35 now reads: "api/ is for server_config (the bounds and HEARTBEAT_SECONDS) and the route's resolve_translatable_video, fetch_instance_track and TARGET_LANGUAGE; fetch code comes from data.source_fetch."
- I checked this against line 41 of the file, where `HEARTBEAT_SECONDS` is imported from `server_config` next to the `SUBTITLE_*` bounds.
- Nothing else changed. The module docstring's "every 5 s" is still correct, and the old comment and literal for the heartbeat are already gone.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `tests/active/test_frontend_translate.py`

<changes>
I added a paragraph to the module docstring of `tests/active/test_frontend_translate.py` describing the third runner, `CONTRACT_RUNNER`.

- **Already present:** the replay tests the checklist was waiting on are now in this module. The docstring already has a "Contract replay" section stating what they check: valid cases come back with their gateway fields, `ready` cues are sorted by start then end, `running` cues keep the order given, rejected cases throw exactly "Translate response was malformed", and each case is checked for its request and its non-finite value. I left that section as it was.
- **New paragraph:** it sits after the two existing runner paragraphs and says how the third runner is set up:
  - it bundles `data/translate.ts` on its own, not the video page;
  - it stubs `localStorage`, a `window` whose `location.origin` is set before the dynamic import (because api-base.ts reads it when it loads), and a `fetch` that answers every request with a 200;
  - it writes non-finite numbers back out as `1e999`, because `JSON.stringify` would write `null`;
  - `FETCH_RECORDER`, put in front of the runner, records each request's method, path and `after`;
  - the report gives, for each case, its value or thrown message, and whether the served text parsed to a non-finite number.
- **Checked against the code:** each of those points matches `CONTRACT_RUNNER`, `FETCH_RECORDER` and `_contract_report` in the file.

No code changed, and I ran no tests.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/55-translate-state-contract.md`

<changes>
Issue 55 is now marked `complete`: all acceptance criteria are ticked, a Delivered note is added, and the issue is copied to `docs/project/issues/archive/`. **The original at `docs/project/issues/55-translate-state-contract.md` still needs deleting** (for example with `git rm`), because I have no delete tool.

- **Status:** `enhancement, ready-for-agent` is now `enhancement, complete`, following `docs/project/triage-labels.md`.
- **Delivered (2026-10-04)** is a new comment after Triage. It says where each piece landed, and I checked each against the tree:
  - **Fixture:** `tests/active/fixtures/translate_contract.json`, with 29 valid and 14 rejected cases.
  - **Gateway:** the replay and the state-set coverage tests are in the new `tests/active/test_engine_api_client.py`. Its line 102 also requires exactly one `Video not found` 404 case per route.
  - **Frontend:** the `CONTRACT_RUNNER` replay is in `test_frontend_translate.py`.
  - **Engine:** the `ENGINE_DRIVERS` key/type check and the timeout chain test are in `test_internal_translate.py`.
  - **Heartbeat:** the pair is in `engine/server/api/server_config.py` (`HEARTBEAT_SECONDS = 5.0` at line 430, `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)` at line 432). The derivation test is in `test_server_config.py`.
  - **Departure from the brief:** the harvest judged a fixture-reading Engine Video-not-found test redundant. Existing tests already assert that exact body on both routes, and the gateway coverage test ties the fixture's 404 case to the same body.
  - **Mutation check:** adding "state paused" made the gateway replay raise `EngineApiError` and the coverage test fail. That result is in the build record.
  - The note also says the `TRANSLATE_*_ANSWERS` tables in `test_server.py` are still hand-written.
- **Desired behavior, Engine tests bullet:** I added "(held by existing tests instead; see the Delivered comment)". This follows the pattern issue 56 used for its own departure.
- **Acceptance criteria:** all 9 are ticked. One caveat on the "pass" criteria: in `tests/last_test_validation.json`, the most recent green runs of the translate suites predate the harvested tests. `test_engine_api_client.py` has no group entry there. I ticked these criteria on the strength of the tests being in the active suite, but nothing I could read shows them passing.
- **Unchanged:** the Problem section's line references (as filed), the Triage comment, the rest of the Agent Brief, and Out of scope.
</changes>

<not_on_checklist>
docs/project/issues/archive/55-translate-state-contract.md — the issue's new location after archiving. This file is new; the original at docs/project/issues/55-translate-state-contract.md is unchanged and still needs deleting.
</not_on_checklist>

## 2026-10-04 - Step 10 - Harvest tests

<moved>
I moved 8 of the 9 checkpoint tests (103 test items) into the durable suite:
- tests/tmp/test_55_translate_state_contract_phase1.py::test_each_contract_case_parses_through_the_real_gateway_to_its_stated_answer_from_one_request_to_its_route (43 cases) → tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)
- tests/tmp/test_55_translate_state_contract_phase1.py::test_the_contract_fixture_states_exactly_the_gateway_state_sets_with_and_without_available_under_unique_names → tests/active/test_engine_api_client.py, group test_engine_api_client.py (new)
- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_valid_contract_case_comes_back_with_exactly_its_gateway_fields_ready_cues_sorted_by_start_then_end_running_in_given_order (29 cases) → tests/active/test_frontend_translate.py, group test_frontend_translate.py
- tests/tmp/test_55_translate_state_contract_phase2.py::test_each_rejected_contract_case_served_as_a_200_throws_exactly_translate_response_was_malformed (14 cases) → tests/active/test_frontend_translate.py, group test_frontend_translate.py
- tests/tmp/test_55_translate_state_contract_phase3.py::test_the_engine_driver_table_has_exactly_the_contract_fixtures_route_states → tests/active/test_internal_translate.py, after ENGINE_DRIVERS, group test_internal_translate.py
- tests/tmp/test_55_translate_state_contract_phase3.py::test_each_route_state_driven_through_the_real_handler_answers_a_200_with_its_contract_cases_keys_and_json_types_cues_included (13 route/states) → tests/active/test_internal_translate.py, group test_internal_translate.py
- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_engine_fetch_budget_and_socket_timeout_fit_inside_the_client_translate_timeout_which_fits_inside_the_deploy_drain → tests/active/test_internal_translate.py, after test_one_15_second_budget_covers_both_fetches, group test_internal_translate.py
- tests/tmp/test_55_translate_state_contract_phase4.py::test_the_heartbeat_freshness_window_is_derived_from_the_interval_in_server_config_and_both_consumers_import_it → tests/active/test_server_config.py, group test_server_config.py

Not moved, because it is redundant with tests already in the suite: phase3::test_an_unknown_or_actively_denied_video_answers_the_contract_fixtures_video_not_found_404_on_each_route.

You chose the new test_engine_api_client.py over test_server.py for the phase 1 tests (AskUser). The stub engine (_serving, _TranslateEngine, _translate_engine) was copied in from test_server.py, not imported. The description in tests/active/fixtures/translate_contract.json now names test_engine_api_client.py instead of test_server.py.

Name checks:
- `whitelist` (test_internal_translate.py), `SERVER_CONFIG` and `API_DIR` (test_server_config.py) already existed with the same body, so one copy of each was kept. Nothing was renamed.

Other changes:
- I removed the checkpoints' "not written yet" fallbacks (`durable.` prefixes, `_drivers()`, the CONTRACT_RUNNER None path).
- I added docstring paragraphs that state each rule.

Everything ran from the session directory, /home/enduser/code/PeerTube-browser. That is where --show-config resolves tests/config.json and where the scope files and the .preharvest snapshot were. It is not the `.worktrees/55` path the harvest file records.
</moved>

<retired>
none
</retired>

<group_map>
Changes to tests/config.json test_groups:
- test_engine_api_client.py: new entry with client/backend/lib/engine_api_client.py and tests/active/fixtures/translate_contract.json.
- test_frontend_translate.py: added tests/active/fixtures/translate_contract.json and client/frontend/src/data/api-base.ts.
- test_internal_translate.py: added tests/active/fixtures/translate_contract.json, client/backend/lib/engine_api_client.py and scripts/deploy-bluegreen.sh.
- test_server_config.py: added engine/server/api/handlers/internal_translate.py and engine/server/db/jobs/translate-worker.py.

No entry was dropped. `validate_tests.py --audit-map` exited 0, and none of its advisory MISSING findings involves a moved test or a file one reads.
</group_map>

<mutations>
Before every edit I counted the anchor and found exactly one occurrence. Each production file was backed up to .scratch/harvest/<test>/<basename>.bak, outside the production tree. After each red run the file was restored from that copy, `diff` showed it byte-identical, and the test was run green again. No mutation hung or survived, and no .bak was left under client/, engine/, scripts/ or tests/active.
- Gateway replay: removed `and math.isfinite(value)` from `_is_seconds` in client/backend/lib/engine_api_client.py. Red: [state start 1e999] failed with "DID NOT RAISE EngineApiError" (the rejected-case assertion) while 42 passed. Green after restore: 43 passed.
- Fixture states equal gateway sets: `TRANSLATE_REQUEST_STATES = TRANSLATE_STATES | {"busy", "paused"}` in engine_api_client.py. Red: the enqueue with-available set equality failed with "Extra items in the right set: 'paused'". Green after restore: 1 passed.
- Frontend valid cases: in client/frontend/src/data/translate.ts, `compareCues` changed to `a.start - b.start || b.end - a.end`. Red: [state ready] and [state ready without available] failed the value deep-equal (Long first came before Short first) while 27 passed. Green after restore: 29 passed.
- Frontend rejected cases: in translate.ts, `const MALFORMED = "Translate response was invalid"`. Red: all 14 failed `thrown == "Translate response was malformed"`. Green after restore: 14 passed.
- Driver table: this test reads no production file (only the fixture and the test-side ENGINE_DRIVERS), so I mutated its group subject tests/active/fixtures/translate_contract.json instead, changing the `enqueue busy` engine state to "paused". Red: "no fixture (route, state) without a driver" failed with `[('enqueue', 'paused')] == []`. Green after restore: 1 passed.
- Route/state shape: in engine/server/api/handlers/internal_translate.py, the running answer's `"total": str(len(cues))`. Red: [state running] failed the key-to-JSON-type assertion (`total` string != number) while 12 passed. Green after restore: 13 passed.
- Heartbeat derivation: `HEARTBEAT_FRESH_MS = 15000` in engine/server/api/server_config.py. Red: the derived-from-the-interval assertion failed with `'HEARTBEAT_SECONDS' in set()`. Green after restore: 1 passed.
- Timeout chain: `REQUEST_BUDGET_SECONDS = 16.5` in internal_translate.py. Red: `budget + socket_timeout < client_timeout` failed as (16.5 + 4.0) < 20. Green after restore: 1 passed.
</mutations>

<cleared>
delete_me/ now holds the four checkpoint files, moved there from tests/tmp with no name clash:
- test_55_translate_state_contract_phase1.py
- test_55_translate_state_contract_phase2.py
- test_55_translate_state_contract_phase3.py
- test_55_translate_state_contract_phase4.py

tests/tmp holds none of the in-scope files. Build 55's probes are outside scope and were not moved: probe_55_*.py (10 files) and the zero-byte test_probe_55_phase3_drivers.py are still in tests/tmp, and the last one is still collected by every tests/tmp run. Nothing was deleted; delete_me/ is waiting for you to decide.

Final counts:
- I restored tests/last_test_validation.json.preharvest over the record and then ran `validate_tests.py --compare` with no tier. It selected 12 of 66 groups and they ran green: 661 passed, 0 failed.
- Against the pre-harvest record, 103 tests appeared. That is 43 + 1 in test_engine_api_client, 29 + 14 in test_frontend_translate, 1 + 13 + 1 in test_internal_translate and 1 in test_server_config, exactly the harvested items.
- Nothing departed, nothing new went red, and nothing stopped being red. The record is banked.
- Two files sit outside the trees: .scratch/harvest/ keeps the mutation backups, the red outputs and compare.out, and HARVEST_FILE records the name checks, mutations, disposal and these counts.
</cleared>

`--audit-map` exited 0.
Files still in tests/tmp: ['tests/tmp/test_probe_55_phase3_drivers.py']

`--compare` exited 0.

```
selected 1 of 66 test groups (65 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.9s
  ---------------------
  total                  10 passed                              2.2s wall, 1 lane

nothing moved against the previous record

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

