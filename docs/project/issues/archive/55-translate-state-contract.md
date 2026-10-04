# Declare the translate state contract once

Status: enhancement, complete
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "one declared translate state contract" (Worth exploring)

## Problem

The Translate state contract is derived separately in the Engine, the Client gateway and the frontend. The contract covers the states, the `available` default, the cue shape, `after`/`total`, and "video not found" meaning `none`.

- The state sets are `client/backend/lib/engine_api_client.py:21-23` and `client/frontend/src/data/translate.ts:11-20`. The Engine's set is implicit in its branches (`engine/server/api/handlers/internal_translate.py:290-308`).
- "A missing `available` reads as false" appears in `engine_api_client.py:161-166` and `translate.ts:110-115`. Cue validation appears in `engine_api_client.py:156-178` and `translate.ts:117-123`.
- Cue sorting is written four times: `internal_translate.py:183`, `engine/server/db/jobs/translate-worker.py:424`, `translate.ts:101` and `client/frontend/src/pages/video-page/translate.ts:181`.
- `VIDEO_NOT_FOUND` (`internal_translate.py:40`) is matched as a string in another process (`engine_api_client.py:19-20, 187, 208`).
- The page's requeue detection, `state.total < runningHeld` (`video-page/translate.ts:175`), depends on how the Engine slices running cues. That behaviour is not documented.
- `HEARTBEAT_SECONDS` (`translate-worker.py:60-61`) and `HEARTBEAT_FRESH_MS` (`internal_translate.py:37-38`) are tied together only by comments. The timeout chain is the same: the Client's 20 s, the Engine's budget plus socket timeout, and the deploy's 30 s drain.

The Client's re-validation at the trust boundary is deliberate and should stay. What's missing is one place that says what every layer validates against.

## Proposed solution

Declare the contract once, either as a schema or as a small shared definition that tests check every layer against. Put the heartbeat pair in one constant that both the Engine and the worker import. Keep each layer's own validation. The form is not decided yet.

## Related

- `CONTEXT.md`: Translate state, Generation available.
- `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`.

## Comments

**Triage (2026-10-04).** The code claims above were checked against the tree, and all of them hold. Nothing declares the contract today, and there are no prior rejections. The README's boundary guard forbids the Client backend from importing Engine modules, and the frontend is TypeScript, so the contract cannot be shared runtime code. The maintainer chose a **contract fixture file**: one checked-in JSON file of cases, each giving the Engine's status and body and the gateway's answer or a rejection. The Client's tests and the frontend's tests replay every case, and the Engine's tests check that its answers match the valid cases. Each layer keeps its own runtime validation. The running-slice rule (`total` counts every stored cue) is now in `CONTEXT.md` under Translate state.

**Delivered (2026-10-04).** The fixture is `tests/active/fixtures/translate_contract.json`: 29 valid and 14 rejected cases, read by tests only. `tests/active/test_engine_api_client.py` replays every case through the real `fetch_translate`/`request_translate`, and holds the fixture's valid states equal to `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (with and without `available`), with exactly one `Video not found` 404 case per route. `tests/active/test_frontend_translate.py` replays every case through `data/translate.ts` under `CONTRACT_RUNNER`. `tests/active/test_internal_translate.py` drives each (route, state) through `ENGINE_DRIVERS` and checks keys and JSON types, and holds the timeout chain. The heartbeat pair lives in `engine/server/api/server_config.py`: `HEARTBEAT_SECONDS = 5.0` and `HEARTBEAT_FRESH_MS = int(HEARTBEAT_SECONDS * 3 * 1000)`, imported by both the state route and the worker. `tests/active/test_server_config.py` checks the derivation. One departure from the brief: no Engine test reads the fixture's 404 body. The harvest judged it redundant, because existing `test_internal_translate.py` tests already assert exactly `{"error": "Video not found"}` for an unknown video and a denylisted one on both routes, and the gateway coverage test holds the fixture's 404 case to that same body. The new-state mutation ("state paused" added to the fixture alone) was run once during the build: the gateway replay raised `EngineApiError` and the coverage test failed. The result is in the build record. The `TRANSLATE_*_ANSWERS` tables in `test_server.py` are still hand-written.

## Agent Brief

**Category:** enhancement
**Summary:** Declare the translate state contract once, as a contract fixture that the Engine, Client gateway and frontend tests all check against. Give the heartbeat pair one Engine-side definition, and turn the timeout chain into a test. Runtime behaviour does not change.

