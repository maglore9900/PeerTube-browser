# Say "no speech" instead of "failed" when a video has no speech

Status: enhancement, needs-triage
Origin: operator report, 2026-10-14 (translate debugging session)

## Problem

When the translate worker finds no speech in a video, the page says "Translation failed for this video." That reads as a fault, but nothing went wrong: the video is music, or has no speech at all.

`translate_audio` in `engine/server/db/jobs/translate-worker.py` raises `JobFailed("no speech detected")` when Silero VAD finds no speech in any window, or when no chunk yields a cue. `run_job` stores that as `failed` with the error text. The Engine state route (`engine/server/api/handlers/internal_translate.py`) answers `failed` and never exposes the error. The page (`client/frontend/src/pages/video-page/translate.ts`) maps `failed` to `ENDED_LABELS.failed`.

Language detection runs only on the first chunk that has speech, so a music-only video never reaches the `already_english` check, even when the uploader tagged it `en`.

On 2026-10-14, five rows in `subtitles.db` were `failed` with `no speech detected`, all short music videos:
- fediverse.tv 7ce990f6
- v.basspistol.org 655a7a8e
- video.tedomum.net 6acfcffb
- blurt.media 61705ca1
- tube.xy-space.de bdb642e9 (seen in the worker log)

## Proposed solution

Add a `no_speech` end state, shown as "No speech was found in this video." Like `failed` and `already_english`, it ends the page's poll.

Places that change:
- The worker writes `no_speech`, not `failed`, for `no speech detected`. `no audio decoded` stays `failed`, since that is a decode fault.
- `engine/server/data/subtitles.py` gets a job-handle end write for `no_speech`.
- The Engine state route treats `no_speech` like `failed` and `already_english`: it still tries the instance's own English track, and a track it finds is stored ready over the row. The cancel route answers it as stored.
- `client/backend/lib/engine_api_client.py` adds it to `TRANSLATE_STATES`.
- `client/frontend/src/data/translate.ts` accepts it in the parser and in `CANCEL_STATES`.
- `client/frontend/src/pages/video-page/translate.ts` adds it to `ENDED_LABELS`.
- `tests/active/fixtures/translate_contract.json` adds it to the shared contract.
- Docs: `engine/server/db/jobs/docs/TRANSLATE_WORKER.md` (end states and error texts), `CONTEXT.md`, and the Engine and Client READMEs.

Existing `failed` rows with `no speech detected` stay `failed` unless they are converted or deleted once the change lands. Decide which in planning.

Out of scope: using the uploader's language tag to decide `already_english`. The operator did not choose it.

## Related

- `docs/project/issues/archive/55-translate-state-contract.md`: the state contract this extends.
- `docs/project/issues/archive/56-split-translate-worker.md`: the worker's end states.

## Comments
