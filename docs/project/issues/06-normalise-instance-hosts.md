# Normalise instance host strings on the Python whitelist path

Status: bug, needs-triage
Origin: task 86, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

`sync-whitelist.py` and `updater-worker.fetch_join_hosts` only `strip().lower()` host strings from the JoinPeerTube index, while the crawler parses them as URLs, so a host entry containing `/`, `?`, `#` or `@` reaches URL construction verbatim.

## Proposed solution

Apply the crawler's normalisation on the Python side.

1. Add a `normalize_host_token` helper on the Python side mirroring `host-filters.normalizeHostToken`, with a docstring.
2. Apply it in `engine/server/db/jobs/sync-whitelist.py` and in `updater-worker.fetch_join_hosts` before storing into `instances`.
3. Reject entries that do not reduce to a bare hostname.

## Comments
