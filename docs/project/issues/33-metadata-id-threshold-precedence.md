# The id metadata lookup applies the error threshold to one pair per chunk

Status: bug, needs-triage
Origin: build `16-14-batch-like-resolution`, where it was recorded as "Open item A" and deliberately left alone (option 1). Harvest 14 left it unasserted in `tests/active/test_metadata.py`.

## Problem

`fetch_metadata_by_ids` (`engine/server/data/metadata.py:110`) is meant to exclude every video whose `error_count` is at or over the Engine's error threshold. For a batch of more than one entry, it excludes an errored video only when that video is the last pair of its 450-entry chunk.

The function joins the chunk's pairs with a bare `OR` (`metadata.py:121-123`) and passes the result to `_select_metadata` unparenthesised (`metadata.py:128`). `_select_metadata` renders `WHERE {conditions} {error_clause}` (`metadata.py:212-213`), so the query reads:

```sql
WHERE (v.video_id = ? AND v.instance_domain = ?) OR ... OR (v.video_id = ? AND v.instance_domain = ?)
  AND (v.error_count IS NULL OR v.error_count < ?)
```

`AND` binds tighter than `OR`, so the threshold attaches to the final pair alone. Every other pair in the chunk matches whatever its `error_count`.

The uuid lookup beside it, `fetch_metadata_by_uuids`, wraps its conditions in parentheses (`metadata.py:155`) and filters correctly. The comment at `metadata.py:120` records that the id path is left unparenthesised on purpose.

## Impact

`VIDEO_ERROR_THRESHOLD` is 3 by default (`engine/server/api/server_config.py:387`), so the filter is on in every deployment. It is meant to keep videos the crawler repeatedly failed to reach out of what visitors see. Callers that pass more than one id entry:

- `engine/server/data/similarity_candidates.py:170-179` resolves cached and ANN similar-video candidates into rows. Errored videos can therefore appear in similar and up-next lists, except where one happens to be the last pair of its chunk.
- `/internal/videos/metadata` with id-form entries (`engine/server/api/handlers/internal_client_reads.py:157`). The Client's current id-form call (the block lookup, `client/backend/server.py:954`) sends one entry, where the single pair is also the last and the filter works.

Not measured: how often an errored video actually reaches a similar list on the current dataset.

## Observed

- `tests/active/test_metadata.py::test_both_lookups_return_every_healthy_video_across_the_450_entry_chunk_boundary` builds 460 videos with one errored video (`c455`, in the second chunk and not its last pair). At threshold 3, the uuid lookup drops it. The test does not assert the id lookup's result for `c455`, because under today's precedence the id lookup returns it.
- Build 16-14's working file (`docs/project/plans/archive/16-14-batch-like-resolution.md`, "Open item A") calls this "a live pre-existing bug on the id path". It was kept so that plan 14's requirement "id callers see exactly the rows they saw before" held.

## Candidate fix (not chosen)

- Parenthesise the id conditions as the uuid path does: pass `f"({conditions})"` at `metadata.py:128` and drop the comment at `:120`.
- Then assert in the chunk-boundary test that `c452` is present and `c455` is absent on the id path too, and remove the known-limitation paragraph from `test_metadata.py`'s module docstring.
- This changes what id callers receive: errored videos stop appearing in similar and up-next candidates, so those lists can come back shorter.

## Related

- ADR-0003 (`docs/project/adr/0003-metadata-endpoint-accepts-uuid-entries.md`), which added the uuid path that filters correctly.
- Issue 09 (`09-similars-diversity.md`), on similar pools being small, which a stricter filter would shrink further.

## Comments
