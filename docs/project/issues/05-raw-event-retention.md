# Retention for raw interaction events and bounded like expansion

Status: bug, needs-triage
Origin: task 85, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

`interaction_raw_events` has no retention policy, and `_resolve_client_likes` builds one `OR` term per submitted like with no cap on the similar endpoint.

## Proposed solution

Prune old rows and cap the expansion.

1. Add a retention window and a pruning step for `interaction_raw_events` in the existing maintenance/updater path.
2. Cap the number of likes expanded in `_resolve_client_likes` (`engine/server/api/handlers/similar.py`) at the same limit the recommendations path uses.

## Comments
