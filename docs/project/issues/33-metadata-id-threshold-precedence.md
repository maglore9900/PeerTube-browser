# The id metadata lookup applies the error threshold to one pair per chunk

Status: bug, ready-for-agent
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

### Triage

**Established:**

- **Reproduced through the real function on the live `whitelist.db` (read-only).** No embedded video is at `error_count ≥ 3` today, so the probe used threshold 1:
  - `fetch_metadata_by_ids([err, err, err, ok], error_threshold=1)` returned 4 rows, where 1 is correct.
  - `[ok, err, err, err]` returned 3 rows: only the last errored pair was dropped.
  - `[err]` on its own returned 0 rows.
- **Impact on the current dataset: none yet.** Error counts on embedded videos are 0 for 884,469 videos, 1 for 5,578 and 2 for 5. `VIDEO_ERROR_THRESHOLD` is 3 (now `server_config.py:412`), so nothing is filtered on either path today. The first video to reach 3 errors will leak into similar and up-next lists unless it happens to be the last pair of its chunk.
- **No standing decision keeps the quirk.** Build 16-14 kept it only to meet that build's own "id callers see the same rows" requirement (Open item A, option 1). No ADR or `docs/project/rejected/` entry covers it.
- **Maintainer decision:** fix it. Id callers, similar and up-next included, drop errored videos wherever they sit in a chunk, and the lists may come back shorter once videos reach the threshold. No shrinkage measurement is required.

## Agent Brief

**Category:** bug
**Summary:** The id-keyed metadata lookup must apply the error-count threshold to every requested pair, not only to the last pair of each chunk.

**Current behavior:**
`fetch_metadata_by_ids` builds each chunk's WHERE as an OR of `(video_id = ? AND instance_domain = ?)` pairs and hands it to the shared metadata SELECT without parentheses. The SELECT appends `AND (error_count IS NULL OR error_count < ?)`. Because AND binds tighter than OR, the threshold only filters the last pair of each chunk, and every other errored video in the chunk is returned. The uuid-keyed sibling, `fetch_metadata_by_uuids`, wraps its conditions and filters correctly. A code comment beside the id lookup describes the unparenthesised form as deliberate. The active suite's metadata test documents the gap as a known limitation and leaves the errored video on the id path unasserted.

**Desired behavior:**
- With a threshold greater than 0, `fetch_metadata_by_ids` omits every video whose `error_count` is at or over the threshold, wherever its pair sits in the request or chunk. It returns every other matching video unchanged: same row dict, same `video_id::instance_domain` key.
- With no threshold (None or ≤ 0), it returns what it returns today.
- The comment that calls the unparenthesised form deliberate is gone. The test module's known-limitation paragraph is gone too, and its chunk-boundary test asserts the errored video's absence on the id path as it already does on the uuid path.

**Key interfaces:**
- `fetch_metadata_by_ids(conn, entries, error_threshold=None) -> dict[str, dict]`: same signature, keys and row shape. Only the filtering changes.
- The shared metadata SELECT helper used by both lookups: no change is needed if the id caller passes its conditions wrapped, as the uuid caller does.
- Callers that change behaviour, with no code change needed: the similar/up-next candidate row builder, and `/internal/videos/metadata` with id-form entries.

**Acceptance criteria:**
- [ ] At threshold 3, a request of several id pairs where an errored video (`error_count` ≥ 3) is **not** the last pair of its chunk returns no row for that video, and returns every healthy requested video.
- [ ] That holds across the 450-pair chunk boundary: the active suite's chunk-boundary test asserts the errored video in the second chunk is absent from the id lookup's result, and every healthy video is present.
- [ ] A video with `error_count` NULL, or below the threshold, is still returned.
- [ ] With `error_threshold=None`, the errored video is returned.
- [ ] The uuid lookup's existing tests still pass unchanged.
- [ ] No comment or test docstring still describes the id path's threshold as applying to one pair per chunk.
- [ ] The Engine README's `/internal/videos/metadata` entry says both entry forms leave out videos at or over the error-count threshold. Today it says the id form filters only the last pair of each chunk.

**Out of scope:**
- Changing `VIDEO_ERROR_THRESHOLD` or how `error_count` is incremented.
- The rowid-keyed `fetch_metadata`, which filters correctly already.
- Refilling similar or up-next lists that come back shorter (issue 09 covers pool size).
- Merging the id and uuid lookups into one code path.
