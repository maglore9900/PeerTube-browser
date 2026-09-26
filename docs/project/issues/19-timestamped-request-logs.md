# Timestamped request logs

Status: enhancement, needs-triage
Origin: task 41, [M7][F4]

## Problem

Request timing analysis is harder when logs rely only on the journal envelope time or inconsistent message formatting.

## Proposed solution

An explicit timestamp in the application log format and in request lifecycle logs.

- Logging format with an explicit timestamp (ISO-8601 with milliseconds, UTC).
- Request lifecycle logs and internal server logs share that format.
- Optional structured output config (plain text default, JSON optional).
- Compatible with journald (no duplicate parsing assumptions).

## Validation (from the original task)

- Sample log lines include full date/time and a timezone marker.
- Ordering across request-start/work/request-end uses the application timestamp.

## Related

- First of the logging chain: this, then `20-request-lifecycle-logs`, then `21-static-page-visit-logs`.

## Comments