**Current behavior:**
Two answers are under contract: the Engine's `/internal/translate` (state read) and `/internal/translate/enqueue` (generation request), as the Client gateway re-validates them and the frontend parses the gateway's `/api/translate` GET and POST. Each layer derives the contract on its own:
- **The Client backend** names `TRANSLATE_STATES` and `TRANSLATE_REQUEST_STATES` (adding `busy`). It reads a missing `available` as `false`, checks each cue as finite `start` and `end` plus string `text`, requires a non-negative non-bool integer `total` for `running`, and maps an Engine 404 whose `error` is exactly `Video not found` to `{state: none, available: false}`. It matches that string by copy.
- **The frontend** declares the `TranslateState` and `TranslateRequestState` types and a `REQUEST_STATES` list. It repeats the `available` default and the cue checks, and sorts `ready` cues by start then end.
- **The Engine** names no state set; its states exist only as branches of the state route. It sorts cues by `(start, end)` in two places: when parsing an instance track, and when the worker finishes a job.
- **The video page** treats a `running` answer whose `total` is below the number of running cues it holds as a requeue. This relies on the Engine returning `cues[after:]` with `total` counting every stored cue, which no document states.
- **The heartbeat.** The worker beats every `HEARTBEAT_SECONDS` (5 s), and the route treats a beat as fresh within `HEARTBEAT_FRESH_MS` (15 s). They are tied together only by comments.
- **The timeout chain.** The Client's translate timeout (20 s) must exceed the Engine's request budget plus one socket timeout (15 s + 4 s), and the blue/green deploy's default drain (30 s) must exceed the Client's timeout. These are also tied together only by comments.

**Desired behavior:**
- **The fixture.** One contract fixture file lives outside every runtime package and is read only by tests. It holds named cases for both routes. Each case is an Engine HTTP status and JSON body, plus either the gateway's normalised answer or a rejection. It covers at least:
  - every state of each route, with and without `available`;
  - `ready` and `running` cue lists, including a `running` answer sliced by `after` with its `total`;
  - the `Video not found` 404 for both routes, read as `none` and not available, and a different 404 rejected;
  - rejections: an unknown state, a non-bool `available`, a non-list `cues`, a cue with a non-finite or bool time or a non-string text, and a negative or bool `total`.
- **Client backend tests** replay every case through the gateway's Engine-answer parsing for that route and assert the fixture's expected answer or rejection.
- **Frontend tests** replay every valid case's gateway answer through the frontend's state and request parsers and assert it is accepted with the same fields, with `ready` cues sorted by start then end. They also offer every rejected case's Engine body as a 200 gateway answer and assert it is refused.
- **Engine tests** drive the state and enqueue routes into each state and assert every answer has exactly the keys and value types of the fixture's valid case for that state. They also assert that the state route's 404 for an unknown or denied video is the fixture's `Video not found` body (held by existing tests instead; see the Delivered comment).
- **Prose.** The running-slice rule (`cues` from `after` on, `total` counting every stored cue) is stated next to the route in the Engine server README.
- **The heartbeat pair** comes from one Engine-side definition. The fresh window is derived from the beat interval (three beats), and both the state route and the worker import it. Neither keeps its own literal.
- **The timeout chain** is checked by one test that reads the Client's translate timeout, the Engine's request budget and socket timeout, and the deploy script's default drain. It fails when any link breaks the ordering budget + socket < Client timeout < drain. Reading another layer's value in a test is allowed; importing it at runtime is not.

**Key interfaces:**
- The fixture shape is up to the agent. One JSON file with a `cases` list of `{name, route, engine: {status, body}, gateway: <answer> | "rejected"}` is enough.
- No runtime module is shared across the Engine, the Client backend and the frontend. Each layer's state lists, `available` default, cue checks and not-found mapping stay where they are.
- The heartbeat definition lives in an Engine module that both the API and the jobs already import, not in a route handler.

**Acceptance criteria:**
- [x] One contract fixture covers every state of both routes and every rejection listed above, and nothing at runtime reads it.
- [x] The Client backend's tests replay every fixture case through both route parsers and pass.
- [x] The frontend's tests replay every fixture case through both parsers and pass.
- [x] The Engine's tests check each state's answer against the fixture's valid case for that state, and check the not-found body.
- [x] Adding a new state to the fixture alone, with no layer changed, makes at least one layer's tests fail. Check this once by hand, as a mutation.
- [x] The worker's beat interval and the route's fresh window come from one definition, and changing the interval changes the window.
- [x] One test asserts budget + socket < Client translate timeout < deploy default drain from the real values, and fails when any one of them is moved past its neighbour.
- [x] The Engine server README states the running-slice rule beside `/internal/translate`.
- [x] No runtime behaviour changes: every existing translate route, Client gateway, frontend translate and translate worker test passes unchanged, apart from tests rewritten to read the fixture.

**Out of scope:**
- Removing or merging any layer's runtime validation. The Client's re-validation at the trust boundary stays, by decision.
- Generating code or types from the fixture, or adding a schema validator dependency.
- Changing any state, field, timeout or heartbeat value.
- Deduplicating the cue sorts across layers. The two Engine sorts may share one Engine helper, but this is not required.
- The fetch adapter (issue 53), the job handle (issue 54) and the worker split (issue 56).
