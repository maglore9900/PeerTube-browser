# Fast response with similars on the video page

Status: enhancement, needs-triage
Origin: task 1, [M2][F1]

## Problem

Until the server receives a response from the source instance, the client shows an empty page; some instances respond slowly.

## Proposed solution

Show similar videos first (fast, from the local DB), then load the current video's metadata when it arrives.

- Opening the video page starts two independent requests in parallel: similars, and metadata for the current video.
- The server answers the similars request immediately from local cache/DB, without waiting for the instance.
- Metadata refresh goes through a separate request to the instance, is saved to the DB, and updates the UI.

## Related

- After `09-similars-diversity`; before `12-similars-on-scroll`.

## Comments
