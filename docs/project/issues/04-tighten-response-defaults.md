# Tighten Client and Engine response defaults

Status: bug, needs-triage
Origin: task 84, SI4-M1 — hardening notes from security audit runs 1-2

## Problem

The Client backend sends `access-control-allow-origin: *` on write endpoints, both services return raw exception text to callers, and `RECOMMENDATIONS_DEBUG_ENABLED` defaults to `True`.

## Proposed solution

Correct the three defaults.

1. Replace the wildcard CORS value in `client/backend/lib/http_utils.py` with a configured allowed origin.
2. Log the exception and return a generic message in the Engine error path in `engine/server/api/handlers/similar.py` and the Client error path in `client/backend/server.py`.
3. Set `RECOMMENDATIONS_DEBUG_ENABLED = False` by default in `engine/server/api/server_config.py` (and update the value `DEPLOYMENT.md` quotes).

## Comments
