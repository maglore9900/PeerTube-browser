# Resolve a translatable video in one place

Status: enhancement, wontfix
Origin: architecture review `.scratch/architecture-review-20261004-0901.md`, candidate "one resolve translatable video function" (Speculative)

## Problem

The whitelist row lookup and the active-denylist check are written twice:

- **Route:** `_resolve_translate_key` (`engine/server/api/handlers/internal_translate.py:246-274`).
  - Runs `resolve_video_row`.
  - Then runs `list_active_denied_hosts` under `server.db_lock`.
  - Reads the error threshold from `server.video_error_threshold` (`engine/server/api/handlers/video.py:281`).
  - Writes the 400 or 404 response itself, so the worker cannot reuse it.
- **Worker:** `resolve_video` (`engine/server/db/jobs/translate-worker.py:100-123`).
  - Runs `fetch_video_row`.
  - Then the same denylist check.
  - Then a duration bound.
  - Takes the threshold from `VIDEO_ERROR_THRESHOLD`.
  - Sets `busy_timeout` inline.
  - Notes a pitfall in a comment: `fetch_video_row` with a `None` host matches the id on any host.

The page's enqueue and the worker's claim can therefore drift apart.

## Proposed solution

Write one function that takes a connection and returns a row or a refusal. The HTTP mapping stays in the route. It is small, and probably best done as part of issue 54.

## Related

- Issue 54 (translate job handle).
- `docs/project/issues/archive/45-translate-worker-whitelist-locked-at-claim.md`.

## Comments

**Triage (2026-10-04).** Closed as `wontfix` because this work is folded into issue 54 (`docs/project/issues/54-translate-job-handle.md`), not because it was rejected. Issue 54's agent brief takes this issue's proposal in full, under "Resolve a translatable video (from issue 57)". One function takes a whitelist connection, id, normalised host and error threshold, and returns a row or a refusal. The route keeps its HTTP mapping, and the worker keeps its duration bound. A missing host is refused. Nothing was written to `docs/project/rejected/`.
