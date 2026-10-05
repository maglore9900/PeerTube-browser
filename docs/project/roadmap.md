# Roadmap

Milestones and the features planned under them. A line here is an intention, not tracked work: it becomes an issue in `docs/project/issues/` or a plan in `docs/project/plans/` when someone picks it up, and the line then points at that file. Feature ids (`F<n>-M<n>`) are the ones the retired `dev/` tracker used, kept so old commits and notes still resolve.

Markers: a line starting `DONE` is delivered and kept for context; a line starting `PARTIAL` is part-delivered, with what remains named on the line. Unmarked lines are open.

Assumptions from the original milestone plan: 1-2 developers; the Client is 100% public; estimates are rough and solo full-time.

## Delivered

- DONE — **F1-M1** — Engine/Client separation points closed and module boundaries fixed: ownership contract, boundary checks (`tests/check-client-engine-boundary.sh`, `tests/check-frontend-client-gateway.sh`), local/dev split contour validated.
- DONE — **Security remediation, old tasks 69-79** — shared `safeExternalUrl` on every frontend URL sink; embed iframe scheme-gated and sandboxed; `?api=` override DEV-only; CSP on pages and in the nginx config; non-http(s) URLs rejected at crawl; `/api/channels` term escaped and capped; SQLite statement deadline; crawled text capped at 200 chars; gateway forwards `X-Client-IP`; internal event ingest capped and batched; Client->Engine bridge authenticated with `ENGINE_BRIDGE_TOKEN` and the browser publish passthrough removed.
- DONE — **F6-M3** — multilingual hybrid search API. `docs/project/plans/archive/01-search-api.md`.
- DONE — **F10-M2** — video search page. `docs/project/plans/archive/02-search-page.md`.
- DONE — **F12-M2, block half** — per-profile channel and account blocks, filtered from feeds and search by the Client. `docs/project/plans/archive/07-channel-blocks.md`.
- DONE — **F12-M2, likes and dislikes server half** — profile-held likes and dislikes, dislike taste vectors computed by the Engine, disliked videos removed from and similar videos ranked lower in the profile's feeds, and the reaction and likes-import routes. `docs/project/plans/03-like-dislike.md`.
- DONE — **F12-M2, likes and dislikes frontend half** — like, un-like, dislike and un-dislike on the video page with honest active, in-flight and error states; local likes imported into a profile; My likes read from the profile with a Remove control per card (issue `15`); the visitor's reaction marked on feed, search and similar cards; an undone like neutral in the Engine's random and popular reads. `docs/project/plans/08-likes-dislikes-frontend.md`.
- DONE — **Security issue `06`, instance host normalisation** — `sync-whitelist.py` and the updater's `fetch_join_hosts` pass every JoinPeerTube hosts-list entry through `data.moderation.normalize_host_token`, a port of the crawler's `normalizeHostToken`, so all three readers store one spelling per host. `docs/project/plans/archive/10-normalise-instance-hosts.md`.
- DONE — **Security issue `01`, deterministic event ids and popular signal cap** — the Client derives each `Like`/`UndoLike` id from actor, video, event type and like generation, and a profile publishes only when a like opens or closes, so repeated likes collapse at the Engine's ingest; the popular ordering adds at most `POPULAR_SIGNAL_CAP` of a video's interaction signal. `docs/project/plans/archive/13-deterministic-event-ids.md`.
- DONE — **Security issues `02` to `05`** — trusted-proxy client address, batch like resolution, tightened response defaults and raw event retention. `docs/project/plans/archive/16-12-trusted-proxy-client-address.md`, `16-14-batch-like-resolution.md`, `16-15-tighten-response-defaults.md`, `16-11-raw-event-retention.md`.
- DONE — **F11-M2, issue `14`, collapsible video description** — the video page clips the description to four lines, with a "Show more"/"Show less" toggle shown only while the text is longer. `docs/project/plans/archive/19-14-collapsible-description.md`.
- DONE — **F11-M2, issue `13`, read-only video comments** — the video page shows the source instance's comment threads, fetched directly by the browser, newest first and 20 per "Load more comments", with replies expandable per thread, remote text rendered as text only, and "Comments are unavailable on {host}." with the original-video link when the instance cannot supply them. `docs/project/plans/archive/19-13-video-comments.md`.
- DONE — **F11-M2, issues `10` to `12`, video page metadata and similars** — video metadata completeness, fast similars response (`/api/video/refresh`) and similars loaded on scroll. `docs/project/plans/archive/19-10-video-metadata-completeness.md`, `19-11-fast-similars-response.md`, `19-12-similars-on-scroll.md`.
- DONE — **F11-M2, Translate from instance captions (plan 18, B1)** — for a visitor with a profile, a Translate toggle on the video page shows the source instance's own English caption track as text over the embed, in time with playback; the Engine fetches the track from the video's own host only, parses it strictly and caches it in `engine/server/db/subtitles.db`, and a video without one reads "No English translation is available for this video."; see `client/frontend/README.md`. `docs/project/plans/archive/48-translate-instance-captions.md`.
- DONE — **F11-M2, Translate generation from the video page (plan 18, B2 page side)** — with Translate on and no English track, the video page queues a Whisper translate job while a translate worker is serving and shows its English lines as they arrive, with a label for each job state; see `client/frontend/README.md`. `docs/project/plans/archive/50-translate-generation-in-page.md`.
- DONE — **Dataset migration (old "Phase 0")** — re-embed on the multilingual model and FTS5 sync, which the search API runs against. Whether the similarity and random caches were rebuilt afterwards was not verified at migration. Resume a stalled build with `scripts/run-dataset-build.sh --from sync`: the tags stage re-fetches every no-tag video on each run and never converges.
- DONE — **Issue `09`, up-next similars diversity** — up-next pools filled past one batch by a serve-time ANN fallback that never writes the similarity cache, each refresh a score-weighted random draw from the pool's top rows, and likes reranking that window at alpha 0.7 / beta 0.3 so the source video stays dominant. `docs/project/plans/19-09-similars-diversity.md`.
- DONE — **F3-M3, issue `16`, similarity-weighted popular draw** — with likes, the home feed's popular layer draws its candidates weighted by similarity to the likes instead of uniformly, set by `generators.popular.weighted_random_alpha` (1.0 by default, 0 disables); see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, "popular Layer". `docs/project/plans/20-16-popular-weighted-random.md`.
- DONE — **F3-M3, issue `17`, home feed modes** — the home page switches its feed between Recommendations, Hot, Recent, Random and Popular, carried as the `mode` parameter on unseeded `/recommendations` requests and remembered in the URL and `localStorage`; hot, recent and popular are global orders paged through `exclude`. See `engine/server/README.md` for the parameter and `engine/server/api/recommendations/docs/OVERVIEW.md` for the orders. `docs/project/plans/19-17-feed-modes.md`.
- DONE — **Logging, issues `18` to `21`** — about-page outbound click tracking, timestamped request logs, request lifecycle logs and static page visit logs. `docs/project/plans/archive/23-18-about-outbound-click-tracking.md`, `20-19-timestamped-request-logs.md`, `21-20-request-lifecycle-logs.md`, `22-21-static-page-visit-logs.md`.
- DONE — **Issues `22` and `23`, random cache background refresh and non-blocking startup** — the Engine answers `/api/health` without waiting on a random-cache build: it opens a usable cache read-only, starts listening, and builds in one background worker at start and every `RANDOM_CACHE_REFRESH_INTERVAL_MINUTES` (60 by default, 0 disables), each build written to a temp file, renamed over the cache and swapped in as a new read-only handle; see `engine/server/api/recommendations/docs/LAYER_PARAMS.md`, "Random Cache Params (Global)". `docs/project/plans/19-22-random-cache-background-refresh.md`.
- DONE — **Issues `24` and `25`, similarity cache shadow swap and precompute of existing sources**. `docs/project/plans/archive/19-24-similarity-cache-shadow-swap.md`, `19-25-similarity-precompute-existing-sources.md`.
- DONE — **Issue `26`, zero-downtime Engine deploy** — the prod Engine runs as `peertube-engine@7070` or `@7071` behind a loopback nginx listener on `127.0.0.1:7079`, and `scripts/deploy-bluegreen.sh --blue-green` starts the other instance, switches the nginx upstream to it once it is healthy, then drains and stops the old one, rolling back on its own if anything fails before the switch is confirmed; see `DEPLOYMENT.md`, "Blue/green deploy". `docs/project/plans/19-26-zero-downtime-deploy.md`.
- DONE — **F13-M2, issue `40`, search card controls** — search result cards carry Like, Dislike, Block channel and Block account; on search, Dislike toggles and the card stays, and a block removes the source's loaded cards; see `client/frontend/README.md`. The same controls on home feed cards were already in the tree, and the docs do not record which change delivered them. `docs/project/plans/archive/20-40-search-card-actions.md`.
- DONE — **F1-M2, issue `08`, stable ANN ids** — every embedded video carries `video_embeddings.ann_id`, an int64 derived from its video id and instance host (ADR-0006), and the FAISS index, similar, vector search, the similarity precompute and the random cache (`random_ann_ids`) resolve hits through it, so an index left stale by a merge, purge or re-embed misses new videos rather than returning wrong ones; the Engine refuses to start on an index whose sidecar `id_source` is not `video_embeddings.ann_id`. See `DATA_BUILD.md` for the migration and index rebuild. `docs/project/plans/41-ann-ids-a-schema-writers.md`, `docs/project/plans/42-ann-ids-b-readers-cutover.md`, `docs/project/issues/archive/08-stable-ann-ids.md`.
- DONE — **Issue `38`, Trending from source instances** — the home feed's Trending mode and the Recommendations mix's popular layer serve the Trending order: each catalogue host's own PeerTube `sort=-trending` top 100, fetched by the updater's weekly trending stage into `trending_ranks` and merged by rank (ADR-0010); `mode=hot` answers 400, and the frontend reads a stored or linked `hot` as `trending`. See `engine/server/db/jobs/docs/UPDATER_WORKER.md`, "Trending Stage", and `engine/server/api/recommendations/docs/OVERVIEW.md`. `docs/project/plans/45-trending-from-source-instances.md`, `docs/project/plans/46-45-trending-from-source-instances.md`, `docs/project/issues/archive/38-hot-trending-by-growth.md`.

