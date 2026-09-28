# Build record - 11-fast-similars-response

Written by the `dev-flow` workflow. The plan it accompanies is `docs/project/plans/19-11-fast-similars-response.md`.

**Nothing but the workflow writes this file.** It carries the evidence each gate turned on: the baseline, both auditor verdicts verbatim, every self-check table, every red and its reason, every checkpoint outcome, and every amendment the operator approved to a settled section of the plan.

## Run state

<!-- dev-flow:state
```json
{
  "version": 1,
  "request": "# Fast response with similars on the video page\n\nStatus: enhancement, needs-triage\nOrigin: task 1, [M2][F1]\n\n## Problem\n\nUntil the server receives a response from the source instance, the client shows an empty page; some instances respond slowly.\n\n## Proposed solution\n\nShow similar videos first (fast, from the local DB), then load the current video's metadata when it arrives.\n\n- Opening the video page starts two independent requests in parallel: similars, and metadata for the current video.\n- The server answers the similars request immediately from local cache/DB, without waiting for the instance.\n- Metadata refresh goes through a separate request to the instance, is saved to the DB, and updates the UI.\n\n## Related\n\n- After `09-similars-diversity`; before `12-similars-on-scroll`.\n\n## Comments",
  "request_source": "read from docs/project/issues/11-fast-similars-response.md",
  "slug": "11-fast-similars-response",
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
    "9": "done"
  },
  "phases": [
    {
      "n": "1",
      "kind": "code",
      "name": "Engine refresh route",
      "checkpoint": "Seam: the Engine's HTTP handler over a real DB. New `tests/active/test_video_metadata.py` runs each case in an `ENGINE_PY` child over a temporary DB, following the `subprocess.run([str(ENGINE_PY), \"-c\", CHILD, ...], cwd=API_DIR)` pattern of `test_similar.py` / `test_internal_events.py`. The child builds a real `SimilarServer` carrying `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`, and patches `handlers.video.fetch_instance_json` with a recording stub (never the shared `engine` fixture). It asserts over GET `/api/video/refresh`: (a) with the stub answering detail + channel JSON, the response carries today's response keys with the instance's values, `accountAvatarUrl` included, the channel URL built from slug + host and the original URL from uuid + host. (b) With the detail JSON omitting fields (e.g. no `description`, no `tags`) and the channel sub-call answering `None`, those fields and the channel fields come from the seeded DB row. Guards: 400 `Missing video id` with no id, and 404 `Video not found` for an unknown id; and `/api/video` against the same answering stub still returns the instance's values (today's live behaviour kept until the follow-up plan).",
      "intent": "`engine/server/api/handlers/video.py` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`, and a new `handle_video_refresh_request`, dispatched from `SimilarHandler`'s GET branch in `similar.py`, answers `/api/video/refresh` with the instance's live values merged over the DB row field by field, while `/api/video` keeps today's live behaviour through the same functions.",
      "clauses": [
        {
          "id": "C1",
          "text": "`/api/video/refresh` answers the instance's live values in today's `/api/video` response shape."
        },
        {
          "id": "C2",
          "text": "A field the instance did not supply in a refresh falls back to the DB row's value."
        }
      ],
      "files": [
        "engine/server/api/handlers/video.py (EDITED)",
        "engine/server/api/handlers/similar.py (EDITED)",
        "engine/server/api/handlers/__init__.py (EDITED)",
        "tests/active/test_video_metadata.py (NEW)"
      ],
      "done": true,
      "outcome": "### engine/server/api/handlers/video.py\n- `handle_video_request` is split into three module-level functions. The merge rules and SQL are the same as before; only their location changed.\n  - `resolve_video_row(handler, server, params)` reads `id`/`video_id` and `host`/`instance_domain` and answers 400 `Missing video id` or 404 `Video not found`. Otherwise it returns `(row, id_param, instance_domain)`. `db_lock` is still held only around the SELECT.\n  - `merge_video_metadata(row, dynamic, instance_domain)` returns `(response, merged)`. `response` has the same eighteen `/api/video` keys as before, and a field the instance left out falls back to the row, field by field. Title and description use `or`; the numbers use `is None`, so a supplied `likes: 0` is kept. `merged` holds the raw values (`None` included), so the write stores `NULL` rather than the response's `\"\"`.\n  - `persist_video_metadata(server, row, instance_domain, merged)` holds the three UPDATEs (videos, channels, instances), the popularity calculation and the logged `sqlite3.OperationalError` catch. It reads its values from `merged`. The argument order follows the Step 5 draft, so Phase 2 can add its statement deadline there.\n- New `handle_video_refresh_request` runs resolve, then `fetch_instance_video_dynamic` (by the requested id, outside the lock), then merge, then persist under the same `if dynamic and instance_domain and row.get(\"video_id\")` guard as before, then answers 200.\n- `handle_video_request` keeps its name and passes the request to `handle_video_refresh_request`, so `/api/video` behaves as before: it calls the instance live and writes to the DB.\n  - A `rat-tail:` comment says what's left: `/api/video` still makes the instance call and the write, and the follow-up plan makes it DB-only by answering `merge_video_metadata(row, {}, instance_domain)` with no fetch and no write.\n  - Phase 1 did not touch the `{}`-on-failed-detail success signal in `fetch_instance_video_dynamic`; that is Phase 2's clause.\n- Module docstring updated to cover both routes and the persist step.\n\n### engine/server/api/handlers/similar.py\n- The import now reads `from handlers.video import handle_video_refresh_request, handle_video_request`.\n- New branch in `_dispatch_get`: `if url.path == \"/api/video/refresh\": handle_video_refresh_request(self, self.server, params)`, placed after the `/api/video` branch. It gets the existing `/api/` rate limit (its own per-path bucket) and the statement deadline in `do_GET`.\n- A `/api/video/refresh` line is added to the docstring's list of routes.\n\n### engine/server/api/handlers/__init__.py\n- The `video` module line in the docstring now names both routes.\n\n### tests/active/test_video_metadata.py\n- Not written. This path is where the gated checkpoint `tests/tmp/test_11_fast_similars_response_phase1.py` gets promoted to; I did not touch the checkpoint or write a copy of it.\n\n### Not run\n- I did not run the checkpoint; the workflow's run is the one that counts.\n- I expect it to go green because the checkpoint's own probe showed today's `/api/video` returning exactly the expected bodies with the same stubs, and the refresh route now runs that same merge.\n\n### Leftovers in tests/tmp\n- The earlier authoring turns left `tests/tmp/probe_11_video_metadata.py` and `tests/tmp/probe_11_remediation.py` in place. I didn't touch them and have no tool to delete them, so they still need removing."
    },
    {
      "n": "2",
      "kind": "code",
      "name": "Refresh persists only on instance success",
      "checkpoint": "Seam: the same `ENGINE_PY`-child harness in `tests/active/test_video_metadata.py`, going through the HTTP handler and reading the DB afterwards. (a) Persist on success: the stub answers detail JSON, and after `/api/video/refresh` the `videos`, `channels` and `instances` rows hold the instance's values, with `instances.last_error*` NULL. A failed channel sub-call still persists, with the DB channel fields. With `statement_timeout_seconds` about 0.2 and a stub that sleeps 0.5 s before answering, the rows are still updated. (b) No write on failure: parametrized over a detail answer of `None`, `{}`, a JSON list, and a raised `URLError`. Each answers 200 with the DB values, and the `videos`, `channels` and `instances` rows (including `last_checked_at` and `last_error`) are identical before and after. (c) R7: with a stub that blocks about 5 s, a refresh is started on a thread; the id-based similars GET then returns 200 in well under 5 s, and the stub's call log holds only the refresh's `/api/v1/videos/...` paths.",
      "intent": "`fetch_instance_video_dynamic` returns `{}` when the video detail call did not answer, so `handle_video_refresh_request` writes the merge through `persist_video_metadata`, under its own statement deadline, only when the instance answered, and its instance calls run outside `db_lock`, so a slow refresh leaves the similars route answering.",
      "clauses": [
        {
          "id": "C1",
          "text": "A refresh updates the videos, channels and instances rows only when the instance's video detail call answered."
        },
        {
          "id": "C2",
          "text": "A refresh blocked on a slow instance does not delay the similars route's answer."
        }
      ],
      "files": [
        "engine/server/api/handlers/video.py (EDITED)",
        "tests/active/test_video_metadata.py (EDITED)"
      ],
      "done": true,
      "outcome": "### `engine/server/api/handlers/video.py`\n- `fetch_instance_video_dynamic` now returns `{}` when the video detail call didn't answer. That covers `None` (which includes `URLError`/`HTTPError`/timeout, since `fetch_instance_json` already catches those), an empty object, and any non-dict JSON. Before, a JSON list crashed on `detail.get` and dropped the connection, and `None` or `{}` produced a dict of `None`s. That dict counts as true, so `handle_video_refresh_request`'s existing `if dynamic and ...` guard went ahead and wrote anyway. Now that guard really does limit the write to refreshes the instance answered (C1). A failed refresh still answers 200 with the DB-only values, through `merge_video_metadata(row, {}, ...)`.\n- `persist_video_metadata` now runs its write under its own `statement_deadline(server.statement_timeout_seconds)`, falling back to `DEFAULT_STATEMENT_TIMEOUT_SECONDS`. The deadline is entered just before `db_lock`. The request's deadline from `do_GET` has usually been used up waiting on the instance, so an UPDATE long enough to reach the progress handler used to get interrupted and logged, and nothing was saved. `statement_deadline` puts the request's own deadline back on exit. New imports: `statement_deadline` from `data.db` and `DEFAULT_STATEMENT_TIMEOUT_SECONDS` from `server_config`. `similar.py` already uses both from the same places.\n- C2 needed no code change. The instance calls already ran outside `db_lock`: `resolve_video_row` takes the lock only for the row read, and `persist_video_metadata` takes it only for the write. I didn't observe this with a run; the checkpoint run will confirm it.\n- I updated the module docstring's persist line to say the write happens only when the detail call answered.\n\n### `tests/active/test_video_metadata.py`\nI didn't touch it. It doesn't exist in the worktree yet. I take this to be where the checkpoint (`tests/tmp/test_11_fast_similars_response_phase2.py`) will be moved; it isn't a file for me to write."
    },
    {
      "n": "3",
      "kind": "code",
      "name": "Client proxy for the refresh route",
      "checkpoint": "Seam: the Client backend's HTTP proxy in front of a stub Engine. Added to `tests/active/test_server.py`, using its `EngineStub(BaseHTTPRequestHandler)` + `_serving(ThreadingHTTPServer(...))` + `_client_backend(tmp_path, engine_base, RateLimiter(1000, 60))` + `_status` harness (precedent: `test_engine_receives_the_resolved_address_as_x_client_ip`). (a) GET `/api/video/refresh?id=\u2026&host=\u2026` reaches the stub with exactly those two params. Adding `user_id`, adding `refresh_cache`, or repeating `id` each answers 400, and the stub records no request. (b) With `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` monkeypatched to about 0.3 s for the refresh and a stub that sleeps past it, the browser gets 502 and the stub counts exactly one refresh GET. Guard: `/api/video` against the same sleeping stub (with `ENGINE_PROXY_TIMEOUT_SECONDS` patched small) counts two attempts.",
      "intent": "`client/backend/server.py` proxies `/api/video/refresh` as a read route with its own `{id, host}` allow-list, and `_proxy_engine_request` gives it a 20 s timeout and zero retries through the per-path mappings while every other route keeps 10 s and one retry.",
      "clauses": [
        {
          "id": "C1",
          "text": "The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400."
        },
        {
          "id": "C2",
          "text": "A refresh that times out at the proxy is sent to the Engine once and answered 502."
        }
      ],
      "files": [
        "client/backend/server.py (EDITED)",
        "tests/active/test_server.py (EDITED)"
      ],
      "done": true,
      "outcome": "### client/backend/server.py\n- `/api/video/refresh` added to `PROXY_READ_GET_ROUTES`. It now goes through the same rate limit and the same `_handle_engine_read_proxy_get` sanitising as the other GET read proxies: an unknown key or a repeated key gets 400, and values are stripped.\n- New `PROXY_ALLOWED_QUERY_PARAMS[\"/api/video/refresh\"] = {\"id\", \"host\"}`. The `/api/video` entry is unchanged and keeps `refresh_cache` and `user_id`.\n- Two new per-path mappings sit next to the shared constants, with a one-line comment saying why the refresh differs:\n  - `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS = {\"/api/video/refresh\": 20}`\n  - `ENGINE_PROXY_ROUTE_RETRY_COUNT = {\"/api/video/refresh\": 0}`\n- `_proxy_engine_request` looks up `timeout_seconds` and `retry_count` once per request from these mappings. The lookup is keyed on `path`, not `upstream`, which carries the query string. Any path not in a mapping falls back to `ENGINE_PROXY_TIMEOUT_SECONDS` / `ENGINE_PROXY_RETRY_COUNT`. Both are module globals read at call time, which lets a test patch them.\n- All four sites that used the shared constants now read the locals: the retry loop's `range`, the `urlopen` timeout, the retry check `attempt < retry_count`, and the `\"attempts\"` field of the \"proxy request unavailable\" log.\n- Result: the refresh gets 20 s and no retry, and a transport timeout on it is answered 502 `ENGINE_PROXY_UNAVAILABLE` after one send. Every other proxied route still gets 10 s and one retry."
    }
  ],
  "digests": {
    "tests/tmp/test_11_fast_similars_response_phase1.py": "4224bf950a54e696ab1dff9aebf9f68580c384e7016dd3eac1a1630a61dd68cc",
    "tests/tmp/test_11_fast_similars_response_phase2.py": "275ed42c4f9d17c0c680538fe92a1d8576e2f267370f72abf11a9da4bf272a53",
    "tests/tmp/test_11_fast_similars_response_phase3.py": "838438bf3ff149795a011783654f350deeeb2d126f0f9c3937f3d6e40bc21259"
  },
  "paths": {
    "active": "tests/active",
    "working": "tests/tmp",
    "plans": "docs/project/plans",
    "delete_me": "delete_me",
    "archive": "tests/archive",
    "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/11",
    "record": "tests/last_test_validation.json",
    "output": "tests/last_test_output.txt"
  },
  "baseline": {
    "code": 0,
    "variant": false
  },
  "sessions": [
    "20260927T195923-da37-dev-flow"
  ],
  "plan": "docs/project/plans/19-11-fast-similars-response.md",
  "record": "docs/project/plans/19-11-fast-similars-response.record.md",
  "replies": {
    "step_1_gather_requirements": "<requirements>\n### Purpose\n\nNothing on the video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) waits on the source PeerTube instance. Similar videos and the current video's stored metadata render immediately from the Engine's local DB; a separate refresh request fetches live metadata from the instance, persists it to the Engine DB, and updates the page when it arrives. Operator chose the \"two-phase metadata\" reading of the issue.\n\n### Findings from the tree that shape this build\n\n- The page already starts `loadVideo()` and `loadSimilarVideos()` in parallel, and the similars route (`/recommendations`, proxied by `client/backend/server.py` to the Engine's `_handle_similar` in `engine/server/api/handlers/similar.py`) is served from ANN/cache/DB without contacting the instance. Both the Client backend and the Engine are `ThreadingHTTPServer`, so the two requests do not serialise. The \"similars first\" part of the issue is therefore already mostly true; what stays empty is the current video's own panel.\n- `loadVideo()` renders nothing until metadata arrives. The Engine's `handle_video_request` (`engine/server/api/handlers/video.py`) reads the DB row, then synchronously calls the instance (`fetch_instance_video_dynamic`: `/api/v1/videos/{id}` then `/api/v1/video-channels/{slug}`, `timeout=8` each), merges, writes the DB, then responds. The Client backend proxy (`ENGINE_PROXY_TIMEOUT_SECONDS = 10`) can time out first, after which the browser falls back to `fetchVideoMetadataFromInstance` (another instance wait). Even on success, `fetchVideoMetadataFromServer` awaits the browser-side `fetchInstanceMetadata` (`https://{host}/api/v1/config`) before rendering.\n- The DB row (`fetch_video_row`) already holds title, description, embed_path, video_url, channel (name/url/display name/followers/avatar), account name/url, views, likes, dislikes and published_at: enough to render the panel immediately.\n- The Client backend allow-list `PROXY_ALLOWED_QUERY_PARAMS[\"/api/video\"]` already lists `refresh_cache`, which the Engine's video handler ignores today.\n\n### R1 - Fast metadata from the DB\n\nThe Engine's `GET /api/video` answers from the DB row only; it makes no instance call and performs no DB write. The response keeps its current JSON shape and field names (`videoUuid`, `title`, `description`, `channelName`, `channelUrl`, `channelAvatarUrl`, `subscribersCount`, `instanceName`, `instanceUrl`, `accountName`, `accountUrl`, `accountAvatarUrl`, `embedUrl`, `originalUrl`, `views`, `likes`, `dislikes`, `publishedAt`), each filled from the DB with the same fallbacks as today (e.g. channel URL built from slug + host, original URL built from uuid/id + host). Fields only the instance supplies today (e.g. `accountAvatarUrl`) are empty or DB-sourced. A missing row still answers 404 `{\"error\": \"Video not found\"}`; a missing id still answers 400.\n\n### R2 - Separate refresh request\n\nA separate Engine route performs the live refresh, and the Client backend proxies it with its own query-parameter allow-list (same sanitising rules as the other read proxies). It:\n- resolves the row exactly as `/api/video` does (404 if absent);\n- fetches from the instance with today's behaviour: `timeout=8`, catching `HTTPError`/`URLError`/`TimeoutError`, field-by-field fallback to the DB row when the instance omits or fails a field;\n- on a successful instance fetch, persists with today's writes: the `videos` UPDATE (title, description, channel_name, views, likes, dislikes, popularity via `compute_popularity`, tags_json, category, nsfw, last_checked_at), the `channels` UPDATE when `channel_id` is known, and the reset of `instances.last_error`/`last_error_at`/`last_error_source`; a `sqlite3.OperationalError` on write is logged and does not fail the response, as today;\n- on a failed instance fetch writes nothing;\n- returns the merged metadata in the same shape as `/api/video`.\nThis route is the single write path for per-request metadata refresh, so issue 10 (metadata completeness) can extend it later.\n\n### R3 - Page flow and ordering\n\nOn load the page starts three independent requests: similars, fast metadata (R1), and refresh (R2); none awaits another. The video panel renders from whichever metadata response arrives first; when the refresh succeeds the panel re-renders with its values. Refreshed data always wins regardless of arrival order: a fast response arriving after the refresh must not overwrite refreshed values. If the refresh fails, errors or times out, the panel keeps what it shows and no error is shown to the visitor (a console warning is acceptable).\n\n### R4 - No instance wait before first render\n\nNothing in the first render of the video panel awaits a request to the source instance. The browser-side `fetchInstanceMetadata` call (`/api/v1/config`, supplying instance name and avatar) moves off the first-render path; its values fill in when it resolves. Until then the instance chip shows the host with initials fallback, as it does today when that call fails.\n\n### R5 - Video unknown to the Engine\n\nWhen fast metadata answers 404 (or fails), the panel renders immediately from the URL params (`title`, `channel`, `channelUrl`, `embed`, `url`, `host`, as `fallback` holds them today), and the existing direct browser-to-instance fallback (`fetchVideoMetadataFromInstance`) fills it in when it arrives. The existing `https://`-only check on the embed URL is kept on every render path.\n\n### R6 - Re-render safety\n\nA re-render of the panel:\n- does not reassign the embed iframe `src` when the embed URL is unchanged (playback must not restart);\n- does not attach duplicate listeners to the like, dislike, block-channel or block-account buttons (the existing `dataset.wired` guards keep holding);\n- does not fetch the visitor's reaction again once it has been fetched for the same video uuid/host;\n- keeps escaping and `safeExternalUrl` on every value it writes, as today.\n\n### R7 - Similars unchanged\n\nSimilars content, ranking, limit (8), the `localLikesImported` wait, profile-key handling and error display are unchanged. A test shows that a similars request is answered without contacting the source instance and is not delayed by a slow metadata/refresh call running concurrently.\n\n### Constraints\n\n- The refresh route's worst case on the instance is about 16 s (two sequential 8 s calls) while the Client proxy times out at 10 s. The design step must decide how the refresh fits that budget (for example a per-route proxy timeout, a shorter instance timeout, or a single overall budget) and state the choice; a proxy timeout on the refresh must degrade per R3 (panel keeps its values), never blank the page.\n- Stdlib only on the Python side; no new frontend dependency. New code matches the style of the file it lands in.\n- `client/frontend/dist/` is build output and is not hand-edited.\n\n### Out of scope\n\n- Rendering tags/category and refreshing further fields (issue `10-video-metadata-completeness`).\n- Loading more similars on scroll / removing the similar-videos page (issue `12-similars-on-scroll`).\n- Similars diversity (issue `09-similars-diversity`).\n\n### Baseline suite state\n\nPre-build suite exited 0; baseline variant: false. Tests live in `tests/active` (working area `tests/tmp`).\n</requirements>\n\n<conflicts>\nIssue text \"the server answers the similars request immediately... without waiting for the instance\" vs the tree: similars (`/recommendations` \u2192 `_handle_similar`) already never contact the instance and already run in parallel with metadata; the actual blocking path is `/api/video` in `engine/server/api/handlers/video.py`. Resolved by the operator choosing the two-phase metadata reading (R1-R3).\nR2 refresh worst case (~16 s: two sequential `timeout=8` instance calls in `fetch_instance_video_dynamic`) vs `ENGINE_PROXY_TIMEOUT_SECONDS = 10` in `client/backend/server.py`: the refresh can be cut off by the Client proxy; left to the design step as a stated constraint.\n</conflicts>",
    "step_2_develop_solution": "<initial_solution>\n### Approach\n\nThe Engine's single video handler becomes two routes over one merge step. On the frontend, `loadVideo` is split into a render function that can run more than once and a small coordinator that decides which result wins.\n\n**Engine (`engine/server/api/handlers/video.py`, dispatch in `engine/server/api/handlers/similar.py`).** `handle_video_request` is split into three module-level functions in the file's existing style:\n- a row resolver: id/host parsing, 400 on missing id, 404 `{\"error\": \"Video not found\"}` on a missing row, using `fetch_video_row` with `video_error_threshold` as today;\n- a pure merge that takes the row, a `dynamic` dict and the instance domain, and returns the response dict. This is today's merge block unchanged: `dynamic`-or-row per field, channel URL from slug + host, original URL from uuid/id + host, embed from `embed_path`;\n- a persist function holding today's three UPDATEs, its `sqlite3.OperationalError` catch and its log line, unchanged.\n\nHow each requirement is met:\n- **R1.** `GET /api/video` = resolve, then merge with an empty `dynamic`. No `urlopen`, no write. Every field falls back to the DB exactly as today. `accountAvatarUrl` comes back empty because no DB column holds it.\n- **R2.** A new `GET /api/video/refresh`, added next to the `/api/video` branch in `SimilarHandler`'s GET dispatch. It resolves the row the same way, calls `fetch_instance_video_dynamic` (unchanged: `timeout=8` per call, same exception set, same field picking), merges, persists only when the instance fetch succeeded, and responds with the same shape. This handler is the one per-request write path that issue 10 extends later.\n- **Success signal (a gotcha found while reading).** `fetch_instance_video_dynamic` currently always returns a non-empty dict of keys, even when the detail call failed. Today's `if dynamic` guard is therefore always true, so today a failed fetch still writes DB values back, bumps `last_checked_at` and clears `instances.last_error`. R2 says a failed fetch writes nothing, so the function returns `{}` when the `/api/v1/videos/{id}` call itself returns `None`. Success means \"the video detail came back\". A failed channel sub-call still counts as success, with DB fallback for the channel fields, which matches the field-by-field rule. The function has no other callers; I grepped the tree.\n\n**Client backend (`client/backend/server.py`).**\n- `/api/video/refresh` is added to `PROXY_READ_GET_ROUTES`, so it gets the same rate limit and the same `_handle_engine_read_proxy_get` sanitising: unknown key \u2192 400, repeated key \u2192 400, values stripped.\n- Its own `PROXY_ALLOWED_QUERY_PARAMS` entry is `{\"id\", \"host\"}`. `refresh_cache` stays on `/api/video`'s list, untouched.\n- It is not in `FILTERED_ROUTES`, so it passes through `_profile_filter` untouched.\n\n**Budget decision (the constraint).** The refresh route gets a per-route proxy timeout of 20 s and no proxy retry. Everything else keeps `ENGINE_PROXY_TIMEOUT_SECONDS = 10` and `ENGINE_PROXY_RETRY_COUNT = 1`. It is implemented as a small path\u2192timeout mapping and a path check on the retry count inside `_proxy_engine_request`.\n- The Engine's worst case of about 16 s (two sequential 8 s calls) fits, so R2 keeps today's instance timeouts literally.\n- Dropping the retry matters as much as the timeout. Today a transport timeout is retried, which on this route would fire a second pair of instance calls and possibly a second write.\n- If the proxy still gives up, the browser gets the proxy's usual failure status. R3 treats that as a failed refresh: the panel keeps its values and a console warning is logged.\n- The Engine thread carries on and may still persist the result, which is harmless and even useful for the next visit.\n\n**Frontend (`client/frontend/src/pages/video-page/index.ts`).**\n- `loadVideo` becomes `renderVideo(metadata)`: today's body, minus the fetching.\n- A coordinator starts three things at load, none awaiting another:\n  - the fast `/api/video` fetch;\n  - the `/api/video/refresh` fetch;\n  - one shared `fetchInstanceMetadata(host)` promise.\n  `loadSimilarVideos()` stays exactly as it is.\n- **R3 ordering.** Each metadata source carries a rank: URL params 0, fast DB 1, direct browser-to-instance fallback 2, refresh 3. A result renders only if its rank is at least the rank currently shown. A late fast response therefore never overwrites refreshed values, whatever the arrival order. A failed or non-OK refresh logs `console.warn` and changes nothing.\n- **R4.** `fetchVideoMetadataFromServer` no longer awaits `fetchInstanceMetadata`. When the shared instance promise resolves, its avatar (and its name, where today's precedence lets the name through) is stored and the current best metadata is re-rendered. Until then the instance chip shows the host with initials, as it does today when `/api/v1/config` fails. Today's precedence is kept: the Engine's `instanceName`/`instanceUrl` win over the config values, and only the avatar is new. The direct-instance fallback also stops awaiting `fetchInstanceMetadata` and uses the shared promise.\n- **R5.** If the fast fetch returns non-OK or throws, the panel renders at once from `fallback` (rank 0). `fetchVideoMetadataFromInstance` then runs, and its result renders at rank 2 when it arrives. The `https://` check on the embed stays inside `renderVideo`, so every path passes through it.\n- **R6.**\n  - A module-level `lastEmbed` holds the last embed string assigned; `src` is set only when the checked embed differs from it. The comparison is against our own string, not `embedEl.src`, which the browser normalises.\n  - The block and like buttons keep their `dataset.wired` guards.\n  - `loadReaction` is gated by a `uuid|host` key of the last reaction fetched, so re-renders do not fetch it again for the same video.\n  - Escaping and `safeExternalUrl` stay on every write because the rendering code itself is not changed.\n- **R7.** Similars code is untouched. The new test starts the Engine handler over a fixture DB with `fetch_instance_json` patched to block for several seconds. It fires a refresh and then a similars request concurrently, and asserts the similars answer arrives well inside that delay with the instance stub never called by it.\n\nFiles touched: `engine/server/api/handlers/video.py`, `engine/server/api/handlers/similar.py` (one dispatch branch), `client/backend/server.py`, `client/frontend/src/pages/video-page/index.ts`, and `engine/server/README.md` (route list). `dist/` is regenerated by the build, not edited.\n\n### Alternatives considered\n\n- **Keep one `/api/video` with a `refresh_cache` flag, since the allow-list already carries it.** Rejected: R2 asks for a separate route. A flag would also give one route two latency profiles, so a proxy timeout could not be tuned per behaviour.\n- **Refresh in the background inside the Engine after `/api/video` answers from the DB, with the page polling or calling again.** Rejected: it needs a thread or queue and a second read to see the result, where one extra request already carries the data.\n- **Shorten the instance timeouts, or give the Engine one overall deadline of about 9 s across both calls, so the refresh fits the existing 10 s proxy timeout.** This keeps the proxy uniform. Rejected because R2 fixes `timeout=8` as today's behaviour, and the refresh is off the render path, so waiting longer costs the visitor nothing. It remains the upgrade if long-held threads ever matter.\n- **Render from the URL params at t=0, before any response.** Rejected: the `?embed=` value and the DB `embed_path` can differ textually, which would reload the iframe moments later. R3 also says the first render comes from a metadata response. The URL-param render happens only when the fast call fails, as R5 says.\n- **Extract the rank arbitration into a shared lib module for testability.** Not chosen by default: it has one caller. Tests can drive the page in node with a stubbed `document`/`fetch`, the same way `test_frontend_blocks.py` stubs the platform. If that proves too heavy, the test step may justify extracting the helper.\n\n### Risks, gotchas and limitations\n\n- `urlopen(timeout=8)` bounds each socket operation, not the whole call. A slowly dripping instance can take longer than 16 s. The 20 s proxy timeout caps what the browser waits, and R3's degrade covers it.\n- Each page view now holds a Client thread and an Engine thread for up to about 20 s on a slow instance, instead of up to 10 s plus a retry. Both servers are `ThreadingHTTPServer` with unbounded threads, so this costs memory, not correctness.\n- Each page view now makes two Client\u2192Engine metadata requests, so it spends two rate-limit tokens instead of one. The refresh has its own per-path bucket, so it does not eat into `/api/video`'s.\n- The fast path no longer bumps `last_checked_at`; only a successful refresh does. Nothing I read keys on it per request, but a worker that relies on it would see fewer bumps. They would now be honest ones, because today it is bumped even on failure.\n- The first-wired closures keep the first known video: the reaction listener captures the first `reactionVideo()`, and `enableBlockButtons` the first uuid. Re-renders do not rewire them. This is unchanged from today, but it becomes visible only if a later source reports a different uuid than the first, which should not happen for one row.\n- Avatar `innerHTML` is rewritten on every re-render, so the images may flicker once. This is cosmetic; skipping unchanged avatars is a trivial follow-up if it shows.\n- If the fast call fails but the refresh succeeds, for example on a transient proxy error, rank 3 wins as intended, and the direct-instance fallback's later result is ignored.\n\n### Tradeoffs the operator is asked to accept\n\n- A refresh against a slow or dead instance can keep a request open for up to 20 s, and the proxy does not retry it. This is the price of keeping today's 8 s per-call instance timeouts inside R2.\n- `accountAvatarUrl` is empty on first render and appears only after a successful refresh, because the DB has no column for it. Adding one is issue-10 territory.\n- A failed instance fetch no longer clears `instances.last_error` or bumps `last_checked_at`. This follows directly from R2 but changes today's accidental behaviour.\n</initial_solution>\n\n<conflicts>\nnone\n</conflicts>",
    "step_3_identify_impacts": "<impacts>\n<impacts>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request() (lines 208-361), split into resolver, pure merge, persist, plus a /api/video handler and a /api/video/refresh handler\">\n**What changes.** The one function becomes three module-level helpers and two thin route handlers.\n- **Resolver.** Takes lines 210-224. `id` falls back to `video_id` and `host` to `instance_domain` (210-211). It answers 400 `{\"error\": \"Missing video id\"}` and 404 `{\"error\": \"Video not found\"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` inside `with server.db_lock:`, which is held for 215-221 only.\n- **Merge.** Takes lines 226-290 with `dynamic` passed in. Line 226, `instance_domain = row.get(\"instance_domain\") or host_param or \"\"`, needs `host_param`, so the resolver has to hand back `host_param` or `instance_domain` along with the row.\n- **Persist.** Takes lines 292-358. It needs the merged intermediates (`title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`) plus `row[\"video_id\"]`, `row[\"channel_id\"]`, `row[\"published_at\"]` and `instance_domain`. The response dict cannot supply them:\n  - it has no `channel_slug`, `tags_json`, `category` or `nsfw`;\n  - it turns `None` into `\"\"` (`channelName: channel_display or \"\"`, `title or \"\"`).\n  So feeding persist from the response would write `\"\"` where today's code writes `NULL`. The plan says the merge \"returns the response dict\"; it must also expose the intermediates, or persist must re-derive them. The plan leaves this open.\n- **`/api/video`.** Resolve, then merge with `{}`. Every `dynamic.get(...)` is `None`, so each field falls back to the row exactly as today. `accountAvatarUrl` (283) becomes `\"\"`. `accountName`/`accountUrl` (281-282) already come from the row only.\n- **`/api/video/refresh`.** Resolve, `fetch_instance_video_dynamic`, merge, persist only on success, then respond with the same shape.\n- **Docstrings.** The module docstring (1-7, \"Merge DB metadata with live instance metadata (when available)\") and line 209 must say which route does what.\n\n**What depends on it.** `engine/server/api/handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else imports it. No test in `tests/active` touches this module (grep for `handlers.video`, `/api/video` and `fetch_instance` over `tests/`); only the smoke scripts call `/api/video`.\n\n**Regression risk: medium.**\n- **Lock boundary.** The instance call must stay outside `server.db_lock`, as today, where the lock is taken only around the SELECT (215) and around the UPDATEs (303). Pulling the fetch inside the resolver's `with` block would stall every Engine route that takes the lock (similar.py 261, 467, 652, 884, 957; similars included) for up to about 16 s, which breaks R7.\n- **Renames.** A renamed or removed `handle_video_request` breaks the import at similar.py:84. That is an import-time failure of the whole Engine, and every test that uses the session `engine` fixture fails with it.\n- **Races.** The row is read before the instance call and written after it, so two concurrent refreshes of one video both write and the last one wins. This is harmless.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails\">\n**What changes.** Line 164 today is `detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\") or {}`. It becomes an early `return {}` when the detail call does not come back.\n\n**The gotcha is confirmed.** The return at 188-205 always builds a 14-key dict, so the `if dynamic and instance_domain and row.get(\"video_id\")` guard at 293 is always true today. A failed fetch therefore:\n- writes DB values back;\n- recomputes `popularity`;\n- bumps `last_checked_at`;\n- clears `instances.last_error*`.\n\n**Edge cases for the success test.**\n- **Non-dict JSON.** `fetch_instance_json` returns whatever `json.loads` gives. A 200 with a JSON array or string reaches `detail.get` and raises `AttributeError`, which nothing catches. This is pre-existing.\n- **Empty object.** A 200 with `{}` passes an `is not None` test but carries no data, so persist would write DB values back and clear `last_error`.\n- **The fix.** Testing `isinstance(detail, dict) and detail` closes both cases.\n\n**Channel sub-call.** The sub-call at 176 runs only when `channel_slug` came back, so after the change it runs only on success.\n\n**What depends on it.** Only `handle_video_request` today (grep of the tree, tests included), and only the refresh handler after the build.\n\n**Regression risk: low.** This is the one deliberate behaviour change and the operator accepts it. The consequence: a failed fetch no longer resets `instances.last_error` or bumps `last_checked_at`.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_json() (lines 75-87): unchanged; the test seam; narrow exception set\">\n**What changes.** Nothing. The R7 test and the refresh tests patch it.\n\n**What depends on it.**\n- Both instance calls in `fetch_instance_video_dynamic` look it up as a module global. A test must patch the attribute on the `handlers.video` module; patching an imported alias has no effect.\n\n**The error path.**\n- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` misses `json.JSONDecodeError` (a non-JSON 200), `UnicodeDecodeError`, and `ConnectionResetError`/`http.client.RemoteDisconnected` raised during `resp.read()`.\n- **What happens then.** These escape the refresh handler. `SimilarHandler.do_GET` (similar.py:433-441) re-raises anything that is not an interrupted `OperationalError`, so the Engine drops the connection without answering.\n- **What the Client sees.** The drop reaches the Client as `RemoteDisconnected` or a reset, not as a `URLError`. It therefore lands in `except Exception` (client/backend/server.py:700-721), which answers 502 `ENGINE_PROXY_FAILURE`. The page treats that as a failed refresh (R3).\n- **Before and after.** This is pre-existing: today the same failure kills `/api/video` itself. After the split only the refresh can hit it.\n- **Timeout scope.** `timeout=8` bounds each socket operation, not the whole call.\n\n**Regression risk: none in code.**\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"statement_deadline() / _deadline_passed() / PROGRESS_HANDLER_INSTRUCTIONS (lines 14-64), as it applies to the refresh's persist\">\n**What changes.** Nothing in code, but the refresh's timing brings this into play.\n\n**How the deadline applies.**\n- `SimilarHandler.do_GET` (similar.py:436) runs the whole dispatch inside `self._statement_deadline()` (similar.py:345-353). That is `statement_deadline(server.statement_timeout_seconds)`, and `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0` (server_config.py:435) is assigned at `engine/server/api/server.py:272`.\n- The deadline is wall-clock time, thread-local, and counted from the start of the request.\n- The refresh reaches its UPDATEs only after up to about 16 s of instance calls, so by then its thread's deadline has usually passed.\n- The progress handler fires every 10,000 VM instructions (line 14). Any persist statement that runs that long after the deadline is aborted with `OperationalError: interrupted`.\n- The `videos` UPDATE fires `videos_fts_au` (`engine/server/db/jobs/sync-whitelist.py:279-284`), which deletes and re-inserts title, description, tags_json, category and channel_name into FTS5. Crossing 10,000 instructions is plausible there, especially with long descriptions.\n\n**Consequence.**\n- The persist's own `except sqlite3.OperationalError` (video.py:352-358) catches the abort, logs `[video] failed to persist dynamic metadata ... interrupted`, and `with server.db:` rolls back.\n- The response is still 200 with the refreshed values, so a successful but slow refresh can silently fail to persist, against R2.\n- This is pre-existing and masked today. After the build the refresh is the only writer, so it now matters.\n\n**Mitigation.** Wrap persist in its own nested `statement_deadline(...)`. Lines 59-64 save and restore the outer deadline, so nesting is supported. The other option is to state it as a limitation.\n\n**Regression risk: medium to high for R2's persist guarantee.** I have not measured whether one UPDATE plus the trigger actually crosses 10,000 instructions. A child-process test with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json` would show it.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_get() /api/video branch (lines 495-497), import at line 84, module docstring route list (lines 3-13)\">\n**What changes.**\n- A new branch, `if url.path == \"/api/video/refresh\":`, goes beside line 495 and calls the refresh handler.\n- The import at line 84 gains the new name or names.\n- The docstring gains a `/api/video/refresh` line, and line 9 (`/api/video: single video metadata.`) should say it reads from the DB.\n\n**What depends on it.**\n- **Rate limit.** Line 447 rate-limits every path under `/api/` on the key `f\"{ip}:{path}\"` (`_rate_limit_check`, 576-583). The refresh therefore gets its own bucket (`DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60`, server_config.py:431). The ip comes from the `x-client-ip` header the Client sets (client/backend/server.py:590).\n- **Matching.** Paths are matched with `==`. `_extract_video_id_from_similar_path` (499) matches only `/videos/.../similar`, so without the new branch `/api/video/refresh` falls through to the 404 at 508. Nothing shadows it.\n- **Deadline.** Both routes run inside the statement deadline in `do_GET` (see the db.py entry). An interrupted error raised during the resolver's SELECT would still reach `_respond_interrupted` as a 503, but that SELECT is fast.\n\n**Regression risk: low.** It is one branch, and the similars dispatch (499-506, `_handle_similar_request`) is untouched, which keeps R7.\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 5 ('video: fetches video metadata for /api/video.')\">\n**What changes.** The line names both routes: `/api/video` (DB only) and `/api/video/refresh` (live instance refresh, persisted on success).\n\n**What depends on it.** Nothing.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"respond_json() (lines 23-30), the refresh's final write\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- It writes to `handler.wfile` unguarded.\n- A slowly dripping instance can outlast the Client's 20 s proxy timeout, because `timeout=8` applies per socket operation. The Engine then writes its late answer to a socket the Client has already closed.\n- The write raises `BrokenPipeError`/`ConnectionResetError`, which `do_GET` does not catch, so `socketserver` prints a traceback to stderr.\n- By then persist has already run, so the data is kept, and the browser has already had its 502.\n- This is pre-existing on `/api/video` at 10 s; after the build only the refresh can hit it.\n\nUnlike this Engine helper, the Client side's `respond_bytes` already returns False when the client disconnects (server.py:619).\n\n**Regression risk: low (log noise).**\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer (ThreadingHTTPServer, line 207): video_error_threshold (230/264), popularity_like_weight (234/268), statement_timeout_seconds (272), db, db_lock\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The resolver reads `server.video_error_threshold` directly, not through `getattr`.\n- Persist reads `getattr(server, \"popularity_like_weight\", 2.0)`, `server.db` and `server.db_lock`.\n- `ThreadingHTTPServer` gives each request its own thread, so a refresh blocked on an instance holds one thread and not the server. R7 relies on this.\n\n**Test note.** A child-process test needs a server object that carries `db`, `db_lock` and `video_error_threshold`, plus `popularity_like_weight` if persist runs and `statement_timeout_seconds` if the deadline is exercised. `tests/active/test_internal_events.py:52` builds a real `SimilarServer` from kwargs this way.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/popularity.py\" element=\"compute_popularity(), called by persist (video.py:295-301)\">\n**What changes.** Nothing. It moves with the persist block. Its arguments must stay:\n- the merged `views`/`likes` (the instance value, or the DB fallback);\n- `row[\"published_at\"]`;\n- the like weight;\n- `now_ms_value=checked_at`.\n\n**What depends on it.** The `videos.popularity` column, which ranking reads.\n\n**Regression risk: low.** Today it runs on every page view, including failed fetches that write the DB values back unchanged. After the build it runs only on a successful refresh, and the popular-video ordering reads the same column.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"videos_fts_au AFTER UPDATE trigger (lines 279-284)\">\n**What changes.** Nothing.\n\n**What depends on it.** Every persisted refresh fires the trigger and re-indexes the video for search. Writes fall from one per page view (failures included) to one per successful refresh, so FTS churn and write-lock time go down. It is also why the statement-deadline entry matters.\n\n**Regression risk: none in code.**\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301), data/search.py (80), data/channels.py (129-159, instances.last_error*)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- These files only project `last_checked_at` and `instances.last_error*` into rows. A grep of `engine/server` (outside whitelist_migrations.py) shows nothing that filters or orders on them.\n- The frontend source never reads `last_checked_at` (grep of `client/`, dist excluded).\n- So the fast path no longer bumping them, and a failed refresh no longer clearing `last_error`, is invisible to serving.\n- `/api/channels` exposes `last_error*` as data, so a stale error now stays visible there until a successful refresh or a crawl clears it.\n\n**Regression risk: none in serving; low for the `/api/channels` display.** I did not audit the crawler (`engine/crawler`), which keeps its own DB.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0 (435), DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60 (431), line 455 comment ('Optional future toggle for /api/video hide behavior')\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The statement budget interacts with the refresh persist.\n- The Engine's per-path rate limit now applies to the refresh as a separate bucket.\n- The line 455 toggle is not referenced by video.py and stays unrelated.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)\">\n**What changes.**\n- `\"/api/video/refresh\"` joins the frozenset.\n- A new entry `\"/api/video/refresh\": {\"id\", \"host\"}` is added.\n- `/api/video` keeps `{\"id\", \"host\", \"refresh_cache\", \"user_id\"}`.\n\n**What depends on it.**\n- `do_GET` (277-282) routes on `url.path in PROXY_READ_GET_ROUTES`. It applies `_rate_limit_check(url.path)` (406-409, key `ip:path`, `RATE_LIMIT_MAX_REQUESTS = 90` per 60 s), so the refresh gets its own Client bucket, then calls `_handle_engine_read_proxy_get`.\n- `_handle_engine_read_proxy_get` (417-436) answers 400 on an unknown key or a repeated key, and strips values.\n- The frontend must send only `id` and `host`: a `user_id` or `refresh_cache` on the refresh now gets 400.\n\n**Regression risk: low.** It is a pure addition.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_proxy_engine_request() (lines 570-745) with ENGINE_PROXY_TIMEOUT_SECONDS (77), ENGINE_PROXY_RETRY_COUNT (79), ENGINE_PROXY_RETRY_DELAY_SECONDS (80)\">\n**What changes.** A path\u2192timeout mapping (20 s for the refresh, `ENGINE_PROXY_TIMEOUT_SECONDS` otherwise) and a per-path retry count (0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise).\n\n**Four sites must read the per-path values.**\n- 604: `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)`.\n- 606: `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)`.\n- 696: `if attempt < ENGINE_PROXY_RETRY_COUNT`.\n- 731: the `\"attempts\": ENGINE_PROXY_RETRY_COUNT + 1` field of the \"proxy request unavailable\" log. It is easy to miss; left alone it logs 2 attempts for a refresh that made 1.\n\n**Key on `path`.** The mapping must use `path`, not `upstream`, which carries the query string (581-583).\n\n**What depends on it.** Every proxied read:\n- GET `/api/video`, `/api/channels` and `/api/v1/search/videos`;\n- POST `/recommendations` and `/videos/similar` (561).\n\nAll of them must keep 10 s and one retry.\n\n**How a refresh failure surfaces.**\n- The Engine writes nothing until it finishes, so the proxy waits up to the full timeout.\n- `socket.timeout` is `TimeoutError`, which lands in the `(URLError, TimeoutError)` branch (694). With 0 retries the loop breaks to the 502 `ENGINE_PROXY_UNAVAILABLE` (736-744).\n- A dropped Engine connection lands in the generic 502 (700-721).\n- An Engine 404 or 400 with a body passes through the HTTPError branch (646-677).\n- All of these are non-OK for the browser.\n\n**Test harness.** `tests/active/test_server.py` offers `_serving` (347-355), `_client_backend` (358-367), `_status` (370-378, `timeout=30`) and an `EngineStub` (400-422), which together are the template for a stub that counts GETs and sleeps. No existing test monkeypatches the proxy constants, so a new test can patch them or the mapping on `client_server` to stay fast.\n\n**Regression risk: medium.** This loop carries every browser read. A wrong key or a missed site silently changes the timeout or retry for every route, so tests must pin both the refresh and one ordinary route.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The refresh gets the same sanitising.\n- An empty value is dropped (431), so `id=` reaches the Engine with no `id` and gets its 400 `Missing video id`, which the Client passes through.\n- `_profile_filter` returns `(True, None, None, None)` for the refresh, because it is in neither `FEED_ROUTES` nor `FILTERED_ROUTES` (71-72). An `X-Profile-Key` header on it is therefore ignored rather than validated.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"module top level: `void loadVideo()` (79), `void loadSimilarVideos()` (80), currentMetadata (50), seedId/seedHost (54-55), fallback (57-63), localLikesImported (75-77), applyActionIcons() (1226)\">\n**What changes.** Line 79 becomes the coordinator start. Line 80 is unchanged.\n\n**What the coordinator must preserve.**\n- **No usable source.** When `resolveVideoSource()` gives no host or no id, `fetchVideoMetadata` returns `null` at 508, and today the page renders once with `metadata = null` from `fallback`, `seedHost` and `https://${seedHost}`. That must be kept, and in that case neither the fast fetch nor the refresh should fire.\n- **`currentMetadata` in step.** It must always equal the metadata actually rendered, because `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost` (1151-1166).\n\n**Testing constraints.** The module does DOM work at import:\n- about 27 `getElementById` constants (22-48);\n- `window.location.search` (53);\n- `importLocalLikes` (75);\n- `applyActionIcons()` (1226);\n- `import \"../../video.css\"` (5).\n\nA node test of the page therefore needs a stubbed `document`/`window`, a scripted `fetch`, `localStorage`, and an esbuild css loader flag. The existing frontend tests (`test_frontend_blocks.py:23,66`, `test_frontend_videos.py`, `test_frontend_reactions.py`, `test_frontend_profile.py`) bundle data modules only, with `--platform=node`.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadVideo() (lines 85-229) becoming renderVideo(metadata)\">\n**What changes.** The body stays, minus `await fetchVideoMetadata()` (86). `currentMetadata = metadata` (87) moves into or next to it. It now runs once per accepted source, and again when the instance config arrives.\n\n**What re-runs on every render.**\n- **Text and markup.** Title, the channel `innerHTML` through `escapeHtml`/`safeExternalUrl` (120-122), subscribers, instance link, account link, description, views, counts and the original link. All of these are idempotent.\n- **Avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatars (154-161, 179-186) are rewritten, and `bindAvatarFallback` (426-437) binds a `once` listener to each fresh `<img>`. The old nodes are discarded, so listeners do not pile up, though an image may flicker.\n- **Embed (212-221).** Today it sets `embedEl.src = embed` unconditionally. The new `lastEmbed` guard must compare against the checked string actually assigned, and must be cleared when the `else` branch calls `removeAttribute(\"src\")`; otherwise a later valid identical URL is never reassigned.\n- **`document.title`** (114).\n- **`enableBlockButtons`** (196) is guarded by `dataset.wired`.\n- **`void loadReaction()`** (197) needs the new gate (see its entry).\n\n**Values across sources.**\n- The Engine sends `\"\"`, not null, for empty strings, so `metadata?.title ?? fallback.title` gives `\"\"`, and `titleEl` shows \"Video page\" through `title || \"Video page\"`, as today.\n- Ranks 1 and 3 both carry `embedUrl = resolve_asset_url(instance_domain, row.embed_path)`, which is textually identical, so there is no reload between them.\n- Rank 0 uses `fallback.embed` and rank 2 uses `resolveApiAssetUrl(host, embedPath)` (592). So when the fast call fails, one iframe reload between rank 0 and a later rank is possible. R6 covers only an unchanged URL.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)\">\n**What changes.**\n- The sequential \"server, else instance\" logic in `fetchVideoMetadata` moves into the coordinator.\n- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (525). It must now serve both `/api/video` and `/api/video/refresh`, through a path argument or a shared mapper; the refresh answers the same shape, so the mapping at 527-551 applies unchanged.\n\n**Precedence, confirmed in code.**\n- The Engine always sends `instanceName`/`instanceUrl` as strings (video.py:279-280, possibly `\"\"`), and `??` does not skip `\"\"`. So for ranks 1 and 3, `instanceMeta?.name`/`url` never win today (534-539); the config supplies only `instanceAvatarUrl` (540).\n- For rank 2 (608-610), the config's name and URL do win.\n- If re-applying the shared config overwrote `instanceName` for ranks 1 and 3, the chip label would visibly change from the host to the display name. It would also change `resolveLikeHost` when `seedHost` is empty.\n\n**Other effects.**\n- `catch { return null; }` (552-554) also swallows `response.json()` failures and non-OK statuses. The refresh caller needs its own failure signal to `console.warn`.\n- `instanceAvatarUrl` must be merged in from the shared promise on every render, or it disappears when a later rank re-renders.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)\">\n**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, because it is part of rank 2 itself.\n\n**Behaviour to keep.**\n- The rank-2 result has no `videoUuid`, so `resolveLikeUuid` falls back to `seedId` only when `looksLikeUuid` (1171-1173) accepts it.\n- `instanceName: instanceMeta?.name ?? source.host` (608) can be `\"\"`, because `getString` returns `\"\"` (724-730). `instanceMetaEl.hidden = !instanceName` (140) then hides the chip. This is pre-existing.\n- It runs only after the fast fetch fails (R5). If rank 3 is already shown, the rank rule drops its result, so the coordinator could skip starting it.\n\n**Regression risk: low to medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchInstanceMetadata() (655-688) and getString() (724-730), as one shared promise\">\n**What changes.** It is called once per load, and the promise is shared.\n\n**What it returns.**\n- `getString` returns `\"\"`, never undefined, so the `?? ... ?? host` chain at 664-667 never reaches `host`.\n- `avatarUrl` is always set on success, falling back to `https://${host}/favicon.ico`.\n- Any failure, including a CORS failure, resolves to `null` and never rejects, so a `.then` needs no `.catch`.\n\n**What depends on it.**\n- The instance avatar on every rank, and the name and URL on rank 2.\n- When it resolves, the current best metadata is re-rendered at the same rank, so the rank rule must allow equal-rank renders (\"at least the rank shown\").\n- Rank 0 renders with `null` metadata, so if the avatar should appear there, it has to be applied in `renderVideo` from a module variable, not merged into the metadata object.\n\n**Constraint.** It may start only once a host is known.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadReaction() (318-341), reactionVideo() (381-386), react()/renderReaction() (346-364)\">\n**What changes.** A module-level `uuid|host` key for the last reaction fetched gates `fetchReaction`.\n\n**How the gate must work.**\n- **Non-null video only.** `reactionVideo()` depends on `currentMetadata`. On a rank-0 or rank-2 render with a non-UUID `seedId` it returns `null`, and `loadReaction` returns at 320 without wiring the buttons. A later rank that carries `videoUuid` (1 or 3) must still fetch and wire, so the key is set only when `video` is non-null.\n- **Before the first await.** `await localLikesImported` (322) comes before the fetch, so the key must be written before that first `await`. Otherwise two quick renders both pass the gate and fetch twice.\n- **Listeners.** The listeners (331-340) capture the first non-null `video` and are never rewired, because of `likeButton.dataset.wired` (327). This is unchanged.\n\n**What depends on it.** `renderReaction` and `setReactionStatus`. `tests/active/test_frontend_reactions.py` exercises `data/reactions.ts`, not this page.\n\n**Regression risk: medium.** A wrong gate either breaks R6 (a second fetch) or leaves the buttons disabled when the uuid arrives only with a later rank.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"enableBlockButtons() (275-308)\">\n**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.\n\n**What depends on it.**\n- It captures `uuid` and `host` from the first call where both are non-empty.\n- On a rank-0 render, `metadata?.videoUuid || resolveVideoSource()?.id` (196) is `seedId`, which may be a numeric id, and the buttons keep it for good.\n- That already happens today when `/api/video` fails. It is more reachable now, if the fast call fails and the refresh brings the real uuid later.\n- I did not trace whether `blockVideoSource` resolves a numeric id.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadSimilarVideos() (234-269) and the similar stats helpers\">\n**What changes.** Nothing (R7). It waits only on `localLikesImported` and never on metadata.\n\n**Regression risk: none,** as long as the coordinator neither awaits it nor chains it.\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"CSP meta (line 8)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser\u2192instance fetches.\n- `frame-src https:` matches the embed's `https://` check.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/dist/assets/video-gjYm1MC8.js\" element=\"built video page bundle (build output)\">\n**What changes.** The build regenerates it under a new hash; it is never edited by hand.\n\n**What depends on it.** The deployed static site serves `dist`.\n\n**Regression risk: low.** A stale `dist` deployed against the new Engine still works, because `/api/video` keeps its shape. It just no longer gets live values or the account avatar.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"dev server proxy '/api' (lines 27-28)\">\n**What changes.** Nothing. The `/api` prefix already covers `/api/video/refresh` in dev.\n\n**Regression risk: none.** I did not check whether a dev proxy timeout is set.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"frontend gateway preflight (lines 22-38)\">\n**What changes.** Nothing. It forbids only:\n- Engine base usage;\n- hard-coded Engine ports;\n- `/internal/*` routes in `client/frontend/src`.\n\nA `/api/video/refresh` literal passes.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"nginx `location /api/` (319-325); ufw prose (369, 374-375)\">\n**What changes.**\n- **nginx block.** Needs nothing. `location /api/` already proxies `/api/video/refresh`, and no `proxy_read_timeout` is set, so nginx's 60 s default exceeds 20 s.\n- **ufw comment (369).** \"live video metadata\" stays true.\n- **Prose at 374-375.** \"`/api/video` makes live calls to source instances per request\" becomes wrong (see the docs checklist).\n\n**Regression risk: none in config.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture (105-140) over WHITELIST_DB (34); ENGINE_PY (32); ENGINE_SERVER (33); CLOSED_ENGINE (45)\">\n**What changes.** Nothing.\n\n**What new tests must avoid.**\n- A refresh through the session `engine` fixture would make real outbound HTTPS calls and write to the shared `whitelist.db`.\n- Refresh tests and the R7 test must run the handler in an `ENGINE_PY` child over a temporary DB, with `handlers.video.fetch_instance_json` patched.\n- Precedents: `test_internal_client_reads.py:144-145`, `test_internal_events.py:52,174`, and the child runs in `test_similar.py` (237, 307, 415, 533).\n- A fast `/api/video` against the shared Engine is safe after the build (no calls, no writes).\n\n**Regression risk: medium for test hygiene.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"_serving/_client_backend/_status/EngineStub pattern (lines 347-422)\">\n**What changes.** Nothing. It is the template for the new proxy test.\n\n**The new test.** A stub Engine counts GETs and sleeps past a monkeypatched timeout on `/api/video/refresh`. It checks two things:\n- the refresh makes one attempt;\n- `/api/video` still retries once.\n\n**Test group.** The file maps to `client/backend/server.py` and `engine/server/api/handlers/similar.py` in `.un/skills/devsecops/config.json` (57-60).\n\n**Regression risk: low.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups mapping\">\n**What changes.** Nothing during the build.\n\n**Coverage gaps.** Grep finds no mapping for `engine/server/api/handlers/video.py` or `client/frontend/src/pages/video-page/index.ts`. Any new test file for them needs an entry at harvest, or it runs only in full-suite runs.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647) and README.md line 134\">\n**What changes.** Nothing is required: `/api/video` still answers 200, and faster.\n\n**Optional.** A `/api/video/refresh` check would depend on outbound 443, so asserting \"200 or 502\" is safer.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/security-audit/run-1/REPORT.md\" element=\"line 299 (`/api/video` performs up to two outbound HTTPS requests); also run-1/architecture.md:35,67, run-1/FINDINGS-DETAIL.md:127, run-2/REPORT.md:73,125,221, run-2/FINDINGS-DETAIL.md:12,136, run-2/findings.json\">\n**What changes.** Nothing. These are dated audit records and are not rewritten. I list them only because a grep for `/api/video` hits them and they describe the old behaviour.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/plans/19-11-fast-similars-response.record.md\" element=\"workflow record for this build\">\n**What changes.** The workflow renders it; do not hand-edit it. It already holds an earlier step-3 pass. I re-read the files it names, and its line numbers still match the tree.\n\n**Regression risk: none.**\n</impact>\n</impacts>\n</impacts>\n\n<docs_checklist>\n<doc path=\"engine/server/README.md\">\nLine 9 (`/api/video` metadata for the video page) becomes two bullets:\n- `/api/video` answers from the local DB only, with no instance call and no write. The response shape is unchanged, and `accountAvatarUrl` is empty.\n- `/api/video/refresh` fetches live metadata from the source instance: video detail, then channel, with an 8 s socket timeout on each. It answers the same shape. Only when the detail call succeeds does it run the `videos`/`channels` UPDATE and reset `instances.last_error*`; a failed fetch writes nothing. It is the one per-request metadata write path.\n\nLine 3 (\"Read-only Engine API\") should acknowledge that the refresh route writes metadata.\n</doc><doc path=\"README.md\">\nThe boundary table at line 46 (Engine public read API) and line 48 (Client browser-facing read gateway): add `/api/video/refresh` to both route lists. Line 134 (the smoke check expects `/api/video` to answer 200) stays true.\n</doc><doc path=\"client/README.md\">\nLine 37 (read gateway list): add `/api/video/refresh`. Optionally note that the refresh proxy accepts only `id` and `host`, waits up to 20 s and is not retried, while every other read proxy keeps 10 s with one retry.\n</doc><doc path=\"client/frontend/README.md\">\nLine 8 (fetched gateway routes): add `/api/video/refresh`. Optionally add one sentence on the video page's load order:\n- it renders from `/api/video` first;\n- it re-renders when the refresh and the instance config arrive;\n- when `/api/video` fails, it falls back to the URL params and then to the direct instance fetch.\n</doc><doc path=\"DEPLOYMENT.md\">\nLines 374-375: \"`/api/video` makes live calls to source instances per request\" becomes `/api/video/refresh`, one live refresh per video page view. The ufw comment at 369 and the nginx block at 319-325 need no change.\n</doc><doc path=\"docs/project/issues/10-video-metadata-completeness.md\">\nAdd a comment rather than editing the body:\n- Line 22 (\"reflected after the next `/api/video` request\") now applies to `/api/video/refresh`.\n- Line 17's rule (\"the DB update and `instances.last_error` reset run only on a successful refresh\") is now real behaviour, delivered by this build.\n- The refresh handler in `engine/server/api/handlers/video.py` is the single per-request write path this issue extends.\n- Line 16 stays true.\n</doc><doc path=\"docs/project/issues/20-request-lifecycle-logs.md\">\nLine 25 (smoke list naming `/api/video`): add `/api/video/refresh`. It is the long-running, instance-bound route whose start\u2192end logging matters most.\n</doc><doc path=\"docs/project/roadmap.md\">\nLine 54 (F2-M3 API versioning lists the unversioned routes): add `/api/video/refresh`.\n</doc><doc path=\"docs/project/issues/11-fast-similars-response.md\">\nAt harvest:\n- set `Status: enhancement, complete`;\n- add a delivery comment recording the two-phase reading, the 20 s no-retry refresh budget, and the accepted `last_error`/`last_checked_at` change;\n- move the file to `docs/project/issues/archive/`.\n</doc>\n</docs_checklist>\n\n<highest_risk>\nengine/server/data/db.py statement_deadline, applied to the refresh persist in engine/server/api/handlers/video.py: `SimilarHandler.do_GET` (similar.py:436) starts a 5 s wall-clock deadline (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`) when the request begins, but the refresh reaches its UPDATEs only after up to about 16 s of instance calls. Any persist statement, including the `videos_fts_au` FTS trigger, that runs past 10,000 VM instructions after that deadline is aborted as `interrupted`, and persist's own `OperationalError` catch swallows the abort. A slow but successful refresh can therefore silently not persist, against R2. A nested `statement_deadline` around persist fixes it; I have not measured whether the threshold is actually crossed.\nclient/backend/server.py _proxy_engine_request (570-745): the per-path timeout and retry change sits in the loop every browser read goes through. Four sites must switch (604, 606, 696, and the `attempts` log field at 731), and the lookup must key on `path`, not on `upstream`, which carries the query string. A mistake silently changes the 10 s timeout and single retry of `/api/video`, `/api/channels`, search and the feed POSTs. Tests must pin the refresh at one attempt and an ordinary route at two.\nclient/frontend/src/pages/video-page/index.ts renderVideo/loadReaction/fetchVideoMetadataFromServer: code written to render once now renders several times, and three rules keep it correct. First, the `lastEmbed` guard must be cleared when `src` is removed. Second, the reaction gate must be written before the first `await` and only for a non-null `reactionVideo()`; otherwise the reaction is fetched twice, or the buttons stay unwired when the uuid arrives only with a later rank. Third, the Engine always sends `instanceName`/`instanceUrl` as strings, so for ranks 1 and 3 the shared instance config may add only the avatar; overwriting the name visibly changes the chip label.\n</highest_risk>",
    "step_4_reassess": "<summary>\nI checked every inventory entry that makes a claim about code, and all of them held. I read all of `engine/server/api/handlers/video.py`; `similar.py` 330-590 (deadline wrapper, `do_GET`, `_dispatch_get`, rate limit); `client/backend/server.py` (constants 60-105, `do_GET` 273-282, `_rate_limit_check`, `_handle_engine_read_proxy_get`, `_profile_filter`, `_proxy_engine_request` 570-745); `engine/server/data/db.py` 1-90; `respond_json`; the `videos_fts_au` trigger; the `test_server.py` harness at 347-422; and all of `client/frontend/src/pages/video-page/index.ts`. I grepped for other users of the proxy constants, of `handle_video_request`/`fetch_instance_video_dynamic`, and of `last_error`/`last_checked_at` in the Engine's Python. I found nothing the inventory lacks. The five documents an earlier step-4 pass reported (four route lists and issue 10), plus the roadmap line, are already in this build's docs checklist in the record, so I am not reporting them again. The plan works as intended. It has two design gaps, both already named in the inventory: persist's inputs, and the statement deadline over persist.\n<question id=\"1\">\nYes, it works as intended. What the code confirms:\n- **R1.** With `dynamic = {}`, every field at video.py 229-290 falls back to the row. `accountAvatarUrl` (283) becomes `\"\"`, and nothing else changes.\n- **R2's success signal.** `fetch_instance_video_dynamic` always returns a 14-key dict (188-205). The guard at 293 is therefore always true today, so the early `return {}` is what makes \"no write on failure\" real.\n- **R7.** `db_lock` is held only around the SELECT (215-221) and the UPDATEs (303-351). The instance call is outside the lock, and `SimilarServer` is a `ThreadingHTTPServer`, so a slow refresh cannot delay similars as long as the split keeps the call outside the lock.\n- **Proxy.** The constants are used only in `_proxy_engine_request`, at 604, 606, 696 and 731; grep finds no other user. A per-path lookup in that one function covers the change. Every refresh failure mode reaches the browser as non-OK:\n  - a timeout lands in the `(URLError, TimeoutError)` branch and ends as a 502 `ENGINE_PROXY_UNAVAILABLE`;\n  - a dropped Engine connection lands in the generic 502;\n  - an Engine 404 or 429 with a body passes through.\n  R3's degrade path therefore holds.\n- **Frontend.** The only instance awaits on the render path are at 525 and 600, as the plan says. `fetchInstanceMetadata` never rejects.\n\nTwo things only the design step can settle, both already in the inventory:\n- **Persist deadline.** Persist runs under a 5 s deadline that is counted from the start of the request (similar.py 436, db.py 59-60). After a slow instance, the UPDATE and FTS trigger (sync-whitelist.py 279-284) can be aborted as `interrupted`. The `except` at 352 swallows that, so R2's \"persists on success\" can fail without any error.\n- **Persist inputs.** Persist needs the merge's intermediate values, which the response dict does not carry.\n</question>\n<question id=\"2\">\n- **Requests per view.** Each page view makes two Client\u2192Engine metadata requests. Each has its own `ip:path` rate-limit bucket on both tiers: Client, 90 per 60 s; Engine, 60 per 60 s.\n- **Held threads.** On a slow instance, one Client thread and one Engine thread are held for up to 20 s.\n- **Fewer writes.** DB and FTS writes drop from one per view (failures included) to one per successful refresh.\n- **Error and timestamp columns.** `last_checked_at` and `instances.last_error*` stop being touched on failure. Nothing in `engine/server` filters on them; `data/channels.py` 129-159 only exposes them.\n- **Log noise.** A late Engine write to a closed proxy socket raises in `respond_json`, which is unguarded (http_utils.py 30). This is noise only.\n- **Instance calls.** The refresh becomes the only route that reaches the instance, so its uncaught errors (JSONDecodeError and similar) now affect only the refresh, not the page's first render.\n</question>\n<question id=\"3\">\nEverything required is already in the inventory:\n- **Import.** `similar.py:84` must import the new names; if one is missing, the whole Engine fails at import time.\n- **Proxy sites.** All four proxy sites must read the per-path values, keyed on `path`, not `upstream`.\n- **Deadline.** Persist must run under its own `statement_deadline` (nesting is supported at db.py 59-64), or the gap is stated as a limitation.\n- **Merge output.** The merge must return its intermediates so that persist writes `NULL`, not `\"\"`.\n- **Frontend rules:**\n  - `lastEmbed` is cleared on the `removeAttribute(\"src\")` branch;\n  - the reaction gate is set only for a non-null `reactionVideo()`, and before `await localLikesImported`;\n  - for ranks 1 and 3, the instance config supplies only the avatar, because the Engine always sends `instanceName` as a string (279) and `??` does not skip `\"\"`;\n  - nothing is fetched when `resolveVideoSource()` gives no host or id.\n- **Docs.** The docs checklist edits.\n</question>\n<question id=\"4\">\n- **`/api/video`** becomes DB-only: faster, `accountAvatarUrl` always `\"\"`, no instance call, no write.\n- **Live values** arrive through `/api/video/refresh`, and are persisted only when the detail call succeeds.\n- **A failed fetch** no longer writes DB values back, recomputes `popularity`, bumps `last_checked_at` or clears `instances.last_error*`.\n- **Proxy.** The refresh gets 20 s and no retry; every other route keeps 10 s and one retry.\n- **Page.** It renders before the instance config arrives and may re-render up to three times. The instance avatar fills in late.\n- **Iframe.** When the fast call fails, one iframe reload between `?embed=` and a later embed URL is possible.\n\nSimilars, the response shape, the 400/404 answers, escaping and `safeExternalUrl` are unchanged.\n</question>\n</summary>\n\n<new_impacts>\nnone\n</new_impacts>\n\n<unconfirmed>\nnone\n</unconfirmed>\n\n<new_conflicts>\nnone\n</new_conflicts>\n\n<recommendations>\n1. **Run persist under its own `statement_deadline(server.statement_timeout_seconds)`.** It changes one `with` line in the persist function, plus one child-process test that runs with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json`. Without it, a slow but successful refresh can quietly fail to persist, and slow instances are exactly the case the refresh exists for. The alternative is to record it as a limitation, which costs nothing now but leaves R2 partly unmet.\n2. **Have the merge return its intermediates next to the response dict, and have persist take those.** The intermediates are `title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw` and `instance_domain`. This costs one extra return value and changes no behaviour. Re-deriving them from the response would write `\"\"` where today's code writes `NULL`.\n3. **Treat the detail call as successful only when `isinstance(detail, dict) and detail`.** This costs one expression. It also closes the uncaught `AttributeError` on a non-object 200, and stops an empty `{}` from clearing `last_error`.\n4. **Keep the instance-config result in a module variable and apply it inside `renderVideo`.** Use the avatar on every rank, and the name and URL on rank 2 only, instead of merging it into the metadata object. This costs one variable and a few lines, and it lets the rank-0 `renderVideo(null)` path show the avatar too. Alternatively, state plainly that rank 0 shows no avatar.\n5. **Pin both routes in one stub-Engine test in `tests/active/test_server.py`, with the proxy constants monkeypatched.** The refresh should make one attempt under the 20 s mapping; `/api/video` should make two attempts at 10 s. This costs one test and protects the loop every browser read goes through.\n6. **Take the docs checklist as recorded.** It costs about ten lines of documentation and no code.\n</recommendations>",
    "step_5_draft_implementation": "<draft>\n## Draft implementation: two-phase video metadata (issue 11)\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/handlers/video.py` | `fetch_instance_video_dynamic` returns `{}` on a failed detail call. `handle_video_request` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`. `handle_video_request` (DB only) keeps its name; `handle_video_refresh_request` is new. Module docstring updated. |\n| `engine/server/api/handlers/similar.py` | Import gains `handle_video_refresh_request`. New `/api/video/refresh` dispatch branch. Docstring route list updated. |\n| `engine/server/api/handlers/__init__.py` | Docstring line 5 names both routes. |\n| `client/backend/server.py` | Route and allow-list entries. Two per-path mappings (timeout, retry count), read at four sites in `_proxy_engine_request`. |\n| `client/frontend/src/pages/video-page/index.ts` | `loadVideo` \u2192 `renderVideo(metadata)`. Coordinator `startVideoLoad` with rank arbitration. Shared instance-config promise. Embed and reaction guards. `fetchVideoMetadataFromServer(path, source)`. `fetchVideoMetadata` removed. |\n| Docs | `engine/server/README.md`, `README.md`, `client/README.md`, `client/frontend/README.md`, `DEPLOYMENT.md`, issue/roadmap comments, per the settled checklist. |\n\n`dist/` is regenerated by the build.\n\n---\n\n### Engine: `engine/server/api/handlers/video.py`\n\n**Module docstring**\n\n```python\n\"\"\"Video metadata endpoint handlers.\n\nResponsibilities:\n- Resolve video row by id/uuid/host.\n- /api/video: answer from the DB row only, with no instance call and no write.\n- /api/video/refresh: fetch live instance metadata, merge it over the row field by field, persist it when the instance answered, and answer the same shape.\n\"\"\"\n```\n\n**New imports**, in the file's existing style:\n\n```python\nfrom data.db import statement_deadline\nfrom server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS\n```\n\n**`fetch_instance_video_dynamic`: success signal.** Only line 164 changes; the rest of the function is untouched.\n\n```python\n    detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\")\n    # An empty dict tells the caller the instance did not answer, so nothing is persisted.\n    if not isinstance(detail, dict) or not detail:\n        return {}\n```\n\n- Invariant: it returns `{}` if and only if the detail call failed or came back as a non-dict or empty JSON value. Otherwise it returns today's 14-key dict.\n- A non-dict JSON body no longer reaches `detail.get` and raises `AttributeError`.\n- The channel sub-call now runs only on success. When it fails, the channel fields fall back to the DB in the merge, and the result still counts as success.\n\n**`resolve_video_row`**, which takes lines 210-224 and 226:\n\n```python\ndef resolve_video_row(\n    handler: Any,\n    server: Any,\n    params: dict[str, list[str]],\n) -> tuple[dict[str, Any], str, str] | None:\n    \"\"\"Resolve the requested row, or answer 400/404 and return None.\n\n    Returns the row, the requested id and the instance domain the merge and refresh use.\n    \"\"\"\n    id_param = params.get(\"id\", params.get(\"video_id\", [None]))[0]\n    host_param = params.get(\"host\", params.get(\"instance_domain\", [None]))[0]\n    if not id_param:\n        respond_json(handler, 400, {\"error\": \"Missing video id\"})\n        return None\n    with server.db_lock:\n        row = fetch_video_row(\n            server.db,\n            id_param,\n            host_param,\n            error_threshold=server.video_error_threshold,\n        )\n    if not row:\n        respond_json(handler, 404, {\"error\": \"Video not found\"})\n        return None\n    instance_domain = row.get(\"instance_domain\") or host_param or \"\"\n    return row, id_param, instance_domain\n```\n\nThe lock covers the SELECT only.\n\n**`merge_video_metadata`**, which takes lines 229-290 verbatim:\n\n```python\ndef merge_video_metadata(\n    row: dict[str, Any],\n    dynamic: dict[str, Any],\n    instance_domain: str,\n) -> tuple[dict[str, Any], dict[str, Any]]:\n    \"\"\"Merge live `dynamic` fields over the DB row, field by field.\n\n    Returns the response payload and the merged column values the persist step writes.\n    An empty `dynamic` gives the DB-only answer.\n    \"\"\"\n    # lines 229-290 unchanged: title \u2026 nsfw, channel_url, embed_url, original_url, response\n    merged = {\n        \"title\": title,\n        \"description\": description,\n        \"channel_display\": channel_display,\n        \"channel_slug\": channel_slug,\n        \"channel_followers\": channel_followers,\n        \"views\": views,\n        \"likes\": likes,\n        \"dislikes\": dislikes,\n        \"tags_json\": tags_json,\n        \"category\": category,\n        \"nsfw\": nsfw,\n    }\n    return response, merged\n```\n\n- **The impact inventory's open point.** `merged` carries the raw intermediates, `None` included, so persist writes `NULL` where today's code writes `NULL` and never the response's `\"\"`.\n- The function is pure: no DB access and no I/O.\n- With `dynamic={}`, every `dynamic.get` is `None`, so each field falls back to the row exactly as today, and `accountAvatarUrl` is `\"\"`.\n\n**`persist_video_metadata`**, which takes lines 294-358:\n\n```python\ndef persist_video_metadata(\n    server: Any,\n    row: dict[str, Any],\n    instance_domain: str,\n    merged: dict[str, Any],\n) -> None:\n    \"\"\"Write a successful refresh to the videos, channels and instances tables.\n\n    The writes run under a fresh statement budget taken once the DB lock is held, because the request's own budget is mostly spent on the instance calls by then.\n    \"\"\"\n    checked_at = now_ms()\n    popularity = compute_popularity(\n        merged[\"views\"],\n        merged[\"likes\"],\n        row.get(\"published_at\"),\n        float(getattr(server, \"popularity_like_weight\", 2.0)),\n        now_ms_value=checked_at,\n    )\n    channel_id = row.get(\"channel_id\")\n    try:\n        with server.db_lock:\n            with statement_deadline(\n                float(getattr(server, \"statement_timeout_seconds\", DEFAULT_STATEMENT_TIMEOUT_SECONDS))\n            ):\n                with server.db:\n                    # today's three UPDATEs, parameters read from `merged` and `row`, unchanged SQL\n    except sqlite3.OperationalError as exc:\n        logging.warning(\n            \"[video] failed to persist dynamic metadata for video_id=%s host=%s: %s\",\n            row.get(\"video_id\"),\n            instance_domain,\n            exc,\n        )\n```\n\n- **Why the nested deadline.** The settled db.py entry picks this mitigation. Without it the outer deadline has usually expired after roughly 16 s of instance calls, and the FTS trigger's UPDATE could be interrupted, which silently breaks R2's persist.\n- **Why it sits inside `db_lock`.** Time spent waiting for the lock does not use up the new budget.\n- **Nesting is safe.** `statement_deadline` restores the outer deadline on exit (db.py:59-64).\n- **The rest is today's code.** The SQL, the parameter order, the `channels` UPDATE only when `channel_id` is set, the `instances` reset, and the catch-and-log.\n\n**Route handlers**\n\n```python\ndef handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:\n    \"\"\"Handle /api/video: answer from the DB row only, with no instance call and no write.\"\"\"\n    resolved = resolve_video_row(handler, server, params)\n    if resolved is None:\n        return True\n    row, _id_param, instance_domain = resolved\n    response, _merged = merge_video_metadata(row, {}, instance_domain)\n    respond_json(handler, 200, response)\n    return True\n\n\ndef handle_video_refresh_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:\n    \"\"\"Handle /api/video/refresh: fetch live metadata, persist it when the instance answered, answer the merge.\n\n    This is the single per-request metadata write path; issue 10 extends it.\n    \"\"\"\n    resolved = resolve_video_row(handler, server, params)\n    if resolved is None:\n        return True\n    row, id_param, instance_domain = resolved\n    # The instance calls run outside the DB lock, so a slow instance never stalls other routes.\n    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else {}\n    response, merged = merge_video_metadata(row, dynamic, instance_domain)\n    if dynamic and instance_domain and row.get(\"video_id\"):\n        persist_video_metadata(server, row, instance_domain, merged)\n    respond_json(handler, 200, response)\n    return True\n```\n\n- Keeping the name `handle_video_request` means the import at similar.py:84 cannot break.\n- The `if dynamic` guard is now meaningful, because a failed fetch returns `{}`.\n\n### Engine: `engine/server/api/handlers/similar.py`\n\n- **Line 84:** `from handlers.video import handle_video_refresh_request, handle_video_request`.\n- **After line 497:**\n  ```python\n          if url.path == \"/api/video/refresh\":\n              handle_video_refresh_request(self, self.server, params)\n              return\n  ```\n- **Docstring lines 9-10:**\n  - `- /api/video: single video metadata from the local DB (no instance call).`\n  - `- /api/video/refresh: live instance refresh of one video's metadata, persisted on success.`\n- **Unchanged:** the rate limit at 447 (its own `ip:/api/video/refresh` bucket), the statement deadline in `do_GET`, and the similars dispatch.\n\n### Engine: `engine/server/api/handlers/__init__.py`\n\nLine 5 becomes: `- video: /api/video (DB only) and /api/video/refresh (live instance refresh, persisted on success).`\n\n---\n\n### Client backend: `client/backend/server.py`\n\n**Constants**, next to lines 77-101:\n\n```python\nENGINE_PROXY_TIMEOUT_SECONDS = 10\n# The refresh waits on up to two 8 s instance calls in the Engine, and a retry would repeat them and the write.\nENGINE_PROXY_ROUTE_TIMEOUT_SECONDS: dict[str, float] = {\"/api/video/refresh\": 20}\nENGINE_PROXY_MAX_BODY_BYTES = 1_000_000\nENGINE_PROXY_RETRY_COUNT = 1\nENGINE_PROXY_ROUTE_RETRY_COUNT: dict[str, int] = {\"/api/video/refresh\": 0}\nENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25\nPROXY_READ_GET_ROUTES = frozenset(\n    (\"/api/video\", \"/api/video/refresh\", \"/api/channels\", \"/api/v1/search/videos\")\n)\nPROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {\n    ...\n    \"/api/video\": {\"id\", \"host\", \"refresh_cache\", \"user_id\"},\n    \"/api/video/refresh\": {\"id\", \"host\"},\n    ...\n}\n```\n\nThe plan asked for \"a path check on the retry count\". A second one-entry dict does the same job, with the same shape as the timeout mapping and one more place a test can monkeypatch.\n\n**`_proxy_engine_request`.** Two locals are resolved once, from `path` (never from `upstream`, which carries the query string), right after `upstream` is built. The mappings are module globals read at call time, so a test that patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` takes effect.\n\n```python\n        timeout_seconds = ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS.get(path, ENGINE_PROXY_TIMEOUT_SECONDS)\n        retry_count = ENGINE_PROXY_ROUTE_RETRY_COUNT.get(path, ENGINE_PROXY_RETRY_COUNT)\n```\n\nFour sites change:\n\n| Line | Before | After |\n|---|---|---|\n| 604 | `range(ENGINE_PROXY_RETRY_COUNT + 1)` | `range(retry_count + 1)` |\n| 606 | `timeout=ENGINE_PROXY_TIMEOUT_SECONDS` | `timeout=timeout_seconds` |\n| 696 | `attempt < ENGINE_PROXY_RETRY_COUNT` | `attempt < retry_count` |\n| 731 | `\"attempts\": ENGINE_PROXY_RETRY_COUNT + 1` | `\"attempts\": retry_count + 1` |\n\n- Every other route keeps 10 s and one retry.\n- `_handle_engine_read_proxy_get` and `_profile_filter` are unchanged. The refresh gets the same sanitising: an unknown or repeated key answers 400, and a `user_id` or `refresh_cache` on it now answers 400 too.\n\n**How a failed refresh reaches the browser:**\n- a timeout breaks the loop with 0 retries \u2192 502 `ENGINE_PROXY_UNAVAILABLE`;\n- a dropped Engine connection \u2192 502 `ENGINE_PROXY_FAILURE`;\n- an Engine 400 or 404 \u2192 passed through.\n\nThe page treats all of these as a failed refresh.\n\n---\n\n### Frontend: `client/frontend/src/pages/video-page/index.ts`\n\n**Module state.** These lines go next to `currentMetadata` (line 50-51). They must be declared before the coordinator call at line 79: the no-source path renders synchronously, and a `let` declared later would throw a TDZ error.\n\n```ts\ntype InstanceMetadata = Awaited<ReturnType<typeof fetchInstanceMetadata>>;\n// Which metadata source the panel shows; a source renders only if it ranks at least as high.\nconst METADATA_RANK = { params: 0, fast: 1, instance: 2, refresh: 3 } as const;\nlet shownRank = -1;\nlet instanceConfig: InstanceMetadata = null;\nlet instanceMetadata: Promise<InstanceMetadata> = Promise.resolve(null);\nlet lastEmbed = \"\";\nlet reactionKey = \"\";\n```\n\n**Start (line 79).** `void loadVideo();` becomes `startVideoLoad();`. Line 80, `void loadSimilarVideos();`, is unchanged, and the coordinator neither awaits nor chains it.\n\n**Coordinator**\n\n```ts\n/**\n * Start the three metadata sources at once: the Engine's DB answer, its live refresh, and the instance config. None awaits another.\n */\nfunction startVideoLoad() {\n  const source = resolveVideoSource();\n  if (!source?.host || !source.id) {\n    offerMetadata(METADATA_RANK.params, null);\n    return;\n  }\n  instanceMetadata = fetchInstanceMetadata(source.host);\n  void instanceMetadata.then((meta) => {\n    instanceConfig = meta;\n    if (meta && shownRank >= 0) renderVideo(currentMetadata);\n  });\n  void loadFastMetadata(source);\n  void loadRefreshedMetadata(source);\n}\n\n/**\n * Render `metadata` unless a higher-ranked source is already shown, so a late fast answer never overwrites refreshed values.\n */\nfunction offerMetadata(rank: number, metadata: VideoMetadata | null) {\n  if (rank < shownRank) return;\n  shownRank = rank;\n  renderVideo(metadata);\n}\n\n/**\n * Show the Engine's stored metadata, or the URL params and then the instance's own answer when the Engine has no row.\n */\nasync function loadFastMetadata(source: { host: string; id: string; url: string }) {\n  const metadata = await fetchVideoMetadataFromServer(\"/api/video\", source);\n  if (metadata) {\n    offerMetadata(METADATA_RANK.fast, metadata);\n    return;\n  }\n  offerMetadata(METADATA_RANK.params, null);\n  if (shownRank > METADATA_RANK.instance) return;\n  const instanceMeta = await fetchVideoMetadataFromInstance(source);\n  if (instanceMeta) offerMetadata(METADATA_RANK.instance, instanceMeta);\n}\n\n/**\n * Show live metadata once the Engine has refreshed it; a failure keeps what the panel shows.\n */\nasync function loadRefreshedMetadata(source: { host: string; id: string; url: string }) {\n  const metadata = await fetchVideoMetadataFromServer(\"/api/video/refresh\", source);\n  if (!metadata) {\n    console.warn(\"[video] metadata refresh failed; keeping the values shown\");\n    return;\n  }\n  offerMetadata(METADATA_RANK.refresh, metadata);\n}\n```\n\n- **No-source path.** It renders once with `null`, with no fetch and no config, exactly as today.\n- **Equal ranks re-render.** Equal-rank renders are allowed, which is what lets the config's re-render at the current rank through.\n- **`currentMetadata` stays in step.** It is set only inside `renderVideo`, so it always equals what is shown, and the config re-render reuses it.\n- **Skipped fallback.** If the refresh is already shown, the direct-instance fallback is not started at all.\n\n**`renderVideo(metadata: VideoMetadata | null)`.** This is today's `loadVideo` body without `await fetchVideoMetadata()`, and it is synchronous. Line 87 stays as the first statement: `currentMetadata = metadata;`. Three edits:\n\n1. **Instance avatar** (line 109) is taken from the shared config at render time, so it survives every re-render and also reaches rank 0:\n   `const instanceAvatarUrl = metadata?.instanceAvatarUrl || instanceConfig?.avatarUrl || \"\";`\n2. **Embed** (lines 212-221). The comparison is against our own last assigned string, and the guard is cleared when `src` is removed:\n   ```ts\n   if (embedEl) {\n     // The embed URL can come straight from the `?embed=` query parameter when metadata resolution fails, so a scheme check is what stops a `javascript:` URL from executing in this origin via iframe navigation.\n     const checkedEmbed = embed && /^https:\\/\\//i.test(embed.trim()) ? embed : \"\";\n     if (!checkedEmbed) {\n       embedEl.removeAttribute(\"src\");\n       lastEmbed = \"\";\n     } else if (checkedEmbed !== lastEmbed) {\n       // Reassigning an unchanged src would restart playback on every re-render.\n       embedEl.src = checkedEmbed;\n       lastEmbed = checkedEmbed;\n     }\n   }\n   ```\n3. **Everything else is unchanged:** `escapeHtml`/`safeExternalUrl` on every write, the `enableBlockButtons(...)` call (its `dataset.wired` guard makes re-renders no-ops), and `void loadReaction()`.\n\n**`loadReaction` gate.** The key is written only for a non-null video, and before the first `await`:\n\n```ts\nasync function loadReaction() {\n  const video = reactionVideo();\n  if (!video || !likeButton || !dislikeButton) return;\n  // Re-renders call this again; the visitor's reaction is read once per video.\n  const key = `${video.uuid}|${video.host}`;\n  if (key === reactionKey) return;\n  reactionKey = key;\n  try {\n    await localLikesImported;\n    ...unchanged\n```\n\nA rank-0 render with a non-UUID `seedId` returns `null` and leaves the gate open, so a later rank that carries `videoUuid` still fetches and wires the buttons.\n\n**`fetchVideoMetadataFromServer(path, source)`**\n\n- Signature: `async function fetchVideoMetadataFromServer(path: string, source: { host: string; id: string; url: string }): Promise<VideoMetadata | null>`.\n- `new URL(path, apiBase)`, with only `id` and `host` set, as today. The refresh allow-list accepts exactly these.\n- `await fetchInstanceMetadata(source.host)` (line 525) is removed.\n- The instance fields become:\n  ```ts\n  instanceName: (data.instanceName as string | undefined) ?? source.host,\n  instanceUrl: (data.instanceUrl as string | undefined) ?? `https://${source.host}`,\n  instanceAvatarUrl: \"\",\n  ```\n  The Engine always sends both as strings (video.py:279-280), so `instanceMeta?.name`/`url` could never win here today. Dropping them keeps what is visible, and the avatar now comes from `instanceConfig` in `renderVideo`.\n- `catch { return null; }` is unchanged. `null` is the failure signal both callers use.\n\n**`fetchVideoMetadataFromInstance`.** Line 600 becomes `const instanceMeta = await instanceMetadata;`, which awaits the shared promise instead of issuing a second `/api/v1/config` request. The effect on R4:\n- This source ranks 2 and runs only after rank 0 has rendered, so the wait is never on the first-render path.\n- It keeps today's rank-2 precedence exactly, with the config's name and URL winning.\n\n**Removed:** `loadVideo` and `fetchVideoMetadata`, whose sequencing moved into the coordinator. `loadSimilarVideos` and the similars helpers are untouched (R7).\n\n---\n\n### What the build needs to test\n\n**Engine: new `tests/active/test_video_metadata.py`.** Each case runs in an `ENGINE_PY` child over a temporary DB, following `test_internal_events.py:52` / `test_similar.py`. The child uses a real `SimilarServer` with `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`. The patch goes on `handlers.video.fetch_instance_json`, never the shared `engine` fixture.\n- **Fast route.**\n  - `/api/video` answers the DB fields with the shape unchanged, `accountAvatarUrl == \"\"`, the channel URL built from slug + host, and the original URL built from uuid + host.\n  - The stub is never called.\n  - `last_checked_at` and `instances.last_error` are unchanged.\n- **Errors on both routes.** 400 `Missing video id` and 404 `Video not found`.\n- **Successful refresh.** It answers the instance values, including `accountAvatarUrl`. The `videos`, `channels` and `instances` rows are updated, with `last_error*` set to NULL. A failed channel sub-call still persists, with the DB channel fields.\n- **Failed refresh.** Detail `None`, `{}`, a JSON list and a raised `URLError` each answer 200 with DB values and change no row.\n- **Deadline.** With `statement_timeout_seconds` around 0.2 and a stub that sleeps 0.5 s, a successful refresh still persists.\n- **R7.**\n  - Setup: a stub that blocks about 5 s, and a refresh started on a thread.\n  - The id-based similars GET is answered in well under 5 s.\n  - The stub's call log holds only the refresh's paths.\n\n**Client proxy: added to `tests/active/test_server.py`,** using `EngineStub`, `_serving`, `_client_backend` and `_status`:\n- `/api/video/refresh` forwards `id`/`host` and answers 400 on `user_id`, `refresh_cache` or a repeated key;\n- with both mappings patched to a small timeout, a sleeping stub sees exactly one refresh GET and the browser gets 502;\n- `/api/video` against a sleeping stub still makes two attempts;\n- `/api/video` keeps the 10 s default (assert the mapping lookup).\n\n**Frontend: new `tests/active/test_frontend_video_page.py`.** The page is bundled with esbuild (`--platform=node`, css loader `empty`) and driven with a stubbed `document`/`window`/`localStorage` and a scripted `fetch`, following `test_frontend_blocks.py`. It asserts:\n- the first render happens before `/api/v1/config` resolves;\n- whichever of refresh and fast arrives first, the refreshed values end up shown;\n- a failed refresh keeps the values shown and calls `console.warn`;\n- a fast 404 renders the URL params, then the instance data;\n- `src` is assigned once across the rank 1 \u2192 3 renders;\n- `fetchReaction` is called once;\n- a `javascript:` embed is never assigned;\n- similars are fetched with `limit=8` regardless of metadata timing.\n\nIf the stubbing proves too heavy, the plan's own escape hatch applies: extract `offerMetadata`'s rank rule into a lib module.\n\n**At harvest:** `.un/skills/devsecops/config.json` maps the new files to `video.py`, `similar.py`, `server.py` and `video-page/index.ts`.\n\n---\n\n### Check against the plan and requirements\n\nThis took two passes; the first found gaps and the second closed them.\n\n| Item | Met by |\n|---|---|\n| R1 | `merge_video_metadata(row, {}, \u2026)`, no fetch, no write. 400/404 through the shared resolver. |\n| R2 | Separate route and handler. Same resolver. `fetch_instance_video_dynamic` unchanged except the success signal. Persist only when `dynamic` is non-empty, with today's SQL and catch. Same response shape. The proxy's own allow-list `{id, host}`. |\n| R3 | Three independent starts. The rank rule keeps refreshed values over a late fast answer. A failed refresh is `console.warn` only. |\n| R4 | No first-render path awaits `/api/v1/config`. The avatar fills in through the shared promise's re-render. The chip uses host initials until then. |\n| R5 | Fast failure renders rank 0 at once, then rank 2. The `https://` check sits inside `renderVideo`, which every path passes through. |\n| R6 | `lastEmbed` guard. `dataset.wired` guards unchanged. `reactionKey` gate written before the first await. Escaping unchanged. |\n| R7 | Similars code untouched. The instance calls run outside `db_lock`. Covered by the Engine R7 test. |\n| Budget constraint | 20 s, no retry, refresh only. A proxy failure degrades per R3. |\n| Stdlib / style / dist | Stdlib only. No new dependency. Module-level functions in the files' style. `dist` rebuilt. |\n\n**What pass 1 missed, and pass 2 fixed:**\n- **Persist intermediates.** Solved by returning a `merged` dict instead of feeding persist from the response.\n- **Persist under an expired deadline.** Nested `statement_deadline` inside `db_lock`.\n- **TDZ.** The coordinator's state is declared before line 79.\n- **Reaction gate.** Written before the `await` and only for a non-null video.\n- **Line 731 log.** Now uses `retry_count`.\n\n### Named simplifications and residual limits\n\n- **Rank rule is one number.** It has no per-field merge: a higher-ranked source replaces the whole panel. That is enough because the refresh answers a superset of the fast answer. The ceiling: a future partial refresh would need per-field precedence.\n- **Refresh failure is a bare `null`.** The console warning carries no reason; the status can be logged later if diagnosis needs it.\n- **Engine's late write after a Client timeout.** `respond_json` writes to a closed socket and prints a `BrokenPipeError` traceback. This is pre-existing log noise and is left as is; the persist has already run.\n- **Different uuid on a later render.** The reaction and block listeners keep the first video they captured. If a later rank reported a different uuid, which should not happen for one row, the reaction is re-read for the new key but clicks still act on the first video. This is unchanged from today.\n- **Deviations from the settled plan text, both taken from the settled impacts.**\n  - Persist gains a nested statement deadline; the plan said \"unchanged\".\n  - The rank-2 fallback awaits the shared config promise rather than not awaiting it at all. This keeps today's rank-2 name/URL precedence and stays off the first-render path.\n\n</draft>",
    "step_6_develop_phase_breakdown": "<phases>\n<phase n=\"1\" kind=\"code\">\n<checkpoint>Seam: the Engine's HTTP handler over a real DB. New `tests/active/test_video_metadata.py` runs each case in an `ENGINE_PY` child over a temporary DB, following the `subprocess.run([str(ENGINE_PY), \"-c\", CHILD, ...], cwd=API_DIR)` pattern of `test_similar.py` / `test_internal_events.py`. The child builds a real `SimilarServer` carrying `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`, and patches `handlers.video.fetch_instance_json` with a recording stub (never the shared `engine` fixture). It asserts over GET `/api/video/refresh`: (a) with the stub answering detail + channel JSON, the response carries today's response keys with the instance's values, `accountAvatarUrl` included, the channel URL built from slug + host and the original URL from uuid + host. (b) With the detail JSON omitting fields (e.g. no `description`, no `tags`) and the channel sub-call answering `None`, those fields and the channel fields come from the seeded DB row. Guards: 400 `Missing video id` with no id, and 404 `Video not found` for an unknown id; and `/api/video` against the same answering stub still returns the instance's values (today's live behaviour kept until the follow-up plan).</checkpoint>\n<name>Engine refresh route</name>\n<intent>`engine/server/api/handlers/video.py` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`, and a new `handle_video_refresh_request`, dispatched from `SimilarHandler`'s GET branch in `similar.py`, answers `/api/video/refresh` with the instance's live values merged over the DB row field by field, while `/api/video` keeps today's live behaviour through the same functions.</intent>\n<clause_1>`/api/video/refresh` answers the instance's live values in today's `/api/video` response shape.</clause_1>\n<clause_2>A field the instance did not supply in a refresh falls back to the DB row's value.</clause_2>\n<files>engine/server/api/handlers/video.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), tests/active/test_video_metadata.py (NEW)</files>\n</phase>\n<phase n=\"2\" kind=\"code\">\n<checkpoint>Seam: the same `ENGINE_PY`-child harness in `tests/active/test_video_metadata.py`, going through the HTTP handler and reading the DB afterwards. (a) Persist on success: the stub answers detail JSON, and after `/api/video/refresh` the `videos`, `channels` and `instances` rows hold the instance's values, with `instances.last_error*` NULL. A failed channel sub-call still persists, with the DB channel fields. With `statement_timeout_seconds` about 0.2 and a stub that sleeps 0.5 s before answering, the rows are still updated. (b) No write on failure: parametrized over a detail answer of `None`, `{}`, a JSON list, and a raised `URLError`. Each answers 200 with the DB values, and the `videos`, `channels` and `instances` rows (including `last_checked_at` and `last_error`) are identical before and after. (c) R7: with a stub that blocks about 5 s, a refresh is started on a thread; the id-based similars GET then returns 200 in well under 5 s, and the stub's call log holds only the refresh's `/api/v1/videos/...` paths.</checkpoint>\n<name>Refresh persists only on instance success</name>\n<intent>`fetch_instance_video_dynamic` returns `{}` when the video detail call did not answer, so `handle_video_refresh_request` writes the merge through `persist_video_metadata`, under its own statement deadline, only when the instance answered, and its instance calls run outside `db_lock`, so a slow refresh leaves the similars route answering.</intent>\n<clause_1>A refresh updates the videos, channels and instances rows only when the instance's video detail call answered.</clause_1>\n<clause_2>A refresh blocked on a slow instance does not delay the similars route's answer.</clause_2>\n<files>engine/server/api/handlers/video.py (EDITED), tests/active/test_video_metadata.py (EDITED)</files>\n</phase>\n<phase n=\"3\" kind=\"code\">\n<checkpoint>Seam: the Client backend's HTTP proxy in front of a stub Engine. Added to `tests/active/test_server.py`, using its `EngineStub(BaseHTTPRequestHandler)` + `_serving(ThreadingHTTPServer(...))` + `_client_backend(tmp_path, engine_base, RateLimiter(1000, 60))` + `_status` harness (precedent: `test_engine_receives_the_resolved_address_as_x_client_ip`). (a) GET `/api/video/refresh?id=\u2026&host=\u2026` reaches the stub with exactly those two params. Adding `user_id`, adding `refresh_cache`, or repeating `id` each answers 400, and the stub records no request. (b) With `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` monkeypatched to about 0.3 s for the refresh and a stub that sleeps past it, the browser gets 502 and the stub counts exactly one refresh GET. Guard: `/api/video` against the same sleeping stub (with `ENGINE_PROXY_TIMEOUT_SECONDS` patched small) counts two attempts.</checkpoint>\n<name>Client proxy for the refresh route</name>\n<intent>`client/backend/server.py` proxies `/api/video/refresh` as a read route with its own `{id, host}` allow-list, and `_proxy_engine_request` gives it a 20 s timeout and zero retries through the per-path mappings while every other route keeps 10 s and one retry.</intent>\n<clause_1>The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400.</clause_1>\n<clause_2>A refresh that times out at the proxy is sent to the Engine once and answered 502.</clause_2>\n<files>client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)</files>\n</phase>\n</phases>\n\n<needs_coordination>\nnone\n</needs_coordination>\n\n<rationale>\nThe work carries six independently observable behaviours, which do not fit in four phases of at most two clauses each. With the operator's approval, it is split into two plans on a seam that causes no regression in between.\n\nThis plan (A) is purely additive. It adds the Engine's `/api/video/refresh` route (P1). It adds the success-gated persist, with its nested statement deadline, and the R7 guard (P2). It exposes the route through the Client proxy with its own allow-list, a 20 s timeout and no retry (P3). No caller uses the new route yet. `/api/video` keeps today's live fetch-and-persist behaviour through the newly split `resolve_video_row` / `merge_video_metadata` / `persist_video_metadata`. The one visible change on `/api/video` is the corrected success signal: a failed instance fetch no longer writes. That is R2's accepted tradeoff arriving early, not a regression. P1's checkpoint guards that `/api/video` still answers live values.\n\nThe follow-up plan (B), recorded for the next build, finishes the settled design in three phases:\n- `/api/video` becomes DB-only: no instance call, no row changed (R1).\n- The page coordinator and rank rule in `video-page/index.ts`: the first render waits on no other source (R4/R5), and the refreshed values win in either arrival order (R3). Tested on the node-bundled page following `test_frontend_blocks.py`.\n- The `lastEmbed` and `reactionKey` re-render guards (R6).\n\nB ships the DB-only fast route together with the frontend that calls the refresh. So metadata is never left without a refresh path, which was the regression that ruled out the earlier Engine/frontend split.\n\nOrder within A follows the dependencies. P1 creates the split functions and the route. P2 gives persist its success gate and deadline. P3 needs the Engine route to exist before proxying it.\n\nDocs get no phase: `engine/server/README.md`, the READMEs, `DEPLOYMENT.md` and the issue and roadmap notes are updated at Step 9. The `dist/` rebuild and the devsecops config mapping happen at harvest. The checkpoints need only the existing local engine `.pixi` env.\n</rationale>",
    "author:tests/tmp/test_11_fast_similars_response_phase1.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C2e\">\n<disposition>fixed</disposition>\n<what>Added OMITTING, the complement of PARTIAL. The detail has no `name`, `likes` or `dislikes`, but it supplies its own description \"Live description B\", views 900, channel displayName \"Live Chan B\" and followersCount 60, and the channel call answers None. test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted now runs it as a second case. :160 asserts (title, likes, dislikes) == (\"DB title\", 2, 1), the row's values. That excludes an instance-only merge, which reads (\"\", None, None). :161 pins the whole eighteen-key body. Its expected values were observed from today's /api/video over the same stub. Between PARTIAL (:153) and OMITTING (:160), all seven instance-sourced fields that have a row counterpart now get a fallback assertion.</what>\n</item>\n<item id=\"D4\">\n<disposition>fixed</disposition>\n<what>test_refresh_answers_the_instances_values_in_the_api_video_shape now runs a second refresh that requests the row by its video_id: `/api/video/refresh?id=v1&host=tube.example`. The stub map is BY_VIDEO_ID, which is ANSWERING plus `/api/v1/videos/v1` \u2192 DETAIL, so the detail answers under either id and the case turns only on URL sourcing. :144 asserts (200, LIVE), whose originalUrl is `https://tube.example/videos/watch/uuid-v1`. That excludes building the original URL from the query id, which reads `.../watch/v1`. The value was observed: today's /api/video?id=v1 over the same map answered exactly LIVE. The docstring bullet now says so.</what>\n</item>\n<item id=\"D5c\">\n<disposition>fixed</disposition>\n<what>The same by-video_id case carries this row. :144 whole-dict equality against LIVE requires videoUuid \"uuid-v1\" and embedUrl `https://tube.example/videos/embed/uuid-v1`, which come from the row's video_uuid and embed_path. Building either from the requested id reads \"v1\" or `.../embed/v1` and fails. The value was observed from today's /api/video?id=v1. The docstring now says \"Requested by the row's video id rather than its uuid, it answers the same, so uuid, embed and original URL come from the row and not from the query id.\"</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, C2e: title/likes/dislikes fallback never exercised): added the OMITTING case, a detail with no name/likes/dislikes. :160 asserts (\"DB title\", 2, 1) against the instance-only (\"\", None, None), and :161 pins the full body. Observed from today's /api/video before writing.\nClaim RECOMMENDATION 1 (D4/D5c sources indistinguishable) taken: added a refresh requested by video_id \"v1\" and asserted (200, LIVE) at :144, so uuid, embed and original URL built from the query id fail. Observed from today's /api/video?id=v1.\nClaim RECOMMENDATION 4 (docstring opening sentence missing its verb) taken: it now reads \"and answers a field the instance omitted from the row's value.\"\nShape audit: no CRITICAL. The new assertions compare against literals observed from a run, not against anything built from production's own table, and the edited file still fails 3 / passes 1 for the same reason as before (see answer 7).\nProbe files tests/tmp/probe_11_video_metadata.py and tests/tmp/probe_11_remediation.py are still on disk, because no tool I have can delete a file. Both need removing.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:140 \u2014 refresh over ANSWERING answers (200, LIVE): all eighteen /api/video keys with the instance's values; :142 \u2014 calls are [detail by uuid, channel by live_slug]; :144 \u2014 refresh requested by video_id \"v1\" over BY_VIDEO_ID answers (200, LIVE)</assertion>\n<expected>(200, LIVE), with title \"Live title\", views 1000, likes 50, dislikes 3, channelName \"Live Chan\", subscribersCount 77 (only from the channel call), accountAvatarUrl `.../avatars/live.png`, and videoUuid/embedUrl/originalUrl on uuid-v1 even when requested by \"v1\". Calls: [[\"tube.example\", \"/api/v1/videos/uuid-v1\"], [\"tube.example\", \"/api/v1/video-channels/live_slug\"]].</expected>\n<wrong_implementation>Unrouted refresh: 404 {\"error\": \"Not found\"}. Row-only answer: \"DB title\", views 10, accountAvatarUrl \"\". Skipping the channel call: subscribersCount 70. Building uuid, embed or original URL from the query id: \"v1\", `.../embed/v1`, `.../watch/v1`, which fails :144.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:153 \u2014 PARTIAL: (description, views, channelName, subscribersCount) == (\"DB description\", 10, \"DB Chan\", 5); :155 \u2014 (title, likes, dislikes) == (\"Live title B\", 0, 3); :160 \u2014 OMITTING: (title, likes, dislikes) == (\"DB title\", 2, 1); :156 and :161 pin the full eighteen-key bodies</assertion>\n<expected>Every one of the seven instance-sourced fields with a row counterpart falls back to the row when omitted. PARTIAL gives \"DB description\", 10, \"DB Chan\", 5. OMITTING gives \"DB title\", 2, 1. A supplied likes 0 is kept as 0.</expected>\n<wrong_implementation>An instance-only merge reads (\"\", None, \"\", None) at :153 and (\"\", None, None) at :160. A truthiness fallback reads likes 2 at :155.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. Every no-call assertion (:166, :168) pairs with a status and body that only the routed handler produces. The partial cases carry call-list controls (:150, :158) and 200 preconditions. With the code under test deleted, every refresh assertion fails on 404 {\"error\": \"Not found\"}.\n2. No. Expected values are literals: LIVE and the OMITTING/PARTIAL overrides, all observed from today's /api/video over the same stubs. The test does not recompute any merge. Deleting the refresh route, or its row fallback for title/likes/dislikes, turns :140/:144/:160 red.\n3. No. Fallback is read on two complementary partial details, and URL/uuid sourcing on two request ids (uuid and video_id). Every row value differs from every instance value.\n4. No. The only double is `handlers.video.fetch_instance_json`, the network boundary to a remote PeerTube instance. The server, handler, DB layer and merge are all real.\n5. Yes, it collects: 4 tests, and the run shows 3 failed, 1 passed. The new names OMITTING and BY_VIDEO_ID are defined at module level, and `_get` already takes *cases.\n6. Yes. The OMITTING body and the by-video_id body were both printed by probe tests/tmp/probe_11_remediation.py, which runs today's /api/video with these exact stubs. The first answered title \"DB title\", likes 2, dislikes 1, description \"Live description B\", views 900, channelName \"Live Chan B\", subscribersCount 60 and accountAvatarUrl \"\". The second answered exactly LIVE, with calls to /api/v1/videos/v1 and then the channel.\n7. Yes. ValidateTests on the file: the refresh tests fail at :140 and :149 on 404 {\"error\": \"Not found\"}, and at :166 on 404 vs 400. The /api/video guard passes. That is the same red, for the unbuilt route.\nNo rewrite was needed. The edits were the ledger fixes above.\n</answers>",
    "self_check:tests/tmp/test_11_fast_similars_response_phase1.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:136 \u2014 GET `/api/video/refresh?id=uuid-v1&host=tube.example`, with the stub answering the detail (DETAIL) and the channel (CHANNEL), answers `(200, LIVE)`. LIVE has exactly the eighteen `/api/video` keys and the instance's values: title \"Live title\", description \"Live description\", views 1000, likes 50, dislikes 3, channelName \"Live Chan\", subscribersCount 77, and accountAvatarUrl `https://tube.example/lazy-static/avatars/live.png`. channelUrl is built from the instance slug plus the host (`.../video-channels/live_slug`) and originalUrl from the row's uuid plus the host. The keys today's merge takes from the row (videoUuid, channelAvatarUrl, accountName, accountUrl, embedUrl, publishedAt) carry the row's values.</assertion>\n<expected>(200, LIVE). I did not guess this value. Today's `/api/video` answered it with the same stub and seed: the probe's first report, and `test_api_video_still_answers_the_instances_values`, which passed in this run. The refresh is planned to use the same merge.</expected>\n<wrong_implementation>Route not added: seen in this run as `(404, {'error': 'Not found'})`. The refresh answers from the row with no live merge (`dynamic={}`): title \"DB title\", views 10, likes 2, dislikes 1, channelName \"DB Chan\", subscribersCount 5, accountAvatarUrl \"\". The refresh answers `fetch_instance_video_dynamic`'s own dict instead of the `/api/video` shape: snake_case keys like `channel_display` and `account_avatar_url`, and videoUuid, embedUrl and publishedAt are missing. Each of these differs from LIVE.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:138 \u2014 the refresh's instance calls are exactly `[[\"tube.example\", \"/api/v1/videos/uuid-v1\"], [\"tube.example\", \"/api/v1/video-channels/live_slug\"]]`: the detail for the requested id, then the channel for the slug the detail named.</assertion>\n<expected>`[[HOST, \"/api/v1/videos/uuid-v1\"], [HOST, \"/api/v1/video-channels/live_slug\"]]`, seen in the probe's first report for today's live fetch.</expected>\n<wrong_implementation>If the refresh skips the channel sub-call, the list holds only the detail path, and subscribersCount reads 70 (the detail's `followersCount`), not 77. If it fetches by the row's `video_id` (\"v1\") instead of the requested id, the path reads `/api/v1/videos/v1`. If it takes the slug from the DB (`db_slug`), the second path reads `/api/v1/video-channels/db_slug`. If the route does not exist, the list is `[]`.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:147 \u2014 the detail omits `description` and `views` and gives a channel with no displayName or followers, and the channel call answers None. The refresh then answers description, views, channelName and subscribersCount as the row's `(\"DB description\", 10, \"DB Chan\", 5)`.</assertion>\n<expected>(\"DB description\", 10, \"DB Chan\", 5). The probe's second report showed exactly these for today's merge over the same PARTIAL detail.</expected>\n<wrong_implementation>A merge that takes only the instance's fields, with no row fallback, reads `(\"\", None, \"\", None)`, because the response maps None to \"\" for text and passes numbers through. Dropping the `channel_display_name` step from the fallback chain reads channelName \"DB Chan\" from `videos.channel_name`, the same string in this seed, so that variant is not separated here. The other three fields still separate it.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:149 \u2014 in the same partial refresh, the fields the instance did supply still win: `(title, likes, dislikes) == (\"Live title B\", 0, 3)`. likes 0 is supplied and falsy.</assertion>\n<expected>(\"Live title B\", 0, 3), seen in the probe's second report.</expected>\n<wrong_implementation>A truthiness fallback (`dynamic.get(\"likes\") or row.get(\"likes\")`) reads likes 2, the row's value. A fallback that prefers the row, or answers the row alone, reads `(\"DB title\", 2, 1)`.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:150 \u2014 the whole partial-refresh body equals `{**LIVE, \"title\": \"Live title B\", \"description\": \"DB description\", \"channelName\": \"DB Chan\", \"subscribersCount\": 5, \"accountAvatarUrl\": \"\", \"views\": 10, \"likes\": 0}`. That is the same eighteen keys, with every other value (channelUrl from the instance slug, dislikes 3, row-sourced keys) unchanged.</assertion>\n<expected>That dict, identical key for key to the probe's second report.</expected>\n<wrong_implementation>A merge that builds channelUrl from the DB slug when the instance's channel lacks a display name reads `.../video-channels/db_slug`. A refresh answering a different shape adds or drops keys. accountAvatarUrl filled from anywhere but the instance reads non-empty.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. C1 (live values in `/api/video`'s shape) is carried by :136, which is full equality with the eighteen-key LIVE, every live value distinct from the row's, and by :138, the call sequence that is the only way to reach 77. C2 (a field the instance omitted falls back to the row) is carried by :147 for the omitted fields, :149 for supplied fields still winning, including a falsy 0, and :150 for the whole body. The docstring's other two bullets have their own tests: the refusal guards at :155/:157, and the `/api/video`-stays-live guard at :163/:164. Every docstring clause maps to an assertion.\n2. Absence only: no. The one negative is `calls == []` at :155/:157. Each is inside the same tuple as a positive status and body, 400 \"Missing video id\" or 404 \"Video not found\", which only the refresh handler's resolver produces. That body is the control proving the route ran. The unrouted path reads 404 \"Not found\", which the tuple tells apart. The stub's recording is shown working by :138/:144 in the identical CHILD.\n3. Echoed literal: no. LIVE and PARTIAL are fixed literals, and the test performs no merge. Lines whose deletion turns it red: the `/api/video/refresh` branch the phase adds to `SimilarHandler._dispatch_get` (all rows); for the live values, `title = dynamic.get(\"title\") or row.get(\"title\")` (video.py:229) and `\"accountAvatarUrl\": dynamic.get(\"account_avatar_url\") or \"\"` (video.py:283), which move into the merge; for C2, the row halves of video.py:230 (description), 232-233 (views), 243 (channel_display_name) and 248-249 (followers).\n4. One value: no. Each C2 field is read at two inputs: supplied (test 1: \"Live description\", 1000, \"Live Chan\", 77) and omitted (test 2: \"DB description\", 10, \"DB Chan\", 5). likes is read at 50 and at a supplied 0. Each expected value is an independent literal, never pinned against another field of the same response.\n5. The double: no. The only double replaces `handlers.video.fetch_instance_json`, the one function that does `urlopen` to a third-party PeerTube instance. That is the severed network layer, and the plan names it as the seam. Everything the project owns runs for real: `SimilarServer`, `SimilarHandler`, dispatch, `fetch_video_row`, `fetch_instance_video_dynamic` and the merge, over a real SQLite DB built by `sync-whitelist.py`'s own schema functions.\n6. It collects: yes. The raw collect output in tests/last_test_output.txt shows 4 tests collected, matching the four test functions; the \"no tests\" line is the runner's summary of a collect-only run. In this run the control at :129 passed, so the CHILD's imports (`server`, `data.db.connect_db`, `handlers.video`, `handlers.similar.SimilarHandler`), the `SimilarServer` kwargs and `sync_job.ensure_whitelist_schema`/`ensure_content_schema` all resolved and bound.\n7. Observed, not predicted: yes, all observed. I re-ran `tests/tmp/probe_11_video_metadata.py` with `ValidateTests` this turn. Its reports showed today's `/api/video` over the same seed and stub:\n   - ANSWERING: exactly LIVE, with calls [detail, channel/live_slug].\n   - PARTIAL: exactly the :150 dict, with calls [detail, channel/live_slug].\n   - Unrouted `/api/video/refresh`: 404 {\"error\": \"Not found\"}, calls [].\n   - No id: 400 {\"error\": \"Missing video id\"}.\n   - Unknown id: 404 {\"error\": \"Video not found\"}.\n   - statement_timeout_seconds: 5.0 on the built server.\n   One premise rests on the plan rather than a run: that the refresh answers the same merge as `/api/video` (the plan's `merge_video_metadata`). Nothing can observe it before the route exists. The implementation run confirms it.\nNo rewrite; the test file is unchanged. The probe is named probe_*.py, not test_*.py. I have no delete tool this turn, so it remains in tests/tmp for cleanup.\n8. Red, not green: yes, red. `ValidateTests tests/tmp/test_11_fast_similars_response_phase1.py` printed \"3 failed, 1 passed \u2026 recorded: tests/last_test_validation.json (exit 1)\", exit status 1. The one pass is the guard `test_api_video_still_answers_the_instances_values`, which is meant to be green today: `/api/video` keeps its live behaviour in this phase.\n9. Red for the right reason: yes. The harness control `assert run.returncode == 0` at :129 passed in all three failing tests, so the child built each server and ran each request. The failures:\n   - :136 `AssertionError: assert (404, {'error': 'Not found'}) == (200, {'video...e Chan', ...})`, \"At index 0 diff: 404 != 200\".\n   - :143 `AssertionError: {'error': 'Not found'} / assert 404 == 200`.\n   - :155 `AssertionError: assert (404, {'error...t found'}, []) == (400, {'error...ideo id'}, [])`, \"At index 0 diff: 404 != 400\".\n   Each is the dispatcher's unrouted answer for `/api/video/refresh`: the route does not exist yet. None is a typo, missing import, bad path or harness limit. :143 is the refresh's own status, a phase observable, not a harness control; it stops before :147/:149. Those two rows' expected values come from the probe's run over the same merge, not from this red.\n10. Observed expected output: each row's `expected` matches a run. :136 matches LIVE, as the probe's first report and the passing :163 showed. :138 matches the probe's calls. :147, :149 and :150 match the probe's second report key for key. The red run contradicted no row: every failure read the unrouted 404 that the test comments at :135/:156 already name.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:1": "<changes>\n### engine/server/api/handlers/video.py\n- `handle_video_request` is split into three module-level functions. The merge rules and SQL are the same as before; only their location changed.\n  - `resolve_video_row(handler, server, params)` reads `id`/`video_id` and `host`/`instance_domain` and answers 400 `Missing video id` or 404 `Video not found`. Otherwise it returns `(row, id_param, instance_domain)`. `db_lock` is still held only around the SELECT.\n  - `merge_video_metadata(row, dynamic, instance_domain)` returns `(response, merged)`. `response` has the same eighteen `/api/video` keys as before, and a field the instance left out falls back to the row, field by field. Title and description use `or`; the numbers use `is None`, so a supplied `likes: 0` is kept. `merged` holds the raw values (`None` included), so the write stores `NULL` rather than the response's `\"\"`.\n  - `persist_video_metadata(server, row, instance_domain, merged)` holds the three UPDATEs (videos, channels, instances), the popularity calculation and the logged `sqlite3.OperationalError` catch. It reads its values from `merged`. The argument order follows the Step 5 draft, so Phase 2 can add its statement deadline there.\n- New `handle_video_refresh_request` runs resolve, then `fetch_instance_video_dynamic` (by the requested id, outside the lock), then merge, then persist under the same `if dynamic and instance_domain and row.get(\"video_id\")` guard as before, then answers 200.\n- `handle_video_request` keeps its name and passes the request to `handle_video_refresh_request`, so `/api/video` behaves as before: it calls the instance live and writes to the DB.\n  - A `rat-tail:` comment says what's left: `/api/video` still makes the instance call and the write, and the follow-up plan makes it DB-only by answering `merge_video_metadata(row, {}, instance_domain)` with no fetch and no write.\n  - Phase 1 did not touch the `{}`-on-failed-detail success signal in `fetch_instance_video_dynamic`; that is Phase 2's clause.\n- Module docstring updated to cover both routes and the persist step.\n\n### engine/server/api/handlers/similar.py\n- The import now reads `from handlers.video import handle_video_refresh_request, handle_video_request`.\n- New branch in `_dispatch_get`: `if url.path == \"/api/video/refresh\": handle_video_refresh_request(self, self.server, params)`, placed after the `/api/video` branch. It gets the existing `/api/` rate limit (its own per-path bucket) and the statement deadline in `do_GET`.\n- A `/api/video/refresh` line is added to the docstring's list of routes.\n\n### engine/server/api/handlers/__init__.py\n- The `video` module line in the docstring now names both routes.\n\n### tests/active/test_video_metadata.py\n- Not written. This path is where the gated checkpoint `tests/tmp/test_11_fast_similars_response_phase1.py` gets promoted to; I did not touch the checkpoint or write a copy of it.\n\n### Not run\n- I did not run the checkpoint; the workflow's run is the one that counts.\n- I expect it to go green because the checkpoint's own probe showed today's `/api/video` returning exactly the expected bodies with the same stubs, and the refresh route now runs that same merge.\n\n### Leftovers in tests/tmp\n- The earlier authoring turns left `tests/tmp/probe_11_video_metadata.py` and `tests/tmp/probe_11_remediation.py` in place. I didn't touch them and have no tool to delete them, so they still need removing.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_11_fast_similars_response_phase2.py": "<items>\n<item id=\"D11\">\n<disposition>fixed</disposition>\n<what>I added a control at the top of test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed, with a new helper `_interrupted` (:193) and a module fixture `data_db` (:143). The fixture loads engine/server/data/db.py, which is stdlib only. The helper seeds a DB, opens it with the Engine's own `connect_db`, so the real `install_deadline_handler` and the real PROGRESS_HANDLER_INSTRUCTIONS apply and the test copies no constant. Inside a `statement_deadline(0.05)` it sleeps 0.1 s, runs an UPDATE on v1, and returns True only when `is_interrupted_error` recognises the raised error. Any other OperationalError is re-raised. There are two assertions. :264 says that on the heavy-trigger fixture the UPDATE is interrupted (`is True`). :265 says that on the plain schema the same UPDATE finishes (`is False`). Together they show the trigger is what carries the write to the progress handler's check. The wrong fixture they rule out is one whose UPDATE never reaches the check, for example no trigger, a trigger too light, or a schema change that drops it. That fixture makes :264 read False, so D10 can no longer pass without testing anything. I ran both results in a probe (tests/tmp/probe_11_d11.py, SQLite 3.53.4) before writing them down: heavy gave OperationalError('interrupted') and plain gave 'ok'. With the control in place, `-k deadline` on the pre-phase code still fails at :237 (`last_checked_at` is still 1, inside _assert_written called from :270). The new controls at :264 and :265 pass.</what>\n</item>\n</items>\n\n<findings_addressed>\nNeither auditor raised a CRITICAL. I took claim-audit recommendation 1 (D11 whole-claim, :4 and :173): the deadline test now opens with the controls at :264 and :265 described under D11. They show, through the Engine's own connect_db and statement_deadline, that an expired deadline interrupts a v1 UPDATE on the heavy fixture and does not on the plain schema. I left claim-audit recommendations 2 (a non-empty dict with no known fields, and a non-200 status) and 3 (C2 with a slow refresh that then fails) alone. Both would add cases beyond the ledger, and this round is bounded to it. Housekeeping: I have no delete tool, so the probes tests/tmp/probe_11_phase2.py and tests/tmp/probe_11_d11.py are still on disk. Both end in `assert False` and need deleting before any tests/tmp run.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:237, :238, :241, :242, :244 (_assert_written, called from :251, :259 and :270): last_checked_at falls inside the run's window, popularity > 0, v1 carries the live video columns with v2 untouched, channels.c1 carries the written slug, display name and followers, and the instance errors are NULL. :283 and :285 (parametrized over None, {}, a JSON list and URLError): the refresh answers (200, DB_ONLY) and the rows before equal the rows after. Controls: :250, :257, :268, :281, plus :264 and :265 for the expired-deadline fixture.</assertion>\n<expected>Answered detail: the videos, channels and instances rows are written, including after the request's 0.2 s deadline has expired. Unanswered detail: 200 with DB_ONLY and no row changed.</expected>\n<wrong_implementation>Pre-phase code does two things wrong. It persists on any truthy dynamic dict, so for None, {} and URLError last_checked_at moves off 1, popularity is recomputed and last_error 'boom' is cleared, and :285 goes red; the list case drops the connection with status None, so :283 goes red. It also persists under the request's expired deadline, so the heavy-trigger UPDATE is interrupted and last_checked_at stays 1, and :237 goes red (observed just now). A refresh that skips the write altogether reddens :237 in the success and channel-failed tests.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:294, :296, :298, :300, :301, with the controls at :291 and :292: the similars GET, sent while the refresh sits in a 5 s instance call, answers 200 with seed v1 and rows [v2] in under 1.0 s, and the only instance call is the refresh's detail call.</assertion>\n<expected>status 200, (\"v1\", [\"v2\"]), elapsed about 2 ms, calls [[tube.example, /api/v1/videos/uuid-v1]]</expected>\n<wrong_implementation>If the instance call is made inside db_lock, the similars GET waits the refresh out. It was observed at 4.0 s against a locked 2 s \u00d7 2 stub, so :298 goes red. A canned or empty similars answer fails :296.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The only negative in the new code is :265 (the plain-schema UPDATE is not interrupted). It is paired with the positive at :264 (the heavy UPDATE is interrupted), and both run through the real handler. The no-write assertion at :285 keeps its control at :281.\n2. No. The control does not copy production's 10,000-instruction constant or its handler. It calls the Engine's own connect_db, statement_deadline and is_interrupted_error. Removing install_deadline_handler from connect_db turns :264 red. Removing the heavy_au trigger from _seed also turns :264 red.\n3. No. The interruption is read on two fixtures, heavy and plain, and they give opposite results.\n4. No new double. data.db is loaded as the real module. The existing stubs replace only the instance HTTP layer (fetch_instance_json and urlopen).\n5. Yes, everything resolves. SERVER_DIR/data/db.py exists and defines connect_db, statement_deadline and is_interrupted_error. The `-k deadline` run collected 1 test with 7 deselected, so the file still holds 8 tests.\n6. Yes, both control values were observed. The interrupted/ok pair came from a probe run (SQLite 3.53.4) before I wrote them in. I did not run the control under ENGINE_PY's SQLite. The heavy join is about 90,000 rows against a 10,000-instruction check, a wide margin. The plain side is closer to the edge; running `_interrupted` inside the Engine child would confirm it there.\n7. Yes. The expired-deadline test still fails at :237 (last_checked_at == 1) and gets past the new controls at :264 and :265, which pass. The rest of the file is unchanged from the run of 5 failed and 3 passed.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "self_check:tests/tmp/test_11_fast_similars_response_phase2.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:256 \u2014 parametrized over a detail answering None, {}, a JSON list, and urlopen raising URLError: every column of the videos, channels and instances rows is the same after the refresh as before it (`report[\"after\"] == report[\"before\"]`). The control at :252 shows the refresh made exactly one instance call, for the detail.</assertion>\n<expected>after == before in all four cases: v1.last_checked_at stays 1, popularity stays 0.0, and instances.last_error/_at/_source stay 'boom'/123/'crawler'.</expected>\n<wrong_implementation>Today's guard `if dynamic and ...` is always true, because fetch_instance_video_dynamic always returns its 14-key dict. So a failed call still persists the DB values. In this run :256 went red for None, {} and URLError: the videos and instances items differed, because last_checked_at was bumped, popularity recomputed and last_error cleared. The pre-phase probe showed the same.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:254 \u2014 each failed-detail case answers (200, DB_ONLY): all eighteen fields come from the seeded row.</assertion>\n<expected>(200, DB_ONLY) for all four cases. This run showed exactly that for None, {} and URLError, which passed :254. For the JSON list, the value comes from the plan's `not isinstance(detail, dict)` \u2192 `{}` path, the same merge as the None case.</expected>\n<wrong_implementation>A detail that is a JSON list reaches `detail.get` and raises AttributeError, and the connection drops unanswered. This run read (None, \"RemoteDisconnected(...)\"). A fix that treated only None as failure would still crash here.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:211 / :212 / :215 / :216 / :218, via _assert_written from :241 \u2014 with statement_timeout_seconds=0.2, each instance call taking 0.5 s, and a heavy AFTER UPDATE trigger on videos, the refresh still writes. last_checked_at falls inside the run's wall-clock window, popularity > 0, v1 carries LIVE_VIDEO with v2 untouched, channels c1 carries live_slug/Live Chan/77, and the instance's last_error* are NULL. Controls: status 200 at :238, elapsed \u2265 1.0 s at :239.</assertion>\n<expected>The rows written exactly as in the success test. The probe showed a fresh 0.2 s budget persisting through the same trigger, and the whole request took 0.002 s.</expected>\n<wrong_implementation>Persisting under the request's own deadline, which has already expired, gets \"interrupted\" from the progress handler. The error is logged and rolled back, so every row stays as seeded. This run failed :211 with `assert 1790556377740.1506 <= 1`: last_checked_at was still 1.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:211\u2013218 via _assert_written from :225 (ANSWERING) and :233 (CHANNEL_FAILED) \u2014 when the detail answered, the videos, channels and instances rows are written. With the channel call answering None, the channel display name and followers keep the DB's \"DB Chan\"/5 while the slug becomes live_slug.</assertion>\n<expected>ANSWERING gives v1 = LIVE_VIDEO (title \"Live title\", views 1000, tags_json '[\"live\"]', category \"Music\", nsfw 0, channel_name \"Live Chan\") and c1 = live_slug/Live Chan/77. CHANNEL_FAILED gives the same video values except channel_name \"DB Chan\", and c1 = live_slug/DB Chan/5. In both, instances last_error* are NULL, last_checked_at is inside the window, and popularity > 0. All of this was seen in the probe and in this run, where both tests passed.</expected>\n<wrong_implementation>A success signal that is too strict leaves every row as seeded (\"DB title\", views 10, last_checked_at 1, 'boom') and fails :211: for example, persisting nothing, or counting a failed channel call as a failed refresh. These two tests are green today as guards on the positive half of \"only when\".</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:269 \u2014 the id-based similars GET sent while the refresh sits in a 5 s instance call answers in under 1.0 s. With :265 (status 200) and :267 (seed v1, rows [\"v2\"], the real ANN answer). Controls: :262 (the GET was sent while the refresh was inside the call) and :263 (the refresh was held \u2265 4.5 s).</assertion>\n<expected>200, seed v1, rows [\"v2\"], elapsed a few ms. The probe observed 0.0016 s during a blocked refresh, and in this run the test passed.</expected>\n<wrong_implementation>With the instance call made inside db_lock, the similars GET waits the refresh out. The probe observed 4.0 s against a stub holding srv.db_lock for 2 s \u00d7 2 calls, which fails :269.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:271 and :272 \u2014 when the similars GET answered, and again after the refresh finished, the instance stub's call log is only [[tube.example, /api/v1/videos/uuid-v1]].</assertion>\n<expected>[[\"tube.example\", \"/api/v1/videos/uuid-v1\"]] at both points, as seen in the probe and in this run.</expected>\n<wrong_implementation>A similars route that contacted the instance would add its own call. Under a lock-held refresh, the similars GET answers only after the refresh has finished all of its calls. The probe's locked run showed the channel call already in the log at that point.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: no gap. Docstring bullet 1 (answered detail writes, including channel-failed with the DB channel fields, v2 untouched) is carried by :211\u2013:218 through :225 and :233. Bullet 2 (the expired request deadline plus the heavy trigger) is carried by :241 with the controls at :238/:239. Bullet 3 (None, {}, JSON list and URLError answer 200 DB_ONLY and every column stays the same) is carried by :254 and :256 over four parametrized cases. Bullet 4 (the similars GET answers 200 with its ANN neighbour in under 1 s, and the stub has been called only for the detail) is carried by :265, :267, :269, :271 and :272. The final paragraph describes the harness, and :252, :262 and :263 plus the returncode control in _run show it ran as described.\n2. Absence only: no. :256 (nothing changed) is armed by :252 (the refresh reached the instance call) and :254 (the handler answered 200 with DB values). The same harness makes writes visible in :225/:233, which read back written rows. :271/:272 (no extra call) are armed by :262 (the GET went out during the call), :265/:267 (the similars route really answered with real rows) and :263 (the refresh was really held).\n3. Echoed literal: no. LIVE_VIDEO, LIVE_CHANNEL, DB_CHANNEL_*, CLEARED_INSTANCE and DB_ONLY are literals observed from runs. The test performs no merge and no popularity arithmetic: :212 is only > 0. Production lines whose deletion turns it red: the phase's new early `return {}` in fetch_instance_video_dynamic on a non-dict or empty detail turns :256 (three cases) and :254 (JSON list) red; the nested statement_deadline in persist_video_metadata turns :211 in the deadline test red; the persist call in handle_video_refresh_request (video.py:400) turns :211 in the success tests red.\n4. One value: no. The write is read over three inputs (ANSWERING, CHANNEL_FAILED, and ANSWERING under an expired deadline), and the channel display name and followers differ between them (Live Chan/77 against DB Chan/5). No-write is read over four failure inputs. last_checked_at is bounded by an independent wall-clock window, not by a sibling field. C2's elapsed is a bound read at the one delay (5 s) where the locked and unlocked implementations are 4+ s apart. It is not pinned against another value from the same response.\n5. The double: no. The stub replaces handlers.video.fetch_instance_json, the project's one-function wrapper around urlopen to a third-party PeerTube instance. That is the severed network layer, and the plan names it as the seam. Its None/{}/list returns are values the real function can return: on a caught error, or from json.loads. The URLError case patches stdlib urlopen instead, so the real fetch_instance_json error path runs. SimilarServer, SimilarHandler, the merge and persist, the recommendation strategy, the faiss index and the SQLite schema from sync-whitelist.py are all real.\n6. It collects: yes. tests/last_test_output.txt from the collect-only run lists 8 test ids (\"8 tests collected\"): 3 plain + 4 parametrized + 1 similars, which matches the file. The \"no tests\" line is the runner's collect-only summary. In the ValidateTests run, the returncode control in _run passed in every test, so the child's imports (server, data.db.connect_db, handlers.video, handlers.similar.SimilarHandler, faiss, numpy), the SimilarServer kwargs, RecommendationBuilderDeps/Settings and sync_job.ensure_whitelist_schema/ensure_content_schema all bound.\n7. Observed, not predicted: yes, with one named exception. DB_ONLY, the pre-phase row mutations on failure, the written LIVE values (including tags_json '[\"live\"]' and followers 77), the heavy trigger's \"interrupted\" on the old code, a fresh 0.2 s budget persisting through the trigger, the similars answer (v1 \u2192 [\"v2\"], ~2 ms) and the 4.0 s locked-stub timing all come from ValidateTests runs of tests/tmp/probe_11_phase2.py, and this run confirmed them again. One expected value cannot be observed before the phase: the JSON-list case answering (200, DB_ONLY). It rests on the plan's `not isinstance(detail, dict)` \u2192 `{}`, which gives the same merge input as the None case, observed as DB_ONLY. The implementation run confirms it.\nNo rewrite; the test file is unchanged. The probe file tests/tmp/probe_11_phase2.py remains on disk (it ends in `assert False`). I have no delete tool, so it needs removing.\n8. Red, not green: yes. ValidateTests printed \"5 failed, 3 passed \u2026 recorded: tests/last_test_validation.json (exit 1)\", exit status 1. The three that pass are the success test, the channel-failed test and the similars test. They pass because Phase 1 already persists on success and already makes the instance calls outside db_lock. The positive half of C1 and all of C2 are therefore already true, and they stay as guards. C2 is a preservation clause: the phase's intent is that the instance calls stay outside db_lock. No assertion carrying it can be red against code that already satisfies it, but the probe's lock-held stub (4.0 s) shows :269 does discriminate the wrong implementation. C1's \"only when\" half, and its deadline case, are red.\n9. Red for the right reason: yes. No control failed: the returncode control passed everywhere, as did :238 (status 200), :239 (elapsed \u2265 1.0) and :252 (calls == [[HOST, DETAIL_PATH]]) in every case. Failures:\n- test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed at :211, \"assert 1790556377740.1506 <= 1\". last_checked_at is still the seeded 1, because the write was interrupted under the expired deadline.\n- detail-none, detail-empty-object and urlopen-urlerror at :256, \"AssertionError: assert {'videos': ...} == {'videos': ...}\", with differing items 'instances' and 'videos'. The failed call still wrote.\n- detail-json-list at :254, \"assert (None, \"Remot...t response')\") == (200, {...})\", \"At index 0 diff: None != 200\". The list reached `detail.get` and the connection dropped.\nEach is the unbuilt phase: no success signal, and no fresh deadline for persist. None is a typo, a missing import, a bad path or a harness limit.\n10. Observed expected output: every row's expected value agrees with this run or with the probe run.\n- :254: DB_ONLY matched for the three non-list cases, which passed.\n- :211\u2013:218: the success and channel-failed tests passed with exactly LIVE_VIDEO/LIVE_CHANNEL and DB_CHANNEL_*.\n- :265\u2013:272: passed with v1 \u2192 [\"v2\"] and the single detail call.\n- The red values match what the rows' wrong_implementation columns predicted: last_checked_at 1 at :211, rows changed at :256, status None at :254.\nNothing the run showed contradicts a row.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:2": "<changes>\n### `engine/server/api/handlers/video.py`\n- `fetch_instance_video_dynamic` now returns `{}` when the video detail call didn't answer. That covers `None` (which includes `URLError`/`HTTPError`/timeout, since `fetch_instance_json` already catches those), an empty object, and any non-dict JSON. Before, a JSON list crashed on `detail.get` and dropped the connection, and `None` or `{}` produced a dict of `None`s. That dict counts as true, so `handle_video_refresh_request`'s existing `if dynamic and ...` guard went ahead and wrote anyway. Now that guard really does limit the write to refreshes the instance answered (C1). A failed refresh still answers 200 with the DB-only values, through `merge_video_metadata(row, {}, ...)`.\n- `persist_video_metadata` now runs its write under its own `statement_deadline(server.statement_timeout_seconds)`, falling back to `DEFAULT_STATEMENT_TIMEOUT_SECONDS`. The deadline is entered just before `db_lock`. The request's deadline from `do_GET` has usually been used up waiting on the instance, so an UPDATE long enough to reach the progress handler used to get interrupted and logged, and nothing was saved. `statement_deadline` puts the request's own deadline back on exit. New imports: `statement_deadline` from `data.db` and `DEFAULT_STATEMENT_TIMEOUT_SECONDS` from `server_config`. `similar.py` already uses both from the same places.\n- C2 needed no code change. The instance calls already ran outside `db_lock`: `resolve_video_row` takes the lock only for the row read, and `persist_video_metadata` takes it only for the write. I didn't observe this with a run; the checkpoint run will confirm it.\n- I updated the module docstring's persist line to say the write happens only when the detail call answered.\n\n### `tests/active/test_video_metadata.py`\nI didn't touch it. It doesn't exist in the worktree yet. I take this to be where the checkpoint (`tests/tmp/test_11_fast_similars_response_phase2.py`) will be moved; it isn't a file for me to write.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "author:tests/tmp/test_11_fast_similars_response_phase3.py": "<exemptions>\nnone\n</exemptions>\n\n<items>\n<item id=\"C1e\">\n<disposition>fixed</disposition>\n<what>Line 65's refused list now also sends `id=uuid-1&host=tube.example&host=other.example`, a repeated `host`. Line 67 now reads `assert refused == [400, 400, 400, 400, 400]`, so it carries the clause. It excludes a handler that checks `id` for multiple values but reads `host` as `params[\"host\"][0]` or `[-1]`. That handler would answer 200 on the fifth query and forward it, and :70 would also go red because a second entry would appear. The docstring now names the repeated `host` too.</what>\n</item>\n</items>\n\n<findings_addressed>\nClaim CRITICAL 1 (whole-claim, repeated `host` not tested): a query with `host` repeated is added to the refused list at :65. :67 now requires 400 for it, and :70 requires that it never reaches the Engine. The docstring was updated to match. After the edit I ran ValidateTests on the pre-phase code: `[404, 404, 404, 404, 404] == [400, 400, 400, 400, 400]` at :67, and `404 == 502` at :84. Both fail because the route is not built yet.\nClaim RECOMMENDATION 1 (bounds), partly taken: `foo=1` is added at :65, a key that is in no allow-list, so \"any other key\" is no longer tested only with keys borrowed from `/api/video`. I did not add cases for a missing, empty or whitespace `id`/`host`. `must_prove` does not say what the refresh route should do with those, so any expected value would be invented.\nShape audit: PASS with no findings. The new expectations are the literal 400 from C1. None is derived from a production allow-list table, so the assertion does not mirror production.\n</findings_addressed>\n\n<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:67 \u2014 GET /api/video/refresh with `user_id` added, `refresh_cache` added, `foo` added, `id` repeated, and `host` repeated each answers 400</assertion>\n<expected>[400, 400, 400, 400, 400]</expected>\n<wrong_implementation>A route that reuses the `/api/video` allow-list reads 200 on the first two. A route that checks only `id` for repeats and takes the first or last `host` reads 200 on the fifth. A route left unrouted reads [404, 404, 404, 404, 404], which I observed on the pre-phase code.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:68 \u2014 GET /api/video/refresh?id=uuid-1&host=tube.example answers 200 with the stub Engine's body unchanged</assertion>\n<expected>(200, {\"videoUuid\": \"uuid-1\", \"title\": \"Refreshed\"})</expected>\n<wrong_implementation>A route that refuses everything, or that passes through only the status and rewrites or filters the body, gives a 400/404 or a different body.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:70 \u2014 the stub recorded exactly one request: `/api/video/refresh` with query exactly {id: [uuid-1], host: [tube.example]}. The five refused requests were sent first</assertion>\n<expected>[(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]</expected>\n<wrong_implementation>A route that forwards to `/api/video` gets the wrong path. One that adds `user_id` or drops `host` gets the wrong dict. One that forwards a refused request (for example the one with `host` repeated) puts an extra entry at the front.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:84 \u2014 with the refresh's route timeout patched to 0.3 s and a 1.5 s Engine, the refresh answers 502</assertion>\n<expected>502</expected>\n<wrong_implementation>A route that ignores the per-route timeout and uses the shared 10 s default lets the 1.5 s answer through as 200. An unrouted refresh reads 404 (observed).</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:85 \u2014 the Engine received that timed-out refresh exactly once</assertion>\n<expected>[(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]</expected>\n<wrong_implementation>A refresh that gets the shared ENGINE_PROXY_RETRY_COUNT=1 is sent twice, so the snapshot holds two entries. The :87 guard (/api/video still 502 after two attempts) shows that the single send is not retries being dropped for every route.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. No. The negative at :70 (refused requests never reach the Engine) has a positive control: :68 and :70 need the allowed refresh to arrive, and the refused ones are sent first on the same stub. The single send at :85 is armed by :84's 502 and by the :87 guard that sees two attempts on /api/video. With the code under test deleted, :67 reads 404s, which I observed.\n2. No. Every expected value is a literal: status codes, the FORWARDED dict built from QUERY by hand, and the stub's own ANSWER. Deleting the refresh route (the missing PROXY_READ_GET_ROUTES/PROXY_ALLOWED_QUERY_PARAMS entries) turns :67 and :84 red. Deleting the repeat check on `host` turns :67 red at index 4.\n3. No. Refusal is read on five distinct inputs: two keys borrowed from /api/video, one key in no allow-list, and each allowed key repeated. It is not pinned against a sibling.\n4. No. The only double is the stub Engine, a separate HTTP service on the other side of the network seam. The Client backend is real.\n5. Yes, it collects. The imports are unchanged, and the run collected and executed both tests (2 failed).\n6. Yes. The pre-phase 404s for the new `foo` and repeated-`host` queries were observed in this round's ValidateTests run: `[404, 404, 404, 404, 404]`. The 400 under the right implementation comes from the C1 wording, not from any output shape. The earlier observations (allow-list forwarding user_id, 2 attempts on /api/video, BrokenPipe) came from the probe run on the previous round.\n7. Yes. The post-edit run fails at :67 with `[404, 404, 404, 404, 404] == [400, 400, 400, 400, 400]` and at :84 with `404 == 502`. Both fail because the route is not built, not because of a collection or setup error. Line numbers did not shift, so the ledger's :67/:70/:84/:85/:87 still point at the same assertions. Nothing needed a rewrite. Note: the probe files tests/tmp/probe_11_phase3.py and probe_11_phase3_selfcheck.py are still there because I have no delete tool, and they should be removed.\n</answers>",
    "self_check:tests/tmp/test_11_fast_similars_response_phase3.py": "<rows>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:67 \u2014 GET /api/video/refresh?id=uuid-1&host=tube.example with `&user_id=u-1` added, with `&refresh_cache=1` added, and with `id` repeated (`id=uuid-2&\u2026`) answers [400, 400, 400]</assertion>\n<expected>[400, 400, 400] once the refresh has its own {id, host} allow-list. The run on the current code read [404, 404, 404] because the route is not proxied.</expected>\n<wrong_implementation>Route not added: [404, 404, 404], seen in this run. Refresh added to PROXY_READ_GET_ROUTES but falling back to /api/video's allow-list (or no entry of its own that is wider than {id, host}): user_id and refresh_cache pass. That reads [200, 200, 400]; on /api/video both were observed at 200 and repeated id at 400.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:68 \u2014 GET /api/video/refresh?id=uuid-1&host=tube.example answers (200, {\"videoUuid\": \"uuid-1\", \"title\": \"Refreshed\"}), the stub Engine's body passed through</assertion>\n<expected>(200, ANSWER). The same stub behind /api/video was observed to answer exactly (200, {'videoUuid': 'uuid-1', 'title': 'Refreshed'}) through the proxy.</expected>\n<wrong_implementation>Route not added: 404. An allow-list entry that is empty or too narrow (for example {} or {\"id\"}) refuses the valid query with 400.</wrong_implementation>\n</row>\n<row clause=\"C1\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:70 \u2014 the stub Engine received exactly [(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]</assertion>\n<expected>A single entry: the allowed refresh on path /api/video/refresh with exactly id and host. The three refused requests were sent before it and never reached the Engine.</expected>\n<wrong_implementation>A refresh proxied upstream to /api/video, or with its query rewritten, records a different path or query. A refused request forwarded anyway, or rejected only after it was proxied, records an entry ahead of the allowed one. A refresh forwarding user_id or refresh_cache records those extra keys, which /api/video was observed to forward. Route not added: [].</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:84 \u2014 with ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS[\"/api/video/refresh\"] patched to 0.3 and a stub Engine that sleeps 1.5 s before answering, GET /api/video/refresh answers 502</assertion>\n<expected>502. The run on the current code read 404 (route not proxied).</expected>\n<wrong_implementation>Refresh uses the shared 10 s timeout (the per-route mapping is ignored, or keyed on `upstream`, which carries the query string): the 1.5 s answer arrives and the status reads 200. This was observed for /api/video against the same 1.5 s stub at the default timeout: 200 after 1.5 s. Route not added: 404, seen in this run.</wrong_implementation>\n</row>\n<row clause=\"C2\">\n<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:85 \u2014 during that timed-out refresh the stub Engine received exactly one request, [(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]; the guard at :87 (the same stub still gets /api/video twice, 502) ties the single send to the refresh's own retry count</assertion>\n<expected>One refresh GET. Guard: (502, two /api/video entries), observed on the current code in the run's log line \"path\":\"/api/video\",\"status\":502,\"attempts\":2 and in the earlier probe.</expected>\n<wrong_implementation>Refresh keeps the shared ENGINE_PROXY_RETRY_COUNT = 1: the list reads two identical refresh entries. A timeout-retried send counted per path through `upstream` has the same effect. Setting ENGINE_PROXY_RETRY_COUNT to 0 for every route passes :85 but fails the guard at :87 with one /api/video entry.</wrong_implementation>\n</row>\n</rows>\n\n<answers>\n1. Whole claim: yes, each clause is tested. C1 has three parts. \"Forwards with only id and host\" is :68 plus :70, which pins the exact path and query dict the Engine saw. \"Refuses any other key with 400\" is :67 cases 1\u20132 (user_id, refresh_cache), the two keys /api/video's list accepts. \"Refuses a repeated key with 400\" is :67 case 3. C2's \"answered 502\" is :84 and \"sent once\" is :85. The docstring's /api/video two-attempt sentence is the guard at :87. The docstring now says the refresh entry is \"patched to\" 0.3 s, which matches the rewritten setup.\n2. Absence only: no. The one negative is that no refused request reached the Engine. It is carried by :70's exact equality, and the same list must hold the allowed refresh, sent after the three refused ones. So the stub recording and the forwarding path are both shown working in the same assertion. C2's \"sent once\" (:85) is exact equality to one entry, not an absence.\n3. Echoed literal: no. FORWARDED and ANSWER are fixed literals, and the test does no allow-list or retry logic of its own. Deleting the planned `\"/api/video/refresh\": {\"id\", \"host\"}` entry in PROXY_ALLOWED_QUERY_PARAMS turns :67/:68 red. Deleting `\"/api/video/refresh\"` from PROXY_READ_GET_ROUTES turns every assertion red. Deleting the `timeout_seconds = ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS.get(path, \u2026)` lookup turns :84 red (200). Deleting the `retry_count = ENGINE_PROXY_ROUTE_RETRY_COUNT.get(path, \u2026)` lookup turns :85 red (two sends).\n4. One value: no. Refusal is read at three different inputs, next to one allowed input. The timeout is read at two routes against the same sleeping Engine: the refresh expects 502 after one send, /api/video expects 502 after two. So the refresh's count is compared with an independently observed ordinary-route count, not with another field from the same source.\n5. The double: no. The stub stands in for the Engine process behind the HTTP boundary, the layer the Client/Engine split severs; the plan names \"the Client backend's HTTP proxy in front of a stub Engine\" as the seam. Every Client module under test is real: ClientBackendServer, the handler, _handle_engine_read_proxy_get and _proxy_engine_request. monkeypatch changes two timeout constants, not behaviour.\n6. It collects: yes. The run printed \"collected 2 items\", which matches the two test functions. The \"no tests\" line in the handed collect-only summary is the runner's summary for a collect-only run, not a count. conftest's RateLimiter and client_server, and test_server's _client_backend, _serving and _status all resolved: both tests ran their servers and requests, and the log shows /api/video proxied. The _status and _client_backend arguments match their definitions at test_server.py:359 and :370.\n7. Observed, not predicted. There was a yes here, and I rewrote it. The setup premise `monkeypatch.setitem(client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS, \u2026)` assumed a name that does not exist yet, and the run showed it raising AttributeError at :75, before any assertion. That line now sets the mapping with `raising=False`, merged over any existing mapping; the plan says it is a module global read per request. I also ran a new probe, tests/tmp/probe_11_phase3_selfcheck.py (with -s), to observe the premises the rows rest on:\n   - /api/video through the proxy answers (200, {'videoUuid': 'uuid-1', 'title': 'Refreshed'}).\n   - /api/video with refresh_cache answers 200, and with a repeated id answers 400.\n   - With the default timeout and the 1.5 s stub, /api/video answers 200 after 1.5 s with one send. This is the \"200 under the shared timeout\" wrong-implementation value.\n   The earlier probe had already shown user_id forwarded on /api/video and 502 after two sends at 0.3 s. That second one shows again in this run's log: \"path\":\"/api/video\",\"status\":502,\"attempts\":2,\"duration_ms\":851.\n   One thing is still a prediction: that the phase's code reads ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS at call time under that name, as the plan specifies. Only the implementation run can confirm it.\n   I cannot delete files, so tests/tmp/probe_11_phase3.py and tests/tmp/probe_11_phase3_selfcheck.py need removing.\n8. Red, not green: yes, red. The final ValidateTests run on tests/tmp/test_11_fast_similars_response_phase3.py printed \"2 failed \u2026 recorded: tests/last_test_validation.json (exit 1)\", exit status 1.\n9. Red for the right reason: yes, after the rewrite. Before it, test 2 stopped at :75 on \"AttributeError: module 'server' has no attribute 'ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS'\". That was a setup failure that measured nothing, and it is what I fixed. The final run has two failures, and both are phase observables, not controls:\n   - :67 `assert [404, 404, 404] == [400, 400, 400]` (\"At index 0 diff: 404 != 400\").\n   - :84 `assert 404 == 502`.\n   Both are the Client's 404 for an unproxied /api/video/refresh, meaning the route and its allow-list do not exist yet. The same run's log shows the guard's path working: /api/video returned 502 after 2 attempts.\n10. Observed expected output: yes. No row's expected value was contradicted. The run showed the pre-phase 404 that each row's wrong_implementation names. Each post-phase expected value (400, the pass-through body, the exact forwarded query, 502, one versus two sends) matches what the probes observed on /api/video under the same stubs. The refresh's own 400/502 cannot be observed before the phase is implemented.\n</answers>\n\n<exemptions>\nnone\n</exemptions>",
    "step_7_implement:3": "<changes>\n### client/backend/server.py\n- `/api/video/refresh` added to `PROXY_READ_GET_ROUTES`. It now goes through the same rate limit and the same `_handle_engine_read_proxy_get` sanitising as the other GET read proxies: an unknown key or a repeated key gets 400, and values are stripped.\n- New `PROXY_ALLOWED_QUERY_PARAMS[\"/api/video/refresh\"] = {\"id\", \"host\"}`. The `/api/video` entry is unchanged and keeps `refresh_cache` and `user_id`.\n- Two new per-path mappings sit next to the shared constants, with a one-line comment saying why the refresh differs:\n  - `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS = {\"/api/video/refresh\": 20}`\n  - `ENGINE_PROXY_ROUTE_RETRY_COUNT = {\"/api/video/refresh\": 0}`\n- `_proxy_engine_request` looks up `timeout_seconds` and `retry_count` once per request from these mappings. The lookup is keyed on `path`, not `upstream`, which carries the query string. Any path not in a mapping falls back to `ENGINE_PROXY_TIMEOUT_SECONDS` / `ENGINE_PROXY_RETRY_COUNT`. Both are module globals read at call time, which lets a test patch them.\n- All four sites that used the shared constants now read the locals: the retry loop's `range`, the `urlopen` timeout, the retry check `attempt < retry_count`, and the `\"attempts\"` field of the \"proxy request unavailable\" log.\n- Result: the refresh gets 20 s and no retry, and a transport timeout on it is answered 502 `ENGINE_PROXY_UNAVAILABLE` after one send. Every other proxied route still gets 10 s and one retry.\n</changes>\n\n<inner_tests>\nnone\n</inner_tests>\n\n<unanticipated>\nnone\n</unanticipated>\n\n<awaiting_operator>\nnone\n</awaiting_operator>",
    "step_8_i1_refactor": "<refactors>\nengine/server/api/handlers/video.py: added a module-level `pick_present(value, fallback)` helper, placed with `pick_text`/`pick_number`, which returns the fallback only when the value is None. `merge_video_metadata` now uses it in place of the seven hand-written `x = dynamic.get(k); if x is None: x = row.get(k)` blocks (views, likes, dislikes, channel_followers, tags_json, category, nsfw). Each field falls back the same way as before: `is None` for these seven, `or` for title, description, channel_display and channel_slug. The operator confirmed this refactor before I made it.\n</refactors>\n\n<left_out>\nThe dead `channel_detail = None` line in `fetch_instance_video_dynamic`. It was there before this build and no phase touched it, so I left it alone. I did not run the gating checkpoints after the helper refactor. The fallback cases in tests/tmp/test_11_fast_similars_response_phase1.py (case b) and phase 2 (the no-write merge) cover it, and the workflow's run will confirm it. client/backend/server.py, similar.py and handlers/__init__.py: I found nothing to refactor; the per-path timeout/retry lookups and the new dispatch branch are already as small as they can be. There are leftover probe files in tests/tmp (probe_11_video_metadata.py, probe_11_remediation.py, probe_11_phase2.py, probe_11_phase3.py, probe_11_phase3_selfcheck.py, probe_11_d11.py) that still need deleting. I have no delete tool, and they are outside this step's files. tests/active/test_video_metadata.py does not exist yet. It is where the phase 1 and 2 checkpoints get promoted, so it is not mine to write.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe only refactor that paid its way was folding seven identical `is None` fallbacks in merge_video_metadata into one helper. The merge rules are unchanged: 0 and 0/1 values are kept, and title, description and channel names still use `or`. Everything else that landed was already minimal, and the step's rules placeholder was blank, so I measured the pass against the role's rules with operator consent.\n</observation>",
    "step_8_triage:0": "<failures>\n### tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux]\n\n**What happened.** The second of two identical `POST /recommendations` home requests (`plain = _home(...)`, line 150) got `500 {\"error\": \"Recommendations request failed\"}`. The first request (`previous`), with the same five likes and a moment earlier, got 200. The `[cooking]` and `[music]` cases of the same test passed in the same run.\n\n**The test is sound.** It asks for a home page twice and expects 200 each time. That is a fair expectation, it does not rely on anything this build changed, and it does not conflict with any clause of the build. Nothing needs retiring or fixing in it.\n\n**The build did not cause it.** No phase touched the home path. Phase 1 added one import and one GET branch (`/api/video/refresh`) to `similar.py`. Phase 2 edited only `video.py`. Phase 3 edited only the Client backend. The home request runs `do_POST` \u2192 `_handle_similar` \u2192 `_handle_home` \u2192 the mixer, none of which changed. `test_similar.py` was re-selected only because `similar.py` changed.\n\n**What I observed.** I used a throwaway probe, `tests/tmp/probe_11_home_500.py`, that starts the real Engine the way the `engine` fixture does, with its log somewhere the probe can read it:\n- It does not happen on a single Engine. The failing sequence (likes, home, home, home with `exclude`) ran 20 rounds across linux, cooking and music: 60 home requests, all 200, and no ERROR record in the Engine log.\n- A home request with five likes takes about 0.83 s (five calls, 0.81 to 0.88 s) against the 5 s budget that `do_POST` gives each request (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`).\n- When that budget runs out, the answer is this exact failure. With the budget patched to 0.001 s, both home requests got `500 {\"error\": \"Recommendations request failed\"}`. The log showed `server error` with the traceback `_handle_home \u2192 mixer \u2192 explore_range._fetch_pool \u2192 fetch_random_rows_from_cache \u2192 fetch_metadata \u2192 sqlite3.OperationalError: interrupted`. `_handle_similar`'s `except Exception` catches the interrupt before `do_POST`'s handler can turn it into `503 Query time limit exceeded`, so a timeout on this route looks like a generic 500.\n\n**Most likely cause (inferred, not seen in the suite run).** The suite ran 11 lanes at once, each with its own faiss-backed Engine on the same machine and the same repo database files. Under that load, one home request probably took more than 5 s of wall-clock time \u2014 about six times its unloaded time \u2014 and its statement was interrupted. The other possibility is a `database is locked` error on the shared `similarity-cache.db`, which another lane's Engine also writes. That would reach the same `except Exception` and the same 500 body.\n\nI could not read the suite run's Engine log: `/tmp/pytest-of-enduser/pytest-5194/engine0/engine.log` is outside this session's sandbox. That log would settle it. Look for a `\"message\":\"server error\"` record near the failed request, ending in `sqlite3.OperationalError: interrupted` (budget trip) or `database is locked` (cache contention).\n\n**What I changed.** Nothing in the code or the tests. This is an intermittent failure caused by load, which existed before this build, not a regression.\n</failures>\n\n<checkpoint_gaps>\nnone\n</checkpoint_gaps>\n\n<correction>\n- I read the failing test and its output. The test is sound: its failure is a 500 on a repeat of a request that had just succeeded.\n- I checked what each phase touched. None of them touched the home path in `_handle_similar` / `_handle_home` / the mixer.\n- I wrote and ran `tests/tmp/probe_11_home_500.py` (see \"What I observed\" above): 60 home requests on an isolated Engine never failed, a request takes about 0.83 s against a 5 s budget, and running out of the budget produces exactly this 500.\n- I changed no implementation file, no active test and no checkpoint, and retired no test: none conflicts with a requirement of this build or passes without really testing anything.\n\n**What I recommend:**\n1. Have the workflow rerun `tests/active/test_similar.py` to confirm the red was intermittent.\n2. Before or instead of that, check the suite run's Engine log (path above) for the traceback of the failed request.\n3. Two problems that predate this build could go on the issue tracker; that is outside this step's files, so I have not filed them:\n   - A statement interrupt inside `_handle_similar` answers a generic 500 instead of `do_POST`'s 503, because the broad `except Exception` catches it first.\n   - A fixed 5 s wall-clock budget, shared across 11 parallel Engine lanes, makes the home tests sensitive to machine load.\n\n**Housekeeping:**\n- `tests/tmp/probe_11_home_500.py` needs deleting; I have no tool to delete files. The same goes for the earlier leftovers the Phase 1 report listed.\n- Each probe run overwrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with the probe's results. The `test_similar` red is still listed under \"failed tests\", but the full suite output is no longer in those files.\n</correction>",
    "step_9_triage": "<docs>\n<doc path=\"engine/server/README.md\" update=\"yes\">\nLine 9 (\"`/api/video` metadata for the video page.\") is incomplete, and line 3 (\"Read-only Engine API ...\") was already false and still is. What landed differs from the checklist: `/api/video` is NOT DB-only. `handle_video_request` hands the request to `handle_video_refresh_request`, so both routes behave the same way, and the entry must not say `/api/video` makes no instance call or that `accountAvatarUrl` is empty. What the file needs:\n- **`/api/video` bullet.** Keep it, and say that it fetches live metadata from the source instance (the video detail, then the channel, with an 8 s socket timeout on each) and merges it over the DB row field by field.\n- **New `/api/video/refresh` bullet.** It gives the same answer in the same shape and is the route the Client proxies with its own budget.\n- **Persist rule, for both routes.** The `videos`/`channels` UPDATE and the `instances.last_error*` reset run only when the instance's video detail call answered. They run under their own statement deadline. A detail call that failed or answered empty or non-object JSON writes nothing, and the response then falls back to the DB values.\n- **Line 3.** Say the API is read-only apart from this per-request metadata write-back.\n</doc>\n<doc path=\"README.md\" update=\"yes\">\nTwo rows of the boundary table list `/api/video` but not the new route: line 46 (Engine public read API) and line 48 (Client browser-facing read gateway). Add `/api/video/refresh` to both lists. The Engine dispatches it in `SimilarHandler._dispatch_get`, and the Client proxies it through `PROXY_READ_GET_ROUTES`. Line 134 (the smoke check expects the Client proxy `/api/video` to answer 200) is still true.\n</doc>\n<doc path=\"client/README.md\" update=\"yes\">\nLine 37 (the read gateway list) is missing `/api/video/refresh`, which `client/backend/server.py` now proxies. Add it. Also say how this proxy differs from the others: it accepts only `id` and `host`, and any other key or a repeated key answers 400. It waits up to 20 s and is sent once with no retry (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` / `ENGINE_PROXY_ROUTE_RETRY_COUNT`), so a timeout answers 502 `ENGINE_PROXY_UNAVAILABLE`. Every other proxied read keeps 10 s and one retry.\n</doc>\n<doc path=\"client/frontend/README.md\" update=\"no\">\nNo frontend phase landed: `client/frontend/src/pages/video-page/index.ts` was not touched, and the page does not call `/api/video/refresh`. Line 8's list of routes the frontend fetches (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) is still exactly right, and the page loads in the same order as before. The checklist's addition and its load-order sentence belong to the follow-up plan that builds the page coordinator.\n</doc>\n<doc path=\"DEPLOYMENT.md\" update=\"no\">\nLines 374-375 (\"`/api/video` makes live calls to source instances per request\") are still true. `/api/video` was kept live in this build; only the follow-up plan makes it DB-only. The sentence's point, that outbound 443 is a runtime dependency, also still holds. The ufw comment at 369 (\"live video metadata\") is true. The nginx `location /api/` block already covers `/api/video/refresh`, and its default 60 s read timeout is longer than the 20 s proxy budget.\n</doc>\n<doc path=\"docs/project/issues/10-video-metadata-completeness.md\" update=\"yes\">\nAdd a comment and leave the body as it is. What the comment records:\n- **The single write path now exists.** It is `persist_video_metadata` in `engine/server/api/handlers/video.py`, reached through `handle_video_refresh_request`, which both `/api/video` and `/api/video/refresh` currently run. It is the one place this issue extends with further fields (line 15's \"one write path\").\n- **Line 17 is now real behaviour.** `fetch_instance_video_dynamic` returns `{}` when the detail call fails or answers empty or non-object JSON. The DB update and the `instances.last_error` reset then run only when the detail call answered. The write has its own statement deadline, so a slow instance no longer causes it to be interrupted silently.\n- **The merge rules.** The field-by-field fallback lives in `merge_video_metadata`. Title, description and the channel names fall back when empty (`or`); counts, `tags_json`, `category` and `nsfw` fall back only when missing (`pick_present`, an `is None` test), so a supplied 0 is kept.\n- **Line 22.** It holds for either route today. Once the follow-up plan makes `/api/video` DB-only, it will hold only for `/api/video/refresh`.\n</doc>\n<doc path=\"docs/project/issues/20-request-lifecycle-logs.md\" update=\"no\">\nLine 25 names `/api/video` in the smoke list for start\u2192end request logs. That route still exists and is still the long-running call bound to the instance, because it was kept live. This future-work spec says nothing that is now false. Adding `/api/video/refresh` would be a scope choice for whoever plans issue 20, not a correction.\n</doc>\n<doc path=\"docs/project/roadmap.md\" update=\"yes\">\nLine 54 (F2-M3, API versioning) lists the unversioned routes that feature must version: `/api/channels`, `/api/video` and the similar routes. The build added a new unversioned public route, so the list is now incomplete. Add `/api/video/refresh`.\n</doc>\n<doc path=\"docs/project/issues/11-fast-similars-response.md\" update=\"yes\">\nAdd a delivery comment, but do NOT carry out the checklist's harvest action. Leave `Status:` open and the file in `docs/project/issues/`. The build delivered only the first of two plans (Engine refresh route, persist on success, Client proxy). Still to do, in the follow-up plan: `/api/video` answering from the DB only (R1); the page coordinator, starting three requests with the refresh winning in either arrival order (R3); a first render that waits on no instance request (R4); URL-param rendering when the Engine has no row (R5); and the re-render guards (R6).\n\nThe page still renders nothing until `/api/video` returns from the instance, which is the problem the issue describes, so closing it would be false. The comment records:\n- the operator's two-phase reading;\n- the refresh route, `GET /api/video/refresh`;\n- the 20 s, no-retry proxy budget for the refresh;\n- that similars are not delayed by a slow refresh, with the instance calls kept outside `db_lock`;\n- the accepted behaviour change: a failed instance fetch no longer writes, bumps `last_checked_at` or clears `instances.last_error*`. This already applies to `/api/video` today.\n</doc>\n</docs>\n\n<adr_conflicts>\nnone\n</adr_conflicts>",
    "step_9_i2_update:engine/server/README.md": "<changes>\n`engine/server/README.md`: the `/api/video` entry is updated, a `/api/video/refresh` entry is added, the write-back rule is documented, and the \"read-only\" claim on line 3 is corrected.\n\n- **Line 3:** the Engine API is now described as read-only apart from the per-request video metadata write-back. That write is described under `/api/video`.\n- **`/api/video` bullet:** gives the lookup parameters (`id`/`video_id`, optional `host`/`instance_domain`) and the 400 `Missing video id` and 404 `Video not found` answers. It says the route reads the DB row, then fetches live metadata from the source instance and merges it over the row field by field. The fetch is the video detail and then its channel, with an 8 s socket timeout on each, made outside `db_lock`. I checked all of this against `resolve_video_row`, `fetch_instance_video_dynamic` and `merge_video_metadata`.\n- **New `/api/video/refresh` bullet:** it gives the same answer in the same shape. It is the route the Client proxies with its own budget, and the entry points to `client/README.md` for that budget rather than repeating the 20 s / no-retry figures. I confirmed the dispatch in `similar.py` `_dispatch_get`.\n- **New write-back bullet, covering both routes:**\n  - The write happens only when the video detail call answered with a non-empty JSON object.\n  - It covers the `videos` UPDATE, the `channels` UPDATE when the row has a channel, and the reset of `instances.last_error`, `last_error_at` and `last_error_source`.\n  - It runs under its own statement deadline.\n  - A `sqlite3.OperationalError` is logged and does not fail the response.\n  - A detail call that failed or answered empty or non-object JSON writes nothing, and the response then carries the DB values.\n\n  I checked this against `persist_video_metadata` and the `if dynamic and ...` guard in `handle_video_refresh_request`.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:README.md": "<changes>\nAdded `/api/video/refresh` to two rows of the boundary table: the Engine public read API and the Client read gateway.\n\n- Line 46 (Engine public read API): added `/api/video/refresh` after `/api/video`. I checked the code: `SimilarHandler._dispatch_get` in `engine/server/api/handlers/similar.py` dispatches it at line 500.\n- Line 48 (Client browser-facing read gateway): added `/api/video/refresh` after `/api/video`. I checked the code: it is listed in `PROXY_READ_GET_ROUTES` in `client/backend/server.py` at line 85.\n- Everything else is unchanged. Line 134 (the smoke check expects the Client proxy's `/api/video` to answer 200) is still true. The route's behaviour, its 20 s no-retry proxy budget and its `id`/`host` allow-list belong to `engine/server/README.md` and `client/README.md`, so this file doesn't repeat them.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:client/README.md": "<changes>\nAdded `/api/video/refresh` to the Client read gateway list and described how its proxy differs from the other reads (allow-list, 20 s, no retry, 502 when it times out).\n\n- **Boundary Contract, read gateway list:** added `/api/video/refresh` after `/api/video`.\n- **Backend Responsibilities:** added one new bullet before the Engine-failure bullet. It says:\n  - The route is proxied like the other GET reads but accepts only `id` and `host`. Any other key, or the same key given twice, answers 400.\n  - The proxy waits up to 20 s and sends the request once with no retry (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`, `ENGINE_PROXY_ROUTE_RETRY_COUNT`).\n  - A transport failure or timeout answers 502 `ENGINE_PROXY_UNAVAILABLE`.\n  - Every other proxied read waits 10 s and is retried once.\n- **Engine side not repeated:** for what the route does inside the Engine, the bullet points to `engine/server/README.md` instead of restating it.\n- **Checked against `client/backend/server.py`:**\n  - The route is in `PROXY_READ_GET_ROUTES` (line 85) and in `PROXY_ALLOWED_QUERY_PARAMS` (line 92).\n  - The per-path mappings are at lines 79 and 82, and `_proxy_engine_request` looks them up at lines 589\u2013590.\n  - The retry loop and the 502 `ENGINE_PROXY_UNAVAILABLE` answer are at lines 611\u2013751.\n  - The 400s for an unknown key and a repeated key come from `_handle_engine_read_proxy_get` (lines 421\u2013436).\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/10-video-metadata-completeness.md": "<changes>\nAdded a comment to issue 10 about the metadata write path, merge rules and persist-on-success behaviour that issue 11 delivered. Body and `Status:` are unchanged.\n\n- **Write path:** the single write path is `persist_video_metadata`, reached through `handle_video_refresh_request`, which both `/api/video` and `/api/video/refresh` run. The comment lists what it writes today:\n  - `title`, `description`, counts, `tags_json`, `category`, `nsfw` and `last_checked_at` on `videos`;\n  - channel name, display name and followers on `channels`.\n  \n  It also says what this issue still has to add: `language`, `duration`, `thumbnail_url`, and tags/category in the response. I checked all of this against `video.py`.\n- **Robustness rule is live behaviour:** `fetch_instance_video_dynamic` returns `{}` when the detail call fails or answers empty or non-object JSON. When it does, no UPDATE runs, `instances.last_error*` is not reset and `last_checked_at` is not bumped. The write has its own statement deadline.\n- **Merge rules:** these live in `merge_video_metadata`. Title, description and the channel names fall back to the row when empty (`or`). Counts, `tags_json`, `category` and `nsfw` fall back only when missing (`pick_present`), so a supplied 0 is kept. New fields belong in these two functions.\n- **Validation line \"after the next `/api/video` request\":** this holds for either route today. It will hold only for `/api/video/refresh` once issue 11's follow-up plan makes `/api/video` answer from the DB only.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/roadmap.md": "<changes>\nAdded `/api/video/refresh` to F2-M3's list of routes that still need versioning.\n\n- Line 54 (F2-M3, API versioning) now reads: \"`/api/channels`, `/api/video`, `/api/video/refresh` and the similar routes are this feature's work.\"\n- I checked the route against the code: `SimilarHandler._dispatch_get` in `engine/server/api/handlers/similar.py` dispatches the unversioned path `/api/video/refresh` (line 500).\n- Nothing else in the roadmap changed. The F11-M2 line and the similarity/video-page order (`08` -> ... -> `11` -> `12`) are still correct, because issue `11` stays open.\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>",
    "step_9_i2_update:docs/project/issues/11-fast-similars-response.md": "<changes>\nAdded a partial-delivery comment to issue 11. Status and location unchanged: the issue stays open in `docs/project/issues/`.\n\n- New `### First plan delivered` comment under `## Comments`, linking `docs/project/plans/19-11-fast-similars-response.md`.\n- It records the operator's two-phase reading and why the issue stays open: the page still renders nothing until `/api/video` returns from the instance.\n- **Delivered:**\n  - `GET /api/video/refresh`. `/api/video` currently runs the same handler.\n  - The instance write runs only when the instance's video detail call answered, under its own statement deadline. The comment records the accepted behaviour change: a failed fetch no longer writes, bumps `last_checked_at` or clears `instances.last_error*`, and this already applies to `/api/video`.\n  - The Client proxy gives the refresh 20 s and no retry.\n  - Similars are not delayed, because the instance calls run outside `db_lock`.\n- **Still to do** in the follow-up plan: R1, R3, R4, R5 and R6.\n- Each claim was checked against `engine/server/api/handlers/video.py` and `client/backend/server.py`: the `{}` return, the `statement_deadline` + `db_lock` write, the lock held only for the row read, the handler delegation, and the 20 s / 0-retry mappings.\n- Deliberately not done: the checklist's harvest action (`Status: complete` and moving the file to `archive/`).\n</changes>\n\n<not_on_checklist>\nnone\n</not_on_checklist>"
  },
  "requirements": "### Purpose\n\nNothing on the video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) waits on the source PeerTube instance. Similar videos and the current video's stored metadata render immediately from the Engine's local DB; a separate refresh request fetches live metadata from the instance, persists it to the Engine DB, and updates the page when it arrives. Operator chose the \"two-phase metadata\" reading of the issue.\n\n### Findings from the tree that shape this build\n\n- The page already starts `loadVideo()` and `loadSimilarVideos()` in parallel, and the similars route (`/recommendations`, proxied by `client/backend/server.py` to the Engine's `_handle_similar` in `engine/server/api/handlers/similar.py`) is served from ANN/cache/DB without contacting the instance. Both the Client backend and the Engine are `ThreadingHTTPServer`, so the two requests do not serialise. The \"similars first\" part of the issue is therefore already mostly true; what stays empty is the current video's own panel.\n- `loadVideo()` renders nothing until metadata arrives. The Engine's `handle_video_request` (`engine/server/api/handlers/video.py`) reads the DB row, then synchronously calls the instance (`fetch_instance_video_dynamic`: `/api/v1/videos/{id}` then `/api/v1/video-channels/{slug}`, `timeout=8` each), merges, writes the DB, then responds. The Client backend proxy (`ENGINE_PROXY_TIMEOUT_SECONDS = 10`) can time out first, after which the browser falls back to `fetchVideoMetadataFromInstance` (another instance wait). Even on success, `fetchVideoMetadataFromServer` awaits the browser-side `fetchInstanceMetadata` (`https://{host}/api/v1/config`) before rendering.\n- The DB row (`fetch_video_row`) already holds title, description, embed_path, video_url, channel (name/url/display name/followers/avatar), account name/url, views, likes, dislikes and published_at: enough to render the panel immediately.\n- The Client backend allow-list `PROXY_ALLOWED_QUERY_PARAMS[\"/api/video\"]` already lists `refresh_cache`, which the Engine's video handler ignores today.\n\n### R1 - Fast metadata from the DB\n\nThe Engine's `GET /api/video` answers from the DB row only; it makes no instance call and performs no DB write. The response keeps its current JSON shape and field names (`videoUuid`, `title`, `description`, `channelName`, `channelUrl`, `channelAvatarUrl`, `subscribersCount`, `instanceName`, `instanceUrl`, `accountName`, `accountUrl`, `accountAvatarUrl`, `embedUrl`, `originalUrl`, `views`, `likes`, `dislikes`, `publishedAt`), each filled from the DB with the same fallbacks as today (e.g. channel URL built from slug + host, original URL built from uuid/id + host). Fields only the instance supplies today (e.g. `accountAvatarUrl`) are empty or DB-sourced. A missing row still answers 404 `{\"error\": \"Video not found\"}`; a missing id still answers 400.\n\n### R2 - Separate refresh request\n\nA separate Engine route performs the live refresh, and the Client backend proxies it with its own query-parameter allow-list (same sanitising rules as the other read proxies). It:\n- resolves the row exactly as `/api/video` does (404 if absent);\n- fetches from the instance with today's behaviour: `timeout=8`, catching `HTTPError`/`URLError`/`TimeoutError`, field-by-field fallback to the DB row when the instance omits or fails a field;\n- on a successful instance fetch, persists with today's writes: the `videos` UPDATE (title, description, channel_name, views, likes, dislikes, popularity via `compute_popularity`, tags_json, category, nsfw, last_checked_at), the `channels` UPDATE when `channel_id` is known, and the reset of `instances.last_error`/`last_error_at`/`last_error_source`; a `sqlite3.OperationalError` on write is logged and does not fail the response, as today;\n- on a failed instance fetch writes nothing;\n- returns the merged metadata in the same shape as `/api/video`.\nThis route is the single write path for per-request metadata refresh, so issue 10 (metadata completeness) can extend it later.\n\n### R3 - Page flow and ordering\n\nOn load the page starts three independent requests: similars, fast metadata (R1), and refresh (R2); none awaits another. The video panel renders from whichever metadata response arrives first; when the refresh succeeds the panel re-renders with its values. Refreshed data always wins regardless of arrival order: a fast response arriving after the refresh must not overwrite refreshed values. If the refresh fails, errors or times out, the panel keeps what it shows and no error is shown to the visitor (a console warning is acceptable).\n\n### R4 - No instance wait before first render\n\nNothing in the first render of the video panel awaits a request to the source instance. The browser-side `fetchInstanceMetadata` call (`/api/v1/config`, supplying instance name and avatar) moves off the first-render path; its values fill in when it resolves. Until then the instance chip shows the host with initials fallback, as it does today when that call fails.\n\n### R5 - Video unknown to the Engine\n\nWhen fast metadata answers 404 (or fails), the panel renders immediately from the URL params (`title`, `channel`, `channelUrl`, `embed`, `url`, `host`, as `fallback` holds them today), and the existing direct browser-to-instance fallback (`fetchVideoMetadataFromInstance`) fills it in when it arrives. The existing `https://`-only check on the embed URL is kept on every render path.\n\n### R6 - Re-render safety\n\nA re-render of the panel:\n- does not reassign the embed iframe `src` when the embed URL is unchanged (playback must not restart);\n- does not attach duplicate listeners to the like, dislike, block-channel or block-account buttons (the existing `dataset.wired` guards keep holding);\n- does not fetch the visitor's reaction again once it has been fetched for the same video uuid/host;\n- keeps escaping and `safeExternalUrl` on every value it writes, as today.\n\n### R7 - Similars unchanged\n\nSimilars content, ranking, limit (8), the `localLikesImported` wait, profile-key handling and error display are unchanged. A test shows that a similars request is answered without contacting the source instance and is not delayed by a slow metadata/refresh call running concurrently.\n\n### Constraints\n\n- The refresh route's worst case on the instance is about 16 s (two sequential 8 s calls) while the Client proxy times out at 10 s. The design step must decide how the refresh fits that budget (for example a per-route proxy timeout, a shorter instance timeout, or a single overall budget) and state the choice; a proxy timeout on the refresh must degrade per R3 (panel keeps its values), never blank the page.\n- Stdlib only on the Python side; no new frontend dependency. New code matches the style of the file it lands in.\n- `client/frontend/dist/` is build output and is not hand-edited.\n\n### Out of scope\n\n- Rendering tags/category and refreshing further fields (issue `10-video-metadata-completeness`).\n- Loading more similars on scroll / removing the similar-videos page (issue `12-similars-on-scroll`).\n- Similars diversity (issue `09-similars-diversity`).\n\n### Baseline suite state\n\nPre-build suite exited 0; baseline variant: false. Tests live in `tests/active` (working area `tests/tmp`).",
  "approved": [
    "1",
    "2",
    "3",
    "3",
    "3",
    "5",
    "6",
    "9"
  ],
  "initial_solution": "### Approach\n\nThe Engine's single video handler becomes two routes over one merge step. On the frontend, `loadVideo` is split into a render function that can run more than once and a small coordinator that decides which result wins.\n\n**Engine (`engine/server/api/handlers/video.py`, dispatch in `engine/server/api/handlers/similar.py`).** `handle_video_request` is split into three module-level functions in the file's existing style:\n- a row resolver: id/host parsing, 400 on missing id, 404 `{\"error\": \"Video not found\"}` on a missing row, using `fetch_video_row` with `video_error_threshold` as today;\n- a pure merge that takes the row, a `dynamic` dict and the instance domain, and returns the response dict. This is today's merge block unchanged: `dynamic`-or-row per field, channel URL from slug + host, original URL from uuid/id + host, embed from `embed_path`;\n- a persist function holding today's three UPDATEs, its `sqlite3.OperationalError` catch and its log line, unchanged.\n\nHow each requirement is met:\n- **R1.** `GET /api/video` = resolve, then merge with an empty `dynamic`. No `urlopen`, no write. Every field falls back to the DB exactly as today. `accountAvatarUrl` comes back empty because no DB column holds it.\n- **R2.** A new `GET /api/video/refresh`, added next to the `/api/video` branch in `SimilarHandler`'s GET dispatch. It resolves the row the same way, calls `fetch_instance_video_dynamic` (unchanged: `timeout=8` per call, same exception set, same field picking), merges, persists only when the instance fetch succeeded, and responds with the same shape. This handler is the one per-request write path that issue 10 extends later.\n- **Success signal (a gotcha found while reading).** `fetch_instance_video_dynamic` currently always returns a non-empty dict of keys, even when the detail call failed. Today's `if dynamic` guard is therefore always true, so today a failed fetch still writes DB values back, bumps `last_checked_at` and clears `instances.last_error`. R2 says a failed fetch writes nothing, so the function returns `{}` when the `/api/v1/videos/{id}` call itself returns `None`. Success means \"the video detail came back\". A failed channel sub-call still counts as success, with DB fallback for the channel fields, which matches the field-by-field rule. The function has no other callers; I grepped the tree.\n\n**Client backend (`client/backend/server.py`).**\n- `/api/video/refresh` is added to `PROXY_READ_GET_ROUTES`, so it gets the same rate limit and the same `_handle_engine_read_proxy_get` sanitising: unknown key \u2192 400, repeated key \u2192 400, values stripped.\n- Its own `PROXY_ALLOWED_QUERY_PARAMS` entry is `{\"id\", \"host\"}`. `refresh_cache` stays on `/api/video`'s list, untouched.\n- It is not in `FILTERED_ROUTES`, so it passes through `_profile_filter` untouched.\n\n**Budget decision (the constraint).** The refresh route gets a per-route proxy timeout of 20 s and no proxy retry. Everything else keeps `ENGINE_PROXY_TIMEOUT_SECONDS = 10` and `ENGINE_PROXY_RETRY_COUNT = 1`. It is implemented as a small path\u2192timeout mapping and a path check on the retry count inside `_proxy_engine_request`.\n- The Engine's worst case of about 16 s (two sequential 8 s calls) fits, so R2 keeps today's instance timeouts literally.\n- Dropping the retry matters as much as the timeout. Today a transport timeout is retried, which on this route would fire a second pair of instance calls and possibly a second write.\n- If the proxy still gives up, the browser gets the proxy's usual failure status. R3 treats that as a failed refresh: the panel keeps its values and a console warning is logged.\n- The Engine thread carries on and may still persist the result, which is harmless and even useful for the next visit.\n\n**Frontend (`client/frontend/src/pages/video-page/index.ts`).**\n- `loadVideo` becomes `renderVideo(metadata)`: today's body, minus the fetching.\n- A coordinator starts three things at load, none awaiting another:\n  - the fast `/api/video` fetch;\n  - the `/api/video/refresh` fetch;\n  - one shared `fetchInstanceMetadata(host)` promise.\n  `loadSimilarVideos()` stays exactly as it is.\n- **R3 ordering.** Each metadata source carries a rank: URL params 0, fast DB 1, direct browser-to-instance fallback 2, refresh 3. A result renders only if its rank is at least the rank currently shown. A late fast response therefore never overwrites refreshed values, whatever the arrival order. A failed or non-OK refresh logs `console.warn` and changes nothing.\n- **R4.** `fetchVideoMetadataFromServer` no longer awaits `fetchInstanceMetadata`. When the shared instance promise resolves, its avatar (and its name, where today's precedence lets the name through) is stored and the current best metadata is re-rendered. Until then the instance chip shows the host with initials, as it does today when `/api/v1/config` fails. Today's precedence is kept: the Engine's `instanceName`/`instanceUrl` win over the config values, and only the avatar is new. The direct-instance fallback also stops awaiting `fetchInstanceMetadata` and uses the shared promise.\n- **R5.** If the fast fetch returns non-OK or throws, the panel renders at once from `fallback` (rank 0). `fetchVideoMetadataFromInstance` then runs, and its result renders at rank 2 when it arrives. The `https://` check on the embed stays inside `renderVideo`, so every path passes through it.\n- **R6.**\n  - A module-level `lastEmbed` holds the last embed string assigned; `src` is set only when the checked embed differs from it. The comparison is against our own string, not `embedEl.src`, which the browser normalises.\n  - The block and like buttons keep their `dataset.wired` guards.\n  - `loadReaction` is gated by a `uuid|host` key of the last reaction fetched, so re-renders do not fetch it again for the same video.\n  - Escaping and `safeExternalUrl` stay on every write because the rendering code itself is not changed.\n- **R7.** Similars code is untouched. The new test starts the Engine handler over a fixture DB with `fetch_instance_json` patched to block for several seconds. It fires a refresh and then a similars request concurrently, and asserts the similars answer arrives well inside that delay with the instance stub never called by it.\n\nFiles touched: `engine/server/api/handlers/video.py`, `engine/server/api/handlers/similar.py` (one dispatch branch), `client/backend/server.py`, `client/frontend/src/pages/video-page/index.ts`, and `engine/server/README.md` (route list). `dist/` is regenerated by the build, not edited.\n\n### Alternatives considered\n\n- **Keep one `/api/video` with a `refresh_cache` flag, since the allow-list already carries it.** Rejected: R2 asks for a separate route. A flag would also give one route two latency profiles, so a proxy timeout could not be tuned per behaviour.\n- **Refresh in the background inside the Engine after `/api/video` answers from the DB, with the page polling or calling again.** Rejected: it needs a thread or queue and a second read to see the result, where one extra request already carries the data.\n- **Shorten the instance timeouts, or give the Engine one overall deadline of about 9 s across both calls, so the refresh fits the existing 10 s proxy timeout.** This keeps the proxy uniform. Rejected because R2 fixes `timeout=8` as today's behaviour, and the refresh is off the render path, so waiting longer costs the visitor nothing. It remains the upgrade if long-held threads ever matter.\n- **Render from the URL params at t=0, before any response.** Rejected: the `?embed=` value and the DB `embed_path` can differ textually, which would reload the iframe moments later. R3 also says the first render comes from a metadata response. The URL-param render happens only when the fast call fails, as R5 says.\n- **Extract the rank arbitration into a shared lib module for testability.** Not chosen by default: it has one caller. Tests can drive the page in node with a stubbed `document`/`fetch`, the same way `test_frontend_blocks.py` stubs the platform. If that proves too heavy, the test step may justify extracting the helper.\n\n### Risks, gotchas and limitations\n\n- `urlopen(timeout=8)` bounds each socket operation, not the whole call. A slowly dripping instance can take longer than 16 s. The 20 s proxy timeout caps what the browser waits, and R3's degrade covers it.\n- Each page view now holds a Client thread and an Engine thread for up to about 20 s on a slow instance, instead of up to 10 s plus a retry. Both servers are `ThreadingHTTPServer` with unbounded threads, so this costs memory, not correctness.\n- Each page view now makes two Client\u2192Engine metadata requests, so it spends two rate-limit tokens instead of one. The refresh has its own per-path bucket, so it does not eat into `/api/video`'s.\n- The fast path no longer bumps `last_checked_at`; only a successful refresh does. Nothing I read keys on it per request, but a worker that relies on it would see fewer bumps. They would now be honest ones, because today it is bumped even on failure.\n- The first-wired closures keep the first known video: the reaction listener captures the first `reactionVideo()`, and `enableBlockButtons` the first uuid. Re-renders do not rewire them. This is unchanged from today, but it becomes visible only if a later source reports a different uuid than the first, which should not happen for one row.\n- Avatar `innerHTML` is rewritten on every re-render, so the images may flicker once. This is cosmetic; skipping unchanged avatars is a trivial follow-up if it shows.\n- If the fast call fails but the refresh succeeds, for example on a transient proxy error, rank 3 wins as intended, and the direct-instance fallback's later result is ignored.\n\n### Tradeoffs the operator is asked to accept\n\n- A refresh against a slow or dead instance can keep a request open for up to 20 s, and the proxy does not retry it. This is the price of keeping today's 8 s per-call instance timeouts inside R2.\n- `accountAvatarUrl` is empty on first render and appears only after a successful refresh, because the DB has no column for it. Adding one is issue-10 territory.\n- A failed instance fetch no longer clears `instances.last_error` or bumps `last_checked_at`. This follows directly from R2 but changes today's accidental behaviour.",
  "conflicts": "none",
  "impacts": "<impacts>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"handle_video_request() (lines 208-361), split into resolver, pure merge, persist, plus a /api/video handler and a /api/video/refresh handler\">\n**What changes.** The one function becomes three module-level helpers and two thin route handlers.\n- **Resolver.** Takes lines 210-224. `id` falls back to `video_id` and `host` to `instance_domain` (210-211). It answers 400 `{\"error\": \"Missing video id\"}` and 404 `{\"error\": \"Video not found\"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` inside `with server.db_lock:`, which is held for 215-221 only.\n- **Merge.** Takes lines 226-290 with `dynamic` passed in. Line 226, `instance_domain = row.get(\"instance_domain\") or host_param or \"\"`, needs `host_param`, so the resolver has to hand back `host_param` or `instance_domain` along with the row.\n- **Persist.** Takes lines 292-358. It needs the merged intermediates (`title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`) plus `row[\"video_id\"]`, `row[\"channel_id\"]`, `row[\"published_at\"]` and `instance_domain`. The response dict cannot supply them:\n  - it has no `channel_slug`, `tags_json`, `category` or `nsfw`;\n  - it turns `None` into `\"\"` (`channelName: channel_display or \"\"`, `title or \"\"`).\n  So feeding persist from the response would write `\"\"` where today's code writes `NULL`. The plan says the merge \"returns the response dict\"; it must also expose the intermediates, or persist must re-derive them. The plan leaves this open.\n- **`/api/video`.** Resolve, then merge with `{}`. Every `dynamic.get(...)` is `None`, so each field falls back to the row exactly as today. `accountAvatarUrl` (283) becomes `\"\"`. `accountName`/`accountUrl` (281-282) already come from the row only.\n- **`/api/video/refresh`.** Resolve, `fetch_instance_video_dynamic`, merge, persist only on success, then respond with the same shape.\n- **Docstrings.** The module docstring (1-7, \"Merge DB metadata with live instance metadata (when available)\") and line 209 must say which route does what.\n\n**What depends on it.** `engine/server/api/handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else imports it. No test in `tests/active` touches this module (grep for `handlers.video`, `/api/video` and `fetch_instance` over `tests/`); only the smoke scripts call `/api/video`.\n\n**Regression risk: medium.**\n- **Lock boundary.** The instance call must stay outside `server.db_lock`, as today, where the lock is taken only around the SELECT (215) and around the UPDATEs (303). Pulling the fetch inside the resolver's `with` block would stall every Engine route that takes the lock (similar.py 261, 467, 652, 884, 957; similars included) for up to about 16 s, which breaks R7.\n- **Renames.** A renamed or removed `handle_video_request` breaks the import at similar.py:84. That is an import-time failure of the whole Engine, and every test that uses the session `engine` fixture fails with it.\n- **Races.** The row is read before the instance call and written after it, so two concurrent refreshes of one video both write and the last one wins. This is harmless.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails\">\n**What changes.** Line 164 today is `detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\") or {}`. It becomes an early `return {}` when the detail call does not come back.\n\n**The gotcha is confirmed.** The return at 188-205 always builds a 14-key dict, so the `if dynamic and instance_domain and row.get(\"video_id\")` guard at 293 is always true today. A failed fetch therefore:\n- writes DB values back;\n- recomputes `popularity`;\n- bumps `last_checked_at`;\n- clears `instances.last_error*`.\n\n**Edge cases for the success test.**\n- **Non-dict JSON.** `fetch_instance_json` returns whatever `json.loads` gives. A 200 with a JSON array or string reaches `detail.get` and raises `AttributeError`, which nothing catches. This is pre-existing.\n- **Empty object.** A 200 with `{}` passes an `is not None` test but carries no data, so persist would write DB values back and clear `last_error`.\n- **The fix.** Testing `isinstance(detail, dict) and detail` closes both cases.\n\n**Channel sub-call.** The sub-call at 176 runs only when `channel_slug` came back, so after the change it runs only on success.\n\n**What depends on it.** Only `handle_video_request` today (grep of the tree, tests included), and only the refresh handler after the build.\n\n**Regression risk: low.** This is the one deliberate behaviour change and the operator accepts it. The consequence: a failed fetch no longer resets `instances.last_error` or bumps `last_checked_at`.\n</impact>\n<impact path=\"engine/server/api/handlers/video.py\" element=\"fetch_instance_json() (lines 75-87): unchanged; the test seam; narrow exception set\">\n**What changes.** Nothing. The R7 test and the refresh tests patch it.\n\n**What depends on it.**\n- Both instance calls in `fetch_instance_video_dynamic` look it up as a module global. A test must patch the attribute on the `handlers.video` module; patching an imported alias has no effect.\n\n**The error path.**\n- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` misses `json.JSONDecodeError` (a non-JSON 200), `UnicodeDecodeError`, and `ConnectionResetError`/`http.client.RemoteDisconnected` raised during `resp.read()`.\n- **What happens then.** These escape the refresh handler. `SimilarHandler.do_GET` (similar.py:433-441) re-raises anything that is not an interrupted `OperationalError`, so the Engine drops the connection without answering.\n- **What the Client sees.** The drop reaches the Client as `RemoteDisconnected` or a reset, not as a `URLError`. It therefore lands in `except Exception` (client/backend/server.py:700-721), which answers 502 `ENGINE_PROXY_FAILURE`. The page treats that as a failed refresh (R3).\n- **Before and after.** This is pre-existing: today the same failure kills `/api/video` itself. After the split only the refresh can hit it.\n- **Timeout scope.** `timeout=8` bounds each socket operation, not the whole call.\n\n**Regression risk: none in code.**\n</impact>\n<impact path=\"engine/server/data/db.py\" element=\"statement_deadline() / _deadline_passed() / PROGRESS_HANDLER_INSTRUCTIONS (lines 14-64), as it applies to the refresh's persist\">\n**What changes.** Nothing in code, but the refresh's timing brings this into play.\n\n**How the deadline applies.**\n- `SimilarHandler.do_GET` (similar.py:436) runs the whole dispatch inside `self._statement_deadline()` (similar.py:345-353). That is `statement_deadline(server.statement_timeout_seconds)`, and `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0` (server_config.py:435) is assigned at `engine/server/api/server.py:272`.\n- The deadline is wall-clock time, thread-local, and counted from the start of the request.\n- The refresh reaches its UPDATEs only after up to about 16 s of instance calls, so by then its thread's deadline has usually passed.\n- The progress handler fires every 10,000 VM instructions (line 14). Any persist statement that runs that long after the deadline is aborted with `OperationalError: interrupted`.\n- The `videos` UPDATE fires `videos_fts_au` (`engine/server/db/jobs/sync-whitelist.py:279-284`), which deletes and re-inserts title, description, tags_json, category and channel_name into FTS5. Crossing 10,000 instructions is plausible there, especially with long descriptions.\n\n**Consequence.**\n- The persist's own `except sqlite3.OperationalError` (video.py:352-358) catches the abort, logs `[video] failed to persist dynamic metadata ... interrupted`, and `with server.db:` rolls back.\n- The response is still 200 with the refreshed values, so a successful but slow refresh can silently fail to persist, against R2.\n- This is pre-existing and masked today. After the build the refresh is the only writer, so it now matters.\n\n**Mitigation.** Wrap persist in its own nested `statement_deadline(...)`. Lines 59-64 save and restore the outer deadline, so nesting is supported. The other option is to state it as a limitation.\n\n**Regression risk: medium to high for R2's persist guarantee.** I have not measured whether one UPDATE plus the trigger actually crosses 10,000 instructions. A child-process test with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json` would show it.\n</impact>\n<impact path=\"engine/server/api/handlers/similar.py\" element=\"SimilarHandler._dispatch_get() /api/video branch (lines 495-497), import at line 84, module docstring route list (lines 3-13)\">\n**What changes.**\n- A new branch, `if url.path == \"/api/video/refresh\":`, goes beside line 495 and calls the refresh handler.\n- The import at line 84 gains the new name or names.\n- The docstring gains a `/api/video/refresh` line, and line 9 (`/api/video: single video metadata.`) should say it reads from the DB.\n\n**What depends on it.**\n- **Rate limit.** Line 447 rate-limits every path under `/api/` on the key `f\"{ip}:{path}\"` (`_rate_limit_check`, 576-583). The refresh therefore gets its own bucket (`DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60`, server_config.py:431). The ip comes from the `x-client-ip` header the Client sets (client/backend/server.py:590).\n- **Matching.** Paths are matched with `==`. `_extract_video_id_from_similar_path` (499) matches only `/videos/.../similar`, so without the new branch `/api/video/refresh` falls through to the 404 at 508. Nothing shadows it.\n- **Deadline.** Both routes run inside the statement deadline in `do_GET` (see the db.py entry). An interrupted error raised during the resolver's SELECT would still reach `_respond_interrupted` as a 503, but that SELECT is fast.\n\n**Regression risk: low.** It is one branch, and the similars dispatch (499-506, `_handle_similar_request`) is untouched, which keeps R7.\n</impact>\n<impact path=\"engine/server/api/handlers/__init__.py\" element=\"module docstring line 5 ('video: fetches video metadata for /api/video.')\">\n**What changes.** The line names both routes: `/api/video` (DB only) and `/api/video/refresh` (live instance refresh, persisted on success).\n\n**What depends on it.** Nothing.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/api/http_utils.py\" element=\"respond_json() (lines 23-30), the refresh's final write\">\n**What changes.** Nothing.\n\n**Why it matters.**\n- It writes to `handler.wfile` unguarded.\n- A slowly dripping instance can outlast the Client's 20 s proxy timeout, because `timeout=8` applies per socket operation. The Engine then writes its late answer to a socket the Client has already closed.\n- The write raises `BrokenPipeError`/`ConnectionResetError`, which `do_GET` does not catch, so `socketserver` prints a traceback to stderr.\n- By then persist has already run, so the data is kept, and the browser has already had its 502.\n- This is pre-existing on `/api/video` at 10 s; after the build only the refresh can hit it.\n\nUnlike this Engine helper, the Client side's `respond_bytes` already returns False when the client disconnects (server.py:619).\n\n**Regression risk: low (log noise).**\n</impact>\n<impact path=\"engine/server/api/server.py\" element=\"SimilarServer (ThreadingHTTPServer, line 207): video_error_threshold (230/264), popularity_like_weight (234/268), statement_timeout_seconds (272), db, db_lock\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The resolver reads `server.video_error_threshold` directly, not through `getattr`.\n- Persist reads `getattr(server, \"popularity_like_weight\", 2.0)`, `server.db` and `server.db_lock`.\n- `ThreadingHTTPServer` gives each request its own thread, so a refresh blocked on an instance holds one thread and not the server. R7 relies on this.\n\n**Test note.** A child-process test needs a server object that carries `db`, `db_lock` and `video_error_threshold`, plus `popularity_like_weight` if persist runs and `statement_timeout_seconds` if the deadline is exercised. `tests/active/test_internal_events.py:52` builds a real `SimilarServer` from kwargs this way.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"engine/server/data/popularity.py\" element=\"compute_popularity(), called by persist (video.py:295-301)\">\n**What changes.** Nothing. It moves with the persist block. Its arguments must stay:\n- the merged `views`/`likes` (the instance value, or the DB fallback);\n- `row[\"published_at\"]`;\n- the like weight;\n- `now_ms_value=checked_at`.\n\n**What depends on it.** The `videos.popularity` column, which ranking reads.\n\n**Regression risk: low.** Today it runs on every page view, including failed fetches that write the DB values back unchanged. After the build it runs only on a successful refresh, and the popular-video ordering reads the same column.\n</impact>\n<impact path=\"engine/server/db/jobs/sync-whitelist.py\" element=\"videos_fts_au AFTER UPDATE trigger (lines 279-284)\">\n**What changes.** Nothing.\n\n**What depends on it.** Every persisted refresh fires the trigger and re-indexes the video for search. Writes fall from one per page view (failures included) to one per successful refresh, so FTS churn and write-lock time go down. It is also why the statement-deadline entry matters.\n\n**Regression risk: none in code.**\n</impact>\n<impact path=\"engine/server/data/metadata.py\" element=\"readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301), data/search.py (80), data/channels.py (129-159, instances.last_error*)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- These files only project `last_checked_at` and `instances.last_error*` into rows. A grep of `engine/server` (outside whitelist_migrations.py) shows nothing that filters or orders on them.\n- The frontend source never reads `last_checked_at` (grep of `client/`, dist excluded).\n- So the fast path no longer bumping them, and a failed refresh no longer clearing `last_error`, is invisible to serving.\n- `/api/channels` exposes `last_error*` as data, so a stale error now stays visible there until a successful refresh or a crawl clears it.\n\n**Regression risk: none in serving; low for the `/api/channels` display.** I did not audit the crawler (`engine/crawler`), which keeps its own DB.\n</impact>\n<impact path=\"engine/server/api/server_config.py\" element=\"DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0 (435), DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60 (431), line 455 comment ('Optional future toggle for /api/video hide behavior')\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The statement budget interacts with the refresh persist.\n- The Engine's per-path rate limit now applies to the refresh as a separate bucket.\n- The line 455 toggle is not referenced by video.py and stays unrelated.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/backend/server.py\" element=\"PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)\">\n**What changes.**\n- `\"/api/video/refresh\"` joins the frozenset.\n- A new entry `\"/api/video/refresh\": {\"id\", \"host\"}` is added.\n- `/api/video` keeps `{\"id\", \"host\", \"refresh_cache\", \"user_id\"}`.\n\n**What depends on it.**\n- `do_GET` (277-282) routes on `url.path in PROXY_READ_GET_ROUTES`. It applies `_rate_limit_check(url.path)` (406-409, key `ip:path`, `RATE_LIMIT_MAX_REQUESTS = 90` per 60 s), so the refresh gets its own Client bucket, then calls `_handle_engine_read_proxy_get`.\n- `_handle_engine_read_proxy_get` (417-436) answers 400 on an unknown key or a repeated key, and strips values.\n- The frontend must send only `id` and `host`: a `user_id` or `refresh_cache` on the refresh now gets 400.\n\n**Regression risk: low.** It is a pure addition.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_proxy_engine_request() (lines 570-745) with ENGINE_PROXY_TIMEOUT_SECONDS (77), ENGINE_PROXY_RETRY_COUNT (79), ENGINE_PROXY_RETRY_DELAY_SECONDS (80)\">\n**What changes.** A path\u2192timeout mapping (20 s for the refresh, `ENGINE_PROXY_TIMEOUT_SECONDS` otherwise) and a per-path retry count (0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise).\n\n**Four sites must read the per-path values.**\n- 604: `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)`.\n- 606: `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)`.\n- 696: `if attempt < ENGINE_PROXY_RETRY_COUNT`.\n- 731: the `\"attempts\": ENGINE_PROXY_RETRY_COUNT + 1` field of the \"proxy request unavailable\" log. It is easy to miss; left alone it logs 2 attempts for a refresh that made 1.\n\n**Key on `path`.** The mapping must use `path`, not `upstream`, which carries the query string (581-583).\n\n**What depends on it.** Every proxied read:\n- GET `/api/video`, `/api/channels` and `/api/v1/search/videos`;\n- POST `/recommendations` and `/videos/similar` (561).\n\nAll of them must keep 10 s and one retry.\n\n**How a refresh failure surfaces.**\n- The Engine writes nothing until it finishes, so the proxy waits up to the full timeout.\n- `socket.timeout` is `TimeoutError`, which lands in the `(URLError, TimeoutError)` branch (694). With 0 retries the loop breaks to the 502 `ENGINE_PROXY_UNAVAILABLE` (736-744).\n- A dropped Engine connection lands in the generic 502 (700-721).\n- An Engine 404 or 400 with a body passes through the HTTPError branch (646-677).\n- All of these are non-OK for the browser.\n\n**Test harness.** `tests/active/test_server.py` offers `_serving` (347-355), `_client_backend` (358-367), `_status` (370-378, `timeout=30`) and an `EngineStub` (400-422), which together are the template for a stub that counts GETs and sleeps. No existing test monkeypatches the proxy constants, so a new test can patch them or the mapping on `client_server` to stay fast.\n\n**Regression risk: medium.** This loop carries every browser read. A wrong key or a missed site silently changes the timeout or retry for every route, so tests must pin both the refresh and one ordinary route.\n</impact>\n<impact path=\"client/backend/server.py\" element=\"_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- The refresh gets the same sanitising.\n- An empty value is dropped (431), so `id=` reaches the Engine with no `id` and gets its 400 `Missing video id`, which the Client passes through.\n- `_profile_filter` returns `(True, None, None, None)` for the refresh, because it is in neither `FEED_ROUTES` nor `FILTERED_ROUTES` (71-72). An `X-Profile-Key` header on it is therefore ignored rather than validated.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"module top level: `void loadVideo()` (79), `void loadSimilarVideos()` (80), currentMetadata (50), seedId/seedHost (54-55), fallback (57-63), localLikesImported (75-77), applyActionIcons() (1226)\">\n**What changes.** Line 79 becomes the coordinator start. Line 80 is unchanged.\n\n**What the coordinator must preserve.**\n- **No usable source.** When `resolveVideoSource()` gives no host or no id, `fetchVideoMetadata` returns `null` at 508, and today the page renders once with `metadata = null` from `fallback`, `seedHost` and `https://${seedHost}`. That must be kept, and in that case neither the fast fetch nor the refresh should fire.\n- **`currentMetadata` in step.** It must always equal the metadata actually rendered, because `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost` (1151-1166).\n\n**Testing constraints.** The module does DOM work at import:\n- about 27 `getElementById` constants (22-48);\n- `window.location.search` (53);\n- `importLocalLikes` (75);\n- `applyActionIcons()` (1226);\n- `import \"../../video.css\"` (5).\n\nA node test of the page therefore needs a stubbed `document`/`window`, a scripted `fetch`, `localStorage`, and an esbuild css loader flag. The existing frontend tests (`test_frontend_blocks.py:23,66`, `test_frontend_videos.py`, `test_frontend_reactions.py`, `test_frontend_profile.py`) bundle data modules only, with `--platform=node`.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadVideo() (lines 85-229) becoming renderVideo(metadata)\">\n**What changes.** The body stays, minus `await fetchVideoMetadata()` (86). `currentMetadata = metadata` (87) moves into or next to it. It now runs once per accepted source, and again when the instance config arrives.\n\n**What re-runs on every render.**\n- **Text and markup.** Title, the channel `innerHTML` through `escapeHtml`/`safeExternalUrl` (120-122), subscribers, instance link, account link, description, views, counts and the original link. All of these are idempotent.\n- **Avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatars (154-161, 179-186) are rewritten, and `bindAvatarFallback` (426-437) binds a `once` listener to each fresh `<img>`. The old nodes are discarded, so listeners do not pile up, though an image may flicker.\n- **Embed (212-221).** Today it sets `embedEl.src = embed` unconditionally. The new `lastEmbed` guard must compare against the checked string actually assigned, and must be cleared when the `else` branch calls `removeAttribute(\"src\")`; otherwise a later valid identical URL is never reassigned.\n- **`document.title`** (114).\n- **`enableBlockButtons`** (196) is guarded by `dataset.wired`.\n- **`void loadReaction()`** (197) needs the new gate (see its entry).\n\n**Values across sources.**\n- The Engine sends `\"\"`, not null, for empty strings, so `metadata?.title ?? fallback.title` gives `\"\"`, and `titleEl` shows \"Video page\" through `title || \"Video page\"`, as today.\n- Ranks 1 and 3 both carry `embedUrl = resolve_asset_url(instance_domain, row.embed_path)`, which is textually identical, so there is no reload between them.\n- Rank 0 uses `fallback.embed` and rank 2 uses `resolveApiAssetUrl(host, embedPath)` (592). So when the fast call fails, one iframe reload between rank 0 and a later rank is possible. R6 covers only an unchanged URL.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)\">\n**What changes.**\n- The sequential \"server, else instance\" logic in `fetchVideoMetadata` moves into the coordinator.\n- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (525). It must now serve both `/api/video` and `/api/video/refresh`, through a path argument or a shared mapper; the refresh answers the same shape, so the mapping at 527-551 applies unchanged.\n\n**Precedence, confirmed in code.**\n- The Engine always sends `instanceName`/`instanceUrl` as strings (video.py:279-280, possibly `\"\"`), and `??` does not skip `\"\"`. So for ranks 1 and 3, `instanceMeta?.name`/`url` never win today (534-539); the config supplies only `instanceAvatarUrl` (540).\n- For rank 2 (608-610), the config's name and URL do win.\n- If re-applying the shared config overwrote `instanceName` for ranks 1 and 3, the chip label would visibly change from the host to the display name. It would also change `resolveLikeHost` when `seedHost` is empty.\n\n**Other effects.**\n- `catch { return null; }` (552-554) also swallows `response.json()` failures and non-OK statuses. The refresh caller needs its own failure signal to `console.warn`.\n- `instanceAvatarUrl` must be merged in from the shared promise on every render, or it disappears when a later rank re-renders.\n\n**Regression risk: medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)\">\n**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, because it is part of rank 2 itself.\n\n**Behaviour to keep.**\n- The rank-2 result has no `videoUuid`, so `resolveLikeUuid` falls back to `seedId` only when `looksLikeUuid` (1171-1173) accepts it.\n- `instanceName: instanceMeta?.name ?? source.host` (608) can be `\"\"`, because `getString` returns `\"\"` (724-730). `instanceMetaEl.hidden = !instanceName` (140) then hides the chip. This is pre-existing.\n- It runs only after the fast fetch fails (R5). If rank 3 is already shown, the rank rule drops its result, so the coordinator could skip starting it.\n\n**Regression risk: low to medium.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"fetchInstanceMetadata() (655-688) and getString() (724-730), as one shared promise\">\n**What changes.** It is called once per load, and the promise is shared.\n\n**What it returns.**\n- `getString` returns `\"\"`, never undefined, so the `?? ... ?? host` chain at 664-667 never reaches `host`.\n- `avatarUrl` is always set on success, falling back to `https://${host}/favicon.ico`.\n- Any failure, including a CORS failure, resolves to `null` and never rejects, so a `.then` needs no `.catch`.\n\n**What depends on it.**\n- The instance avatar on every rank, and the name and URL on rank 2.\n- When it resolves, the current best metadata is re-rendered at the same rank, so the rank rule must allow equal-rank renders (\"at least the rank shown\").\n- Rank 0 renders with `null` metadata, so if the avatar should appear there, it has to be applied in `renderVideo` from a module variable, not merged into the metadata object.\n\n**Constraint.** It may start only once a host is known.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadReaction() (318-341), reactionVideo() (381-386), react()/renderReaction() (346-364)\">\n**What changes.** A module-level `uuid|host` key for the last reaction fetched gates `fetchReaction`.\n\n**How the gate must work.**\n- **Non-null video only.** `reactionVideo()` depends on `currentMetadata`. On a rank-0 or rank-2 render with a non-UUID `seedId` it returns `null`, and `loadReaction` returns at 320 without wiring the buttons. A later rank that carries `videoUuid` (1 or 3) must still fetch and wire, so the key is set only when `video` is non-null.\n- **Before the first await.** `await localLikesImported` (322) comes before the fetch, so the key must be written before that first `await`. Otherwise two quick renders both pass the gate and fetch twice.\n- **Listeners.** The listeners (331-340) capture the first non-null `video` and are never rewired, because of `likeButton.dataset.wired` (327). This is unchanged.\n\n**What depends on it.** `renderReaction` and `setReactionStatus`. `tests/active/test_frontend_reactions.py` exercises `data/reactions.ts`, not this page.\n\n**Regression risk: medium.** A wrong gate either breaks R6 (a second fetch) or leaves the buttons disabled when the uuid arrives only with a later rank.\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"enableBlockButtons() (275-308)\">\n**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.\n\n**What depends on it.**\n- It captures `uuid` and `host` from the first call where both are non-empty.\n- On a rank-0 render, `metadata?.videoUuid || resolveVideoSource()?.id` (196) is `seedId`, which may be a numeric id, and the buttons keep it for good.\n- That already happens today when `/api/video` fails. It is more reachable now, if the fast call fails and the refresh brings the real uuid later.\n- I did not trace whether `blockVideoSource` resolves a numeric id.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"client/frontend/src/pages/video-page/index.ts\" element=\"loadSimilarVideos() (234-269) and the similar stats helpers\">\n**What changes.** Nothing (R7). It waits only on `localLikesImported` and never on metadata.\n\n**Regression risk: none,** as long as the coordinator neither awaits it nor chains it.\n</impact>\n<impact path=\"client/frontend/video-page.html\" element=\"CSP meta (line 8)\">\n**What changes.** Nothing.\n\n**What depends on it.**\n- `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser\u2192instance fetches.\n- `frame-src https:` matches the embed's `https://` check.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"client/frontend/dist/assets/video-gjYm1MC8.js\" element=\"built video page bundle (build output)\">\n**What changes.** The build regenerates it under a new hash; it is never edited by hand.\n\n**What depends on it.** The deployed static site serves `dist`.\n\n**Regression risk: low.** A stale `dist` deployed against the new Engine still works, because `/api/video` keeps its shape. It just no longer gets live values or the account avatar.\n</impact>\n<impact path=\"client/frontend/vite.config.ts\" element=\"dev server proxy '/api' (lines 27-28)\">\n**What changes.** Nothing. The `/api` prefix already covers `/api/video/refresh` in dev.\n\n**Regression risk: none.** I did not check whether a dev proxy timeout is set.\n</impact>\n<impact path=\"tests/check-frontend-client-gateway.sh\" element=\"frontend gateway preflight (lines 22-38)\">\n**What changes.** Nothing. It forbids only:\n- Engine base usage;\n- hard-coded Engine ports;\n- `/internal/*` routes in `client/frontend/src`.\n\nA `/api/video/refresh` literal passes.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"DEPLOYMENT.md\" element=\"nginx `location /api/` (319-325); ufw prose (369, 374-375)\">\n**What changes.**\n- **nginx block.** Needs nothing. `location /api/` already proxies `/api/video/refresh`, and no `proxy_read_timeout` is set, so nginx's 60 s default exceeds 20 s.\n- **ufw comment (369).** \"live video metadata\" stays true.\n- **Prose at 374-375.** \"`/api/video` makes live calls to source instances per request\" becomes wrong (see the docs checklist).\n\n**Regression risk: none in config.**\n</impact>\n<impact path=\"tests/active/conftest.py\" element=\"engine fixture (105-140) over WHITELIST_DB (34); ENGINE_PY (32); ENGINE_SERVER (33); CLOSED_ENGINE (45)\">\n**What changes.** Nothing.\n\n**What new tests must avoid.**\n- A refresh through the session `engine` fixture would make real outbound HTTPS calls and write to the shared `whitelist.db`.\n- Refresh tests and the R7 test must run the handler in an `ENGINE_PY` child over a temporary DB, with `handlers.video.fetch_instance_json` patched.\n- Precedents: `test_internal_client_reads.py:144-145`, `test_internal_events.py:52,174`, and the child runs in `test_similar.py` (237, 307, 415, 533).\n- A fast `/api/video` against the shared Engine is safe after the build (no calls, no writes).\n\n**Regression risk: medium for test hygiene.**\n</impact>\n<impact path=\"tests/active/test_server.py\" element=\"_serving/_client_backend/_status/EngineStub pattern (lines 347-422)\">\n**What changes.** Nothing. It is the template for the new proxy test.\n\n**The new test.** A stub Engine counts GETs and sleeps past a monkeypatched timeout on `/api/video/refresh`. It checks two things:\n- the refresh makes one attempt;\n- `/api/video` still retries once.\n\n**Test group.** The file maps to `client/backend/server.py` and `engine/server/api/handlers/similar.py` in `.un/skills/devsecops/config.json` (57-60).\n\n**Regression risk: low.**\n</impact>\n<impact path=\".un/skills/devsecops/config.json\" element=\"test_groups mapping\">\n**What changes.** Nothing during the build.\n\n**Coverage gaps.** Grep finds no mapping for `engine/server/api/handlers/video.py` or `client/frontend/src/pages/video-page/index.ts`. Any new test file for them needs an entry at harvest, or it runs only in full-suite runs.\n\n**Regression risk: low.**\n</impact>\n<impact path=\"tests/run-arch-split-smoke.sh\" element=\"client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647) and README.md line 134\">\n**What changes.** Nothing is required: `/api/video` still answers 200, and faster.\n\n**Optional.** A `/api/video/refresh` check would depend on outbound 443, so asserting \"200 or 502\" is safer.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/security-audit/run-1/REPORT.md\" element=\"line 299 (`/api/video` performs up to two outbound HTTPS requests); also run-1/architecture.md:35,67, run-1/FINDINGS-DETAIL.md:127, run-2/REPORT.md:73,125,221, run-2/FINDINGS-DETAIL.md:12,136, run-2/findings.json\">\n**What changes.** Nothing. These are dated audit records and are not rewritten. I list them only because a grep for `/api/video` hits them and they describe the old behaviour.\n\n**Regression risk: none.**\n</impact>\n<impact path=\"docs/project/plans/19-11-fast-similars-response.record.md\" element=\"workflow record for this build\">\n**What changes.** The workflow renders it; do not hand-edit it. It already holds an earlier step-3 pass. I re-read the files it names, and its line numbers still match the tree.\n\n**Regression risk: none.**\n</impact>\n</impacts>",
  "docs_checklist": "- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/api/video` entry is updated, a `/api/video/refresh` entry is added, the write-back rule is documented, and the \"read-only\" claim on line 3 is corrected.\n- [x] `README.md` - updated: Added `/api/video/refresh` to two rows of the boundary table: the Engine public read API and the Client read gateway.\n- [x] `client/README.md` - updated: Added `/api/video/refresh` to the Client read gateway list and described how its proxy differs from the other reads (allow-list, 20 s, no retry, 502 when it times out).\n- [x] `docs/project/issues/10-video-metadata-completeness.md` - updated: Added a comment to issue 10 about the metadata write path, merge rules and persist-on-success behaviour that issue 11 delivered. Body and `Status:` are unchanged.\n- [x] `docs/project/roadmap.md` - updated: Added `/api/video/refresh` to F2-M3's list of routes that still need versioning.\n- [x] `docs/project/issues/11-fast-similars-response.md` - updated: Added a partial-delivery comment to issue 11. Status and location unchanged: the issue stays open in `docs/project/issues/`.\n- [x] `client/frontend/README.md` - out of scope: No frontend phase landed: `client/frontend/src/pages/video-page/index.ts` was not touched, and the page does not call `/api/video/refresh`. Line 8's list of routes the frontend fetches (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) is still exactly right, and the page loads in the same order as before. The checklist's addition and its load-order sentence belong to the follow-up plan that builds the page coordinator.\n- [x] `DEPLOYMENT.md` - out of scope: Lines 374-375 (\"`/api/video` makes live calls to source instances per request\") are still true. `/api/video` was kept live in this build; only the follow-up plan makes it DB-only. The sentence's point, that outbound 443 is a runtime dependency, also still holds. The ufw comment at 369 (\"live video metadata\") is true. The nginx `location /api/` block already covers `/api/video/refresh`, and its default 60 s read timeout is longer than the 20 s proxy budget.\n- [x] `docs/project/issues/20-request-lifecycle-logs.md` - out of scope: Line 25 names `/api/video` in the smoke list for start\u2192end request logs. That route still exists and is still the long-running call bound to the instance, because it was kept live. This future-work spec says nothing that is now false. Adding `/api/video/refresh` would be a scope choice for whoever plans issue 20, not a correction.",
  "docs": [
    {
      "path": "engine/server/README.md",
      "note": "Line 9 (`/api/video` metadata for the video page) becomes two bullets:\n- `/api/video` answers from the local DB only, with no instance call and no write. The response shape is unchanged, and `accountAvatarUrl` is empty.\n- `/api/video/refresh` fetches live metadata from the source instance: video detail, then channel, with an 8 s socket timeout on each. It answers the same shape. Only when the detail call succeeds does it run the `videos`/`channels` UPDATE and reset `instances.last_error*`; a failed fetch writes nothing. It is the one per-request metadata write path.\n\nLine 3 (\"Read-only Engine API\") should acknowledge that the refresh route writes metadata."
    },
    {
      "path": "README.md",
      "note": "The boundary table at line 46 (Engine public read API) and line 48 (Client browser-facing read gateway): add `/api/video/refresh` to both route lists. Line 134 (the smoke check expects `/api/video` to answer 200) stays true."
    },
    {
      "path": "client/README.md",
      "note": "Line 37 (read gateway list): add `/api/video/refresh`. Optionally note that the refresh proxy accepts only `id` and `host`, waits up to 20 s and is not retried, while every other read proxy keeps 10 s with one retry."
    },
    {
      "path": "client/frontend/README.md",
      "note": "Line 8 (fetched gateway routes): add `/api/video/refresh`. Optionally add one sentence on the video page's load order:\n- it renders from `/api/video` first;\n- it re-renders when the refresh and the instance config arrive;\n- when `/api/video` fails, it falls back to the URL params and then to the direct instance fetch."
    },
    {
      "path": "DEPLOYMENT.md",
      "note": "Lines 374-375: \"`/api/video` makes live calls to source instances per request\" becomes `/api/video/refresh`, one live refresh per video page view. The ufw comment at 369 and the nginx block at 319-325 need no change."
    },
    {
      "path": "docs/project/issues/10-video-metadata-completeness.md",
      "note": "Add a comment rather than editing the body:\n- Line 22 (\"reflected after the next `/api/video` request\") now applies to `/api/video/refresh`.\n- Line 17's rule (\"the DB update and `instances.last_error` reset run only on a successful refresh\") is now real behaviour, delivered by this build.\n- The refresh handler in `engine/server/api/handlers/video.py` is the single per-request write path this issue extends.\n- Line 16 stays true."
    },
    {
      "path": "docs/project/issues/20-request-lifecycle-logs.md",
      "note": "Line 25 (smoke list naming `/api/video`): add `/api/video/refresh`. It is the long-running, instance-bound route whose start\u2192end logging matters most."
    },
    {
      "path": "docs/project/roadmap.md",
      "note": "Line 54 (F2-M3 API versioning lists the unversioned routes): add `/api/video/refresh`."
    },
    {
      "path": "docs/project/issues/11-fast-similars-response.md",
      "note": "At harvest:\n- set `Status: enhancement, complete`;\n- add a delivery comment recording the two-phase reading, the 20 s no-retry refresh budget, and the accepted `last_error`/`last_checked_at` change;\n- move the file to `docs/project/issues/archive/`."
    }
  ],
  "reassessments": 3,
  "draft": "## Draft implementation: two-phase video metadata (issue 11)\n\n### Module map\n\n| File | Change |\n|---|---|\n| `engine/server/api/handlers/video.py` | `fetch_instance_video_dynamic` returns `{}` on a failed detail call. `handle_video_request` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`. `handle_video_request` (DB only) keeps its name; `handle_video_refresh_request` is new. Module docstring updated. |\n| `engine/server/api/handlers/similar.py` | Import gains `handle_video_refresh_request`. New `/api/video/refresh` dispatch branch. Docstring route list updated. |\n| `engine/server/api/handlers/__init__.py` | Docstring line 5 names both routes. |\n| `client/backend/server.py` | Route and allow-list entries. Two per-path mappings (timeout, retry count), read at four sites in `_proxy_engine_request`. |\n| `client/frontend/src/pages/video-page/index.ts` | `loadVideo` \u2192 `renderVideo(metadata)`. Coordinator `startVideoLoad` with rank arbitration. Shared instance-config promise. Embed and reaction guards. `fetchVideoMetadataFromServer(path, source)`. `fetchVideoMetadata` removed. |\n| Docs | `engine/server/README.md`, `README.md`, `client/README.md`, `client/frontend/README.md`, `DEPLOYMENT.md`, issue/roadmap comments, per the settled checklist. |\n\n`dist/` is regenerated by the build.\n\n---\n\n### Engine: `engine/server/api/handlers/video.py`\n\n**Module docstring**\n\n```python\n\"\"\"Video metadata endpoint handlers.\n\nResponsibilities:\n- Resolve video row by id/uuid/host.\n- /api/video: answer from the DB row only, with no instance call and no write.\n- /api/video/refresh: fetch live instance metadata, merge it over the row field by field, persist it when the instance answered, and answer the same shape.\n\"\"\"\n```\n\n**New imports**, in the file's existing style:\n\n```python\nfrom data.db import statement_deadline\nfrom server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS\n```\n\n**`fetch_instance_video_dynamic`: success signal.** Only line 164 changes; the rest of the function is untouched.\n\n```python\n    detail = fetch_instance_json(host, f\"/api/v1/videos/{quote(video_id)}\")\n    # An empty dict tells the caller the instance did not answer, so nothing is persisted.\n    if not isinstance(detail, dict) or not detail:\n        return {}\n```\n\n- Invariant: it returns `{}` if and only if the detail call failed or came back as a non-dict or empty JSON value. Otherwise it returns today's 14-key dict.\n- A non-dict JSON body no longer reaches `detail.get` and raises `AttributeError`.\n- The channel sub-call now runs only on success. When it fails, the channel fields fall back to the DB in the merge, and the result still counts as success.\n\n**`resolve_video_row`**, which takes lines 210-224 and 226:\n\n```python\ndef resolve_video_row(\n    handler: Any,\n    server: Any,\n    params: dict[str, list[str]],\n) -> tuple[dict[str, Any], str, str] | None:\n    \"\"\"Resolve the requested row, or answer 400/404 and return None.\n\n    Returns the row, the requested id and the instance domain the merge and refresh use.\n    \"\"\"\n    id_param = params.get(\"id\", params.get(\"video_id\", [None]))[0]\n    host_param = params.get(\"host\", params.get(\"instance_domain\", [None]))[0]\n    if not id_param:\n        respond_json(handler, 400, {\"error\": \"Missing video id\"})\n        return None\n    with server.db_lock:\n        row = fetch_video_row(\n            server.db,\n            id_param,\n            host_param,\n            error_threshold=server.video_error_threshold,\n        )\n    if not row:\n        respond_json(handler, 404, {\"error\": \"Video not found\"})\n        return None\n    instance_domain = row.get(\"instance_domain\") or host_param or \"\"\n    return row, id_param, instance_domain\n```\n\nThe lock covers the SELECT only.\n\n**`merge_video_metadata`**, which takes lines 229-290 verbatim:\n\n```python\ndef merge_video_metadata(\n    row: dict[str, Any],\n    dynamic: dict[str, Any],\n    instance_domain: str,\n) -> tuple[dict[str, Any], dict[str, Any]]:\n    \"\"\"Merge live `dynamic` fields over the DB row, field by field.\n\n    Returns the response payload and the merged column values the persist step writes.\n    An empty `dynamic` gives the DB-only answer.\n    \"\"\"\n    # lines 229-290 unchanged: title \u2026 nsfw, channel_url, embed_url, original_url, response\n    merged = {\n        \"title\": title,\n        \"description\": description,\n        \"channel_display\": channel_display,\n        \"channel_slug\": channel_slug,\n        \"channel_followers\": channel_followers,\n        \"views\": views,\n        \"likes\": likes,\n        \"dislikes\": dislikes,\n        \"tags_json\": tags_json,\n        \"category\": category,\n        \"nsfw\": nsfw,\n    }\n    return response, merged\n```\n\n- **The impact inventory's open point.** `merged` carries the raw intermediates, `None` included, so persist writes `NULL` where today's code writes `NULL` and never the response's `\"\"`.\n- The function is pure: no DB access and no I/O.\n- With `dynamic={}`, every `dynamic.get` is `None`, so each field falls back to the row exactly as today, and `accountAvatarUrl` is `\"\"`.\n\n**`persist_video_metadata`**, which takes lines 294-358:\n\n```python\ndef persist_video_metadata(\n    server: Any,\n    row: dict[str, Any],\n    instance_domain: str,\n    merged: dict[str, Any],\n) -> None:\n    \"\"\"Write a successful refresh to the videos, channels and instances tables.\n\n    The writes run under a fresh statement budget taken once the DB lock is held, because the request's own budget is mostly spent on the instance calls by then.\n    \"\"\"\n    checked_at = now_ms()\n    popularity = compute_popularity(\n        merged[\"views\"],\n        merged[\"likes\"],\n        row.get(\"published_at\"),\n        float(getattr(server, \"popularity_like_weight\", 2.0)),\n        now_ms_value=checked_at,\n    )\n    channel_id = row.get(\"channel_id\")\n    try:\n        with server.db_lock:\n            with statement_deadline(\n                float(getattr(server, \"statement_timeout_seconds\", DEFAULT_STATEMENT_TIMEOUT_SECONDS))\n            ):\n                with server.db:\n                    # today's three UPDATEs, parameters read from `merged` and `row`, unchanged SQL\n    except sqlite3.OperationalError as exc:\n        logging.warning(\n            \"[video] failed to persist dynamic metadata for video_id=%s host=%s: %s\",\n            row.get(\"video_id\"),\n            instance_domain,\n            exc,\n        )\n```\n\n- **Why the nested deadline.** The settled db.py entry picks this mitigation. Without it the outer deadline has usually expired after roughly 16 s of instance calls, and the FTS trigger's UPDATE could be interrupted, which silently breaks R2's persist.\n- **Why it sits inside `db_lock`.** Time spent waiting for the lock does not use up the new budget.\n- **Nesting is safe.** `statement_deadline` restores the outer deadline on exit (db.py:59-64).\n- **The rest is today's code.** The SQL, the parameter order, the `channels` UPDATE only when `channel_id` is set, the `instances` reset, and the catch-and-log.\n\n**Route handlers**\n\n```python\ndef handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:\n    \"\"\"Handle /api/video: answer from the DB row only, with no instance call and no write.\"\"\"\n    resolved = resolve_video_row(handler, server, params)\n    if resolved is None:\n        return True\n    row, _id_param, instance_domain = resolved\n    response, _merged = merge_video_metadata(row, {}, instance_domain)\n    respond_json(handler, 200, response)\n    return True\n\n\ndef handle_video_refresh_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:\n    \"\"\"Handle /api/video/refresh: fetch live metadata, persist it when the instance answered, answer the merge.\n\n    This is the single per-request metadata write path; issue 10 extends it.\n    \"\"\"\n    resolved = resolve_video_row(handler, server, params)\n    if resolved is None:\n        return True\n    row, id_param, instance_domain = resolved\n    # The instance calls run outside the DB lock, so a slow instance never stalls other routes.\n    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else {}\n    response, merged = merge_video_metadata(row, dynamic, instance_domain)\n    if dynamic and instance_domain and row.get(\"video_id\"):\n        persist_video_metadata(server, row, instance_domain, merged)\n    respond_json(handler, 200, response)\n    return True\n```\n\n- Keeping the name `handle_video_request` means the import at similar.py:84 cannot break.\n- The `if dynamic` guard is now meaningful, because a failed fetch returns `{}`.\n\n### Engine: `engine/server/api/handlers/similar.py`\n\n- **Line 84:** `from handlers.video import handle_video_refresh_request, handle_video_request`.\n- **After line 497:**\n  ```python\n          if url.path == \"/api/video/refresh\":\n              handle_video_refresh_request(self, self.server, params)\n              return\n  ```\n- **Docstring lines 9-10:**\n  - `- /api/video: single video metadata from the local DB (no instance call).`\n  - `- /api/video/refresh: live instance refresh of one video's metadata, persisted on success.`\n- **Unchanged:** the rate limit at 447 (its own `ip:/api/video/refresh` bucket), the statement deadline in `do_GET`, and the similars dispatch.\n\n### Engine: `engine/server/api/handlers/__init__.py`\n\nLine 5 becomes: `- video: /api/video (DB only) and /api/video/refresh (live instance refresh, persisted on success).`\n\n---\n\n### Client backend: `client/backend/server.py`\n\n**Constants**, next to lines 77-101:\n\n```python\nENGINE_PROXY_TIMEOUT_SECONDS = 10\n# The refresh waits on up to two 8 s instance calls in the Engine, and a retry would repeat them and the write.\nENGINE_PROXY_ROUTE_TIMEOUT_SECONDS: dict[str, float] = {\"/api/video/refresh\": 20}\nENGINE_PROXY_MAX_BODY_BYTES = 1_000_000\nENGINE_PROXY_RETRY_COUNT = 1\nENGINE_PROXY_ROUTE_RETRY_COUNT: dict[str, int] = {\"/api/video/refresh\": 0}\nENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25\nPROXY_READ_GET_ROUTES = frozenset(\n    (\"/api/video\", \"/api/video/refresh\", \"/api/channels\", \"/api/v1/search/videos\")\n)\nPROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {\n    ...\n    \"/api/video\": {\"id\", \"host\", \"refresh_cache\", \"user_id\"},\n    \"/api/video/refresh\": {\"id\", \"host\"},\n    ...\n}\n```\n\nThe plan asked for \"a path check on the retry count\". A second one-entry dict does the same job, with the same shape as the timeout mapping and one more place a test can monkeypatch.\n\n**`_proxy_engine_request`.** Two locals are resolved once, from `path` (never from `upstream`, which carries the query string), right after `upstream` is built. The mappings are module globals read at call time, so a test that patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` takes effect.\n\n```python\n        timeout_seconds = ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS.get(path, ENGINE_PROXY_TIMEOUT_SECONDS)\n        retry_count = ENGINE_PROXY_ROUTE_RETRY_COUNT.get(path, ENGINE_PROXY_RETRY_COUNT)\n```\n\nFour sites change:\n\n| Line | Before | After |\n|---|---|---|\n| 604 | `range(ENGINE_PROXY_RETRY_COUNT + 1)` | `range(retry_count + 1)` |\n| 606 | `timeout=ENGINE_PROXY_TIMEOUT_SECONDS` | `timeout=timeout_seconds` |\n| 696 | `attempt < ENGINE_PROXY_RETRY_COUNT` | `attempt < retry_count` |\n| 731 | `\"attempts\": ENGINE_PROXY_RETRY_COUNT + 1` | `\"attempts\": retry_count + 1` |\n\n- Every other route keeps 10 s and one retry.\n- `_handle_engine_read_proxy_get` and `_profile_filter` are unchanged. The refresh gets the same sanitising: an unknown or repeated key answers 400, and a `user_id` or `refresh_cache` on it now answers 400 too.\n\n**How a failed refresh reaches the browser:**\n- a timeout breaks the loop with 0 retries \u2192 502 `ENGINE_PROXY_UNAVAILABLE`;\n- a dropped Engine connection \u2192 502 `ENGINE_PROXY_FAILURE`;\n- an Engine 400 or 404 \u2192 passed through.\n\nThe page treats all of these as a failed refresh.\n\n---\n\n### Frontend: `client/frontend/src/pages/video-page/index.ts`\n\n**Module state.** These lines go next to `currentMetadata` (line 50-51). They must be declared before the coordinator call at line 79: the no-source path renders synchronously, and a `let` declared later would throw a TDZ error.\n\n```ts\ntype InstanceMetadata = Awaited<ReturnType<typeof fetchInstanceMetadata>>;\n// Which metadata source the panel shows; a source renders only if it ranks at least as high.\nconst METADATA_RANK = { params: 0, fast: 1, instance: 2, refresh: 3 } as const;\nlet shownRank = -1;\nlet instanceConfig: InstanceMetadata = null;\nlet instanceMetadata: Promise<InstanceMetadata> = Promise.resolve(null);\nlet lastEmbed = \"\";\nlet reactionKey = \"\";\n```\n\n**Start (line 79).** `void loadVideo();` becomes `startVideoLoad();`. Line 80, `void loadSimilarVideos();`, is unchanged, and the coordinator neither awaits nor chains it.\n\n**Coordinator**\n\n```ts\n/**\n * Start the three metadata sources at once: the Engine's DB answer, its live refresh, and the instance config. None awaits another.\n */\nfunction startVideoLoad() {\n  const source = resolveVideoSource();\n  if (!source?.host || !source.id) {\n    offerMetadata(METADATA_RANK.params, null);\n    return;\n  }\n  instanceMetadata = fetchInstanceMetadata(source.host);\n  void instanceMetadata.then((meta) => {\n    instanceConfig = meta;\n    if (meta && shownRank >= 0) renderVideo(currentMetadata);\n  });\n  void loadFastMetadata(source);\n  void loadRefreshedMetadata(source);\n}\n\n/**\n * Render `metadata` unless a higher-ranked source is already shown, so a late fast answer never overwrites refreshed values.\n */\nfunction offerMetadata(rank: number, metadata: VideoMetadata | null) {\n  if (rank < shownRank) return;\n  shownRank = rank;\n  renderVideo(metadata);\n}\n\n/**\n * Show the Engine's stored metadata, or the URL params and then the instance's own answer when the Engine has no row.\n */\nasync function loadFastMetadata(source: { host: string; id: string; url: string }) {\n  const metadata = await fetchVideoMetadataFromServer(\"/api/video\", source);\n  if (metadata) {\n    offerMetadata(METADATA_RANK.fast, metadata);\n    return;\n  }\n  offerMetadata(METADATA_RANK.params, null);\n  if (shownRank > METADATA_RANK.instance) return;\n  const instanceMeta = await fetchVideoMetadataFromInstance(source);\n  if (instanceMeta) offerMetadata(METADATA_RANK.instance, instanceMeta);\n}\n\n/**\n * Show live metadata once the Engine has refreshed it; a failure keeps what the panel shows.\n */\nasync function loadRefreshedMetadata(source: { host: string; id: string; url: string }) {\n  const metadata = await fetchVideoMetadataFromServer(\"/api/video/refresh\", source);\n  if (!metadata) {\n    console.warn(\"[video] metadata refresh failed; keeping the values shown\");\n    return;\n  }\n  offerMetadata(METADATA_RANK.refresh, metadata);\n}\n```\n\n- **No-source path.** It renders once with `null`, with no fetch and no config, exactly as today.\n- **Equal ranks re-render.** Equal-rank renders are allowed, which is what lets the config's re-render at the current rank through.\n- **`currentMetadata` stays in step.** It is set only inside `renderVideo`, so it always equals what is shown, and the config re-render reuses it.\n- **Skipped fallback.** If the refresh is already shown, the direct-instance fallback is not started at all.\n\n**`renderVideo(metadata: VideoMetadata | null)`.** This is today's `loadVideo` body without `await fetchVideoMetadata()`, and it is synchronous. Line 87 stays as the first statement: `currentMetadata = metadata;`. Three edits:\n\n1. **Instance avatar** (line 109) is taken from the shared config at render time, so it survives every re-render and also reaches rank 0:\n   `const instanceAvatarUrl = metadata?.instanceAvatarUrl || instanceConfig?.avatarUrl || \"\";`\n2. **Embed** (lines 212-221). The comparison is against our own last assigned string, and the guard is cleared when `src` is removed:\n   ```ts\n   if (embedEl) {\n     // The embed URL can come straight from the `?embed=` query parameter when metadata resolution fails, so a scheme check is what stops a `javascript:` URL from executing in this origin via iframe navigation.\n     const checkedEmbed = embed && /^https:\\/\\//i.test(embed.trim()) ? embed : \"\";\n     if (!checkedEmbed) {\n       embedEl.removeAttribute(\"src\");\n       lastEmbed = \"\";\n     } else if (checkedEmbed !== lastEmbed) {\n       // Reassigning an unchanged src would restart playback on every re-render.\n       embedEl.src = checkedEmbed;\n       lastEmbed = checkedEmbed;\n     }\n   }\n   ```\n3. **Everything else is unchanged:** `escapeHtml`/`safeExternalUrl` on every write, the `enableBlockButtons(...)` call (its `dataset.wired` guard makes re-renders no-ops), and `void loadReaction()`.\n\n**`loadReaction` gate.** The key is written only for a non-null video, and before the first `await`:\n\n```ts\nasync function loadReaction() {\n  const video = reactionVideo();\n  if (!video || !likeButton || !dislikeButton) return;\n  // Re-renders call this again; the visitor's reaction is read once per video.\n  const key = `${video.uuid}|${video.host}`;\n  if (key === reactionKey) return;\n  reactionKey = key;\n  try {\n    await localLikesImported;\n    ...unchanged\n```\n\nA rank-0 render with a non-UUID `seedId` returns `null` and leaves the gate open, so a later rank that carries `videoUuid` still fetches and wires the buttons.\n\n**`fetchVideoMetadataFromServer(path, source)`**\n\n- Signature: `async function fetchVideoMetadataFromServer(path: string, source: { host: string; id: string; url: string }): Promise<VideoMetadata | null>`.\n- `new URL(path, apiBase)`, with only `id` and `host` set, as today. The refresh allow-list accepts exactly these.\n- `await fetchInstanceMetadata(source.host)` (line 525) is removed.\n- The instance fields become:\n  ```ts\n  instanceName: (data.instanceName as string | undefined) ?? source.host,\n  instanceUrl: (data.instanceUrl as string | undefined) ?? `https://${source.host}`,\n  instanceAvatarUrl: \"\",\n  ```\n  The Engine always sends both as strings (video.py:279-280), so `instanceMeta?.name`/`url` could never win here today. Dropping them keeps what is visible, and the avatar now comes from `instanceConfig` in `renderVideo`.\n- `catch { return null; }` is unchanged. `null` is the failure signal both callers use.\n\n**`fetchVideoMetadataFromInstance`.** Line 600 becomes `const instanceMeta = await instanceMetadata;`, which awaits the shared promise instead of issuing a second `/api/v1/config` request. The effect on R4:\n- This source ranks 2 and runs only after rank 0 has rendered, so the wait is never on the first-render path.\n- It keeps today's rank-2 precedence exactly, with the config's name and URL winning.\n\n**Removed:** `loadVideo` and `fetchVideoMetadata`, whose sequencing moved into the coordinator. `loadSimilarVideos` and the similars helpers are untouched (R7).\n\n---\n\n### What the build needs to test\n\n**Engine: new `tests/active/test_video_metadata.py`.** Each case runs in an `ENGINE_PY` child over a temporary DB, following `test_internal_events.py:52` / `test_similar.py`. The child uses a real `SimilarServer` with `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`. The patch goes on `handlers.video.fetch_instance_json`, never the shared `engine` fixture.\n- **Fast route.**\n  - `/api/video` answers the DB fields with the shape unchanged, `accountAvatarUrl == \"\"`, the channel URL built from slug + host, and the original URL built from uuid + host.\n  - The stub is never called.\n  - `last_checked_at` and `instances.last_error` are unchanged.\n- **Errors on both routes.** 400 `Missing video id` and 404 `Video not found`.\n- **Successful refresh.** It answers the instance values, including `accountAvatarUrl`. The `videos`, `channels` and `instances` rows are updated, with `last_error*` set to NULL. A failed channel sub-call still persists, with the DB channel fields.\n- **Failed refresh.** Detail `None`, `{}`, a JSON list and a raised `URLError` each answer 200 with DB values and change no row.\n- **Deadline.** With `statement_timeout_seconds` around 0.2 and a stub that sleeps 0.5 s, a successful refresh still persists.\n- **R7.**\n  - Setup: a stub that blocks about 5 s, and a refresh started on a thread.\n  - The id-based similars GET is answered in well under 5 s.\n  - The stub's call log holds only the refresh's paths.\n\n**Client proxy: added to `tests/active/test_server.py`,** using `EngineStub`, `_serving`, `_client_backend` and `_status`:\n- `/api/video/refresh` forwards `id`/`host` and answers 400 on `user_id`, `refresh_cache` or a repeated key;\n- with both mappings patched to a small timeout, a sleeping stub sees exactly one refresh GET and the browser gets 502;\n- `/api/video` against a sleeping stub still makes two attempts;\n- `/api/video` keeps the 10 s default (assert the mapping lookup).\n\n**Frontend: new `tests/active/test_frontend_video_page.py`.** The page is bundled with esbuild (`--platform=node`, css loader `empty`) and driven with a stubbed `document`/`window`/`localStorage` and a scripted `fetch`, following `test_frontend_blocks.py`. It asserts:\n- the first render happens before `/api/v1/config` resolves;\n- whichever of refresh and fast arrives first, the refreshed values end up shown;\n- a failed refresh keeps the values shown and calls `console.warn`;\n- a fast 404 renders the URL params, then the instance data;\n- `src` is assigned once across the rank 1 \u2192 3 renders;\n- `fetchReaction` is called once;\n- a `javascript:` embed is never assigned;\n- similars are fetched with `limit=8` regardless of metadata timing.\n\nIf the stubbing proves too heavy, the plan's own escape hatch applies: extract `offerMetadata`'s rank rule into a lib module.\n\n**At harvest:** `.un/skills/devsecops/config.json` maps the new files to `video.py`, `similar.py`, `server.py` and `video-page/index.ts`.\n\n---\n\n### Check against the plan and requirements\n\nThis took two passes; the first found gaps and the second closed them.\n\n| Item | Met by |\n|---|---|\n| R1 | `merge_video_metadata(row, {}, \u2026)`, no fetch, no write. 400/404 through the shared resolver. |\n| R2 | Separate route and handler. Same resolver. `fetch_instance_video_dynamic` unchanged except the success signal. Persist only when `dynamic` is non-empty, with today's SQL and catch. Same response shape. The proxy's own allow-list `{id, host}`. |\n| R3 | Three independent starts. The rank rule keeps refreshed values over a late fast answer. A failed refresh is `console.warn` only. |\n| R4 | No first-render path awaits `/api/v1/config`. The avatar fills in through the shared promise's re-render. The chip uses host initials until then. |\n| R5 | Fast failure renders rank 0 at once, then rank 2. The `https://` check sits inside `renderVideo`, which every path passes through. |\n| R6 | `lastEmbed` guard. `dataset.wired` guards unchanged. `reactionKey` gate written before the first await. Escaping unchanged. |\n| R7 | Similars code untouched. The instance calls run outside `db_lock`. Covered by the Engine R7 test. |\n| Budget constraint | 20 s, no retry, refresh only. A proxy failure degrades per R3. |\n| Stdlib / style / dist | Stdlib only. No new dependency. Module-level functions in the files' style. `dist` rebuilt. |\n\n**What pass 1 missed, and pass 2 fixed:**\n- **Persist intermediates.** Solved by returning a `merged` dict instead of feeding persist from the response.\n- **Persist under an expired deadline.** Nested `statement_deadline` inside `db_lock`.\n- **TDZ.** The coordinator's state is declared before line 79.\n- **Reaction gate.** Written before the `await` and only for a non-null video.\n- **Line 731 log.** Now uses `retry_count`.\n\n### Named simplifications and residual limits\n\n- **Rank rule is one number.** It has no per-field merge: a higher-ranked source replaces the whole panel. That is enough because the refresh answers a superset of the fast answer. The ceiling: a future partial refresh would need per-field precedence.\n- **Refresh failure is a bare `null`.** The console warning carries no reason; the status can be logged later if diagnosis needs it.\n- **Engine's late write after a Client timeout.** `respond_json` writes to a closed socket and prints a `BrokenPipeError` traceback. This is pre-existing log noise and is left as is; the persist has already run.\n- **Different uuid on a later render.** The reaction and block listeners keep the first video they captured. If a later rank reported a different uuid, which should not happen for one row, the reaction is re-read for the new key but clicks still act on the first video. This is unchanged from today.\n- **Deviations from the settled plan text, both taken from the settled impacts.**\n  - Persist gains a nested statement deadline; the plan said \"unchanged\".\n  - The rank-2 fallback awaits the shared config promise rather than not awaiting it at all. This keeps today's rank-2 name/URL precedence and stays off the first-render path.\n",
  "coordination": "none",
  "tests": {
    "tests/tmp/test_11_fast_similars_response_phase1.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase1.py:140 \u2014 refresh over ANSWERING answers (200, LIVE): all eighteen /api/video keys with the instance's values; :142 \u2014 calls are [detail by uuid, channel by live_slug]; :144 \u2014 refresh requested by video_id \"v1\" over BY_VIDEO_ID answers (200, LIVE)",
          "expected": "(200, LIVE), with title \"Live title\", views 1000, likes 50, dislikes 3, channelName \"Live Chan\", subscribersCount 77 (only from the channel call), accountAvatarUrl `.../avatars/live.png`, and videoUuid/embedUrl/originalUrl on uuid-v1 even when requested by \"v1\". Calls: [[\"tube.example\", \"/api/v1/videos/uuid-v1\"], [\"tube.example\", \"/api/v1/video-channels/live_slug\"]].",
          "wrong_implementation": "Unrouted refresh: 404 {\"error\": \"Not found\"}. Row-only answer: \"DB title\", views 10, accountAvatarUrl \"\". Skipping the channel call: subscribersCount 70. Building uuid, embed or original URL from the query id: \"v1\", `.../embed/v1`, `.../watch/v1`, which fails :144."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase1.py:153 \u2014 PARTIAL: (description, views, channelName, subscribersCount) == (\"DB description\", 10, \"DB Chan\", 5); :155 \u2014 (title, likes, dislikes) == (\"Live title B\", 0, 3); :160 \u2014 OMITTING: (title, likes, dislikes) == (\"DB title\", 2, 1); :156 and :161 pin the full eighteen-key bodies",
          "expected": "Every one of the seven instance-sourced fields with a row counterpart falls back to the row when omitted. PARTIAL gives \"DB description\", 10, \"DB Chan\", 5. OMITTING gives \"DB title\", 2, 1. A supplied likes 0 is kept as 0.",
          "wrong_implementation": "An instance-only merge reads (\"\", None, \"\", None) at :153 and (\"\", None, None) at :160. A truthiness fallback reads likes 2 at :155."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "`/api/video/refresh` answers the instance's live values in today's `/api/video` response shape."
        },
        {
          "id": "C2",
          "text": "A field the instance did not supply in a refresh falls back to the DB row's value."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_11_fast_similars_response_phase1.py",
        "code": 1,
        "output": "  tests/tmp/test_11_fast_similars_response_phase1.py  3 failed, 1 passed                     0.0s\n  --------------------------------------------------\n  total                                               3 failed, 1 passed                     4.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_11_fast_similars_response_phase2.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase2.py:237, :238, :241, :242, :244 (_assert_written, called from :251, :259 and :270): last_checked_at falls inside the run's window, popularity > 0, v1 carries the live video columns with v2 untouched, channels.c1 carries the written slug, display name and followers, and the instance errors are NULL. :283 and :285 (parametrized over None, {}, a JSON list and URLError): the refresh answers (200, DB_ONLY) and the rows before equal the rows after. Controls: :250, :257, :268, :281, plus :264 and :265 for the expired-deadline fixture.",
          "expected": "Answered detail: the videos, channels and instances rows are written, including after the request's 0.2 s deadline has expired. Unanswered detail: 200 with DB_ONLY and no row changed.",
          "wrong_implementation": "Pre-phase code does two things wrong. It persists on any truthy dynamic dict, so for None, {} and URLError last_checked_at moves off 1, popularity is recomputed and last_error 'boom' is cleared, and :285 goes red; the list case drops the connection with status None, so :283 goes red. It also persists under the request's expired deadline, so the heavy-trigger UPDATE is interrupted and last_checked_at stays 1, and :237 goes red (observed just now). A refresh that skips the write altogether reddens :237 in the success and channel-failed tests."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase2.py:294, :296, :298, :300, :301, with the controls at :291 and :292: the similars GET, sent while the refresh sits in a 5 s instance call, answers 200 with seed v1 and rows [v2] in under 1.0 s, and the only instance call is the refresh's detail call.",
          "expected": "status 200, (\"v1\", [\"v2\"]), elapsed about 2 ms, calls [[tube.example, /api/v1/videos/uuid-v1]]",
          "wrong_implementation": "If the instance call is made inside db_lock, the similars GET waits the refresh out. It was observed at 4.0 s against a locked 2 s \u00d7 2 stub, so :298 goes red. A canned or empty similars answer fails :296."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "A refresh updates the videos, channels and instances rows only when the instance's video detail call answered."
        },
        {
          "id": "C2",
          "text": "A refresh blocked on a slow instance does not delay the similars route's answer."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_11_fast_similars_response_phase2.py",
        "code": 1,
        "output": "  tests/tmp/test_11_fast_similars_response_phase2.py  5 failed, 3 passed                     0.0s\n  --------------------------------------------------\n  total                                               5 failed, 3 passed                    11.5s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    },
    "tests/tmp/test_11_fast_similars_response_phase3.py": {
      "rows": [
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase3.py:67 \u2014 GET /api/video/refresh with `user_id` added, `refresh_cache` added, `foo` added, `id` repeated, and `host` repeated each answers 400",
          "expected": "[400, 400, 400, 400, 400]",
          "wrong_implementation": "A route that reuses the `/api/video` allow-list reads 200 on the first two. A route that checks only `id` for repeats and takes the first or last `host` reads 200 on the fifth. A route left unrouted reads [404, 404, 404, 404, 404], which I observed on the pre-phase code."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase3.py:68 \u2014 GET /api/video/refresh?id=uuid-1&host=tube.example answers 200 with the stub Engine's body unchanged",
          "expected": "(200, {\"videoUuid\": \"uuid-1\", \"title\": \"Refreshed\"})",
          "wrong_implementation": "A route that refuses everything, or that passes through only the status and rewrites or filters the body, gives a 400/404 or a different body."
        },
        {
          "clause": "C1",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase3.py:70 \u2014 the stub recorded exactly one request: `/api/video/refresh` with query exactly {id: [uuid-1], host: [tube.example]}. The five refused requests were sent first",
          "expected": "[(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]",
          "wrong_implementation": "A route that forwards to `/api/video` gets the wrong path. One that adds `user_id` or drops `host` gets the wrong dict. One that forwards a refused request (for example the one with `host` repeated) puts an extra entry at the front."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase3.py:84 \u2014 with the refresh's route timeout patched to 0.3 s and a 1.5 s Engine, the refresh answers 502",
          "expected": "502",
          "wrong_implementation": "A route that ignores the per-route timeout and uses the shared 10 s default lets the 1.5 s answer through as 200. An unrouted refresh reads 404 (observed)."
        },
        {
          "clause": "C2",
          "assertion": "tests/tmp/test_11_fast_similars_response_phase3.py:85 \u2014 the Engine received that timed-out refresh exactly once",
          "expected": "[(\"/api/video/refresh\", {\"id\": [\"uuid-1\"], \"host\": [\"tube.example\"]})]",
          "wrong_implementation": "A refresh that gets the shared ENGINE_PROXY_RETRY_COUNT=1 is sent twice, so the snapshot holds two entries. The :87 guard (/api/video still 502 after two attempts) shows that the single send is not retries being dropped for every route."
        }
      ],
      "clauses": [
        {
          "id": "C1",
          "text": "The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400."
        },
        {
          "id": "C2",
          "text": "A refresh that times out at the proxy is sent to the Engine once and answered 502."
        }
      ],
      "surface": "checkpoint",
      "results": {
        "command": "validate_tests.py tests/tmp/test_11_fast_similars_response_phase3.py",
        "code": 1,
        "output": "  tests/tmp/test_11_fast_similars_response_phase3.py  2 failed                               0.0s\n  --------------------------------------------------\n  total                                               2 failed                               2.3s wall, 1 lane\n\nrecorded: tests/last_test_validation.json (exit 1)\nwrote tests/last_test_output.txt"
      }
    }
  },
  "audits": {
    "tests/tmp/test_11_fast_similars_response_phase1.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 136 on\n`assert (report[\"status\"], report[\"body\"]) == (200, LIVE)`. It reads (404, {\"error\": \"Not found\"})\nbecause `SimilarHandler._dispatch_get` (similar.py:495-508) has no `/api/video/refresh` route.\ntest_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 143 on the\nsame 404. test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance\nfails at line 155, reading (404, {\"error\": \"Not found\"}, []) against (400, {\"error\": \"Missing video id\"}, []).\ntest_api_video_still_answers_the_instances_values passes as the control, because\n`handle_video_request` already merges live values over the row.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve.\n   It was not read, and nothing in test_path imports it.\n2. `fixtures_path` was not supplied. tests/active/conftest.py was found by Glob, and only the\n   `ROOT` and `ENGINE_PY` definitions the test imports (conftest.py:31-32) were checked.\n3. engine/server/db/jobs/sync-whitelist.py was checked only to confirm that `ensure_whitelist_schema`\n   (line 253) and `ensure_content_schema` (line 323) exist. The column set the seed INSERTs rely on\n   was not read.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (22 clauses: 7 must_prove, 11 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :136 | every live value in DETAIL/CHANNEL differs from the row, so a row-only answer (\"DB title\", views 10, empty accountAvatarUrl) or an unrouted 404 fails | CARRIED |\n| C1b | must_prove | in today's `/api/video` response shape | :136, :163 | whole-dict equality against LIVE, and :163 anchors LIVE as what `/api/video` answers for the same stub; a missing, extra or renamed key fails | CARRIED |\n| C1c | must_prove | the live values come from the instance's detail and channel calls | :138 | a refresh that skips the channel call (subscribersCount 70, not 77) or calls in another order or path | CARRIED |\n| C2a | must_prove | omitted `description` falls back to the row | :147 | taking only the instance's field (\"\" in the answer) | CARRIED |\n| C2b | must_prove | omitted `views` falls back to the row | :147 | taking only the instance's field (None) | CARRIED |\n| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :147 | \"\" / None from an instance-only merge | CARRIED |\n| C2d | must_prove | a supplied falsy value is not treated as omitted | :149 | a truthiness fallback that answers the row's likes 2 | CARRIED |\n| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | none | nothing: PARTIAL supplies all three (`\"name\"`, `\"likes\": 0`, `\"dislikes\": 3`), so their fallback never runs | UNCARRIED |\n| D1 | docstring | \"answers 200 with exactly `/api/video`'s eighteen keys\" | :136 | an added or dropped key | CARRIED |\n| D2 | docstring | \"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\" | :136 | row values (all distinct), or the detail's followers 70 used instead of the channel call's 77 | CARRIED |\n| D3 | docstring | \"the channel URL built from the instance's channel slug and the host\" | :136 | building it from the row's `db_slug` | CARRIED |\n| D4 | docstring | \"the original URL from the row's uuid and the host\" | :136 | nothing on the source: the requested id equals the row's uuid (`uuid-v1`), so building it from the query id passes too | UNCARRIED |\n| D5a | docstring | account name and URL \"from the row\" | :136 | taking the instance's \"Live Account\" or `/accounts/live` | CARRIED |\n| D5b | docstring | channel avatar and published date \"from the row\" | :136 | an instance-only merge (the only source of these values is the row, so it answers \"\" / None) | CARRIED |\n| D5c | docstring | uuid and embed \"from the row\" | :136 | nothing on the source: the row's `embed_path` and uuid match what the requested id and host would build | UNCARRIED |\n| D6 | docstring | \"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\" | :138 | a wrong path, a wrong host, a reversed order, or an extra call | CARRIED |\n| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :147, :150 | an instance-only merge | CARRIED |\n| D8 | docstring | \"beside the instance's title, dislikes and `likes` 0\" | :149 | row title, row dislikes 1, truthiness likes 2 | CARRIED |\n| D9 | docstring | no id \u2192 400 `Missing video id`, no instance call | :155 | another status or body, or a call made before validation | CARRIED |\n| D10 | docstring | id not in DB \u2192 404 `Video not found`, no instance call | :157 | an unrouted 404 `Not found`, or a call made before the lookup | CARRIED |\n| D11 | docstring | \"`/api/video` against the same answering instance still answers the instance's values\" | :163, :164 | a DB-only `/api/video` (\"DB title\", no calls) | CARRIED |\n| N1 | name | \"refresh answers the instance's values in the api video shape\" | :136 | as C1a/C1b | CARRIED |\n| N2 | name | \"refresh answers the row's value for each field the instance omitted\" | :147, :150 | every field PARTIAL omits is asserted, so an instance-only merge fails | CARRIED |\n| N3 | name | \"refresh without an id or for an unknown video is refused without calling the instance\" | :155, :157 | as D9/D10 | CARRIED |\n| N4 | name | \"api video still answers the instance's values\" | :163 | as D11 | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:149\n   assert (body[\"title\"], body[\"likes\"], body[\"dislikes\"]) == (\"Live title B\", 0, 3)  # C2\n   C2 says any field the instance did not supply falls back to the row. The response takes seven fields from the instance that have row counterparts: title, description, views, likes, dislikes, channelName and subscribersCount. PARTIAL (:38) omits only four of them. The instance still supplies `name`, `likes` and `dislikes`, so :149 checks that supplied values win. It never checks the fallback for those three fields. A refresh that answers `title: \"\"` or `likes: None` / `dislikes: None` when the instance omits them passes every assertion in the file. The principle says \"a claim naming a set of fields asserts every member of the set\". Here the test asserts four members of seven (C2e).\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:136\n   D4 and D5c are UNCARRIED. The docstring (:3) says originalUrl, videoUuid and embedUrl come \"from the row's uuid\" / \"from the row\". But the requested id is `UUID`, the same value as the row's `video_uuid`, and the row's `embed_path` is exactly what the uuid and host would build. So a refresh that builds these from the query id passes. To separate the sources, request the row by `video_id` (`v1`), or give it an embed_path that differs from the built one. The other option is to narrow the docstring sentence.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:141\n   The only instance failure tested is a missing channel call. No case covers the detail call answering nothing (the stub returns `None` for DETAIL_PATH). That is the expected failure mode of a refresh against an unreachable instance.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:153\n   The refusal cases cover a missing id and an unknown id. These are untested: an id that exists under a different `host`, a refresh with no `host`, and a row whose `error_count` has reached `video_error_threshold`. The handler's lookup filters on all three (`fetch_video_row`), and the server is built with a threshold of 3 (:73).\n4. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:1\n   No rule covers docstrings directly. The opening sentence \"and a field the instance omitted from the row's value\" is missing its verb (presumably \"answers\"), so it does not read as the claim it summarises.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), which does not exist in the worktree, so it was not read.\n2. `fixtures_path` was not supplied. The test imports `ENGINE_PY` and `ROOT` from tests/active/conftest.py. Their definitions were checked (:31-32). The rest of that conftest was not read.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 136 on\n`assert (report[\"status\"], report[\"body\"]) == (200, LIVE)`. It reads (404, {\"error\": \"Not found\"})\nbecause `SimilarHandler._dispatch_get` (similar.py:495-508) has no `/api/video/refresh` route.\ntest_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 143 on the\nsame 404. test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance\nfails at line 155, reading (404, {\"error\": \"Not found\"}, []) against (400, {\"error\": \"Missing video id\"}, []).\ntest_api_video_still_answers_the_instances_values passes as the control, because\n`handle_video_request` already merges live values over the row.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve.\n   It was not read, and nothing in test_path imports it.\n2. `fixtures_path` was not supplied. tests/active/conftest.py was found by Glob, and only the\n   `ROOT` and `ENGINE_PY` definitions the test imports (conftest.py:31-32) were checked.\n3. engine/server/db/jobs/sync-whitelist.py was checked only to confirm that `ensure_whitelist_schema`\n   (line 253) and `ensure_content_schema` (line 323) exist. The column set the seed INSERTs rely on\n   was not read.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (22 clauses: 7 must_prove, 11 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :136 | every live value in DETAIL/CHANNEL differs from the row, so a row-only answer (\"DB title\", views 10, empty accountAvatarUrl) or an unrouted 404 fails | CARRIED |\n| C1b | must_prove | in today's `/api/video` response shape | :136, :163 | whole-dict equality against LIVE, and :163 anchors LIVE as what `/api/video` answers for the same stub; a missing, extra or renamed key fails | CARRIED |\n| C1c | must_prove | the live values come from the instance's detail and channel calls | :138 | a refresh that skips the channel call (subscribersCount 70, not 77) or calls in another order or path | CARRIED |\n| C2a | must_prove | omitted `description` falls back to the row | :147 | taking only the instance's field (\"\" in the answer) | CARRIED |\n| C2b | must_prove | omitted `views` falls back to the row | :147 | taking only the instance's field (None) | CARRIED |\n| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :147 | \"\" / None from an instance-only merge | CARRIED |\n| C2d | must_prove | a supplied falsy value is not treated as omitted | :149 | a truthiness fallback that answers the row's likes 2 | CARRIED |\n| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | none | nothing: PARTIAL supplies all three (`\"name\"`, `\"likes\": 0`, `\"dislikes\": 3`), so their fallback never runs | UNCARRIED |\n| D1 | docstring | \"answers 200 with exactly `/api/video`'s eighteen keys\" | :136 | an added or dropped key | CARRIED |\n| D2 | docstring | \"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\" | :136 | row values (all distinct), or the detail's followers 70 used instead of the channel call's 77 | CARRIED |\n| D3 | docstring | \"the channel URL built from the instance's channel slug and the host\" | :136 | building it from the row's `db_slug` | CARRIED |\n| D4 | docstring | \"the original URL from the row's uuid and the host\" | :136 | nothing on the source: the requested id equals the row's uuid (`uuid-v1`), so building it from the query id passes too | UNCARRIED |\n| D5a | docstring | account name and URL \"from the row\" | :136 | taking the instance's \"Live Account\" or `/accounts/live` | CARRIED |\n| D5b | docstring | channel avatar and published date \"from the row\" | :136 | an instance-only merge (the only source of these values is the row, so it answers \"\" / None) | CARRIED |\n| D5c | docstring | uuid and embed \"from the row\" | :136 | nothing on the source: the row's `embed_path` and uuid match what the requested id and host would build | UNCARRIED |\n| D6 | docstring | \"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\" | :138 | a wrong path, a wrong host, a reversed order, or an extra call | CARRIED |\n| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :147, :150 | an instance-only merge | CARRIED |\n| D8 | docstring | \"beside the instance's title, dislikes and `likes` 0\" | :149 | row title, row dislikes 1, truthiness likes 2 | CARRIED |\n| D9 | docstring | no id \u2192 400 `Missing video id`, no instance call | :155 | another status or body, or a call made before validation | CARRIED |\n| D10 | docstring | id not in DB \u2192 404 `Video not found`, no instance call | :157 | an unrouted 404 `Not found`, or a call made before the lookup | CARRIED |\n| D11 | docstring | \"`/api/video` against the same answering instance still answers the instance's values\" | :163, :164 | a DB-only `/api/video` (\"DB title\", no calls) | CARRIED |\n| N1 | name | \"refresh answers the instance's values in the api video shape\" | :136 | as C1a/C1b | CARRIED |\n| N2 | name | \"refresh answers the row's value for each field the instance omitted\" | :147, :150 | every field PARTIAL omits is asserted, so an instance-only merge fails | CARRIED |\n| N3 | name | \"refresh without an id or for an unknown video is refused without calling the instance\" | :155, :157 | as D9/D10 | CARRIED |\n| N4 | name | \"api video still answers the instance's values\" | :163 | as D11 | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:149\n   assert (body[\"title\"], body[\"likes\"], body[\"dislikes\"]) == (\"Live title B\", 0, 3)  # C2\n   C2 says any field the instance did not supply falls back to the row. The response takes seven fields from the instance that have row counterparts: title, description, views, likes, dislikes, channelName and subscribersCount. PARTIAL (:38) omits only four of them. The instance still supplies `name`, `likes` and `dislikes`, so :149 checks that supplied values win. It never checks the fallback for those three fields. A refresh that answers `title: \"\"` or `likes: None` / `dislikes: None` when the instance omits them passes every assertion in the file. The principle says \"a claim naming a set of fields asserts every member of the set\". Here the test asserts four members of seven (C2e).\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:136\n   D4 and D5c are UNCARRIED. The docstring (:3) says originalUrl, videoUuid and embedUrl come \"from the row's uuid\" / \"from the row\". But the requested id is `UUID`, the same value as the row's `video_uuid`, and the row's `embed_path` is exactly what the uuid and host would build. So a refresh that builds these from the query id passes. To separate the sources, request the row by `video_id` (`v1`), or give it an embed_path that differs from the built one. The other option is to narrow the docstring sentence.\n2. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:141\n   The only instance failure tested is a missing channel call. No case covers the detail call answering nothing (the stub returns `None` for DETAIL_PATH). That is the expected failure mode of a refresh against an unreachable instance.\n3. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:153\n   The refusal cases cover a missing id and an unknown id. These are untested: an id that exists under a different `host`, a refresh with no `host`, and a row whose `error_count` has reached `video_error_threshold`. The handler's lookup filters on all three (`fetch_video_row`), and the server is built with a threshold of 3 (:73).\n4. name-as-sentence (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase1.py:1\n   No rule covers docstrings directly. The opening sentence \"and a field the instance omitted from the row's value\" is missing its verb (presumably \"answers\"), so it does not read as the claim it summarises.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), which does not exist in the worktree, so it was not read.\n2. `fixtures_path` was not supplied. The test imports `ENGINE_PY` and `ROOT` from tests/active/conftest.py. Their definitions were checked (:31-32). The rest of that conftest was not read.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`/api/video/refresh` answers the instance's live values",
            "assertion": ":136",
            "excludes": "every live value in DETAIL/CHANNEL differs from the row, so a row-only answer (\"DB title\", views 10, empty accountAvatarUrl) or an unrouted 404 fails",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "in today's `/api/video` response shape",
            "assertion": ":136, :163",
            "excludes": "whole-dict equality against LIVE, and :163 anchors LIVE as what `/api/video` answers for the same stub; a missing, extra or renamed key fails",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "the live values come from the instance's detail and channel calls",
            "assertion": ":138",
            "excludes": "a refresh that skips the channel call (subscribersCount 70, not 77) or calls in another order or path",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "omitted `description` falls back to the row",
            "assertion": ":147",
            "excludes": "taking only the instance's field (\"\" in the answer)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "omitted `views` falls back to the row",
            "assertion": ":147",
            "excludes": "taking only the instance's field (None)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "channel display name and follower count fall back when neither the detail nor the channel call supplies them",
            "assertion": ":147",
            "excludes": "\"\" / None from an instance-only merge",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "a supplied falsy value is not treated as omitted",
            "assertion": ":149",
            "excludes": "a truthiness fallback that answers the row's likes 2",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "omitted `title`, `likes` or `dislikes` falls back to the row",
            "assertion": "none",
            "excludes": "nothing: PARTIAL supplies all three (`\"name\"`, `\"likes\": 0`, `\"dislikes\": 3`), so their fallback never runs",
            "status": "UNCARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers 200 with exactly `/api/video`'s eighteen keys\"",
            "assertion": ":136",
            "excludes": "an added or dropped key",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\"",
            "assertion": ":136",
            "excludes": "row values (all distinct), or the detail's followers 70 used instead of the channel call's 77",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"the channel URL built from the instance's channel slug and the host\"",
            "assertion": ":136",
            "excludes": "building it from the row's `db_slug`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the original URL from the row's uuid and the host\"",
            "assertion": ":136",
            "excludes": "nothing on the source: the requested id equals the row's uuid (`uuid-v1`), so building it from the query id passes too",
            "status": "UNCARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "account name and URL \"from the row\"",
            "assertion": ":136",
            "excludes": "taking the instance's \"Live Account\" or `/accounts/live`",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "channel avatar and published date \"from the row\"",
            "assertion": ":136",
            "excludes": "an instance-only merge (the only source of these values is the row, so it answers \"\" / None)",
            "status": "CARRIED"
          },
          {
            "id": "D5c",
            "source": "docstring",
            "clause": "uuid and embed \"from the row\"",
            "assertion": ":136",
            "excludes": "nothing on the source: the row's `embed_path` and uuid match what the requested id and host would build",
            "status": "UNCARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\"",
            "assertion": ":138",
            "excludes": "a wrong path, a wrong host, a reversed order, or an extra call",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "partial detail: row's description, views, channel display name and follower count",
            "assertion": ":147, :150",
            "excludes": "an instance-only merge",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"beside the instance's title, dislikes and `likes` 0\"",
            "assertion": ":149",
            "excludes": "row title, row dislikes 1, truthiness likes 2",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "no id \u2192 400 `Missing video id`, no instance call",
            "assertion": ":155",
            "excludes": "another status or body, or a call made before validation",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "id not in DB \u2192 404 `Video not found`, no instance call",
            "assertion": ":157",
            "excludes": "an unrouted 404 `Not found`, or a call made before the lookup",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"`/api/video` against the same answering instance still answers the instance's values\"",
            "assertion": ":163, :164",
            "excludes": "a DB-only `/api/video` (\"DB title\", no calls)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"refresh answers the instance's values in the api video shape\"",
            "assertion": ":136",
            "excludes": "as C1a/C1b",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"refresh answers the row's value for each field the instance omitted\"",
            "assertion": ":147, :150",
            "excludes": "every field PARTIAL omits is asserted, so an instance-only merge fails",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"refresh without an id or for an unknown video is refused without calling the instance\"",
            "assertion": ":155, :157",
            "excludes": "as D9/D10",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"api video still answers the instance's values\"",
            "assertion": ":163",
            "excludes": "as D11",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThree tests fail, all because `/api/video/refresh` has no route and gets `404 {\"error\": \"Not found\"}`.\ntest_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 140 on\n`assert (report[\"status\"], report[\"body\"]) == (200, LIVE)`, reading (404, {\"error\": \"Not found\"}).\ntest_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 149 on\n`assert report[\"status\"] == 200`, reading 404.\ntest_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance fails\nat line 166, reading (404, {\"error\": \"Not found\"}, []) where it expects (400, {\"error\": \"Missing video id\"}, []).\ntest_api_video_still_answers_the_instances_values passes against today's `handle_video_request`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve. It\n   was not read, and nothing in the test under audit imports it.\n2. `fixtures_path` was not supplied. I found tests/active/conftest.py and checked only the two\n   names the test imports from it: `ROOT` (line 31) and `ENGINE_PY` (line 32). The rest of that\n   file was not read.\n3. I confirmed that `SimilarServer.__init__` exists (engine/server/api/server.py:209), but did not\n   read its parameters. So the child's `dict.fromkeys(...)[3:]` construction (test line 76) was not\n   checked against its real signature. That does not change the shape findings.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 8 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :140 | Every live value in DETAIL/CHANNEL differs from the row's value. An answer built only from the row (\"DB title\", views 10, empty accountAvatarUrl) fails, and so does an unrouted 404 | CARRIED |\n| C1b | must_prove | in today's `/api/video` response shape | :140, :174 | :140 compares the whole dict to LIVE, and :174 pins LIVE as what `/api/video` answers for the same stub. A missing, extra or renamed key fails | CARRIED |\n| C1c | must_prove | the live values come from the instance's detail and channel calls | :142 | A refresh that skips the channel call (subscribersCount 70, not 77), or calls in another order or on another path | CARRIED |\n| C2a | must_prove | omitted `description` falls back to the row | :153 | Taking only the instance's field (\"\" in the answer) | CARRIED |\n| C2b | must_prove | omitted `views` falls back to the row | :153 | Taking only the instance's field (None) | CARRIED |\n| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :153 | The \"\" / None an instance-only merge would give | CARRIED |\n| C2d | must_prove | a supplied falsy value is not treated as omitted | :155 | A truthiness fallback that answers the row's likes 2 | CARRIED |\n| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | :160, :161 | OMITTING leaves out all three. An instance-only merge answers \"\", None, None, not the row's \"DB title\", 2, 1 | CARRIED |\n| D1 | docstring | \"answers 200 with exactly `/api/video`'s eighteen keys\" | :140 | An added or dropped key | CARRIED |\n| D2 | docstring | \"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\" | :140 | Row values (all distinct), or the detail's followers 70 used in place of the channel call's 77 | CARRIED |\n| D3 | docstring | \"the channel URL built from the instance's channel slug and the host\" | :140 | Building it from the row's `db_slug` | CARRIED |\n| D4 | docstring | \"the original URL from the row's uuid and the host\" | :144 | The request is made by id `v1`, so building the URL from the query id gives `.../watch/v1`, not LIVE's `.../watch/uuid-v1` | CARRIED |\n| D5a | docstring | account name and URL \"from the row\" | :140 | Taking the instance's \"Live Account\" or `/accounts/live` | CARRIED |\n| D5b | docstring | channel avatar and published date \"from the row\" | :140 | An instance-only merge (\"\" / None) | CARRIED |\n| D5c | docstring | uuid and embed \"from the row\" | :144 | The request is made by id `v1`, so a videoUuid or embed built from the query id gives `v1` or `.../embed/v1`, not LIVE's `uuid-v1` values | CARRIED |\n| D6 | docstring | \"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\" | :142 | A wrong path, a wrong host, a reversed order, or an extra call | CARRIED |\n| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :153, :156 | An instance-only merge | CARRIED |\n| D8 | docstring | \"beside the instance's title, dislikes and `likes` 0\" | :155 | Row title, row dislikes 1, or a truthiness fallback giving likes 2 | CARRIED |\n| D9 | docstring | no id \u2192 400 `Missing video id`, no instance call | :166 | Another status or body, or a call made before validation | CARRIED |\n| D10 | docstring | id not in DB \u2192 404 `Video not found`, no instance call | :168 | An unrouted 404 `Not found`, or a call made before the lookup | CARRIED |\n| D11 | docstring | \"`/api/video` against the same answering instance still answers the instance's values\" | :174, :175 | A DB-only `/api/video` (\"DB title\", no calls) | CARRIED |\n| N1 | name | \"refresh answers the instance's values in the api video shape\" | :140, :144 | Same as C1a/C1b | CARRIED |\n| N2 | name | \"refresh answers the row's value for each field the instance omitted\" | :153, :156, :160, :161 | Between PARTIAL and OMITTING, every field either case omits is asserted, so an instance-only merge fails | CARRIED |\n| N3 | name | \"refresh without an id or for an unknown video is refused without calling the instance\" | :166, :168 | Same as D9/D10 | CARRIED |\n| N4 | name | \"api video still answers the instance's values\" | :174 | Same as D11 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:4. The docstring gained a clause the ledger does not have: \"with the detail omitting title, likes and dislikes instead, it answers the row's title, likes and dislikes beside the instance's description, views, channel display name and follower count\". It is carried by :160 and :161: the whole-body equality at :161 rules out the row's \"DB description\", 10, \"DB Chan\" and 5 standing in for OMITTING's values. It is recorded here because the prose was added alongside the assertions that answer C2e, D4 and D5c. It is not a defect.\n2. bounds / normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:147. No case has the detail call answer nothing at all (`fetch_instance_json` returns None for DETAIL_PATH). That is the far edge of C2's per-field fallback: every field omitted at once, with no channel slug to follow. No `must_prove` clause names that case, so it does not block.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), and that path does not exist. Nothing was judged from it.\n2. `fixtures_path` was not supplied. The test's only outside fixture inputs are `ENGINE_PY` and `ROOT`, which it imports from tests/active/conftest.py (lines 31\u201332). They were read there, and `sync_job` is defined in the test file itself.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThree tests fail, all because `/api/video/refresh` has no route and gets `404 {\"error\": \"Not found\"}`.\ntest_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 140 on\n`assert (report[\"status\"], report[\"body\"]) == (200, LIVE)`, reading (404, {\"error\": \"Not found\"}).\ntest_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 149 on\n`assert report[\"status\"] == 200`, reading 404.\ntest_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance fails\nat line 166, reading (404, {\"error\": \"Not found\"}, []) where it expects (400, {\"error\": \"Missing video id\"}, []).\ntest_api_video_still_answers_the_instances_values passes against today's `handle_video_request`.\n\nNOT ASSESSED\n1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve. It\n   was not read, and nothing in the test under audit imports it.\n2. `fixtures_path` was not supplied. I found tests/active/conftest.py and checked only the two\n   names the test imports from it: `ROOT` (line 31) and `ENGINE_PY` (line 32). The rest of that\n   file was not read.\n3. I confirmed that `SimilarServer.__init__` exists (engine/server/api/server.py:209), but did not\n   read its parameters. So the child's `dict.fromkeys(...)[3:]` construction (test line 76) was not\n   checked against its real signature. That does not change the shape findings.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (25 clauses: 8 must_prove, 13 docstring, 4 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :140 | Every live value in DETAIL/CHANNEL differs from the row's value. An answer built only from the row (\"DB title\", views 10, empty accountAvatarUrl) fails, and so does an unrouted 404 | CARRIED |\n| C1b | must_prove | in today's `/api/video` response shape | :140, :174 | :140 compares the whole dict to LIVE, and :174 pins LIVE as what `/api/video` answers for the same stub. A missing, extra or renamed key fails | CARRIED |\n| C1c | must_prove | the live values come from the instance's detail and channel calls | :142 | A refresh that skips the channel call (subscribersCount 70, not 77), or calls in another order or on another path | CARRIED |\n| C2a | must_prove | omitted `description` falls back to the row | :153 | Taking only the instance's field (\"\" in the answer) | CARRIED |\n| C2b | must_prove | omitted `views` falls back to the row | :153 | Taking only the instance's field (None) | CARRIED |\n| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :153 | The \"\" / None an instance-only merge would give | CARRIED |\n| C2d | must_prove | a supplied falsy value is not treated as omitted | :155 | A truthiness fallback that answers the row's likes 2 | CARRIED |\n| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | :160, :161 | OMITTING leaves out all three. An instance-only merge answers \"\", None, None, not the row's \"DB title\", 2, 1 | CARRIED |\n| D1 | docstring | \"answers 200 with exactly `/api/video`'s eighteen keys\" | :140 | An added or dropped key | CARRIED |\n| D2 | docstring | \"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\" | :140 | Row values (all distinct), or the detail's followers 70 used in place of the channel call's 77 | CARRIED |\n| D3 | docstring | \"the channel URL built from the instance's channel slug and the host\" | :140 | Building it from the row's `db_slug` | CARRIED |\n| D4 | docstring | \"the original URL from the row's uuid and the host\" | :144 | The request is made by id `v1`, so building the URL from the query id gives `.../watch/v1`, not LIVE's `.../watch/uuid-v1` | CARRIED |\n| D5a | docstring | account name and URL \"from the row\" | :140 | Taking the instance's \"Live Account\" or `/accounts/live` | CARRIED |\n| D5b | docstring | channel avatar and published date \"from the row\" | :140 | An instance-only merge (\"\" / None) | CARRIED |\n| D5c | docstring | uuid and embed \"from the row\" | :144 | The request is made by id `v1`, so a videoUuid or embed built from the query id gives `v1` or `.../embed/v1`, not LIVE's `uuid-v1` values | CARRIED |\n| D6 | docstring | \"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\" | :142 | A wrong path, a wrong host, a reversed order, or an extra call | CARRIED |\n| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :153, :156 | An instance-only merge | CARRIED |\n| D8 | docstring | \"beside the instance's title, dislikes and `likes` 0\" | :155 | Row title, row dislikes 1, or a truthiness fallback giving likes 2 | CARRIED |\n| D9 | docstring | no id \u2192 400 `Missing video id`, no instance call | :166 | Another status or body, or a call made before validation | CARRIED |\n| D10 | docstring | id not in DB \u2192 404 `Video not found`, no instance call | :168 | An unrouted 404 `Not found`, or a call made before the lookup | CARRIED |\n| D11 | docstring | \"`/api/video` against the same answering instance still answers the instance's values\" | :174, :175 | A DB-only `/api/video` (\"DB title\", no calls) | CARRIED |\n| N1 | name | \"refresh answers the instance's values in the api video shape\" | :140, :144 | Same as C1a/C1b | CARRIED |\n| N2 | name | \"refresh answers the row's value for each field the instance omitted\" | :153, :156, :160, :161 | Between PARTIAL and OMITTING, every field either case omits is asserted, so an instance-only merge fails | CARRIED |\n| N3 | name | \"refresh without an id or for an unknown video is refused without calling the instance\" | :166, :168 | Same as D9/D10 | CARRIED |\n| N4 | name | \"api video still answers the instance's values\" | :174 | Same as D11 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:4. The docstring gained a clause the ledger does not have: \"with the detail omitting title, likes and dislikes instead, it answers the row's title, likes and dislikes beside the instance's description, views, channel display name and follower count\". It is carried by :160 and :161: the whole-body equality at :161 rules out the row's \"DB description\", 10, \"DB Chan\" and 5 standing in for OMITTING's values. It is recorded here because the prose was added alongside the assertions that answer C2e, D4 and D5c. It is not a defect.\n2. bounds / normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:147. No case has the detail call answer nothing at all (`fetch_instance_json` returns None for DETAIL_PATH). That is the far edge of C2's per-field fallback: every field omitted at once, with no channel slug to follow. No `must_prove` clause names that case, so it does not block.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), and that path does not exist. Nothing was judged from it.\n2. `fixtures_path` was not supplied. The test's only outside fixture inputs are `ENGINE_PY` and `ROOT`, which it imports from tests/active/conftest.py (lines 31\u201332). They were read there, and `sync_job` is defined in the test file itself.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "`/api/video/refresh` answers the instance's live values",
            "assertion": ":140",
            "excludes": "Every live value in DETAIL/CHANNEL differs from the row's value. An answer built only from the row (\"DB title\", views 10, empty accountAvatarUrl) fails, and so does an unrouted 404",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "in today's `/api/video` response shape",
            "assertion": ":140, :174",
            "excludes": ":140 compares the whole dict to LIVE, and :174 pins LIVE as what `/api/video` answers for the same stub. A missing, extra or renamed key fails",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "the live values come from the instance's detail and channel calls",
            "assertion": ":142",
            "excludes": "A refresh that skips the channel call (subscribersCount 70, not 77), or calls in another order or on another path",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "omitted `description` falls back to the row",
            "assertion": ":153",
            "excludes": "Taking only the instance's field (\"\" in the answer)",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "omitted `views` falls back to the row",
            "assertion": ":153",
            "excludes": "Taking only the instance's field (None)",
            "status": "CARRIED"
          },
          {
            "id": "C2c",
            "source": "must_prove",
            "clause": "channel display name and follower count fall back when neither the detail nor the channel call supplies them",
            "assertion": ":153",
            "excludes": "The \"\" / None an instance-only merge would give",
            "status": "CARRIED"
          },
          {
            "id": "C2d",
            "source": "must_prove",
            "clause": "a supplied falsy value is not treated as omitted",
            "assertion": ":155",
            "excludes": "A truthiness fallback that answers the row's likes 2",
            "status": "CARRIED"
          },
          {
            "id": "C2e",
            "source": "must_prove",
            "clause": "omitted `title`, `likes` or `dislikes` falls back to the row",
            "assertion": ":160, :161",
            "excludes": "OMITTING leaves out all three. An instance-only merge answers \"\", None, None, not the row's \"DB title\", 2, 1",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"answers 200 with exactly `/api/video`'s eighteen keys\"",
            "assertion": ":140",
            "excludes": "An added or dropped key",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar\"",
            "assertion": ":140",
            "excludes": "Row values (all distinct), or the detail's followers 70 used in place of the channel call's 77",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"the channel URL built from the instance's channel slug and the host\"",
            "assertion": ":140",
            "excludes": "Building it from the row's `db_slug`",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the original URL from the row's uuid and the host\"",
            "assertion": ":144",
            "excludes": "The request is made by id `v1`, so building the URL from the query id gives `.../watch/v1`, not LIVE's `.../watch/uuid-v1`",
            "status": "CARRIED"
          },
          {
            "id": "D5a",
            "source": "docstring",
            "clause": "account name and URL \"from the row\"",
            "assertion": ":140",
            "excludes": "Taking the instance's \"Live Account\" or `/accounts/live`",
            "status": "CARRIED"
          },
          {
            "id": "D5b",
            "source": "docstring",
            "clause": "channel avatar and published date \"from the row\"",
            "assertion": ":140",
            "excludes": "An instance-only merge (\"\" / None)",
            "status": "CARRIED"
          },
          {
            "id": "D5c",
            "source": "docstring",
            "clause": "uuid and embed \"from the row\"",
            "assertion": ":144",
            "excludes": "The request is made by id `v1`, so a videoUuid or embed built from the query id gives `v1` or `.../embed/v1`, not LIVE's `uuid-v1` values",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`\"",
            "assertion": ":142",
            "excludes": "A wrong path, a wrong host, a reversed order, or an extra call",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "partial detail: row's description, views, channel display name and follower count",
            "assertion": ":153, :156",
            "excludes": "An instance-only merge",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"beside the instance's title, dislikes and `likes` 0\"",
            "assertion": ":155",
            "excludes": "Row title, row dislikes 1, or a truthiness fallback giving likes 2",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "no id \u2192 400 `Missing video id`, no instance call",
            "assertion": ":166",
            "excludes": "Another status or body, or a call made before validation",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "id not in DB \u2192 404 `Video not found`, no instance call",
            "assertion": ":168",
            "excludes": "An unrouted 404 `Not found`, or a call made before the lookup",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "\"`/api/video` against the same answering instance still answers the instance's values\"",
            "assertion": ":174, :175",
            "excludes": "A DB-only `/api/video` (\"DB title\", no calls)",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"refresh answers the instance's values in the api video shape\"",
            "assertion": ":140, :144",
            "excludes": "Same as C1a/C1b",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"refresh answers the row's value for each field the instance omitted\"",
            "assertion": ":153, :156, :160, :161",
            "excludes": "Between PARTIAL and OMITTING, every field either case omits is asserted, so an instance-only merge fails",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"refresh without an id or for an unknown video is refused without calling the instance\"",
            "assertion": ":166, :168",
            "excludes": "Same as D9/D10",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"api video still answers the instance's values\"",
            "assertion": ":174",
            "excludes": "Same as D11",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_11_fast_similars_response_phase2.py": [
      {
        "shape": "SHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe parametrized test `test_a_refresh_the_instance_did_not_answer_writes_nothing` fails. For `detail-none`, `detail-empty-object` and `urlopen-urlerror` it fails at tests/tmp/test_11_fast_similars_response_phase2.py:256 on `assert report[\"after\"] == report[\"before\"]`. `fetch_instance_video_dynamic` always returns a dict full of keys, so `if dynamic` at handlers/video.py:399 is truthy and `persist_video_metadata` runs. That run moves `videos.last_checked_at` off 1, recomputes `popularity` and clears `instances.last_error` 'boom'. For `detail-json-list` it fails earlier, at line 254 on `(status, body) == (200, DB_ONLY)`: `detail.get` on the list raises AttributeError and the connection drops with status None. `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` also fails, at line 211 inside `_assert_written` (called from line 241) on the `last_checked_at` window check. `do_GET` wraps the refresh in `statement_deadline(0.2)`, so the heavy trigger's UPDATE is interrupted and the OperationalError is swallowed at handlers/video.py:382.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". `ENGINE_PY` and `ROOT` were resolved from tests/active/conftest.py, which the test imports explicitly at line 25. The test's only fixture, `sync_job`, is defined in the test file. `sync-whitelist.py`'s `ensure_whitelist_schema` / `ensure_content_schema` were not read, so the seeded column set was not checked against the schema.\n2. `code_under_test` lists tests/active/test_video_metadata.py as EDITED. It is a test file, not code the test under audit exercises, so it was not read.\n3. `server.SimilarServer`, `RecommendationBuilderDeps` / `RecommendationBuilderSettings` and the similars route handler were not read. The C2 part of the stub question was answered from the assertion form: lines 267 and 269 pin a specific ANN answer (`(\"v1\", [\"v2\"])`) and elapsed < 1.0 s against a 5 s blocked refresh. A fast canned answer, or the older behaviour where the instance call runs inside `db_lock`, would not pass both.",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :215 (via :225) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:36) | CARRIED |\n| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :216 (via :225) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |\n| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :218 (via :225) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |\n| C1d | must_prove | \"only when\": no `videos` write when the detail call did not answer | :256 | a write on None / {} / list / URLError; bumping last_checked_at or popularity would break the before==after equality | CARRIED |\n| C1e | must_prove | \"only when\": no `channels` write when the detail call did not answer | :256 | a channel UPDATE that runs on a failed detail call | CARRIED |\n| C1f | must_prove | \"only when\": no `instances` write when the detail call did not answer | :256 | clearing last_error on a failed call | CARRIED |\n| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :269, preconditions :262, :263 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |\n| D1 | docstring | \"writes the videos, channels and instances rows only when the ... detail call answered\" | :215\u2013:218, :256 | same as C1a\u2013C1f | CARRIED |\n| D2 | docstring | \"a refresh blocked on the instance does not hold up the id-based similars GET\" | :269 | same as C2 | CARRIED |\n| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :215 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |\n| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :211 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |\n| D5 | docstring | nonzero `popularity` | :212 | popularity left as seeded, or not recomputed | CARRIED |\n| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :216 | taking the followers from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |\n| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :218 | any of the three left uncleared | CARRIED |\n| D8 | docstring | every other column and the other video's row unchanged | :215, :216, :218 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |\n| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :233 (via :211\u2013:218) | counting a failed channel call as a failed refresh (:211 fails); nulling display_name or followers_count | CARRIED |\n| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :241, precondition :239 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |\n| D11 | docstring | the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\" | none | nothing asserts the trigger reaches the check, so a fixture whose UPDATE never hits the progress handler lets D10 pass without testing anything | UNCARRIED |\n| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :254 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |\n| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :256 | any write on the failed-detail path | CARRIED |\n| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :265, :267, precondition :262 | an error answer; an empty answer; returning the seed itself | CARRIED |\n| D15 | docstring | \"in under 1 s\" | :269 | the similars GET serialised behind the 5 s instance call | CARRIED |\n| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :271, :272 | the similars route making instance calls of its own | CARRIED |\n| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :202 | a child that failed to build the server or run the requests | CARRIED |\n| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :215, :216, :218 | as C1a\u2013C1c | CARRIED |\n| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :233 | as D9 | CARRIED |\n| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :241, :239 | as D10 | CARRIED |\n| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :256 | as C1d\u2013C1f | CARRIED |\n| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :265, :267, :269 with :262, :263 | as C2 / D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:4, :173\n   `conn.execute(\"CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END\")`\n   D11 is UNCARRIED. The docstring says this trigger drives the UPDATE past the progress handler's 10,000-instruction check. The only support is the \"observed\" comments at :170 and :240. No assertion shows the check actually runs during the write in this fixture. Without that, D10 / N3 cannot tell an expired deadline that was honoured from one that was never checked. Either add a control that the deadline does interrupt a write in this fixture, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:244\u2013249\n   The \"did not answer\" cases are None, `{}`, a JSON list and URLError. These are not tested:\n   - a non-empty dict carrying none of the known fields, such as `{\"error\": \"...\"}`\n   - a non-200 status reaching `fetch_instance_json` through `urlopen`\n\n   These are the edges between \"answered\" and \"not answered\" that C1's \"only when\" depends on.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:261\n   C2 is only tested with a slow instance that does answer (`{**DETAIL, \"channel\": {}}`). No test covers a refresh that is blocked and then fails, such as a slow URLError or a detail that comes back None, while a similars GET is in flight.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py, which does not exist, so it was not read.\n2. The statement-deadline and progress-handler code (engine/server/api/server.py:272, engine/server/api/handlers/similar.py:351) is not in `code_under_test`. D10 and D11 were judged from the test and handlers/video.py only.\n3. The `popularity` column's seeded default (relied on at :210 and :212) was not confirmed in `sync-whitelist.py`'s schema.",
        "body": "### devsecops-test-shape-auditor\n\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\nThe parametrized test `test_a_refresh_the_instance_did_not_answer_writes_nothing` fails. For `detail-none`, `detail-empty-object` and `urlopen-urlerror` it fails at tests/tmp/test_11_fast_similars_response_phase2.py:256 on `assert report[\"after\"] == report[\"before\"]`. `fetch_instance_video_dynamic` always returns a dict full of keys, so `if dynamic` at handlers/video.py:399 is truthy and `persist_video_metadata` runs. That run moves `videos.last_checked_at` off 1, recomputes `popularity` and clears `instances.last_error` 'boom'. For `detail-json-list` it fails earlier, at line 254 on `(status, body) == (200, DB_ONLY)`: `detail.get` on the list raises AttributeError and the connection drops with status None. `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` also fails, at line 211 inside `_assert_written` (called from line 241) on the `last_checked_at` window check. `do_GET` wraps the refresh in `statement_deadline(0.2)`, so the heavy trigger's UPDATE is interrupted and the OperationalError is swallowed at handlers/video.py:382.\n\nNOT ASSESSED\n1. `fixtures_path` was given as \"none found\". `ENGINE_PY` and `ROOT` were resolved from tests/active/conftest.py, which the test imports explicitly at line 25. The test's only fixture, `sync_job`, is defined in the test file. `sync-whitelist.py`'s `ensure_whitelist_schema` / `ensure_content_schema` were not read, so the seeded column set was not checked against the schema.\n2. `code_under_test` lists tests/active/test_video_metadata.py as EDITED. It is a test file, not code the test under audit exercises, so it was not read.\n3. `server.SimilarServer`, `RecommendationBuilderDeps` / `RecommendationBuilderSettings` and the similars route handler were not read. The C2 part of the stub question was answered from the assertion form: lines 267 and 269 pin a specific ANN answer (`(\"v1\", [\"v2\"])`) and elapsed < 1.0 s against a 5 s blocked refresh. A fast canned answer, or the older behaviour where the instance call runs inside `db_lock`, would not pass both.\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :215 (via :225) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:36) | CARRIED |\n| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :216 (via :225) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |\n| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :218 (via :225) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |\n| C1d | must_prove | \"only when\": no `videos` write when the detail call did not answer | :256 | a write on None / {} / list / URLError; bumping last_checked_at or popularity would break the before==after equality | CARRIED |\n| C1e | must_prove | \"only when\": no `channels` write when the detail call did not answer | :256 | a channel UPDATE that runs on a failed detail call | CARRIED |\n| C1f | must_prove | \"only when\": no `instances` write when the detail call did not answer | :256 | clearing last_error on a failed call | CARRIED |\n| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :269, preconditions :262, :263 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |\n| D1 | docstring | \"writes the videos, channels and instances rows only when the ... detail call answered\" | :215\u2013:218, :256 | same as C1a\u2013C1f | CARRIED |\n| D2 | docstring | \"a refresh blocked on the instance does not hold up the id-based similars GET\" | :269 | same as C2 | CARRIED |\n| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :215 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |\n| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :211 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |\n| D5 | docstring | nonzero `popularity` | :212 | popularity left as seeded, or not recomputed | CARRIED |\n| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :216 | taking the followers from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |\n| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :218 | any of the three left uncleared | CARRIED |\n| D8 | docstring | every other column and the other video's row unchanged | :215, :216, :218 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |\n| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :233 (via :211\u2013:218) | counting a failed channel call as a failed refresh (:211 fails); nulling display_name or followers_count | CARRIED |\n| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :241, precondition :239 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |\n| D11 | docstring | the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\" | none | nothing asserts the trigger reaches the check, so a fixture whose UPDATE never hits the progress handler lets D10 pass without testing anything | UNCARRIED |\n| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :254 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |\n| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :256 | any write on the failed-detail path | CARRIED |\n| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :265, :267, precondition :262 | an error answer; an empty answer; returning the seed itself | CARRIED |\n| D15 | docstring | \"in under 1 s\" | :269 | the similars GET serialised behind the 5 s instance call | CARRIED |\n| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :271, :272 | the similars route making instance calls of its own | CARRIED |\n| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :202 | a child that failed to build the server or run the requests | CARRIED |\n| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :215, :216, :218 | as C1a\u2013C1c | CARRIED |\n| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :233 | as D9 | CARRIED |\n| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :241, :239 | as D10 | CARRIED |\n| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :256 | as C1d\u2013C1f | CARRIED |\n| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :265, :267, :269 with :262, :263 | as C2 / D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:4, :173\n   `conn.execute(\"CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END\")`\n   D11 is UNCARRIED. The docstring says this trigger drives the UPDATE past the progress handler's 10,000-instruction check. The only support is the \"observed\" comments at :170 and :240. No assertion shows the check actually runs during the write in this fixture. Without that, D10 / N3 cannot tell an expired deadline that was honoured from one that was never checked. Either add a control that the deadline does interrupt a write in this fixture, or narrow the sentence.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:244\u2013249\n   The \"did not answer\" cases are None, `{}`, a JSON list and URLError. These are not tested:\n   - a non-empty dict carrying none of the known fields, such as `{\"error\": \"...\"}`\n   - a non-200 status reaching `fetch_instance_json` through `urlopen`\n\n   These are the edges between \"answered\" and \"not answered\" that C1's \"only when\" depends on.\n3. normal-and-abnormal-paths (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:261\n   C2 is only tested with a slow instance that does answer (`{**DETAIL, \"channel\": {}}`). No test covers a refresh that is blocked and then fails, such as a slow URLError or a detail that comes back None, while a similars GET is in flight.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py, which does not exist, so it was not read.\n2. The statement-deadline and progress-handler code (engine/server/api/server.py:272, engine/server/api/handlers/similar.py:351) is not in `code_under_test`. D10 and D11 were judged from the test and handlers/video.py only.\n3. The `popularity` column's seeded default (relied on at :210 and :212) was not confirmed in `sync-whitelist.py`'s schema.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "refresh updates the `videos` row when the detail call answered",
            "assertion": ":215 (via :225)",
            "excludes": "a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:36)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "refresh updates the `channels` row when the detail call answered",
            "assertion": ":216 (via :225)",
            "excludes": "a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "refresh updates the `instances` row when the detail call answered",
            "assertion": ":218 (via :225)",
            "excludes": "an instance row still reading 'boom', 123, 'crawler'",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"only when\": no `videos` write when the detail call did not answer",
            "assertion": ":256",
            "excludes": "a write on None / {} / list / URLError; bumping last_checked_at or popularity would break the before==after equality",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"only when\": no `channels` write when the detail call did not answer",
            "assertion": ":256",
            "excludes": "a channel UPDATE that runs on a failed detail call",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "\"only when\": no `instances` write when the detail call did not answer",
            "assertion": ":256",
            "excludes": "clearing last_error on a failed call",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "a refresh blocked on a slow instance does not delay the similars answer",
            "assertion": ":269, preconditions :262, :263",
            "excludes": "taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"writes the videos, channels and instances rows only when the ... detail call answered\"",
            "assertion": ":215\u2013:218, :256",
            "excludes": "same as C1a\u2013C1f",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a refresh blocked on the instance does not hold up the id-based similars GET\"",
            "assertion": ":269",
            "excludes": "same as C2",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "video row holds title, description, channel display name, counts, tags, category, nsfw",
            "assertion": ":215",
            "excludes": "any of the nine LIVE_VIDEO columns left at its seeded value or written wrong",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "`last_checked_at` inside the run's wall-clock window",
            "assertion": ":211",
            "excludes": "last_checked_at left at 1, or stamped with a stale or constant value",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "nonzero `popularity`",
            "assertion": ":212",
            "excludes": "popularity left as seeded, or not recomputed",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "channel row holds slug, display name and the channel call's follower count",
            "assertion": ":216",
            "excludes": "taking the followers from the detail (70) and not from the channel call (77); slug left at db_slug",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "instance `last_error`, `last_error_at`, `last_error_source` are NULL",
            "assertion": ":218",
            "excludes": "any of the three left uncleared",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "every other column and the other video's row unchanged",
            "assertion": ":215, :216, :218",
            "excludes": "an UPDATE that also touches account columns or v2 (full-dict equality)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "channel call answering nothing: rows still written, display name and followers keep DB values",
            "assertion": ":233 (via :211\u2013:218)",
            "excludes": "counting a failed channel call as a failed refresh (:211 fails); nulling display_name or followers_count",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written",
            "assertion": ":241, precondition :239",
            "excludes": "a persist interrupted by the request's expired deadline, which leaves rows as seeded",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\"",
            "assertion": "none",
            "excludes": "nothing asserts the trigger reaches the check, so a fixture whose UPDATE never hits the progress handler lets D10 pass without testing anything",
            "status": "UNCARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "detail None / {} / list / URLError: refresh answers 200 with the DB-only values",
            "assertion": ":254",
            "excludes": "a dropped connection on the list case; a 500; live values or blanks in the answer",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "every column incl. `last_checked_at` and `last_error` the same before and after",
            "assertion": ":256",
            "excludes": "any write on the failed-detail path",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour",
            "assertion": ":265, :267, precondition :262",
            "excludes": "an error answer; an empty answer; returning the seed itself",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"in under 1 s\"",
            "assertion": ":269",
            "excludes": "the similars GET serialised behind the 5 s instance call",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "stub called only for the refresh's `/api/v1/videos/{uuid}` by then",
            "assertion": ":271, :272",
            "excludes": "the similars route making instance calls of its own",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB",
            "assertion": ":202",
            "excludes": "a child that failed to build the server or run the requests",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows`",
            "assertion": ":215, :216, :218",
            "excludes": "as C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields`",
            "assertion": ":233",
            "excludes": "as D9",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed`",
            "assertion": ":241, :239",
            "excludes": "as D10",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "`test_a_refresh_the_instance_did_not_answer_writes_nothing`",
            "assertion": ":256",
            "excludes": "as C1d\u2013C1f",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "`test_similars_answer_while_a_refresh_is_blocked_on_the_instance`",
            "assertion": ":265, :267, :269 with :262, :263",
            "excludes": "as C2 / D14",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_the_instance_did_not_answer_writes_nothing fails. For [detail-none],\n[detail-empty-object] and [urlopen-urlerror] it fails at line 285 on\n`assert report[\"after\"] == report[\"before\"]`: `fetch_instance_video_dynamic`\n(video.py:189) always returns a non-empty dict of keys, so `if dynamic` (video.py:399)\nis true and `persist_video_metadata` bumps `last_checked_at` from 1, recomputes\n`popularity`, and clears `instances.last_error` 'boom'. For [detail-json-list] it fails\nearlier, at line 283 on `(status, body) == (200, DB_ONLY)`: `detail.get` (video.py:166)\nraises on a list, the connection drops, and status is None.\n\nNOT ASSESSED\n1. The `code_under_test` path tests/active/test_video_metadata.py does not resolve\n   (no such file). This audit was completed from test_path, engine/server/api/handlers/video.py,\n   and the symbols the test names: `statement_deadline`, `is_interrupted_error` and\n   `connect_db` in engine/server/data/db.py, and `ensure_whitelist_schema` and\n   `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py. All of them resolve.\n2. No `fixtures_path` was supplied. The test imports `ENGINE_PY` and `ROOT` from\n   tests/active/conftest.py (line 25). Both were confirmed at conftest.py:31-32, and no\n   other external fixture is used.\n3. The child-process names SimilarServer, RecommendationBuilderDeps and the\n   server.fetch_* helpers (lines 96-107) were not traced to their definitions. The C2\n   stub answer rests on the assertion form at lines 291-301, not on those symbols.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 17 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :241 (via :251) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:37, :42) | CARRIED |\n| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :242 (via :251) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |\n| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :244 (via :251) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |\n| C1d | must_prove | \"only when\": no `videos` write when the detail call did not answer | :285 | a write on None / {} / list / URLError; bumping last_checked_at or popularity breaks the before==after equality | CARRIED |\n| C1e | must_prove | \"only when\": no `channels` write when the detail call did not answer | :285 | a channel UPDATE that runs on a failed detail call | CARRIED |\n| C1f | must_prove | \"only when\": no `instances` write when the detail call did not answer | :285 | clearing last_error on a failed call | CARRIED |\n| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :298, preconditions :291, :292 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |\n| D1 | docstring | \"writes the videos, channels and instances rows only when the ... detail call answered\" | :241\u2013:244, :285 | same as C1a\u2013C1f | CARRIED |\n| D2 | docstring | \"a refresh blocked on the instance does not hold up the id-based similars GET\" | :298 | same as C2 | CARRIED |\n| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :241 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |\n| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :237 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |\n| D5 | docstring | nonzero `popularity` | :238 | popularity left as seeded, or not recomputed | CARRIED |\n| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :242 | followers taken from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |\n| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :244 | any of the three left uncleared | CARRIED |\n| D8 | docstring | every other column and the other video's row unchanged | :241, :242, :244 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |\n| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :259 (via :237\u2013:244) | treating a failed channel call as a failed refresh (:237 fails); nulling display_name or followers_count | CARRIED |\n| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :270, precondition :268 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |\n| D11 | docstring | the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\" | :264, :265 | a heavy fixture whose UPDATE never reaches the progress handler (:264 would return False); a plain schema that already reaches it, which would make the trigger pointless (:265) | CARRIED |\n| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :283 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |\n| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :285 | any write on the failed-detail path | CARRIED |\n| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :294, :296, precondition :291 | an error answer; an empty answer; returning the seed itself | CARRIED |\n| D15 | docstring | \"in under 1 s\" | :298 | the similars GET waiting behind the 5 s instance call | CARRIED |\n| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :300, :301 | the similars route making instance calls of its own | CARRIED |\n| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :228 | a child that failed to build the server or run the requests | CARRIED |\n| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :241, :242, :244 | as C1a\u2013C1c | CARRIED |\n| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :259 | as D9 | CARRIED |\n| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :270, :268 | as D10 | CARRIED |\n| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :285 | as C1d\u2013C1f | CARRIED |\n| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :294, :296, :298 with :291, :292 | as C2 / D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:264\n   assert _interrupted(data_db, sync_job, tmp_path / \"heavy.db\", True) is True\n   The first audit left D11 UNCARRIED. It is now carried because an assertion was added, not because the docstring was narrowed. :264 checks that the heavy fixture's UPDATE is interrupted once the deadline has expired. :265 checks that the plain schema's UPDATE is not. The control runs on its own file (heavy.db), not on the case's case.db. Both are seeded by the same `_seed(..., heavy=True)`, so the fixture it checks is the one :266 runs on.\n2. The ledger's line citations no longer match the file, because lines were added above them. Every row above cites its assertion's current line. The ledger's :215/:216/:218 are now :241/:242/:244, :256 is now :285, and :269 is now :298.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (EDITED). I did not read it: the test under audit does not import or call it, and it has no bearing on how the clauses map to assertions.\n2. I read `conftest.ENGINE_PY` / `ROOT` (imported at :25 from tests/active/conftest.py) only as names. They affect where the child process runs, not which clauses the test carries.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_the_instance_did_not_answer_writes_nothing fails. For [detail-none],\n[detail-empty-object] and [urlopen-urlerror] it fails at line 285 on\n`assert report[\"after\"] == report[\"before\"]`: `fetch_instance_video_dynamic`\n(video.py:189) always returns a non-empty dict of keys, so `if dynamic` (video.py:399)\nis true and `persist_video_metadata` bumps `last_checked_at` from 1, recomputes\n`popularity`, and clears `instances.last_error` 'boom'. For [detail-json-list] it fails\nearlier, at line 283 on `(status, body) == (200, DB_ONLY)`: `detail.get` (video.py:166)\nraises on a list, the connection drops, and status is None.\n\nNOT ASSESSED\n1. The `code_under_test` path tests/active/test_video_metadata.py does not resolve\n   (no such file). This audit was completed from test_path, engine/server/api/handlers/video.py,\n   and the symbols the test names: `statement_deadline`, `is_interrupted_error` and\n   `connect_db` in engine/server/data/db.py, and `ensure_whitelist_schema` and\n   `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py. All of them resolve.\n2. No `fixtures_path` was supplied. The test imports `ENGINE_PY` and `ROOT` from\n   tests/active/conftest.py (line 25). Both were confirmed at conftest.py:31-32, and no\n   other external fixture is used.\n3. The child-process names SimilarServer, RecommendationBuilderDeps and the\n   server.fetch_* helpers (lines 96-107) were not traced to their definitions. The C2\n   stub answer rests on the assertion form at lines 291-301, not on those symbols.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (29 clauses: 7 must_prove, 17 docstring, 5 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :241 (via :251) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:37, :42) | CARRIED |\n| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :242 (via :251) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |\n| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :244 (via :251) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |\n| C1d | must_prove | \"only when\": no `videos` write when the detail call did not answer | :285 | a write on None / {} / list / URLError; bumping last_checked_at or popularity breaks the before==after equality | CARRIED |\n| C1e | must_prove | \"only when\": no `channels` write when the detail call did not answer | :285 | a channel UPDATE that runs on a failed detail call | CARRIED |\n| C1f | must_prove | \"only when\": no `instances` write when the detail call did not answer | :285 | clearing last_error on a failed call | CARRIED |\n| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :298, preconditions :291, :292 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |\n| D1 | docstring | \"writes the videos, channels and instances rows only when the ... detail call answered\" | :241\u2013:244, :285 | same as C1a\u2013C1f | CARRIED |\n| D2 | docstring | \"a refresh blocked on the instance does not hold up the id-based similars GET\" | :298 | same as C2 | CARRIED |\n| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :241 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |\n| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :237 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |\n| D5 | docstring | nonzero `popularity` | :238 | popularity left as seeded, or not recomputed | CARRIED |\n| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :242 | followers taken from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |\n| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :244 | any of the three left uncleared | CARRIED |\n| D8 | docstring | every other column and the other video's row unchanged | :241, :242, :244 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |\n| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :259 (via :237\u2013:244) | treating a failed channel call as a failed refresh (:237 fails); nulling display_name or followers_count | CARRIED |\n| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :270, precondition :268 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |\n| D11 | docstring | the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\" | :264, :265 | a heavy fixture whose UPDATE never reaches the progress handler (:264 would return False); a plain schema that already reaches it, which would make the trigger pointless (:265) | CARRIED |\n| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :283 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |\n| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :285 | any write on the failed-detail path | CARRIED |\n| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :294, :296, precondition :291 | an error answer; an empty answer; returning the seed itself | CARRIED |\n| D15 | docstring | \"in under 1 s\" | :298 | the similars GET waiting behind the 5 s instance call | CARRIED |\n| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :300, :301 | the similars route making instance calls of its own | CARRIED |\n| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :228 | a child that failed to build the server or run the requests | CARRIED |\n| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :241, :242, :244 | as C1a\u2013C1c | CARRIED |\n| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :259 | as D9 | CARRIED |\n| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :270, :268 | as D10 | CARRIED |\n| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :285 | as C1d\u2013C1f | CARRIED |\n| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :294, :296, :298 with :291, :292 | as C2 / D14 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase2.py:264\n   assert _interrupted(data_db, sync_job, tmp_path / \"heavy.db\", True) is True\n   The first audit left D11 UNCARRIED. It is now carried because an assertion was added, not because the docstring was narrowed. :264 checks that the heavy fixture's UPDATE is interrupted once the deadline has expired. :265 checks that the plain schema's UPDATE is not. The control runs on its own file (heavy.db), not on the case's case.db. Both are seeded by the same `_seed(..., heavy=True)`, so the fixture it checks is the one :266 runs on.\n2. The ledger's line citations no longer match the file, because lines were added above them. Every row above cites its assertion's current line. The ledger's :215/:216/:218 are now :241/:242/:244, :256 is now :285, and :269 is now :298.\n\nNOT ASSESSED\n1. `code_under_test` lists tests/active/test_video_metadata.py (EDITED). I did not read it: the test under audit does not import or call it, and it has no bearing on how the clauses map to assertions.\n2. I read `conftest.ENGINE_PY` / `ROOT` (imported at :25 from tests/active/conftest.py) only as names. They affect where the child process runs, not which clauses the test carries.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "refresh updates the `videos` row when the detail call answered",
            "assertion": ":241 (via :251)",
            "excludes": "a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:37, :42)",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "refresh updates the `channels` row when the detail call answered",
            "assertion": ":242 (via :251)",
            "excludes": "a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "refresh updates the `instances` row when the detail call answered",
            "assertion": ":244 (via :251)",
            "excludes": "an instance row still reading 'boom', 123, 'crawler'",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"only when\": no `videos` write when the detail call did not answer",
            "assertion": ":285",
            "excludes": "a write on None / {} / list / URLError; bumping last_checked_at or popularity breaks the before==after equality",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"only when\": no `channels` write when the detail call did not answer",
            "assertion": ":285",
            "excludes": "a channel UPDATE that runs on a failed detail call",
            "status": "CARRIED"
          },
          {
            "id": "C1f",
            "source": "must_prove",
            "clause": "\"only when\": no `instances` write when the detail call did not answer",
            "assertion": ":285",
            "excludes": "clearing last_error on a failed call",
            "status": "CARRIED"
          },
          {
            "id": "C2",
            "source": "must_prove",
            "clause": "a refresh blocked on a slow instance does not delay the similars answer",
            "assertion": ":298, preconditions :291, :292",
            "excludes": "taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"writes the videos, channels and instances rows only when the ... detail call answered\"",
            "assertion": ":241\u2013:244, :285",
            "excludes": "same as C1a\u2013C1f",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"a refresh blocked on the instance does not hold up the id-based similars GET\"",
            "assertion": ":298",
            "excludes": "same as C2",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "video row holds title, description, channel display name, counts, tags, category, nsfw",
            "assertion": ":241",
            "excludes": "any of the nine LIVE_VIDEO columns left at its seeded value or written wrong",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "`last_checked_at` inside the run's wall-clock window",
            "assertion": ":237",
            "excludes": "last_checked_at left at 1, or stamped with a stale or constant value",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "nonzero `popularity`",
            "assertion": ":238",
            "excludes": "popularity left as seeded, or not recomputed",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "channel row holds slug, display name and the channel call's follower count",
            "assertion": ":242",
            "excludes": "followers taken from the detail (70) and not from the channel call (77); slug left at db_slug",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "instance `last_error`, `last_error_at`, `last_error_source` are NULL",
            "assertion": ":244",
            "excludes": "any of the three left uncleared",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "every other column and the other video's row unchanged",
            "assertion": ":241, :242, :244",
            "excludes": "an UPDATE that also touches account columns or v2 (full-dict equality)",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "channel call answering nothing: rows still written, display name and followers keep DB values",
            "assertion": ":259 (via :237\u2013:244)",
            "excludes": "treating a failed channel call as a failed refresh (:237 fails); nulling display_name or followers_count",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written",
            "assertion": ":270, precondition :268",
            "excludes": "a persist interrupted by the request's expired deadline, which leaves rows as seeded",
            "status": "CARRIED"
          },
          {
            "id": "D11",
            "source": "docstring",
            "clause": "the extra AFTER UPDATE trigger \"runs well past the progress handler's 10,000-instruction check\"",
            "assertion": ":264, :265",
            "excludes": "a heavy fixture whose UPDATE never reaches the progress handler (:264 would return False); a plain schema that already reaches it, which would make the trigger pointless (:265)",
            "status": "CARRIED"
          },
          {
            "id": "D12",
            "source": "docstring",
            "clause": "detail None / {} / list / URLError: refresh answers 200 with the DB-only values",
            "assertion": ":283",
            "excludes": "a dropped connection on the list case; a 500; live values or blanks in the answer",
            "status": "CARRIED"
          },
          {
            "id": "D13",
            "source": "docstring",
            "clause": "every column incl. `last_checked_at` and `last_error` the same before and after",
            "assertion": ":285",
            "excludes": "any write on the failed-detail path",
            "status": "CARRIED"
          },
          {
            "id": "D14",
            "source": "docstring",
            "clause": "similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour",
            "assertion": ":294, :296, precondition :291",
            "excludes": "an error answer; an empty answer; returning the seed itself",
            "status": "CARRIED"
          },
          {
            "id": "D15",
            "source": "docstring",
            "clause": "\"in under 1 s\"",
            "assertion": ":298",
            "excludes": "the similars GET waiting behind the 5 s instance call",
            "status": "CARRIED"
          },
          {
            "id": "D16",
            "source": "docstring",
            "clause": "stub called only for the refresh's `/api/v1/videos/{uuid}` by then",
            "assertion": ":300, :301",
            "excludes": "the similars route making instance calls of its own",
            "status": "CARRIED"
          },
          {
            "id": "D17",
            "source": "docstring",
            "clause": "each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB",
            "assertion": ":228",
            "excludes": "a child that failed to build the server or run the requests",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "`test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows`",
            "assertion": ":241, :242, :244",
            "excludes": "as C1a\u2013C1c",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "`test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields`",
            "assertion": ":259",
            "excludes": "as D9",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "`test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed`",
            "assertion": ":270, :268",
            "excludes": "as D10",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "`test_a_refresh_the_instance_did_not_answer_writes_nothing`",
            "assertion": ":285",
            "excludes": "as C1d\u2013C1f",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "`test_similars_answer_while_a_refresh_is_blocked_on_the_instance`",
            "assertion": ":294, :296, :298 with :291, :292",
            "excludes": "as C2 / D14",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ],
    "tests/tmp/test_11_fast_similars_response_phase3.py": [
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400\nfails at tests/tmp/test_11_fast_similars_response_phase3.py:67 on `assert refused == [400, 400, 400]`,\nbecause client/backend/server.py has no route for `/api/video/refresh` (it is absent from\nPROXY_READ_GET_ROUTES and PROXY_ALLOWED_QUERY_PARAMS, server.py:81-101), so each query answers\n404. test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84 on\n`assert refresh_status == 502`, because the refresh answers 404 for the same reason.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The imported harness was read in place:\n   tests/active/conftest.py:41-42 (`client_server`, `RateLimiter`) and tests/active/test_server.py:347-378\n   (`_serving`, `_client_backend`, `_status`). Nothing further was needed.\n2. The 404 in the predicted failure is taken from the test's own comment at line 64 (\"unrouted,\n   all three answer 404 (observed)\") and from the route tables at server.py:81-101. The handler's\n   unrouted-GET branch was not read line by line.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"forwards `/api/video/refresh`\" to the Engine | :70 | the request is forwarded to `/api/video` or another path, or never reaches the Engine | CARRIED |\n| C1b | must_prove | \"with only `id` and `host`\" | :70 | the proxy adds a param (such as `user_id`), drops one, or changes a value. Exact dict equality with FORWARDED | CARRIED |\n| C1c | must_prove | \"refuses any other \u2026 query key with 400\" | :67 | the route reuses the `/api/video` allow-list (user_id, refresh_cache), or stays unrouted and answers 404 | CARRIED |\n| C1d | must_prove | \"refuses any \u2026 repeated query key with 400\": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` | CARRIED |\n| C1e | must_prove | \"refuses any \u2026 repeated query key with 400\": `host` repeated | none | nothing. No refused query repeats `host` | UNCARRIED |\n| C2a | must_prove | a timed-out refresh \"is sent to the Engine once\" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |\n| C2b | must_prove | a timed-out refresh is \"answered 502\" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |\n| D1 | docstring | \"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\" | :70 | a wrong upstream path or an extra or missing param | CARRIED |\n| D2 | docstring | \"sends a refresh that times out at the proxy to the Engine once\" | :85 | a retry on timeout | CARRIED |\n| D3 | docstring | \"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\" | :70 | a wrong path, or params added or dropped | CARRIED |\n| D4 | docstring | \"the browser gets the Engine's 200 body\" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |\n| D5 | docstring | \"plus `user_id`, plus `refresh_cache`, or with `id` repeated each answers 400\" | :67 | any of the three being accepted, or answering 404 | CARRIED |\n| D6 | docstring | \"and reaches the Engine not at all\" | :70 | forwarding a refused request. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |\n| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |\n| D8 | docstring | \"and the Engine saw it once\" | :85 | a retry. The retry would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |\n| D9 | docstring | \"`/api/video` \u2026 answers 502 after two attempts\" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |\n| D10 | docstring | \"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |\n| N1 | name | \"a refresh reaches the engine with only id and host\" | :70 | a wrong path, or extra or missing params | CARRIED |\n| N2 | name | \"any other \u2026 key answers 400\" | :67 | the `/api/video` allow-list being reused | CARRIED |\n| N3 | name | \"or repeated key answers 400\" | :67 | only a repeated `id` is excluded, and a repeated `host` is not (see C1e) | CARRIED |\n| N4 | name | \"a refresh that times out at the proxy\" | :84 | the 10 s default letting the answer through as 200 | CARRIED |\n| N5 | name | \"is sent once\" | :85 | a retry on timeout | CARRIED |\n| N6 | name | \"and answered 502\" | :84 | any status other than 502 | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   `refused = [_status(base, \"GET\", f\"{REFRESH_ROUTE}?{query}\", {}) for query in (f\"{QUERY}&user_id=u-1\", f\"{QUERY}&refresh_cache=1\", f\"id=uuid-2&{QUERY}\")]`\n   C1 says the Client refuses \"any \u2026 repeated query key\" with 400, and only two keys are allowed: `id` and `host`. The principle says \"a claim naming a set of fields asserts every member of the set\". The test repeats only `id` (`id=uuid-2&{QUERY}`) and checks it at :67 (`assert refused == [400, 400, 400]`). Nothing sends a repeated `host`. So a refresh handler that checks `id` for multiple values but reads `host` as `params[\"host\"][0]` or `params[\"host\"][-1]` would pass this test while breaking C1. Row C1e is UNCARRIED.\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   \"Any other key\" is tested only with `user_id` and `refresh_cache`. Both are keys the `/api/video` allow-list accepts, which rules out copying that list. No key outside every allow-list is tested, such as `foo=1`. The edges of the accepted input are also untested: `id` or `host` missing, empty (`id=&host=\u2026`), or whitespace-only. The generic GET handler (client/backend/server.py:430-432) quietly drops empty values after stripping, so what the refresh route forwards in that case has no test.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines no pytest fixtures besides `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from tests/active/conftest.py, which I checked only at their definitions (conftest.py:41-42). It imports `_client_backend`, `_serving` and `_status` from tests/active/test_server.py:347-378, and I read those in full.\n2. client/backend/server.py as read has no `/api/video/refresh` route, no entry for it in `PROXY_ALLOWED_QUERY_PARAMS`, and no `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`. So I could not read the refresh route's accepted inputs or failure mode from code. Bounds and the abnormal path were judged against `must_prove` and the existing generic proxy handler (server.py:417-436, 570-745).",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400\nfails at tests/tmp/test_11_fast_similars_response_phase3.py:67 on `assert refused == [400, 400, 400]`,\nbecause client/backend/server.py has no route for `/api/video/refresh` (it is absent from\nPROXY_READ_GET_ROUTES and PROXY_ALLOWED_QUERY_PARAMS, server.py:81-101), so each query answers\n404. test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84 on\n`assert refresh_status == 502`, because the refresh answers 404 for the same reason.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The imported harness was read in place:\n   tests/active/conftest.py:41-42 (`client_server`, `RateLimiter`) and tests/active/test_server.py:347-378\n   (`_serving`, `_client_backend`, `_status`). Nothing further was needed.\n2. The 404 in the predicted failure is taken from the test's own comment at line 64 (\"unrouted,\n   all three answer 404 (observed)\") and from the route tables at server.py:81-101. The handler's\n   unrouted-GET branch was not read line by line.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: BLOCK\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"forwards `/api/video/refresh`\" to the Engine | :70 | the request is forwarded to `/api/video` or another path, or never reaches the Engine | CARRIED |\n| C1b | must_prove | \"with only `id` and `host`\" | :70 | the proxy adds a param (such as `user_id`), drops one, or changes a value. Exact dict equality with FORWARDED | CARRIED |\n| C1c | must_prove | \"refuses any other \u2026 query key with 400\" | :67 | the route reuses the `/api/video` allow-list (user_id, refresh_cache), or stays unrouted and answers 404 | CARRIED |\n| C1d | must_prove | \"refuses any \u2026 repeated query key with 400\": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` | CARRIED |\n| C1e | must_prove | \"refuses any \u2026 repeated query key with 400\": `host` repeated | none | nothing. No refused query repeats `host` | UNCARRIED |\n| C2a | must_prove | a timed-out refresh \"is sent to the Engine once\" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |\n| C2b | must_prove | a timed-out refresh is \"answered 502\" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |\n| D1 | docstring | \"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\" | :70 | a wrong upstream path or an extra or missing param | CARRIED |\n| D2 | docstring | \"sends a refresh that times out at the proxy to the Engine once\" | :85 | a retry on timeout | CARRIED |\n| D3 | docstring | \"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\" | :70 | a wrong path, or params added or dropped | CARRIED |\n| D4 | docstring | \"the browser gets the Engine's 200 body\" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |\n| D5 | docstring | \"plus `user_id`, plus `refresh_cache`, or with `id` repeated each answers 400\" | :67 | any of the three being accepted, or answering 404 | CARRIED |\n| D6 | docstring | \"and reaches the Engine not at all\" | :70 | forwarding a refused request. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |\n| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |\n| D8 | docstring | \"and the Engine saw it once\" | :85 | a retry. The retry would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |\n| D9 | docstring | \"`/api/video` \u2026 answers 502 after two attempts\" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |\n| D10 | docstring | \"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |\n| N1 | name | \"a refresh reaches the engine with only id and host\" | :70 | a wrong path, or extra or missing params | CARRIED |\n| N2 | name | \"any other \u2026 key answers 400\" | :67 | the `/api/video` allow-list being reused | CARRIED |\n| N3 | name | \"or repeated key answers 400\" | :67 | only a repeated `id` is excluded, and a repeated `host` is not (see C1e) | CARRIED |\n| N4 | name | \"a refresh that times out at the proxy\" | :84 | the 10 s default letting the answer through as 200 | CARRIED |\n| N5 | name | \"is sent once\" | :85 | a retry on timeout | CARRIED |\n| N6 | name | \"and answered 502\" | :84 | any status other than 502 | CARRIED |\n\nCRITICAL\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   `refused = [_status(base, \"GET\", f\"{REFRESH_ROUTE}?{query}\", {}) for query in (f\"{QUERY}&user_id=u-1\", f\"{QUERY}&refresh_cache=1\", f\"id=uuid-2&{QUERY}\")]`\n   C1 says the Client refuses \"any \u2026 repeated query key\" with 400, and only two keys are allowed: `id` and `host`. The principle says \"a claim naming a set of fields asserts every member of the set\". The test repeats only `id` (`id=uuid-2&{QUERY}`) and checks it at :67 (`assert refused == [400, 400, 400]`). Nothing sends a repeated `host`. So a refresh handler that checks `id` for multiple values but reads `host` as `params[\"host\"][0]` or `params[\"host\"][-1]` would pass this test while breaking C1. Row C1e is UNCARRIED.\n\nRECOMMENDATIONS\n1. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   \"Any other key\" is tested only with `user_id` and `refresh_cache`. Both are keys the `/api/video` allow-list accepts, which rules out copying that list. No key outside every allow-list is tested, such as `foo=1`. The edges of the accepted input are also untested: `id` or `host` missing, empty (`id=&host=\u2026`), or whitespace-only. The generic GET handler (client/backend/server.py:430-432) quietly drops empty values after stripping, so what the refresh route forwards in that case has no test.\n\nOBSERVATIONS\nnone\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test defines no pytest fixtures besides `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from tests/active/conftest.py, which I checked only at their definitions (conftest.py:41-42). It imports `_client_backend`, `_serving` and `_status` from tests/active/test_server.py:347-378, and I read those in full.\n2. client/backend/server.py as read has no `/api/video/refresh` route, no entry for it in `PROXY_ALLOWED_QUERY_PARAMS`, and no `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`. So I could not read the refresh route's accepted inputs or failure mode from code. Bounds and the abnormal path were judged against `must_prove` and the existing generic proxy handler (server.py:417-436, 570-745).",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"forwards `/api/video/refresh`\" to the Engine",
            "assertion": ":70",
            "excludes": "the request is forwarded to `/api/video` or another path, or never reaches the Engine",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"with only `id` and `host`\"",
            "assertion": ":70",
            "excludes": "the proxy adds a param (such as `user_id`), drops one, or changes a value. Exact dict equality with FORWARDED",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"refuses any other \u2026 query key with 400\"",
            "assertion": ":67",
            "excludes": "the route reuses the `/api/video` allow-list (user_id, refresh_cache), or stays unrouted and answers 404",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"refuses any \u2026 repeated query key with 400\": `id` repeated",
            "assertion": ":67",
            "excludes": "first-value-wins or last-value-wins handling of `id`",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"refuses any \u2026 repeated query key with 400\": `host` repeated",
            "assertion": "none",
            "excludes": "nothing. No refused query repeats `host`",
            "status": "UNCARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a timed-out refresh \"is sent to the Engine once\"",
            "assertion": ":85",
            "excludes": "the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "a timed-out refresh is \"answered 502\"",
            "assertion": ":84",
            "excludes": "the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\"",
            "assertion": ":70",
            "excludes": "a wrong upstream path or an extra or missing param",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"sends a refresh that times out at the proxy to the Engine once\"",
            "assertion": ":85",
            "excludes": "a retry on timeout",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\"",
            "assertion": ":70",
            "excludes": "a wrong path, or params added or dropped",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the browser gets the Engine's 200 body\"",
            "assertion": ":68",
            "excludes": "status-only passthrough, or a rewritten or filtered body",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"plus `user_id`, plus `refresh_cache`, or with `id` repeated each answers 400\"",
            "assertion": ":67",
            "excludes": "any of the three being accepted, or answering 404",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"and reaches the Engine not at all\"",
            "assertion": ":70",
            "excludes": "forwarding a refused request. The refused ones are sent first, so a forwarded one would add an entry to the exact list",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\"",
            "assertion": ":84",
            "excludes": "the per-route timeout being ignored, so 200 comes back under the 10 s default",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"and the Engine saw it once\"",
            "assertion": ":85",
            "excludes": "a retry. The retry would land before the 502 is written, so the snapshot at :80 would hold two entries",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`/api/video` \u2026 answers 502 after two attempts\"",
            "assertion": ":87",
            "excludes": "retries dropped for every route rather than only for the refresh",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\"",
            "assertion": ":70, :85",
            "excludes": "a stub that did not record the query would fail both exact comparisons. This sentence describes the harness",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a refresh reaches the engine with only id and host\"",
            "assertion": ":70",
            "excludes": "a wrong path, or extra or missing params",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"any other \u2026 key answers 400\"",
            "assertion": ":67",
            "excludes": "the `/api/video` allow-list being reused",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"or repeated key answers 400\"",
            "assertion": ":67",
            "excludes": "only a repeated `id` is excluded, and a repeated `host` is not (see C1e)",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a refresh that times out at the proxy\"",
            "assertion": ":84",
            "excludes": "the 10 s default letting the answer through as 200",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"is sent once\"",
            "assertion": ":85",
            "excludes": "a retry on timeout",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"and answered 502\"",
            "assertion": ":84",
            "excludes": "any status other than 502",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      },
      {
        "shape": "```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400\nfails at line 67 on `assert refused == [400, 400, 400, 400, 400]`, which reads\n[404, 404, 404, 404, 404]. client/backend/server.py has no `/api/video/refresh` entry in\n`PROXY_ALLOWED_QUERY_PARAMS` (lines 85-101) or in `PROXY_READ_GET_ROUTES` (lines 81-83),\nso the route is unrouted.\ntest_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84\non `assert refresh_status == 502`, which reads 404 for the same reason.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses no pytest fixture beyond the built-in\n   `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from\n   tests/active/conftest.py (lines 41-42), and `_client_backend`, `_serving` and `_status`\n   from tests/active/test_server.py (lines 347-378). All of these were read.\n   `ensure_user_schema` was not read. It only sets up the users DB and has no bearing on the\n   assertion form.\n2. The GET dispatch in client/backend/server.py that turns an unrouted path into 404 was not\n   read. The 404 in the predicted failure rests on two things: a Grep for \"refresh\" in\n   server.py matches only line 88 (the `/api/video` allow-list), and the test's own comment\n   at line 64 says 404 was observed.\n```",
        "claim": "CLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"forwards `/api/video/refresh`\" to the Engine | :70 | the request going to `/api/video` or another path, or never reaching the Engine | CARRIED |\n| C1b | must_prove | \"with only `id` and `host`\" | :70 | the proxy adding a param (such as `user_id`), dropping one, or changing a value. Exact dict equality with FORWARDED | CARRIED |\n| C1c | must_prove | \"refuses any other \u2026 query key with 400\" | :67 | the route reusing the `/api/video` allow-list (user_id, refresh_cache), accepting an unlisted key (`foo`), or staying unrouted and answering 404 | CARRIED |\n| C1d | must_prove | \"refuses any \u2026 repeated query key with 400\": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` (`id=uuid-2&{QUERY}`, :65) | CARRIED |\n| C1e | must_prove | \"refuses any \u2026 repeated query key with 400\": `host` repeated | :67 | first-value-wins or last-value-wins handling of `host` (`{QUERY}&host=other.example`, :65, fifth element of the exact list) | CARRIED |\n| C2a | must_prove | a timed-out refresh \"is sent to the Engine once\" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |\n| C2b | must_prove | a timed-out refresh is \"answered 502\" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |\n| D1 | docstring | \"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\" | :70 | a wrong upstream path, or a param added or missing | CARRIED |\n| D2 | docstring | \"sends a refresh that times out at the proxy to the Engine once\" | :85 | a retry on timeout | CARRIED |\n| D3 | docstring | \"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\" | :70 | a wrong path, or params added or dropped | CARRIED |\n| D4 | docstring | \"the browser gets the Engine's 200 body\" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |\n| D5 | docstring | \"plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400\" | :67 | any of the five being accepted, or answering 404. Each one is a position in the exact list | CARRIED |\n| D6 | docstring | \"and reaches the Engine not at all\" | :70 | a refused request being forwarded. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |\n| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |\n| D8 | docstring | \"and the Engine saw it once\" | :85 | a retry. It would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |\n| D9 | docstring | \"`/api/video` \u2026 answers 502 after two attempts\" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |\n| D10 | docstring | \"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |\n| N1 | name | \"a refresh reaches the engine with only id and host\" | :70 | a wrong path, or extra or missing params | CARRIED |\n| N2 | name | \"any other \u2026 key answers 400\" | :67 | the `/api/video` allow-list being reused, or an unlisted key being accepted | CARRIED |\n| N3 | name | \"or repeated key answers 400\" | :67 | a repeated `id` or a repeated `host` being accepted under first-value-wins or last-value-wins | CARRIED |\n| N4 | name | \"a refresh that times out at the proxy\" | :84 | the 10 s default letting the answer through as 200 | CARRIED |\n| N5 | name | \"is sent once\" | :85 | a retry on timeout | CARRIED |\n| N6 | name | \"and answered 502\" | :84 | any status other than 502 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:3, :65\n   The C1e fix added an assertion. It did not narrow the prose. `{QUERY}&host=other.example` is now the fifth refused query at :65, and the exact-list equality at :67 carries it. The docstring also got wider: it now names `plus foo` and `with host repeated`. Both are in the D5 row and both are carried at :67.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   No ledger row covers this. Every accepted query has both `id` and `host` present with non-empty values. Nothing tests a query missing `id`, a query missing `host`, an empty value (`id=`), or an empty query string. `must_prove` says \"only `id` and `host`\" but not \"requires\", so this falls outside C1. Left for the reader to decide.\n3. surfaces / checkpoint_definition (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:76\n   The test patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` with `raising=False`. That name does not exist in client/backend/server.py yet: the only timeout global is `ENGINE_PROXY_TIMEOUT_SECONDS` at server.py:77, and `/api/video/refresh` is not in `PROXY_ALLOWED_QUERY_PARAMS` at server.py:85-99. The test therefore fixes the name the implementation has to read the per-route timeout from. If the implementation uses a different name, the patch does nothing, the 10 s default lets the 1.5 s answer through, and :84 fails. That is a false negative, not a false pass, so it does not weaken C2b.\n\nNOT ASSESSED\n1. The `client/backend/server.py` edits for this phase are not present yet (no refresh route and no per-route timeout mapping). I judged the bounds and abnormal paths against the code as it stands and against `must_prove`, not against the finished route.",
        "body": "### devsecops-test-shape-auditor\n\n```\nSHAPE AUDIT \u2014 VERDICT: PASS\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nPREDICTED FAILURE\ntest_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400\nfails at line 67 on `assert refused == [400, 400, 400, 400, 400]`, which reads\n[404, 404, 404, 404, 404]. client/backend/server.py has no `/api/video/refresh` entry in\n`PROXY_ALLOWED_QUERY_PARAMS` (lines 85-101) or in `PROXY_READ_GET_ROUTES` (lines 81-83),\nso the route is unrouted.\ntest_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84\non `assert refresh_status == 502`, which reads 404 for the same reason.\n\nNOT ASSESSED\n1. `fixtures_path` was not supplied. The test uses no pytest fixture beyond the built-in\n   `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from\n   tests/active/conftest.py (lines 41-42), and `_client_backend`, `_serving` and `_status`\n   from tests/active/test_server.py (lines 347-378). All of these were read.\n   `ensure_user_schema` was not read. It only sets up the users DB and has no bearing on the\n   assertion form.\n2. The GET dispatch in client/backend/server.py that turns an unrouted path into 404 was not\n   read. The 404 in the predicted failure rests on two things: a Grep for \"refresh\" in\n   server.py matches only line 88 (the `/api/video` allow-list), and the test's own comment\n   at line 64 says 404 was observed.\n```\n\n### devsecops-test-claim-auditor\n\nCLAIM AUDIT \u2014 VERDICT: PASS\n\nCLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)\n| id | source | clause | assertion | excludes | status |\n|---|---|---|---|---|---|\n| C1a | must_prove | \"forwards `/api/video/refresh`\" to the Engine | :70 | the request going to `/api/video` or another path, or never reaching the Engine | CARRIED |\n| C1b | must_prove | \"with only `id` and `host`\" | :70 | the proxy adding a param (such as `user_id`), dropping one, or changing a value. Exact dict equality with FORWARDED | CARRIED |\n| C1c | must_prove | \"refuses any other \u2026 query key with 400\" | :67 | the route reusing the `/api/video` allow-list (user_id, refresh_cache), accepting an unlisted key (`foo`), or staying unrouted and answering 404 | CARRIED |\n| C1d | must_prove | \"refuses any \u2026 repeated query key with 400\": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` (`id=uuid-2&{QUERY}`, :65) | CARRIED |\n| C1e | must_prove | \"refuses any \u2026 repeated query key with 400\": `host` repeated | :67 | first-value-wins or last-value-wins handling of `host` (`{QUERY}&host=other.example`, :65, fifth element of the exact list) | CARRIED |\n| C2a | must_prove | a timed-out refresh \"is sent to the Engine once\" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |\n| C2b | must_prove | a timed-out refresh is \"answered 502\" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |\n| D1 | docstring | \"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\" | :70 | a wrong upstream path, or a param added or missing | CARRIED |\n| D2 | docstring | \"sends a refresh that times out at the proxy to the Engine once\" | :85 | a retry on timeout | CARRIED |\n| D3 | docstring | \"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\" | :70 | a wrong path, or params added or dropped | CARRIED |\n| D4 | docstring | \"the browser gets the Engine's 200 body\" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |\n| D5 | docstring | \"plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400\" | :67 | any of the five being accepted, or answering 404. Each one is a position in the exact list | CARRIED |\n| D6 | docstring | \"and reaches the Engine not at all\" | :70 | a refused request being forwarded. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |\n| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |\n| D8 | docstring | \"and the Engine saw it once\" | :85 | a retry. It would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |\n| D9 | docstring | \"`/api/video` \u2026 answers 502 after two attempts\" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |\n| D10 | docstring | \"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |\n| N1 | name | \"a refresh reaches the engine with only id and host\" | :70 | a wrong path, or extra or missing params | CARRIED |\n| N2 | name | \"any other \u2026 key answers 400\" | :67 | the `/api/video` allow-list being reused, or an unlisted key being accepted | CARRIED |\n| N3 | name | \"or repeated key answers 400\" | :67 | a repeated `id` or a repeated `host` being accepted under first-value-wins or last-value-wins | CARRIED |\n| N4 | name | \"a refresh that times out at the proxy\" | :84 | the 10 s default letting the answer through as 200 | CARRIED |\n| N5 | name | \"is sent once\" | :85 | a retry on timeout | CARRIED |\n| N6 | name | \"and answered 502\" | :84 | any status other than 502 | CARRIED |\n\nCRITICAL\nnone\n\nRECOMMENDATIONS\nnone\n\nOBSERVATIONS\n1. whole-claim (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:3, :65\n   The C1e fix added an assertion. It did not narrow the prose. `{QUERY}&host=other.example` is now the fifth refused query at :65, and the exact-list equality at :67 carries it. The docstring also got wider: it now names `plus foo` and `with host repeated`. Both are in the D5 row and both are carried at :67.\n2. bounds (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:65\n   No ledger row covers this. Every accepted query has both `id` and `host` present with non-empty values. Nothing tests a query missing `id`, a query missing `host`, an empty value (`id=`), or an empty query string. `must_prove` says \"only `id` and `host`\" but not \"requires\", so this falls outside C1. Left for the reader to decide.\n3. surfaces / checkpoint_definition (rules/testing.md) \u2014 tests/tmp/test_11_fast_similars_response_phase3.py:76\n   The test patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` with `raising=False`. That name does not exist in client/backend/server.py yet: the only timeout global is `ENGINE_PROXY_TIMEOUT_SECONDS` at server.py:77, and `/api/video/refresh` is not in `PROXY_ALLOWED_QUERY_PARAMS` at server.py:85-99. The test therefore fixes the name the implementation has to read the per-route timeout from. If the implementation uses a different name, the patch does nothing, the 10 s default lets the 1.5 s answer through, and :84 fails. That is a false negative, not a false pass, so it does not weaken C2b.\n\nNOT ASSESSED\n1. The `client/backend/server.py` edits for this phase are not present yet (no refresh route and no per-route timeout mapping). I judged the bounds and abnormal paths against the code as it stands and against `must_prove`, not against the finished route.",
        "map": [
          {
            "id": "C1a",
            "source": "must_prove",
            "clause": "\"forwards `/api/video/refresh`\" to the Engine",
            "assertion": ":70",
            "excludes": "the request going to `/api/video` or another path, or never reaching the Engine",
            "status": "CARRIED"
          },
          {
            "id": "C1b",
            "source": "must_prove",
            "clause": "\"with only `id` and `host`\"",
            "assertion": ":70",
            "excludes": "the proxy adding a param (such as `user_id`), dropping one, or changing a value. Exact dict equality with FORWARDED",
            "status": "CARRIED"
          },
          {
            "id": "C1c",
            "source": "must_prove",
            "clause": "\"refuses any other \u2026 query key with 400\"",
            "assertion": ":67",
            "excludes": "the route reusing the `/api/video` allow-list (user_id, refresh_cache), accepting an unlisted key (`foo`), or staying unrouted and answering 404",
            "status": "CARRIED"
          },
          {
            "id": "C1d",
            "source": "must_prove",
            "clause": "\"refuses any \u2026 repeated query key with 400\": `id` repeated",
            "assertion": ":67",
            "excludes": "first-value-wins or last-value-wins handling of `id` (`id=uuid-2&{QUERY}`, :65)",
            "status": "CARRIED"
          },
          {
            "id": "C1e",
            "source": "must_prove",
            "clause": "\"refuses any \u2026 repeated query key with 400\": `host` repeated",
            "assertion": ":67",
            "excludes": "first-value-wins or last-value-wins handling of `host` (`{QUERY}&host=other.example`, :65, fifth element of the exact list)",
            "status": "CARRIED"
          },
          {
            "id": "C2a",
            "source": "must_prove",
            "clause": "a timed-out refresh \"is sent to the Engine once\"",
            "assertion": ":85",
            "excludes": "the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice",
            "status": "CARRIED"
          },
          {
            "id": "C2b",
            "source": "must_prove",
            "clause": "a timed-out refresh is \"answered 502\"",
            "assertion": ":84",
            "excludes": "the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504",
            "status": "CARRIED"
          },
          {
            "id": "D1",
            "source": "docstring",
            "clause": "\"proxies GET `/api/video/refresh` to the Engine with only `id` and `host`\"",
            "assertion": ":70",
            "excludes": "a wrong upstream path, or a param added or missing",
            "status": "CARRIED"
          },
          {
            "id": "D2",
            "source": "docstring",
            "clause": "\"sends a refresh that times out at the proxy to the Engine once\"",
            "assertion": ":85",
            "excludes": "a retry on timeout",
            "status": "CARRIED"
          },
          {
            "id": "D3",
            "source": "docstring",
            "clause": "\"`?id=\u2026&host=\u2026` reaches the Engine as `/api/video/refresh` with exactly those two params\"",
            "assertion": ":70",
            "excludes": "a wrong path, or params added or dropped",
            "status": "CARRIED"
          },
          {
            "id": "D4",
            "source": "docstring",
            "clause": "\"the browser gets the Engine's 200 body\"",
            "assertion": ":68",
            "excludes": "status-only passthrough, or a rewritten or filtered body",
            "status": "CARRIED"
          },
          {
            "id": "D5",
            "source": "docstring",
            "clause": "\"plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400\"",
            "assertion": ":67",
            "excludes": "any of the five being accepted, or answering 404. Each one is a position in the exact list",
            "status": "CARRIED"
          },
          {
            "id": "D6",
            "source": "docstring",
            "clause": "\"and reaches the Engine not at all\"",
            "assertion": ":70",
            "excludes": "a refused request being forwarded. The refused ones are sent first, so a forwarded one would add an entry to the exact list",
            "status": "CARRIED"
          },
          {
            "id": "D7",
            "source": "docstring",
            "clause": "with the route timeout at 0.3 s and a 1.5 s Engine, \"the refresh answers 502\"",
            "assertion": ":84",
            "excludes": "the per-route timeout being ignored, so 200 comes back under the 10 s default",
            "status": "CARRIED"
          },
          {
            "id": "D8",
            "source": "docstring",
            "clause": "\"and the Engine saw it once\"",
            "assertion": ":85",
            "excludes": "a retry. It would land before the 502 is written, so the snapshot at :80 would hold two entries",
            "status": "CARRIED"
          },
          {
            "id": "D9",
            "source": "docstring",
            "clause": "\"`/api/video` \u2026 answers 502 after two attempts\"",
            "assertion": ":87",
            "excludes": "retries dropped for every route rather than only for the refresh",
            "status": "CARRIED"
          },
          {
            "id": "D10",
            "source": "docstring",
            "clause": "\"a real Client backend \u2026 in front of a stub Engine that records each GET's path and query\"",
            "assertion": ":70, :85",
            "excludes": "a stub that did not record the query would fail both exact comparisons. This sentence describes the harness",
            "status": "CARRIED"
          },
          {
            "id": "N1",
            "source": "name",
            "clause": "\"a refresh reaches the engine with only id and host\"",
            "assertion": ":70",
            "excludes": "a wrong path, or extra or missing params",
            "status": "CARRIED"
          },
          {
            "id": "N2",
            "source": "name",
            "clause": "\"any other \u2026 key answers 400\"",
            "assertion": ":67",
            "excludes": "the `/api/video` allow-list being reused, or an unlisted key being accepted",
            "status": "CARRIED"
          },
          {
            "id": "N3",
            "source": "name",
            "clause": "\"or repeated key answers 400\"",
            "assertion": ":67",
            "excludes": "a repeated `id` or a repeated `host` being accepted under first-value-wins or last-value-wins",
            "status": "CARRIED"
          },
          {
            "id": "N4",
            "source": "name",
            "clause": "\"a refresh that times out at the proxy\"",
            "assertion": ":84",
            "excludes": "the 10 s default letting the answer through as 200",
            "status": "CARRIED"
          },
          {
            "id": "N5",
            "source": "name",
            "clause": "\"is sent once\"",
            "assertion": ":85",
            "excludes": "a retry on timeout",
            "status": "CARRIED"
          },
          {
            "id": "N6",
            "source": "name",
            "clause": "\"and answered 502\"",
            "assertion": ":84",
            "excludes": "any status other than 502",
            "status": "CARRIED"
          }
        ],
        "map_problem": ""
      }
    ]
  },
  "refactors": "<refactors>\nengine/server/api/handlers/video.py: added a module-level `pick_present(value, fallback)` helper, placed with `pick_text`/`pick_number`, which returns the fallback only when the value is None. `merge_video_metadata` now uses it in place of the seven hand-written `x = dynamic.get(k); if x is None: x = row.get(k)` blocks (views, likes, dislikes, channel_followers, tags_json, category, nsfw). Each field falls back the same way as before: `is None` for these seven, `or` for title, description, channel_display and channel_slug. The operator confirmed this refactor before I made it.\n</refactors>\n\n<left_out>\nThe dead `channel_detail = None` line in `fetch_instance_video_dynamic`. It was there before this build and no phase touched it, so I left it alone. I did not run the gating checkpoints after the helper refactor. The fallback cases in tests/tmp/test_11_fast_similars_response_phase1.py (case b) and phase 2 (the no-write merge) cover it, and the workflow's run will confirm it. client/backend/server.py, similar.py and handlers/__init__.py: I found nothing to refactor; the per-path timeout/retry lookups and the new dispatch branch are already as small as they can be. There are leftover probe files in tests/tmp (probe_11_video_metadata.py, probe_11_remediation.py, probe_11_phase2.py, probe_11_phase3.py, probe_11_phase3_selfcheck.py, probe_11_d11.py) that still need deleting. I have no delete tool, and they are outside this step's files. tests/active/test_video_metadata.py does not exist yet. It is where the phase 1 and 2 checkpoints get promoted, so it is not mine to write.\n</left_out>\n\n<needs_fresh_red>\nnone\n</needs_fresh_red>\n\n<observation>\nThe only refactor that paid its way was folding seven identical `is None` fallbacks in merge_video_metadata into one helper. The merge rules are unchanged: 0 and 0/1 values are kept, and title, description and channel names still use `or`. Everything else that landed was already minimal, and the step's rules placeholder was blank, so I measured the pass against the role's rules with operator consent.\n</observation>"
}
```
dev-flow:state -->

## 2026-09-27 - Step 0 - baseline

Resolved paths: {
  "active": "tests/active",
  "working": "tests/tmp",
  "plans": "docs/project/plans",
  "delete_me": "delete_me",
  "archive": "tests/archive",
  "project_dir": "/home/enduser/code/PeerTube-browser/.worktrees/11",
  "record": "tests/last_test_validation.json",
  "output": "tests/last_test_output.txt"
}

Pre-build suite exited 0. Baseline variant: False.

```
selected 1 of 23 test groups (22 unchanged):
  test_search_fusion.py — no map entry
  test_search_fusion.py  10 passed                              1.8s
  ---------------------
  total                  10 passed                              2.0s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 1 - Gather requirements

Approved by the operator.

### requirements

### Purpose

Nothing on the video page (`client/frontend/video-page.html`, `client/frontend/src/pages/video-page/index.ts`) waits on the source PeerTube instance. Similar videos and the current video's stored metadata render immediately from the Engine's local DB; a separate refresh request fetches live metadata from the instance, persists it to the Engine DB, and updates the page when it arrives. Operator chose the "two-phase metadata" reading of the issue.

### Findings from the tree that shape this build

- The page already starts `loadVideo()` and `loadSimilarVideos()` in parallel, and the similars route (`/recommendations`, proxied by `client/backend/server.py` to the Engine's `_handle_similar` in `engine/server/api/handlers/similar.py`) is served from ANN/cache/DB without contacting the instance. Both the Client backend and the Engine are `ThreadingHTTPServer`, so the two requests do not serialise. The "similars first" part of the issue is therefore already mostly true; what stays empty is the current video's own panel.
- `loadVideo()` renders nothing until metadata arrives. The Engine's `handle_video_request` (`engine/server/api/handlers/video.py`) reads the DB row, then synchronously calls the instance (`fetch_instance_video_dynamic`: `/api/v1/videos/{id}` then `/api/v1/video-channels/{slug}`, `timeout=8` each), merges, writes the DB, then responds. The Client backend proxy (`ENGINE_PROXY_TIMEOUT_SECONDS = 10`) can time out first, after which the browser falls back to `fetchVideoMetadataFromInstance` (another instance wait). Even on success, `fetchVideoMetadataFromServer` awaits the browser-side `fetchInstanceMetadata` (`https://{host}/api/v1/config`) before rendering.
- The DB row (`fetch_video_row`) already holds title, description, embed_path, video_url, channel (name/url/display name/followers/avatar), account name/url, views, likes, dislikes and published_at: enough to render the panel immediately.
- The Client backend allow-list `PROXY_ALLOWED_QUERY_PARAMS["/api/video"]` already lists `refresh_cache`, which the Engine's video handler ignores today.

### R1 - Fast metadata from the DB

The Engine's `GET /api/video` answers from the DB row only; it makes no instance call and performs no DB write. The response keeps its current JSON shape and field names (`videoUuid`, `title`, `description`, `channelName`, `channelUrl`, `channelAvatarUrl`, `subscribersCount`, `instanceName`, `instanceUrl`, `accountName`, `accountUrl`, `accountAvatarUrl`, `embedUrl`, `originalUrl`, `views`, `likes`, `dislikes`, `publishedAt`), each filled from the DB with the same fallbacks as today (e.g. channel URL built from slug + host, original URL built from uuid/id + host). Fields only the instance supplies today (e.g. `accountAvatarUrl`) are empty or DB-sourced. A missing row still answers 404 `{"error": "Video not found"}`; a missing id still answers 400.

### R2 - Separate refresh request

A separate Engine route performs the live refresh, and the Client backend proxies it with its own query-parameter allow-list (same sanitising rules as the other read proxies). It:
- resolves the row exactly as `/api/video` does (404 if absent);
- fetches from the instance with today's behaviour: `timeout=8`, catching `HTTPError`/`URLError`/`TimeoutError`, field-by-field fallback to the DB row when the instance omits or fails a field;
- on a successful instance fetch, persists with today's writes: the `videos` UPDATE (title, description, channel_name, views, likes, dislikes, popularity via `compute_popularity`, tags_json, category, nsfw, last_checked_at), the `channels` UPDATE when `channel_id` is known, and the reset of `instances.last_error`/`last_error_at`/`last_error_source`; a `sqlite3.OperationalError` on write is logged and does not fail the response, as today;
- on a failed instance fetch writes nothing;
- returns the merged metadata in the same shape as `/api/video`.
This route is the single write path for per-request metadata refresh, so issue 10 (metadata completeness) can extend it later.

### R3 - Page flow and ordering

On load the page starts three independent requests: similars, fast metadata (R1), and refresh (R2); none awaits another. The video panel renders from whichever metadata response arrives first; when the refresh succeeds the panel re-renders with its values. Refreshed data always wins regardless of arrival order: a fast response arriving after the refresh must not overwrite refreshed values. If the refresh fails, errors or times out, the panel keeps what it shows and no error is shown to the visitor (a console warning is acceptable).

### R4 - No instance wait before first render

Nothing in the first render of the video panel awaits a request to the source instance. The browser-side `fetchInstanceMetadata` call (`/api/v1/config`, supplying instance name and avatar) moves off the first-render path; its values fill in when it resolves. Until then the instance chip shows the host with initials fallback, as it does today when that call fails.

### R5 - Video unknown to the Engine

When fast metadata answers 404 (or fails), the panel renders immediately from the URL params (`title`, `channel`, `channelUrl`, `embed`, `url`, `host`, as `fallback` holds them today), and the existing direct browser-to-instance fallback (`fetchVideoMetadataFromInstance`) fills it in when it arrives. The existing `https://`-only check on the embed URL is kept on every render path.

### R6 - Re-render safety

A re-render of the panel:
- does not reassign the embed iframe `src` when the embed URL is unchanged (playback must not restart);
- does not attach duplicate listeners to the like, dislike, block-channel or block-account buttons (the existing `dataset.wired` guards keep holding);
- does not fetch the visitor's reaction again once it has been fetched for the same video uuid/host;
- keeps escaping and `safeExternalUrl` on every value it writes, as today.

### R7 - Similars unchanged

Similars content, ranking, limit (8), the `localLikesImported` wait, profile-key handling and error display are unchanged. A test shows that a similars request is answered without contacting the source instance and is not delayed by a slow metadata/refresh call running concurrently.

### Constraints

- The refresh route's worst case on the instance is about 16 s (two sequential 8 s calls) while the Client proxy times out at 10 s. The design step must decide how the refresh fits that budget (for example a per-route proxy timeout, a shorter instance timeout, or a single overall budget) and state the choice; a proxy timeout on the refresh must degrade per R3 (panel keeps its values), never blank the page.
- Stdlib only on the Python side; no new frontend dependency. New code matches the style of the file it lands in.
- `client/frontend/dist/` is build output and is not hand-edited.

### Out of scope

- Rendering tags/category and refreshing further fields (issue `10-video-metadata-completeness`).
- Loading more similars on scroll / removing the similar-videos page (issue `12-similars-on-scroll`).
- Similars diversity (issue `09-similars-diversity`).

### Baseline suite state

Pre-build suite exited 0; baseline variant: false. Tests live in `tests/active` (working area `tests/tmp`).

### conflicts

Issue text "the server answers the similars request immediately... without waiting for the instance" vs the tree: similars (`/recommendations` → `_handle_similar`) already never contact the instance and already run in parallel with metadata; the actual blocking path is `/api/video` in `engine/server/api/handlers/video.py`. Resolved by the operator choosing the two-phase metadata reading (R1-R3).
R2 refresh worst case (~16 s: two sequential `timeout=8` instance calls in `fetch_instance_video_dynamic`) vs `ENGINE_PROXY_TIMEOUT_SECONDS = 10` in `client/backend/server.py`: the refresh can be cut off by the Client proxy; left to the design step as a stated constraint.

## 2026-09-27 - Step 2 - Develop a solution

Approved by the operator.

### initial_solution

### Approach

The Engine's single video handler becomes two routes over one merge step. On the frontend, `loadVideo` is split into a render function that can run more than once and a small coordinator that decides which result wins.

**Engine (`engine/server/api/handlers/video.py`, dispatch in `engine/server/api/handlers/similar.py`).** `handle_video_request` is split into three module-level functions in the file's existing style:
- a row resolver: id/host parsing, 400 on missing id, 404 `{"error": "Video not found"}` on a missing row, using `fetch_video_row` with `video_error_threshold` as today;
- a pure merge that takes the row, a `dynamic` dict and the instance domain, and returns the response dict. This is today's merge block unchanged: `dynamic`-or-row per field, channel URL from slug + host, original URL from uuid/id + host, embed from `embed_path`;
- a persist function holding today's three UPDATEs, its `sqlite3.OperationalError` catch and its log line, unchanged.

How each requirement is met:
- **R1.** `GET /api/video` = resolve, then merge with an empty `dynamic`. No `urlopen`, no write. Every field falls back to the DB exactly as today. `accountAvatarUrl` comes back empty because no DB column holds it.
- **R2.** A new `GET /api/video/refresh`, added next to the `/api/video` branch in `SimilarHandler`'s GET dispatch. It resolves the row the same way, calls `fetch_instance_video_dynamic` (unchanged: `timeout=8` per call, same exception set, same field picking), merges, persists only when the instance fetch succeeded, and responds with the same shape. This handler is the one per-request write path that issue 10 extends later.
- **Success signal (a gotcha found while reading).** `fetch_instance_video_dynamic` currently always returns a non-empty dict of keys, even when the detail call failed. Today's `if dynamic` guard is therefore always true, so today a failed fetch still writes DB values back, bumps `last_checked_at` and clears `instances.last_error`. R2 says a failed fetch writes nothing, so the function returns `{}` when the `/api/v1/videos/{id}` call itself returns `None`. Success means "the video detail came back". A failed channel sub-call still counts as success, with DB fallback for the channel fields, which matches the field-by-field rule. The function has no other callers; I grepped the tree.

**Client backend (`client/backend/server.py`).**
- `/api/video/refresh` is added to `PROXY_READ_GET_ROUTES`, so it gets the same rate limit and the same `_handle_engine_read_proxy_get` sanitising: unknown key → 400, repeated key → 400, values stripped.
- Its own `PROXY_ALLOWED_QUERY_PARAMS` entry is `{"id", "host"}`. `refresh_cache` stays on `/api/video`'s list, untouched.
- It is not in `FILTERED_ROUTES`, so it passes through `_profile_filter` untouched.

**Budget decision (the constraint).** The refresh route gets a per-route proxy timeout of 20 s and no proxy retry. Everything else keeps `ENGINE_PROXY_TIMEOUT_SECONDS = 10` and `ENGINE_PROXY_RETRY_COUNT = 1`. It is implemented as a small path→timeout mapping and a path check on the retry count inside `_proxy_engine_request`.
- The Engine's worst case of about 16 s (two sequential 8 s calls) fits, so R2 keeps today's instance timeouts literally.
- Dropping the retry matters as much as the timeout. Today a transport timeout is retried, which on this route would fire a second pair of instance calls and possibly a second write.
- If the proxy still gives up, the browser gets the proxy's usual failure status. R3 treats that as a failed refresh: the panel keeps its values and a console warning is logged.
- The Engine thread carries on and may still persist the result, which is harmless and even useful for the next visit.

**Frontend (`client/frontend/src/pages/video-page/index.ts`).**
- `loadVideo` becomes `renderVideo(metadata)`: today's body, minus the fetching.
- A coordinator starts three things at load, none awaiting another:
  - the fast `/api/video` fetch;
  - the `/api/video/refresh` fetch;
  - one shared `fetchInstanceMetadata(host)` promise.
  `loadSimilarVideos()` stays exactly as it is.
- **R3 ordering.** Each metadata source carries a rank: URL params 0, fast DB 1, direct browser-to-instance fallback 2, refresh 3. A result renders only if its rank is at least the rank currently shown. A late fast response therefore never overwrites refreshed values, whatever the arrival order. A failed or non-OK refresh logs `console.warn` and changes nothing.
- **R4.** `fetchVideoMetadataFromServer` no longer awaits `fetchInstanceMetadata`. When the shared instance promise resolves, its avatar (and its name, where today's precedence lets the name through) is stored and the current best metadata is re-rendered. Until then the instance chip shows the host with initials, as it does today when `/api/v1/config` fails. Today's precedence is kept: the Engine's `instanceName`/`instanceUrl` win over the config values, and only the avatar is new. The direct-instance fallback also stops awaiting `fetchInstanceMetadata` and uses the shared promise.
- **R5.** If the fast fetch returns non-OK or throws, the panel renders at once from `fallback` (rank 0). `fetchVideoMetadataFromInstance` then runs, and its result renders at rank 2 when it arrives. The `https://` check on the embed stays inside `renderVideo`, so every path passes through it.
- **R6.**
  - A module-level `lastEmbed` holds the last embed string assigned; `src` is set only when the checked embed differs from it. The comparison is against our own string, not `embedEl.src`, which the browser normalises.
  - The block and like buttons keep their `dataset.wired` guards.
  - `loadReaction` is gated by a `uuid|host` key of the last reaction fetched, so re-renders do not fetch it again for the same video.
  - Escaping and `safeExternalUrl` stay on every write because the rendering code itself is not changed.
- **R7.** Similars code is untouched. The new test starts the Engine handler over a fixture DB with `fetch_instance_json` patched to block for several seconds. It fires a refresh and then a similars request concurrently, and asserts the similars answer arrives well inside that delay with the instance stub never called by it.

Files touched: `engine/server/api/handlers/video.py`, `engine/server/api/handlers/similar.py` (one dispatch branch), `client/backend/server.py`, `client/frontend/src/pages/video-page/index.ts`, and `engine/server/README.md` (route list). `dist/` is regenerated by the build, not edited.

### Alternatives considered

- **Keep one `/api/video` with a `refresh_cache` flag, since the allow-list already carries it.** Rejected: R2 asks for a separate route. A flag would also give one route two latency profiles, so a proxy timeout could not be tuned per behaviour.
- **Refresh in the background inside the Engine after `/api/video` answers from the DB, with the page polling or calling again.** Rejected: it needs a thread or queue and a second read to see the result, where one extra request already carries the data.
- **Shorten the instance timeouts, or give the Engine one overall deadline of about 9 s across both calls, so the refresh fits the existing 10 s proxy timeout.** This keeps the proxy uniform. Rejected because R2 fixes `timeout=8` as today's behaviour, and the refresh is off the render path, so waiting longer costs the visitor nothing. It remains the upgrade if long-held threads ever matter.
- **Render from the URL params at t=0, before any response.** Rejected: the `?embed=` value and the DB `embed_path` can differ textually, which would reload the iframe moments later. R3 also says the first render comes from a metadata response. The URL-param render happens only when the fast call fails, as R5 says.
- **Extract the rank arbitration into a shared lib module for testability.** Not chosen by default: it has one caller. Tests can drive the page in node with a stubbed `document`/`fetch`, the same way `test_frontend_blocks.py` stubs the platform. If that proves too heavy, the test step may justify extracting the helper.

### Risks, gotchas and limitations

- `urlopen(timeout=8)` bounds each socket operation, not the whole call. A slowly dripping instance can take longer than 16 s. The 20 s proxy timeout caps what the browser waits, and R3's degrade covers it.
- Each page view now holds a Client thread and an Engine thread for up to about 20 s on a slow instance, instead of up to 10 s plus a retry. Both servers are `ThreadingHTTPServer` with unbounded threads, so this costs memory, not correctness.
- Each page view now makes two Client→Engine metadata requests, so it spends two rate-limit tokens instead of one. The refresh has its own per-path bucket, so it does not eat into `/api/video`'s.
- The fast path no longer bumps `last_checked_at`; only a successful refresh does. Nothing I read keys on it per request, but a worker that relies on it would see fewer bumps. They would now be honest ones, because today it is bumped even on failure.
- The first-wired closures keep the first known video: the reaction listener captures the first `reactionVideo()`, and `enableBlockButtons` the first uuid. Re-renders do not rewire them. This is unchanged from today, but it becomes visible only if a later source reports a different uuid than the first, which should not happen for one row.
- Avatar `innerHTML` is rewritten on every re-render, so the images may flicker once. This is cosmetic; skipping unchanged avatars is a trivial follow-up if it shows.
- If the fast call fails but the refresh succeeds, for example on a transient proxy error, rank 3 wins as intended, and the direct-instance fallback's later result is ignored.

### Tradeoffs the operator is asked to accept

- A refresh against a slow or dead instance can keep a request open for up to 20 s, and the proxy does not retry it. This is the price of keeping today's 8 s per-call instance timeouts inside R2.
- `accountAvatarUrl` is empty on first render and appears only after a successful refresh, because the DB has no column for it. Adding one is issue-10 territory.
- A failed instance fetch no longer clears `instances.last_error` or bumps `last_checked_at`. This follows directly from R2 but changes today's accidental behaviour.

### conflicts

none

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request() (lines 208-361), split into a row resolver, a pure merge and a persist function">
**What changes.** The one function becomes three module-level helpers plus two thin route handlers.
- **Resolver.** It takes lines 210-224 as they are. `id` falls back to `video_id` and `host` falls back to `instance_domain`. It answers 400 `{"error": "Missing video id"}` and 404 `{"error": "Video not found"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` under `server.db_lock`.
- **Merge.** It takes lines 226-290, with `dynamic` passed in. `instance_domain = row.get("instance_domain") or host_param or ""` must be computed in the resolver or passed to the merge, because the merge needs it and so does persist (`WHERE instance_domain = ?`).
- **Persist.** It takes lines 292-358. It needs the merged locals as well as the response dict: `title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, plus `row["video_id"]`, `row["channel_id"]` and `row["published_at"]`. The response dict does not carry `channel_slug`, `tags_json`, `category` or `nsfw`, and `channelName` is `channel_display or ""`, not `None`. So persist cannot be fed from the response alone: either the merge returns the intermediate values too, or persist re-derives them. That is a design detail the plan leaves open.
- **`/api/video`.** Resolve, merge with `{}`, respond. No `urlopen`, no write.
- **`/api/video/refresh`.** Resolve, call `fetch_instance_video_dynamic`, merge, persist only when that returns non-empty, respond.
- The module docstring (lines 1-7: "Merge DB metadata with live instance metadata") should say which route does what.

**What depends on it.** `handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else imports it (grep over the tree). No test in `tests/active` touches this module or `/api/video` (grep: only the smoke scripts do).

**Regression risk: medium.**
- **R1 field parity.** With `dynamic = {}`, every field falls back exactly as today, because each `dynamic.get(...)` is `None`. `accountAvatarUrl` becomes `""` for every fast response. `accountName` and `accountUrl` already come only from the row today, even when the instance returns them (lines 281-282 ignore `dynamic["account_name"]` and `dynamic["account_url"]`). That stays.
- **The db_lock boundary.** The resolver must release `server.db_lock` before the instance call, as today (the lock covers lines 215-221 only). If the refactor fetched inside the `with server.db_lock:` block, every Engine request, similars included, would block for up to about 16 s. That would break R7.
- **The row read and the write are not atomic.** The row is read at resolve time and written after the instance call. A concurrent refresh of the same video may interleave, and the last writer wins. That is harmless: both write instance data.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails">
**What changes.** Line 164 currently reads `detail = fetch_instance_json(...) or {}`. It becomes: if `fetch_instance_json` returns `None`, return `{}` at once. Everything else stays the same.

**Why this matters.** I confirmed the plan's gotcha. The function today always returns a 14-key dict, so `if dynamic` at line 293 is always true, and a failed fetch writes DB values back, bumps `last_checked_at` and clears `instances.last_error*`.

**Edge cases.**
- **Truthy non-dict JSON.** `fetch_instance_json` returns whatever `json.loads` yields. A 200 with a JSON array or a string would reach `.get` and raise `AttributeError`, which is not caught. That is pre-existing. The plan's success test should probably be "`isinstance(detail, dict)`" rather than "is not None", or a non-dict 200 now crashes the refresh handler. It crashes today too.
- **An empty dict `{}` from the instance** counts as a "success" under a `None` check but carries no data. Persist would then write the DB values back and clear `last_error`. This is minor. Stating the success rule as "a non-empty dict came back" closes it.

**What depends on it.** Only `handle_video_request` today, and the refresh route after the build (grep: no other callers in `engine/`, and none in tests). The channel sub-call (line 176) still runs only when `channel_slug` came back, so it runs only on success.

**Regression risk: low.** It is the one behavioural change to the persist trigger. It means a failed refresh no longer clears `instances.last_error` (a tradeoff the operator accepts).
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_json() (lines 75-87): unchanged, but it is the test seam and its exception set is narrow">
**What changes.** Nothing. The R7 test patches it to block.

**What depends on it.** Both instance calls in `fetch_instance_video_dynamic`.

**Regression risk: none in code, but note the error path.**
- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` does not catch:
  - `json.JSONDecodeError` from a non-JSON 200;
  - `ConnectionResetError` or `http.client.RemoteDisconnected` during `resp.read()`;
  - `UnicodeDecodeError`.
- **Consequence on the refresh route.** These propagate out of the handler. `do_GET`'s wrapper (`similar.py:433-441`) re-raises everything except an interrupted `OperationalError`, so the socketserver drops the connection with no response. The Client proxy then sees `RemoteDisconnected`: not a `URLError`, so it goes through the generic `except Exception` branch and answers 502 `ENGINE_PROXY_FAILURE`.
- **R3 is still met.** A non-OK refresh changes nothing on the page, so the degrade holds. But the Engine logs a traceback per such instance. This is pre-existing (today the same exception kills `/api/video` itself, which is worse). After the split, `/api/video` can no longer hit it.
- **The patch target.** The R7 test must patch `handlers.video.fetch_instance_json`, the module attribute, because `fetch_instance_video_dynamic` looks it up as a global. Patching an imported alias would not take effect.
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline() / _deadline_passed() (lines 21-64), as it applies to the refresh's persist">
**What changes.** Nothing in code. The refresh route's timing makes it matter.

**How the deadline applies.**
- `SimilarHandler.do_GET` (`similar.py:433-441`) wraps the whole dispatch in `statement_deadline(server.statement_timeout_seconds)`. That is `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0` (`server_config.py:435`), a wall-clock deadline from the start of the request.
- The refresh reaches its three UPDATEs only after the instance calls, which can take up to about 16 s. By then the thread's deadline has usually passed.
- The progress handler, installed on `server.db` by `connect_db`, checks every 10,000 VM instructions. Any UPDATE statement that runs past that count after the deadline is aborted with `OperationalError: interrupted`.
- The `videos` UPDATE fires the `videos_fts_au` FTS trigger (`sync-whitelist.py:279`) on `whitelist.db`, which re-tokenises the title and description. That makes crossing 10,000 instructions plausible for long descriptions. I have not measured it.

**Consequence.**
- The persist's own `except sqlite3.OperationalError` (lines 352-358) catches the abort. It logs `[video] failed to persist dynamic metadata ... interrupted` at WARNING. `with server.db:` rolls back, and the response is still 200 with the refreshed values.
- So a slow instance's successful refresh may silently not persist. That contradicts R2's "on a successful instance fetch, persists".
- This is pre-existing today, but today it is masked. After the build, the refresh is the only writer, so the gap is what the build is judged on.

**Options for the design step.**
- Run persist under its own fresh `statement_deadline(...)`. It nests and restores (lines 59-64).
- Or accept the gap and state it.

**Regression risk: medium to high for R2's persist guarantee. I am uncertain whether a single-row UPDATE plus the FTS trigger actually reaches 10,000 instructions; a test with a `time.sleep` stub longer than 5 s would show it.**
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_get() /api/video branch (lines 495-497), the import at line 84, and the module docstring route list (lines 3-13)">
**What changes.**
- A new `if url.path == "/api/video/refresh":` branch goes beside line 495. It calls the new refresh handler.
- The line-84 import gains the new function name.
- The docstring gains `- /api/video/refresh: live instance refresh of one video's metadata (writes the DB).`

**What depends on it.**
- **Rate limiting.** Line 447 rate-limits every `/api/` path per `f"{ip}:{path}"` (`_rate_limit_check`, lines 576-583), with `DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60` per 60 s. The refresh therefore gets its own bucket and does not consume `/api/video`'s, as the plan says. The key uses `X-Client-IP`, which the Client forwards (`client/backend/server.py:590`).
- **Exact matching.** The branch compares with `==`, and the similar-path extractor (line 499) only matches `/videos/.../similar`. So `/api/video/refresh` would otherwise fall to the 404 at line 508. Nothing else shadows it.
- **Statement deadline.** Both routes run inside `do_GET`'s statement deadline (see the `db.py` entry).

**Regression risk: low.** It is one branch. The similars dispatch is untouched, which keeps R7.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring (line 5: 'video: fetches video metadata for /api/video')">
**What changes.** The docstring line should name both routes, e.g. `video: /api/video (DB metadata) and /api/video/refresh (live instance refresh, persisted).`

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer attributes used by the video handlers: db, db_lock, video_error_threshold (230, 264), popularity_like_weight (234, 268), statement_timeout_seconds (272); ThreadingHTTPServer base (207)">
**What changes.** Nothing.

**What depends on it.**
- The resolver reads `server.video_error_threshold`.
- Persist reads `getattr(server, "popularity_like_weight", 2.0)`, plus `server.db` and `server.db_lock`.
- `SimilarServer` is a `ThreadingHTTPServer`, so a refresh blocked on an instance holds one thread and not the server. R7 relies on this.

**Test note.** A child-process test that builds a stub server must supply `db`, `db_lock` and `video_error_threshold`, and `popularity_like_weight` if persist runs. The `test_internal_events.py:51-52` pattern builds the real `SimilarServer` with `None` for every other argument and would work.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/popularity.py" element="compute_popularity(), called by persist">
**What changes.** Nothing. It moves with the persist block, and its arguments stay `views`, `likes`, `row["published_at"]`, the like weight and `now_ms_value=checked_at`.

**What depends on it.** It is the `videos.popularity` column that ranking reads.

**Regression risk: low.** The merged `views`/`likes` (instance value or DB fallback) must still be what persist passes, not the response's.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts_au AFTER UPDATE trigger (line 279) on whitelist.db">
**What changes.** Nothing.

**What depends on it.** Each successful refresh's `videos` UPDATE fires the trigger and re-indexes the title and description for search. Fewer writes now happen per page view: only successful refreshes, where today every view wrote, even on failure. So FTS churn goes down.

**Regression risk: none in code.** It is relevant to the statement-deadline entry.
</impact>
<impact path="engine/server/data/metadata.py" element="readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301) and data/search.py (80)">
**What changes.** Nothing.

**What depends on it.** These only project `last_checked_at` into rows. Nothing in `engine/server` selects or orders by it per request (grep). So the fast path no longer bumping it is invisible to serving.

**Regression risk: none.** The crawler and updater are outside this read of `engine/server`. The plan's "a worker that relies on it" risk is unverified for `engine/crawler`.
</impact>
<impact path="client/backend/server.py" element="PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)">
**What changes.**
- `"/api/video/refresh"` joins the frozenset.
- A new entry `"/api/video/refresh": {"id", "host"}` is added.
- `/api/video` keeps `{"id", "host", "refresh_cache", "user_id"}`.

**What depends on it.**
- `do_GET` (lines 277-282) routes on `url.path in PROXY_READ_GET_ROUTES`, applies `_rate_limit_check(url.path)` (`RATE_LIMIT_MAX_REQUESTS = 90` per 60 s, keyed `ip:path`, so the refresh has its own bucket), then calls `_handle_engine_read_proxy_get`.
- That function (417-436) answers 400 for an unknown key, 400 for a repeated key, and strips values.
- `_profile_filter` (438-469) returns `(True, None, None, None)` because the path is in neither `FEED_ROUTES` nor `FILTERED_ROUTES`. So there is no key check, and `X-Profile-Key` is ignored.
- The frontend must send only `id` and `host` to the refresh. Any `user_id` or `refresh_cache` would now be a 400.

**Regression risk: low.** It is a pure addition. Nothing reads these tables besides the two handlers.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() retry loop and timeout (lines 570-744), with ENGINE_PROXY_TIMEOUT_SECONDS / ENGINE_PROXY_RETRY_COUNT (77-80)">
**What changes.**
- A path→timeout mapping (e.g. a module constant `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS = {"/api/video/refresh": 20}`) is read with a default of `ENGINE_PROXY_TIMEOUT_SECONDS`.
- The retry count becomes per-path: 0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise.

**Sites that must use the per-path values.**
- `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)` (604).
- `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)` (606).
- `if attempt < ENGINE_PROXY_RETRY_COUNT` (696).
- The `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` field of the "proxy request unavailable" log (731). This one is easy to miss. A hard-coded constant there would log `attempts: 2` for a refresh that made one attempt.

**What depends on it.** Every proxied read: GET `/api/video`, `/api/channels` and `/api/v1/search/videos`; POST `/recommendations` and `/videos/similar`. They must keep 10 s and one retry.

**How a refresh timeout surfaces.**
- `urlopen`'s timeout is per socket operation. The Engine sends nothing until it has finished, so the read waits up to 20 s. The timeout surfaces as `TimeoutError` (`socket.timeout` is an alias on 3.10+), which lands in the `(URLError, TimeoutError)` branch.
- With 0 retries it breaks out to the 502 `ENGINE_PROXY_UNAVAILABLE` body, which still carries `detail: str(last_transport_error)`. That `detail` is pre-existing, flagged as unfinished by plan 15's refactor record; this build does not change it.
- A dropped Engine connection (`RemoteDisconnected`, see the `fetch_instance_json` entry) lands in the generic 502 branch.
- Both are non-OK for the browser, which is the R3 degrade.

**Test harness.** `test_server.py:400-422` shows the `EngineStub` plus `_client_backend` pattern for a stub that counts requests and sleeps. It is the natural harness for "refresh gets one attempt with a timeout of about 20 s; `/api/video` still gets two".

**Regression risk: medium.** This function is shared by every browser read. A mapping or path check that is wrong (for example keyed on the full upstream URL with its query string instead of `path`) would silently change the timeout or retry for all routes. The test must cover both the refresh and a non-refresh path.
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)">
**What changes.** Nothing.

**What depends on it.**
- The refresh passes through the same sanitising as the other read proxies.
- An empty value is dropped (line 431). A refresh with `id=` but no value therefore reaches the Engine without `id` and gets its 400 `Missing video id`, passed through by the HTTPError-with-payload branch (646-677).

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module top level: `void loadVideo()` (line 79), currentMetadata (50), fallback (57-63), seedId/seedHost (54-55)">
**What changes.** Line 79 becomes the coordinator start. `void loadSimilarVideos()` (80) stays as it is.

**What the coordinator must do.**
- **No usable source.** When `resolveVideoSource()` gives no host or id (`fetchVideoMetadata`, line 508, returns `null` today), today renders once with `metadata = null`, which is the URL-param fallback. The coordinator must keep that: no fetch, render the fallback.
- **Keep `currentMetadata` in step.** It must be set to the metadata actually rendered, the winning rank. `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost`.
- **Rank 0 is today's null render.** `renderVideo(null)` already takes every value from `fallback`, `seedHost` and `https://${seedHost}`. The plan's rank-0 render is therefore `renderVideo(null)`.

**What depends on it.** The DOM element constants (22-48) are resolved once at import. The module has top-level side effects: `document.getElementById`, `importLocalLikes`, `applyActionIcons` at 1226, and `window.location`. A node test that imports the page needs a stubbed `document`, `window.location.search`, `fetch`, `localStorage` and `Intl`. It also needs the `../../video.css` import handled: esbuild `--bundle` emits a css file beside the bundle, or use `--loader:.css=empty`.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo() (lines 85-229) becoming renderVideo(metadata)">
**What changes.** The body stays the same, minus `await fetchVideoMetadata()` and the `currentMetadata = metadata` assignment, which moves to the coordinator or stays at the top of the render. The render then runs once per accepted source, and again when the instance config arrives.

**Parts that re-run on every render.**
- **Text and markup writes** (title, channel `innerHTML` with `escapeHtml`/`safeExternalUrl`, subscribers, instance link, account link, description, views, counts, original link). These are idempotent.
- **The avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatar `innerHTML` (154-161, 179-186) are rewritten each time, followed by `bindAvatarFallback` on the fresh `<img>`s. The old `<img>` and its listener are discarded with the markup, so no listeners pile up. There is a possible one-time image flicker, as the plan says.
- **The embed (212-221).** Today it sets `embedEl.src = embed` unconditionally. The new `lastEmbed` guard must also be reset when the `else` branch calls `removeAttribute("src")`. Otherwise a later valid embed equal to the pre-removal string would never be reassigned.
- **`document.title` (114).** Rewritten each time.
- **`enableBlockButtons(...)` (196).** Guarded, see its entry.
- **`void loadReaction()` (197).** Needs the new gate, see its entry.

**Which fields change between sources.**
- The Engine returns `""` rather than null for empty strings. So `metadata?.title ?? fallback.title` yields `""`, and `titleEl` shows "Video page" via `title || "Video page"`, exactly as today.
- `embedUrl` from the fast and refresh routes is the same `resolve_asset_url(instance_domain, row.embed_path)` string. The embed guard therefore does not reload the iframe between rank 1 and rank 3.
- Rank 2 (`fetchVideoMetadataFromInstance`) builds `embedUrl` with `resolveApiAssetUrl`, which can differ textually from the `?embed=` fallback that rank 0 rendered. So one iframe reload between rank 0 and rank 2 is possible. That already happens today in effect, since today the page shows nothing until rank 2.

**Regression risk: medium.** The embed reload is what R6 names. The equality check must compare the exact string assigned, after the `https://` test.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)">
**What changes.**
- `fetchVideoMetadata`'s sequential "server, else instance" logic moves into the coordinator.
- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (line 525). It must serve both `/api/video` and `/api/video/refresh`, which means a path parameter or a shared response mapper. The refresh answers the same shape, so the mapping at 527-551 applies unchanged.

**Correction to the plan's R4 wording on instance-name precedence.**
- The Engine always sends `instanceName` and `instanceUrl` as strings: `instance_domain or ""` and `f"https://{instance_domain}"` or `""` (`video.py:279-280`).
- `??` does not skip `""`. So whenever the Engine answers, `instanceMeta?.name` never wins today, even when the Engine's value is empty.
- "Where today's precedence lets the name through" therefore means never, for ranks 1 and 3. The instance config supplies only `instanceAvatarUrl` there.
- For rank 2 (`fetchVideoMetadataFromInstance`, 608-610) the config's name and URL do win. The shared-promise merge must keep that distinction per source.
- If the implementation re-applies the config by overwriting `instanceName` unconditionally, the chip label would change from the host to the instance's display name on ranks 1 and 3. That is a visible behaviour change.

**Other effects.**
- The `catch { return null; }` (552-554) also swallows `response.json()` failures. For the refresh, the plan wants a `console.warn` on failure, so the refresh caller needs its own catch or a non-null error signal.
- Unmapped fields: `channelId` and other extra keys are ignored, as today.

**Regression risk: medium.** Precedence is subtle. `instanceAvatarUrl` must be merged in from the shared promise for every source, or the avatar disappears when a later rank re-renders without it.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)">
**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, since it is part of the rank-2 source itself.

**What it returns.** Its result has no `videoUuid`. After a rank-2 render, `currentMetadata.videoUuid` is therefore undefined, and `resolveLikeUuid` falls back to `seedId` only if it looks like a UUID (1151-1155, 1171-1173).

**Coordinator condition.** It runs only after the fast fetch fails, per R5. It should keep today's semantics: it runs only when the Engine did not give metadata.

**Regression risk: low to medium.** If rank 2 arrives after rank 3 (fast fails, refresh succeeds), the rank rule drops it. The plan acknowledges that.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchInstanceMetadata() (655-688) as a shared promise">
**What changes.** It is called once per page load and its promise is shared.

**What it returns.**
- On success it always returns an `avatarUrl`, falling back to `https://${host}/favicon.ico`, and a `name` (`getString` returns `""`, which `??` does not skip, so `name` can be `""`).
- On failure it returns `null`. Cross-origin `/api/v1/config` often fails CORS in browsers, which means the host initials stay; the plan calls this today's behaviour.

**What depends on it.** It feeds the instance chip avatar for all ranks, and the name and URL for rank 2 only (see the precedence entry). Its resolution triggers a re-render of the current best metadata at the same rank. So the rank rule must allow equal-rank re-renders, as the plan's "at least the rank currently shown" does.

**Regression risk: low.** The promise resolves to `null` rather than rejecting (internal catch), so a `.then` needs no `.catch`. It must not start before a host is known: use `resolveVideoSource().host`, as today's two call sites use `source.host`.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadReaction() (318-341) and reactionVideo() (381-386)">
**What changes.** The plan adds a gate: a module-level key `uuid|host` of the last reaction fetched, checked before `fetchReaction`.

**How the existing code behaves.**
- `reactionVideo()` depends on `currentMetadata`. On a rank-0 render (fast failed) with a numeric `seedId`, it returns `null`, so `loadReaction` returns early (320) without wiring the buttons. A later rank that carries a `videoUuid` (only rank 3; rank 2 has none) then fetches the reaction and wires the buttons. The gate key must therefore be set only when `video` is non-null, or the later fetch would be suppressed.
- The click listeners (331-340) capture the first non-null `video` and are never rewired, because of `likeButton.dataset.wired`. This is as the plan states.

**Interleaving.** `await localLikesImported` (322) and `fetchReaction` are async. Two quick renders could both pass a gate that is only written after the await, and fetch twice. So the key must be written before the first `await`.

**What depends on it.** `renderReaction` and `setReactionStatus`. `test_frontend_reactions.py` exercises `data/reactions.ts`, not this page, and is unaffected.

**Regression risk: medium.** The gate must be set synchronously and only for a non-null video. Otherwise R6 ("does not fetch the visitor's reaction again") fails, or the buttons stay disabled for pages whose uuid only arrives with the refresh.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="enableBlockButtons() (275-308)">
**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.

**What depends on it.**
- It captures `uuid` and `host` from the first call with both non-empty.
- On a rank-0 render, `metadata?.videoUuid || resolveVideoSource()?.id` gives `seedId`, which may be a numeric `video_id` rather than a uuid. The buttons are then wired with it for good. That already happens today when `/api/video` fails.
- It is more reachable now: if the fast call fails but the refresh later succeeds with the real uuid, the buttons keep the numeric id.
- The Client's block route resolves through the Engine (`/internal/videos/resolve` matches `video_id` or uuid), so a numeric id probably still works. I have not traced `blockVideoSource` to confirm.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (234-269), localLikesImported (75-77), similar stats helpers (866-1027)">
**What changes.** Nothing, per R7.

**What depends on it.** Its independence from the metadata flow is what R7 asserts. It waits only on `localLikesImported`, never on metadata.

**Regression risk: none,** as long as the coordinator does not await or chain it.
</impact>
<impact path="client/frontend/video-page.html" element="#video-embed iframe (32-36), #video-title placeholder (40), CSP meta (8), module script (112)">
**What changes.** Nothing.

**What depends on it.**
- The CSP's `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser→instance fetches.
- The static "Video page" title and the "Loading..." similars placeholder (106) show until the first render and the similars arrive.

**Regression risk: none.**
</impact>
<impact path="client/frontend/dist/assets/video-gjYm1MC8.js" element="built video page bundle (build output)">
**What changes.** It is regenerated by the frontend build with a new hash filename. It must not be edited by hand.

**What depends on it.** The deployed static site (`DEPLOYMENT.md` nginx root) serves `dist`. It contains `/api/video` today (grep hit).

**Regression risk: low.** A stale `dist` would deploy the old page against the new Engine. That old page still works, because `/api/video` keeps its shape; it just stops getting live values.
</impact>
<impact path="client/frontend/vite.config.ts" element="dev server proxy '/api' (lines 27-28)">
**What changes.** Nothing. The `/api` prefix proxy already covers `/api/video/refresh` in dev.

**Regression risk: none.** I did not check whether the proxy sets a timeout; Vite's http-proxy default has none.
</impact>
<impact path="DEPLOYMENT.md" element="nginx `location /api/` (lines 319-325) and the ufw note (lines 369-375)">
**What changes.**
- Nothing in the nginx block. `location /api/` already proxies `/api/video/refresh`, and nginx's default `proxy_read_timeout` of 60 s exceeds the 20 s refresh.
- The prose at 374-375 ("`/api/video` makes live calls to source instances per request") becomes wrong: it is now `/api/video/refresh`. See the docs checklist.

**Regression risk: none in config.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (line 106) over the shared WHITELIST_DB (line 34), ENGINE_PY (line 32), CLOSED_ENGINE (line 45)">
**What changes.** Nothing needs changing.

**What the new tests must avoid.**
- **Live refresh on the shared Engine.** Any refresh test through the session `engine` fixture would make real outbound HTTPS calls to source instances and write to the shared `whitelist.db`. The R2 and R7 tests must therefore run the Engine handler in an `ENGINE_PY` child over a temporary fixture DB, with `handlers.video.fetch_instance_json` patched. Precedents are `test_internal_client_reads.py:144-145`, `test_internal_events.py:42-60` and `test_similar.py`'s children.
- **Fast `/api/video` on the shared Engine.** Testing it there is safe after the build: it makes no calls and no writes. Before the build it would call instances.

**Regression risk: medium for test hygiene** if a new test calls the refresh against the shared Engine.
</impact>
<impact path="tests/active/test_server.py" element="EngineStub + _client_backend pattern (lines 359-422)">
**What changes.** Nothing. It is the template for the new proxy test.

**The new test.** A stub Engine that counts GETs and sleeps longer than 10 s on `/api/video/refresh` checks two things:
- a refresh gets one attempt and is still waited for within 20 s;
- `/api/video` still retries once.
A test that waits for real timeouts adds about 20 s or more to the suite. Monkeypatching the timeout mapping and constants on `client_server` keeps it fast.

**Other constraints.** `_status` uses `timeout=30` (375), so a 20 s proxy wait fits. The file is mapped to `client/backend/server.py` in `.un/skills/devsecops/config.json:57-58`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="esbuild + node runner pattern with stubbed platform (lines 22-85)">
**What changes.** Nothing. It is the precedent the plan names for driving the page in node.

**Why it does not transfer directly.** That test bundles data modules only. The video page module runs DOM code at import, and imports `../../video.css`. A page test needs:
- a fake `document` with `getElementById` returning stub elements (`innerHTML`, `textContent`, `hidden`, `dataset`, `classList`, `closest`, `querySelector`, `querySelectorAll`, `addEventListener`, `setAttribute`, `removeAttribute`, `insertAdjacentHTML`);
- `window.location.search`;
- a scripted `fetch`;
- a css loader flag.

**Regression risk: medium for test effort.** The plan allows extracting the rank helper instead if this is too heavy.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups mapping">
**What changes.** Nothing required during the build.

**At harvest.**
- `engine/server/api/handlers/video.py` and `client/frontend/src/pages/video-page/index.ts` are not mapped to any test group (grep found only `server.py` entries). New test files need entries.
- `test_server.py` is already mapped to `client/backend/server.py`.

**Regression risk: low.**
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647)">
**What changes.** Nothing required. `/api/video` still answers 200, and faster.

**Optional.** A `/api/video/refresh` status check could be added. It would make the smoke run depend on outbound 443 to a source instance, so a check for "200 or 502" is safer.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_STATEMENT_TIMEOUT_SECONDS (435), DEFAULT_RATE_LIMIT_* (431-432), DEFAULT_HIDE_BLOCKED_IN_VIDEO_API (455-456)">
**What changes.** Nothing.

**What depends on it.**
- The 5 s statement budget interacts with the refresh persist (see the `db.py` entry).
- The 60-per-60 s per-path Engine rate limit now applies separately to the refresh.
- `DEFAULT_HIDE_BLOCKED_IN_VIDEO_API` is an unused "future toggle" for `/api/video`. It is not referenced by `video.py` and stays unrelated.

**Regression risk: none.**
</impact>
<impact path="docs/project/security-audit/run-1/REPORT.md" element="line 299 ('/api/video performs up to two outbound HTTPS requests'); also run-1/architecture.md:67, run-2/REPORT.md:125,221">
**What changes.** Nothing. These are dated audit records and should not be rewritten.

**Why they are listed.** A grep for `/api/video` hits them, and they will describe the old behaviour.

**Regression risk: none.**
</impact>
</impacts>

### docs_checklist

<doc path="engine/server/README.md">
**"What it does" (line 9).** Replace the single `/api/video` bullet with two bullets:
- `/api/video`: the video page's metadata from the local DB only. It makes no instance call and no write. `accountAvatarUrl` is empty.
- `/api/video/refresh`: fetches the live metadata from the source instance. Each call has an 8 s socket timeout, and the video detail and channel lookups run in sequence. It answers the same shape. Only when the video detail call succeeds does it write the `videos`/`channels` UPDATE and reset `instances.last_error*`. A failed fetch writes nothing. It is the one per-request metadata write path.

**Line 3 ("Read-only Engine API").** This was already inaccurate, since `/api/video` wrote. It should say the refresh route writes metadata.
</doc><doc path="README.md">
Boundary table, rows at lines 46 and 48. Add `/api/video/refresh` to both route lists:
- "Public read API" (Engine);
- "Browser-facing read gateway" (Client backend).
</doc><doc path="client/README.md">
**Line 37, the read gateway list.** Add `/api/video/refresh`.

**Backend Responsibilities.** Optionally add one line: the refresh proxy allows only `id` and `host`, waits up to 20 s and is not retried; every other read proxy keeps 10 s with one retry.
</doc><doc path="client/frontend/README.md">
Line 8, the list of fetched gateway routes: add `/api/video/refresh`. Optionally add one sentence on how the video page loads:
- it renders from `/api/video` first;
- it re-renders when the refresh arrives;
- it falls back to the URL params and then the direct instance fetch when `/api/video` fails.
</doc><doc path="DEPLOYMENT.md">
Lines 374-375: "`/api/video` makes live calls to source instances per request" becomes `/api/video/refresh` (one live refresh per video page view). The ufw comment at line 369 ("live video metadata") stays true. The nginx block needs no change, because `location /api/` covers the new route.
</doc><doc path="docs/project/issues/10-video-metadata-completeness.md">
Line 22 ("a source metadata change is reflected after the next `/api/video` request") becomes the next `/api/video/refresh`. Line 16 ("the schema `/api/video` reads") stays true. The issue should also note that the refresh handler is now its single per-request write path.
</doc><doc path="docs/project/issues/11-fast-similars-response.md">
At harvest:
- set `Status: enhancement, complete`;
- record the two-phase reading and the 20 s / no-retry refresh budget;
- move the file to `docs/project/issues/archive/` per `docs/project/triage-labels.md`.
</doc>

### highest_risk

engine/server/data/db.py statement_deadline, applied to the new persist in engine/server/api/handlers/video.py: `do_GET` sets a 5 s wall-clock deadline at the start of the request, and the refresh reaches its UPDATEs only after instance calls that can take up to about 16 s. Any UPDATE that crosses 10,000 VM instructions after the deadline (the `videos_fts_au` FTS trigger makes that plausible) is aborted as `interrupted`. The abort is swallowed by the persist's own `OperationalError` catch, so a successful refresh silently does not persist, which breaks R2. Persist likely needs its own fresh `statement_deadline`; this is unmeasured.
client/backend/server.py _proxy_engine_request: the per-path timeout and retry change sits in the loop every browser read goes through (`/api/video`, `/api/channels`, search, `/recommendations`, `/videos/similar`). A mapping keyed wrongly, or a missed site among lines 604, 606, 696 and 731 (the `attempts` log field), silently changes the timeout or retry for all routes. Tests must pin both the refresh (one attempt, about 20 s) and a normal route (10 s, one retry).
client/frontend/src/pages/video-page/index.ts renderVideo, loadReaction and fetchVideoMetadataFromServer: the render now runs several times, but today's code assumes one run. Three things can break. The `lastEmbed` guard must reset when `src` is removed, or the iframe reloads or goes stale. The reaction gate must be set synchronously and only for a non-null `reactionVideo()`, or the buttons are never wired, or wired twice, when the uuid arrives only with the refresh. The Engine always sends `instanceName` as a string (possibly empty), so the config name never wins today for Engine sources; re-applying the shared instance config must add only the avatar there, and the name and URL only for the rank-2 instance fallback.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 1)

Pass 1. New impacts: YES.

I checked the inventory against the files at its paths and it holds up. I read `video.py` in full, plus `similar.py` 340-369 and 425-508, `db.py` 1-80, `http_utils.py`, `server.py` 60-120, 265-294, 410-475 and 570-745, the page's `index.ts` in the relevant ranges, `sync-whitelist.py` 260-310, and ran greps for `last_checked_at`, `last_error`, `/api/video` and the proxy constants across the tree and tests.

Several claims are confirmed exactly:
- `detail = fetch_instance_json(...) or {}` means `if dynamic` is always true.
- `db_lock` covers only the row read.
- `do_GET` wraps dispatch in the 5 s `statement_deadline` and re-raises everything except an interrupted `OperationalError`.
- The four proxy sites at 604/606/696/731 are right, and `RemoteDisconnected` from `getresponse` escapes `urlopen` unwrapped, so it lands in the generic 502 branch.
- `getString` returns `""`, so the Engine's string `instanceName` always beats the config name for ranks 1 and 3.
- `loadReaction` captures `video` before its first `await`.

One refinement strengthens the `db.py` entry: `videos_fts_au` deletes and re-inserts five columns (title, description, tags_json, category, channel_name), not just two. That makes the post-deadline interrupt more plausible.

Two things are only partly true. `engine/crawler` reads and writes `last_error`/`last_checked_at` in its own DB, not in the Engine's `whitelist.db`. And `data/channels.py` only projects `instances.last_error`. So nothing in serving keys on the writes that change.

The inventory misses only two small things: the Engine writing a response after the proxy has already hung up, and one issue doc that names `/api/video`.

<question id="1">
Yes, the plan works as intended. The split keeps R1's field parity, because every `dynamic.get` becomes `None` and falls back to the row. R7 holds because the instance call runs outside `db_lock` and both servers are `ThreadingHTTPServer`. The 20 s, no-retry proxy covers the ~16 s worst case.

It meets R2's "persists on success" only if the persist escapes the request's 5 s statement deadline, which has usually expired by the time the UPDATEs run after a slow instance. R2 tolerates a logged `OperationalError`, so this is not a conflict. It is a quality gap, and the inventory already names it. The frontend ordering is correct provided the inventory's conditions are kept:
- `lastEmbed` is reset when `src` is removed;
- the reaction gate is set synchronously and only for a non-null video;
- the config supplies only the avatar for ranks 1 and 3.
</question>
<question id="2">
Ramifications:
- A page view now costs two Client→Engine metadata requests, each on its own rate-limit bucket.
- A slow instance holds one Client thread and one Engine thread for up to ~20 s, with no retry.
- Per-view DB writes, and with them FTS churn, drop to successful refreshes only.
- `last_checked_at` and `instances.last_error` change only on real success.
- `/api/video` can no longer throw on instance errors (`JSONDecodeError`, `RemoteDisconnected`); only the refresh can, and there it degrades to a 502 the page ignores.

**New:** when an instance takes longer than 20 s, the Engine writes its answer to a socket the proxy has already closed. That raises `BrokenPipeError`/`ConnectionResetError`, which escapes `do_GET`, and `socketserver` prints a traceback to stderr. The persist has already run by then, so the data is kept. This happens today on `/api/video` at 10 s; after the build only the refresh can hit it.
</question>
<question id="3">
Beyond the plan's file list, these are needed:
- The persist runs under its own fresh `statement_deadline` (it nests and restores), or the gap is stated.
- The success rule is "a non-empty dict came back", not "not None".
- The four proxy sites all read the per-path timeout and retry, and a test pins both the refresh and one ordinary route.
- The coordinator sets `currentMetadata` to the winning rank, reproduces today's single null render when there is no usable source, and never chains `loadSimilarVideos`.
- `dist/` is rebuilt.
- These docs are updated: `engine/server/README.md`, `README.md`, `client/README.md`, `client/frontend/README.md`, `DEPLOYMENT.md` 374-375, issue 10, and issue 20 line 25 (new).
- Refresh tests run in an `ENGINE_PY` child over a temp DB with `handlers.video.fetch_instance_json` patched, never against the shared Engine.
</question>
<question id="4">
- `/api/video` no longer calls the instance or writes. It returns DB values with an empty `accountAvatarUrl`, and it no longer bumps `last_checked_at`, `popularity` or `instances.last_error`, even on the failure path where it used to.
- Live values arrive only through `/api/video/refresh`. A failed instance fetch now writes nothing.
- The page renders the panel from the DB instead of after the instance round-trip, then may re-render once or twice: on the refresh, and when the instance config supplies the avatar.
- When `/api/video` fails, the URL params are shown at once instead of a blank panel.
- The proxy no longer retries the refresh and waits 20 s instead of 10.
- `refresh_cache` on `/api/video` stays accepted and ignored, as today.
</question>

New impacts:
engine/server/api/http_utils.py respond_json() (lines 23-30), as the refresh's final write: it does not handle a peer that has gone away, and neither `SimilarHandler.do_GET` (similar.py:433-441, which catches only an interrupted `sqlite3.OperationalError`) nor the server overrides `handle_error`. When an instance holds the refresh past the Client's 20 s proxy timeout (`urlopen(timeout=8)` bounds each socket operation, so a slowly dripping instance can exceed it), the Engine's late `wfile.write` raises `BrokenPipeError`/`ConnectionResetError`, and `socketserver` prints a traceback to stderr for each such request. The persist has already run, so the data is kept, and the browser has already had its 502 and degraded per R3. This is pre-existing on `/api/video` at 10 s; after the build only `/api/video/refresh` can hit it. Regression risk: low (log noise only).
docs/project/issues/20-request-lifecycle-logs.md line 25: its smoke list for start→end request logs names `/api/video`. After the build, the long-running, instance-bound route whose lifecycle logging matters is `/api/video/refresh`, so the issue should name it too. The docs checklist does not carry this file. Regression risk: none (docs).

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. Run the refresh's persist under its own nested `statement_deadline(server.statement_timeout_seconds)`.
- What it changes: the write gets a fresh 5 s budget instead of the request's expired one, so a slow instance's successful refresh actually persists, which is what R2 means.
- What it costs: about 2 lines in `video.py` and one import from `data.db`. It also needs one child-process test with a patched `fetch_instance_json` that sleeps just past a lowered `server.statement_timeout_seconds` (e.g. 0.2 s), then asserts the row changed. This keeps the test fast.
- If you decline: state the gap as a known limitation.

2. State the success signal in `fetch_instance_video_dynamic` as "`detail` is a non-empty dict" rather than "is not None".
- What it changes: a 200 carrying `[]`, a string or `{}` no longer writes DB values back and clears `last_error`, and no longer crashes with `AttributeError`.
- What it costs: one line. This stays within the plan's intent ("the video detail came back"), so it is not a plan change.

3. In the coordinator, do not start the rank-2 direct-instance fallback when rank 3 is already shown.
- What it changes: the browser skips a cross-origin video fetch and a channel fetch whose result the rank rule would drop anyway.
- What it costs: one condition. Its test is an extra ordering case: refresh first, then the fast call fails.

4. Accept the write-to-closed-socket traceback (the new `http_utils.py` impact) as a known pre-existing noise source rather than fixing it in this build.
- Why: catching `BrokenPipeError`/`ConnectionResetError` in the refresh handler, or overriding `handle_error`, would be a new pattern in the Engine's handlers and reaches beyond R1-R7.
- What it costs: nothing now. The follow-up belongs with issue 20 (request lifecycle logs).

5. At harvest, add `/api/video/refresh` to issue 20's smoke list next to the docs-checklist items.
- What it costs: a one-line docs edit.

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts


<impacts>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request() (lines 208-361), split into a row resolver, a pure merge and a persist function, plus two route handlers">
**What changes.** The single function becomes three module-level helpers and two thin handlers, one for `/api/video` and one for `/api/video/refresh`.
- **Resolver.** It takes lines 210-224 as they are. `id` falls back to `video_id` and `host` to `instance_domain`. It answers 400 `{"error": "Missing video id"}` and 404 `{"error": "Video not found"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` inside `with server.db_lock:` (lines 215-221 only).
- **Merge.** It takes lines 226-290 with `dynamic` passed in. `instance_domain = row.get("instance_domain") or host_param or ""` (line 226) needs `host_param`, so the resolver must return it or `instance_domain` itself, and both the merge and persist need it.
- **Persist.** It takes lines 292-358. It needs the merged intermediates, not just the response dict: `title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, plus `row["video_id"]`, `row["channel_id"]` and `row["published_at"]`. The response carries no `channel_slug`, `tags_json`, `category` or `nsfw`, and `channelName` is `channel_display or ""`, so a `None` would become `""` if persist were fed from the response. The merge therefore has to return its intermediates, or persist has to re-derive them. The plan leaves this open.
- **`/api/video`.** Resolve, merge with `{}`, respond. With `dynamic = {}` every `dynamic.get(...)` is `None` and each field falls back to the row exactly as today. `accountAvatarUrl` becomes `""`. `accountName` and `accountUrl` already come only from the row today (lines 281-282 ignore `dynamic["account_name"]` and `dynamic["account_url"]`), so they do not change.
- **`/api/video/refresh`.** Resolve, `fetch_instance_video_dynamic`, merge, persist only when the fetch reports success, respond with the same shape.
- **Docstrings.** The module docstring (lines 1-7, "Merge DB metadata with live instance metadata (when available)") and the handler's own docstring (line 209) must say which route does what.

**What depends on it.** `engine/server/api/handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else in the tree imports it (grep). No test in `tests/` touches this module; only the smoke scripts call `/api/video`.

**Regression risk: medium.**
- **db_lock boundary.** The instance fetch must stay outside `server.db_lock`, as today. Moving it inside the resolver's `with` block would block every Engine route, similars included, for up to ~16 s, which breaks R7.
- **Renaming.** If `handle_video_request` is renamed, the import at `similar.py:84` must follow, or the Engine fails at import and every live-Engine test fails in the `engine` fixture.
- **Read and write are not atomic.** The row is read before the instance call and written after it. Two concurrent refreshes of one video both write instance data, last writer wins. This is harmless.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails">
**What changes.** Line 164 is `detail = fetch_instance_json(...) or {}`. It becomes an early `return {}` when the detail call does not come back.

**The gotcha is confirmed.** Today the function always returns a 14-key dict, so `if dynamic` (line 293) is always true. A failed fetch therefore writes DB values back, bumps `last_checked_at`, recomputes `popularity` and clears `instances.last_error*`.

**Edge cases the success test should cover.**
- `fetch_instance_json` returns whatever `json.loads` yields. A 200 carrying a JSON array or a string reaches `detail.get` and raises `AttributeError`, which nothing catches. This is pre-existing. A test of "`isinstance(detail, dict)` and non-empty" instead of "`is not None`" closes it.
- A 200 carrying `{}` passes a `None` check but holds no data. Persist would then write DB values back and clear `last_error`. This is minor, and the same check closes it.

**What depends on it.** Only `handle_video_request` today (grep, including tests), and after the build only the refresh handler. The channel sub-call (line 176) runs only when `channel_slug` came back, so after the change it runs only on success.

**Regression risk: low.** It is the one deliberate behaviour change to the persist trigger, and the operator accepts it: a failed fetch no longer clears `instances.last_error` or bumps `last_checked_at`.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_json() (lines 75-87): unchanged; test seam; narrow exception set">
**What changes.** Nothing. The R7 test patches it to block.

**What depends on it.** Both instance calls in `fetch_instance_video_dynamic`, which looks it up as a module global. A test must patch `handlers.video.fetch_instance_json` on the module; patching an imported alias has no effect.

**The error path.**
- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` misses `json.JSONDecodeError` (a non-JSON 200), `UnicodeDecodeError`, and `ConnectionResetError` / `http.client.RemoteDisconnected` raised during `resp.read()`.
- **What happens then.** These propagate out of the refresh handler. `SimilarHandler.do_GET` (`similar.py:433-441`) re-raises everything except an interrupted `OperationalError`, so the Engine drops the connection without a response.
- **What the Client sees.** `RemoteDisconnected`, which is not a `URLError`, so it lands in the generic `except Exception` branch (`client/backend/server.py:700-721`) and answers 502 `ENGINE_PROXY_FAILURE`. The page treats that as a failed refresh (R3).
- **Before and after.** This is pre-existing: today the same exception kills `/api/video` itself. After the split only the refresh can hit it.
- **Timeout scope.** `timeout=8` bounds each socket operation, not the whole call.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline() / _deadline_passed() / PROGRESS_HANDLER_INSTRUCTIONS (lines 14-64), as it applies to the refresh's persist">
**What changes.** Nothing in code, but the refresh's timing makes it bite.

**How the deadline applies.**
- `SimilarHandler.do_GET` (`similar.py:436`) wraps the whole dispatch in `self._statement_deadline()`. That is `statement_deadline(server.statement_timeout_seconds)`, set from `DEFAULT_STATEMENT_TIMEOUT_SECONDS` at `engine/server/api/server.py:272`: a wall-clock deadline counted from request start.
- The refresh reaches its three UPDATEs only after up to ~16 s of instance calls, so the thread's deadline has usually passed by then.
- The progress handler fires every 10,000 VM instructions (line 14). Any persist statement that runs that long after the deadline is aborted with `OperationalError: interrupted`.
- The `videos` UPDATE fires `videos_fts_au` (`engine/server/db/jobs/sync-whitelist.py:279`), which re-tokenises several text columns. That makes crossing 10,000 instructions plausible for long descriptions.

**Consequence.**
- The persist's own `except sqlite3.OperationalError` (video.py:352-358) catches the abort, logs `[video] failed to persist dynamic metadata ... interrupted` and rolls back `with server.db:`. The response is still 200 with refreshed values.
- So a successful refresh from a slow instance may silently not persist, against R2's "on a successful instance fetch, persists".
- This is pre-existing and masked today. After the build the refresh is the only writer, so it matters.

**Options for the design step.**
- Run persist under its own nested `statement_deadline(...)`. The block saves and restores the previous deadline (lines 59-64), so nesting is supported.
- Or state the gap as a known limitation.

**Regression risk: medium to high for R2's persist guarantee.** Unmeasured: I have not confirmed that a single-row UPDATE plus the FTS trigger crosses 10,000 instructions. A child-process test with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json` would show it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_get() /api/video branch (lines 495-497), import at line 84, module docstring route list (lines 3-13)">
**What changes.**
- A new `if url.path == "/api/video/refresh":` branch goes beside line 495 and calls the new refresh handler.
- The line-84 import gains the new name(s).
- The docstring gains a `/api/video/refresh` line, and line 9 (`/api/video: single video metadata.`) could say "from the DB".

**What depends on it.**
- **Rate limit.** Line 447 rate-limits every `/api/` path on the key `f"{ip}:{path}"` (`_rate_limit_check`, lines 576-583), so the refresh gets its own bucket. The ip comes from `X-Client-IP`, which the Client sends (`client/backend/server.py:590`).
- **Matching.** Paths are matched with `==`, and `_extract_video_id_from_similar_path` (line 499) matches only `/videos/.../similar`. Without the new branch, `/api/video/refresh` would fall through to the 404 at line 508. Nothing shadows it.
- **Statement deadline.** Both routes run inside `do_GET`'s statement deadline (see the `db.py` entry).

**Regression risk: low.** It is one branch. The similars dispatch is untouched, which keeps R7.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 5 ('video: fetches video metadata for /api/video.')">
**What changes.** The line should name both routes: `/api/video` (DB only) and `/api/video/refresh` (live instance refresh, persisted).

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/http_utils.py" element="respond_json() (lines 23-30), the refresh's final write">
**What changes.** Nothing.

**Why it matters.**
- `respond_json` writes to `handler.wfile` unguarded.
- When the instance holds the refresh past the Client's 20 s proxy timeout (possible, since `timeout=8` is per socket operation), the Engine's late write goes to a closed socket.
- It raises `BrokenPipeError`/`ConnectionResetError`, which `do_GET` does not catch, so `socketserver` prints a traceback to stderr.
- Persist has already run, so the data is kept, and the browser has already had its 502.
- This is pre-existing on `/api/video` at 10 s; after the build only the refresh can hit it.

**Regression risk: low (log noise).**
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer (ThreadingHTTPServer, line 207): db, db_lock, video_error_threshold (230, 264), popularity_like_weight (234, 268), statement_timeout_seconds (272)">
**What changes.** Nothing.

**What depends on it.**
- The resolver reads `server.video_error_threshold`.
- Persist reads `getattr(server, "popularity_like_weight", 2.0)`, `server.db` and `server.db_lock`.
- `SimilarServer` is a `ThreadingHTTPServer`, so a refresh blocked on an instance ties up one thread, not the server. R7 relies on this.

**Test note.** A child-process test needs a server object with `db`, `db_lock` and `video_error_threshold`, plus `popularity_like_weight` if persist runs and `statement_timeout_seconds` if the deadline is exercised. `tests/active/test_internal_events.py:52` builds a real `SimilarServer` this way.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/popularity.py" element="compute_popularity(), called by persist">
**What changes.** Nothing. It moves with the persist block. Its arguments must stay the merged `views`/`likes` (instance value or DB fallback), not the response's copies, plus `row["published_at"]`, the like weight and `now_ms_value=checked_at`.

**What depends on it.** The `videos.popularity` column, which ranking reads.

**Regression risk: low.** After the build it runs only on a successful refresh, where today it runs on every view, failures included.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts_au AFTER UPDATE trigger (line 279)">
**What changes.** Nothing.

**What depends on it.** Every persisted refresh fires the trigger and re-indexes the video for search. Writes drop from one per page view (even on a failed fetch) to one per successful refresh, so FTS churn falls. It is also relevant to the statement-deadline entry.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/metadata.py" element="readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301), data/search.py (80), data/channels.py (129-159, instances.last_error*)">
**What changes.** Nothing.

**What depends on it.** These only project `last_checked_at` and `instances.last_error*` into rows. A grep shows nothing in `engine/server` selecting, filtering or ordering on them per request, and nothing in `engine/server/db/jobs/*worker*.py` references them. So the fast path no longer bumping them is invisible to serving.

**Regression risk: none in serving.** The crawler (`engine/crawler`) keeps its own DB; I did not audit it.
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_STATEMENT_TIMEOUT_SECONDS, DEFAULT_RATE_LIMIT_*, DEFAULT_HIDE_BLOCKED_IN_VIDEO_API (line 455 comment)">
**What changes.** Nothing.

**What depends on it.**
- The statement budget interacts with the refresh persist.
- The per-path Engine rate limit now applies to the refresh separately.
- Line 455's "Optional future toggle for /api/video hide behavior" is unused by `video.py` and stays unrelated.

**Regression risk: none.**
</impact>
<impact path="client/backend/server.py" element="PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)">
**What changes.**
- `"/api/video/refresh"` joins the frozenset.
- A new entry `"/api/video/refresh": {"id", "host"}` is added.
- `/api/video` keeps `{"id", "host", "refresh_cache", "user_id"}`.

**What depends on it.**
- `do_GET` (lines 277-282) routes on `url.path in PROXY_READ_GET_ROUTES`, applies `_rate_limit_check(url.path)` (`RATE_LIMIT_MAX_REQUESTS = 90` per 60 s, keyed per path, so the refresh gets its own bucket), then calls `_handle_engine_read_proxy_get`.
- That function (417-436) answers 400 for an unknown key or a repeated key, and strips values.
- `_profile_filter` (438-469) passes the refresh through untouched, because it is in neither `FEED_ROUTES` nor `FILTERED_ROUTES` (lines 71-72).
- The frontend must send only `id` and `host`: `user_id` or `refresh_cache` on the refresh would now get 400.

**Regression risk: low.** It is a pure addition.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() (lines 570-745) with ENGINE_PROXY_TIMEOUT_SECONDS (77) / ENGINE_PROXY_RETRY_COUNT (79) / ENGINE_PROXY_RETRY_DELAY_SECONDS (80)">
**What changes.** A path→timeout mapping, defaulting to `ENGINE_PROXY_TIMEOUT_SECONDS`, and a per-path retry count: 0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise.

**Four sites must read the per-path values.**
- Line 604: `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)`.
- Line 606: `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)`.
- Line 696: `if attempt < ENGINE_PROXY_RETRY_COUNT`.
- Line 731: the `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` field of the "proxy request unavailable" log. It is easy to miss, and left alone it logs 2 attempts for a refresh that made 1.

**Key on `path`.** The function receives both `path` and `upstream`; `upstream` carries the query string (line 583). The mapping must be keyed on `path`.

**What depends on it.** Every proxied read: GET `/api/video`, `/api/channels`, `/api/v1/search/videos`, and POST `/recommendations`, `/videos/similar` (line 561). They must keep 10 s and one retry.

**How a refresh timeout surfaces.**
- The Engine sends nothing until it has finished, so the read waits up to the full timeout.
- `socket.timeout` is `TimeoutError`, which lands in the `(URLError, TimeoutError)` branch. With 0 retries the loop breaks to the 502 `ENGINE_PROXY_UNAVAILABLE` body (736-744), which carries a pre-existing `detail`.
- A dropped Engine connection lands in the generic 502 branch (700-721).
- Both are non-OK for the browser, which is the R3 degrade.

**Test harness.** `tests/active/test_server.py:347-422` (`_serving`, `_client_backend`, `EngineStub`) is the template for a stub that counts GETs and sleeps. Monkeypatching the constants or the mapping on `client_server` avoids a real 20 s wait.

**Regression risk: medium.** This loop carries every browser read. A wrong key or a missed site silently changes the timeout or retry for all routes, so tests must pin both the refresh and one ordinary route.
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)">
**What changes.** Nothing.

**What depends on it.** The refresh gets the same sanitising. An empty value is dropped (line 431), so `id=` reaches the Engine without `id` and gets its 400 `Missing video id`, passed through by the HTTPError-with-payload branch (646-677).

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module top level: `void loadVideo()` (line 79), currentMetadata (50), seedId/seedHost (54-55), fallback (57-63), localLikesImported (75-77), applyActionIcons() (1226)">
**What changes.** Line 79 becomes the coordinator start. `void loadSimilarVideos()` (80) is unchanged.

**What the coordinator must preserve.**
- **No usable source.** When `resolveVideoSource()` yields no host or id (`fetchVideoMetadata`, line 508, returns `null` today), today's code renders once with `metadata = null`, taking every value from `fallback`, `seedHost` and `https://${seedHost}`. The coordinator must keep that. Rank 0 is therefore exactly `renderVideo(null)`.
- **`currentMetadata` in step.** It must equal the metadata actually rendered, because `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost` (1151-1166).

**Testing constraints.** The module does DOM work at import: 27 `getElementById` constants (22-48), `window.location.search`, `importLocalLikes`, `applyActionIcons()`, and `import "../../video.css"`. A node test of the page needs a stubbed `document` and `window`, a scripted `fetch`, `localStorage`, and an esbuild css loader (e.g. `--loader:.css=empty`).

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo() (lines 85-229) becoming renderVideo(metadata)">
**What changes.** The body stays the same, minus `await fetchVideoMetadata()` (86); the `currentMetadata = metadata` line (87) moves to or is set by the coordinator. The function then runs once per accepted source, and again when the instance config arrives.

**What re-runs on each render.**
- **Text and markup writes.** Title, channel `innerHTML` through `escapeHtml`/`safeExternalUrl`, subscribers, instance link, account link, description, views, counts, original link. All idempotent.
- **Avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatars (154-161, 179-186) are rewritten each time, then `bindAvatarFallback` (426-437) binds a `once` listener on the fresh `<img>`. The old nodes are discarded, so listeners do not pile up, though an image may flicker.
- **Embed (212-221).** Today `embedEl.src = embed` is set unconditionally. The new `lastEmbed` guard compares against the string actually assigned, after the `https://` test. It must be reset when the `else` branch calls `removeAttribute("src")`, or a later identical valid URL would never be reassigned.
- **`document.title`** (114) is rewritten each time.
- **`enableBlockButtons`** (196) is guarded; see its entry.
- **`void loadReaction()`** (197) needs the new gate; see its entry.

**Values across sources.**
- The Engine sends `""` for empty strings. `metadata?.title ?? fallback.title` therefore yields `""`, and `titleEl` shows "Video page" through `title || "Video page"`, as today.
- Ranks 1 and 3 both carry `embedUrl = resolve_asset_url(instance_domain, row.embed_path)`, which is textually identical, so no reload between them.
- Rank 0 uses `fallback.embed` (`?embed=`). Rank 2 builds its URL with `resolveApiAssetUrl`, and rank 3 uses the DB path. So when the fast call fails, one iframe reload between rank 0 and a later rank is possible. R6 only covers an unchanged URL.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)">
**What changes.**
- The sequential "server, else instance" logic in `fetchVideoMetadata` moves into the coordinator.
- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (525). It must serve both `/api/video` and `/api/video/refresh`, through a path parameter or a shared mapper; the refresh has the same shape, so the mapping at 527-551 applies unchanged.

**Correction to the plan's precedence wording.**
- The Engine always sends `instanceName` and `instanceUrl` as strings (`video.py:279-280`, possibly `""`), and `??` does not skip `""`. So for ranks 1 and 3, `instanceMeta?.name`/`url` never win today.
- The config supplies only `instanceAvatarUrl` (line 540) there.
- For rank 2 (608-610), the config's name and URL do win.
- If re-applying the config overwrote `instanceName` unconditionally, the chip label for ranks 1 and 3 would change from the host to the instance's display name. That is a visible change, and it would also alter `resolveLikeHost` only if `seedHost` were empty.

**Other effects.**
- `catch { return null; }` (552-554) also swallows `response.json()` failures and non-OK statuses. The refresh caller needs its own signal to `console.warn`.
- `instanceAvatarUrl` must be merged in from the shared promise for every rank, or it disappears when a later rank re-renders.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)">
**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, since it is part of rank 2 itself.

**Behaviour to keep.**
- Its result has no `videoUuid`, so after a rank-2 render `resolveLikeUuid` falls back to `seedId` only if it looks like a UUID (1151-1155, 1171-1173).
- It runs only after the fast fetch fails (R5).
- If rank 3 is already shown, its result is dropped by the rank rule. The coordinator could skip starting it then.

**Regression risk: low to medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchInstanceMetadata() (655-688) and getString() (724-730), as one shared promise">
**What changes.** It is called once per load and its promise is shared.

**What it returns.**
- `getString` returns `""`, never undefined, so the `?? ... ?? host` chain at 664-667 never reaches `host`, and `name` can be `""`.
- On success `avatarUrl` is always set, falling back to `https://${host}/favicon.ico`.
- On any failure, including the common cross-origin/CORS failure, it resolves to `null` and never rejects. A `.then` needs no `.catch`.

**What depends on it.**
- The instance chip avatar for every rank, and the name and URL for rank 2 only.
- Its resolution re-renders the current best metadata at the same rank, so the rank rule must allow equal-rank renders ("at least the rank shown").

**Constraint.** It must start only once a host is known (`resolveVideoSource().host`).

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadReaction() (318-341), reactionVideo() (381-386), react()/renderReaction()">
**What changes.** A module-level `uuid|host` key of the last reaction fetched gates `fetchReaction`.

**How the gate must work.**
- `reactionVideo()` depends on `currentMetadata`. On a rank-0 or rank-2 render with a non-UUID `seedId` it returns `null`, and `loadReaction` returns early (320) without wiring the buttons. A later rank carrying `videoUuid` (rank 1 or 3) must still fetch and wire, so the key must be set only when `video` is non-null.
- `await localLikesImported` (322) comes before the fetch. The key must be written before that first `await`, or two quick renders both pass the gate and fetch twice.
- The click listeners (331-340) capture the first non-null `video` and are never rewired because of `likeButton.dataset.wired`. This is unchanged.

**What depends on it.** `renderReaction` and `setReactionStatus`. `tests/active/test_frontend_reactions.py` tests `data/reactions.ts`, not this page.

**Regression risk: medium.** A wrong gate either breaks R6 (a second fetch) or leaves the buttons disabled when the uuid arrives only with a later rank.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="enableBlockButtons() (275-308)">
**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.

**What depends on it.**
- It captures `uuid` and `host` from the first call where both are non-empty.
- On rank 0, `metadata?.videoUuid || resolveVideoSource()?.id` gives `seedId`, which may be a numeric `video_id`, and the buttons keep it for good. This already happens today when `/api/video` fails.
- It is more reachable now if the fast call fails and the refresh later brings the real uuid. The block route resolves through the Engine by `video_id` or uuid, so it probably still works; I did not trace `blockVideoSource`.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (234-269) and similar stats helpers">
**What changes.** Nothing (R7). It waits only on `localLikesImported`, never on metadata.

**Regression risk: none,** provided the coordinator neither awaits nor chains it.
</impact>
<impact path="client/frontend/video-page.html" element="CSP meta (line 8), #video-embed iframe (32-36), #video-title placeholder (40), module script (112)">
**What changes.** Nothing.

**What depends on it.**
- `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser→instance fetches.
- The static "Video page" title shows until the first render.

**Regression risk: none.**
</impact>
<impact path="client/frontend/dist/assets/video-gjYm1MC8.js" element="built video page bundle (build output)">
**What changes.** It is regenerated by the frontend build under a new hash filename, never edited by hand.

**What depends on it.** The deployed static site serves `dist`.

**Regression risk: low.** A stale `dist` deployed against the new Engine still works, because `/api/video` keeps its shape; the page just stops receiving live values.
</impact>
<impact path="client/frontend/vite.config.ts" element="dev server proxy '/api' (lines 27-28)">
**What changes.** Nothing. The `/api` prefix already covers `/api/video/refresh` in dev.

**Regression risk: none.** I did not check for a proxy timeout.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend gateway preflight (lines 22-38)">
**What changes.** Nothing. It forbids only Engine base usage, hard-coded Engine ports and `/internal/*` routes in `client/frontend/src`; there is no allow-list of gateway routes. A `/api/video/refresh` literal in `index.ts` passes.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="nginx `location /api/` (lines 319-325), ufw note (369-375)">
**What changes.**
- The nginx block needs nothing: `location /api/` already proxies `/api/video/refresh`, and nginx's default `proxy_read_timeout` (60 s, not overridden here) exceeds 20 s.
- The prose at 374-375 ("`/api/video` makes live calls to source instances per request") becomes wrong. See the docs checklist.

**Regression risk: none in config.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (line 106) over the shared WHITELIST_DB (34); ENGINE_PY (32); CLOSED_ENGINE (45)">
**What changes.** Nothing.

**What the new tests must avoid.**
- A refresh through the session `engine` fixture would make real outbound HTTPS calls and write to the shared `whitelist.db`. Refresh and R7 tests must run the Engine handler in an `ENGINE_PY` child over a temporary DB, with `handlers.video.fetch_instance_json` patched. Precedents: `test_internal_client_reads.py:144-145`, `test_internal_events.py:52,174`, and `test_similar.py`'s children.
- Fast `/api/video` against the shared Engine is safe after the build (no calls, no writes), but not before it.

**Regression risk: medium for test hygiene.**
</impact>
<impact path="tests/active/test_server.py" element="_serving/_client_backend/EngineStub pattern (lines 347-422)">
**What changes.** Nothing. It is the template for the new proxy test.

**The new test.** A stub Engine that counts GETs and sleeps past the timeout on `/api/video/refresh` checks two things: the refresh gets one attempt, and `/api/video` still retries once. `_status` uses `timeout=30` (375), so a 20 s proxy wait fits, but monkeypatching the timeouts keeps the suite fast.

**Test group.** The file is mapped to `client/backend/server.py` in `.un/skills/devsecops/config.json:57-58`.

**Regression risk: low.**
</impact>
<impact path="tests/active/test_frontend_blocks.py" element="esbuild + node runner pattern (lines 22-85)">
**What changes.** Nothing. It is the precedent the plan names.

**Why it does not transfer directly.** It bundles data modules only. The video page runs DOM code and imports css at load. A page test needs:
- a fake `document` whose elements support `innerHTML`, `textContent`, `hidden`, `dataset`, `classList`, `closest`, `querySelector(All)`, `addEventListener`, `setAttribute`, `removeAttribute` and `insertAdjacentHTML`;
- `window.location.search`;
- a scripted `fetch`;
- a css loader flag.

**Regression risk: medium for test effort.** Extracting the rank helper is the fallback the plan allows.
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups mapping">
**What changes.** Nothing during the build.

**At harvest.** `engine/server/api/handlers/video.py` and `client/frontend/src/pages/video-page/index.ts` are not mapped to any test group (grep). New test files need entries. `client/backend/server.py` is already mapped by several groups.

**Regression risk: low.**
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647) and README.md line 134">
**What changes.** Nothing required: `/api/video` still answers 200, and faster.

**Optional.** A `/api/video/refresh` check would depend on outbound 443 to a source instance, so asserting "200 or 502" is safer.

**Regression risk: none.**
</impact>
<impact path="docs/project/security-audit/run-1/REPORT.md" element="line 299 (`/api/video` performs up to two outbound HTTPS requests); also run-1/architecture.md:67, run-2/REPORT.md:125,221, run-2/FINDINGS-DETAIL.md:136">
**What changes.** Nothing. These are dated audit records and must not be rewritten. They are listed because a grep for `/api/video` hits them and they describe the old behaviour.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/19-11-fast-similars-response.record.md" element="workflow record for this build">
**What changes.** It is rendered by the workflow; do not hand-edit it. It already holds a prior step-3 pass. This inventory re-verified that pass's line numbers against the tree, and they hold.

**Regression risk: none.**
</impact>
</impacts>


### docs_checklist


<doc path="engine/server/README.md">
Line 9 (`/api/video` metadata for the video page) becomes two bullets:
- `/api/video` answers from the local DB only: no instance call and no write, same response shape, and `accountAvatarUrl` is empty.
- `/api/video/refresh` fetches live metadata from the source instance (video detail, then channel; 8 s socket timeout each) and answers the same shape. Only when the video detail call succeeds does it run the `videos`/`channels` UPDATE and reset `instances.last_error*`; a failed fetch writes nothing. It is the one per-request metadata write path.

Line 3 ("Read-only Engine API") was already inaccurate and should note that the refresh route writes metadata.
</doc><doc path="README.md">
Boundary table, lines 46 (Engine public read API) and 48 (Client browser-facing read gateway): add `/api/video/refresh` to both route lists.
</doc><doc path="client/README.md">
Line 37 (read gateway list): add `/api/video/refresh`.

Optionally, under Backend Responsibilities: the refresh proxy accepts only `id` and `host`, waits up to 20 s and is not retried, while every other read proxy keeps 10 s with one retry.
</doc><doc path="client/frontend/README.md">
Line 8 (fetched gateway routes): add `/api/video/refresh`.

Optionally add one sentence on the video page's load order:
- it renders from `/api/video` first;
- it re-renders when the refresh and the instance config arrive;
- when `/api/video` fails, it falls back to the URL params and then the direct instance fetch.
</doc><doc path="DEPLOYMENT.md">
Lines 374-375: "`/api/video` makes live calls to source instances per request" becomes `/api/video/refresh`, one live refresh per video page view. The ufw comment at 369 stays true, and the nginx block needs no change.
</doc><doc path="docs/project/issues/10-video-metadata-completeness.md">
- Line 22 ("reflected after the next `/api/video` request") becomes the next `/api/video/refresh`.
- Line 17's "the DB update and `instances.last_error` reset run only on a successful refresh" now describes real behaviour. Note that the refresh handler is the single per-request write path to extend.
- Line 16 stays true.
</doc><doc path="docs/project/issues/20-request-lifecycle-logs.md">
Line 25 (smoke list naming `/api/video`): add `/api/video/refresh`, the long-running, instance-bound route whose start→end logging matters most.
</doc><doc path="docs/project/issues/11-fast-similars-response.md">
At harvest:
- set `Status: enhancement, complete`;
- add a delivery comment recording the two-phase reading, the 20 s / no-retry refresh budget, and the accepted `last_error`/`last_checked_at` change;
- move the file to `docs/project/issues/archive/`.
</doc>


### highest_risk


engine/server/data/db.py statement_deadline, applied to the refresh persist in engine/server/api/handlers/video.py: `SimilarHandler.do_GET` sets a 5 s wall-clock deadline at request start, but the refresh runs its UPDATEs only after instance calls that can take ~16 s. A persist statement that crosses 10,000 VM instructions after the deadline is aborted as `interrupted`, and the `videos_fts_au` trigger makes that plausible. The abort is swallowed by the persist's own `OperationalError` catch, so a successful slow refresh silently does not persist, against R2. The fix is a nested fresh `statement_deadline` around persist. I have not measured whether the threshold is actually crossed.
client/backend/server.py _proxy_engine_request: the per-path timeout and retry change sits in the loop every browser read uses. Four sites must switch to per-path values (lines 604, 606, 696, and the `attempts` log field at 731), and the mapping must be keyed on `path`, not on `upstream` with its query string. A mistake silently changes the timeout or retry for `/api/video`, `/api/channels`, search and the feed POSTs. Tests must pin the refresh at one attempt and an ordinary route at 10 s with one retry.
client/frontend/src/pages/video-page/index.ts renderVideo, loadReaction and fetchVideoMetadataFromServer: code written for a single render now runs several times, and three rules keep it correct. The `lastEmbed` guard must reset when `src` is removed. The reaction gate must be set before the first `await`, and only for a non-null `reactionVideo()`; otherwise the buttons stay unwired when the uuid arrives only with a later rank, or the reaction is fetched twice. The Engine always sends `instanceName`/`instanceUrl` as strings, so for ranks 1 and 3 re-applying the shared instance config must add only the avatar; overwriting the name visibly changes the chip label.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 2)

Pass 2. New impacts: YES.

I read the files behind the inventory's key claims. The whole of `engine/server/api/handlers/video.py`, the dispatch and `do_GET` in `similar.py` (433-508), `client/backend/server.py` (constants 60-105, `do_GET`, `_handle_engine_read_proxy_get`, `_profile_filter`, `_proxy_engine_request` 570-745), `engine/server/data/db.py` (1-70), and `client/frontend/src/pages/video-page/index.ts` (1-440, 500-739). Every claim I checked held. I also grepped the tree for other mentions of the route. That found five documents describing `/api/video` that the inventory does not carry: four route lists and issue 10's validation line. None of them changes the design. The plan works as intended. Two points need a decision in the design step: a persist rule the plan leaves open, and the persist deadline the inventory already flags.
<question id="1">
Yes. What the code shows:
- **Fast route.** With `dynamic = {}`, every field in `handle_video_request` (229-290) falls back to the row. Only `accountAvatarUrl` changes, to `""`.
- **Success signal.** `fetch_instance_video_dynamic` always returns 14 keys (188-205), so the `if dynamic` guard at line 293 is always true today. Returning early when the detail call fails is what makes "persist only on success" real.
- **Lock boundary.** `db_lock` is held only around `fetch_video_row` (215-221) and around the UPDATEs (303-351). The instance call is outside the lock today and stays outside after the split. R7 holds, because `ThreadingHTTPServer` gives each request its own thread.
- **Proxy loop.** Three sites use the constants: timeout at 606, retry at 604/696, and the log at 731. A `socket.timeout` during `getresponse()` is `TimeoutError`, which lands in the retry branch. A dropped Engine connection (`RemoteDisconnected`) is not wrapped in `URLError`, so it reaches the generic 502 branch. Both are non-OK for the browser, which is R3's degrade.
- **Frontend.** The current code awaits `fetchInstanceMetadata` at 525 and 600, as the plan says.

Two things only the design step can settle:
- **Persist deadline.** Persist runs after the request-wide statement deadline in `do_GET` (436) has usually expired. The progress handler can then abort the UPDATE plus FTS trigger. The persist's own `except` swallows the abort, so R2's "persists on success" can fail silently. The inventory already carries this.
- **Rank 0 and the instance avatar.** Rank 0 is `renderVideo(null)`, while the avatar is to be merged "for every rank". With `null` metadata there is nothing to merge into, so the coordinator needs to decide which one gives way.
</question>
<question id="2">
- **Page views.** Each view now makes two Client→Engine requests, in separate rate-limit buckets on both tiers (Client `_rate_limit_check` at 406-409 and Engine at 576-583, both keyed `ip:path`).
- **Held threads.** On a slow instance, one Client thread and one Engine thread stay busy for up to 20 s.
- **DB writes.** Writes to the DB and the FTS index (re-indexing) fall from one per view, failures included, to one per successful refresh.
- **Error and timestamp columns.** `last_checked_at` and `instances.last_error*` are no longer touched on failure. Nothing in serving reads them per request.
- **Docs.** Documentation that describes `/api/video` as a live call becomes wrong: DEPLOYMENT.md:374 (in the inventory) plus the route lists and issue 10 (new, below).
- **Issue 10.** The refresh route becomes issue 10's single write path. That delivers issue 10's robustness bullet (line 17: "the DB update and `instances.last_error` reset run only on a successful refresh") ahead of that issue, and moves its integration check (line 22) onto the refresh route.
</question>
<question id="3">
Beyond the inventory:
- **Import.** `similar.py:84` must import the new handler names; a missed name is an import-time failure of the whole Engine.
- **Proxy sites.** The per-path timeout and retry must be read at all four sites in `_proxy_engine_request`, keyed on `path`, not `upstream`.
- **Reaction gate.** The `loadReaction` gate must be keyed on a non-null `video` and written before the first `await`.
- **Embed guard.** `lastEmbed` must be reset on the `removeAttribute("src")` branch.
- **Instance name.** The shared instance-config promise must not overwrite `instanceName` for ranks 1 and 3. The Engine always sends a string there, so the name has never come from the config on those ranks.
- **Route lists.** They must name the new route so that the documented read gateway (README.md:48) stays accurate: README.md:46,48, client/README.md:37, client/frontend/README.md:8, engine/server/README.md:9.
- **Issue 10.** Its validation line should point at `/api/video/refresh`.

Nothing existing breaks functionally without these doc edits. The gateway has no enforced allow-list in docs or preflight (`tests/check-frontend-client-gateway.sh`).
</question>
<question id="4">
- **Fast route.** `/api/video` becomes DB-only. It is faster, always returns `accountAvatarUrl: ""`, and never writes.
- **Live values.** They arrive on the page later, from `/api/video/refresh`, and only on success.
- **No-write on failure.** A failed instance fetch no longer writes DB values back, bumps `last_checked_at`, recomputes `popularity`, or clears `instances.last_error*`.
- **Proxy.** The refresh gets a 20 s timeout and no retry; every other route keeps 10 s and one retry.
- **Render order.** The page renders before the instance config arrives. The instance chip shows initials first, then the avatar, and the panel may re-render up to three times.
- **Iframe.** When the fast call fails, one reload between `?embed=` and a later embed URL is possible (inventory already notes it).

Everything else keeps today's behaviour: similars, the response shape, 400/404, escaping and URL safety.
</question>

New impacts:
README.md (lines 46, 48): the Engine public-read-API table and the Client read-gateway table list `/api/video` and not `/api/video/refresh`. Both rows need the new route, and the Engine row's description of `/api/video` as metadata should say DB-only. Documentation only; the risk is none.
client/README.md (line 37): the read-gateway route list needs `/api/video/refresh`. Documentation only.
client/frontend/README.md (line 8): the list of gateway routes the frontend fetches needs `/api/video/refresh`. Documentation only.
engine/server/README.md (line 9): "`/api/video` metadata for the video page". The plan names this file, but the inventory has no entry for it. It needs a `/api/video/refresh` line and "from the DB" on `/api/video`. Documentation only.
docs/project/issues/10-video-metadata-completeness.md (lines 15-17, 22): issue 10 assumes the per-request refresh lives on `/api/video`. After this build the refresh route is the one write path, and line 17's rule ("DB update and `instances.last_error` reset run only on a successful refresh") is delivered here. Line 22's integration check ("reflected after the next `/api/video` request") must name `/api/video/refresh`. Per the tracker convention this needs a comment on the issue, not an edit to its body. The risk is that the issue is planned later against stale wording.
docs/project/roadmap.md (line 54): the F2-M3 API-versioning item lists the unversioned routes it must version. `/api/video/refresh` becomes one more. One-word edit; the risk is none.

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Guarantee the persist on success.** The design step should run persist inside its own nested `statement_deadline(server.statement_timeout_seconds)`. `db.py:59-64` restores the outer deadline on exit, so nesting is safe. It changes one `with` line in the persist function and adds one child-process test. Without it, R2's "persists on success" can fail silently whenever the instance was slow, which is exactly the case the refresh exists for. The alternative is to record it as a known limitation, which costs nothing now but leaves R2 partly unmet.
2. **Fix persist's inputs.** The merge should return its intermediates (`title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`, `instance_domain`) alongside the response dict, and persist should take them. It costs one tuple or dict return and no behaviour change. Re-deriving them from the response would write `""` where today's code writes `NULL`.
3. **Tighten the success test.** Treat success as `isinstance(detail, dict) and detail`, not `is not None`. It costs one expression. It also closes the uncaught `AttributeError` on a non-object 200 and the "empty `{}` clears `last_error`" case.
4. **Settle rank 0 and the avatar.** The coordinator should keep the instance-config result separately (`instanceAvatarUrl`, plus name and URL for rank 2 only) and apply it inside `renderVideo`, rather than merging it into the metadata object. Then the rank-0 `renderVideo(null)` path also shows the avatar when the config arrives. It costs a module-level variable and two lines in `renderVideo`. The other choice is to leave rank 0 without an avatar, as today, which should be stated rather than left implicit.
5. **Doc updates.** Add the doc edits from new_impacts to the docs step: four route lists, one roadmap word, and a comment on issue 10 recording that its refresh write path and failure rule now exist on `/api/video/refresh`. About ten lines in total; no code.
6. **Pin both paths in the proxy test.** Pin both the refresh (one attempt, 20 s mapping) and `/api/video` (two attempts, 10 s) in one test, with the constants monkeypatched. It costs one stub-engine test in `tests/active/test_server.py` and protects the loop every browser read goes through.

## 2026-09-27 - Step 3 - Identify every file, function and doc affected

Recorded ungated, at the operator direction.

### impacts

<impacts>
<impact path="engine/server/api/handlers/video.py" element="handle_video_request() (lines 208-361), split into resolver, pure merge, persist, plus a /api/video handler and a /api/video/refresh handler">
**What changes.** The one function becomes three module-level helpers and two thin route handlers.
- **Resolver.** Takes lines 210-224. `id` falls back to `video_id` and `host` to `instance_domain` (210-211). It answers 400 `{"error": "Missing video id"}` and 404 `{"error": "Video not found"}`, and calls `fetch_video_row(..., error_threshold=server.video_error_threshold)` inside `with server.db_lock:`, which is held for 215-221 only.
- **Merge.** Takes lines 226-290 with `dynamic` passed in. Line 226, `instance_domain = row.get("instance_domain") or host_param or ""`, needs `host_param`, so the resolver has to hand back `host_param` or `instance_domain` along with the row.
- **Persist.** Takes lines 292-358. It needs the merged intermediates (`title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw`) plus `row["video_id"]`, `row["channel_id"]`, `row["published_at"]` and `instance_domain`. The response dict cannot supply them:
  - it has no `channel_slug`, `tags_json`, `category` or `nsfw`;
  - it turns `None` into `""` (`channelName: channel_display or ""`, `title or ""`).
  So feeding persist from the response would write `""` where today's code writes `NULL`. The plan says the merge "returns the response dict"; it must also expose the intermediates, or persist must re-derive them. The plan leaves this open.
- **`/api/video`.** Resolve, then merge with `{}`. Every `dynamic.get(...)` is `None`, so each field falls back to the row exactly as today. `accountAvatarUrl` (283) becomes `""`. `accountName`/`accountUrl` (281-282) already come from the row only.
- **`/api/video/refresh`.** Resolve, `fetch_instance_video_dynamic`, merge, persist only on success, then respond with the same shape.
- **Docstrings.** The module docstring (1-7, "Merge DB metadata with live instance metadata (when available)") and line 209 must say which route does what.

**What depends on it.** `engine/server/api/handlers/similar.py:84` imports `handle_video_request` by name, and `similar.py:495-497` calls it. Nothing else imports it. No test in `tests/active` touches this module (grep for `handlers.video`, `/api/video` and `fetch_instance` over `tests/`); only the smoke scripts call `/api/video`.

**Regression risk: medium.**
- **Lock boundary.** The instance call must stay outside `server.db_lock`, as today, where the lock is taken only around the SELECT (215) and around the UPDATEs (303). Pulling the fetch inside the resolver's `with` block would stall every Engine route that takes the lock (similar.py 261, 467, 652, 884, 957; similars included) for up to about 16 s, which breaks R7.
- **Renames.** A renamed or removed `handle_video_request` breaks the import at similar.py:84. That is an import-time failure of the whole Engine, and every test that uses the session `engine` fixture fails with it.
- **Races.** The row is read before the instance call and written after it, so two concurrent refreshes of one video both write and the last one wins. This is harmless.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_video_dynamic() (lines 162-205): return {} when the detail call fails">
**What changes.** Line 164 today is `detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}") or {}`. It becomes an early `return {}` when the detail call does not come back.

**The gotcha is confirmed.** The return at 188-205 always builds a 14-key dict, so the `if dynamic and instance_domain and row.get("video_id")` guard at 293 is always true today. A failed fetch therefore:
- writes DB values back;
- recomputes `popularity`;
- bumps `last_checked_at`;
- clears `instances.last_error*`.

**Edge cases for the success test.**
- **Non-dict JSON.** `fetch_instance_json` returns whatever `json.loads` gives. A 200 with a JSON array or string reaches `detail.get` and raises `AttributeError`, which nothing catches. This is pre-existing.
- **Empty object.** A 200 with `{}` passes an `is not None` test but carries no data, so persist would write DB values back and clear `last_error`.
- **The fix.** Testing `isinstance(detail, dict) and detail` closes both cases.

**Channel sub-call.** The sub-call at 176 runs only when `channel_slug` came back, so after the change it runs only on success.

**What depends on it.** Only `handle_video_request` today (grep of the tree, tests included), and only the refresh handler after the build.

**Regression risk: low.** This is the one deliberate behaviour change and the operator accepts it. The consequence: a failed fetch no longer resets `instances.last_error` or bumps `last_checked_at`.
</impact>
<impact path="engine/server/api/handlers/video.py" element="fetch_instance_json() (lines 75-87): unchanged; the test seam; narrow exception set">
**What changes.** Nothing. The R7 test and the refresh tests patch it.

**What depends on it.**
- Both instance calls in `fetch_instance_video_dynamic` look it up as a module global. A test must patch the attribute on the `handlers.video` module; patching an imported alias has no effect.

**The error path.**
- **What is not caught.** `except (HTTPError, URLError, TimeoutError)` misses `json.JSONDecodeError` (a non-JSON 200), `UnicodeDecodeError`, and `ConnectionResetError`/`http.client.RemoteDisconnected` raised during `resp.read()`.
- **What happens then.** These escape the refresh handler. `SimilarHandler.do_GET` (similar.py:433-441) re-raises anything that is not an interrupted `OperationalError`, so the Engine drops the connection without answering.
- **What the Client sees.** The drop reaches the Client as `RemoteDisconnected` or a reset, not as a `URLError`. It therefore lands in `except Exception` (client/backend/server.py:700-721), which answers 502 `ENGINE_PROXY_FAILURE`. The page treats that as a failed refresh (R3).
- **Before and after.** This is pre-existing: today the same failure kills `/api/video` itself. After the split only the refresh can hit it.
- **Timeout scope.** `timeout=8` bounds each socket operation, not the whole call.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/db.py" element="statement_deadline() / _deadline_passed() / PROGRESS_HANDLER_INSTRUCTIONS (lines 14-64), as it applies to the refresh's persist">
**What changes.** Nothing in code, but the refresh's timing brings this into play.

**How the deadline applies.**
- `SimilarHandler.do_GET` (similar.py:436) runs the whole dispatch inside `self._statement_deadline()` (similar.py:345-353). That is `statement_deadline(server.statement_timeout_seconds)`, and `DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0` (server_config.py:435) is assigned at `engine/server/api/server.py:272`.
- The deadline is wall-clock time, thread-local, and counted from the start of the request.
- The refresh reaches its UPDATEs only after up to about 16 s of instance calls, so by then its thread's deadline has usually passed.
- The progress handler fires every 10,000 VM instructions (line 14). Any persist statement that runs that long after the deadline is aborted with `OperationalError: interrupted`.
- The `videos` UPDATE fires `videos_fts_au` (`engine/server/db/jobs/sync-whitelist.py:279-284`), which deletes and re-inserts title, description, tags_json, category and channel_name into FTS5. Crossing 10,000 instructions is plausible there, especially with long descriptions.

**Consequence.**
- The persist's own `except sqlite3.OperationalError` (video.py:352-358) catches the abort, logs `[video] failed to persist dynamic metadata ... interrupted`, and `with server.db:` rolls back.
- The response is still 200 with the refreshed values, so a successful but slow refresh can silently fail to persist, against R2.
- This is pre-existing and masked today. After the build the refresh is the only writer, so it now matters.

**Mitigation.** Wrap persist in its own nested `statement_deadline(...)`. Lines 59-64 save and restore the outer deadline, so nesting is supported. The other option is to state it as a limitation.

**Regression risk: medium to high for R2's persist guarantee.** I have not measured whether one UPDATE plus the trigger actually crosses 10,000 instructions. A child-process test with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json` would show it.
</impact>
<impact path="engine/server/api/handlers/similar.py" element="SimilarHandler._dispatch_get() /api/video branch (lines 495-497), import at line 84, module docstring route list (lines 3-13)">
**What changes.**
- A new branch, `if url.path == "/api/video/refresh":`, goes beside line 495 and calls the refresh handler.
- The import at line 84 gains the new name or names.
- The docstring gains a `/api/video/refresh` line, and line 9 (`/api/video: single video metadata.`) should say it reads from the DB.

**What depends on it.**
- **Rate limit.** Line 447 rate-limits every path under `/api/` on the key `f"{ip}:{path}"` (`_rate_limit_check`, 576-583). The refresh therefore gets its own bucket (`DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60`, server_config.py:431). The ip comes from the `x-client-ip` header the Client sets (client/backend/server.py:590).
- **Matching.** Paths are matched with `==`. `_extract_video_id_from_similar_path` (499) matches only `/videos/.../similar`, so without the new branch `/api/video/refresh` falls through to the 404 at 508. Nothing shadows it.
- **Deadline.** Both routes run inside the statement deadline in `do_GET` (see the db.py entry). An interrupted error raised during the resolver's SELECT would still reach `_respond_interrupted` as a 503, but that SELECT is fast.

**Regression risk: low.** It is one branch, and the similars dispatch (499-506, `_handle_similar_request`) is untouched, which keeps R7.
</impact>
<impact path="engine/server/api/handlers/__init__.py" element="module docstring line 5 ('video: fetches video metadata for /api/video.')">
**What changes.** The line names both routes: `/api/video` (DB only) and `/api/video/refresh` (live instance refresh, persisted on success).

**What depends on it.** Nothing.

**Regression risk: none.**
</impact>
<impact path="engine/server/api/http_utils.py" element="respond_json() (lines 23-30), the refresh's final write">
**What changes.** Nothing.

**Why it matters.**
- It writes to `handler.wfile` unguarded.
- A slowly dripping instance can outlast the Client's 20 s proxy timeout, because `timeout=8` applies per socket operation. The Engine then writes its late answer to a socket the Client has already closed.
- The write raises `BrokenPipeError`/`ConnectionResetError`, which `do_GET` does not catch, so `socketserver` prints a traceback to stderr.
- By then persist has already run, so the data is kept, and the browser has already had its 502.
- This is pre-existing on `/api/video` at 10 s; after the build only the refresh can hit it.

Unlike this Engine helper, the Client side's `respond_bytes` already returns False when the client disconnects (server.py:619).

**Regression risk: low (log noise).**
</impact>
<impact path="engine/server/api/server.py" element="SimilarServer (ThreadingHTTPServer, line 207): video_error_threshold (230/264), popularity_like_weight (234/268), statement_timeout_seconds (272), db, db_lock">
**What changes.** Nothing.

**What depends on it.**
- The resolver reads `server.video_error_threshold` directly, not through `getattr`.
- Persist reads `getattr(server, "popularity_like_weight", 2.0)`, `server.db` and `server.db_lock`.
- `ThreadingHTTPServer` gives each request its own thread, so a refresh blocked on an instance holds one thread and not the server. R7 relies on this.

**Test note.** A child-process test needs a server object that carries `db`, `db_lock` and `video_error_threshold`, plus `popularity_like_weight` if persist runs and `statement_timeout_seconds` if the deadline is exercised. `tests/active/test_internal_events.py:52` builds a real `SimilarServer` from kwargs this way.

**Regression risk: none.**
</impact>
<impact path="engine/server/data/popularity.py" element="compute_popularity(), called by persist (video.py:295-301)">
**What changes.** Nothing. It moves with the persist block. Its arguments must stay:
- the merged `views`/`likes` (the instance value, or the DB fallback);
- `row["published_at"]`;
- the like weight;
- `now_ms_value=checked_at`.

**What depends on it.** The `videos.popularity` column, which ranking reads.

**Regression risk: low.** Today it runs on every page view, including failed fetches that write the DB values back unchanged. After the build it runs only on a successful refresh, and the popular-video ordering reads the same column.
</impact>
<impact path="engine/server/db/jobs/sync-whitelist.py" element="videos_fts_au AFTER UPDATE trigger (lines 279-284)">
**What changes.** Nothing.

**What depends on it.** Every persisted refresh fires the trigger and re-indexes the video for search. Writes fall from one per page view (failures included) to one per successful refresh, so FTS churn and write-lock time go down. It is also why the statement-deadline entry matters.

**Regression risk: none in code.**
</impact>
<impact path="engine/server/data/metadata.py" element="readers of videos.last_checked_at (lines 57, 98, 201); also data/random_videos.py (54-301), data/search.py (80), data/channels.py (129-159, instances.last_error*)">
**What changes.** Nothing.

**What depends on it.**
- These files only project `last_checked_at` and `instances.last_error*` into rows. A grep of `engine/server` (outside whitelist_migrations.py) shows nothing that filters or orders on them.
- The frontend source never reads `last_checked_at` (grep of `client/`, dist excluded).
- So the fast path no longer bumping them, and a failed refresh no longer clearing `last_error`, is invisible to serving.
- `/api/channels` exposes `last_error*` as data, so a stale error now stays visible there until a successful refresh or a crawl clears it.

**Regression risk: none in serving; low for the `/api/channels` display.** I did not audit the crawler (`engine/crawler`), which keeps its own DB.
</impact>
<impact path="engine/server/api/server_config.py" element="DEFAULT_STATEMENT_TIMEOUT_SECONDS = 5.0 (435), DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60 (431), line 455 comment ('Optional future toggle for /api/video hide behavior')">
**What changes.** Nothing.

**What depends on it.**
- The statement budget interacts with the refresh persist.
- The Engine's per-path rate limit now applies to the refresh as a separate bucket.
- The line 455 toggle is not referenced by video.py and stays unrelated.

**Regression risk: none.**
</impact>
<impact path="client/backend/server.py" element="PROXY_READ_GET_ROUTES (lines 81-83) and PROXY_ALLOWED_QUERY_PARAMS (lines 85-101)">
**What changes.**
- `"/api/video/refresh"` joins the frozenset.
- A new entry `"/api/video/refresh": {"id", "host"}` is added.
- `/api/video` keeps `{"id", "host", "refresh_cache", "user_id"}`.

**What depends on it.**
- `do_GET` (277-282) routes on `url.path in PROXY_READ_GET_ROUTES`. It applies `_rate_limit_check(url.path)` (406-409, key `ip:path`, `RATE_LIMIT_MAX_REQUESTS = 90` per 60 s), so the refresh gets its own Client bucket, then calls `_handle_engine_read_proxy_get`.
- `_handle_engine_read_proxy_get` (417-436) answers 400 on an unknown key or a repeated key, and strips values.
- The frontend must send only `id` and `host`: a `user_id` or `refresh_cache` on the refresh now gets 400.

**Regression risk: low.** It is a pure addition.
</impact>
<impact path="client/backend/server.py" element="_proxy_engine_request() (lines 570-745) with ENGINE_PROXY_TIMEOUT_SECONDS (77), ENGINE_PROXY_RETRY_COUNT (79), ENGINE_PROXY_RETRY_DELAY_SECONDS (80)">
**What changes.** A path→timeout mapping (20 s for the refresh, `ENGINE_PROXY_TIMEOUT_SECONDS` otherwise) and a per-path retry count (0 for the refresh, `ENGINE_PROXY_RETRY_COUNT` otherwise).

**Four sites must read the per-path values.**
- 604: `for attempt in range(ENGINE_PROXY_RETRY_COUNT + 1)`.
- 606: `urlopen(request, timeout=ENGINE_PROXY_TIMEOUT_SECONDS)`.
- 696: `if attempt < ENGINE_PROXY_RETRY_COUNT`.
- 731: the `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` field of the "proxy request unavailable" log. It is easy to miss; left alone it logs 2 attempts for a refresh that made 1.

**Key on `path`.** The mapping must use `path`, not `upstream`, which carries the query string (581-583).

**What depends on it.** Every proxied read:
- GET `/api/video`, `/api/channels` and `/api/v1/search/videos`;
- POST `/recommendations` and `/videos/similar` (561).

All of them must keep 10 s and one retry.

**How a refresh failure surfaces.**
- The Engine writes nothing until it finishes, so the proxy waits up to the full timeout.
- `socket.timeout` is `TimeoutError`, which lands in the `(URLError, TimeoutError)` branch (694). With 0 retries the loop breaks to the 502 `ENGINE_PROXY_UNAVAILABLE` (736-744).
- A dropped Engine connection lands in the generic 502 (700-721).
- An Engine 404 or 400 with a body passes through the HTTPError branch (646-677).
- All of these are non-OK for the browser.

**Test harness.** `tests/active/test_server.py` offers `_serving` (347-355), `_client_backend` (358-367), `_status` (370-378, `timeout=30`) and an `EngineStub` (400-422), which together are the template for a stub that counts GETs and sleeps. No existing test monkeypatches the proxy constants, so a new test can patch them or the mapping on `client_server` to stay fast.

**Regression risk: medium.** This loop carries every browser read. A wrong key or a missed site silently changes the timeout or retry for every route, so tests must pin both the refresh and one ordinary route.
</impact>
<impact path="client/backend/server.py" element="_handle_engine_read_proxy_get() (417-436) and _profile_filter() (438-469)">
**What changes.** Nothing.

**What depends on it.**
- The refresh gets the same sanitising.
- An empty value is dropped (431), so `id=` reaches the Engine with no `id` and gets its 400 `Missing video id`, which the Client passes through.
- `_profile_filter` returns `(True, None, None, None)` for the refresh, because it is in neither `FEED_ROUTES` nor `FILTERED_ROUTES` (71-72). An `X-Profile-Key` header on it is therefore ignored rather than validated.

**Regression risk: none.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="module top level: `void loadVideo()` (79), `void loadSimilarVideos()` (80), currentMetadata (50), seedId/seedHost (54-55), fallback (57-63), localLikesImported (75-77), applyActionIcons() (1226)">
**What changes.** Line 79 becomes the coordinator start. Line 80 is unchanged.

**What the coordinator must preserve.**
- **No usable source.** When `resolveVideoSource()` gives no host or no id, `fetchVideoMetadata` returns `null` at 508, and today the page renders once with `metadata = null` from `fallback`, `seedHost` and `https://${seedHost}`. That must be kept, and in that case neither the fast fetch nor the refresh should fire.
- **`currentMetadata` in step.** It must always equal the metadata actually rendered, because `reactionVideo()` (381-386) reads it through `resolveLikeUuid`/`resolveLikeHost` (1151-1166).

**Testing constraints.** The module does DOM work at import:
- about 27 `getElementById` constants (22-48);
- `window.location.search` (53);
- `importLocalLikes` (75);
- `applyActionIcons()` (1226);
- `import "../../video.css"` (5).

A node test of the page therefore needs a stubbed `document`/`window`, a scripted `fetch`, `localStorage`, and an esbuild css loader flag. The existing frontend tests (`test_frontend_blocks.py:23,66`, `test_frontend_videos.py`, `test_frontend_reactions.py`, `test_frontend_profile.py`) bundle data modules only, with `--platform=node`.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadVideo() (lines 85-229) becoming renderVideo(metadata)">
**What changes.** The body stays, minus `await fetchVideoMetadata()` (86). `currentMetadata = metadata` (87) moves into or next to it. It now runs once per accepted source, and again when the instance config arrives.

**What re-runs on every render.**
- **Text and markup.** Title, the channel `innerHTML` through `escapeHtml`/`safeExternalUrl` (120-122), subscribers, instance link, account link, description, views, counts and the original link. All of these are idempotent.
- **Avatars.** `channelAvatarEl.innerHTML` (129) and the instance and account avatars (154-161, 179-186) are rewritten, and `bindAvatarFallback` (426-437) binds a `once` listener to each fresh `<img>`. The old nodes are discarded, so listeners do not pile up, though an image may flicker.
- **Embed (212-221).** Today it sets `embedEl.src = embed` unconditionally. The new `lastEmbed` guard must compare against the checked string actually assigned, and must be cleared when the `else` branch calls `removeAttribute("src")`; otherwise a later valid identical URL is never reassigned.
- **`document.title`** (114).
- **`enableBlockButtons`** (196) is guarded by `dataset.wired`.
- **`void loadReaction()`** (197) needs the new gate (see its entry).

**Values across sources.**
- The Engine sends `""`, not null, for empty strings, so `metadata?.title ?? fallback.title` gives `""`, and `titleEl` shows "Video page" through `title || "Video page"`, as today.
- Ranks 1 and 3 both carry `embedUrl = resolve_asset_url(instance_domain, row.embed_path)`, which is textually identical, so there is no reload between them.
- Rank 0 uses `fallback.embed` and rank 2 uses `resolveApiAssetUrl(host, embedPath)` (592). So when the fast call fails, one iframe reload between rank 0 and a later rank is possible. R6 covers only an unchanged URL.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadata() (506-512) and fetchVideoMetadataFromServer() (517-555)">
**What changes.**
- The sequential "server, else instance" logic in `fetchVideoMetadata` moves into the coordinator.
- `fetchVideoMetadataFromServer` drops `await fetchInstanceMetadata(source.host)` (525). It must now serve both `/api/video` and `/api/video/refresh`, through a path argument or a shared mapper; the refresh answers the same shape, so the mapping at 527-551 applies unchanged.

**Precedence, confirmed in code.**
- The Engine always sends `instanceName`/`instanceUrl` as strings (video.py:279-280, possibly `""`), and `??` does not skip `""`. So for ranks 1 and 3, `instanceMeta?.name`/`url` never win today (534-539); the config supplies only `instanceAvatarUrl` (540).
- For rank 2 (608-610), the config's name and URL do win.
- If re-applying the shared config overwrote `instanceName` for ranks 1 and 3, the chip label would visibly change from the host to the display name. It would also change `resolveLikeHost` when `seedHost` is empty.

**Other effects.**
- `catch { return null; }` (552-554) also swallows `response.json()` failures and non-OK statuses. The refresh caller needs its own failure signal to `console.warn`.
- `instanceAvatarUrl` must be merged in from the shared promise on every render, or it disappears when a later rank re-renders.

**Regression risk: medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchVideoMetadataFromInstance() (560-625) and fetchChannelMetadata() (630-650)">
**What changes.** `await fetchInstanceMetadata(source.host)` (600) is replaced by the shared promise. The awaited `fetchChannelMetadata` (599) stays, because it is part of rank 2 itself.

**Behaviour to keep.**
- The rank-2 result has no `videoUuid`, so `resolveLikeUuid` falls back to `seedId` only when `looksLikeUuid` (1171-1173) accepts it.
- `instanceName: instanceMeta?.name ?? source.host` (608) can be `""`, because `getString` returns `""` (724-730). `instanceMetaEl.hidden = !instanceName` (140) then hides the chip. This is pre-existing.
- It runs only after the fast fetch fails (R5). If rank 3 is already shown, the rank rule drops its result, so the coordinator could skip starting it.

**Regression risk: low to medium.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="fetchInstanceMetadata() (655-688) and getString() (724-730), as one shared promise">
**What changes.** It is called once per load, and the promise is shared.

**What it returns.**
- `getString` returns `""`, never undefined, so the `?? ... ?? host` chain at 664-667 never reaches `host`.
- `avatarUrl` is always set on success, falling back to `https://${host}/favicon.ico`.
- Any failure, including a CORS failure, resolves to `null` and never rejects, so a `.then` needs no `.catch`.

**What depends on it.**
- The instance avatar on every rank, and the name and URL on rank 2.
- When it resolves, the current best metadata is re-rendered at the same rank, so the rank rule must allow equal-rank renders ("at least the rank shown").
- Rank 0 renders with `null` metadata, so if the avatar should appear there, it has to be applied in `renderVideo` from a module variable, not merged into the metadata object.

**Constraint.** It may start only once a host is known.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadReaction() (318-341), reactionVideo() (381-386), react()/renderReaction() (346-364)">
**What changes.** A module-level `uuid|host` key for the last reaction fetched gates `fetchReaction`.

**How the gate must work.**
- **Non-null video only.** `reactionVideo()` depends on `currentMetadata`. On a rank-0 or rank-2 render with a non-UUID `seedId` it returns `null`, and `loadReaction` returns at 320 without wiring the buttons. A later rank that carries `videoUuid` (1 or 3) must still fetch and wire, so the key is set only when `video` is non-null.
- **Before the first await.** `await localLikesImported` (322) comes before the fetch, so the key must be written before that first `await`. Otherwise two quick renders both pass the gate and fetch twice.
- **Listeners.** The listeners (331-340) capture the first non-null `video` and are never rewired, because of `likeButton.dataset.wired` (327). This is unchanged.

**What depends on it.** `renderReaction` and `setReactionStatus`. `tests/active/test_frontend_reactions.py` exercises `data/reactions.ts`, not this page.

**Regression risk: medium.** A wrong gate either breaks R6 (a second fetch) or leaves the buttons disabled when the uuid arrives only with a later rank.
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="enableBlockButtons() (275-308)">
**What changes.** Nothing. The `button.dataset.wired` guard (282) makes re-renders no-ops.

**What depends on it.**
- It captures `uuid` and `host` from the first call where both are non-empty.
- On a rank-0 render, `metadata?.videoUuid || resolveVideoSource()?.id` (196) is `seedId`, which may be a numeric id, and the buttons keep it for good.
- That already happens today when `/api/video` fails. It is more reachable now, if the fast call fails and the refresh brings the real uuid later.
- I did not trace whether `blockVideoSource` resolves a numeric id.

**Regression risk: low.**
</impact>
<impact path="client/frontend/src/pages/video-page/index.ts" element="loadSimilarVideos() (234-269) and the similar stats helpers">
**What changes.** Nothing (R7). It waits only on `localLikesImported` and never on metadata.

**Regression risk: none,** as long as the coordinator neither awaits it nor chains it.
</impact>
<impact path="client/frontend/video-page.html" element="CSP meta (line 8)">
**What changes.** Nothing.

**What depends on it.**
- `connect-src 'self' https:` already allows the same-origin `/api/video/refresh` and the browser→instance fetches.
- `frame-src https:` matches the embed's `https://` check.

**Regression risk: none.**
</impact>
<impact path="client/frontend/dist/assets/video-gjYm1MC8.js" element="built video page bundle (build output)">
**What changes.** The build regenerates it under a new hash; it is never edited by hand.

**What depends on it.** The deployed static site serves `dist`.

**Regression risk: low.** A stale `dist` deployed against the new Engine still works, because `/api/video` keeps its shape. It just no longer gets live values or the account avatar.
</impact>
<impact path="client/frontend/vite.config.ts" element="dev server proxy '/api' (lines 27-28)">
**What changes.** Nothing. The `/api` prefix already covers `/api/video/refresh` in dev.

**Regression risk: none.** I did not check whether a dev proxy timeout is set.
</impact>
<impact path="tests/check-frontend-client-gateway.sh" element="frontend gateway preflight (lines 22-38)">
**What changes.** Nothing. It forbids only:
- Engine base usage;
- hard-coded Engine ports;
- `/internal/*` routes in `client/frontend/src`.

A `/api/video/refresh` literal passes.

**Regression risk: none.**
</impact>
<impact path="DEPLOYMENT.md" element="nginx `location /api/` (319-325); ufw prose (369, 374-375)">
**What changes.**
- **nginx block.** Needs nothing. `location /api/` already proxies `/api/video/refresh`, and no `proxy_read_timeout` is set, so nginx's 60 s default exceeds 20 s.
- **ufw comment (369).** "live video metadata" stays true.
- **Prose at 374-375.** "`/api/video` makes live calls to source instances per request" becomes wrong (see the docs checklist).

**Regression risk: none in config.**
</impact>
<impact path="tests/active/conftest.py" element="engine fixture (105-140) over WHITELIST_DB (34); ENGINE_PY (32); ENGINE_SERVER (33); CLOSED_ENGINE (45)">
**What changes.** Nothing.

**What new tests must avoid.**
- A refresh through the session `engine` fixture would make real outbound HTTPS calls and write to the shared `whitelist.db`.
- Refresh tests and the R7 test must run the handler in an `ENGINE_PY` child over a temporary DB, with `handlers.video.fetch_instance_json` patched.
- Precedents: `test_internal_client_reads.py:144-145`, `test_internal_events.py:52,174`, and the child runs in `test_similar.py` (237, 307, 415, 533).
- A fast `/api/video` against the shared Engine is safe after the build (no calls, no writes).

**Regression risk: medium for test hygiene.**
</impact>
<impact path="tests/active/test_server.py" element="_serving/_client_backend/_status/EngineStub pattern (lines 347-422)">
**What changes.** Nothing. It is the template for the new proxy test.

**The new test.** A stub Engine counts GETs and sleeps past a monkeypatched timeout on `/api/video/refresh`. It checks two things:
- the refresh makes one attempt;
- `/api/video` still retries once.

**Test group.** The file maps to `client/backend/server.py` and `engine/server/api/handlers/similar.py` in `.un/skills/devsecops/config.json` (57-60).

**Regression risk: low.**
</impact>
<impact path=".un/skills/devsecops/config.json" element="test_groups mapping">
**What changes.** Nothing during the build.

**Coverage gaps.** Grep finds no mapping for `engine/server/api/handlers/video.py` or `client/frontend/src/pages/video-page/index.ts`. Any new test file for them needs an entry at harvest, or it runs only in full-suite runs.

**Regression risk: low.**
</impact>
<impact path="tests/run-arch-split-smoke.sh" element="client_video_proxy check (line 582); also tests/run-installers-smoke.sh (line 647) and README.md line 134">
**What changes.** Nothing is required: `/api/video` still answers 200, and faster.

**Optional.** A `/api/video/refresh` check would depend on outbound 443, so asserting "200 or 502" is safer.

**Regression risk: none.**
</impact>
<impact path="docs/project/security-audit/run-1/REPORT.md" element="line 299 (`/api/video` performs up to two outbound HTTPS requests); also run-1/architecture.md:35,67, run-1/FINDINGS-DETAIL.md:127, run-2/REPORT.md:73,125,221, run-2/FINDINGS-DETAIL.md:12,136, run-2/findings.json">
**What changes.** Nothing. These are dated audit records and are not rewritten. I list them only because a grep for `/api/video` hits them and they describe the old behaviour.

**Regression risk: none.**
</impact>
<impact path="docs/project/plans/19-11-fast-similars-response.record.md" element="workflow record for this build">
**What changes.** The workflow renders it; do not hand-edit it. It already holds an earlier step-3 pass. I re-read the files it names, and its line numbers still match the tree.

**Regression risk: none.**
</impact>
</impacts>

### docs_checklist

<doc path="engine/server/README.md">
Line 9 (`/api/video` metadata for the video page) becomes two bullets:
- `/api/video` answers from the local DB only, with no instance call and no write. The response shape is unchanged, and `accountAvatarUrl` is empty.
- `/api/video/refresh` fetches live metadata from the source instance: video detail, then channel, with an 8 s socket timeout on each. It answers the same shape. Only when the detail call succeeds does it run the `videos`/`channels` UPDATE and reset `instances.last_error*`; a failed fetch writes nothing. It is the one per-request metadata write path.

Line 3 ("Read-only Engine API") should acknowledge that the refresh route writes metadata.
</doc><doc path="README.md">
The boundary table at line 46 (Engine public read API) and line 48 (Client browser-facing read gateway): add `/api/video/refresh` to both route lists. Line 134 (the smoke check expects `/api/video` to answer 200) stays true.
</doc><doc path="client/README.md">
Line 37 (read gateway list): add `/api/video/refresh`. Optionally note that the refresh proxy accepts only `id` and `host`, waits up to 20 s and is not retried, while every other read proxy keeps 10 s with one retry.
</doc><doc path="client/frontend/README.md">
Line 8 (fetched gateway routes): add `/api/video/refresh`. Optionally add one sentence on the video page's load order:
- it renders from `/api/video` first;
- it re-renders when the refresh and the instance config arrive;
- when `/api/video` fails, it falls back to the URL params and then to the direct instance fetch.
</doc><doc path="DEPLOYMENT.md">
Lines 374-375: "`/api/video` makes live calls to source instances per request" becomes `/api/video/refresh`, one live refresh per video page view. The ufw comment at 369 and the nginx block at 319-325 need no change.
</doc><doc path="docs/project/issues/10-video-metadata-completeness.md">
Add a comment rather than editing the body:
- Line 22 ("reflected after the next `/api/video` request") now applies to `/api/video/refresh`.
- Line 17's rule ("the DB update and `instances.last_error` reset run only on a successful refresh") is now real behaviour, delivered by this build.
- The refresh handler in `engine/server/api/handlers/video.py` is the single per-request write path this issue extends.
- Line 16 stays true.
</doc><doc path="docs/project/issues/20-request-lifecycle-logs.md">
Line 25 (smoke list naming `/api/video`): add `/api/video/refresh`. It is the long-running, instance-bound route whose start→end logging matters most.
</doc><doc path="docs/project/roadmap.md">
Line 54 (F2-M3 API versioning lists the unversioned routes): add `/api/video/refresh`.
</doc><doc path="docs/project/issues/11-fast-similars-response.md">
At harvest:
- set `Status: enhancement, complete`;
- add a delivery comment recording the two-phase reading, the 20 s no-retry refresh budget, and the accepted `last_error`/`last_checked_at` change;
- move the file to `docs/project/issues/archive/`.
</doc>

### highest_risk

engine/server/data/db.py statement_deadline, applied to the refresh persist in engine/server/api/handlers/video.py: `SimilarHandler.do_GET` (similar.py:436) starts a 5 s wall-clock deadline (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`) when the request begins, but the refresh reaches its UPDATEs only after up to about 16 s of instance calls. Any persist statement, including the `videos_fts_au` FTS trigger, that runs past 10,000 VM instructions after that deadline is aborted as `interrupted`, and persist's own `OperationalError` catch swallows the abort. A slow but successful refresh can therefore silently not persist, against R2. A nested `statement_deadline` around persist fixes it; I have not measured whether the threshold is actually crossed.
client/backend/server.py _proxy_engine_request (570-745): the per-path timeout and retry change sits in the loop every browser read goes through. Four sites must switch (604, 606, 696, and the `attempts` log field at 731), and the lookup must key on `path`, not on `upstream`, which carries the query string. A mistake silently changes the 10 s timeout and single retry of `/api/video`, `/api/channels`, search and the feed POSTs. Tests must pin the refresh at one attempt and an ordinary route at two.
client/frontend/src/pages/video-page/index.ts renderVideo/loadReaction/fetchVideoMetadataFromServer: code written to render once now renders several times, and three rules keep it correct. First, the `lastEmbed` guard must be cleared when `src` is removed. Second, the reaction gate must be written before the first `await` and only for a non-null `reactionVideo()`; otherwise the reaction is fetched twice, or the buttons stay unwired when the uuid arrives only with a later rank. Third, the Engine always sends `instanceName`/`instanceUrl` as strings, so for ranks 1 and 3 the shared instance config may add only the avatar; overwriting the name visibly changes the chip label.

## 2026-09-27 - Step 4 - Reassess the implementation plan (pass 3)

Pass 3. New impacts: none.

I checked every inventory entry that makes a claim about code, and all of them held. I read all of `engine/server/api/handlers/video.py`; `similar.py` 330-590 (deadline wrapper, `do_GET`, `_dispatch_get`, rate limit); `client/backend/server.py` (constants 60-105, `do_GET` 273-282, `_rate_limit_check`, `_handle_engine_read_proxy_get`, `_profile_filter`, `_proxy_engine_request` 570-745); `engine/server/data/db.py` 1-90; `respond_json`; the `videos_fts_au` trigger; the `test_server.py` harness at 347-422; and all of `client/frontend/src/pages/video-page/index.ts`. I grepped for other users of the proxy constants, of `handle_video_request`/`fetch_instance_video_dynamic`, and of `last_error`/`last_checked_at` in the Engine's Python. I found nothing the inventory lacks. The five documents an earlier step-4 pass reported (four route lists and issue 10), plus the roadmap line, are already in this build's docs checklist in the record, so I am not reporting them again. The plan works as intended. It has two design gaps, both already named in the inventory: persist's inputs, and the statement deadline over persist.
<question id="1">
Yes, it works as intended. What the code confirms:
- **R1.** With `dynamic = {}`, every field at video.py 229-290 falls back to the row. `accountAvatarUrl` (283) becomes `""`, and nothing else changes.
- **R2's success signal.** `fetch_instance_video_dynamic` always returns a 14-key dict (188-205). The guard at 293 is therefore always true today, so the early `return {}` is what makes "no write on failure" real.
- **R7.** `db_lock` is held only around the SELECT (215-221) and the UPDATEs (303-351). The instance call is outside the lock, and `SimilarServer` is a `ThreadingHTTPServer`, so a slow refresh cannot delay similars as long as the split keeps the call outside the lock.
- **Proxy.** The constants are used only in `_proxy_engine_request`, at 604, 606, 696 and 731; grep finds no other user. A per-path lookup in that one function covers the change. Every refresh failure mode reaches the browser as non-OK:
  - a timeout lands in the `(URLError, TimeoutError)` branch and ends as a 502 `ENGINE_PROXY_UNAVAILABLE`;
  - a dropped Engine connection lands in the generic 502;
  - an Engine 404 or 429 with a body passes through.
  R3's degrade path therefore holds.
- **Frontend.** The only instance awaits on the render path are at 525 and 600, as the plan says. `fetchInstanceMetadata` never rejects.

Two things only the design step can settle, both already in the inventory:
- **Persist deadline.** Persist runs under a 5 s deadline that is counted from the start of the request (similar.py 436, db.py 59-60). After a slow instance, the UPDATE and FTS trigger (sync-whitelist.py 279-284) can be aborted as `interrupted`. The `except` at 352 swallows that, so R2's "persists on success" can fail without any error.
- **Persist inputs.** Persist needs the merge's intermediate values, which the response dict does not carry.
</question>
<question id="2">
- **Requests per view.** Each page view makes two Client→Engine metadata requests. Each has its own `ip:path` rate-limit bucket on both tiers: Client, 90 per 60 s; Engine, 60 per 60 s.
- **Held threads.** On a slow instance, one Client thread and one Engine thread are held for up to 20 s.
- **Fewer writes.** DB and FTS writes drop from one per view (failures included) to one per successful refresh.
- **Error and timestamp columns.** `last_checked_at` and `instances.last_error*` stop being touched on failure. Nothing in `engine/server` filters on them; `data/channels.py` 129-159 only exposes them.
- **Log noise.** A late Engine write to a closed proxy socket raises in `respond_json`, which is unguarded (http_utils.py 30). This is noise only.
- **Instance calls.** The refresh becomes the only route that reaches the instance, so its uncaught errors (JSONDecodeError and similar) now affect only the refresh, not the page's first render.
</question>
<question id="3">
Everything required is already in the inventory:
- **Import.** `similar.py:84` must import the new names; if one is missing, the whole Engine fails at import time.
- **Proxy sites.** All four proxy sites must read the per-path values, keyed on `path`, not `upstream`.
- **Deadline.** Persist must run under its own `statement_deadline` (nesting is supported at db.py 59-64), or the gap is stated as a limitation.
- **Merge output.** The merge must return its intermediates so that persist writes `NULL`, not `""`.
- **Frontend rules:**
  - `lastEmbed` is cleared on the `removeAttribute("src")` branch;
  - the reaction gate is set only for a non-null `reactionVideo()`, and before `await localLikesImported`;
  - for ranks 1 and 3, the instance config supplies only the avatar, because the Engine always sends `instanceName` as a string (279) and `??` does not skip `""`;
  - nothing is fetched when `resolveVideoSource()` gives no host or id.
- **Docs.** The docs checklist edits.
</question>
<question id="4">
- **`/api/video`** becomes DB-only: faster, `accountAvatarUrl` always `""`, no instance call, no write.
- **Live values** arrive through `/api/video/refresh`, and are persisted only when the detail call succeeds.
- **A failed fetch** no longer writes DB values back, recomputes `popularity`, bumps `last_checked_at` or clears `instances.last_error*`.
- **Proxy.** The refresh gets 20 s and no retry; every other route keeps 10 s and one retry.
- **Page.** It renders before the instance config arrives and may re-render up to three times. The instance avatar fills in late.
- **Iframe.** When the fast call fails, one iframe reload between `?embed=` and a later embed URL is possible.

Similars, the response shape, the 400/404 answers, escaping and `safeExternalUrl` are unchanged.
</question>

New impacts:
none

Inventory entries that did not hold up:
none

Conflicts: none

Recommendations: 1. **Run persist under its own `statement_deadline(server.statement_timeout_seconds)`.** It changes one `with` line in the persist function, plus one child-process test that runs with a lowered `statement_timeout_seconds` and a sleeping `fetch_instance_json`. Without it, a slow but successful refresh can quietly fail to persist, and slow instances are exactly the case the refresh exists for. The alternative is to record it as a limitation, which costs nothing now but leaves R2 partly unmet.
2. **Have the merge return its intermediates next to the response dict, and have persist take those.** The intermediates are `title`, `description`, `channel_display`, `channel_slug`, `channel_followers`, `views`, `likes`, `dislikes`, `tags_json`, `category`, `nsfw` and `instance_domain`. This costs one extra return value and changes no behaviour. Re-deriving them from the response would write `""` where today's code writes `NULL`.
3. **Treat the detail call as successful only when `isinstance(detail, dict) and detail`.** This costs one expression. It also closes the uncaught `AttributeError` on a non-object 200, and stops an empty `{}` from clearing `last_error`.
4. **Keep the instance-config result in a module variable and apply it inside `renderVideo`.** Use the avatar on every rank, and the name and URL on rank 2 only, instead of merging it into the metadata object. This costs one variable and a few lines, and it lets the rank-0 `renderVideo(null)` path show the avatar too. Alternatively, state plainly that rank 0 shows no avatar.
5. **Pin both routes in one stub-Engine test in `tests/active/test_server.py`, with the proxy constants monkeypatched.** The refresh should make one attempt under the 20 s mapping; `/api/video` should make two attempts at 10 s. This costs one test and protects the loop every browser read goes through.
6. **Take the docs checklist as recorded.** It costs about ten lines of documentation and no code.

## 2026-09-27 - Step 5 - Draft the initial implementation

Recorded ungated, at the operator direction.

### draft

## Draft implementation: two-phase video metadata (issue 11)

### Module map

| File | Change |
|---|---|
| `engine/server/api/handlers/video.py` | `fetch_instance_video_dynamic` returns `{}` on a failed detail call. `handle_video_request` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`. `handle_video_request` (DB only) keeps its name; `handle_video_refresh_request` is new. Module docstring updated. |
| `engine/server/api/handlers/similar.py` | Import gains `handle_video_refresh_request`. New `/api/video/refresh` dispatch branch. Docstring route list updated. |
| `engine/server/api/handlers/__init__.py` | Docstring line 5 names both routes. |
| `client/backend/server.py` | Route and allow-list entries. Two per-path mappings (timeout, retry count), read at four sites in `_proxy_engine_request`. |
| `client/frontend/src/pages/video-page/index.ts` | `loadVideo` → `renderVideo(metadata)`. Coordinator `startVideoLoad` with rank arbitration. Shared instance-config promise. Embed and reaction guards. `fetchVideoMetadataFromServer(path, source)`. `fetchVideoMetadata` removed. |
| Docs | `engine/server/README.md`, `README.md`, `client/README.md`, `client/frontend/README.md`, `DEPLOYMENT.md`, issue/roadmap comments, per the settled checklist. |

`dist/` is regenerated by the build.

---

### Engine: `engine/server/api/handlers/video.py`

**Module docstring**

```python
"""Video metadata endpoint handlers.

Responsibilities:
- Resolve video row by id/uuid/host.
- /api/video: answer from the DB row only, with no instance call and no write.
- /api/video/refresh: fetch live instance metadata, merge it over the row field by field, persist it when the instance answered, and answer the same shape.
"""
```

**New imports**, in the file's existing style:

```python
from data.db import statement_deadline
from server_config import DEFAULT_STATEMENT_TIMEOUT_SECONDS
```

**`fetch_instance_video_dynamic`: success signal.** Only line 164 changes; the rest of the function is untouched.

```python
    detail = fetch_instance_json(host, f"/api/v1/videos/{quote(video_id)}")
    # An empty dict tells the caller the instance did not answer, so nothing is persisted.
    if not isinstance(detail, dict) or not detail:
        return {}
```

- Invariant: it returns `{}` if and only if the detail call failed or came back as a non-dict or empty JSON value. Otherwise it returns today's 14-key dict.
- A non-dict JSON body no longer reaches `detail.get` and raises `AttributeError`.
- The channel sub-call now runs only on success. When it fails, the channel fields fall back to the DB in the merge, and the result still counts as success.

**`resolve_video_row`**, which takes lines 210-224 and 226:

```python
def resolve_video_row(
    handler: Any,
    server: Any,
    params: dict[str, list[str]],
) -> tuple[dict[str, Any], str, str] | None:
    """Resolve the requested row, or answer 400/404 and return None.

    Returns the row, the requested id and the instance domain the merge and refresh use.
    """
    id_param = params.get("id", params.get("video_id", [None]))[0]
    host_param = params.get("host", params.get("instance_domain", [None]))[0]
    if not id_param:
        respond_json(handler, 400, {"error": "Missing video id"})
        return None
    with server.db_lock:
        row = fetch_video_row(
            server.db,
            id_param,
            host_param,
            error_threshold=server.video_error_threshold,
        )
    if not row:
        respond_json(handler, 404, {"error": "Video not found"})
        return None
    instance_domain = row.get("instance_domain") or host_param or ""
    return row, id_param, instance_domain
```

The lock covers the SELECT only.

**`merge_video_metadata`**, which takes lines 229-290 verbatim:

```python
def merge_video_metadata(
    row: dict[str, Any],
    dynamic: dict[str, Any],
    instance_domain: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge live `dynamic` fields over the DB row, field by field.

    Returns the response payload and the merged column values the persist step writes.
    An empty `dynamic` gives the DB-only answer.
    """
    # lines 229-290 unchanged: title … nsfw, channel_url, embed_url, original_url, response
    merged = {
        "title": title,
        "description": description,
        "channel_display": channel_display,
        "channel_slug": channel_slug,
        "channel_followers": channel_followers,
        "views": views,
        "likes": likes,
        "dislikes": dislikes,
        "tags_json": tags_json,
        "category": category,
        "nsfw": nsfw,
    }
    return response, merged
```

- **The impact inventory's open point.** `merged` carries the raw intermediates, `None` included, so persist writes `NULL` where today's code writes `NULL` and never the response's `""`.
- The function is pure: no DB access and no I/O.
- With `dynamic={}`, every `dynamic.get` is `None`, so each field falls back to the row exactly as today, and `accountAvatarUrl` is `""`.

**`persist_video_metadata`**, which takes lines 294-358:

```python
def persist_video_metadata(
    server: Any,
    row: dict[str, Any],
    instance_domain: str,
    merged: dict[str, Any],
) -> None:
    """Write a successful refresh to the videos, channels and instances tables.

    The writes run under a fresh statement budget taken once the DB lock is held, because the request's own budget is mostly spent on the instance calls by then.
    """
    checked_at = now_ms()
    popularity = compute_popularity(
        merged["views"],
        merged["likes"],
        row.get("published_at"),
        float(getattr(server, "popularity_like_weight", 2.0)),
        now_ms_value=checked_at,
    )
    channel_id = row.get("channel_id")
    try:
        with server.db_lock:
            with statement_deadline(
                float(getattr(server, "statement_timeout_seconds", DEFAULT_STATEMENT_TIMEOUT_SECONDS))
            ):
                with server.db:
                    # today's three UPDATEs, parameters read from `merged` and `row`, unchanged SQL
    except sqlite3.OperationalError as exc:
        logging.warning(
            "[video] failed to persist dynamic metadata for video_id=%s host=%s: %s",
            row.get("video_id"),
            instance_domain,
            exc,
        )
```

- **Why the nested deadline.** The settled db.py entry picks this mitigation. Without it the outer deadline has usually expired after roughly 16 s of instance calls, and the FTS trigger's UPDATE could be interrupted, which silently breaks R2's persist.
- **Why it sits inside `db_lock`.** Time spent waiting for the lock does not use up the new budget.
- **Nesting is safe.** `statement_deadline` restores the outer deadline on exit (db.py:59-64).
- **The rest is today's code.** The SQL, the parameter order, the `channels` UPDATE only when `channel_id` is set, the `instances` reset, and the catch-and-log.

**Route handlers**

```python
def handle_video_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video: answer from the DB row only, with no instance call and no write."""
    resolved = resolve_video_row(handler, server, params)
    if resolved is None:
        return True
    row, _id_param, instance_domain = resolved
    response, _merged = merge_video_metadata(row, {}, instance_domain)
    respond_json(handler, 200, response)
    return True


def handle_video_refresh_request(handler: Any, server: Any, params: dict[str, list[str]]) -> bool:
    """Handle /api/video/refresh: fetch live metadata, persist it when the instance answered, answer the merge.

    This is the single per-request metadata write path; issue 10 extends it.
    """
    resolved = resolve_video_row(handler, server, params)
    if resolved is None:
        return True
    row, id_param, instance_domain = resolved
    # The instance calls run outside the DB lock, so a slow instance never stalls other routes.
    dynamic = fetch_instance_video_dynamic(instance_domain, id_param) if instance_domain else {}
    response, merged = merge_video_metadata(row, dynamic, instance_domain)
    if dynamic and instance_domain and row.get("video_id"):
        persist_video_metadata(server, row, instance_domain, merged)
    respond_json(handler, 200, response)
    return True
```

- Keeping the name `handle_video_request` means the import at similar.py:84 cannot break.
- The `if dynamic` guard is now meaningful, because a failed fetch returns `{}`.

### Engine: `engine/server/api/handlers/similar.py`

- **Line 84:** `from handlers.video import handle_video_refresh_request, handle_video_request`.
- **After line 497:**
  ```python
          if url.path == "/api/video/refresh":
              handle_video_refresh_request(self, self.server, params)
              return
  ```
- **Docstring lines 9-10:**
  - `- /api/video: single video metadata from the local DB (no instance call).`
  - `- /api/video/refresh: live instance refresh of one video's metadata, persisted on success.`
- **Unchanged:** the rate limit at 447 (its own `ip:/api/video/refresh` bucket), the statement deadline in `do_GET`, and the similars dispatch.

### Engine: `engine/server/api/handlers/__init__.py`

Line 5 becomes: `- video: /api/video (DB only) and /api/video/refresh (live instance refresh, persisted on success).`

---

### Client backend: `client/backend/server.py`

**Constants**, next to lines 77-101:

```python
ENGINE_PROXY_TIMEOUT_SECONDS = 10
# The refresh waits on up to two 8 s instance calls in the Engine, and a retry would repeat them and the write.
ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS: dict[str, float] = {"/api/video/refresh": 20}
ENGINE_PROXY_MAX_BODY_BYTES = 1_000_000
ENGINE_PROXY_RETRY_COUNT = 1
ENGINE_PROXY_ROUTE_RETRY_COUNT: dict[str, int] = {"/api/video/refresh": 0}
ENGINE_PROXY_RETRY_DELAY_SECONDS = 0.25
PROXY_READ_GET_ROUTES = frozenset(
    ("/api/video", "/api/video/refresh", "/api/channels", "/api/v1/search/videos")
)
PROXY_ALLOWED_QUERY_PARAMS: dict[str, set[str]] = {
    ...
    "/api/video": {"id", "host", "refresh_cache", "user_id"},
    "/api/video/refresh": {"id", "host"},
    ...
}
```

The plan asked for "a path check on the retry count". A second one-entry dict does the same job, with the same shape as the timeout mapping and one more place a test can monkeypatch.

**`_proxy_engine_request`.** Two locals are resolved once, from `path` (never from `upstream`, which carries the query string), right after `upstream` is built. The mappings are module globals read at call time, so a test that patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` takes effect.

```python
        timeout_seconds = ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS.get(path, ENGINE_PROXY_TIMEOUT_SECONDS)
        retry_count = ENGINE_PROXY_ROUTE_RETRY_COUNT.get(path, ENGINE_PROXY_RETRY_COUNT)
```

Four sites change:

| Line | Before | After |
|---|---|---|
| 604 | `range(ENGINE_PROXY_RETRY_COUNT + 1)` | `range(retry_count + 1)` |
| 606 | `timeout=ENGINE_PROXY_TIMEOUT_SECONDS` | `timeout=timeout_seconds` |
| 696 | `attempt < ENGINE_PROXY_RETRY_COUNT` | `attempt < retry_count` |
| 731 | `"attempts": ENGINE_PROXY_RETRY_COUNT + 1` | `"attempts": retry_count + 1` |

- Every other route keeps 10 s and one retry.
- `_handle_engine_read_proxy_get` and `_profile_filter` are unchanged. The refresh gets the same sanitising: an unknown or repeated key answers 400, and a `user_id` or `refresh_cache` on it now answers 400 too.

**How a failed refresh reaches the browser:**
- a timeout breaks the loop with 0 retries → 502 `ENGINE_PROXY_UNAVAILABLE`;
- a dropped Engine connection → 502 `ENGINE_PROXY_FAILURE`;
- an Engine 400 or 404 → passed through.

The page treats all of these as a failed refresh.

---

### Frontend: `client/frontend/src/pages/video-page/index.ts`

**Module state.** These lines go next to `currentMetadata` (line 50-51). They must be declared before the coordinator call at line 79: the no-source path renders synchronously, and a `let` declared later would throw a TDZ error.

```ts
type InstanceMetadata = Awaited<ReturnType<typeof fetchInstanceMetadata>>;
// Which metadata source the panel shows; a source renders only if it ranks at least as high.
const METADATA_RANK = { params: 0, fast: 1, instance: 2, refresh: 3 } as const;
let shownRank = -1;
let instanceConfig: InstanceMetadata = null;
let instanceMetadata: Promise<InstanceMetadata> = Promise.resolve(null);
let lastEmbed = "";
let reactionKey = "";
```

**Start (line 79).** `void loadVideo();` becomes `startVideoLoad();`. Line 80, `void loadSimilarVideos();`, is unchanged, and the coordinator neither awaits nor chains it.

**Coordinator**

```ts
/**
 * Start the three metadata sources at once: the Engine's DB answer, its live refresh, and the instance config. None awaits another.
 */
function startVideoLoad() {
  const source = resolveVideoSource();
  if (!source?.host || !source.id) {
    offerMetadata(METADATA_RANK.params, null);
    return;
  }
  instanceMetadata = fetchInstanceMetadata(source.host);
  void instanceMetadata.then((meta) => {
    instanceConfig = meta;
    if (meta && shownRank >= 0) renderVideo(currentMetadata);
  });
  void loadFastMetadata(source);
  void loadRefreshedMetadata(source);
}

/**
 * Render `metadata` unless a higher-ranked source is already shown, so a late fast answer never overwrites refreshed values.
 */
function offerMetadata(rank: number, metadata: VideoMetadata | null) {
  if (rank < shownRank) return;
  shownRank = rank;
  renderVideo(metadata);
}

/**
 * Show the Engine's stored metadata, or the URL params and then the instance's own answer when the Engine has no row.
 */
async function loadFastMetadata(source: { host: string; id: string; url: string }) {
  const metadata = await fetchVideoMetadataFromServer("/api/video", source);
  if (metadata) {
    offerMetadata(METADATA_RANK.fast, metadata);
    return;
  }
  offerMetadata(METADATA_RANK.params, null);
  if (shownRank > METADATA_RANK.instance) return;
  const instanceMeta = await fetchVideoMetadataFromInstance(source);
  if (instanceMeta) offerMetadata(METADATA_RANK.instance, instanceMeta);
}

/**
 * Show live metadata once the Engine has refreshed it; a failure keeps what the panel shows.
 */
async function loadRefreshedMetadata(source: { host: string; id: string; url: string }) {
  const metadata = await fetchVideoMetadataFromServer("/api/video/refresh", source);
  if (!metadata) {
    console.warn("[video] metadata refresh failed; keeping the values shown");
    return;
  }
  offerMetadata(METADATA_RANK.refresh, metadata);
}
```

- **No-source path.** It renders once with `null`, with no fetch and no config, exactly as today.
- **Equal ranks re-render.** Equal-rank renders are allowed, which is what lets the config's re-render at the current rank through.
- **`currentMetadata` stays in step.** It is set only inside `renderVideo`, so it always equals what is shown, and the config re-render reuses it.
- **Skipped fallback.** If the refresh is already shown, the direct-instance fallback is not started at all.

**`renderVideo(metadata: VideoMetadata | null)`.** This is today's `loadVideo` body without `await fetchVideoMetadata()`, and it is synchronous. Line 87 stays as the first statement: `currentMetadata = metadata;`. Three edits:

1. **Instance avatar** (line 109) is taken from the shared config at render time, so it survives every re-render and also reaches rank 0:
   `const instanceAvatarUrl = metadata?.instanceAvatarUrl || instanceConfig?.avatarUrl || "";`
2. **Embed** (lines 212-221). The comparison is against our own last assigned string, and the guard is cleared when `src` is removed:
   ```ts
   if (embedEl) {
     // The embed URL can come straight from the `?embed=` query parameter when metadata resolution fails, so a scheme check is what stops a `javascript:` URL from executing in this origin via iframe navigation.
     const checkedEmbed = embed && /^https:\/\//i.test(embed.trim()) ? embed : "";
     if (!checkedEmbed) {
       embedEl.removeAttribute("src");
       lastEmbed = "";
     } else if (checkedEmbed !== lastEmbed) {
       // Reassigning an unchanged src would restart playback on every re-render.
       embedEl.src = checkedEmbed;
       lastEmbed = checkedEmbed;
     }
   }
   ```
3. **Everything else is unchanged:** `escapeHtml`/`safeExternalUrl` on every write, the `enableBlockButtons(...)` call (its `dataset.wired` guard makes re-renders no-ops), and `void loadReaction()`.

**`loadReaction` gate.** The key is written only for a non-null video, and before the first `await`:

```ts
async function loadReaction() {
  const video = reactionVideo();
  if (!video || !likeButton || !dislikeButton) return;
  // Re-renders call this again; the visitor's reaction is read once per video.
  const key = `${video.uuid}|${video.host}`;
  if (key === reactionKey) return;
  reactionKey = key;
  try {
    await localLikesImported;
    ...unchanged
```

A rank-0 render with a non-UUID `seedId` returns `null` and leaves the gate open, so a later rank that carries `videoUuid` still fetches and wires the buttons.

**`fetchVideoMetadataFromServer(path, source)`**

- Signature: `async function fetchVideoMetadataFromServer(path: string, source: { host: string; id: string; url: string }): Promise<VideoMetadata | null>`.
- `new URL(path, apiBase)`, with only `id` and `host` set, as today. The refresh allow-list accepts exactly these.
- `await fetchInstanceMetadata(source.host)` (line 525) is removed.
- The instance fields become:
  ```ts
  instanceName: (data.instanceName as string | undefined) ?? source.host,
  instanceUrl: (data.instanceUrl as string | undefined) ?? `https://${source.host}`,
  instanceAvatarUrl: "",
  ```
  The Engine always sends both as strings (video.py:279-280), so `instanceMeta?.name`/`url` could never win here today. Dropping them keeps what is visible, and the avatar now comes from `instanceConfig` in `renderVideo`.
- `catch { return null; }` is unchanged. `null` is the failure signal both callers use.

**`fetchVideoMetadataFromInstance`.** Line 600 becomes `const instanceMeta = await instanceMetadata;`, which awaits the shared promise instead of issuing a second `/api/v1/config` request. The effect on R4:
- This source ranks 2 and runs only after rank 0 has rendered, so the wait is never on the first-render path.
- It keeps today's rank-2 precedence exactly, with the config's name and URL winning.

**Removed:** `loadVideo` and `fetchVideoMetadata`, whose sequencing moved into the coordinator. `loadSimilarVideos` and the similars helpers are untouched (R7).

---

### What the build needs to test

**Engine: new `tests/active/test_video_metadata.py`.** Each case runs in an `ENGINE_PY` child over a temporary DB, following `test_internal_events.py:52` / `test_similar.py`. The child uses a real `SimilarServer` with `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`. The patch goes on `handlers.video.fetch_instance_json`, never the shared `engine` fixture.
- **Fast route.**
  - `/api/video` answers the DB fields with the shape unchanged, `accountAvatarUrl == ""`, the channel URL built from slug + host, and the original URL built from uuid + host.
  - The stub is never called.
  - `last_checked_at` and `instances.last_error` are unchanged.
- **Errors on both routes.** 400 `Missing video id` and 404 `Video not found`.
- **Successful refresh.** It answers the instance values, including `accountAvatarUrl`. The `videos`, `channels` and `instances` rows are updated, with `last_error*` set to NULL. A failed channel sub-call still persists, with the DB channel fields.
- **Failed refresh.** Detail `None`, `{}`, a JSON list and a raised `URLError` each answer 200 with DB values and change no row.
- **Deadline.** With `statement_timeout_seconds` around 0.2 and a stub that sleeps 0.5 s, a successful refresh still persists.
- **R7.**
  - Setup: a stub that blocks about 5 s, and a refresh started on a thread.
  - The id-based similars GET is answered in well under 5 s.
  - The stub's call log holds only the refresh's paths.

**Client proxy: added to `tests/active/test_server.py`,** using `EngineStub`, `_serving`, `_client_backend` and `_status`:
- `/api/video/refresh` forwards `id`/`host` and answers 400 on `user_id`, `refresh_cache` or a repeated key;
- with both mappings patched to a small timeout, a sleeping stub sees exactly one refresh GET and the browser gets 502;
- `/api/video` against a sleeping stub still makes two attempts;
- `/api/video` keeps the 10 s default (assert the mapping lookup).

**Frontend: new `tests/active/test_frontend_video_page.py`.** The page is bundled with esbuild (`--platform=node`, css loader `empty`) and driven with a stubbed `document`/`window`/`localStorage` and a scripted `fetch`, following `test_frontend_blocks.py`. It asserts:
- the first render happens before `/api/v1/config` resolves;
- whichever of refresh and fast arrives first, the refreshed values end up shown;
- a failed refresh keeps the values shown and calls `console.warn`;
- a fast 404 renders the URL params, then the instance data;
- `src` is assigned once across the rank 1 → 3 renders;
- `fetchReaction` is called once;
- a `javascript:` embed is never assigned;
- similars are fetched with `limit=8` regardless of metadata timing.

If the stubbing proves too heavy, the plan's own escape hatch applies: extract `offerMetadata`'s rank rule into a lib module.

**At harvest:** `.un/skills/devsecops/config.json` maps the new files to `video.py`, `similar.py`, `server.py` and `video-page/index.ts`.

---

### Check against the plan and requirements

This took two passes; the first found gaps and the second closed them.

| Item | Met by |
|---|---|
| R1 | `merge_video_metadata(row, {}, …)`, no fetch, no write. 400/404 through the shared resolver. |
| R2 | Separate route and handler. Same resolver. `fetch_instance_video_dynamic` unchanged except the success signal. Persist only when `dynamic` is non-empty, with today's SQL and catch. Same response shape. The proxy's own allow-list `{id, host}`. |
| R3 | Three independent starts. The rank rule keeps refreshed values over a late fast answer. A failed refresh is `console.warn` only. |
| R4 | No first-render path awaits `/api/v1/config`. The avatar fills in through the shared promise's re-render. The chip uses host initials until then. |
| R5 | Fast failure renders rank 0 at once, then rank 2. The `https://` check sits inside `renderVideo`, which every path passes through. |
| R6 | `lastEmbed` guard. `dataset.wired` guards unchanged. `reactionKey` gate written before the first await. Escaping unchanged. |
| R7 | Similars code untouched. The instance calls run outside `db_lock`. Covered by the Engine R7 test. |
| Budget constraint | 20 s, no retry, refresh only. A proxy failure degrades per R3. |
| Stdlib / style / dist | Stdlib only. No new dependency. Module-level functions in the files' style. `dist` rebuilt. |

**What pass 1 missed, and pass 2 fixed:**
- **Persist intermediates.** Solved by returning a `merged` dict instead of feeding persist from the response.
- **Persist under an expired deadline.** Nested `statement_deadline` inside `db_lock`.
- **TDZ.** The coordinator's state is declared before line 79.
- **Reaction gate.** Written before the `await` and only for a non-null video.
- **Line 731 log.** Now uses `retry_count`.

### Named simplifications and residual limits

- **Rank rule is one number.** It has no per-field merge: a higher-ranked source replaces the whole panel. That is enough because the refresh answers a superset of the fast answer. The ceiling: a future partial refresh would need per-field precedence.
- **Refresh failure is a bare `null`.** The console warning carries no reason; the status can be logged later if diagnosis needs it.
- **Engine's late write after a Client timeout.** `respond_json` writes to a closed socket and prints a `BrokenPipeError` traceback. This is pre-existing log noise and is left as is; the persist has already run.
- **Different uuid on a later render.** The reaction and block listeners keep the first video they captured. If a later rank reported a different uuid, which should not happen for one row, the reaction is re-read for the new key but clicks still act on the first video. This is unchanged from today.
- **Deviations from the settled plan text, both taken from the settled impacts.**
  - Persist gains a nested statement deadline; the plan said "unchanged".
  - The rank-2 fallback awaits the shared config promise rather than not awaiting it at all. This keeps today's rank-2 name/URL precedence and stays off the first-render path.

## 2026-09-27 - Step 6 - Design the phase breakdown

Approved by the operator.

#### Phase 1 - Engine refresh route [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), engine/server/api/handlers/similar.py (EDITED), engine/server/api/handlers/__init__.py (EDITED), tests/active/test_video_metadata.py (NEW)

**Checkpoint.** Seam: the Engine's HTTP handler over a real DB. New `tests/active/test_video_metadata.py` runs each case in an `ENGINE_PY` child over a temporary DB, following the `subprocess.run([str(ENGINE_PY), "-c", CHILD, ...], cwd=API_DIR)` pattern of `test_similar.py` / `test_internal_events.py`. The child builds a real `SimilarServer` carrying `db`, `db_lock`, `video_error_threshold`, `popularity_like_weight` and `statement_timeout_seconds`, and patches `handlers.video.fetch_instance_json` with a recording stub (never the shared `engine` fixture). It asserts over GET `/api/video/refresh`: (a) with the stub answering detail + channel JSON, the response carries today's response keys with the instance's values, `accountAvatarUrl` included, the channel URL built from slug + host and the original URL from uuid + host. (b) With the detail JSON omitting fields (e.g. no `description`, no `tags`) and the channel sub-call answering `None`, those fields and the channel fields come from the seeded DB row. Guards: 400 `Missing video id` with no id, and 404 `Video not found` for an unknown id; and `/api/video` against the same answering stub still returns the instance's values (today's live behaviour kept until the follow-up plan).

**Intent.** `engine/server/api/handlers/video.py` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`, and a new `handle_video_refresh_request`, dispatched from `SimilarHandler`'s GET branch in `similar.py`, answers `/api/video/refresh` with the instance's live values merged over the DB row field by field, while `/api/video` keeps today's live behaviour through the same functions.

- C1 - `/api/video/refresh` answers the instance's live values in today's `/api/video` response shape.
- C2 - A field the instance did not supply in a refresh falls back to the DB row's value.

**Outcome.** _pending_

#### Phase 2 - Refresh persists only on instance success [code]

**Files touched.** engine/server/api/handlers/video.py (EDITED), tests/active/test_video_metadata.py (EDITED)

**Checkpoint.** Seam: the same `ENGINE_PY`-child harness in `tests/active/test_video_metadata.py`, going through the HTTP handler and reading the DB afterwards. (a) Persist on success: the stub answers detail JSON, and after `/api/video/refresh` the `videos`, `channels` and `instances` rows hold the instance's values, with `instances.last_error*` NULL. A failed channel sub-call still persists, with the DB channel fields. With `statement_timeout_seconds` about 0.2 and a stub that sleeps 0.5 s before answering, the rows are still updated. (b) No write on failure: parametrized over a detail answer of `None`, `{}`, a JSON list, and a raised `URLError`. Each answers 200 with the DB values, and the `videos`, `channels` and `instances` rows (including `last_checked_at` and `last_error`) are identical before and after. (c) R7: with a stub that blocks about 5 s, a refresh is started on a thread; the id-based similars GET then returns 200 in well under 5 s, and the stub's call log holds only the refresh's `/api/v1/videos/...` paths.

**Intent.** `fetch_instance_video_dynamic` returns `{}` when the video detail call did not answer, so `handle_video_refresh_request` writes the merge through `persist_video_metadata`, under its own statement deadline, only when the instance answered, and its instance calls run outside `db_lock`, so a slow refresh leaves the similars route answering.

- C1 - A refresh updates the videos, channels and instances rows only when the instance's video detail call answered.
- C2 - A refresh blocked on a slow instance does not delay the similars route's answer.

**Outcome.** _pending_

#### Phase 3 - Client proxy for the refresh route [code]

**Files touched.** client/backend/server.py (EDITED), tests/active/test_server.py (EDITED)

**Checkpoint.** Seam: the Client backend's HTTP proxy in front of a stub Engine. Added to `tests/active/test_server.py`, using its `EngineStub(BaseHTTPRequestHandler)` + `_serving(ThreadingHTTPServer(...))` + `_client_backend(tmp_path, engine_base, RateLimiter(1000, 60))` + `_status` harness (precedent: `test_engine_receives_the_resolved_address_as_x_client_ip`). (a) GET `/api/video/refresh?id=…&host=…` reaches the stub with exactly those two params. Adding `user_id`, adding `refresh_cache`, or repeating `id` each answers 400, and the stub records no request. (b) With `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` monkeypatched to about 0.3 s for the refresh and a stub that sleeps past it, the browser gets 502 and the stub counts exactly one refresh GET. Guard: `/api/video` against the same sleeping stub (with `ENGINE_PROXY_TIMEOUT_SECONDS` patched small) counts two attempts.

**Intent.** `client/backend/server.py` proxies `/api/video/refresh` as a read route with its own `{id, host}` allow-list, and `_proxy_engine_request` gives it a 20 s timeout and zero retries through the per-path mappings while every other route keeps 10 s and one retry.

- C1 - The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400.
- C2 - A refresh that times out at the proxy is sent to the Engine once and answered 502.

**Outcome.** _pending_


Needs coordination: none

Rationale: The work carries six independently observable behaviours, which do not fit in four phases of at most two clauses each. With the operator's approval, it is split into two plans on a seam that causes no regression in between.

This plan (A) is purely additive. It adds the Engine's `/api/video/refresh` route (P1). It adds the success-gated persist, with its nested statement deadline, and the R7 guard (P2). It exposes the route through the Client proxy with its own allow-list, a 20 s timeout and no retry (P3). No caller uses the new route yet. `/api/video` keeps today's live fetch-and-persist behaviour through the newly split `resolve_video_row` / `merge_video_metadata` / `persist_video_metadata`. The one visible change on `/api/video` is the corrected success signal: a failed instance fetch no longer writes. That is R2's accepted tradeoff arriving early, not a regression. P1's checkpoint guards that `/api/video` still answers live values.

The follow-up plan (B), recorded for the next build, finishes the settled design in three phases:
- `/api/video` becomes DB-only: no instance call, no row changed (R1).
- The page coordinator and rank rule in `video-page/index.ts`: the first render waits on no other source (R4/R5), and the refreshed values win in either arrival order (R3). Tested on the node-bundled page following `test_frontend_blocks.py`.
- The `lastEmbed` and `reactionKey` re-render guards (R6).

B ships the DB-only fast route together with the frontend that calls the refresh. So metadata is never left without a refresh path, which was the regression that ruled out the earlier Engine/frontend split.

Order within A follows the dependencies. P1 creates the split functions and the route. P2 gives persist its success gate and deadline. P3 needs the Engine route to exist before proxying it.

Docs get no phase: `engine/server/README.md`, the READMEs, `DEPLOYMENT.md` and the issue and roadmap notes are updated at Step 9. The `dist/` rebuild and the devsecops config mapping happen at harvest. The checkpoints need only the existing local engine `.pixi` env.

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`engine/server/api/handlers/video.py` is split into `resolve_video_row`, `merge_video_metadata` and `persist_video_metadata`, and a new `handle_video_refresh_request`, dispatched from `SimilarHandler`'s GET branch in `similar.py`, answers `/api/video/refresh` with the instance's live values merged over the DB row field by field, while `/api/video` keeps today's live behaviour through the same functions.

- C1 - `/api/video/refresh` answers the instance's live values in today's `/api/video` response shape.
- C2 - A field the instance did not supply in a refresh falls back to the DB row's value.

must_prove:
- C1 - `/api/video/refresh` answers the instance's live values in today's `/api/video` response shape.
- C2 - A field the instance did not supply in a refresh falls back to the DB row's value.

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - self-check (audit round 1, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase1.py:136 — GET `/api/video/refresh?id=uuid-v1&host=tube.example`, with the stub answering the detail (DETAIL) and the channel (CHANNEL), answers `(200, LIVE)`. LIVE has exactly the eighteen `/api/video` keys and the instance's values: title "Live title", description "Live description", views 1000, likes 50, dislikes 3, channelName "Live Chan", subscribersCount 77, and accountAvatarUrl `https://tube.example/lazy-static/avatars/live.png`. channelUrl is built from the instance slug plus the host (`.../video-channels/live_slug`) and originalUrl from the row's uuid plus the host. The keys today's merge takes from the row (videoUuid, channelAvatarUrl, accountName, accountUrl, embedUrl, publishedAt) carry the row's values. - expected: (200, LIVE). I did not guess this value. Today's `/api/video` answered it with the same stub and seed: the probe's first report, and `test_api_video_still_answers_the_instances_values`, which passed in this run. The refresh is planned to use the same merge. - excludes: Route not added: seen in this run as `(404, {'error': 'Not found'})`. The refresh answers from the row with no live merge (`dynamic={}`): title "DB title", views 10, likes 2, dislikes 1, channelName "DB Chan", subscribersCount 5, accountAvatarUrl "". The refresh answers `fetch_instance_video_dynamic`'s own dict instead of the `/api/video` shape: snake_case keys like `channel_display` and `account_avatar_url`, and videoUuid, embedUrl and publishedAt are missing. Each of these differs from LIVE.
- C1 - tests/tmp/test_11_fast_similars_response_phase1.py:138 — the refresh's instance calls are exactly `[["tube.example", "/api/v1/videos/uuid-v1"], ["tube.example", "/api/v1/video-channels/live_slug"]]`: the detail for the requested id, then the channel for the slug the detail named. - expected: `[[HOST, "/api/v1/videos/uuid-v1"], [HOST, "/api/v1/video-channels/live_slug"]]`, seen in the probe's first report for today's live fetch. - excludes: If the refresh skips the channel sub-call, the list holds only the detail path, and subscribersCount reads 70 (the detail's `followersCount`), not 77. If it fetches by the row's `video_id` ("v1") instead of the requested id, the path reads `/api/v1/videos/v1`. If it takes the slug from the DB (`db_slug`), the second path reads `/api/v1/video-channels/db_slug`. If the route does not exist, the list is `[]`.
- C2 - tests/tmp/test_11_fast_similars_response_phase1.py:147 — the detail omits `description` and `views` and gives a channel with no displayName or followers, and the channel call answers None. The refresh then answers description, views, channelName and subscribersCount as the row's `("DB description", 10, "DB Chan", 5)`. - expected: ("DB description", 10, "DB Chan", 5). The probe's second report showed exactly these for today's merge over the same PARTIAL detail. - excludes: A merge that takes only the instance's fields, with no row fallback, reads `("", None, "", None)`, because the response maps None to "" for text and passes numbers through. Dropping the `channel_display_name` step from the fallback chain reads channelName "DB Chan" from `videos.channel_name`, the same string in this seed, so that variant is not separated here. The other three fields still separate it.
- C2 - tests/tmp/test_11_fast_similars_response_phase1.py:149 — in the same partial refresh, the fields the instance did supply still win: `(title, likes, dislikes) == ("Live title B", 0, 3)`. likes 0 is supplied and falsy. - expected: ("Live title B", 0, 3), seen in the probe's second report. - excludes: A truthiness fallback (`dynamic.get("likes") or row.get("likes")`) reads likes 2, the row's value. A fallback that prefers the row, or answers the row alone, reads `("DB title", 2, 1)`.
- C2 - tests/tmp/test_11_fast_similars_response_phase1.py:150 — the whole partial-refresh body equals `{**LIVE, "title": "Live title B", "description": "DB description", "channelName": "DB Chan", "subscribersCount": 5, "accountAvatarUrl": "", "views": 10, "likes": 0}`. That is the same eighteen keys, with every other value (channelUrl from the instance slug, dislikes 3, row-sourced keys) unchanged. - expected: That dict, identical key for key to the probe's second report. - excludes: A merge that builds channelUrl from the DB slug when the instance's channel lacks a display name reads `.../video-channels/db_slug`. A refresh answering a different shape adds or drops keys. accountAvatarUrl filled from anywhere but the instance reads non-empty.

<assertions>
tests/tmp/test_11_fast_similars_response_phase1.py:129 - control: the Engine interpreter built a real SimilarServer per case over its own seeded whitelist-shaped DB and ran every GET (exit 0) - control
tests/tmp/test_11_fast_similars_response_phase1.py:136 - GET /api/video/refresh with the stub answering detail + channel answers 200 with exactly LIVE: all eighteen /api/video keys; the instance's title, description, views 1000, likes 50, dislikes 3, channelName "Live Chan", subscribersCount 77 and accountAvatarUrl; channelUrl built from the instance slug + host; originalUrl from the row uuid + host; uuid, channel avatar, account name/url, embed and publishedAt from the row as today's merge does. Red today: 404 {"error": "Not found"} - C1
tests/tmp/test_11_fast_similars_response_phase1.py:138 - the refresh fetched /api/v1/videos/{requested id} and then /api/v1/video-channels/live_slug on the row's host; subscribersCount 77 can only come from the second call - C1
tests/tmp/test_11_fast_similars_response_phase1.py:143 - the refresh over a partial detail answers 200 (red today: 404) - C2 precondition
tests/tmp/test_11_fast_similars_response_phase1.py:144 - control: the channel sub-call was made and answered None - control
tests/tmp/test_11_fast_similars_response_phase1.py:147 - with description and views omitted and no channel display name or followers from the instance, the answer carries the row's "DB description", views 10, channelName "DB Chan" and subscribersCount 5 (an instance-only answer would give "", None, "", None) - C2
tests/tmp/test_11_fast_similars_response_phase1.py:149 - the fields the instance did supply still win: title "Live title B", dislikes 3, and likes 0. That is a supplied falsy value; a truthiness fallback would give the row's 2 - C2
tests/tmp/test_11_fast_similars_response_phase1.py:150 - the partial answer is the whole eighteen-key shape, with every other value as in LIVE and accountAvatarUrl "" - C1, C2
tests/tmp/test_11_fast_similars_response_phase1.py:155 - guard: refresh with no id answers 400 {"error": "Missing video id"} with no instance call
tests/tmp/test_11_fast_similars_response_phase1.py:157 - guard: refresh for an unknown id answers 404 {"error": "Video not found"} (not the unrouted {"error": "Not found"}) with no instance call
tests/tmp/test_11_fast_similars_response_phase1.py:163 - guard: /api/video against the same answering stub still answers 200 with LIVE (today's live behaviour kept until the follow-up plan)
tests/tmp/test_11_fast_similars_response_phase1.py:164 - guard: /api/video still makes the detail and channel instance calls
</assertions>

<probes>
Probe tests/tmp/probe_11_video_metadata.py, run via ValidateTests ["tests/tmp/probe_11_video_metadata.py", "-s"]. It used the same child harness as the checkpoint: a real SimilarServer and SimilarHandler over DBs from sync-whitelist.py ensure_whitelist_schema + ensure_content_schema, with handlers.video.fetch_instance_json patched. It printed:
1) today's /api/video with detail + channel answers: status 200, body {"accountAvatarUrl": "https://tube.example/lazy-static/avatars/live.png", "accountName": "DB Account", "accountUrl": "https://tube.example/accounts/db", "channelAvatarUrl": "https://tube.example/lazy-static/avatars/db.png", "channelName": "Live Chan", "channelUrl": "https://tube.example/video-channels/live_slug", "description": "Live description", "dislikes": 3, "embedUrl": "https://tube.example/videos/embed/uuid-v1", "instanceName": "tube.example", "instanceUrl": "https://tube.example", "likes": 50, "originalUrl": "https://tube.example/videos/watch/uuid-v1", "publishedAt": 1700000000000, "subscribersCount": 77, "title": "Live title", "videoUuid": "uuid-v1", "views": 1000}; calls [["tube.example", "/api/v1/videos/uuid-v1"], ["tube.example", "/api/v1/video-channels/live_slug"]].
2) today's /api/video with the partial detail and the channel call answering None: status 200, body identical except accountAvatarUrl "", channelName "DB Chan", description "DB description", likes 0, subscribersCount 5, title "Live title B", views 10; the same two calls.
3) /api/video/refresh today: 404 {"error": "Not found"}, no calls.
4) /api/video?host=... with no id: 400 {"error": "Missing video id"}, no calls.
5) /api/video?id=nope: 404 {"error": "Video not found"}, no calls.
All of these matched the values I had derived by hand beforehand. The final checkpoint then ran via ValidateTests ["tests/tmp/test_11_fast_similars_response_phase1.py"]: 3 failed, 1 passed. The three refresh tests fail on 404 {"error": "Not found"} (400 was expected for the no-id case); the /api/video guard passes on today's behaviour. The probe file tests/tmp/probe_11_video_metadata.py is still on disk because no tool I have can delete a file, so it needs removing. The checkpoint also adds tests/active to sys.path so it can import conftest from tests/tmp.
</probes>

<unassertable>
The checkpoint's example "no `tags`" fallback is not asserted in Phase 1. The /api/video response shape has no tags, category or nsfw key, so their fallback shows up only in the persisted videos row, and persisting is Phase 2's clause C1. The operator chose (AskUser, "response-only") to carry C2 here on the response fields only: description, views, channelName and subscribersCount fall back; likes 0 from the instance is kept. Phase 2's persisted-row check will cover the tags_json fallback.
</unassertable>

### `tests/tmp/test_11_fast_similars_response_phase1.py` - 10387 characters, inlined in full

```
"""GET `/api/video/refresh` answers the instance's live values in `/api/video`'s response shape, and a field the instance omitted from the row's value.

- With the instance answering the video detail and the channel, the refresh answers 200 with exactly `/api/video`'s eighteen keys: the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar; the channel URL built from the instance's channel slug and the host, the original URL from the row's uuid and the host; and the keys today's merge takes from the row (uuid, channel avatar, account name and URL, embed, published date) from the row. It asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`.
- With the detail omitting `description` and `views`, carrying `likes: 0`, and the channel call answering nothing, the refresh answers the row's description, views, channel display name and follower count beside the instance's title, dislikes and `likes` 0.
- A refresh with no id answers 400 `Missing video id`, and one for an id not in the DB answers 404 `Video not found`, neither calling the instance.
- `/api/video` against the same answering instance still answers the instance's values.

Each case runs under the Engine's interpreter in a child process: a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, over its own whitelist-shaped temporary DB (schema from `sync-whitelist.py`), with `handlers.video.fetch_instance_json` replaced by a stub that records each call and answers from the case's path map.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# The active suite's conftest, importable whether this file runs from tests/tmp or tests/active.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
HOST = "tube.example"
UUID = "uuid-v1"
REFRESH = f"/api/video/refresh?id={UUID}&host={HOST}"
DETAIL_PATH = f"/api/v1/videos/{UUID}"
CHANNEL_PATH = "/api/v1/video-channels/live_slug"
# Every value differs from the row's, so an answer built from the row cannot pass for the instance's.
DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
CHANNEL = {"displayName": "Live Chan Detail", "followersCount": 77}
ANSWERING = {DETAIL_PATH: DETAIL, CHANNEL_PATH: CHANNEL}
# No description or views, likes 0 (supplied, and falsy), a channel slug but no channel display name or followers; the channel call is not in the map, so it answers None.
PARTIAL = {DETAIL_PATH: {"name": "Live title B", "likes": 0, "dislikes": 3, "channel": {"name": "live_slug"}}}
# The answer to a refresh over ANSWERING (observed from today's /api/video with the same stub): accountName/accountUrl, channelAvatarUrl, embedUrl, publishedAt and videoUuid come from the row in today's merge.
LIVE = {
    "videoUuid": UUID,
    "title": "Live title",
    "description": "Live description",
    "channelName": "Live Chan",
    "channelUrl": f"https://{HOST}/video-channels/live_slug",
    "channelAvatarUrl": f"https://{HOST}/lazy-static/avatars/db.png",
    "subscribersCount": 77,
    "instanceName": HOST,
    "instanceUrl": f"https://{HOST}",
    "accountName": "DB Account",
    "accountUrl": f"https://{HOST}/accounts/db",
    "accountAvatarUrl": f"https://{HOST}/lazy-static/avatars/live.png",
    "embedUrl": f"https://{HOST}/videos/embed/{UUID}",
    "originalUrl": f"https://{HOST}/videos/watch/{UUID}",
    "views": 1000,
    "likes": 50,
    "dislikes": 3,
    "publishedAt": 1_700_000_000_000,
}
# Starts each case's server on its own DB, runs one GET through the real handler with `fetch_instance_json` stubbed, and reports the status, the parsed body and every instance call.
CHILD = r'''
import http.client, inspect, json, sys, threading
from pathlib import Path
from unittest.mock import patch
import server
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler
reports = []
for db_path, path, answers in json.loads(sys.argv[1]):
    conn = connect_db(Path(db_path))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    calls = []
    def stub(host, api_path):
        calls.append([host, api_path])
        return answers.get(api_path)
    try:
        with patch.object(video, "fetch_instance_json", stub):
            client = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
            client.request("GET", path)
            resp = client.getresponse()
            body = json.loads(resp.read() or b"null")
            client.close()
        reports.append({"status": resp.status, "body": body, "calls": calls})
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''


@pytest.fixture(scope="module")
def sync_job():
    spec = importlib.util.spec_from_file_location("sync_whitelist_video_metadata", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(sync_job, path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.execute("INSERT INTO instances (host, last_error) VALUES (?, 'boom')", (HOST,))
        conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
        # channel_url and video_url are NULL, so both URLs in the answer are built from slug/uuid + host.
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
            (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
        )
        conn.commit()
    finally:
        conn.close()


def _get(sync_job, tmp_path: Path, *cases: tuple[str, dict]) -> list[dict]:
    """Run each (path, instance answers) case on its own freshly seeded DB, so no case sees another's write."""
    runs = []
    for index, (path, answers) in enumerate(cases):
        db_path = tmp_path / f"case{index}.db"
        _seed(sync_job, db_path)
        runs.append([str(db_path), path, answers])
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, json.dumps(runs)], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built each server and ran every request
    return json.loads(run.stdout)


def test_refresh_answers_the_instances_values_in_the_api_video_shape(sync_job, tmp_path):
    (report,) = _get(sync_job, tmp_path, (REFRESH, ANSWERING))
    # Unrouted, the refresh reads 404 {"error": "Not found"}; merged with no live values it reads "DB title", views 10 and an empty accountAvatarUrl.
    assert (report["status"], report["body"]) == (200, LIVE)  # C1
    # The detail by the requested id, then the channel by the slug the detail named; 77 in LIVE is only reachable through the second call.
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # C1


def test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted(sync_job, tmp_path):
    (report,) = _get(sync_job, tmp_path, (REFRESH, PARTIAL))
    assert report["status"] == 200, report["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the channel call was made and answered nothing
    body = report["body"]
    # Taking only the instance's fields reads "", None, "" and None here.
    assert (body["description"], body["views"], body["channelName"], body["subscribersCount"]) == ("DB description", 10, "DB Chan", 5)  # C2
    # The instance's values still win where it supplied them; a truthiness fallback reads likes 2, the row's value.
    assert (body["title"], body["likes"], body["dislikes"]) == ("Live title B", 0, 3)  # C2
    assert body == {**LIVE, "title": "Live title B", "description": "DB description", "channelName": "DB Chan", "subscribersCount": 5, "accountAvatarUrl": "", "views": 10, "likes": 0}  # C1 C2: the same eighteen keys, every other value unchanged


def test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance(sync_job, tmp_path):
    missing, unknown = _get(sync_job, tmp_path, (f"/api/video/refresh?host={HOST}", ANSWERING), (f"/api/video/refresh?id=nope&host={HOST}", ANSWERING))
    assert (missing["status"], missing["body"], missing["calls"]) == (400, {"error": "Missing video id"}, [])
    # The unrouted path reads 404 {"error": "Not found"}, which this body tells apart.
    assert (unknown["status"], unknown["body"], unknown["calls"]) == (404, {"error": "Video not found"}, [])


def test_api_video_still_answers_the_instances_values(sync_job, tmp_path):
    (report,) = _get(sync_job, tmp_path, (f"/api/video?id={UUID}&host={HOST}", ANSWERING))
    # Kept live until the follow-up plan; a DB-only /api/video reads "DB title" and makes no call.
    assert (report["status"], report["body"]) == (200, LIVE)
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - red (audit round 1)

`tests/tmp/test_11_fast_similars_response_phase1.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase1.py  3 failed, 1 passed                     0.0s
  --------------------------------------------------
  total                                               3 failed, 1 passed                     3.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 3 UNCARRIED clause(s) - C2e, D4, D5c; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 136 on
`assert (report["status"], report["body"]) == (200, LIVE)`. It reads (404, {"error": "Not found"})
because `SimilarHandler._dispatch_get` (similar.py:495-508) has no `/api/video/refresh` route.
test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 143 on the
same 404. test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance
fails at line 155, reading (404, {"error": "Not found"}, []) against (400, {"error": "Missing video id"}, []).
test_api_video_still_answers_the_instances_values passes as the control, because
`handle_video_request` already merges live values over the row.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve.
   It was not read, and nothing in test_path imports it.
2. `fixtures_path` was not supplied. tests/active/conftest.py was found by Glob, and only the
   `ROOT` and `ENGINE_PY` definitions the test imports (conftest.py:31-32) were checked.
3. engine/server/db/jobs/sync-whitelist.py was checked only to confirm that `ensure_whitelist_schema`
   (line 253) and `ensure_content_schema` (line 323) exist. The column set the seed INSERTs rely on
   was not read.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (22 clauses: 7 must_prove, 11 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :136 | every live value in DETAIL/CHANNEL differs from the row, so a row-only answer ("DB title", views 10, empty accountAvatarUrl) or an unrouted 404 fails | CARRIED |
| C1b | must_prove | in today's `/api/video` response shape | :136, :163 | whole-dict equality against LIVE, and :163 anchors LIVE as what `/api/video` answers for the same stub; a missing, extra or renamed key fails | CARRIED |
| C1c | must_prove | the live values come from the instance's detail and channel calls | :138 | a refresh that skips the channel call (subscribersCount 70, not 77) or calls in another order or path | CARRIED |
| C2a | must_prove | omitted `description` falls back to the row | :147 | taking only the instance's field ("" in the answer) | CARRIED |
| C2b | must_prove | omitted `views` falls back to the row | :147 | taking only the instance's field (None) | CARRIED |
| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :147 | "" / None from an instance-only merge | CARRIED |
| C2d | must_prove | a supplied falsy value is not treated as omitted | :149 | a truthiness fallback that answers the row's likes 2 | CARRIED |
| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | none | nothing: PARTIAL supplies all three (`"name"`, `"likes": 0`, `"dislikes": 3`), so their fallback never runs | UNCARRIED |
| D1 | docstring | "answers 200 with exactly `/api/video`'s eighteen keys" | :136 | an added or dropped key | CARRIED |
| D2 | docstring | "the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar" | :136 | row values (all distinct), or the detail's followers 70 used instead of the channel call's 77 | CARRIED |
| D3 | docstring | "the channel URL built from the instance's channel slug and the host" | :136 | building it from the row's `db_slug` | CARRIED |
| D4 | docstring | "the original URL from the row's uuid and the host" | :136 | nothing on the source: the requested id equals the row's uuid (`uuid-v1`), so building it from the query id passes too | UNCARRIED |
| D5a | docstring | account name and URL "from the row" | :136 | taking the instance's "Live Account" or `/accounts/live` | CARRIED |
| D5b | docstring | channel avatar and published date "from the row" | :136 | an instance-only merge (the only source of these values is the row, so it answers "" / None) | CARRIED |
| D5c | docstring | uuid and embed "from the row" | :136 | nothing on the source: the row's `embed_path` and uuid match what the requested id and host would build | UNCARRIED |
| D6 | docstring | "asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`" | :138 | a wrong path, a wrong host, a reversed order, or an extra call | CARRIED |
| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :147, :150 | an instance-only merge | CARRIED |
| D8 | docstring | "beside the instance's title, dislikes and `likes` 0" | :149 | row title, row dislikes 1, truthiness likes 2 | CARRIED |
| D9 | docstring | no id → 400 `Missing video id`, no instance call | :155 | another status or body, or a call made before validation | CARRIED |
| D10 | docstring | id not in DB → 404 `Video not found`, no instance call | :157 | an unrouted 404 `Not found`, or a call made before the lookup | CARRIED |
| D11 | docstring | "`/api/video` against the same answering instance still answers the instance's values" | :163, :164 | a DB-only `/api/video` ("DB title", no calls) | CARRIED |
| N1 | name | "refresh answers the instance's values in the api video shape" | :136 | as C1a/C1b | CARRIED |
| N2 | name | "refresh answers the row's value for each field the instance omitted" | :147, :150 | every field PARTIAL omits is asserted, so an instance-only merge fails | CARRIED |
| N3 | name | "refresh without an id or for an unknown video is refused without calling the instance" | :155, :157 | as D9/D10 | CARRIED |
| N4 | name | "api video still answers the instance's values" | :163 | as D11 | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase1.py:149
   assert (body["title"], body["likes"], body["dislikes"]) == ("Live title B", 0, 3)  # C2
   C2 says any field the instance did not supply falls back to the row. The response takes seven fields from the instance that have row counterparts: title, description, views, likes, dislikes, channelName and subscribersCount. PARTIAL (:38) omits only four of them. The instance still supplies `name`, `likes` and `dislikes`, so :149 checks that supplied values win. It never checks the fallback for those three fields. A refresh that answers `title: ""` or `likes: None` / `dislikes: None` when the instance omits them passes every assertion in the file. The principle says "a claim naming a set of fields asserts every member of the set". Here the test asserts four members of seven (C2e).

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase1.py:136
   D4 and D5c are UNCARRIED. The docstring (:3) says originalUrl, videoUuid and embedUrl come "from the row's uuid" / "from the row". But the requested id is `UUID`, the same value as the row's `video_uuid`, and the row's `embed_path` is exactly what the uuid and host would build. So a refresh that builds these from the query id passes. To separate the sources, request the row by `video_id` (`v1`), or give it an embed_path that differs from the built one. The other option is to narrow the docstring sentence.
2. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase1.py:141
   The only instance failure tested is a missing channel call. No case covers the detail call answering nothing (the stub returns `None` for DETAIL_PATH). That is the expected failure mode of a refresh against an unreachable instance.
3. bounds (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase1.py:153
   The refusal cases cover a missing id and an unknown id. These are untested: an id that exists under a different `host`, a refresh with no `host`, and a row whose `error_count` has reached `video_error_threshold`. The handler's lookup filters on all three (`fetch_video_row`), and the server is built with a threshold of 3 (:73).
4. name-as-sentence (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase1.py:1
   No rule covers docstrings directly. The opening sentence "and a field the instance omitted from the row's value" is missing its verb (presumably "answers"), so it does not read as the claim it summarises.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), which does not exist in the worktree, so it was not read.
2. `fixtures_path` was not supplied. The test imports `ENGINE_PY` and `ROOT` from tests/active/conftest.py. Their definitions were checked (:31-32). The rest of that conftest was not read.

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - self-check (audit round 2, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase1.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase1.py:140 — refresh over ANSWERING answers (200, LIVE): all eighteen /api/video keys with the instance's values; :142 — calls are [detail by uuid, channel by live_slug]; :144 — refresh requested by video_id "v1" over BY_VIDEO_ID answers (200, LIVE) - expected: (200, LIVE), with title "Live title", views 1000, likes 50, dislikes 3, channelName "Live Chan", subscribersCount 77 (only from the channel call), accountAvatarUrl `.../avatars/live.png`, and videoUuid/embedUrl/originalUrl on uuid-v1 even when requested by "v1". Calls: [["tube.example", "/api/v1/videos/uuid-v1"], ["tube.example", "/api/v1/video-channels/live_slug"]]. - excludes: Unrouted refresh: 404 {"error": "Not found"}. Row-only answer: "DB title", views 10, accountAvatarUrl "". Skipping the channel call: subscribersCount 70. Building uuid, embed or original URL from the query id: "v1", `.../embed/v1`, `.../watch/v1`, which fails :144.
- C2 - tests/tmp/test_11_fast_similars_response_phase1.py:153 — PARTIAL: (description, views, channelName, subscribersCount) == ("DB description", 10, "DB Chan", 5); :155 — (title, likes, dislikes) == ("Live title B", 0, 3); :160 — OMITTING: (title, likes, dislikes) == ("DB title", 2, 1); :156 and :161 pin the full eighteen-key bodies - expected: Every one of the seven instance-sourced fields with a row counterpart falls back to the row when omitted. PARTIAL gives "DB description", 10, "DB Chan", 5. OMITTING gives "DB title", 2, 1. A supplied likes 0 is kept as 0. - excludes: An instance-only merge reads ("", None, "", None) at :153 and ("", None, None) at :160. A truthiness fallback reads likes 2 at :155.

<exemptions>
none
</exemptions>

<items>
<item id="C2e">
<disposition>fixed</disposition>
<what>Added OMITTING, the complement of PARTIAL. The detail has no `name`, `likes` or `dislikes`, but it supplies its own description "Live description B", views 900, channel displayName "Live Chan B" and followersCount 60, and the channel call answers None. test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted now runs it as a second case. :160 asserts (title, likes, dislikes) == ("DB title", 2, 1), the row's values. That excludes an instance-only merge, which reads ("", None, None). :161 pins the whole eighteen-key body. Its expected values were observed from today's /api/video over the same stub. Between PARTIAL (:153) and OMITTING (:160), all seven instance-sourced fields that have a row counterpart now get a fallback assertion.</what>
</item>
<item id="D4">
<disposition>fixed</disposition>
<what>test_refresh_answers_the_instances_values_in_the_api_video_shape now runs a second refresh that requests the row by its video_id: `/api/video/refresh?id=v1&host=tube.example`. The stub map is BY_VIDEO_ID, which is ANSWERING plus `/api/v1/videos/v1` → DETAIL, so the detail answers under either id and the case turns only on URL sourcing. :144 asserts (200, LIVE), whose originalUrl is `https://tube.example/videos/watch/uuid-v1`. That excludes building the original URL from the query id, which reads `.../watch/v1`. The value was observed: today's /api/video?id=v1 over the same map answered exactly LIVE. The docstring bullet now says so.</what>
</item>
<item id="D5c">
<disposition>fixed</disposition>
<what>The same by-video_id case carries this row. :144 whole-dict equality against LIVE requires videoUuid "uuid-v1" and embedUrl `https://tube.example/videos/embed/uuid-v1`, which come from the row's video_uuid and embed_path. Building either from the requested id reads "v1" or `.../embed/v1` and fails. The value was observed from today's /api/video?id=v1. The docstring now says "Requested by the row's video id rather than its uuid, it answers the same, so uuid, embed and original URL come from the row and not from the query id."</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, C2e: title/likes/dislikes fallback never exercised): added the OMITTING case, a detail with no name/likes/dislikes. :160 asserts ("DB title", 2, 1) against the instance-only ("", None, None), and :161 pins the full body. Observed from today's /api/video before writing.
Claim RECOMMENDATION 1 (D4/D5c sources indistinguishable) taken: added a refresh requested by video_id "v1" and asserted (200, LIVE) at :144, so uuid, embed and original URL built from the query id fail. Observed from today's /api/video?id=v1.
Claim RECOMMENDATION 4 (docstring opening sentence missing its verb) taken: it now reads "and answers a field the instance omitted from the row's value."
Shape audit: no CRITICAL. The new assertions compare against literals observed from a run, not against anything built from production's own table, and the edited file still fails 3 / passes 1 for the same reason as before (see answer 7).
Probe files tests/tmp/probe_11_video_metadata.py and tests/tmp/probe_11_remediation.py are still on disk, because no tool I have can delete a file. Both need removing.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:140 — refresh over ANSWERING answers (200, LIVE): all eighteen /api/video keys with the instance's values; :142 — calls are [detail by uuid, channel by live_slug]; :144 — refresh requested by video_id "v1" over BY_VIDEO_ID answers (200, LIVE)</assertion>
<expected>(200, LIVE), with title "Live title", views 1000, likes 50, dislikes 3, channelName "Live Chan", subscribersCount 77 (only from the channel call), accountAvatarUrl `.../avatars/live.png`, and videoUuid/embedUrl/originalUrl on uuid-v1 even when requested by "v1". Calls: [["tube.example", "/api/v1/videos/uuid-v1"], ["tube.example", "/api/v1/video-channels/live_slug"]].</expected>
<wrong_implementation>Unrouted refresh: 404 {"error": "Not found"}. Row-only answer: "DB title", views 10, accountAvatarUrl "". Skipping the channel call: subscribersCount 70. Building uuid, embed or original URL from the query id: "v1", `.../embed/v1`, `.../watch/v1`, which fails :144.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_11_fast_similars_response_phase1.py:153 — PARTIAL: (description, views, channelName, subscribersCount) == ("DB description", 10, "DB Chan", 5); :155 — (title, likes, dislikes) == ("Live title B", 0, 3); :160 — OMITTING: (title, likes, dislikes) == ("DB title", 2, 1); :156 and :161 pin the full eighteen-key bodies</assertion>
<expected>Every one of the seven instance-sourced fields with a row counterpart falls back to the row when omitted. PARTIAL gives "DB description", 10, "DB Chan", 5. OMITTING gives "DB title", 2, 1. A supplied likes 0 is kept as 0.</expected>
<wrong_implementation>An instance-only merge reads ("", None, "", None) at :153 and ("", None, None) at :160. A truthiness fallback reads likes 2 at :155.</wrong_implementation>
</row>
</rows>

<answers>
1. No. Every no-call assertion (:166, :168) pairs with a status and body that only the routed handler produces. The partial cases carry call-list controls (:150, :158) and 200 preconditions. With the code under test deleted, every refresh assertion fails on 404 {"error": "Not found"}.
2. No. Expected values are literals: LIVE and the OMITTING/PARTIAL overrides, all observed from today's /api/video over the same stubs. The test does not recompute any merge. Deleting the refresh route, or its row fallback for title/likes/dislikes, turns :140/:144/:160 red.
3. No. Fallback is read on two complementary partial details, and URL/uuid sourcing on two request ids (uuid and video_id). Every row value differs from every instance value.
4. No. The only double is `handlers.video.fetch_instance_json`, the network boundary to a remote PeerTube instance. The server, handler, DB layer and merge are all real.
5. Yes, it collects: 4 tests, and the run shows 3 failed, 1 passed. The new names OMITTING and BY_VIDEO_ID are defined at module level, and `_get` already takes *cases.
6. Yes. The OMITTING body and the by-video_id body were both printed by probe tests/tmp/probe_11_remediation.py, which runs today's /api/video with these exact stubs. The first answered title "DB title", likes 2, dislikes 1, description "Live description B", views 900, channelName "Live Chan B", subscribersCount 60 and accountAvatarUrl "". The second answered exactly LIVE, with calls to /api/v1/videos/v1 and then the channel.
7. Yes. ValidateTests on the file: the refresh tests fail at :140 and :149 on 404 {"error": "Not found"}, and at :166 on 404 vs 400. The /api/video guard passes. That is the same red, for the unbuilt route.
No rewrite was needed. The edits were the ledger fixes above.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - red (audit round 2)

`tests/tmp/test_11_fast_similars_response_phase1.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase1.py  3 failed, 1 passed                     0.0s
  --------------------------------------------------
  total                                               3 failed, 1 passed                     4.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - audit (round 2)

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
Three tests fail, all because `/api/video/refresh` has no route and gets `404 {"error": "Not found"}`.
test_refresh_answers_the_instances_values_in_the_api_video_shape fails at line 140 on
`assert (report["status"], report["body"]) == (200, LIVE)`, reading (404, {"error": "Not found"}).
test_refresh_answers_the_rows_value_for_each_field_the_instance_omitted fails at line 149 on
`assert report["status"] == 200`, reading 404.
test_refresh_without_an_id_or_for_an_unknown_video_is_refused_without_calling_the_instance fails
at line 166, reading (404, {"error": "Not found"}, []) where it expects (400, {"error": "Missing video id"}, []).
test_api_video_still_answers_the_instances_values passes against today's `handle_video_request`.

NOT ASSESSED
1. `code_under_test` listed tests/active/test_video_metadata.py (NEW), which does not resolve. It
   was not read, and nothing in the test under audit imports it.
2. `fixtures_path` was not supplied. I found tests/active/conftest.py and checked only the two
   names the test imports from it: `ROOT` (line 31) and `ENGINE_PY` (line 32). The rest of that
   file was not read.
3. I confirmed that `SimilarServer.__init__` exists (engine/server/api/server.py:209), but did not
   read its parameters. So the child's `dict.fromkeys(...)[3:]` construction (test line 76) was not
   checked against its real signature. That does not change the shape findings.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (25 clauses: 8 must_prove, 13 docstring, 4 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | `/api/video/refresh` answers the instance's live values | :140 | Every live value in DETAIL/CHANNEL differs from the row's value. An answer built only from the row ("DB title", views 10, empty accountAvatarUrl) fails, and so does an unrouted 404 | CARRIED |
| C1b | must_prove | in today's `/api/video` response shape | :140, :174 | :140 compares the whole dict to LIVE, and :174 pins LIVE as what `/api/video` answers for the same stub. A missing, extra or renamed key fails | CARRIED |
| C1c | must_prove | the live values come from the instance's detail and channel calls | :142 | A refresh that skips the channel call (subscribersCount 70, not 77), or calls in another order or on another path | CARRIED |
| C2a | must_prove | omitted `description` falls back to the row | :153 | Taking only the instance's field ("" in the answer) | CARRIED |
| C2b | must_prove | omitted `views` falls back to the row | :153 | Taking only the instance's field (None) | CARRIED |
| C2c | must_prove | channel display name and follower count fall back when neither the detail nor the channel call supplies them | :153 | The "" / None an instance-only merge would give | CARRIED |
| C2d | must_prove | a supplied falsy value is not treated as omitted | :155 | A truthiness fallback that answers the row's likes 2 | CARRIED |
| C2e | must_prove | omitted `title`, `likes` or `dislikes` falls back to the row | :160, :161 | OMITTING leaves out all three. An instance-only merge answers "", None, None, not the row's "DB title", 2, 1 | CARRIED |
| D1 | docstring | "answers 200 with exactly `/api/video`'s eighteen keys" | :140 | An added or dropped key | CARRIED |
| D2 | docstring | "the instance's title, description, counts, channel display name, the channel call's follower count and the account avatar" | :140 | Row values (all distinct), or the detail's followers 70 used in place of the channel call's 77 | CARRIED |
| D3 | docstring | "the channel URL built from the instance's channel slug and the host" | :140 | Building it from the row's `db_slug` | CARRIED |
| D4 | docstring | "the original URL from the row's uuid and the host" | :144 | The request is made by id `v1`, so building the URL from the query id gives `.../watch/v1`, not LIVE's `.../watch/uuid-v1` | CARRIED |
| D5a | docstring | account name and URL "from the row" | :140 | Taking the instance's "Live Account" or `/accounts/live` | CARRIED |
| D5b | docstring | channel avatar and published date "from the row" | :140 | An instance-only merge ("" / None) | CARRIED |
| D5c | docstring | uuid and embed "from the row" | :144 | The request is made by id `v1`, so a videoUuid or embed built from the query id gives `v1` or `.../embed/v1`, not LIVE's `uuid-v1` values | CARRIED |
| D6 | docstring | "asks the instance for `/api/v1/videos/{id}` and then `/api/v1/video-channels/{slug}`" | :142 | A wrong path, a wrong host, a reversed order, or an extra call | CARRIED |
| D7 | docstring | partial detail: row's description, views, channel display name and follower count | :153, :156 | An instance-only merge | CARRIED |
| D8 | docstring | "beside the instance's title, dislikes and `likes` 0" | :155 | Row title, row dislikes 1, or a truthiness fallback giving likes 2 | CARRIED |
| D9 | docstring | no id → 400 `Missing video id`, no instance call | :166 | Another status or body, or a call made before validation | CARRIED |
| D10 | docstring | id not in DB → 404 `Video not found`, no instance call | :168 | An unrouted 404 `Not found`, or a call made before the lookup | CARRIED |
| D11 | docstring | "`/api/video` against the same answering instance still answers the instance's values" | :174, :175 | A DB-only `/api/video` ("DB title", no calls) | CARRIED |
| N1 | name | "refresh answers the instance's values in the api video shape" | :140, :144 | Same as C1a/C1b | CARRIED |
| N2 | name | "refresh answers the row's value for each field the instance omitted" | :153, :156, :160, :161 | Between PARTIAL and OMITTING, every field either case omits is asserted, so an instance-only merge fails | CARRIED |
| N3 | name | "refresh without an id or for an unknown video is refused without calling the instance" | :166, :168 | Same as D9/D10 | CARRIED |
| N4 | name | "api video still answers the instance's values" | :174 | Same as D11 | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:4. The docstring gained a clause the ledger does not have: "with the detail omitting title, likes and dislikes instead, it answers the row's title, likes and dislikes beside the instance's description, views, channel display name and follower count". It is carried by :160 and :161: the whole-body equality at :161 rules out the row's "DB description", 10, "DB Chan" and 5 standing in for OMITTING's values. It is recorded here because the prose was added alongside the assertions that answer C2e, D4 and D5c. It is not a defect.
2. bounds / normal-and-abnormal-paths (rules/testing.md): tests/tmp/test_11_fast_similars_response_phase1.py:147. No case has the detail call answer nothing at all (`fetch_instance_json` returns None for DETAIL_PATH). That is the far edge of C2's per-field fallback: every field omitted at once, with no channel slug to follow. No `must_prove` clause names that case, so it does not block.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_metadata.py (NEW), and that path does not exist. Nothing was judged from it.
2. `fixtures_path` was not supplied. The test's only outside fixture inputs are `ENGINE_PY` and `ROOT`, which it imports from tests/active/conftest.py (lines 31–32). They were read there, and `sync_job` is defined in the test file itself.

## 2026-09-27 - Step 7 - Phase 1 (Engine refresh route) - checkpoint outcome (run 1)

`tests/tmp/test_11_fast_similars_response_phase1.py` exited 0 after the phase landed.

<changes>
### engine/server/api/handlers/video.py
- `handle_video_request` is split into three module-level functions. The merge rules and SQL are the same as before; only their location changed.
  - `resolve_video_row(handler, server, params)` reads `id`/`video_id` and `host`/`instance_domain` and answers 400 `Missing video id` or 404 `Video not found`. Otherwise it returns `(row, id_param, instance_domain)`. `db_lock` is still held only around the SELECT.
  - `merge_video_metadata(row, dynamic, instance_domain)` returns `(response, merged)`. `response` has the same eighteen `/api/video` keys as before, and a field the instance left out falls back to the row, field by field. Title and description use `or`; the numbers use `is None`, so a supplied `likes: 0` is kept. `merged` holds the raw values (`None` included), so the write stores `NULL` rather than the response's `""`.
  - `persist_video_metadata(server, row, instance_domain, merged)` holds the three UPDATEs (videos, channels, instances), the popularity calculation and the logged `sqlite3.OperationalError` catch. It reads its values from `merged`. The argument order follows the Step 5 draft, so Phase 2 can add its statement deadline there.
- New `handle_video_refresh_request` runs resolve, then `fetch_instance_video_dynamic` (by the requested id, outside the lock), then merge, then persist under the same `if dynamic and instance_domain and row.get("video_id")` guard as before, then answers 200.
- `handle_video_request` keeps its name and passes the request to `handle_video_refresh_request`, so `/api/video` behaves as before: it calls the instance live and writes to the DB.
  - A `rat-tail:` comment says what's left: `/api/video` still makes the instance call and the write, and the follow-up plan makes it DB-only by answering `merge_video_metadata(row, {}, instance_domain)` with no fetch and no write.
  - Phase 1 did not touch the `{}`-on-failed-detail success signal in `fetch_instance_video_dynamic`; that is Phase 2's clause.
- Module docstring updated to cover both routes and the persist step.

### engine/server/api/handlers/similar.py
- The import now reads `from handlers.video import handle_video_refresh_request, handle_video_request`.
- New branch in `_dispatch_get`: `if url.path == "/api/video/refresh": handle_video_refresh_request(self, self.server, params)`, placed after the `/api/video` branch. It gets the existing `/api/` rate limit (its own per-path bucket) and the statement deadline in `do_GET`.
- A `/api/video/refresh` line is added to the docstring's list of routes.

### engine/server/api/handlers/__init__.py
- The `video` module line in the docstring now names both routes.

### tests/active/test_video_metadata.py
- Not written. This path is where the gated checkpoint `tests/tmp/test_11_fast_similars_response_phase1.py` gets promoted to; I did not touch the checkpoint or write a copy of it.

### Not run
- I did not run the checkpoint; the workflow's run is the one that counts.
- I expect it to go green because the checkpoint's own probe showed today's `/api/video` returning exactly the expected bodies with the same stubs, and the refresh route now runs that same merge.

### Leftovers in tests/tmp
- The earlier authoring turns left `tests/tmp/probe_11_video_metadata.py` and `tests/tmp/probe_11_remediation.py` in place. I didn't touch them and have no tool to delete them, so they still need removing.
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
  tests/tmp/test_11_fast_similars_response_phase1.py  4 passed                               0.0s
  --------------------------------------------------
  total                                               4 passed                               4.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`fetch_instance_video_dynamic` returns `{}` when the video detail call did not answer, so `handle_video_refresh_request` writes the merge through `persist_video_metadata`, under its own statement deadline, only when the instance answered, and its instance calls run outside `db_lock`, so a slow refresh leaves the similars route answering.

- C1 - A refresh updates the videos, channels and instances rows only when the instance's video detail call answered.
- C2 - A refresh blocked on a slow instance does not delay the similars route's answer.

must_prove:
- C1 - A refresh updates the videos, channels and instances rows only when the instance's video detail call answered.
- C2 - A refresh blocked on a slow instance does not delay the similars route's answer.

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - self-check (audit round 1, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase2.py:256 — parametrized over a detail answering None, {}, a JSON list, and urlopen raising URLError: every column of the videos, channels and instances rows is the same after the refresh as before it (`report["after"] == report["before"]`). The control at :252 shows the refresh made exactly one instance call, for the detail. - expected: after == before in all four cases: v1.last_checked_at stays 1, popularity stays 0.0, and instances.last_error/_at/_source stay 'boom'/123/'crawler'. - excludes: Today's guard `if dynamic and ...` is always true, because fetch_instance_video_dynamic always returns its 14-key dict. So a failed call still persists the DB values. In this run :256 went red for None, {} and URLError: the videos and instances items differed, because last_checked_at was bumped, popularity recomputed and last_error cleared. The pre-phase probe showed the same.
- C1 - tests/tmp/test_11_fast_similars_response_phase2.py:254 — each failed-detail case answers (200, DB_ONLY): all eighteen fields come from the seeded row. - expected: (200, DB_ONLY) for all four cases. This run showed exactly that for None, {} and URLError, which passed :254. For the JSON list, the value comes from the plan's `not isinstance(detail, dict)` → `{}` path, the same merge as the None case. - excludes: A detail that is a JSON list reaches `detail.get` and raises AttributeError, and the connection drops unanswered. This run read (None, "RemoteDisconnected(...)"). A fix that treated only None as failure would still crash here.
- C1 - tests/tmp/test_11_fast_similars_response_phase2.py:211 / :212 / :215 / :216 / :218, via _assert_written from :241 — with statement_timeout_seconds=0.2, each instance call taking 0.5 s, and a heavy AFTER UPDATE trigger on videos, the refresh still writes. last_checked_at falls inside the run's wall-clock window, popularity > 0, v1 carries LIVE_VIDEO with v2 untouched, channels c1 carries live_slug/Live Chan/77, and the instance's last_error* are NULL. Controls: status 200 at :238, elapsed ≥ 1.0 s at :239. - expected: The rows written exactly as in the success test. The probe showed a fresh 0.2 s budget persisting through the same trigger, and the whole request took 0.002 s. - excludes: Persisting under the request's own deadline, which has already expired, gets "interrupted" from the progress handler. The error is logged and rolled back, so every row stays as seeded. This run failed :211 with `assert 1790556377740.1506 <= 1`: last_checked_at was still 1.
- C1 - tests/tmp/test_11_fast_similars_response_phase2.py:211–218 via _assert_written from :225 (ANSWERING) and :233 (CHANNEL_FAILED) — when the detail answered, the videos, channels and instances rows are written. With the channel call answering None, the channel display name and followers keep the DB's "DB Chan"/5 while the slug becomes live_slug. - expected: ANSWERING gives v1 = LIVE_VIDEO (title "Live title", views 1000, tags_json '["live"]', category "Music", nsfw 0, channel_name "Live Chan") and c1 = live_slug/Live Chan/77. CHANNEL_FAILED gives the same video values except channel_name "DB Chan", and c1 = live_slug/DB Chan/5. In both, instances last_error* are NULL, last_checked_at is inside the window, and popularity > 0. All of this was seen in the probe and in this run, where both tests passed. - excludes: A success signal that is too strict leaves every row as seeded ("DB title", views 10, last_checked_at 1, 'boom') and fails :211: for example, persisting nothing, or counting a failed channel call as a failed refresh. These two tests are green today as guards on the positive half of "only when".
- C2 - tests/tmp/test_11_fast_similars_response_phase2.py:269 — the id-based similars GET sent while the refresh sits in a 5 s instance call answers in under 1.0 s. With :265 (status 200) and :267 (seed v1, rows ["v2"], the real ANN answer). Controls: :262 (the GET was sent while the refresh was inside the call) and :263 (the refresh was held ≥ 4.5 s). - expected: 200, seed v1, rows ["v2"], elapsed a few ms. The probe observed 0.0016 s during a blocked refresh, and in this run the test passed. - excludes: With the instance call made inside db_lock, the similars GET waits the refresh out. The probe observed 4.0 s against a stub holding srv.db_lock for 2 s × 2 calls, which fails :269.
- C2 - tests/tmp/test_11_fast_similars_response_phase2.py:271 and :272 — when the similars GET answered, and again after the refresh finished, the instance stub's call log is only [[tube.example, /api/v1/videos/uuid-v1]]. - expected: [["tube.example", "/api/v1/videos/uuid-v1"]] at both points, as seen in the probe and in this run. - excludes: A similars route that contacted the instance would add its own call. Under a lock-held refresh, the similars GET answers only after the refresh has finished all of its calls. The probe's locked run showed the channel call already in the log at that point.

<assertions>
tests/tmp/test_11_fast_similars_response_phase2.py:211 - after an answered refresh, videos.v1.last_checked_at falls inside the run's wall-clock window in ms (seeded as 1) - C1 (shared by the success, channel-failed and expired-deadline tests through _assert_written)
tests/tmp/test_11_fast_similars_response_phase2.py:212 - videos.v1.popularity > 0 (seeded 0.0), so it was recomputed - C1
tests/tmp/test_11_fast_similars_response_phase2.py:215 - every videos row equals the seed, except that v1 carries the instance's title, description, channel_name, views, likes, dislikes, tags_json, category and nsfw; v2 is untouched - C1
tests/tmp/test_11_fast_similars_response_phase2.py:216 - channels.c1 equals the seed, except that channel_name, display_name and followers_count hold the written values: live_slug/Live Chan/77 on success, and live_slug/DB Chan/5 when the channel call failed - C1
tests/tmp/test_11_fast_similars_response_phase2.py:218 - instances row equals the seed with last_error, last_error_at and last_error_source all NULL (seeded 'boom', 123, 'crawler') - C1
tests/tmp/test_11_fast_similars_response_phase2.py:224 - control in test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows: the calls are the detail then the channel path; then _assert_written(LIVE_VIDEO, LIVE_CHANNEL) - C1
tests/tmp/test_11_fast_similars_response_phase2.py:231 - control in test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields: the channel call was made and answered None; then _assert_written(DB_CHANNEL_VIDEO, DB_CHANNEL_CHANNEL) - C1
tests/tmp/test_11_fast_similars_response_phase2.py:239 - control in test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed: the refresh took at least 1.0 s under statement_timeout_seconds=0.2, so the request deadline had passed before the write; then _assert_written(LIVE_VIDEO, LIVE_CHANNEL) over a DB with a heavy AFTER UPDATE trigger - C1
tests/tmp/test_11_fast_similars_response_phase2.py:252 - control, parametrized over detail None, {}, a JSON list and URLError raised by urlopen: the refresh made exactly one instance call, for the detail path - C1
tests/tmp/test_11_fast_similars_response_phase2.py:254 - each failure case answers (200, DB_ONLY), all eighteen fields taken from the seeded row - C1
tests/tmp/test_11_fast_similars_response_phase2.py:256 - each failure case leaves every column of the videos, channels and instances rows, last_checked_at and last_error included, identical before and after - C1
tests/tmp/test_11_fast_similars_response_phase2.py:262 - control: the similars GET was sent while the refresh was inside the instance call - C2
tests/tmp/test_11_fast_similars_response_phase2.py:263 - control: the refresh answered 200 after at least 4.5 s, so it really was blocked - C2
tests/tmp/test_11_fast_similars_response_phase2.py:265 - /videos/v1/similar answers 200 - C2
tests/tmp/test_11_fast_similars_response_phase2.py:267 - its seed is v1 and its rows are exactly [v2], the real ANN answer (flat faiss index plus the Engine's own recommendation strategy) - C2
tests/tmp/test_11_fast_similars_response_phase2.py:269 - the similars GET answered in under 1.0 s while the refresh was blocked for 5 s - C2
tests/tmp/test_11_fast_similars_response_phase2.py:271 - when the similars GET answered, the instance stub had been called only for the refresh's /api/v1/videos/uuid-v1 - C2
tests/tmp/test_11_fast_similars_response_phase2.py:272 - after the refresh finished, the whole call log is still only that one detail call, so the similars GET made no instance call - C2
</assertions>

<probes>
All runs were `ValidateTests ["tests/tmp/probe_11_phase2.py"]`: an ENGINE_PY child over temporary whitelist-shaped DBs, with fetch_instance_json (or urlopen) patched. The file went through three versions.
1) Pre-phase code, failure cases, instances seeded with 'boom', 123, 'crawler':
- detail None, detail {} and URLError at urlopen each answered 200 with the DB-only body now recorded as DB_ONLY (channelUrl .../video-channels/db_slug, accountAvatarUrl "", views 10, likes 2, dislikes 1), and each changed the rows: last_checked_at went from 1 to now, popularity went from 0.0 to about 0.39, and instances.last_error/_at/_source became NULL.
- A detail that was a JSON list raised AttributeError, and the connection dropped with RemoteDisconnected (status None).
2) Pre-phase code, success: the rows took the instance's values (channels live_slug / Live Chan / 77, videos Music / '["live"]', popularity about 30.6), and the instance errors became NULL.
3) Pre-phase code, statement_timeout_seconds=0.2 with a 0.5 s delay per call:
- On the plain schema the write still succeeded, even with a 188,894-character description. The real UPDATE plus the FTS trigger never reaches the 10,000-instruction progress check, so without a heavier write this case cannot fail on the old code.
- With the fixture trigger `heavy_au` (SELECT count(*) FROM heavy a, heavy b over 300 rows), the child logged "[video] failed to persist dynamic metadata for video_id=v1 host=tube.example: interrupted" and the rows were unchanged.
- The same trigger with a 0.2 s timeout and no delay persisted: the whole request took 0.002 s. So a fresh 0.2 s budget is enough for the fix.
4) Similars GET /videos/v1/similar?host=tube.example:
- With no embeddings it answered 400 "Missing vector or video reference".
- With embeddings but a None strategy it answered 500.
- With two embeddings, a faiss IndexIDMap(IndexFlatIP(4)), and the strategy built from server.py's own names, it answered 200 with rows [v2] and seed v1: 0.006 s alone and 0.0016 s during a refresh blocked for 3 s. At that point the call log held only the detail call.
5) Wrong implementation simulated: the stub held srv.db_lock while sleeping 2 s per call. The similars GET then took 4.0 s, and the call log already held the channel call as well.
6) The checkpoint itself on the pre-phase code: `ValidateTests ["tests/tmp/test_11_fast_similars_response_phase2.py"]` → 5 failed, 3 passed.
- Failed: the expired-deadline test (last_checked_at is still 1) and all four no-write cases (rows changed; the list case answered status None).
- Passed: the success test, the channel-failed test and the similars test. Phase 1 already keeps the instance calls outside db_lock and already persists on success. These pass today as guards, and step 5 shows the similars assertions do fail against the wrong implementation.
The probe file tests/tmp/probe_11_phase2.py is still on disk and needs deleting: I have no delete tool, and it ends in `assert False`.
</probes>

<unassertable>
none
</unassertable>

### `tests/tmp/test_11_fast_similars_response_phase2.py` - 19107 characters, inlined in full

```
"""GET `/api/video/refresh` writes the `videos`, `channels` and `instances` rows only when the instance's video detail call answered, and a refresh blocked on the instance does not hold up the id-based similars GET.

- With the detail and channel calls answering, the video row holds the instance's title, description, channel display name, counts, tags, category and nsfw, with `last_checked_at` inside the run's wall-clock window and a nonzero `popularity`; the channel row holds the instance's slug, display name and the channel call's follower count; the instance row's `last_error`, `last_error_at` and `last_error_source` are NULL; every other column and the other video's row are unchanged. With the channel call answering nothing, the rows are written the same way, but the channel display name and follower count keep the DB's values.
- With `statement_timeout_seconds` at 0.2 and each instance call taking 0.5 s, so the request's own deadline has passed before the write, the same rows are written. The fixture DB carries an extra AFTER UPDATE trigger on `videos` that runs well past the progress handler's 10,000-instruction check; without it the real UPDATE never reaches that check, and an expired deadline would go unnoticed.
- With the detail call answering `None`, `{}`, a JSON list, or failing with `URLError` at `urlopen`, the refresh answers 200 with the DB-only values, and every column of the `videos`, `channels` and `instances` rows, `last_checked_at` and `last_error` included, is the same before and after.
- With the detail call blocking for 5 s, a `/videos/v1/similar` GET sent while the refresh is inside that call answers 200 with its ANN neighbour in under 1 s, and the instance stub has by then been called only for the refresh's `/api/v1/videos/{uuid}`.

Each case runs under the Engine's interpreter in a child process: a real `SimilarServer` with the real `SimilarHandler` on an ephemeral port, over its own whitelist-shaped temporary DB (schema from `sync-whitelist.py`). `handlers.video.fetch_instance_json` is replaced by a stub that records each call and answers from the case's path map, or `handlers.video.urlopen` by one that raises `URLError`. For the similars case the child also builds a flat faiss index over the DB's embeddings and the Engine's own recommendation strategy.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from array import array
from pathlib import Path

import pytest

# The active suite's conftest, importable whether this file runs from tests/tmp or tests/active.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import ENGINE_PY, ROOT  # noqa: E402

SERVER_DIR = ROOT / "engine" / "server"
API_DIR = SERVER_DIR / "api"
JOBS_DIR = SERVER_DIR / "db" / "jobs"
HOST = "tube.example"
UUID = "uuid-v1"
REFRESH = f"/api/video/refresh?id={UUID}&host={HOST}"
SIMILAR = f"/videos/v1/similar?host={HOST}"
DETAIL_PATH = f"/api/v1/videos/{UUID}"
CHANNEL_PATH = "/api/v1/video-channels/live_slug"
# Every value differs from the row's, so a row left as seeded cannot pass for a written one.
DETAIL = {"name": "Live title", "description": "Live description", "views": 1000, "likes": 50, "dislikes": 3, "tags": ["live"], "category": {"label": "Music"}, "nsfw": False, "channel": {"name": "live_slug", "displayName": "Live Chan", "followersCount": 70}, "account": {"displayName": "Live Account", "url": f"https://{HOST}/accounts/live", "avatar": {"path": "/lazy-static/avatars/live.png"}}}
ANSWERING = {DETAIL_PATH: DETAIL, CHANNEL_PATH: {"displayName": "Live Chan Detail", "followersCount": 77}}
# The detail names the channel slug but no display name or followers, and the channel call is not in the map, so it answers None.
CHANNEL_FAILED = {DETAIL_PATH: {**DETAIL, "channel": {"name": "live_slug"}}}
# The columns an answered refresh writes, over ANSWERING and over CHANNEL_FAILED.
LIVE_VIDEO = {"title": "Live title", "description": "Live description", "channel_name": "Live Chan", "views": 1000, "likes": 50, "dislikes": 3, "tags_json": '["live"]', "category": "Music", "nsfw": 0}
LIVE_CHANNEL = {"channel_name": "live_slug", "display_name": "Live Chan", "followers_count": 77}
DB_CHANNEL_VIDEO = {**LIVE_VIDEO, "channel_name": "DB Chan"}
DB_CHANNEL_CHANNEL = {"channel_name": "live_slug", "display_name": "DB Chan", "followers_count": 5}
CLEARED_INSTANCE = {"last_error": None, "last_error_at": None, "last_error_source": None}
# The refresh's answer when the instance supplied nothing: every field from the seeded row (observed on today's refresh with the detail answering None).
DB_ONLY = {
    "videoUuid": UUID,
    "title": "DB title",
    "description": "DB description",
    "channelName": "DB Chan",
    "channelUrl": f"https://{HOST}/video-channels/db_slug",
    "channelAvatarUrl": f"https://{HOST}/lazy-static/avatars/db.png",
    "subscribersCount": 5,
    "instanceName": HOST,
    "instanceUrl": f"https://{HOST}",
    "accountName": "DB Account",
    "accountUrl": f"https://{HOST}/accounts/db",
    "accountAvatarUrl": "",
    "embedUrl": f"https://{HOST}/videos/embed/{UUID}",
    "originalUrl": f"https://{HOST}/videos/watch/{UUID}",
    "views": 10,
    "likes": 2,
    "dislikes": 1,
    "publishedAt": 1_700_000_000_000,
}
# Starts each case's server on its own DB, sends the refresh (and, for a similars case, the similars GET while the refresh sits in the instance call), and reports statuses, bodies, timings and every instance call.
CHILD = r'''
import http.client, inspect, json, sys, threading, time
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import faiss, numpy as np
import server
from data.db import connect_db
from handlers import video
from handlers.similar import SimilarHandler

def get(port, path):
    started = time.monotonic()
    try:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        client.request("GET", path)
        resp = client.getresponse()
        raw = resp.read()
        client.close()
        return {"status": resp.status, "body": json.loads(raw or b"null"), "elapsed": time.monotonic() - started}
    except Exception as exc:
        return {"status": None, "body": repr(exc), "elapsed": time.monotonic() - started}

def similars_stack(conn):
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    rows = conn.execute("SELECT rowid, embedding FROM video_embeddings").fetchall()
    index.add_with_ids(np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]), np.array([r["rowid"] for r in rows], dtype=np.int64))
    deps = server.RecommendationBuilderDeps(fetch_recent_likes=server.fetch_recent_likes_request, fetch_seed_embedding=server.fetch_seed_embedding, fetch_seed_embeddings_for_likes=server.fetch_seed_embeddings_for_likes, get_similar_candidates=server.get_similar_candidates, like_key=server.like_key, fetch_embeddings_by_ids=server.fetch_embeddings_by_ids, fetch_random_rows=server.fetch_random_rows, fetch_random_rows_from_cache=server.fetch_random_rows_from_cache, fetch_recent_videos=server.fetch_recent_videos, fetch_popular_videos=server.fetch_popular_videos, fetch_dislike_centroids=server.fetch_request_dislike_centroids, fetch_excluded_keys=server.fetch_request_excluded_keys)
    settings = server.RecommendationBuilderSettings(max_likes=server.MAX_LIKES, max_likes_for_recs=server.MAX_LIKES_FOR_RECS, similar_per_like=server.SIMILAR_PER_LIKE, default_similar_from_likes_source=server.DEFAULT_USE_SIMILARITY_CACHE, video_error_threshold=server.VIDEO_ERROR_THRESHOLD, fresh_pool_size=server.DEFAULT_FRESH_POOL_SIZE, dislike_similarity_floor=server.DISLIKE_SIMILARITY_FLOOR)
    strategy = server.build_recommendation_strategy(server.RECOMMENDATION_PIPELINE, deps, settings)
    strategy.settings = settings
    return {"index": index, "embeddings_dim": 4, "embeddings_count": len(rows), "default_limit": 8, "normalize_queries": True, "similarity_search_limit": 0, "similarity_max_per_author": 0, "similarity_exclude_source_author": False, "similarity_require_full_cache": False, "recommendation_strategy": strategy}

reports = []
for case in json.loads(sys.argv[1]):
    conn = connect_db(Path(case["db"]))
    args = dict.fromkeys(list(inspect.signature(server.SimilarServer.__init__).parameters)[3:])
    extra = similars_stack(conn) if case["similar"] else {}
    srv = server.SimilarServer(("127.0.0.1", 0), SimilarHandler, **{**args, "db": conn, "video_error_threshold": 3, "popularity_like_weight": 2.0, **extra})
    if case["timeout"] is not None:
        srv.statement_timeout_seconds = case["timeout"]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    calls = []
    entered = threading.Event()
    def stub(host, api_path):
        calls.append([host, api_path])
        entered.set()
        time.sleep(case["delay"])
        return case["answers"].get(api_path)
    def refusing(req, timeout=None):
        calls.append([req.host, req.selector])
        raise URLError("instance down")
    report = {}
    try:
        with patch.object(video, "urlopen", refusing) if case["refuse"] else patch.object(video, "fetch_instance_json", stub):
            if case["similar"]:
                holder = {}
                worker = threading.Thread(target=lambda: holder.update(get(port, case["path"])))
                worker.start()
                report["entered"] = entered.wait(10)
                report["similar"] = get(port, case["similar"])
                report["calls_at_similar"] = [list(call) for call in calls]
                worker.join(30)
                report["refresh"] = holder
            else:
                report["refresh"] = get(port, case["path"])
        report["calls"] = calls
        reports.append(report)
    finally:
        srv.shutdown()
        srv.server_close()
        conn.close()
print(json.dumps(reports))
'''


@pytest.fixture(scope="module")
def sync_job():
    spec = importlib.util.spec_from_file_location("sync_whitelist_video_metadata_phase2", JOBS_DIR / "sync-whitelist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(sync_job, path: Path, heavy: bool) -> None:
    conn = sqlite3.connect(path)
    try:
        sync_job.ensure_whitelist_schema(conn)
        sync_job.ensure_content_schema(conn)
        conn.execute("INSERT INTO instances (host, last_error, last_error_at, last_error_source) VALUES (?, 'boom', 123, 'crawler')", (HOST,))
        conn.execute("INSERT INTO channels (channel_id, instance_domain, channel_name, display_name, followers_count, avatar_url) VALUES ('c1', ?, 'db_slug', 'DB Chan', 5, ?)", (HOST, f"https://{HOST}/lazy-static/avatars/db.png"))
        conn.execute(
            "INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, channel_name, account_name, account_url, title, description, tags_json, category, published_at, embed_path, views, likes, dislikes, nsfw, last_checked_at) VALUES ('v1', ?, ?, 'c1', 'DB Chan', 'DB Account', ?, 'DB title', 'DB description', '[\"db-tag\"]', 'DB cat', 1700000000000, ?, 10, 2, 1, 0, 1)",
            (UUID, HOST, f"https://{HOST}/accounts/db", f"/videos/embed/{UUID}"),
        )
        # v1's ANN neighbour on another channel, the only row the similars GET can answer; it also shows a refresh of v1 leaves other rows alone.
        conn.execute("INSERT INTO videos (video_id, video_uuid, instance_domain, channel_id, title, published_at, embed_path, views, likes, dislikes, last_checked_at) VALUES ('v2', 'uuid-v2', ?, 'c2', 'Neighbour', 1700000000000, '/videos/embed/uuid-v2', 5, 1, 0, 1)", (HOST,))
        conn.execute("INSERT INTO video_embeddings VALUES ('v1', ?, ?, 4, 'm', 'now')", (HOST, array("f", [1, 0, 0, 0]).tobytes()))
        conn.execute("INSERT INTO video_embeddings VALUES ('v2', ?, ?, 4, 'm', 'now')", (HOST, array("f", [0.8, 0.6, 0, 0]).tobytes()))
        if heavy:
            # About 90,000 joined rows per videos UPDATE: past the progress handler's 10,000-instruction check, yet a few ms of work (observed persisting inside a 0.2 s budget).
            conn.execute("CREATE TABLE heavy (n INTEGER)")
            conn.executemany("INSERT INTO heavy VALUES (?)", [(n,) for n in range(300)])
            conn.execute("CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END")
        conn.commit()
    finally:
        conn.close()


def _rows(path: Path) -> dict[str, dict[str, dict]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "videos": {row["video_id"]: dict(row) for row in conn.execute("SELECT * FROM videos")},
            "channels": {row["channel_id"]: dict(row) for row in conn.execute("SELECT * FROM channels")},
            "instances": {row["host"]: dict(row) for row in conn.execute("SELECT * FROM instances")},
        }
    finally:
        conn.close()


def _run(sync_job, tmp_path: Path, answers: dict, *, delay: float = 0, timeout: float | None = None, refuse: bool = False, heavy: bool = False, similar: str | None = None) -> dict:
    """Run one refresh case on a freshly seeded DB; return the child's report with the rows before and after and the run's wall-clock window in ms."""
    db_path = tmp_path / "case.db"
    _seed(sync_job, db_path, heavy)
    before = _rows(db_path)
    case = {"db": str(db_path), "path": REFRESH, "answers": answers, "delay": delay, "timeout": timeout, "refuse": refuse, "similar": similar}
    assert ENGINE_PY.exists(), f"Engine interpreter missing at {ENGINE_PY}; run `pixi install` in engine/"
    started_ms = time.time() * 1000
    run = subprocess.run([str(ENGINE_PY), "-c", CHILD, json.dumps([case])], cwd=API_DIR, capture_output=True, text=True, timeout=120)
    finished_ms = time.time() * 1000
    assert run.returncode == 0, run.stderr[-2000:]  # control: the Engine's interpreter built the server and ran every request
    (report,) = json.loads(run.stdout)
    return {**report, "before": before, "after": _rows(db_path), "window": (started_ms, finished_ms)}


def _assert_written(report: dict, video: dict, channel: dict) -> None:
    before, after = report["before"], report["after"]
    written = after["videos"]["v1"]
    # Left unwritten, last_checked_at stays 1 and popularity 0.0 as seeded.
    assert report["window"][0] <= written["last_checked_at"] <= report["window"][1]  # C1
    assert written["popularity"] > 0  # C1
    unstamped = {**written, "last_checked_at": None, "popularity": None}
    # Left unwritten, the video row still reads "DB title", views 10 and the rest of the seed; v2 is untouched either way.
    assert {**after["videos"], "v1": unstamped} == {**before["videos"], "v1": {**before["videos"]["v1"], **video, "last_checked_at": None, "popularity": None}}  # C1
    assert after["channels"] == {"c1": {**before["channels"]["c1"], **channel}}  # C1
    # Left unwritten, the instance row still reads 'boom', 123, 'crawler'.
    assert after["instances"] == {HOST: {**before["instances"][HOST], **CLEARED_INSTANCE}}  # C1


def test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows(sync_job, tmp_path):
    report = _run(sync_job, tmp_path, ANSWERING)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the detail and the channel call both answered
    _assert_written(report, LIVE_VIDEO, LIVE_CHANNEL)


def test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields(sync_job, tmp_path):
    report = _run(sync_job, tmp_path, CHANNEL_FAILED)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["calls"] == [[HOST, DETAIL_PATH], [HOST, CHANNEL_PATH]]  # control: the channel call was made and answered nothing
    # Counting a failed channel call as a failed refresh leaves every row as seeded.
    _assert_written(report, DB_CHANNEL_VIDEO, DB_CHANNEL_CHANNEL)


def test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed(sync_job, tmp_path):
    report = _run(sync_job, tmp_path, ANSWERING, delay=0.5, timeout=0.2, heavy=True)
    assert report["refresh"]["status"] == 200, report["refresh"]["body"]
    assert report["refresh"]["elapsed"] >= 1.0  # control: both instance calls took their 0.5 s, so the request's 0.2 s deadline had passed before the write
    # Writing under the request's expired deadline is interrupted: "[video] failed to persist ... interrupted" is logged and every row stays as seeded (observed on the pre-phase code).
    _assert_written(report, LIVE_VIDEO, LIVE_CHANNEL)


@pytest.mark.parametrize("answers, refuse", [
    ({}, False),
    ({DETAIL_PATH: {}}, False),
    ({DETAIL_PATH: [DETAIL]}, False),
    ({}, True),
], ids=["detail-none", "detail-empty-object", "detail-json-list", "urlopen-urlerror"])
def test_a_refresh_the_instance_did_not_answer_writes_nothing(sync_job, tmp_path, answers, refuse):
    report = _run(sync_job, tmp_path, answers, refuse=refuse)
    assert report["calls"] == [[HOST, DETAIL_PATH]]  # control: the refresh asked the instance for the detail, and only that
    # A JSON list reaching `detail.get` drops the connection unanswered (status None); the others answer these DB values today too.
    assert (report["refresh"]["status"], report["refresh"]["body"]) == (200, DB_ONLY)  # C1
    # Writing on a failed call bumps last_checked_at from 1, recomputes popularity from 0.0 and clears instances.last_error 'boom' (observed on the pre-phase code for None, {} and URLError).
    assert report["after"] == report["before"]  # C1


def test_similars_answer_while_a_refresh_is_blocked_on_the_instance(sync_job, tmp_path):
    # A detail naming no channel, so the refresh makes one 5 s instance call.
    report = _run(sync_job, tmp_path, {DETAIL_PATH: {**DETAIL, "channel": {}}}, delay=5, similar=SIMILAR)
    assert report["entered"] is True  # control: the similars GET went out while the refresh was inside the instance call
    assert report["refresh"]["status"] == 200 and report["refresh"]["elapsed"] >= 4.5, report["refresh"]  # control: the refresh really was held about 5 s
    similar = report["similar"]
    assert similar["status"] == 200, similar["body"]  # C2
    # The real ANN answer for v1 over this DB: its neighbour v2, and not the seed itself.
    assert (similar["body"]["seed"]["video_id"], [row["video_id"] for row in similar["body"]["rows"]]) == ("v1", ["v2"])  # C2
    # With the instance call made inside db_lock, the similars GET waits the refresh out (observed 4.0 s against a 2 s x 2 locked stub); unblocked it took about 2 ms.
    assert similar["elapsed"] < 1.0, similar["elapsed"]  # C2
    # The similars GET adds no instance call of its own; a locked refresh has already finished its calls by the time the similars answer.
    assert report["calls_at_similar"] == [[HOST, DETAIL_PATH]]  # C2
    assert report["calls"] == [[HOST, DETAIL_PATH]]  # C2

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - red (audit round 1)

`tests/tmp/test_11_fast_similars_response_phase2.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase2.py  5 failed, 3 passed                     0.0s
  --------------------------------------------------
  total                                               5 failed, 3 passed                    11.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - PASS
- OUTSTANDING: 1 UNCARRIED clause(s) - D11

### devsecops-test-shape-auditor

SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
The parametrized test `test_a_refresh_the_instance_did_not_answer_writes_nothing` fails. For `detail-none`, `detail-empty-object` and `urlopen-urlerror` it fails at tests/tmp/test_11_fast_similars_response_phase2.py:256 on `assert report["after"] == report["before"]`. `fetch_instance_video_dynamic` always returns a dict full of keys, so `if dynamic` at handlers/video.py:399 is truthy and `persist_video_metadata` runs. That run moves `videos.last_checked_at` off 1, recomputes `popularity` and clears `instances.last_error` 'boom'. For `detail-json-list` it fails earlier, at line 254 on `(status, body) == (200, DB_ONLY)`: `detail.get` on the list raises AttributeError and the connection drops with status None. `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` also fails, at line 211 inside `_assert_written` (called from line 241) on the `last_checked_at` window check. `do_GET` wraps the refresh in `statement_deadline(0.2)`, so the heavy trigger's UPDATE is interrupted and the OperationalError is swallowed at handlers/video.py:382.

NOT ASSESSED
1. `fixtures_path` was given as "none found". `ENGINE_PY` and `ROOT` were resolved from tests/active/conftest.py, which the test imports explicitly at line 25. The test's only fixture, `sync_job`, is defined in the test file. `sync-whitelist.py`'s `ensure_whitelist_schema` / `ensure_content_schema` were not read, so the seeded column set was not checked against the schema.
2. `code_under_test` lists tests/active/test_video_metadata.py as EDITED. It is a test file, not code the test under audit exercises, so it was not read.
3. `server.SimilarServer`, `RecommendationBuilderDeps` / `RecommendationBuilderSettings` and the similars route handler were not read. The C2 part of the stub question was answered from the assertion form: lines 267 and 269 pin a specific ANN answer (`("v1", ["v2"])`) and elapsed < 1.0 s against a 5 s blocked refresh. A fast canned answer, or the older behaviour where the instance call runs inside `db_lock`, would not pass both.

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (27 clauses: 7 must_prove, 15 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :215 (via :225) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:36) | CARRIED |
| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :216 (via :225) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |
| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :218 (via :225) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |
| C1d | must_prove | "only when": no `videos` write when the detail call did not answer | :256 | a write on None / {} / list / URLError; bumping last_checked_at or popularity would break the before==after equality | CARRIED |
| C1e | must_prove | "only when": no `channels` write when the detail call did not answer | :256 | a channel UPDATE that runs on a failed detail call | CARRIED |
| C1f | must_prove | "only when": no `instances` write when the detail call did not answer | :256 | clearing last_error on a failed call | CARRIED |
| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :269, preconditions :262, :263 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |
| D1 | docstring | "writes the videos, channels and instances rows only when the ... detail call answered" | :215–:218, :256 | same as C1a–C1f | CARRIED |
| D2 | docstring | "a refresh blocked on the instance does not hold up the id-based similars GET" | :269 | same as C2 | CARRIED |
| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :215 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |
| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :211 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |
| D5 | docstring | nonzero `popularity` | :212 | popularity left as seeded, or not recomputed | CARRIED |
| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :216 | taking the followers from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |
| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :218 | any of the three left uncleared | CARRIED |
| D8 | docstring | every other column and the other video's row unchanged | :215, :216, :218 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |
| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :233 (via :211–:218) | counting a failed channel call as a failed refresh (:211 fails); nulling display_name or followers_count | CARRIED |
| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :241, precondition :239 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |
| D11 | docstring | the extra AFTER UPDATE trigger "runs well past the progress handler's 10,000-instruction check" | none | nothing asserts the trigger reaches the check, so a fixture whose UPDATE never hits the progress handler lets D10 pass without testing anything | UNCARRIED |
| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :254 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |
| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :256 | any write on the failed-detail path | CARRIED |
| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :265, :267, precondition :262 | an error answer; an empty answer; returning the seed itself | CARRIED |
| D15 | docstring | "in under 1 s" | :269 | the similars GET serialised behind the 5 s instance call | CARRIED |
| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :271, :272 | the similars route making instance calls of its own | CARRIED |
| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :202 | a child that failed to build the server or run the requests | CARRIED |
| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :215, :216, :218 | as C1a–C1c | CARRIED |
| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :233 | as D9 | CARRIED |
| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :241, :239 | as D10 | CARRIED |
| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :256 | as C1d–C1f | CARRIED |
| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :265, :267, :269 with :262, :263 | as C2 / D14 | CARRIED |

CRITICAL
none

RECOMMENDATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase2.py:4, :173
   `conn.execute("CREATE TRIGGER heavy_au AFTER UPDATE ON videos BEGIN SELECT count(*) FROM heavy a, heavy b; END")`
   D11 is UNCARRIED. The docstring says this trigger drives the UPDATE past the progress handler's 10,000-instruction check. The only support is the "observed" comments at :170 and :240. No assertion shows the check actually runs during the write in this fixture. Without that, D10 / N3 cannot tell an expired deadline that was honoured from one that was never checked. Either add a control that the deadline does interrupt a write in this fixture, or narrow the sentence.
2. bounds (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase2.py:244–249
   The "did not answer" cases are None, `{}`, a JSON list and URLError. These are not tested:
   - a non-empty dict carrying none of the known fields, such as `{"error": "..."}`
   - a non-200 status reaching `fetch_instance_json` through `urlopen`

   These are the edges between "answered" and "not answered" that C1's "only when" depends on.
3. normal-and-abnormal-paths (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase2.py:261
   C2 is only tested with a slow instance that does answer (`{**DETAIL, "channel": {}}`). No test covers a refresh that is blocked and then fails, such as a slow URLError or a detail that comes back None, while a similars GET is in flight.

OBSERVATIONS
none

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_metadata.py, which does not exist, so it was not read.
2. The statement-deadline and progress-handler code (engine/server/api/server.py:272, engine/server/api/handlers/similar.py:351) is not in `code_under_test`. D10 and D11 were judged from the test and handlers/video.py only.
3. The `popularity` column's seeded default (relied on at :210 and :212) was not confirmed in `sync-whitelist.py`'s schema.

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - self-check (audit round 2, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase2.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase2.py:237, :238, :241, :242, :244 (_assert_written, called from :251, :259 and :270): last_checked_at falls inside the run's window, popularity > 0, v1 carries the live video columns with v2 untouched, channels.c1 carries the written slug, display name and followers, and the instance errors are NULL. :283 and :285 (parametrized over None, {}, a JSON list and URLError): the refresh answers (200, DB_ONLY) and the rows before equal the rows after. Controls: :250, :257, :268, :281, plus :264 and :265 for the expired-deadline fixture. - expected: Answered detail: the videos, channels and instances rows are written, including after the request's 0.2 s deadline has expired. Unanswered detail: 200 with DB_ONLY and no row changed. - excludes: Pre-phase code does two things wrong. It persists on any truthy dynamic dict, so for None, {} and URLError last_checked_at moves off 1, popularity is recomputed and last_error 'boom' is cleared, and :285 goes red; the list case drops the connection with status None, so :283 goes red. It also persists under the request's expired deadline, so the heavy-trigger UPDATE is interrupted and last_checked_at stays 1, and :237 goes red (observed just now). A refresh that skips the write altogether reddens :237 in the success and channel-failed tests.
- C2 - tests/tmp/test_11_fast_similars_response_phase2.py:294, :296, :298, :300, :301, with the controls at :291 and :292: the similars GET, sent while the refresh sits in a 5 s instance call, answers 200 with seed v1 and rows [v2] in under 1.0 s, and the only instance call is the refresh's detail call. - expected: status 200, ("v1", ["v2"]), elapsed about 2 ms, calls [[tube.example, /api/v1/videos/uuid-v1]] - excludes: If the instance call is made inside db_lock, the similars GET waits the refresh out. It was observed at 4.0 s against a locked 2 s × 2 stub, so :298 goes red. A canned or empty similars answer fails :296.

<items>
<item id="D11">
<disposition>fixed</disposition>
<what>I added a control at the top of test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed, with a new helper `_interrupted` (:193) and a module fixture `data_db` (:143). The fixture loads engine/server/data/db.py, which is stdlib only. The helper seeds a DB, opens it with the Engine's own `connect_db`, so the real `install_deadline_handler` and the real PROGRESS_HANDLER_INSTRUCTIONS apply and the test copies no constant. Inside a `statement_deadline(0.05)` it sleeps 0.1 s, runs an UPDATE on v1, and returns True only when `is_interrupted_error` recognises the raised error. Any other OperationalError is re-raised. There are two assertions. :264 says that on the heavy-trigger fixture the UPDATE is interrupted (`is True`). :265 says that on the plain schema the same UPDATE finishes (`is False`). Together they show the trigger is what carries the write to the progress handler's check. The wrong fixture they rule out is one whose UPDATE never reaches the check, for example no trigger, a trigger too light, or a schema change that drops it. That fixture makes :264 read False, so D10 can no longer pass without testing anything. I ran both results in a probe (tests/tmp/probe_11_d11.py, SQLite 3.53.4) before writing them down: heavy gave OperationalError('interrupted') and plain gave 'ok'. With the control in place, `-k deadline` on the pre-phase code still fails at :237 (`last_checked_at` is still 1, inside _assert_written called from :270). The new controls at :264 and :265 pass.</what>
</item>
</items>

<findings_addressed>
Neither auditor raised a CRITICAL. I took claim-audit recommendation 1 (D11 whole-claim, :4 and :173): the deadline test now opens with the controls at :264 and :265 described under D11. They show, through the Engine's own connect_db and statement_deadline, that an expired deadline interrupts a v1 UPDATE on the heavy fixture and does not on the plain schema. I left claim-audit recommendations 2 (a non-empty dict with no known fields, and a non-200 status) and 3 (C2 with a slow refresh that then fails) alone. Both would add cases beyond the ledger, and this round is bounded to it. Housekeeping: I have no delete tool, so the probes tests/tmp/probe_11_phase2.py and tests/tmp/probe_11_d11.py are still on disk. Both end in `assert False` and need deleting before any tests/tmp run.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:237, :238, :241, :242, :244 (_assert_written, called from :251, :259 and :270): last_checked_at falls inside the run's window, popularity > 0, v1 carries the live video columns with v2 untouched, channels.c1 carries the written slug, display name and followers, and the instance errors are NULL. :283 and :285 (parametrized over None, {}, a JSON list and URLError): the refresh answers (200, DB_ONLY) and the rows before equal the rows after. Controls: :250, :257, :268, :281, plus :264 and :265 for the expired-deadline fixture.</assertion>
<expected>Answered detail: the videos, channels and instances rows are written, including after the request's 0.2 s deadline has expired. Unanswered detail: 200 with DB_ONLY and no row changed.</expected>
<wrong_implementation>Pre-phase code does two things wrong. It persists on any truthy dynamic dict, so for None, {} and URLError last_checked_at moves off 1, popularity is recomputed and last_error 'boom' is cleared, and :285 goes red; the list case drops the connection with status None, so :283 goes red. It also persists under the request's expired deadline, so the heavy-trigger UPDATE is interrupted and last_checked_at stays 1, and :237 goes red (observed just now). A refresh that skips the write altogether reddens :237 in the success and channel-failed tests.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_11_fast_similars_response_phase2.py:294, :296, :298, :300, :301, with the controls at :291 and :292: the similars GET, sent while the refresh sits in a 5 s instance call, answers 200 with seed v1 and rows [v2] in under 1.0 s, and the only instance call is the refresh's detail call.</assertion>
<expected>status 200, ("v1", ["v2"]), elapsed about 2 ms, calls [[tube.example, /api/v1/videos/uuid-v1]]</expected>
<wrong_implementation>If the instance call is made inside db_lock, the similars GET waits the refresh out. It was observed at 4.0 s against a locked 2 s × 2 stub, so :298 goes red. A canned or empty similars answer fails :296.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The only negative in the new code is :265 (the plain-schema UPDATE is not interrupted). It is paired with the positive at :264 (the heavy UPDATE is interrupted), and both run through the real handler. The no-write assertion at :285 keeps its control at :281.
2. No. The control does not copy production's 10,000-instruction constant or its handler. It calls the Engine's own connect_db, statement_deadline and is_interrupted_error. Removing install_deadline_handler from connect_db turns :264 red. Removing the heavy_au trigger from _seed also turns :264 red.
3. No. The interruption is read on two fixtures, heavy and plain, and they give opposite results.
4. No new double. data.db is loaded as the real module. The existing stubs replace only the instance HTTP layer (fetch_instance_json and urlopen).
5. Yes, everything resolves. SERVER_DIR/data/db.py exists and defines connect_db, statement_deadline and is_interrupted_error. The `-k deadline` run collected 1 test with 7 deselected, so the file still holds 8 tests.
6. Yes, both control values were observed. The interrupted/ok pair came from a probe run (SQLite 3.53.4) before I wrote them in. I did not run the control under ENGINE_PY's SQLite. The heavy join is about 90,000 rows against a 10,000-instruction check, a wide margin. The plain side is closer to the edge; running `_interrupted` inside the Engine child would confirm it there.
7. Yes. The expired-deadline test still fails at :237 (last_checked_at == 1) and gets past the new controls at :264 and :265, which pass. The rest of the file is unchanged from the run of 5 failed and 3 passed.
</answers>

<exemptions>
none
</exemptions>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - red (audit round 2)

`tests/tmp/test_11_fast_similars_response_phase2.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase2.py  5 failed, 3 passed                     0.0s
  --------------------------------------------------
  total                                               5 failed, 3 passed                    11.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - audit (round 2)

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
test_a_refresh_the_instance_did_not_answer_writes_nothing fails. For [detail-none],
[detail-empty-object] and [urlopen-urlerror] it fails at line 285 on
`assert report["after"] == report["before"]`: `fetch_instance_video_dynamic`
(video.py:189) always returns a non-empty dict of keys, so `if dynamic` (video.py:399)
is true and `persist_video_metadata` bumps `last_checked_at` from 1, recomputes
`popularity`, and clears `instances.last_error` 'boom'. For [detail-json-list] it fails
earlier, at line 283 on `(status, body) == (200, DB_ONLY)`: `detail.get` (video.py:166)
raises on a list, the connection drops, and status is None.

NOT ASSESSED
1. The `code_under_test` path tests/active/test_video_metadata.py does not resolve
   (no such file). This audit was completed from test_path, engine/server/api/handlers/video.py,
   and the symbols the test names: `statement_deadline`, `is_interrupted_error` and
   `connect_db` in engine/server/data/db.py, and `ensure_whitelist_schema` and
   `ensure_content_schema` in engine/server/db/jobs/sync-whitelist.py. All of them resolve.
2. No `fixtures_path` was supplied. The test imports `ENGINE_PY` and `ROOT` from
   tests/active/conftest.py (line 25). Both were confirmed at conftest.py:31-32, and no
   other external fixture is used.
3. The child-process names SimilarServer, RecommendationBuilderDeps and the
   server.fetch_* helpers (lines 96-107) were not traced to their definitions. The C2
   stub answer rests on the assertion form at lines 291-301, not on those symbols.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (29 clauses: 7 must_prove, 17 docstring, 5 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | refresh updates the `videos` row when the detail call answered | :241 (via :251) | a refresh that leaves v1 as seeded; every LIVE_VIDEO value differs from the seed (:37, :42) | CARRIED |
| C1b | must_prove | refresh updates the `channels` row when the detail call answered | :242 (via :251) | a channel row left at db_slug / DB Chan / 5, or a skipped channel UPDATE | CARRIED |
| C1c | must_prove | refresh updates the `instances` row when the detail call answered | :244 (via :251) | an instance row still reading 'boom', 123, 'crawler' | CARRIED |
| C1d | must_prove | "only when": no `videos` write when the detail call did not answer | :285 | a write on None / {} / list / URLError; bumping last_checked_at or popularity breaks the before==after equality | CARRIED |
| C1e | must_prove | "only when": no `channels` write when the detail call did not answer | :285 | a channel UPDATE that runs on a failed detail call | CARRIED |
| C1f | must_prove | "only when": no `instances` write when the detail call did not answer | :285 | clearing last_error on a failed call | CARRIED |
| C2 | must_prove | a refresh blocked on a slow instance does not delay the similars answer | :298, preconditions :291, :292 | taking the instance call inside `db_lock`, so the similars GET waits out the 5 s refresh | CARRIED |
| D1 | docstring | "writes the videos, channels and instances rows only when the ... detail call answered" | :241–:244, :285 | same as C1a–C1f | CARRIED |
| D2 | docstring | "a refresh blocked on the instance does not hold up the id-based similars GET" | :298 | same as C2 | CARRIED |
| D3 | docstring | video row holds title, description, channel display name, counts, tags, category, nsfw | :241 | any of the nine LIVE_VIDEO columns left at its seeded value or written wrong | CARRIED |
| D4 | docstring | `last_checked_at` inside the run's wall-clock window | :237 | last_checked_at left at 1, or stamped with a stale or constant value | CARRIED |
| D5 | docstring | nonzero `popularity` | :238 | popularity left as seeded, or not recomputed | CARRIED |
| D6 | docstring | channel row holds slug, display name and the channel call's follower count | :242 | followers taken from the detail (70) and not from the channel call (77); slug left at db_slug | CARRIED |
| D7 | docstring | instance `last_error`, `last_error_at`, `last_error_source` are NULL | :244 | any of the three left uncleared | CARRIED |
| D8 | docstring | every other column and the other video's row unchanged | :241, :242, :244 | an UPDATE that also touches account columns or v2 (full-dict equality) | CARRIED |
| D9 | docstring | channel call answering nothing: rows still written, display name and followers keep DB values | :259 (via :237–:244) | treating a failed channel call as a failed refresh (:237 fails); nulling display_name or followers_count | CARRIED |
| D10 | docstring | timeout 0.2 s and 0.5 s calls: deadline passed before the write, same rows written | :270, precondition :268 | a persist interrupted by the request's expired deadline, which leaves rows as seeded | CARRIED |
| D11 | docstring | the extra AFTER UPDATE trigger "runs well past the progress handler's 10,000-instruction check" | :264, :265 | a heavy fixture whose UPDATE never reaches the progress handler (:264 would return False); a plain schema that already reaches it, which would make the trigger pointless (:265) | CARRIED |
| D12 | docstring | detail None / {} / list / URLError: refresh answers 200 with the DB-only values | :283 | a dropped connection on the list case; a 500; live values or blanks in the answer | CARRIED |
| D13 | docstring | every column incl. `last_checked_at` and `last_error` the same before and after | :285 | any write on the failed-detail path | CARRIED |
| D14 | docstring | similars GET, sent while the refresh is inside the call, answers 200 with its ANN neighbour | :294, :296, precondition :291 | an error answer; an empty answer; returning the seed itself | CARRIED |
| D15 | docstring | "in under 1 s" | :298 | the similars GET waiting behind the 5 s instance call | CARRIED |
| D16 | docstring | stub called only for the refresh's `/api/v1/videos/{uuid}` by then | :300, :301 | the similars route making instance calls of its own | CARRIED |
| D17 | docstring | each case runs a real SimilarServer / SimilarHandler over a temp whitelist-shaped DB | :228 | a child that failed to build the server or run the requests | CARRIED |
| N1 | name | `test_a_refresh_the_instance_answered_writes_the_video_channel_and_instance_rows` | :241, :242, :244 | as C1a–C1c | CARRIED |
| N2 | name | `test_a_refresh_whose_channel_call_failed_still_writes_with_the_db_channel_fields` | :259 | as D9 | CARRIED |
| N3 | name | `test_a_refresh_writes_after_the_requests_own_statement_deadline_has_passed` | :270, :268 | as D10 | CARRIED |
| N4 | name | `test_a_refresh_the_instance_did_not_answer_writes_nothing` | :285 | as C1d–C1f | CARRIED |
| N5 | name | `test_similars_answer_while_a_refresh_is_blocked_on_the_instance` | :294, :296, :298 with :291, :292 | as C2 / D14 | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase2.py:264
   assert _interrupted(data_db, sync_job, tmp_path / "heavy.db", True) is True
   The first audit left D11 UNCARRIED. It is now carried because an assertion was added, not because the docstring was narrowed. :264 checks that the heavy fixture's UPDATE is interrupted once the deadline has expired. :265 checks that the plain schema's UPDATE is not. The control runs on its own file (heavy.db), not on the case's case.db. Both are seeded by the same `_seed(..., heavy=True)`, so the fixture it checks is the one :266 runs on.
2. The ledger's line citations no longer match the file, because lines were added above them. Every row above cites its assertion's current line. The ledger's :215/:216/:218 are now :241/:242/:244, :256 is now :285, and :269 is now :298.

NOT ASSESSED
1. `code_under_test` lists tests/active/test_video_metadata.py (EDITED). I did not read it: the test under audit does not import or call it, and it has no bearing on how the clauses map to assertions.
2. I read `conftest.ENGINE_PY` / `ROOT` (imported at :25 from tests/active/conftest.py) only as names. They affect where the child process runs, not which clauses the test carries.

## 2026-09-27 - Step 7 - Phase 2 (Refresh persists only on instance success) - checkpoint outcome (run 1)

`tests/tmp/test_11_fast_similars_response_phase2.py` exited 0 after the phase landed.

<changes>
### `engine/server/api/handlers/video.py`
- `fetch_instance_video_dynamic` now returns `{}` when the video detail call didn't answer. That covers `None` (which includes `URLError`/`HTTPError`/timeout, since `fetch_instance_json` already catches those), an empty object, and any non-dict JSON. Before, a JSON list crashed on `detail.get` and dropped the connection, and `None` or `{}` produced a dict of `None`s. That dict counts as true, so `handle_video_refresh_request`'s existing `if dynamic and ...` guard went ahead and wrote anyway. Now that guard really does limit the write to refreshes the instance answered (C1). A failed refresh still answers 200 with the DB-only values, through `merge_video_metadata(row, {}, ...)`.
- `persist_video_metadata` now runs its write under its own `statement_deadline(server.statement_timeout_seconds)`, falling back to `DEFAULT_STATEMENT_TIMEOUT_SECONDS`. The deadline is entered just before `db_lock`. The request's deadline from `do_GET` has usually been used up waiting on the instance, so an UPDATE long enough to reach the progress handler used to get interrupted and logged, and nothing was saved. `statement_deadline` puts the request's own deadline back on exit. New imports: `statement_deadline` from `data.db` and `DEFAULT_STATEMENT_TIMEOUT_SECONDS` from `server_config`. `similar.py` already uses both from the same places.
- C2 needed no code change. The instance calls already ran outside `db_lock`: `resolve_video_row` takes the lock only for the row read, and `persist_video_metadata` takes it only for the write. I didn't observe this with a run; the checkpoint run will confirm it.
- I updated the module docstring's persist line to say the write happens only when the detail call answered.

### `tests/active/test_video_metadata.py`
I didn't touch it. It doesn't exist in the worktree yet. I take this to be where the checkpoint (`tests/tmp/test_11_fast_similars_response_phase2.py`) will be moved; it isn't a file for me to write.
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
  tests/tmp/test_11_fast_similars_response_phase2.py  8 passed                               0.0s
  --------------------------------------------------
  total                                               8 passed                              11.5s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - must_prove

Quoted from the phase Intent, written at Step 6 before the checkpoint was drafted.

Intent:
`client/backend/server.py` proxies `/api/video/refresh` as a read route with its own `{id, host}` allow-list, and `_proxy_engine_request` gives it a 20 s timeout and zero retries through the per-path mappings while every other route keeps 10 s and one retry.

- C1 - The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400.
- C2 - A refresh that times out at the proxy is sent to the Engine once and answered 502.

must_prove:
- C1 - The Client forwards `/api/video/refresh` with only `id` and `host`, and refuses any other or repeated query key with 400.
- C2 - A refresh that times out at the proxy is sent to the Engine once and answered 502.

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - self-check (audit round 1, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:67 — GET /api/video/refresh?id=uuid-1&host=tube.example with `&user_id=u-1` added, with `&refresh_cache=1` added, and with `id` repeated (`id=uuid-2&…`) answers [400, 400, 400] - expected: [400, 400, 400] once the refresh has its own {id, host} allow-list. The run on the current code read [404, 404, 404] because the route is not proxied. - excludes: Route not added: [404, 404, 404], seen in this run. Refresh added to PROXY_READ_GET_ROUTES but falling back to /api/video's allow-list (or no entry of its own that is wider than {id, host}): user_id and refresh_cache pass. That reads [200, 200, 400]; on /api/video both were observed at 200 and repeated id at 400.
- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:68 — GET /api/video/refresh?id=uuid-1&host=tube.example answers (200, {"videoUuid": "uuid-1", "title": "Refreshed"}), the stub Engine's body passed through - expected: (200, ANSWER). The same stub behind /api/video was observed to answer exactly (200, {'videoUuid': 'uuid-1', 'title': 'Refreshed'}) through the proxy. - excludes: Route not added: 404. An allow-list entry that is empty or too narrow (for example {} or {"id"}) refuses the valid query with 400.
- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:70 — the stub Engine received exactly [("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})] - expected: A single entry: the allowed refresh on path /api/video/refresh with exactly id and host. The three refused requests were sent before it and never reached the Engine. - excludes: A refresh proxied upstream to /api/video, or with its query rewritten, records a different path or query. A refused request forwarded anyway, or rejected only after it was proxied, records an entry ahead of the allowed one. A refresh forwarding user_id or refresh_cache records those extra keys, which /api/video was observed to forward. Route not added: [].
- C2 - tests/tmp/test_11_fast_similars_response_phase3.py:84 — with ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS["/api/video/refresh"] patched to 0.3 and a stub Engine that sleeps 1.5 s before answering, GET /api/video/refresh answers 502 - expected: 502. The run on the current code read 404 (route not proxied). - excludes: Refresh uses the shared 10 s timeout (the per-route mapping is ignored, or keyed on `upstream`, which carries the query string): the 1.5 s answer arrives and the status reads 200. This was observed for /api/video against the same 1.5 s stub at the default timeout: 200 after 1.5 s. Route not added: 404, seen in this run.
- C2 - tests/tmp/test_11_fast_similars_response_phase3.py:85 — during that timed-out refresh the stub Engine received exactly one request, [("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})]; the guard at :87 (the same stub still gets /api/video twice, 502) ties the single send to the refresh's own retry count - expected: One refresh GET. Guard: (502, two /api/video entries), observed on the current code in the run's log line "path":"/api/video","status":502,"attempts":2 and in the earlier probe. - excludes: Refresh keeps the shared ENGINE_PROXY_RETRY_COUNT = 1: the list reads two identical refresh entries. A timeout-retried send counted per path through `upstream` has the same effect. Setting ENGINE_PROXY_RETRY_COUNT to 0 for every route passes :85 but fails the guard at :87 with one /api/video entry.

<assertions>
tests/tmp/test_11_fast_similars_response_phase3.py:67 — GET /api/video/refresh with `user_id` added, with `refresh_cache` added, and with `id` repeated each answers 400 (C1)
tests/tmp/test_11_fast_similars_response_phase3.py:68 — GET /api/video/refresh?id=uuid-1&host=tube.example answers 200 with the stub Engine's body passed through (C1)
tests/tmp/test_11_fast_similars_response_phase3.py:70 — the stub Engine recorded exactly one request, `/api/video/refresh` with query exactly {id: [uuid-1], host: [tube.example]}. The three refused requests went out first and reached it not at all (C1)
tests/tmp/test_11_fast_similars_response_phase3.py:83 — with `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS["/api/video/refresh"]` monkeypatched to 0.3 s and a stub that sleeps 1.5 s, the refresh answers 502. Under the shared 10 s timeout it would answer 200 (C2)
tests/tmp/test_11_fast_similars_response_phase3.py:84 — the stub received that refresh exactly once, so it was not retried (C2)
tests/tmp/test_11_fast_similars_response_phase3.py:86 — guard: `/api/video` against the same sleeping stub, with `ENGINE_PROXY_TIMEOUT_SECONDS` patched to 0.3, answers 502 after exactly two attempts. This shows the single refresh comes from the refresh route's own retry setting, not from retries being dropped for every route (guard for C2)
</assertions>

<probes>
tests/tmp/probe_11_phase3.py, run via ValidateTests ["tests/tmp/probe_11_phase3.py", "-s"] against the pre-phase code, using test_server's _serving/_client_backend/_status and a stub recording (path, parse_qs(query)). It printed:
- `has route timeout: False`: `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` does not exist yet.
- `/api/video/refresh` with `id&host`, with `+user_id`, with `+refresh_cache=1`, and with `id` repeated all answered 404.
- `/api/video?id&host&user_id=x` answered 200 and the stub received `[('/api/video', {'id': ['u1'], 'host': ['h.example'], 'user_id': ['x']})]`. So a refresh sent through the /api/video allow-list would forward `user_id`.
- With `ENGINE_PROXY_TIMEOUT_SECONDS` = 0.3 and the stub sleeping 1.5 s, `/api/video` answered 502 after 0.85 s and the stub received 2 identical `/api/video` requests.
- The stub's late write raised `BrokenPipeError(32)`, which is why the test stub catches BrokenPipeError/ConnectionResetError.
Then the real test was run once via ValidateTests ["tests/tmp/test_11_fast_similars_response_phase3.py"]. Both tests fail for the intended reasons: `assert [404, 404, 404] == [400, 400, 400]`, and `AttributeError: module 'server' has no attribute 'ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS'`. The probe file tests/tmp/probe_11_phase3.py is still there because I have no delete tool; it should be removed.
</probes>

<unassertable>
Nothing from C1 or C2 was left out. Two premises could not be observed because the code does not exist yet:
- The test assumes `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` will be a dict keyed by path (the Step 6 wording "per-path mappings"), and patches it with `monkeypatch.setitem`.
- The guard assumes routes other than the refresh read the module-level `ENGINE_PROXY_TIMEOUT_SECONDS` when the request is made, as the agreed guard requires.
Running the phase's implementation will confirm both. As agreed at Step 6, the actual values of 20 s timeout, zero retries for the refresh, and 10 s with one retry for other routes are not asserted.
</unassertable>

### `tests/tmp/test_11_fast_similars_response_phase3.py` - 4819 characters, inlined in full

```
"""The Client backend proxies GET `/api/video/refresh` to the Engine with only `id` and `host`, and sends a refresh that times out at the proxy to the Engine once.

- `?id=…&host=…` reaches the Engine as `/api/video/refresh` with exactly those two params, and the browser gets the Engine's 200 body. The same query plus `user_id`, plus `refresh_cache`, or with `id` repeated each answers 400 and reaches the Engine not at all.
- With the refresh's entry in `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` at 0.3 s and an Engine that sleeps 1.5 s before answering, the refresh answers 502 and the Engine saw it once. `/api/video` against that Engine, with `ENGINE_PROXY_TIMEOUT_SECONDS` at 0.3 s, answers 502 after two attempts.

Each runs a real Client backend (test_server's `_client_backend`) in front of a stub Engine that records each GET's path and query.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# The active suite's conftest and harness, importable whether this file runs from tests/tmp or tests/active.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "active"))
from conftest import RateLimiter, client_server  # noqa: E402
from test_server import _client_backend, _serving, _status  # noqa: E402

REFRESH_ROUTE = "/api/video/refresh"
QUERY = "id=uuid-1&host=tube.example"
FORWARDED = {"id": ["uuid-1"], "host": ["tube.example"]}
ANSWER = {"videoUuid": "uuid-1", "title": "Refreshed"}


def _engine_stub(received, delay):
    class EngineStub(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            received.append((url.path, parse_qs(url.query)))
            time.sleep(delay)
            body = json.dumps(ANSWER).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The proxy gave up on a slow answer and closed the socket, which is the case under test.
                pass

        def log_message(self, format, *args):
            pass

    return EngineStub


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400(tmp_path):
    received = []
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 0))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # The /api/video allow-list takes user_id and refresh_cache (observed 200, user_id forwarded); unrouted, all three answer 404 (observed).
        refused = [_status(base, "GET", f"{REFRESH_ROUTE}?{query}", {}) for query in (f"{QUERY}&user_id=u-1", f"{QUERY}&refresh_cache=1", f"id=uuid-2&{QUERY}")]
        answered = _get(base, f"{REFRESH_ROUTE}?{QUERY}")
    assert refused == [400, 400, 400]  # C1
    assert answered == (200, ANSWER)  # C1
    # Sent before the allowed refresh, a refused one reaching the Engine would stand first here.
    assert received == [(REFRESH_ROUTE, FORWARDED)]  # C1


def test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502(tmp_path, monkeypatch):
    received = []
    monkeypatch.setitem(client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS, REFRESH_ROUTE, 0.3)
    with _serving(ThreadingHTTPServer(("127.0.0.1", 0), _engine_stub(received, 1.5))) as engine_base, _client_backend(tmp_path, engine_base, RateLimiter(1000, 60)) as base:
        # Under the shared 10 s timeout the 1.5 s answer arrives and this is 200; under the shared retry it is sent twice.
        refresh_status = _status(base, "GET", f"{REFRESH_ROUTE}?{QUERY}", {})
        refresh_sent = list(received)
        received.clear()
        monkeypatch.setattr(client_server, "ENGINE_PROXY_TIMEOUT_SECONDS", 0.3)
        video_status = _status(base, "GET", f"/api/video?{QUERY}", {})
    assert refresh_status == 502  # C2
    assert refresh_sent == [(REFRESH_ROUTE, FORWARDED)]  # C2
    # guard: the same sleeping Engine still gets /api/video twice, so the single refresh is the refresh's own retry count and not retries dropped for every route (observed 502 after two on the pre-phase code).
    assert (video_status, received) == (502, [("/api/video", FORWARDED)] * 2)

```


Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - red (audit round 1)

`tests/tmp/test_11_fast_similars_response_phase3.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase3.py  2 failed                               0.0s
  --------------------------------------------------
  total                                               2 failed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - audit (round 1)

- AUDIT: devsecops-test-shape-auditor - PASS
- AUDIT: devsecops-test-claim-auditor - BLOCK
- OUTSTANDING: 1 UNCARRIED clause(s) - C1e; devsecops-test-claim-auditor: critical

### devsecops-test-shape-auditor

```
SHAPE AUDIT — VERDICT: PASS

CRITICAL
none

RECOMMENDATIONS
none

PREDICTED FAILURE
test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400
fails at tests/tmp/test_11_fast_similars_response_phase3.py:67 on `assert refused == [400, 400, 400]`,
because client/backend/server.py has no route for `/api/video/refresh` (it is absent from
PROXY_READ_GET_ROUTES and PROXY_ALLOWED_QUERY_PARAMS, server.py:81-101), so each query answers
404. test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84 on
`assert refresh_status == 502`, because the refresh answers 404 for the same reason.

NOT ASSESSED
1. `fixtures_path` was not supplied. The imported harness was read in place:
   tests/active/conftest.py:41-42 (`client_server`, `RateLimiter`) and tests/active/test_server.py:347-378
   (`_serving`, `_client_backend`, `_status`). Nothing further was needed.
2. The 404 in the predicted failure is taken from the test's own comment at line 64 ("unrouted,
   all three answer 404 (observed)") and from the route tables at server.py:81-101. The handler's
   unrouted-GET branch was not read line by line.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: BLOCK

CLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "forwards `/api/video/refresh`" to the Engine | :70 | the request is forwarded to `/api/video` or another path, or never reaches the Engine | CARRIED |
| C1b | must_prove | "with only `id` and `host`" | :70 | the proxy adds a param (such as `user_id`), drops one, or changes a value. Exact dict equality with FORWARDED | CARRIED |
| C1c | must_prove | "refuses any other … query key with 400" | :67 | the route reuses the `/api/video` allow-list (user_id, refresh_cache), or stays unrouted and answers 404 | CARRIED |
| C1d | must_prove | "refuses any … repeated query key with 400": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` | CARRIED |
| C1e | must_prove | "refuses any … repeated query key with 400": `host` repeated | none | nothing. No refused query repeats `host` | UNCARRIED |
| C2a | must_prove | a timed-out refresh "is sent to the Engine once" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |
| C2b | must_prove | a timed-out refresh is "answered 502" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |
| D1 | docstring | "proxies GET `/api/video/refresh` to the Engine with only `id` and `host`" | :70 | a wrong upstream path or an extra or missing param | CARRIED |
| D2 | docstring | "sends a refresh that times out at the proxy to the Engine once" | :85 | a retry on timeout | CARRIED |
| D3 | docstring | "`?id=…&host=…` reaches the Engine as `/api/video/refresh` with exactly those two params" | :70 | a wrong path, or params added or dropped | CARRIED |
| D4 | docstring | "the browser gets the Engine's 200 body" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |
| D5 | docstring | "plus `user_id`, plus `refresh_cache`, or with `id` repeated each answers 400" | :67 | any of the three being accepted, or answering 404 | CARRIED |
| D6 | docstring | "and reaches the Engine not at all" | :70 | forwarding a refused request. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |
| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, "the refresh answers 502" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |
| D8 | docstring | "and the Engine saw it once" | :85 | a retry. The retry would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |
| D9 | docstring | "`/api/video` … answers 502 after two attempts" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |
| D10 | docstring | "a real Client backend … in front of a stub Engine that records each GET's path and query" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |
| N1 | name | "a refresh reaches the engine with only id and host" | :70 | a wrong path, or extra or missing params | CARRIED |
| N2 | name | "any other … key answers 400" | :67 | the `/api/video` allow-list being reused | CARRIED |
| N3 | name | "or repeated key answers 400" | :67 | only a repeated `id` is excluded, and a repeated `host` is not (see C1e) | CARRIED |
| N4 | name | "a refresh that times out at the proxy" | :84 | the 10 s default letting the answer through as 200 | CARRIED |
| N5 | name | "is sent once" | :85 | a retry on timeout | CARRIED |
| N6 | name | "and answered 502" | :84 | any status other than 502 | CARRIED |

CRITICAL
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase3.py:65
   `refused = [_status(base, "GET", f"{REFRESH_ROUTE}?{query}", {}) for query in (f"{QUERY}&user_id=u-1", f"{QUERY}&refresh_cache=1", f"id=uuid-2&{QUERY}")]`
   C1 says the Client refuses "any … repeated query key" with 400, and only two keys are allowed: `id` and `host`. The principle says "a claim naming a set of fields asserts every member of the set". The test repeats only `id` (`id=uuid-2&{QUERY}`) and checks it at :67 (`assert refused == [400, 400, 400]`). Nothing sends a repeated `host`. So a refresh handler that checks `id` for multiple values but reads `host` as `params["host"][0]` or `params["host"][-1]` would pass this test while breaking C1. Row C1e is UNCARRIED.

RECOMMENDATIONS
1. bounds (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase3.py:65
   "Any other key" is tested only with `user_id` and `refresh_cache`. Both are keys the `/api/video` allow-list accepts, which rules out copying that list. No key outside every allow-list is tested, such as `foo=1`. The edges of the accepted input are also untested: `id` or `host` missing, empty (`id=&host=…`), or whitespace-only. The generic GET handler (client/backend/server.py:430-432) quietly drops empty values after stripping, so what the refresh route forwards in that case has no test.

OBSERVATIONS
none

NOT ASSESSED
1. `fixtures_path` was not supplied. The test defines no pytest fixtures besides `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from tests/active/conftest.py, which I checked only at their definitions (conftest.py:41-42). It imports `_client_backend`, `_serving` and `_status` from tests/active/test_server.py:347-378, and I read those in full.
2. client/backend/server.py as read has no `/api/video/refresh` route, no entry for it in `PROXY_ALLOWED_QUERY_PARAMS`, and no `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`. So I could not read the refresh route's accepted inputs or failure mode from code. Bounds and the abnormal path were judged against `must_prove` and the existing generic proxy handler (server.py:417-436, 570-745).

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - self-check (audit round 2, send-back 0)

`tests/tmp/test_11_fast_similars_response_phase3.py`, surface `checkpoint`. Collection exit 0.

- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:67 — GET /api/video/refresh with `user_id` added, `refresh_cache` added, `foo` added, `id` repeated, and `host` repeated each answers 400 - expected: [400, 400, 400, 400, 400] - excludes: A route that reuses the `/api/video` allow-list reads 200 on the first two. A route that checks only `id` for repeats and takes the first or last `host` reads 200 on the fifth. A route left unrouted reads [404, 404, 404, 404, 404], which I observed on the pre-phase code.
- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:68 — GET /api/video/refresh?id=uuid-1&host=tube.example answers 200 with the stub Engine's body unchanged - expected: (200, {"videoUuid": "uuid-1", "title": "Refreshed"}) - excludes: A route that refuses everything, or that passes through only the status and rewrites or filters the body, gives a 400/404 or a different body.
- C1 - tests/tmp/test_11_fast_similars_response_phase3.py:70 — the stub recorded exactly one request: `/api/video/refresh` with query exactly {id: [uuid-1], host: [tube.example]}. The five refused requests were sent first - expected: [("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})] - excludes: A route that forwards to `/api/video` gets the wrong path. One that adds `user_id` or drops `host` gets the wrong dict. One that forwards a refused request (for example the one with `host` repeated) puts an extra entry at the front.
- C2 - tests/tmp/test_11_fast_similars_response_phase3.py:84 — with the refresh's route timeout patched to 0.3 s and a 1.5 s Engine, the refresh answers 502 - expected: 502 - excludes: A route that ignores the per-route timeout and uses the shared 10 s default lets the 1.5 s answer through as 200. An unrouted refresh reads 404 (observed).
- C2 - tests/tmp/test_11_fast_similars_response_phase3.py:85 — the Engine received that timed-out refresh exactly once - expected: [("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})] - excludes: A refresh that gets the shared ENGINE_PROXY_RETRY_COUNT=1 is sent twice, so the snapshot holds two entries. The :87 guard (/api/video still 502 after two attempts) shows that the single send is not retries being dropped for every route.

<exemptions>
none
</exemptions>

<items>
<item id="C1e">
<disposition>fixed</disposition>
<what>Line 65's refused list now also sends `id=uuid-1&host=tube.example&host=other.example`, a repeated `host`. Line 67 now reads `assert refused == [400, 400, 400, 400, 400]`, so it carries the clause. It excludes a handler that checks `id` for multiple values but reads `host` as `params["host"][0]` or `[-1]`. That handler would answer 200 on the fifth query and forward it, and :70 would also go red because a second entry would appear. The docstring now names the repeated `host` too.</what>
</item>
</items>

<findings_addressed>
Claim CRITICAL 1 (whole-claim, repeated `host` not tested): a query with `host` repeated is added to the refused list at :65. :67 now requires 400 for it, and :70 requires that it never reaches the Engine. The docstring was updated to match. After the edit I ran ValidateTests on the pre-phase code: `[404, 404, 404, 404, 404] == [400, 400, 400, 400, 400]` at :67, and `404 == 502` at :84. Both fail because the route is not built yet.
Claim RECOMMENDATION 1 (bounds), partly taken: `foo=1` is added at :65, a key that is in no allow-list, so "any other key" is no longer tested only with keys borrowed from `/api/video`. I did not add cases for a missing, empty or whitespace `id`/`host`. `must_prove` does not say what the refresh route should do with those, so any expected value would be invented.
Shape audit: PASS with no findings. The new expectations are the literal 400 from C1. None is derived from a production allow-list table, so the assertion does not mirror production.
</findings_addressed>

<rows>
<row clause="C1">
<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:67 — GET /api/video/refresh with `user_id` added, `refresh_cache` added, `foo` added, `id` repeated, and `host` repeated each answers 400</assertion>
<expected>[400, 400, 400, 400, 400]</expected>
<wrong_implementation>A route that reuses the `/api/video` allow-list reads 200 on the first two. A route that checks only `id` for repeats and takes the first or last `host` reads 200 on the fifth. A route left unrouted reads [404, 404, 404, 404, 404], which I observed on the pre-phase code.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:68 — GET /api/video/refresh?id=uuid-1&host=tube.example answers 200 with the stub Engine's body unchanged</assertion>
<expected>(200, {"videoUuid": "uuid-1", "title": "Refreshed"})</expected>
<wrong_implementation>A route that refuses everything, or that passes through only the status and rewrites or filters the body, gives a 400/404 or a different body.</wrong_implementation>
</row>
<row clause="C1">
<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:70 — the stub recorded exactly one request: `/api/video/refresh` with query exactly {id: [uuid-1], host: [tube.example]}. The five refused requests were sent first</assertion>
<expected>[("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})]</expected>
<wrong_implementation>A route that forwards to `/api/video` gets the wrong path. One that adds `user_id` or drops `host` gets the wrong dict. One that forwards a refused request (for example the one with `host` repeated) puts an extra entry at the front.</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:84 — with the refresh's route timeout patched to 0.3 s and a 1.5 s Engine, the refresh answers 502</assertion>
<expected>502</expected>
<wrong_implementation>A route that ignores the per-route timeout and uses the shared 10 s default lets the 1.5 s answer through as 200. An unrouted refresh reads 404 (observed).</wrong_implementation>
</row>
<row clause="C2">
<assertion>tests/tmp/test_11_fast_similars_response_phase3.py:85 — the Engine received that timed-out refresh exactly once</assertion>
<expected>[("/api/video/refresh", {"id": ["uuid-1"], "host": ["tube.example"]})]</expected>
<wrong_implementation>A refresh that gets the shared ENGINE_PROXY_RETRY_COUNT=1 is sent twice, so the snapshot holds two entries. The :87 guard (/api/video still 502 after two attempts) shows that the single send is not retries being dropped for every route.</wrong_implementation>
</row>
</rows>

<answers>
1. No. The negative at :70 (refused requests never reach the Engine) has a positive control: :68 and :70 need the allowed refresh to arrive, and the refused ones are sent first on the same stub. The single send at :85 is armed by :84's 502 and by the :87 guard that sees two attempts on /api/video. With the code under test deleted, :67 reads 404s, which I observed.
2. No. Every expected value is a literal: status codes, the FORWARDED dict built from QUERY by hand, and the stub's own ANSWER. Deleting the refresh route (the missing PROXY_READ_GET_ROUTES/PROXY_ALLOWED_QUERY_PARAMS entries) turns :67 and :84 red. Deleting the repeat check on `host` turns :67 red at index 4.
3. No. Refusal is read on five distinct inputs: two keys borrowed from /api/video, one key in no allow-list, and each allowed key repeated. It is not pinned against a sibling.
4. No. The only double is the stub Engine, a separate HTTP service on the other side of the network seam. The Client backend is real.
5. Yes, it collects. The imports are unchanged, and the run collected and executed both tests (2 failed).
6. Yes. The pre-phase 404s for the new `foo` and repeated-`host` queries were observed in this round's ValidateTests run: `[404, 404, 404, 404, 404]`. The 400 under the right implementation comes from the C1 wording, not from any output shape. The earlier observations (allow-list forwarding user_id, 2 attempts on /api/video, BrokenPipe) came from the probe run on the previous round.
7. Yes. The post-edit run fails at :67 with `[404, 404, 404, 404, 404] == [400, 400, 400, 400, 400]` and at :84 with `404 == 502`. Both fail because the route is not built, not because of a collection or setup error. Line numbers did not shift, so the ledger's :67/:70/:84/:85/:87 still point at the same assertions. Nothing needed a rewrite. Note: the probe files tests/tmp/probe_11_phase3.py and probe_11_phase3_selfcheck.py are still there because I have no delete tool, and they should be removed.
</answers>

Gate: satisfied

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - red (audit round 2)

`tests/tmp/test_11_fast_similars_response_phase3.py` exited 1.

```
  tests/tmp/test_11_fast_similars_response_phase3.py  2 failed                               0.0s
  --------------------------------------------------
  total                                               2 failed                               2.3s wall, 1 lane

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - audit (round 2)

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
test_a_refresh_reaches_the_engine_with_only_id_and_host_and_any_other_or_repeated_key_answers_400
fails at line 67 on `assert refused == [400, 400, 400, 400, 400]`, which reads
[404, 404, 404, 404, 404]. client/backend/server.py has no `/api/video/refresh` entry in
`PROXY_ALLOWED_QUERY_PARAMS` (lines 85-101) or in `PROXY_READ_GET_ROUTES` (lines 81-83),
so the route is unrouted.
test_a_refresh_that_times_out_at_the_proxy_is_sent_once_and_answered_502 fails at line 84
on `assert refresh_status == 502`, which reads 404 for the same reason.

NOT ASSESSED
1. `fixtures_path` was not supplied. The test uses no pytest fixture beyond the built-in
   `tmp_path` and `monkeypatch`. It imports `RateLimiter` and `client_server` from
   tests/active/conftest.py (lines 41-42), and `_client_backend`, `_serving` and `_status`
   from tests/active/test_server.py (lines 347-378). All of these were read.
   `ensure_user_schema` was not read. It only sets up the users DB and has no bearing on the
   assertion form.
2. The GET dispatch in client/backend/server.py that turns an unrouted path into 404 was not
   read. The 404 in the predicted failure rests on two things: a Grep for "refresh" in
   server.py matches only line 88 (the `/api/video` allow-list), and the test's own comment
   at line 64 says 404 was observed.
```

### devsecops-test-claim-auditor

CLAIM AUDIT — VERDICT: PASS

CLAUSE MAP  (23 clauses: 7 must_prove, 10 docstring, 6 name)
| id | source | clause | assertion | excludes | status |
|---|---|---|---|---|---|
| C1a | must_prove | "forwards `/api/video/refresh`" to the Engine | :70 | the request going to `/api/video` or another path, or never reaching the Engine | CARRIED |
| C1b | must_prove | "with only `id` and `host`" | :70 | the proxy adding a param (such as `user_id`), dropping one, or changing a value. Exact dict equality with FORWARDED | CARRIED |
| C1c | must_prove | "refuses any other … query key with 400" | :67 | the route reusing the `/api/video` allow-list (user_id, refresh_cache), accepting an unlisted key (`foo`), or staying unrouted and answering 404 | CARRIED |
| C1d | must_prove | "refuses any … repeated query key with 400": `id` repeated | :67 | first-value-wins or last-value-wins handling of `id` (`id=uuid-2&{QUERY}`, :65) | CARRIED |
| C1e | must_prove | "refuses any … repeated query key with 400": `host` repeated | :67 | first-value-wins or last-value-wins handling of `host` (`{QUERY}&host=other.example`, :65, fifth element of the exact list) | CARRIED |
| C2a | must_prove | a timed-out refresh "is sent to the Engine once" | :85 | the shared retry (ENGINE_PROXY_RETRY_COUNT=1) applied to the refresh, which sends it twice | CARRIED |
| C2b | must_prove | a timed-out refresh is "answered 502" | :84 | the shared 10 s timeout letting the 1.5 s answer through as 200, or a 404 or 504 | CARRIED |
| D1 | docstring | "proxies GET `/api/video/refresh` to the Engine with only `id` and `host`" | :70 | a wrong upstream path, or a param added or missing | CARRIED |
| D2 | docstring | "sends a refresh that times out at the proxy to the Engine once" | :85 | a retry on timeout | CARRIED |
| D3 | docstring | "`?id=…&host=…` reaches the Engine as `/api/video/refresh` with exactly those two params" | :70 | a wrong path, or params added or dropped | CARRIED |
| D4 | docstring | "the browser gets the Engine's 200 body" | :68 | status-only passthrough, or a rewritten or filtered body | CARRIED |
| D5 | docstring | "plus `user_id`, plus `refresh_cache`, plus `foo`, with `id` repeated, or with `host` repeated each answers 400" | :67 | any of the five being accepted, or answering 404. Each one is a position in the exact list | CARRIED |
| D6 | docstring | "and reaches the Engine not at all" | :70 | a refused request being forwarded. The refused ones are sent first, so a forwarded one would add an entry to the exact list | CARRIED |
| D7 | docstring | with the route timeout at 0.3 s and a 1.5 s Engine, "the refresh answers 502" | :84 | the per-route timeout being ignored, so 200 comes back under the 10 s default | CARRIED |
| D8 | docstring | "and the Engine saw it once" | :85 | a retry. It would land before the 502 is written, so the snapshot at :80 would hold two entries | CARRIED |
| D9 | docstring | "`/api/video` … answers 502 after two attempts" | :87 | retries dropped for every route rather than only for the refresh | CARRIED |
| D10 | docstring | "a real Client backend … in front of a stub Engine that records each GET's path and query" | :70, :85 | a stub that did not record the query would fail both exact comparisons. This sentence describes the harness | CARRIED |
| N1 | name | "a refresh reaches the engine with only id and host" | :70 | a wrong path, or extra or missing params | CARRIED |
| N2 | name | "any other … key answers 400" | :67 | the `/api/video` allow-list being reused, or an unlisted key being accepted | CARRIED |
| N3 | name | "or repeated key answers 400" | :67 | a repeated `id` or a repeated `host` being accepted under first-value-wins or last-value-wins | CARRIED |
| N4 | name | "a refresh that times out at the proxy" | :84 | the 10 s default letting the answer through as 200 | CARRIED |
| N5 | name | "is sent once" | :85 | a retry on timeout | CARRIED |
| N6 | name | "and answered 502" | :84 | any status other than 502 | CARRIED |

CRITICAL
none

RECOMMENDATIONS
none

OBSERVATIONS
1. whole-claim (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase3.py:3, :65
   The C1e fix added an assertion. It did not narrow the prose. `{QUERY}&host=other.example` is now the fifth refused query at :65, and the exact-list equality at :67 carries it. The docstring also got wider: it now names `plus foo` and `with host repeated`. Both are in the D5 row and both are carried at :67.
2. bounds (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase3.py:65
   No ledger row covers this. Every accepted query has both `id` and `host` present with non-empty values. Nothing tests a query missing `id`, a query missing `host`, an empty value (`id=`), or an empty query string. `must_prove` says "only `id` and `host`" but not "requires", so this falls outside C1. Left for the reader to decide.
3. surfaces / checkpoint_definition (rules/testing.md) — tests/tmp/test_11_fast_similars_response_phase3.py:76
   The test patches `client_server.ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` with `raising=False`. That name does not exist in client/backend/server.py yet: the only timeout global is `ENGINE_PROXY_TIMEOUT_SECONDS` at server.py:77, and `/api/video/refresh` is not in `PROXY_ALLOWED_QUERY_PARAMS` at server.py:85-99. The test therefore fixes the name the implementation has to read the per-route timeout from. If the implementation uses a different name, the patch does nothing, the 10 s default lets the 1.5 s answer through, and :84 fails. That is a false negative, not a false pass, so it does not weaken C2b.

NOT ASSESSED
1. The `client/backend/server.py` edits for this phase are not present yet (no refresh route and no per-route timeout mapping). I judged the bounds and abnormal paths against the code as it stands and against `must_prove`, not against the finished route.

## 2026-09-27 - Step 7 - Phase 3 (Client proxy for the refresh route) - checkpoint outcome (run 1)

`tests/tmp/test_11_fast_similars_response_phase3.py` exited 0 after the phase landed.

<changes>
### client/backend/server.py
- `/api/video/refresh` added to `PROXY_READ_GET_ROUTES`. It now goes through the same rate limit and the same `_handle_engine_read_proxy_get` sanitising as the other GET read proxies: an unknown key or a repeated key gets 400, and values are stripped.
- New `PROXY_ALLOWED_QUERY_PARAMS["/api/video/refresh"] = {"id", "host"}`. The `/api/video` entry is unchanged and keeps `refresh_cache` and `user_id`.
- Two new per-path mappings sit next to the shared constants, with a one-line comment saying why the refresh differs:
  - `ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS = {"/api/video/refresh": 20}`
  - `ENGINE_PROXY_ROUTE_RETRY_COUNT = {"/api/video/refresh": 0}`
- `_proxy_engine_request` looks up `timeout_seconds` and `retry_count` once per request from these mappings. The lookup is keyed on `path`, not `upstream`, which carries the query string. Any path not in a mapping falls back to `ENGINE_PROXY_TIMEOUT_SECONDS` / `ENGINE_PROXY_RETRY_COUNT`. Both are module globals read at call time, which lets a test patch them.
- All four sites that used the shared constants now read the locals: the retry loop's `range`, the `urlopen` timeout, the retry check `attempt < retry_count`, and the `"attempts"` field of the "proxy request unavailable" log.
- Result: the refresh gets 20 s and no retry, and a transport timeout on it is answered 502 `ENGINE_PROXY_UNAVAILABLE` after one send. Every other proxied route still gets 10 s and one retry.
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
  tests/tmp/test_11_fast_similars_response_phase3.py  2 passed                               0.0s
  --------------------------------------------------
  total                                               2 passed                               2.1s wall, 1 lane

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - clause accounting

- P1C1 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase1.py`
- P1C2 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase1.py`
- P2C1 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase2.py`
- P2C2 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase2.py`
- P3C1 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase3.py`
- P3C2 - carried - rests on: the last audit of `tests/tmp/test_11_fast_similars_response_phase3.py`

## 2026-09-27 - Step 8 - refactor pass

<refactors>
engine/server/api/handlers/video.py: added a module-level `pick_present(value, fallback)` helper, placed with `pick_text`/`pick_number`, which returns the fallback only when the value is None. `merge_video_metadata` now uses it in place of the seven hand-written `x = dynamic.get(k); if x is None: x = row.get(k)` blocks (views, likes, dislikes, channel_followers, tags_json, category, nsfw). Each field falls back the same way as before: `is None` for these seven, `or` for title, description, channel_display and channel_slug. The operator confirmed this refactor before I made it.
</refactors>

<left_out>
The dead `channel_detail = None` line in `fetch_instance_video_dynamic`. It was there before this build and no phase touched it, so I left it alone. I did not run the gating checkpoints after the helper refactor. The fallback cases in tests/tmp/test_11_fast_similars_response_phase1.py (case b) and phase 2 (the no-write merge) cover it, and the workflow's run will confirm it. client/backend/server.py, similar.py and handlers/__init__.py: I found nothing to refactor; the per-path timeout/retry lookups and the new dispatch branch are already as small as they can be. There are leftover probe files in tests/tmp (probe_11_video_metadata.py, probe_11_remediation.py, probe_11_phase2.py, probe_11_phase3.py, probe_11_phase3_selfcheck.py, probe_11_d11.py) that still need deleting. I have no delete tool, and they are outside this step's files. tests/active/test_video_metadata.py does not exist yet. It is where the phase 1 and 2 checkpoints get promoted, so it is not mine to write.
</left_out>

<needs_fresh_red>
none
</needs_fresh_red>

<observation>
The only refactor that paid its way was folding seven identical `is None` fallbacks in merge_video_metadata into one helper. The merge rules are unchanged: 0 and 0/1 values are kept, and title, description and channel names still use `or`. Everything else that landed was already minimal, and the step's rules placeholder was blank, so I measured the pass against the role's rules with operator consent.
</observation>

## 2026-09-27 - Step 8 - suite comparison (attempt 1)

`--compare` exited 1.

```
selected 11 of 23 test groups (12 unchanged):
  test_blocks.py — changed
  test_dislike_profile.py — changed
  test_dislikes.py — changed
  test_frontend_blocks.py — changed
  test_frontend_profile.py — changed
  test_frontend_reactions.py — changed
  test_frontend_videos.py — changed
  test_profiles.py — changed
  test_search_fusion.py — no map entry
  test_server.py — changed
  test_similar.py — changed
  test_blocks.py              7 passed                              31.7s
  test_dislike_profile.py     9 passed                              54.4s
  test_dislikes.py            10 passed                             20.3s
  test_frontend_blocks.py     2 passed                               9.7s
  test_frontend_profile.py    2 passed                               1.2s
  test_frontend_reactions.py  7 passed                              39.4s
  test_frontend_videos.py     1 passed                               9.8s
  test_profiles.py            11 passed                             29.7s
  test_search_fusion.py       10 passed                              2.4s
  test_server.py              68 passed                             40.5s
  test_similar.py             1 failed, 26 passed                   36.3s
  --------------------------
  total                       153 passed, 1 failed                  54.7s wall, 11 lanes

moved against the previous record:
        new red  tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux]

recorded: tests/last_test_validation.json (exit 1)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 8 - red triage (attempt 1)

<failures>
### tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux]

**What happened.** The second of two identical `POST /recommendations` home requests (`plain = _home(...)`, line 150) got `500 {"error": "Recommendations request failed"}`. The first request (`previous`), with the same five likes and a moment earlier, got 200. The `[cooking]` and `[music]` cases of the same test passed in the same run.

**The test is sound.** It asks for a home page twice and expects 200 each time. That is a fair expectation, it does not rely on anything this build changed, and it does not conflict with any clause of the build. Nothing needs retiring or fixing in it.

**The build did not cause it.** No phase touched the home path. Phase 1 added one import and one GET branch (`/api/video/refresh`) to `similar.py`. Phase 2 edited only `video.py`. Phase 3 edited only the Client backend. The home request runs `do_POST` → `_handle_similar` → `_handle_home` → the mixer, none of which changed. `test_similar.py` was re-selected only because `similar.py` changed.

**What I observed.** I used a throwaway probe, `tests/tmp/probe_11_home_500.py`, that starts the real Engine the way the `engine` fixture does, with its log somewhere the probe can read it:
- It does not happen on a single Engine. The failing sequence (likes, home, home, home with `exclude`) ran 20 rounds across linux, cooking and music: 60 home requests, all 200, and no ERROR record in the Engine log.
- A home request with five likes takes about 0.83 s (five calls, 0.81 to 0.88 s) against the 5 s budget that `do_POST` gives each request (`DEFAULT_STATEMENT_TIMEOUT_SECONDS`).
- When that budget runs out, the answer is this exact failure. With the budget patched to 0.001 s, both home requests got `500 {"error": "Recommendations request failed"}`. The log showed `server error` with the traceback `_handle_home → mixer → explore_range._fetch_pool → fetch_random_rows_from_cache → fetch_metadata → sqlite3.OperationalError: interrupted`. `_handle_similar`'s `except Exception` catches the interrupt before `do_POST`'s handler can turn it into `503 Query time limit exceeded`, so a timeout on this route looks like a generic 500.

**Most likely cause (inferred, not seen in the suite run).** The suite ran 11 lanes at once, each with its own faiss-backed Engine on the same machine and the same repo database files. Under that load, one home request probably took more than 5 s of wall-clock time — about six times its unloaded time — and its statement was interrupted. The other possibility is a `database is locked` error on the shared `similarity-cache.db`, which another lane's Engine also writes. That would reach the same `except Exception` and the same 500 body.

I could not read the suite run's Engine log: `/tmp/pytest-of-enduser/pytest-5194/engine0/engine.log` is outside this session's sandbox. That log would settle it. Look for a `"message":"server error"` record near the failed request, ending in `sqlite3.OperationalError: interrupted` (budget trip) or `database is locked` (cache contention).

**What I changed.** Nothing in the code or the tests. This is an intermittent failure caused by load, which existed before this build, not a regression.
</failures>

<checkpoint_gaps>
none
</checkpoint_gaps>

<correction>
- I read the failing test and its output. The test is sound: its failure is a 500 on a repeat of a request that had just succeeded.
- I checked what each phase touched. None of them touched the home path in `_handle_similar` / `_handle_home` / the mixer.
- I wrote and ran `tests/tmp/probe_11_home_500.py` (see "What I observed" above): 60 home requests on an isolated Engine never failed, a request takes about 0.83 s against a 5 s budget, and running out of the budget produces exactly this 500.
- I changed no implementation file, no active test and no checkpoint, and retired no test: none conflicts with a requirement of this build or passes without really testing anything.

**What I recommend:**
1. Have the workflow rerun `tests/active/test_similar.py` to confirm the red was intermittent.
2. Before or instead of that, check the suite run's Engine log (path above) for the traceback of the failed request.
3. Two problems that predate this build could go on the issue tracker; that is outside this step's files, so I have not filed them:
   - A statement interrupt inside `_handle_similar` answers a generic 500 instead of `do_POST`'s 503, because the broad `except Exception` catches it first.
   - A fixed 5 s wall-clock budget, shared across 11 parallel Engine lanes, makes the home tests sensitive to machine load.

**Housekeeping:**
- `tests/tmp/probe_11_home_500.py` needs deleting; I have no tool to delete files. The same goes for the earlier leftovers the Phase 1 report listed.
- Each probe run overwrote `tests/last_test_validation.json` and `tests/last_test_output.txt` with the probe's results. The `test_similar` red is still listed under "failed tests", but the full suite output is no longer in those files.
</correction>

## 2026-09-27 - Step 8 - suite comparison (attempt 2)

`--compare` exited 0.

```
selected 2 of 23 test groups (21 unchanged):
  test_search_fusion.py — no map entry
  test_similar.py — not green
  test_search_fusion.py  10 passed                              2.2s
  test_similar.py        27 passed                             17.8s
  ---------------------
  total                  37 passed                             18.0s wall, 2 lanes

moved against the previous record:
  no longer red  tests.active.test_similar::test_home_excluding_a_previous_page_returns_none_of_it_and_a_full_page[linux]

recorded: tests/last_test_validation.json (exit 0)
wrote tests/last_test_output.txt
```

## 2026-09-27 - Step 9 - document triage

- [ ] `engine/server/README.md` - Line 9 ("`/api/video` metadata for the video page.") is incomplete, and line 3 ("Read-only Engine API ...") was already false and still is. What landed differs from the checklist: `/api/video` is NOT DB-only. `handle_video_request` hands the request to `handle_video_refresh_request`, so both routes behave the same way, and the entry must not say `/api/video` makes no instance call or that `accountAvatarUrl` is empty. What the file needs:
- **`/api/video` bullet.** Keep it, and say that it fetches live metadata from the source instance (the video detail, then the channel, with an 8 s socket timeout on each) and merges it over the DB row field by field.
- **New `/api/video/refresh` bullet.** It gives the same answer in the same shape and is the route the Client proxies with its own budget.
- **Persist rule, for both routes.** The `videos`/`channels` UPDATE and the `instances.last_error*` reset run only when the instance's video detail call answered. They run under their own statement deadline. A detail call that failed or answered empty or non-object JSON writes nothing, and the response then falls back to the DB values.
- **Line 3.** Say the API is read-only apart from this per-request metadata write-back.
- [ ] `README.md` - Two rows of the boundary table list `/api/video` but not the new route: line 46 (Engine public read API) and line 48 (Client browser-facing read gateway). Add `/api/video/refresh` to both lists. The Engine dispatches it in `SimilarHandler._dispatch_get`, and the Client proxies it through `PROXY_READ_GET_ROUTES`. Line 134 (the smoke check expects the Client proxy `/api/video` to answer 200) is still true.
- [ ] `client/README.md` - Line 37 (the read gateway list) is missing `/api/video/refresh`, which `client/backend/server.py` now proxies. Add it. Also say how this proxy differs from the others: it accepts only `id` and `host`, and any other key or a repeated key answers 400. It waits up to 20 s and is sent once with no retry (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS` / `ENGINE_PROXY_ROUTE_RETRY_COUNT`), so a timeout answers 502 `ENGINE_PROXY_UNAVAILABLE`. Every other proxied read keeps 10 s and one retry.
- [ ] `docs/project/issues/10-video-metadata-completeness.md` - Add a comment and leave the body as it is. What the comment records:
- **The single write path now exists.** It is `persist_video_metadata` in `engine/server/api/handlers/video.py`, reached through `handle_video_refresh_request`, which both `/api/video` and `/api/video/refresh` currently run. It is the one place this issue extends with further fields (line 15's "one write path").
- **Line 17 is now real behaviour.** `fetch_instance_video_dynamic` returns `{}` when the detail call fails or answers empty or non-object JSON. The DB update and the `instances.last_error` reset then run only when the detail call answered. The write has its own statement deadline, so a slow instance no longer causes it to be interrupted silently.
- **The merge rules.** The field-by-field fallback lives in `merge_video_metadata`. Title, description and the channel names fall back when empty (`or`); counts, `tags_json`, `category` and `nsfw` fall back only when missing (`pick_present`, an `is None` test), so a supplied 0 is kept.
- **Line 22.** It holds for either route today. Once the follow-up plan makes `/api/video` DB-only, it will hold only for `/api/video/refresh`.
- [ ] `docs/project/roadmap.md` - Line 54 (F2-M3, API versioning) lists the unversioned routes that feature must version: `/api/channels`, `/api/video` and the similar routes. The build added a new unversioned public route, so the list is now incomplete. Add `/api/video/refresh`.
- [ ] `docs/project/issues/11-fast-similars-response.md` - Add a delivery comment, but do NOT carry out the checklist's harvest action. Leave `Status:` open and the file in `docs/project/issues/`. The build delivered only the first of two plans (Engine refresh route, persist on success, Client proxy). Still to do, in the follow-up plan: `/api/video` answering from the DB only (R1); the page coordinator, starting three requests with the refresh winning in either arrival order (R3); a first render that waits on no instance request (R4); URL-param rendering when the Engine has no row (R5); and the re-render guards (R6).

The page still renders nothing until `/api/video` returns from the instance, which is the problem the issue describes, so closing it would be false. The comment records:
- the operator's two-phase reading;
- the refresh route, `GET /api/video/refresh`;
- the 20 s, no-retry proxy budget for the refresh;
- that similars are not delayed by a slow refresh, with the instance calls kept outside `db_lock`;
- the accepted behaviour change: a failed instance fetch no longer writes, bumps `last_checked_at` or clears `instances.last_error*`. This already applies to `/api/video` today.

Out of scope:
- [ ] `client/frontend/README.md` - No frontend phase landed: `client/frontend/src/pages/video-page/index.ts` was not touched, and the page does not call `/api/video/refresh`. Line 8's list of routes the frontend fetches (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) is still exactly right, and the page loads in the same order as before. The checklist's addition and its load-order sentence belong to the follow-up plan that builds the page coordinator.
- [ ] `DEPLOYMENT.md` - Lines 374-375 ("`/api/video` makes live calls to source instances per request") are still true. `/api/video` was kept live in this build; only the follow-up plan makes it DB-only. The sentence's point, that outbound 443 is a runtime dependency, also still holds. The ufw comment at 369 ("live video metadata") is true. The nginx `location /api/` block already covers `/api/video/refresh`, and its default 60 s read timeout is longer than the 20 s proxy budget.
- [ ] `docs/project/issues/20-request-lifecycle-logs.md` - Line 25 names `/api/video` in the smoke list for start→end request logs. That route still exists and is still the long-running call bound to the instance, because it was kept live. This future-work spec says nothing that is now false. Adding `/api/video/refresh` would be a scope choice for whoever plans issue 20, not a correction.

ADR conflicts: none

## 2026-09-27 - Step 9 - Update documentation

- [x] `engine/server/README.md` - updated: `engine/server/README.md`: the `/api/video` entry is updated, a `/api/video/refresh` entry is added, the write-back rule is documented, and the "read-only" claim on line 3 is corrected.
- [x] `README.md` - updated: Added `/api/video/refresh` to two rows of the boundary table: the Engine public read API and the Client read gateway.
- [x] `client/README.md` - updated: Added `/api/video/refresh` to the Client read gateway list and described how its proxy differs from the other reads (allow-list, 20 s, no retry, 502 when it times out).
- [x] `docs/project/issues/10-video-metadata-completeness.md` - updated: Added a comment to issue 10 about the metadata write path, merge rules and persist-on-success behaviour that issue 11 delivered. Body and `Status:` are unchanged.
- [x] `docs/project/roadmap.md` - updated: Added `/api/video/refresh` to F2-M3's list of routes that still need versioning.
- [x] `docs/project/issues/11-fast-similars-response.md` - updated: Added a partial-delivery comment to issue 11. Status and location unchanged: the issue stays open in `docs/project/issues/`.
- [x] `client/frontend/README.md` - out of scope: No frontend phase landed: `client/frontend/src/pages/video-page/index.ts` was not touched, and the page does not call `/api/video/refresh`. Line 8's list of routes the frontend fetches (`/recommendations`, `/videos/similar`, `/api/video`, `/api/channels`) is still exactly right, and the page loads in the same order as before. The checklist's addition and its load-order sentence belong to the follow-up plan that builds the page coordinator.
- [x] `DEPLOYMENT.md` - out of scope: Lines 374-375 ("`/api/video` makes live calls to source instances per request") are still true. `/api/video` was kept live in this build; only the follow-up plan makes it DB-only. The sentence's point, that outbound 443 is a runtime dependency, also still holds. The ufw comment at 369 ("live video metadata") is true. The nginx `location /api/` block already covers `/api/video/refresh`, and its default 60 s read timeout is longer than the 20 s proxy budget.
- [x] `docs/project/issues/20-request-lifecycle-logs.md` - out of scope: Line 25 names `/api/video` in the smoke list for start→end request logs. That route still exists and is still the long-running call bound to the instance, because it was kept live. This future-work spec says nothing that is now false. Adding `/api/video/refresh` would be a scope choice for whoever plans issue 20, not a correction.

**Updated but not named by the Step 3 inventory.** none

**Other files that had to be touched.** none

**ADR conflicts.** none

### `engine/server/README.md`

<changes>
`engine/server/README.md`: the `/api/video` entry is updated, a `/api/video/refresh` entry is added, the write-back rule is documented, and the "read-only" claim on line 3 is corrected.

- **Line 3:** the Engine API is now described as read-only apart from the per-request video metadata write-back. That write is described under `/api/video`.
- **`/api/video` bullet:** gives the lookup parameters (`id`/`video_id`, optional `host`/`instance_domain`) and the 400 `Missing video id` and 404 `Video not found` answers. It says the route reads the DB row, then fetches live metadata from the source instance and merges it over the row field by field. The fetch is the video detail and then its channel, with an 8 s socket timeout on each, made outside `db_lock`. I checked all of this against `resolve_video_row`, `fetch_instance_video_dynamic` and `merge_video_metadata`.
- **New `/api/video/refresh` bullet:** it gives the same answer in the same shape. It is the route the Client proxies with its own budget, and the entry points to `client/README.md` for that budget rather than repeating the 20 s / no-retry figures. I confirmed the dispatch in `similar.py` `_dispatch_get`.
- **New write-back bullet, covering both routes:**
  - The write happens only when the video detail call answered with a non-empty JSON object.
  - It covers the `videos` UPDATE, the `channels` UPDATE when the row has a channel, and the reset of `instances.last_error`, `last_error_at` and `last_error_source`.
  - It runs under its own statement deadline.
  - A `sqlite3.OperationalError` is logged and does not fail the response.
  - A detail call that failed or answered empty or non-object JSON writes nothing, and the response then carries the DB values.

  I checked this against `persist_video_metadata` and the `if dynamic and ...` guard in `handle_video_refresh_request`.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `README.md`

<changes>
Added `/api/video/refresh` to two rows of the boundary table: the Engine public read API and the Client read gateway.

- Line 46 (Engine public read API): added `/api/video/refresh` after `/api/video`. I checked the code: `SimilarHandler._dispatch_get` in `engine/server/api/handlers/similar.py` dispatches it at line 500.
- Line 48 (Client browser-facing read gateway): added `/api/video/refresh` after `/api/video`. I checked the code: it is listed in `PROXY_READ_GET_ROUTES` in `client/backend/server.py` at line 85.
- Everything else is unchanged. Line 134 (the smoke check expects the Client proxy's `/api/video` to answer 200) is still true. The route's behaviour, its 20 s no-retry proxy budget and its `id`/`host` allow-list belong to `engine/server/README.md` and `client/README.md`, so this file doesn't repeat them.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `client/README.md`

<changes>
Added `/api/video/refresh` to the Client read gateway list and described how its proxy differs from the other reads (allow-list, 20 s, no retry, 502 when it times out).

- **Boundary Contract, read gateway list:** added `/api/video/refresh` after `/api/video`.
- **Backend Responsibilities:** added one new bullet before the Engine-failure bullet. It says:
  - The route is proxied like the other GET reads but accepts only `id` and `host`. Any other key, or the same key given twice, answers 400.
  - The proxy waits up to 20 s and sends the request once with no retry (`ENGINE_PROXY_ROUTE_TIMEOUT_SECONDS`, `ENGINE_PROXY_ROUTE_RETRY_COUNT`).
  - A transport failure or timeout answers 502 `ENGINE_PROXY_UNAVAILABLE`.
  - Every other proxied read waits 10 s and is retried once.
- **Engine side not repeated:** for what the route does inside the Engine, the bullet points to `engine/server/README.md` instead of restating it.
- **Checked against `client/backend/server.py`:**
  - The route is in `PROXY_READ_GET_ROUTES` (line 85) and in `PROXY_ALLOWED_QUERY_PARAMS` (line 92).
  - The per-path mappings are at lines 79 and 82, and `_proxy_engine_request` looks them up at lines 589–590.
  - The retry loop and the 502 `ENGINE_PROXY_UNAVAILABLE` answer are at lines 611–751.
  - The 400s for an unknown key and a repeated key come from `_handle_engine_read_proxy_get` (lines 421–436).
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/10-video-metadata-completeness.md`

<changes>
Added a comment to issue 10 about the metadata write path, merge rules and persist-on-success behaviour that issue 11 delivered. Body and `Status:` are unchanged.

- **Write path:** the single write path is `persist_video_metadata`, reached through `handle_video_refresh_request`, which both `/api/video` and `/api/video/refresh` run. The comment lists what it writes today:
  - `title`, `description`, counts, `tags_json`, `category`, `nsfw` and `last_checked_at` on `videos`;
  - channel name, display name and followers on `channels`.
  
  It also says what this issue still has to add: `language`, `duration`, `thumbnail_url`, and tags/category in the response. I checked all of this against `video.py`.
- **Robustness rule is live behaviour:** `fetch_instance_video_dynamic` returns `{}` when the detail call fails or answers empty or non-object JSON. When it does, no UPDATE runs, `instances.last_error*` is not reset and `last_checked_at` is not bumped. The write has its own statement deadline.
- **Merge rules:** these live in `merge_video_metadata`. Title, description and the channel names fall back to the row when empty (`or`). Counts, `tags_json`, `category` and `nsfw` fall back only when missing (`pick_present`), so a supplied 0 is kept. New fields belong in these two functions.
- **Validation line "after the next `/api/video` request":** this holds for either route today. It will hold only for `/api/video/refresh` once issue 11's follow-up plan makes `/api/video` answer from the DB only.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/roadmap.md`

<changes>
Added `/api/video/refresh` to F2-M3's list of routes that still need versioning.

- Line 54 (F2-M3, API versioning) now reads: "`/api/channels`, `/api/video`, `/api/video/refresh` and the similar routes are this feature's work."
- I checked the route against the code: `SimilarHandler._dispatch_get` in `engine/server/api/handlers/similar.py` dispatches the unversioned path `/api/video/refresh` (line 500).
- Nothing else in the roadmap changed. The F11-M2 line and the similarity/video-page order (`08` -> ... -> `11` -> `12`) are still correct, because issue `11` stays open.
</changes>

<not_on_checklist>
none
</not_on_checklist>

### `docs/project/issues/11-fast-similars-response.md`

<changes>
Added a partial-delivery comment to issue 11. Status and location unchanged: the issue stays open in `docs/project/issues/`.

- New `### First plan delivered` comment under `## Comments`, linking `docs/project/plans/19-11-fast-similars-response.md`.
- It records the operator's two-phase reading and why the issue stays open: the page still renders nothing until `/api/video` returns from the instance.
- **Delivered:**
  - `GET /api/video/refresh`. `/api/video` currently runs the same handler.
  - The instance write runs only when the instance's video detail call answered, under its own statement deadline. The comment records the accepted behaviour change: a failed fetch no longer writes, bumps `last_checked_at` or clears `instances.last_error*`, and this already applies to `/api/video`.
  - The Client proxy gives the refresh 20 s and no retry.
  - Similars are not delayed, because the instance calls run outside `db_lock`.
- **Still to do** in the follow-up plan: R1, R3, R4, R5 and R6.
- Each claim was checked against `engine/server/api/handlers/video.py` and `client/backend/server.py`: the `{}` return, the `statement_deadline` + `db_lock` write, the lock held only for the row read, the handler delegation, and the 20 s / 0-retry mappings.
- Deliberately not done: the checklist's harvest action (`Status: complete` and moving the file to `archive/`).
</changes>

<not_on_checklist>
none
</not_on_checklist>

