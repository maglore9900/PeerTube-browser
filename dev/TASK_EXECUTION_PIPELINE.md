# Task Execution Pipeline

This file is the coordination source of truth for multi-task execution.
Use it before implementing any task bundle.

## Recommended implementation order

### Execution sequence (recommended)
1. **37** (stable ANN IDs: `video_id+host -> int64`)  
   First establish stable ANN id contract before further similarity tuning.
2. **33** (video-page similars diversity + larger pools)  
   Build on finalized ANN/cache config and incremental recompute behavior.
3. **3** (video metadata completeness + refresh mutable fields)  
   Improves data quality on video page and creates better API/DB test baseline.
4. **1** then **2** (video-page UX flow for similars)  
   First fast initial response, then progressive loading/scroll behavior.
5. **4** (comments) and **9/9b** (description + single-like removal)  
   Video/profile UX improvements with low backend risk.
6. **12a** then **8b** (popular weighted-random + feed modes)  
   Finalize popular-layer behavior before exposing it as user-facing feed mode.
7. **87** then **88** and **89** then **90** then **91** (search API: multilingual embedding space, FTS5 index, query encoder, hybrid endpoint, gateway)  
   The model change comes first because the re-embed it triggers is the expensive pass and everything downstream is ranked against the resulting space; **88** and **89** are independent of each other; **90** needs both; **91** exposes the finished route.