## M1 — Baseline contour and validation

Goal: lock and verify the implemented baseline of Engine/Client separation.
Checkpoint: dev/prod flows are reproducible and match the current architecture.

- F2-M1 — Formalize the Client <-> Engine API contract in a separate specification and make it the source of truth.
- F3-M1 — Lock and document the baseline Client <-> Engine integration contract (validation, error handling, proxy behaviour).
- Optionally, decide whether the likes import should publish `Like` events. Imported likes publish nothing and never open a published like.
- Add a cursor parameter to the ordered feeds (trending, recent, popular). Continuation through `exclude` ends the feed after about 500 shown rows, and rows the gateway removes for a profile never enter `exclude`, so they pile up at the head of every later page.

## M2 — Video-ID indexing and UI rewrite foundations

Goal: complete migration to a stable ID scheme; rebuild the UI foundations.
Checkpoint: migration to video ID does not break delivery or the API contract; full, incremental and rebuild scenarios are aligned.

- DONE — F2-M2 — Adapt the full index rebuild mechanism to video ID. Delivered with stable ANN ids (issue `08`): the full rebuild keys the index by `video_embeddings.ann_id`, derived from video id and host.
- F3-M2 — Implement/adapt incremental vector and index recomputation for the new scheme. Unblocked by issue `08` (ADR-0006).
- F4-M2 — Correct content deletion without a full index rebuild.
- F5-M2 — Major frontend refactor (replace static HTML/CSS).
- F6-M2 — Scalable frontend framework and component architecture.
- F7-M2 — Unified design system. Issue `28` (`docs/project/plans/archive/21-28-tailwind-evaluation.md`) moved the shared rules into one base stylesheet and deferred Tailwind to this feature.
- F8-M2 — Responsive, mobile-friendly interface.
- PARTIAL — F9-M2 — Home page (feed modes, video cards, dynamic loading). Feed modes (issue `17`) and feed paging (`docs/project/plans/archive/09-feed-paging.md`) are delivered; what remains is the page on the new UI architecture (F5-M2, F6-M2).
- PARTIAL — F11-M2 — Video page (player, comments, similar/up-next). Delivered: comments (`13`), collapsible description (`14`), metadata completeness (`10`), fast similars (`11`), similars on scroll (`12`), up-next diversity (`09`), the Translate overlay from instance English caption tracks (`docs/project/plans/archive/48-translate-instance-captions.md`), the Whisper translate worker that turns a queued job into stored English cues (`docs/project/plans/archive/49-translate-whisper-worker.md`; see `engine/server/db/jobs/docs/TRANSLATE_WORKER.md`), that worker's requeue with back-off when `whitelist.db` is locked or missing at claim (issue `45`, `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`), and Whisper generation requested and shown from the video page (`docs/project/plans/archive/50-translate-generation-in-page.md`). Remaining: the player, still the instance embed (see `docs/project/plans/18-english-subtitles.md`).
- PARTIAL — F13-M2 — Block controls on the channels page. Card controls on the feed and search grids (issue `40`) are delivered; the channels page is what remains.

