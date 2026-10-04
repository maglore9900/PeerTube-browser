# 55-translate-state-contract

_Rendered by the `dev-flow` workflow from its run state. Every edit here is overwritten on the next step; the evidence each gate turned on is in `docs/project/plans/01-55-translate-state-contract.record.md`._

## Requirements

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

## High-level plan

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

## Impacts

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

## Documentation to update

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

## Implementation plan

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

### Phases

#### Phase 1 - Contract fixture and Client gateway replay [code]

**Files touched.** tests/active/fixtures/translate_contract.json (NEW), tests/active/test_server.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Client gateway's parse functions, called directly. A new parametrized test in tests/active/test_server.py, one run per fixture case with the case name as id, starts the existing `_translate_engine` stub (test_server.py:1600) answering the case's engine status and body. It then calls `fetch_translate` (state route, passing the case's `after`) or `request_translate` (enqueue route). It asserts the result equals the case's `gateway` answer, or that `EngineApiError` was raised for "rejected". Control: the stub recorded exactly one request, on the case's /internal/translate route, carrying id, host and the case's `after`, so a rejection comes from the parse and not from a failed call. A second test reads the fixture and asserts: names are unique; there are exactly the two routes; `after` appears only on state cases; the valid 200 states equal TRANSLATE_STATES (state route) and TRANSLATE_REQUEST_STATES (enqueue route), both with and without `available`; each route has exactly one "Video not found" 404 case. Direct calls rather than /api/translate, so a 502 cannot hide why a case failed.

**Intent.** tests/active/fixtures/translate_contract.json states the translate contract. Every case parses through the Client gateway's real fetch_translate/request_translate to its stated answer, and the fixture's valid states are exactly the gateway's state sets.

- C1 - Every fixture case run through fetch_translate (state route, with its after) or request_translate (enqueue route) gives exactly its gateway answer, or raises EngineApiError when the case says rejected, from exactly one request to that route.
- C2 - The fixture's valid 200 states equal TRANSLATE_STATES on the state route and TRANSLATE_REQUEST_STATES on the enqueue route, each present with and without available, and every case name is unique.

**Outcome.** ### tests/active/fixtures/translate_contract.json (NEW, plus the new `tests/active/fixtures/` directory)
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

#### Phase 2 - Frontend parser replay [code]

**Files touched.** tests/active/test_frontend_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real client/frontend/src/data/translate.ts, entered through its exported fetchTranslate/requestTranslate. It follows test_frontend_translate.py's existing esbuild-bundle-plus-node-runner harness (same --platform=node, ESM and import.meta.env defines). A module fixture bundles translate.ts on its own. CONTRACT_RUNNER stubs window, localStorage and a fetch that answers 200 with the served text, reads the fixture with fs, and in one node process serves each case: the gateway answer for a valid case, the Engine body for a rejected one. It reports the returned value or the thrown message, plus whether the parsed text contained a non-finite number. The parametrized Python test asserts that a valid case deep-equals its gateway answer, with ready cues re-sorted by (start, end) and running cues left in the order given, and that a rejected case threw exactly "Translate response was malformed", so a JSON SyntaxError cannot pass as a refusal. Control on every case: the parser read a non-finite number exactly where the fixture writes 1e999. No frontend file changes.

**Intent.** data/translate.ts is proven against every case of the contract fixture. Valid gateway answers come back with their fields intact, and every rejected body is refused as malformed.

- C1 - Every valid fixture case served to fetchTranslate or requestTranslate comes back with exactly its gateway fields: ready cues sorted by start then end, running cues in the order given.
- C2 - Every rejected fixture case served as a 200 throws exactly "Translate response was malformed".

**Outcome.** ### tests/active/test_frontend_translate.py
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

**Beyond the files named.** tests/tmp/probe_55_phase2_runner.py — a throwaway probe I used to watch the runner's real output. I emptied it because I have no tool to delete files; it can be deleted.

#### Phase 3 - Engine answers match the fixture's shape [code]

**Files touched.** tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the Engine's /internal/translate and /internal/translate/enqueue handlers, entered through test_internal_translate.py's existing harness (`_route`, `_state`, `_enqueue`, `_server`, `_seed`, `_claimed`, `_beat`, `_instance`). The fixture is read inside each test, never at module level, because test_source_fetch.py imports this module. A static ENGINE_DRIVERS table keyed by (route, state) drives each state: seeded rows with a fresh beat and no instance track on the state route; on the enqueue route, no beat for none, no row for queued, a seeded stored state, or a queue filled to SUBTITLE_QUEUE_CAP for busy. The parametrized test asserts, for each fixture case that carries available: a 200; answer state equals the state under test (control); the key-to-JSON-type map equals the case's (bool before number); cues non-empty where the case's are; and each answered cue's keys and types match the case's cues. A separate test asserts that the fixture's (route, state) set equals the driver table's keys, both ways. The not-found test asserts that on both routes an unknown video and an actively denylisted video answer exactly the fixture's Video-not-found 404 body with no fetch, and as a control that the same denied video answers 200 once the deny is inactive.

**Intent.** The Engine's two translate routes are checked against the contract fixture. Each (route, state) it produces answers the fixture case's keys and JSON types, and its not-found answer is the fixture's body.

- C1 - Each (route, state) among the fixture's valid 200 cases that carry available, driven through the real handler, answers a 200 with exactly that case's key set and value JSON types, its cues included, and no fixture state is without a driver nor any driver without a fixture state.
- C2 - On both routes, an unknown video and an actively denylisted video answer exactly the fixture's Video not found 404 body.

**Outcome.** ### tests/active/test_internal_translate.py
I added `ENGINE_DRIVERS`, the table the checkpoint looks up. It has 13 entries, keyed by (route, state): `none`, `queued`, `running`, `ready`, `already_english` and `failed` on the state route, and the same six plus `busy` on the enqueue route. I put it right after `_state`, with its two driver factories and one small helper. Each driver is called as `(subtitles_path, whitelist, monkeypatch, case)` and returns what the route's real handler wrote. It reaches the handler through `_state` or `_enqueue`, which look the handler up on the module when they run, so the checkpoint's recorder sees the call. All data goes in through the existing harness: `_seed`, `_claimed`, `_beat`, `_route`, `_server`, and the store's own writers. The only thing patched is `_route`'s usual `build_opener` and `now_ms`, which answers the shape audit's driver-side-patching recommendation.
- **`_state_driver(row)`:** seeds the key as `row` and writes a fresh beat, then calls the state route with `_instance(False)`. Without that no-track instance, `failed`, `already_english` and `none` would answer `ready`. The request carries the case's `after` exactly when the case has one.
- **Running on the state route:** the driver stores as many cues as the case's `total`, built by `_running_cues(count)` in descending start order. So `state running after 3` answers two real cues, not the `[]` that `RUNNING`'s three cues would give.
- **`_enqueue_driver(row)`:** `None` means no beat, which answers `none`. `"no row"` with a beat answers `queued`. A seeded stored state answers that state. `"busy"` fills the queue to `SUBTITLE_QUEUE_CAP` with other keys, as the existing full-queue test does.
- **Docstring:** a new "Contract drivers" paragraph before "Startup:" says what the table does and that the fixture is never read at module level, because `test_source_fetch.py` imports this module.
- **Probe:** a throwaway probe ran every driver against all 14 fixture cases that carry `available`. Each came back as exactly one 200 in the state under test, with the keys the case has. `state running` gave 3 cues and total 3. `state running after 3` sent `after` 3 and gave 2 cues and total 5. `state ready` gave the stored `STORED_READY` cue. `enqueue none` gave `available: false`; the fixture's case says `true`, but both are booleans, so the type check still passes, and the fixture's description already notes this. I did not run the checkpoint itself.
- **Probe file:** I have no tool to delete it, so I emptied `tests/tmp/test_probe_55_phase3_drivers.py`. It can be deleted.

### tests/config.json (not edited)
I left it unchanged, as phases 1 and 2 did. The planned group entries are the fixture plus `translate-worker.py`, `engine_api_client.py` and `deploy-bluegreen.sh`. Nothing in the durable module reads any of those files yet: the drivers get each case passed in. The entries belong with the step that moves the checkpoint's fixture-reading tests into the active suite, or with phase 4's derivation and timeout-chain tests.

#### Phase 4 - Single-sourced heartbeat and checked timeout chain [code]

**Files touched.** engine/server/api/server_config.py (EDITED), engine/server/api/handlers/internal_translate.py (EDITED), engine/server/db/jobs/translate-worker.py (EDITED), tests/active/test_internal_translate.py (EDITED), tests/config.json (EDITED)

**Checkpoint.** Seam: the real constants, with server_config.py's source as the derivation's front door. Two tests in test_internal_translate.py. (1) Heartbeat: ast-parse engine/server/api/server_config.py and find the single HEARTBEAT_FRESH_MS assignment. Assert its expression names HEARTBEAT_SECONDS. Evaluate it with the real interval (equals the module's value, 15000, an int) and with 7.0 (21000). Assert the handler module's HEARTBEAT_FRESH_MS is server_config's. Assert neither internal_translate.py nor translate-worker.py assigns HEARTBEAT_SECONDS or HEARTBEAT_FRESH_MS, and that each imports its name from server_config. (2) Timeout chain, placed after test_one_15_second_budget_covers_both_fetches: take the handler's REQUEST_BUDGET_SECONDS, data.source_fetch.SOCKET_TIMEOUT_SECONDS and lib.engine_api_client.TRANSLATE_TIMEOUT_SECONDS (conftest supplies client/backend on sys.path). Read DRAIN_SECONDS from scripts/deploy-bluegreen.sh with a line-anchored regex that must match exactly once. Assert budget + socket < Client timeout < drain. The existing BEATS 15000/15001 edge tests and test_translate_worker.py, both unchanged, confirm behaviour is preserved.

**Intent.** The heartbeat interval and its freshness window are defined once in server_config.py, the window derived from the interval and imported by both consumers, and the translate timeout chain across Engine, Client and deploy script is held in order by a test.

- C1 - server_config.py's HEARTBEAT_FRESH_MS is derived from HEARTBEAT_SECONDS, and internal_translate.py and translate-worker.py import their heartbeat name from server_config instead of assigning a literal of their own.
- C2 - REQUEST_BUDGET_SECONDS plus SOCKET_TIMEOUT_SECONDS is below the Client's TRANSLATE_TIMEOUT_SECONDS, which is below deploy-bluegreen.sh's DRAIN_SECONDS default.

**Outcome.** ### engine/server/api/server_config.py
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

**Beyond the files named.** tests/tmp/probe_55_phase4_impl.py: a throwaway probe created to observe the imported values. I have no delete tool, so it is still there and should be removed.