8. **10** (search page) and **8c** (about outbound analytics)  
   **10** consumes the endpoint from **90**/**91**; **8c** is orthogonal.
9. **41** then **38** then **43** (timestamped lifecycle logs + request correlation + static-page visit logs)  
   Establish one logging contract first, then add request-id linked lifecycle logs, then extend observability to nginx-served static pages.
10. **16l** then **39** then **44** then **56** then **40** (cache runtime safety + similarity precompute scope + shadow swap + zero-downtime deploy)  
   Add background/atomic cache refresh primitives first, then startup no-downtime hardening, then similarity-cache precompute scoping, then shadow cutover, then blue/green nginx switch automation.
11. **16**, **11** (docs + docstrings)  
   Finalize documentation polish after behavior/stability changes land.

### Functional blocks (aligned with the same order)
- **Block A: Similarity and recommendation core**
  - Tasks: **37 -> 33 -> 12a**
  - Scope: ANN/similarity defaults, impacted recompute, upnext diversity, popular-layer sampling quality.
  - Outcome: ANN switches to stable `ann_id` mapping, upnext refresh stops repeating the same 8 cards, and popular feed uses weighted-random by similarity instead of flat random sampling.
- **Block B: Video page data + UX behavior**
  - Tasks: **3 -> 1 -> 2 -> 4 -> 9 -> 9b**
  - Scope: metadata completeness, fast similar rendering, comments, profile/likes interactions.
  - Outcome: video page loads similars immediately (without waiting for remote metadata), renders progressive similars from one larger batch on scroll, shows tags/category with mutable-field refresh, supports read-only comments with pagination, has collapsible description, and allows removing one like instead of only full reset.
- **Block C: Feed and discovery product features**
  - Tasks: **8b -> 10 -> 15**
  - Scope: feed modes, search page UI, crawler seed mode from one instance/subscriptions.
  - Outcome: home page gets explicit feed mode switch (`recommendations/hot/recent/random/popular`), the search page renders paged and sorted results from the Engine search endpoint that Block L delivers, and crawler can start from one `--seed-instance` and expand through federated subscriptions.
- **Block L: Multilingual search API (`F6-M3`)**
  - Tasks: **87 -> 88 -> 89 -> 90 -> 91**
  - Scope: embedding model of record, FTS5 lexical index, query-time encoder, hybrid endpoint, gateway exposure.
  - Outcome: the dataset is embedded in a multilingual space instead of an English-only one, `whitelist.db` carries a trigger-maintained FTS5 index over video text, the Engine loads a query encoder on first search and releases it after 15 minutes idle, `GET /api/v1/search/videos` answers with bm25 and vector results fused by reciprocal rank under paging, sorting, moderation filtering and the statement deadline, an English query reaches non-English videos, and the route is reachable through the Client gateway only.
- **Block D: Analytics and style infrastructure**
  - Tasks: **8c -> 8**
  - Scope: outbound click analytics and optional styling-system consolidation.
  - Outcome: About-page outbound links send tracked events to a dedicated API endpoint and SQLite analytics table (with validation/rate-limit path), while repeated styling patterns can be migrated to a shared Tailwind-based system for new blocks.
- **Block E: Documentation and maintenance**
  - Tasks: **16 -> 11**
  - Scope: recommendations docs alignment and missing docstrings.
  - Outcome: `RECOMMENDATIONS_OVERVIEW` is aligned with actual runtime pipeline (candidate generation/mixing/filters), and touched modules/functions/classes have explicit docstrings so behavior is readable without code archaeology.
- **Block F: Logging and observability**
  - Tasks: **41 -> 38 -> 43**
  - Scope: explicit timestamped request logs, request-id correlation across request lifecycle, and static-page visit visibility for About/static informational pages.
  - Outcome: every API request gets `request-start -> work logs -> request-end` with one shared `request_id` and explicit timestamp format, and nginx adds dedicated visit logs for static informational routes with request-correlation-compatible fields.
- **Block H: Client-side injection remediation (security audit F1-F4)**
  - Tasks: **69 -> 70 -> 71 -> 72 -> 73**
  - Scope: frontend URL sinks, embed iframe, API base override, response CSP, crawler URL validation.
  - Outcome: every frontend `href`/`src` assignment passes through one scheme-checked helper and the channels link is escaped, the embed iframe accepts only `https://` sources inside a sandbox, `?api=` is ignored in production builds, the Client backend sends a `script-src 'self'` CSP on HTML responses, and non-`http(s)` channel/video URLs never enter the database.
- **Block I: Engine availability remediation (security audit F9-F11)**
  - Tasks: **74 -> 75 -> 76 -> 77 -> 78**
  - Scope: `/api/channels` search term handling, SQLite statement deadline, crawled text length, gateway client identity, internal events batching.
  - Outcome: `?q=` search terms are escaped and length-capped so the caller cannot control wildcard count, no Engine statement can hold `db_lock` past a deadline, crawled names are length-bounded at ingest, the Engine rate limiter buckets per real client instead of one deployment-wide bucket, and event batches are size-capped and committed in one transaction with the lock released between chunks.
- **Block J: Client->Engine trust boundary (security audit F5-F8)**
  - Tasks: **79 -> 80 -> 81 -> 82 -> 83**
  - Scope: bridge authentication, event idempotency and ranking influence, proxy-aware rate-limit keys, profile identity, like resolution batching.
  - Outcome: Engine `/internal/*` requires a shared secret and is no longer reachable from a browser, replayed like events collapse on a deterministic `event_id` with a capped effect on popular ordering, both services key rate limits on a trusted-proxy-resolved address, server-side profiles are either cookie-bound or removed, and one likes request costs one Engine call instead of up to 200.
- **Block K: Security hardening notes (security audit runs 1-2)**
  - Tasks: **84 -> 85 -> 86**
  - Scope: response defaults, data retention, host normalisation.
  - Outcome: write endpoints send an explicit CORS origin instead of `*`, callers receive generic error messages instead of exception text, recommendation debug output is off by default, `interaction_raw_events` is pruned on a retention window, like expansion on the similar endpoint is capped, and JoinPeerTube host entries are normalised on the Python path before storage.
- **Block G: Runtime reliability and operations**
  - Tasks: **16l -> 39 -> 44 -> 56 -> 40**
  - Scope: safe cache refresh/swap runtime behavior (random + similarity), scoped similarity precompute updates, and automated blue/green nginx cutover.
  - Outcome: random/similarity caches refresh via shadow files + atomic swap, updater similarity stage can rewrite scoped cache sources instead of full rebuilds, and deploy script performs blue/green switch on `7070/7071` with health-check gate and rollback.
### Cross-task overlaps and dependencies
- **1 <-> 2 <-> 33**: all touch video-page similar retrieval/rendering behavior.  
  Backend candidate quality/diversity (**33**) should be stable before final UX behavior (**1**, **2**).
- **8b <-> 12a**: both touch popular layer output behavior.  
  Weighted-random in popular should be finished before exposing/locking popular mode UX.
- **41 <-> 38**: same logging contract and request context propagation.  
  Introduce timestamp/log format first (**41**), then request lifecycle + shared request id (**38**) to avoid duplicate logging rewrites.
- **38 <-> 43**: both rely on cross-log correlation (`request_id`, timestamp conventions, runbook).  
  Implement request-trace contract first (**38**), then static-page visit visibility in nginx (**43**).
- **8c <-> 43**: both touch About-page observability and can overlap in intent (analytics vs logging).  
  Keep `8c` as event analytics and `43` as request log visibility to avoid duplicate instrumentation responsibilities.
- **38 <-> 40**: both touch nginx-facing request metadata (`X-Request-ID` propagation and operational config).  
  Keep request-id forwarding contract compatible with blue/green switch scripts and nginx templates.
- **16l <-> 39**: same random-cache runtime path (background refresh, atomic swap, locks).  
  Keep one cache refresh source of truth; implement startup non-blocking behavior on top of `16l` primitives.
- **39 <-> 44**: same operational primitives (shadow file build, atomic swap, lock-scoped reconnect).  
  Reuse one swap/reopen safety pattern across random and similarity cache paths.
- **44 <-> 56**: both touch updater similarity stage and cache rewrite behavior.  
  Land scoped rewrite behavior (**56**) before finalizing long-running shadow/cutover behavior (**44**) to avoid duplicate precompute rewrites.
- **44 <-> 40**: deploy orchestration and cache cutover both affect runtime availability windows.  
  Land in-process similarity cache cutover first, then finalize full blue/green deploy automation.
- **39 <-> 40**: deploy safety depends on fast readiness and warm startup behavior.  
  Zero-downtime cutover (**40**) should be implemented after random-cache startup hardening (**39**).
- **16 / 11** depend on nearly all feature tasks.  
  Doing them earlier causes repeated rewrites.
- **Block H <-> Block I**: independent code paths (frontend/crawler vs Engine request handling).  
  They can run in parallel; neither blocks the other.
- **79 <-> 78**: bridge authentication removes the browser-facing publish path that makes the batch limit multiplication reachable.  
  Land **78** first, or narrow it to the transaction/lock fix once **79** is in.
- **77 <-> 81**: both define how a client address is resolved for rate limiting.  
  Implement the trusted-proxy helper (**81**) as the single source and have the gateway identity header (**77**) consume it, rather than two resolution rules.
- **69 <-> 73**: same URL-scheme trust question at sink and source.  
  Ship the sink helper (**69**) first; the crawler validation (**73**) then cleans stored data without being the only defence.
- **72 <-> 70**: CSP `frame-src` and the iframe `sandbox` attribute both constrain the embed frame.  
  Keep the CSP frame directive compatible with the sandbox value chosen in **70**.
- **87 <-> 89**: both name the embedding model, in the batch job and in the serving process.  
  One model name has to hold on both sides; the Engine's startup gate compares them and disables the vector half when they differ, so land **87** and set `QUERY_ENCODER_MODEL` to the same value.
- **87 <-> Phase 0 re-embed**: the model change only takes effect once the dataset is re-embedded and the ANN index rebuilt.  
  Task **87** changes the default only. Until `run-dataset-build.sh --from embeddings` has run, **90**'s vector half searches an English-only space and acceptance criterion 4 cannot pass.
- **88 <-> 90**: the endpoint's lexical half queries the table **88** creates.  
  `videos_fts` must exist and be populated by a sync-stage run before **90** returns lexical results.
- **89 <-> 90**: the encoder and the sanitizer are used together.  
  The token caps live in **90**'s sanitizer and bound the encoder input, so **89** must not add a second, different cap.
- **90 <-> 74**: the same query-term injection class the `/api/channels` `LIKE` path fixed.  
  Reuse the sanitisation approach from **74** rather than inventing a second escaping rule for FTS5 `MATCH`.
- **90 <-> 10**: the endpoint contract and the page that consumes it.  
  Freeze the response shape in **90** before **10** builds a UI against it.

## Multi-task execution protocol

Protocol is maintained in `TASK_EXECUTION_PROTOCOL.md`.
Use it for every multi-task bundle run together with this pipeline file.

## Update policy when a new task is added

Update policy is maintained in `TASK_EXECUTION_PROTOCOL.md`.

## Bundle command format

Use this command style when requesting multiple tasks:

`Execute bundle: <taskA> -> <taskB> -> <taskC>, mode=strict, no-duplicate-logic`
