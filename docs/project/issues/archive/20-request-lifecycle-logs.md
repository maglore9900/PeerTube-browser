# Request lifecycle logs with a shared request_id

Status: enhancement, complete
Origin: task 38, [M7][F4]

## Problem

Logs are hard to correlate: access logs are emitted on response write, while business logs (`[similar-server]`, `[recommendations]`) are produced during processing and interleave across threads.

## Proposed solution

A per-request lifecycle log (`start` -> work logs -> `end`) and one shared `request_id` propagated through handler and recommendation logs.

- Keep two logs: nginx access log (client/network view) and the app log (internal processing).
- One `request_id` appears in both; nginx forwards `X-Request-ID` (or generates it), the app reads and reuses it.
- Set a request-scoped `request_id` at the start of every API request (`do_GET`/`do_POST`) before business logic.
- Emit `request-start` first with `request_id`, client IP, method, full URL, optional user-agent.
- Reuse the same `request_id` in all downstream request-path logs.
- Emit `request-end` with `request_id`, status, `duration_ms`; bytes stay nginx's responsibility.
- Remove ad-hoc per-handler random ids that conflict with the shared context.
- Ordering guaranteed per request under threaded serving, not globally.

## Validation (from the original task)

- Smoke test on `/api/similar`, `/api/video`, `/api/health`: `start -> ... -> end` with the same `request_id`.
- No request is logged without a `request_id`.
- A runbook comparing one request across both logs by `request_id`.

## Related

- After `19-timestamped-request-logs`; before `21-static-page-visit-logs`.
- Keep `X-Request-ID` forwarding compatible with the blue/green scripts in `26-zero-downtime-deploy`.

## Comments

- Delivered by `docs/project/plans/21-20-request-lifecycle-logs.md`. The Engine and the Client backend each log one `request.start` "request started" (`ip`, `method`, `url`, `user_agent` when the header is non-empty) as the first record of every `GET`/`POST`/`OPTIONS` request, and one `request.end` "request finished" (`status` sent, or `-`, and integer `duration_ms`, no bytes) as the last. These replace the Engine's `access.start` / `access` and the Client's `client.access` lines. http.server's own errors (bad request line, unsupported method, timeout) log one WARNING `http` (Engine) or `client.http` (Client) record carrying `peer`. Every record between start and end carries `request_id`: the incoming `X-Request-ID` when it fully matches `[A-Za-z0-9._-]{1,64}`, otherwise a generated `uuid4().hex`, and the `[similar-server][<id>]` prefix holds that same id. Public nginx sets `X-Request-ID` to its `$request_id` and logs it, and the Client sends the id on every Engine call. For the runbook that follows one id across the logs, see `DEPLOYMENT.md`. The logging tests retired by the event rename are replaced under `docs/project/issues/39-logging-tests-retired-by-request-lifecycle-rename.md`.
