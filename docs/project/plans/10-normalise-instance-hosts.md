# Normalise JoinPeerTube host entries on the Python side

## Requirements

### What was asked for

Build issue `docs/project/issues/06-normalise-instance-hosts.md` as triaged: Normalise JoinPeerTube host entries on the Python side with an exact port of the crawler's `normalizeHostToken`. The Agent Brief below, copied from the issue, is the confirmed requirement set; the build starts from this file.

### Purpose

Close the security-audit finding the issue records. This build is one of issues 01-06, delivered concurrently to use as little operator time and cause as few merge conflicts as possible.

### Decisions this rests on

No ADR. The decision is recorded in the issue's triage comment: an exact port, with no extra validation.

### Agent Brief

**Category:** bug
**Summary:** Normalise JoinPeerTube host entries on the Python side with an exact port of the crawler's `normalizeHostToken`

**Current behavior:**
Three components read the same JoinPeerTube hosts list: the whitelist sync job, the updater worker's join-hosts fetch, and the TypeScript crawler. The crawler passes every entry through `normalizeHostToken` and skips entries that normalise to nothing. The two Python readers only trim and lowercase, so an entry such as `https://Tube.Example/` or `tube.example.` is stored as one string by the crawler and another by the Python jobs. The updater's comparisons (JoinPeerTube hosts vs hosts already in the database, and vs the instance denylist) then treat one instance as two, or miss a denylist match.

**Desired behavior:**
A Python function `normalize_host_token(value: str) -> str | None`, with a docstring, returns exactly what the crawler's `normalizeHostToken` returns for the same input:
1. Trim surrounding whitespace and lowercase. If the result is empty, return None.
2. If it starts with `http://` or `https://`: parse it as a URL and return its hostname, lowercased. Return None if the hostname is empty or parsing fails.
3. Else, if it contains `/`: parse `https://` + value as a URL and return its hostname, lowercased. Return None if the hostname is empty or parsing fails.
4. Else: return the value with all leading and trailing `.` removed, or None if that leaves nothing.

The whitelist sync job and the updater's join-hosts fetch both apply it to every entry, and skip entries that return None. Where the Python and WHATWG URL parsers differ on hostname extraction, the Python port matches the crawler. At minimum that covers userinfo (`user@host`), explicit ports, IPv6 literals (the crawler's hostname keeps the brackets), and internationalised names (the crawler returns punycode).

