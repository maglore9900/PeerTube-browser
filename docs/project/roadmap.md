# Roadmap

Milestones and the features planned under them. A line here is an intention, not tracked work: it becomes an issue in `docs/project/issues/` or a plan in `docs/project/plans/` when someone picks it up, and the line then points at that file. Feature ids (`F<n>-M<n>`) are the ones the retired `dev/` tracker used, kept so old commits and notes still resolve.

Assumptions from the original milestone plan: 1-2 developers; the Client is 100% public; estimates are rough and solo full-time.

## Delivered

- **F1-M1** — Engine/Client separation points closed and module boundaries fixed: ownership contract, boundary checks (`tests/check-client-engine-boundary.sh`, `tests/check-frontend-client-gateway.sh`), local/dev split contour validated.
- **Security remediation, old tasks 69-79** — shared `safeExternalUrl` on every frontend URL sink; embed iframe scheme-gated and sandboxed; `?api=` override DEV-only; CSP on pages and in the nginx config; non-http(s) URLs rejected at crawl; `/api/channels` term escaped and capped; SQLite statement deadline; crawled text capped at 200 chars; gateway forwards `X-Client-IP`; internal event ingest capped and batched; Client->Engine bridge authenticated with `ENGINE_BRIDGE_TOKEN` and the browser publish passthrough removed.
- **F6-M3** — multilingual hybrid search API. `docs/project/plans/archive/01-search-api.md`.
- **F10-M2** — video search page. `docs/project/plans/archive/02-search-page.md`.
- **Dataset migration (old "Phase 0")** — re-embed on the multilingual model and FTS5 sync, which the search API runs against. Whether the similarity and random caches were rebuilt afterwards was not verified at migration. Resume a stalled build with `scripts/run-dataset-build.sh --from sync`: the tags stage re-fetches every no-tag video on each run and never converges.

## M1 — Baseline contour and validation

Goal: lock and verify the implemented baseline of Engine/Client separation.
Checkpoint: dev/prod flows are reproducible and match the current architecture.

- F2-M1 — Formalize the Client <-> Engine API contract in a separate specification and make it the source of truth.
- F3-M1 — Lock and document the baseline Client <-> Engine integration contract (validation, error handling, proxy behaviour).
- Open security issues: `01` to `07` in `docs/project/issues/`.

## M2 — Video-ID indexing and UI rewrite foundations

Goal: complete migration to a stable ID scheme; rebuild the UI foundations.
Checkpoint: migration to video ID does not break delivery or the API contract; full, incremental and rebuild scenarios are aligned.

- F1-M2 — Migrate to video-ID-based indexing (top priority). Related: issue `08-stable-ann-ids`.
- F2-M2 — Adapt the full index rebuild mechanism to video ID.
- F3-M2 — Implement/adapt incremental vector and index recomputation for the new scheme.
- F4-M2 — Correct content deletion without a full index rebuild.
- F5-M2 — Major frontend refactor (replace static HTML/CSS).
- F6-M2 — Scalable frontend framework and component architecture.
- F7-M2 — Unified design system. Related: issue `28-tailwind-evaluation`.
- F8-M2 — Responsive, mobile-friendly interface.
- F9-M2 — Home page (feed modes, video cards, dynamic loading).
- F11-M2 — Video page (player, comments, similar/up-next). Related: issues `10` to `14`.
- F12-M2 — Like/dislike (add/remove). `docs/project/plans/03-like-dislike.md`.

## M3 — API v1 and discovery behaviour

Goal: public API v1 and the UI on the new architecture with feature parity.
Checkpoint: Home/Search/Video run on the new UI architecture with API v1 and feed modes.

- F1-M3 — Public REST API.
- F2-M3 — API versioning. Only `/api/v1/search/videos` is versioned today; `/api/channels`, `/api/video` and the similar routes are this feature's work.
- F3-M3 — Feed modes: random, hot, popular, fresh, recommendations. Related: issues `16-popular-weighted-random`, `17-feed-modes`.
- F4-M3 — Endpoint `similar(video_id)`. Related: issue `09-similars-diversity`.
- F5-M3 — Endpoint `recommendations(list_of_video_ids)`.
- F7-M3 — Verify client read compatibility during indexing scheme changes.

## M4 — Discovery and controlled content scope

Goal: controllable sources and discovery without mandatory deep personalisation.
Checkpoint: content sources and crawler scope are controlled explicitly and predictably.

- F1-M4 — Content selection endpoint within a specified instance/source.
- F2-M4 — Crawler mode with federated scope limitation. Related: issue `27-crawler-seed-instance-mode`.
- F3-M4 — Storage of local user actions (likes/comments) in a local data model (if required by product).
- F4-M4 — Feed parameter panel (if required by product). `docs/project/plans/04-feed-parameter-panel.md`.

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

## M7 — Production operations and reliability

Goal: close the production contour and the security layer on a stable architecture.
Checkpoint: production deployment and the security perimeter operate together without degrading public client availability.

- F1-M7 — Independent production deployment for the Engine.
- F2-M7 — Build and data build as a single production-ready command.
- F3-M7 — Database migration system.
- F4-M7 — Data backup (database and indexes). The old tracker also filed runtime-reliability and logging tasks here: issues `19` to `26`.
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
- F5-M8 — Links to live demo / UI. The old tracker also filed documentation tasks here: issues `29-recommendations-overview-doc`, `30-missing-docstrings`.
- F6-M8 — Full technical documentation (installation, startup, deployment, data build, API usage).
- F7-M8 — Documentation for third-party developers using the Engine.

Release grouping from the original plan: A = M1-M2, B = M3-M5, C = M6-M8.

## Implementation order

Dependency order across the open plans and issues. Items in one step are independent of each other. A step may not start before the constraint named under it holds.

1. **Security remainder, identity-independent** — issues `01`, `02`, `03`, then `04`, `05`, `06`. Issue `01` must precede like/dislike I2, because it changes how repeated likes deduplicate.
2. **Identity** — issue `07`, after deciding like/dislike O8 (key lifecycle). Every Engine-side profile item below is blocked on it.
3. **Like correctness, client-only** — like/dislike I1 and I2, after resolving the overlap with issue `15`. Needs step 1's issue `01`, nothing else.
4. **Filter profile and its consumers** — like/dislike I5 -> I3 and I4 -> I6 and I7 -> I8, in that order. Needs step 2; I4 needs O3 (penalty magnitude) settled.
5. **Language** — feed panel I1 and I2, then I3 whenever convenient. Landing I1 before any further crawl avoids a second full re-crawl.
6. **Saved channels** — feed panel I4 and I5, after like/dislike I5 so both share one profile store.
7. **Feed paging** — feed panel I6, after like/dislike I4 so the seed is designed once.
8. **Feed parameter panel** — feed panel I7, last: it binds every input above.

Independent of that sequence, each with its own internal order noted in the issue files:

- Similarity and video page: `08` -> `09` -> `10` -> `11` -> `12`, plus `13` (comments, any time) and `14`.
- Feed: `16` -> `17`.
- Logging: `19` -> `20` -> `21`; `18` is orthogonal.
- Runtime reliability: `22` -> `23` -> `24`/`25` -> `26`.
- Crawler: `27`.
- Last: `29`, `30`.
