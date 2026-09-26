# Read-only comments under the video

Status: enhancement, needs-triage
Origin: task 4, [M2][F1]

## Problem

Comments are not displayed under the video.

## Proposed solution

The server or client requests comments from the source instance and renders them under the video description.

- Fetch via the instance API (or a server proxy) and render below the description block.
- Placeholder/loader, pagination and batch limits so the page is not overloaded.
- No comment input (view-only).
- First verify on a specific video which request fetches comments, and render from that response structure.

## Related

- Depends only on the comments enrichment of the dataset build; may land any time after it.

## Comments