## M3 — API v1 and discovery behaviour

Goal: public API v1 and the UI on the new architecture with feature parity.
Checkpoint: Home/Search/Video run on the new UI architecture with API v1 and feed modes.

- F1-M3 — Public REST API.
- F2-M3 — API versioning. Only `/api/v1/search/videos` is versioned today; `/api/channels`, `/api/video`, `/api/video/refresh` and the similar routes are this feature's work.
- DONE — F3-M3 — Feed modes: recommendations, trending, recent, random, popular. Delivered on the home feed (issue `17`, with trending from issue `38`), together with the similarity-weighted popular draw (issue `16`); the video page and up-next have no feed modes.
- DONE — F4-M3 — Endpoint `similar(video_id)`. `GET /videos/{id}/similar` and POST `/videos/similar` exist (unversioned; versioning is F2-M3), with up-next diversity from issue `09`.
- F5-M3 — Endpoint `recommendations(list_of_video_ids)`.
- F7-M3 — Verify client read compatibility during indexing scheme changes.

## M4 — Discovery and controlled content scope

Goal: controllable sources and discovery without mandatory deep personalisation.
Checkpoint: content sources and crawler scope are controlled explicitly and predictably.

- F1-M4 — Content selection endpoint within a specified instance/source.
- F2-M4 — Crawler mode with federated scope limitation. Issue `27-crawler-seed-instance-mode` was closed `wontfix` as a deferral; its findings are the starting point.
- PARTIAL — F3-M4 — Storage of local user actions (likes/comments) in a local data model (if required by product). Likes, dislikes and blocks are stored per profile in the Client's `users.db`; comments are not.
- F4-M4 — Feed parameter panel (if required by product). `docs/project/plans/archive/04-feed-parameter-panel.md`.

