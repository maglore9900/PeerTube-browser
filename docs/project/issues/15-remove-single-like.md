# Remove a single like (UI + API)

Status: enhancement, needs-triage
Origin: task 9b, [M2][F1]

## Problem

Users can only reset all likes; they cannot remove a single one.

## Proposed solution

Let the user remove a like from the list (in the My likes modal) and/or by un-liking on the video page.

- UI: a remove button on each like card in the modal.
- Video page: un-like when the video was liked.
- Client: remove the entry from `localStorage` (uuid/host).
- Server: a dedicated endpoint (or an extension of `/user-profile/reset`) to delete a single like from the users DB.

## Related

- **Overlaps `docs/project/plans/03-like-dislike.md` S4 (un-like) directly.** Decide first whether this issue is absorbed into that plan or that plan's un-like half defers to this issue; shipping both produces two implementations of the same button.

## Comments
