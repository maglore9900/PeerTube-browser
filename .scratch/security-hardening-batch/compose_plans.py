"""Compose plans 10-15 from each issue's Agent Brief plus the approved high-level plan."""
import pathlib
import re

ISSUES = pathlib.Path("docs/project/issues")
PLANS = pathlib.Path("docs/project/plans")

BATCH = (
    "Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 "
    "delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, "
    "branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs "
    "in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main "
    "when it closes, and is harvested on main, not in the worktree."
)

COMMON_RISKS = (
    "- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's "
    "test Engines write interaction rows into the same file as other lanes, and as the live Engine if it "
    "runs. Every test run already does this; worktrees only make it concurrent.\n"
    "- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` "
    "always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the "
    "merged tree.\n"
    "- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations "
    "(memory `engine-rate-limit-single-lane-test-runs`)."
)

PLANS_SPEC = [
    {
        "nn": "10", "slug": "normalise-instance-hosts", "issue": "06-normalise-instance-hosts.md",
        "title": "Normalise JoinPeerTube host entries on the Python side",
        "adr": "No ADR. The decision is recorded in the issue's triage comment: an exact port, with no extra validation.",
        "wave": "Wave 1. It touches no file that another batch issue touches.",
        "approach": (
            "Add `normalize_host_token()` to a module in the Engine's shared `engine/server/data` package, "
            "which both jobs already import. It follows the brief's four numbered rules and uses "
            "`urllib.parse` to extract the hostname. Where that differs from WHATWG `URL`, it handles "
            "the case explicitly: userinfo is stripped, the port is stripped, IPv6 literals keep their "
            "brackets, and internationalised names are encoded to punycode (IDNA). `fetch_hosts` in "
            "`sync-whitelist.py` and `fetch_join_hosts` in `updater-worker.py` call it in place of "
            "`strip().lower()` and skip entries that return None.\n\n"
            "Drift protection: one JSON fixture of `input -> expected` pairs covers every input the "
            "brief lists. The Python test checks `normalize_host_token` against the fixture. The same test "
            "then runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js` over the same "
            "inputs and asserts identical output. The expected values are therefore the crawler's own, "
            "and the two sides cannot drift unnoticed."
        ),
        "alternatives": (
            "- **A crawler-side test runner** (vitest or node:test in `engine/crawler`) reading the fixture. "
            "Rejected: the crawler has no test script or runner today (`engine/crawler/package.json`), and "
            "one Python test that invokes Node covers both sides from the suite that already runs.\n"
            "- **Hand-written expected values without running the TS side.** Rejected: that tests Python "
            "against the author's reading of WHATWG, which is where drift hides.\n"
            "- **Reusing `data.moderation.normalize_host`.** Rejected by the triage decision: it is the "
            "lenient normaliser for operator input and stays separate."
        ),
        "risks": (
            "- `dist/host-filters.js` must exist and match `src/`. When `dist` is missing or older than "
            "`src`, the test must fail loudly rather than skip, or it runs `npm run build` first. The build "
            "chooses which at its checkpoint.\n"
            "- `urllib.parse` and WHATWG differ on edge inputs beyond the listed set (for example "
            "percent-encoding and backslashes). Only the listed inputs are pinned; others may differ. The "
            "fixture can grow to cover them later.\n"
            "- Hosts already stored under the old spelling are not rewritten (out of scope), so one "
            "updater run after the change may treat the old and new spellings as different hosts."
        ),
        "tradeoffs": "A Python test depends on Node and on the crawler's compiled output being present.",
    },
    {
        "nn": "11", "slug": "raw-event-retention", "issue": "05-raw-event-retention.md",
        "title": "Strip old raw interaction events and cap likes on /videos/similar",
        "adr": "`docs/project/adr/0005-raw-event-retention-keeps-ids.md`; `CONTEXT.md` **Interaction event**.",
        "wave": (
            "Wave 1. It shares `engine/server/api/handlers/similar.py` with plan 12, in different functions "
            "(lines ~193-233 here, ~283-303 there). It shares `internal_events.py` and `server_config.py` "
            "with plan 15, which runs after this plan merges."
        ),
        "approach": (
            "**Schema.** `ensure_interaction_event_schema()` gains `CREATE INDEX IF NOT EXISTS` on "
            "`interaction_raw_events(ingested_at)`.\n\n"
            "**Strip.** A new function beside `ingest_interaction_event()` in "
            "`engine/server/data/interaction_events.py` takes a connection, a cutoff in ms and a chunk size. "
            "It works one chunk at a time over rows older than the cutoff that are not yet stripped, "
            "setting `raw_payload_json`, `actor_id` and `source_instance` to NULL and committing each chunk. "
            "It returns the total number of rows stripped.\n\n"
            "**Trigger.** After a successful ingest, the Engine's event-ingest handler "
            "(`api/handlers/internal_events.py`) calls the strip if at least an hour has passed since the "
            "last run. A timestamp on the server object records the last run. Each chunk takes and "
            "releases `db_lock` on its own, so no single hold scans the table.\n\n"
            "**Config.** A named 30-day constant goes in `api/server_config.py`. The env var "
            "`INTERACTION_RAW_RETENTION_DAYS` overrides it; it must be a positive integer, checked at "
            "startup, and a bad value stops the Engine with an error naming the variable.\n\n"
            "**Likes cap.** `_recommendations_likes_payload_error()` in `handlers/similar.py` currently "
            "returns early for every path except `/recommendations`. It is widened to both routes in "
            "`SIMILAR_POST_ROUTES`, so `/videos/similar` returns the same 400 body and per-item errors.\n\n"
            "Idempotency needs no change: stripped rows keep `event_id`, so `ON CONFLICT(event_id) DO "
            "NOTHING` still reports a duplicate."
        ),
        "alternatives": (
            "- **Pruning from the updater worker or a timer.** Rejected by ADR-0005: the timer is optional "
            "and weekly, and the ingest path is the only place certain to run when events arrive.\n"
            "- **Deleting old rows.** Rejected by ADR-0005: `event_id` is the idempotency record, and "
            "deleting it lets replays count again.\n"
            "- **A background thread on an interval.** Rejected: it adds a thread lifecycle to the server for "
            "a job the ingest path can rate-limit itself."
        ),
        "risks": (
            "- The first run on a large existing table strips every row past the window, in many chunks. "
            "Each chunk is short, but that first ingest request takes longer: the chunk size bounds each "
            "lock hold, not the whole request.\n"
            "- Reading and writing the timestamp on the server object must be safe under the threaded "
            "server. Either check and set it under the lock, or accept that two threads may very rarely "
            "both run a strip, which is harmless because the strip is idempotent.\n"
            "- Tests age rows by inserting them with a past `ingested_at` rather than waiting."
        ),
        "tradeoffs": "Once an hour, the retention work runs inside an ingest request rather than in a separate job.",
    },
    {
        "nn": "12", "slug": "trusted-proxy-client-address", "issue": "02-trusted-proxy-client-address.md",
        "title": "Resolve the client address once, trusting X-Forwarded-For only from configured proxies",
        "adr": "`docs/project/adr/0002-trusted-proxy-client-address.md`; `CONTEXT.md` **Client address**.",
        "wave": (
            "Wave 1. It shares `client/backend/server.py` with plans 13-15 (later waves), "
            "`engine/server/api/handlers/similar.py` with plan 11 (a different function), and "
            "`DEPLOYMENT.md` with plan 15."
        ),
        "approach": (
            "**Rule.** A pure function in the Client backend takes the peer address, the "
            "`X-Forwarded-For` value and the trusted set. If the peer is in the set and the last trimmed "
            "`X-Forwarded-For` hop is a valid IP, it returns that hop; otherwise it returns the peer. "
            "IPv4-mapped IPv6 peers are unmapped before the membership check. `X-Real-IP` is not read.\n\n"
            "**Config.** `TRUSTED_PROXIES` is parsed once at startup with `ipaddress` into networks held on "
            "the server object. Unset or empty means `127.0.0.1,::1`. A malformed entry raises at startup "
            "with an error naming the entry.\n\n"
            "**Consumers.** `_get_client_ip` (`server.py:171`) is reimplemented on the rule, and all four "
            "consumers read it: the access log (`:202`), the mint limiter (`:280`), `_rate_limit_check` "
            "(`:350`) and the `X-Client-IP` header (`:527`). Today `:280` and `:350` read "
            "`client_address[0]` directly.\n\n"
            "**Engine.** `_get_client_ip` in `engine/server/api/handlers/similar.py:283` returns "
            "`X-Client-IP` when it is non-empty, and the peer otherwise.\n\n"
            "**Docs.** `DEPLOYMENT.md` documents `TRUSTED_PROXIES`, its loopback default, and that every "
            "proxy layer must be listed."
        ),
        "alternatives": (
            "- **The first `X-Forwarded-For` hop** (the audit's suggested fix). Rejected by ADR-0002: nginx "
            "appends to the caller's header, so the caller chooses the first hop.\n"
            "- **Fixing each call site separately.** Rejected: that is how the two rules diverged, which "
            "is the bug.\n"
            "- **Keeping the Engine's `X-Forwarded-For` fallback.** Rejected by ADR-0002: the Engine binds "
            "loopback, and its only peer is the Client backend."
        ),
        "risks": (
            "- A deployment with several proxy layers that does not list them all will key on the inner "
            "proxy. This is documented, not detected.\n"
            "- Existing tests that send `X-Forwarded-For` from a loopback peer and expect the first hop will "
            "now resolve differently. The build's Step 0 baseline will show them.\n"
            "- The engine test fixture calls the Engine directly, not through the Client, so the Engine gets "
            "no `X-Client-IP` and keys on the peer. The harness behaves as it does today."
        ),
        "tradeoffs": "A deployment with several proxy layers must list every layer in `TRUSTED_PROXIES`.",
    },
    {
        "nn": "13", "slug": "deterministic-event-ids", "issue": "01-deterministic-event-ids.md",
        "title": "Derive interaction event ids and cap the signal in the popular ordering",
        "adr": "`docs/project/adr/0001-derived-interaction-event-ids.md`; `CONTEXT.md` **Interaction event**, **Interaction signal**.",
        "wave": (
            "Wave 2, branched from main after plans 10-12 merge, and running alongside plan 14. Both plans "
            "edit `client/backend/server.py`, in different handlers. Both also edit "
            "`client/backend/lib/users_store.py`: this plan changes what `record_like` returns, and plan "
            "14's import calls `record_like` and ignores the return value."
        ),
        "approach": (
            "**Like instance.** The brief leaves its source to the build. The approved design is a new "
            "Client table `like_generations(user_id, video_id, instance_domain, generation)`. "
            "`ensure_user_schema` creates it with `CREATE TABLE IF NOT EXISTS`, and an un-like never "
            "deletes from it.\n"
            "- A `like` that inserts a new `likes` row increments the generation. `record_like` reports "
            "whether the like was new and returns the generation.\n"
            "- An `undo_like`, or a dislike that replaces a like, reads the video's current generation and "
            "removes the like with `remove_like`. It publishes only when a like was removed.\n"
            "- Anonymous actors use a fixed generation `0`.\n\n"
            "**Id.** The user-action handler sets `event_id` to `client-` followed by the SHA-256 hex of the "
            "joined `(actor, video_uuid, instance_domain, event_type, generation)`, replacing "
            "`client-<uuid4>`. Actor is the profile id, or `anonymous`.\n\n"
            "**Publish on change only.** In `_handle_user_action` (`server.py:684`), `publish` is true only "
            "for a new like or when a like was removed. A request that changes nothing still returns 200.\n\n"
            "**Ranking cap.** `engine/server/data/random_videos.py:247` orders by `v.popularity + "
            "MIN(COALESCE(sig.signal_score, 0), C)`, where `C` is a module-level constant set to `25.0`. "
            "Ingest, `_event_deltas` and the stored score are unchanged."
        ),
        "alternatives": (
            "- **A column on `likes`.** Rejected: an un-like deletes the row, so the instance would not "
            "survive to tell the next like apart.\n"
            "- **The like's timestamp as the instance.** Rejected: it does not follow from stored state, so "
            "retrying a request after a partial failure could produce a second id.\n"
            "- **The key without an instance** (the issue's step 1). Rejected at triage (ADR-0001): it drops "
            "genuine re-likes and lets any visitor permanently zero a video's anonymous contribution."
        ),
        "risks": (
            "- **Trimmed likes.** When the `max_likes` trim in `record_like` drops a like, the Engine keeps "
            "its `+1`. A later un-like finds nothing to remove and publishes nothing. This gap exists today, "
            "and the plan does not close it.\n"
            "- `like_generations` gains one row for each (profile, video) pair ever liked. It stays small. If "
            "a profile-deletion path exists, it should also remove that profile's rows; the build checks "
            "at Step 3.\n"
            "- Likes import (plan 14's path) also calls `record_like`. The new return value must not break "
            "that caller; import publishes nothing."
        ),
        "tradeoffs": (
            "Anonymous likes add at most +1 per video, permanently. Events stored before this change keep "
            "their random ids and are not backfilled."
        ),
    },
    {
        "nn": "14", "slug": "batch-like-resolution", "issue": "03-batch-like-resolution.md",
        "title": "Resolve a batch of browser likes with one Engine call and cap requests at 50 likes",
        "adr": "`docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`.",
        "wave": (
            "Wave 2, running alongside plan 13. It edits `client/backend/server.py` in four places: "
            "`MAX_CLIENT_LIKES` (`:49`), the `/recommendations` proxy trim (`:446`), likes import "
            "(`:837-843`) and the likes page (`:970-980`). Plan 15 runs afterwards and rewrites the 502 "
            "bodies this plan leaves in place."
        ),
        "approach": (
            "**Engine parser.** `/internal/videos/metadata` gets its own entry parser, which accepts "
            "`{video_id, instance_domain}` or `{video_uuid, instance_domain}`. An entry with both uses "
            "`video_id`. Malformed entries are skipped, and duplicates within each form are collapsed. "
            "`/internal/dislikes/centroids` keeps the existing `_parse_entries` "
            "(`handlers/internal_client_reads.py:20`), so it still accepts only ids.\n\n"
            "**Engine data.** A uuid-keyed batch lookup is added beside `fetch_metadata_by_ids` "
            "(`engine/server/data/metadata.py:110`). It uses a chunked `(video_uuid, instance_domain) "
            "IN (...)` query, following `fetch_seed_embeddings_for_likes` (`data/embeddings.py:191`), and "
            "applies the same error-count filter. The handler answers both forms under one `db_lock` hold, "
            "returns each video once, and orders rows by their first matching entry.\n\n"
            "**Client.** `resolve_videos_by_uuid_host` (`client/backend/lib/engine_api_client.py:136`) is "
            "removed. The likes page and likes import each make one `fetch_metadata_for_entries` call with "
            "the deduplicated uuid entries. Import records a like for each returned row and skips disliked "
            "videos, as it does today.\n\n"
            "**Cap.** `MAX_CLIENT_LIKES` goes from 200 to 50, and each of its three uses still drops the "
            "extra entries silently."
        ),
        "alternatives": (
            "- **A new `/internal/videos/resolve-batch` endpoint** (the audit's suggested fix). Rejected by "
            "ADR-0003: the metadata endpoint already returns what the likes page needs, so one call "
            "replaces both the resolve loop and the separate metadata call.\n"
            "- **An opt-in flag for uuid entries on the shared `_parse_entries`.** Viable, and the brief "
            "allows it. A separate parser is preferred so a wrong flag default can never widen what "
            "centroids accepts.\n"
            "- **Parallelising the per-like resolve calls.** Rejected: it still takes the lock N times."
        ),
        "risks": (
            "- **Accepted consequence (ADR-0003).** Import no longer imports videos at or over the Engine's "
            "error-count threshold, because the metadata endpoint filters them and resolve did not.\n"
            "- **Row order.** Metadata returns rows in first-entry order, so the likes page keeps the "
            "submitted order only if the handler preserves it across both lookup forms. The acceptance "
            "criteria require this explicitly.\n"
            "- **Callers.** The `/recommendations` proxy trim at `:446` and `_parse_client_likes` both read "
            "`MAX_CLIENT_LIKES`. Grep for any other reader at Step 3."
        ),
        "tradeoffs": "A request's likes beyond the first 50 are dropped silently, not rejected.",
    },
    {
        "nn": "15", "slug": "tighten-response-defaults", "issue": "04-tighten-response-defaults.md",
        "title": "Opt-in CORS by origin, fixed server-error bodies, and recommendations debug off by default",
        "adr": "`docs/project/adr/0004-cors-opt-in-by-origin.md`.",
        "wave": (
            "Wave 3: last, on main after plans 10-14 merge. It touches every 5xx/502 site, so it runs after "
            "the plans that change those sites. Plan 14 replaces the resolve calls, plan 11 adds to "
            "`internal_events.py`, and plans 11 and 12 edit `DEPLOYMENT.md` and `server_config.py`. It "
            "needs no worktree."
        ),
        "approach": (
            "**Client CORS.** `CLIENT_CORS_ORIGINS` is parsed once at startup into a set held on the server "
            "object. `respond_json`, `respond_bytes` and `respond_options` in "
            "`client/backend/lib/http_utils.py` read the request's `Origin` from the handler they are given. "
            "When the origin is in the set, they echo it with `Vary: Origin` and the existing allow-methods "
            "and allow-headers. Otherwise they send no `access-control-*` headers. Preflight returns 204 "
            "either way.\n\n"
            "**Engine CORS.** `engine/server/api/http_utils.py` removes the CORS headers from `respond_json` "
            "and `respond_options`.\n\n"
            "**Error bodies.** Every 5xx/502 site returns a fixed message naming the operation instead of "
            "exception text, and logs the exception with its traceback at error level. Any `code` field "
            "stays, and deliberate 4xx messages are unchanged. Plan 14 moves some sites, so Step 3 lists "
            "them again on the merged tree. The sites today are Client `server.py` 649-656, 718, 745, 843, "
            "905, 961, 980 and 1002, and Engine `internal_events.py:71` and `similar.py:1020-1024`.\n\n"
            "**Debug.** `RECOMMENDATIONS_DEBUG_ENABLED` in `server_config.py:370` derives from the env var "
            "`RECOMMENDATIONS_DEBUG` (`1`/`true`/`yes`, case-insensitive). The active-suite `engine` fixture "
            "(`tests/active/conftest.py:105`) adds `RECOMMENDATIONS_DEBUG=1` to its env.\n\n"
            "**Docs.** `DEPLOYMENT.md:408` replaces the quoted constant with the env var and documents "
            "`CLIENT_CORS_ORIGINS`."
        ),
        "alternatives": (
            "- **A single configured origin instead of a list.** Rejected by ADR-0004: a dev setup may use "
            "more than one Vite origin, and a list costs nothing extra.\n"
            "- **Keeping Engine CORS behind a flag.** Rejected by ADR-0004: the browser never reaches the "
            "Engine.\n"
            "- **Building this in wave 1 with the others.** Rejected: it edits the same lines as plans 13 "
            "and 14 at the Client's 502 sites and would have to be redone after they merge."
        ),
        "risks": (
            "- Tests that assert on error strings containing exception text will change. The Step 0 "
            "baseline on the merged main shows them.\n"
            "- Some 502 bodies embed `EngineApiError` text built from the Engine's error string. Meeting "
            "the \"no Engine error string in the Client body\" criterion therefore needs changes on both "
            "sides.\n"
            "- The Vite dev setup stops working until `CLIENT_CORS_ORIGINS` is set, as documented. Say "
            "this in the hand-off."
        ),
        "tradeoffs": "Cross-origin dev needs an env var, and error bodies lose their diagnostic text, which moves to the logs.",
    },
]


def brief(issue_file: str) -> str:
    text = (ISSUES / issue_file).read_text()
    m = re.search(r"^## Agent Brief\n(.*)\Z", text, re.S | re.M)
    assert m, issue_file
    return m.group(1).strip()


def summary(b: str) -> str:
    return re.search(r"^\*\*Summary:\*\* (.+)$", b, re.M).group(1).strip()


for p in PLANS_SPEC:
    b = brief(p["issue"])
    body = f"""# {p['title']}

## Requirements

### What was asked for

Build issue `docs/project/issues/{p['issue']}` as triaged: {summary(b)}. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

{p['adr']}

### Agent Brief

{b}

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

{BATCH}

{p['wave']}

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

{p['approach']}

### Alternatives considered

{p['alternatives']}

### Risks and limitations

{p['risks']}
{COMMON_RISKS}

### Tradeoffs accepted

{p['tradeoffs']}
"""
    out = PLANS / f"{p['nn']}-{p['slug']}.md"
    assert not out.exists(), out
    out.write_text(body)
    print(out, len(body.splitlines()), "lines")