## M5 — Federation and social delivery

Goal: a working federated contour, validated in practical hosting modes.
Checkpoint: social actions from the Client and federated ingest in the Engine pass end to end and are covered by tests.

- F1-M5 — ActivityPub actor for the Engine.
- F2-M5 — Follow logic and processing of incoming ActivityPub updates.
- F3-M5 — Deduplication of incoming ActivityPub activities.
- F4-M5 — Sending likes and comments via ActivityPub to the source instance.
- F5-M5 — User profile (avatar, nickname, settings) (if required by product).
- F6-M5 — User data export (if required by product).
- F7-M5 — Integration and contract tests for the federated flow.
- Fix the interaction architecture for Engine and Client hosted on one machine.

## M6 — Moderation and governance

Goal: a practical moderation MVP with transparent rules and entities.
Checkpoint: reports and moderation outcomes are consistent between the Client UI and Engine moderation state.

- F1-M6 — Engine moderation system (ban instances, channels).
- F2-M6 — Public Engine dashboard (key statistics).
- F3-M6 — Collection and publication of statistical data.
- F4-M6 — Display of blocked / active / new instances.
- F5-M6 — Moderation and data management UI for the Engine.
- F6-M6 — UI for Engine analytics.
- F7-M6 — User reporting (report + reason).
- F8-M6 — Moderation dashboard.
- F9-M6 — Client-side moderation (users/content/comments).
- Move `engine/server/db/jobs/compare-join-hosts.py` (`hosts_from_payload`, `load_local_hosts`) onto `normalize_host_token`. It is the only Python reader of the JoinPeerTube hosts list that still uses `strip().lower()`, so it can report hosts as missing that the whitelist sync and the updater treat as present.
- Make the crawler's `--whitelist-file` mode agree with its URL mode on trailing dots. `loadHostsFromFile` sends bare hosts through `normalizeHostToken`'s dot-trimming branch, while URL-form entries keep the WHATWG trailing dot, so a dotted host read back from the updater's hosts file changes spelling and churns through purge and recrawl.
- Optionally, make `normalize_host` (denylist input) bracket IPv6 literals and convert IDNs to punycode, so denylist entries match the spelling `normalize_host_token` stores for join hosts.

