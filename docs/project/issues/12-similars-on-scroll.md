# Similars on scroll

Status: enhancement, needs-triage
Origin: task 2, [M2][F1]

## Problem

Only 8 similar videos are shown; users want to see more.

## Proposed solution

Remove the separate "similar videos" page and load similars directly on the video page, like the home page: the server returns N similars and the client renders them progressively on scroll.

- The server returns a full batch of similars at once (e.g. `BATCH_SIZE = 48`) in a single response.
- The client keeps the batch in memory and reveals it in chunks as the user nears the bottom.

## Related

- After `09-similars-diversity` and `11-fast-similars-response`.

## Comments
