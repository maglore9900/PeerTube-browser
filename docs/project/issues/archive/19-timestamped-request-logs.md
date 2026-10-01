# Timestamped request logs

Status: enhancement, complete
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

- Delivered by `docs/project/plans/20-19-timestamped-request-logs.md`. Both the Engine and the Client backend stamp every record's `ts` as UTC `YYYY-MM-DDTHH:MM:SS.mmmZ` from the record's creation time, and `LOG_FORMAT=text` selects one escaped plain-text line per record (see `DEPLOYMENT.md` section 2). By operator decision the default is JSON, not the plain text this issue proposed, because `engine/watch-engine-logs.sh`, `client/watch-client-logs.sh` and the DEPLOYMENT.md runbooks read the JSON.