## M7 — Production operations and reliability

Goal: close the production contour and the security layer on a stable architecture.
Checkpoint: production deployment and the security perimeter operate together without degrading public client availability.

- PARTIAL — F1-M7 — Independent production deployment for the Engine. Zero-downtime blue/green deploy (issue `26`) is delivered; see `DEPLOYMENT.md`.
- F2-M7 — Build and data build as a single production-ready command.
- F3-M7 — Database migration system.
- F4-M7 — Data backup (database and indexes). The runtime-reliability and logging issues the old tracker filed here (`19` to `26`) are all delivered.
- F5-M7 — Task queue for heavy operations.
- F6-M7 — Third-party instances using the Engine via API (plugin-like).
- F7-M7 — API-level rate limiting (IP, instance, service keys).
- F8-M7 — IP and instance-level blocking and restriction.
- F9-M7 — Input size limits and request validation.
- F10-M7 — Service/API keys for internal and admin scenarios (not end-user auth).
- F11-M7 — Service key management (create, revoke, limits).
- F12-M7 — Baseline roles/permissions for admin operations.
- F13-M7 — Independent production deployment for the Client.
- F14-M7 — Client-side security hardening (XSS, CSRF, session protection, secure headers).

## M8 — Documentation and external readiness

Goal: make the platform understandable and integrable for external users.
Checkpoint: documentation reflects real Engine+Client behaviour and is understandable without implicit knowledge.

- F1-M8 — Separate project presentation website.
- F2-M8 — Architecture description (Engine + Client + interaction model).
- F3-M8 — Platform capabilities and usage scenarios.
- F4-M8 — Public API and integration section.
- F5-M8 — Links to live demo / UI. The documentation issues the old tracker filed here are closed: `29-recommendations-overview-doc` delivered, `30-missing-docstrings` `wontfix`.
- F6-M8 — Full technical documentation (installation, startup, deployment, data build, API usage).
- F7-M8 — Documentation for third-party developers using the Engine.

Release grouping from the original plan: A = M1-M2, B = M3-M5, C = M6-M8.

## Implementation order

Dependency order across the open plans and issues. Items in one step are independent of each other. A step may not start before the constraint named under it holds. The security remainder (`02` to `05`) and the similarity, logging, runtime-reliability and documentation sequences (`08` to `12`, `18` to `26`, `29`) are delivered; `27` and `30` are closed `wontfix`.

1. **Language** — feed panel I1's remainder only if still wanted (stored labels; `videos.language` already holds the PeerTube language code, captured by the crawler and by `/api/video`, and labels resolve at read time through `engine/server/data/peertube_labels.py`), then I2 (the filter), then I3 (the backfill) whenever convenient. Existing rows get a language only from a full re-crawl, since `--new-videos` and the `INSERT_ONLY` videos merge skip rows already present, or from video-page views, which write to `whitelist.db` and are discarded by the next sync (see `DATA_BUILD.md`).
2. **Saved channels** — feed panel I4 and I5, stored per profile in the Client's `users.db` beside likes, dislikes and blocks. Renamed Follow in `CONTEXT.md`, and filed as `docs/project/issues/59-follow-channels-and-accounts.md`.
3. **Feed parameter panel** — feed panel I7, last: it binds every input above. Feed paging (I6) is delivered by `docs/project/plans/archive/09-feed-paging.md`.
