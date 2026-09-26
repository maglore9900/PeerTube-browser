# Normalise instance host strings on the Python whitelist path

Status: bug, ready-for-agent
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