**Key interfaces:**
- New `normalize_host_token()` in a Python module importable by both jobs (the Engine server's shared `data` package already serves the jobs).
- The whitelist sync job's host fetch (currently `fetch_hosts`) and the updater's `fetch_join_hosts()`: use it in place of `strip().lower()`.
- The crawler's `normalizeHostToken()` in its host-filters module is the reference and is **not** changed.

**Acceptance criteria:**
- [ ] A table-driven Python test asserts `normalize_host_token` output for at least these inputs, with the expected value being what `normalizeHostToken` returns: `" Tube.Example "`, `"tube.example."`, `"..tube.example.."`, `"https://Tube.Example/"`, `"http://tube.example:8080/path"`, `"https://user@tube.example"`, `"tube.example/videos"`, `"tube.example:9000"`, `"https://[::1]:8080/"`, `"https://bücher.example/"`, `""`, `"   "`, `"."`, `"https://"`.
- [ ] The same inputs and expected values are checked against the TypeScript `normalizeHostToken` (a crawler unit test or a fixture both sides read), so the two implementations cannot drift unnoticed.
- [ ] The whitelist sync job, given a hosts payload containing `"https://Tube.Example/"` and `"tube.example"`, stores the single host `tube.example`.
- [ ] Entries for which the helper returns None are not stored by either job, and the job still completes.
- [ ] The updater's join-hosts set for the same payload equals the set the sync job stores.
- [ ] Existing moderation-integration and orchestrator smoke tests pass.

**Out of scope:**
- Changing `normalizeHostToken` or any crawler behaviour.
- Any validation stricter than `normalizeHostToken` (IP literals, ports, userinfo, characters).
- Rewriting host rows already stored in `instances`.
- `data.moderation.normalize_host` and the denylist/moderation CLIs.
- `compare-join-hosts.py`.

### Consistency constraints

- Match the surrounding code's style: stdlib HTTP handlers, `respond_json`, module-level named constants, and env vars read once at startup.
- Backwards compatibility is not required beyond what the brief states.
- Run `validate_tests.py` from the root of the tree this build runs in (a worktree for waves 1-2, main for wave 3). That tree's `.un` config carries it as `project_dir`.

### Batch context

Part of the security hardening batch (`.scratch/security-hardening-batch/notes.md`): issues 01-06 delivered in three waves of git worktrees. Wave 1 is plans 10, 11 and 12. Wave 2 is 13 and 14, branched from main after wave 1 merges. Wave 3 is 15, on the merged main. A wave 1 or 2 build runs in its own worktree created by `.scratch/security-hardening-batch/worktree-setup.sh`, merges to main when it closes, and is harvested on main, not in the worktree.

Wave 1. It touches no file that another batch issue touches.

### Conflicts

The brief does not conflict with the tree. Every function and line it names was checked against the source on 2026-09-26 (`.scratch/security-hardening-batch/notes.md`, File overlap). Line numbers will drift once earlier waves merge, so re-locate by function name at Step 3.

## High-level plan

### Approach

Add `normalize_host_token()` to a module in the Engine's shared `engine/server/data` package, which both jobs already import. It follows the brief's four numbered rules and uses `urllib.parse` to extract the hostname. Where that differs from WHATWG `URL`, it handles the case explicitly: userinfo is stripped, the port is stripped, IPv6 literals keep their brackets, and internationalised names are encoded to punycode (IDNA). `fetch_hosts` in `sync-whitelist.py` and `fetch_join_hosts` in `updater-worker.py` call it in place of `strip().lower()` and skip entries that return None.

Drift protection: one JSON fixture of `input -> expected` pairs covers every input the brief lists. The Python test checks `normalize_host_token` against the fixture. The same test then runs Node on the crawler's compiled `engine/crawler/dist/host-filters.js` over the same inputs and asserts identical output. The expected values are therefore the crawler's own, and the two sides cannot drift unnoticed.

### Alternatives considered

- **A crawler-side test runner** (vitest or node:test in `engine/crawler`) reading the fixture. Rejected: the crawler has no test script or runner today (`engine/crawler/package.json`), and one Python test that invokes Node covers both sides from the suite that already runs.
- **Hand-written expected values without running the TS side.** Rejected: that tests Python against the author's reading of WHATWG, which is where drift hides.
- **Reusing `data.moderation.normalize_host`.** Rejected by the triage decision: it is the lenient normaliser for operator input and stays separate.

### Risks and limitations

- `dist/host-filters.js` must exist and match `src/`. When `dist` is missing or older than `src`, the test must fail loudly rather than skip, or it runs `npm run build` first. The build chooses which at its checkpoint.
- `urllib.parse` and WHATWG differ on edge inputs beyond the listed set (for example percent-encoding and backslashes). Only the listed inputs are pinned; others may differ. The fixture can grow to cover them later.
- Hosts already stored under the old spelling are not rewritten (out of scope), so one updater run after the change may treat the old and new spellings as different hosts.
- **Shared `whitelist.db`.** The worktree symlinks the main tree's `whitelist.db`, so this build's test Engines write interaction rows into the same file as other lanes, and as the live Engine if it runs. Every test run already does this; worktrees only make it concurrent.
- **Tracked test record.** `tests/last_test_validation.json` and `tests/last_test_output.txt` always conflict on merge. Take main's copy and re-run `validate_tests.py --compare` on the merged tree.
- **Engine rate limit.** Run Engine-backed test files in their own `validate_tests.py` invocations (memory `engine-rate-limit-single-lane-test-runs`).

### Tradeoffs accepted

A Python test depends on Node and on the crawler's compiled output being present.
