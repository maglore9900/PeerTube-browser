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

- **Absorbed into the likes and dislikes feature.** The server half is `docs/project/plans/03-like-dislike.md`: `undo_like` on `POST /api/user-action` removes one like from the profile's `users.db` store, and `GET /api/profile/reaction` reads a video's like state. The UI half, un-like on the video page and a remove control per card in the My likes modal, is `docs/project/plans/08-likes-dislikes-frontend.md` (L4, L7). This issue closes when plan 08 is delivered.

## Comments

- Plan 03 build, Step 1: the operator absorbed this issue in full (Q6 "full"). No separate implementation is to be built from it.
- Delivered by `docs/project/plans/08-likes-dislikes-frontend.md`: the video page un-likes an active like (`undo_like`, and `localLikes:v1` without a key), and each My likes card has a Remove control that does the same.
