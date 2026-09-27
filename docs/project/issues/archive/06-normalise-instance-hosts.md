# Normalise instance host strings on the Python whitelist path

Status: bug, complete
Origin: task 86, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

`sync-whitelist.py` and `updater-worker.fetch_join_hosts` only `strip().lower()` host strings from the JoinPeerTube index, while the crawler parses them as URLs, so a host entry containing `/`, `?`, `#` or `@` reaches URL construction verbatim.

## Proposed solution

Apply the crawler's normalisation on the Python side.

1. Add a `normalize_host_token` helper on the Python side mirroring `host-filters.normalizeHostToken`, with a docstring.
2. Apply it in `engine/server/db/jobs/sync-whitelist.py` and in `updater-worker.fetch_join_hosts` before storing into `instances`.
3. Reject entries that do not reduce to a bare hostname.

## Comments

**Triage.** Confirmed against the code. `sync-whitelist.py`, `updater-worker.fetch_join_hosts` and the crawler (`instances-cli`) all read the same JoinPeerTube hosts list, `instances.joinpeertube.org/api/v1/instances/hosts?count=5000&healthy=true` by default. The crawler normalises each entry with `normalizeHostToken`; both Python paths only `strip().lower()`. So one entry can be stored under two spellings. The updater compares these strings against the hosts already in the database and against the denylist, so a mismatch gives wrong new/stale sets and missed denylist matches. The purpose of this issue is that both sides produce the same string for the same entry.

Decision (maintainer): the Python helper mirrors `normalizeHostToken` exactly, as the issue proposes. An entry it maps to None is not stored, which is step 3. No additional validation beyond what `normalizeHostToken` does. The existing lenient `data.moderation.normalize_host` used for operator denylist input is a separate function and stays as it is. No existing implementation, no prior rejection.

**Delivered** by `docs/project/plans/archive/10-normalise-instance-hosts.md` (build plan `docs/project/plans/16-10-normalise-instance-hosts.md`).
- The helper is `normalize_host_token` in `engine/server/data/moderation.py`, directly after the unchanged `normalize_host`. Its private `_whatwg_hostname` gives the WHATWG `URL.hostname` for the URL branches through stdlib `urlparse`, `ipaddress` and the `idna` codec. `fetch_hosts` in `sync-whitelist.py` and `fetch_join_hosts` in `updater-worker.py` call it in place of `strip().lower()` and skip entries it maps to None.
- Durable test: `tests/active/test_host_normalisation.py`, over the fixture `tests/active/host_tokens.json`. The fixture holds the 14 inputs above plus `"https://tube.example./"` → `"tube.example."`. The same file runs the crawler's compiled `engine/crawler/dist/host-filters.js` under node over that fixture.
- A missing node, dist or git fails the crawler check; it never skips. Dist counts as stale when `src/host-filters.ts` has a later git commit time than it. When either file is dirty or has no commit, file mtimes are compared instead.
- Not yet run: `test-moderation-integration.py`, `test-orchestrator-smoke.py`, and the full `validate_tests.py` comparison with the green baseline. The last acceptance criterion stays open until they pass.
- Accepted limitations:
  - An entry with no scheme and no `/` only has dots trimmed, so `@`, `?`, `#` and a port stay in the stored host.
  - Parity is proven only for the fixture inputs, and only on the Python interpreter that runs the test. The `rat-tail` comment in `_whatwg_hostname` records that `urlparse` accepts forbidden host code points WHATWG rejects. Python's IDNA 2003 codec and WHATWG's UTS #46 can also differ, for example on `ß`.
  - `compare-join-hosts.py` still uses `strip().lower()`.
  - The crawler's `--whitelist-file` read-back (`loadHostsFromFile`) sends bare hosts through branch 4, which strips the trailing dot that a URL-form entry such as `https://tube.example./` keeps.
  - `normalize_host`, used for denylist input, neither brackets IPv6 nor converts to punycode, so a denylist entry for such a host may not match the stored spelling.
  - Rows already in `instances` are not rewritten.

## Agent Brief

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
- [x] A table-driven Python test asserts `normalize_host_token` output for at least these inputs, with the expected value being what `normalizeHostToken` returns: `" Tube.Example "`, `"tube.example."`, `"..tube.example.."`, `"https://Tube.Example/"`, `"http://tube.example:8080/path"`, `"https://user@tube.example"`, `"tube.example/videos"`, `"tube.example:9000"`, `"https://[::1]:8080/"`, `"https://bücher.example/"`, `""`, `"   "`, `"."`, `"https://"`.
- [x] The same inputs and expected values are checked against the TypeScript `normalizeHostToken` (a crawler unit test or a fixture both sides read), so the two implementations cannot drift unnoticed.
- [x] The whitelist sync job, given a hosts payload containing `"https://Tube.Example/"` and `"tube.example"`, stores the single host `tube.example`.
- [x] Entries for which the helper returns None are not stored by either job, and the job still completes.
- [x] The updater's join-hosts set for the same payload equals the set the sync job stores.
- [ ] Existing moderation-integration and orchestrator smoke tests pass.

**Out of scope:**
- Changing `normalizeHostToken` or any crawler behaviour.
- Any validation stricter than `normalizeHostToken` (IP literals, ports, userinfo, characters).
- Rewriting host rows already stored in `instances`.
- `data.moderation.normalize_host` and the denylist/moderation CLIs.
- `compare-join-hosts.py`.
